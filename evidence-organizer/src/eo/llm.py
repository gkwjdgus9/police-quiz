"""로컬 LLM 클라이언트 (2단계).

- OllamaClient: localhost 의 Ollama 에만 붙는다. 호스트가 루프백이 아니면 생성 단계에서 거부한다(외부 API 금지 원칙).
- FakeLLM: 테스트용. 프롬프트에 박힌 task 태그별로 미리 정한 응답을 돌려준다.
- 모든 호출은 out/llm_log.jsonl 에 프롬프트·응답을 그대로 남겨 나중에 사람이 검증할 수 있게 한다.

LLM 의 답은 전부 '제안'이다. 호출하는 쪽(roles.py, narrative.py)이 인용을 검증하고, 통과 못 하면 버린다.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from eo.schema import KST

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b"  # 한국어가 되는 소형 모델이면 무엇이든. 실행 시 --model 로 바꾼다.


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    name: str

    def complete_json(self, *, system: str, prompt: str, task: str) -> dict[str, Any]: ...


def _assert_loopback(url: str) -> None:
    host = urlparse(url).hostname or ""
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise LLMError(f"로컬(루프백) 주소만 허용합니다: {url}")


@dataclass
class CallLog:
    """호출 기록기. path 가 None 이면 메모리에만 쌓는다."""

    path: Path | None = None
    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(self, *, client: str, model: str, task: str, system: str, prompt: str, response: str, ok: bool, error: str = "") -> None:
        entry = {
            "ts": datetime.now(KST).isoformat(),
            "client": client, "model": model, "task": task,
            "system": system, "prompt": prompt, "response": response, "ok": ok, "error": error,
        }
        self.entries.append(entry)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _parse_json_object(text: str) -> dict[str, Any]:
    """모델이 JSON 앞뒤에 군말을 붙여도 첫 번째 { ... } 객체만 꺼낸다."""
    text = text.strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise LLMError("응답에 JSON 객체가 없습니다")
        try:
            obj = json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            raise LLMError(f"JSON 해석 실패: {e}") from e
    if not isinstance(obj, dict):
        raise LLMError("JSON 객체가 아닙니다")
    return obj


class OllamaClient:
    name = "ollama"

    def __init__(self, *, url: str = DEFAULT_OLLAMA_URL, model: str = DEFAULT_MODEL, timeout: float = 120.0, log: CallLog | None = None, temperature: float = 0.0):
        _assert_loopback(url)
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.log = log or CallLog()
        self.temperature = temperature

    def is_available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=3) as r:
                tags = json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            return False
        names = {m.get("name", "") for m in tags.get("models", [])}
        return self.model in names or any(n.split(":")[0] == self.model.split(":")[0] for n in names)

    def complete_json(self, *, system: str, prompt: str, task: str) -> dict[str, Any]:
        body = json.dumps({
            "model": self.model,
            "system": system,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": self.temperature, "seed": 0},
        }).encode("utf-8")
        req = urllib.request.Request(f"{self.url}/api/generate", data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = json.loads(r.read().decode("utf-8")).get("response", "")
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.log.record(client=self.name, model=self.model, task=task, system=system, prompt=prompt, response="", ok=False, error=str(e))
            raise LLMError(f"Ollama 호출 실패: {e}") from e
        try:
            obj = _parse_json_object(raw)
        except LLMError as e:
            self.log.record(client=self.name, model=self.model, task=task, system=system, prompt=prompt, response=raw, ok=False, error=str(e))
            raise
        self.log.record(client=self.name, model=self.model, task=task, system=system, prompt=prompt, response=raw, ok=True)
        return obj


class FakeLLM:
    """테스트용. responses[task] 가 dict 면 그대로, callable 이면 (system, prompt) 를 받아 dict 또는 문자열을 돌려준다."""

    name = "fake"

    def __init__(self, responses: dict[str, Any] | None = None, *, log: CallLog | None = None, model: str = "fake-model"):
        self.responses: dict[str, Any] = responses or {}
        self.log = log or CallLog()
        self.model = model
        self.calls: list[dict[str, str]] = []

    def complete_json(self, *, system: str, prompt: str, task: str) -> dict[str, Any]:
        self.calls.append({"task": task, "system": system, "prompt": prompt})
        if task not in self.responses:
            raise LLMError(f"FakeLLM 에 task={task} 응답이 없습니다")
        resp: Any = self.responses[task]
        if isinstance(resp, Callable):  # type: ignore[arg-type]
            resp = resp(system, prompt)
        raw = resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)
        try:
            obj = _parse_json_object(raw)
        except LLMError as e:
            self.log.record(client=self.name, model=self.model, task=task, system=system, prompt=prompt, response=raw, ok=False, error=str(e))
            raise
        self.log.record(client=self.name, model=self.model, task=task, system=system, prompt=prompt, response=raw, ok=True)
        return obj
