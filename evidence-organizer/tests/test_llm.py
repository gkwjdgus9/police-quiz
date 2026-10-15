"""llm: 루프백 전용, JSON 파싱, 호출 로그."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eo.llm import CallLog, FakeLLM, LLMError, OllamaClient, _parse_json_object


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434"])
def test_ollama_accepts_loopback(url: str) -> None:
    OllamaClient(url=url)


@pytest.mark.parametrize("url", ["http://api.openai.com", "https://10.0.0.5:11434", "http://ollama.internal:11434", "http://192.168.0.2"])
def test_ollama_rejects_non_loopback(url: str) -> None:
    with pytest.raises(LLMError):
        OllamaClient(url=url)


def test_ollama_unavailable_here() -> None:
    # 이 테스트 환경에 Ollama 가 없어도 is_available 은 예외 없이 False 를 돌려준다
    assert OllamaClient(url="http://127.0.0.1:1", timeout=1).is_available() is False


def test_parse_json_object_tolerates_prose() -> None:
    assert _parse_json_object('{"a": 1}') == {"a": 1}
    assert _parse_json_object('답변입니다:\n{"a": [1, 2]}\n감사합니다') == {"a": [1, 2]}
    with pytest.raises(LLMError):
        _parse_json_object("JSON 없음")
    with pytest.raises(LLMError):
        _parse_json_object("[1, 2]")


def test_fake_llm_and_log(tmp_path: Path) -> None:
    log = CallLog(path=tmp_path / "llm_log.jsonl")
    fake = FakeLLM({"roles": {"role": "operator"}, "bad": "이건 JSON 이 아님"}, log=log)
    assert fake.complete_json(system="s", prompt="p", task="roles") == {"role": "operator"}
    with pytest.raises(LLMError):
        fake.complete_json(system="s", prompt="p", task="bad")
    with pytest.raises(LLMError):
        fake.complete_json(system="s", prompt="p", task="missing")
    lines = [json.loads(l) for l in (tmp_path / "llm_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["ok"] for e in lines] == [True, False]
    assert lines[0]["prompt"] == "p" and lines[0]["response"] == '{"role": "operator"}'
    assert fake.calls[0]["task"] == "roles"


def test_fake_llm_callable_response() -> None:
    fake = FakeLLM({"echo": lambda system, prompt: {"len": len(prompt)}})
    assert fake.complete_json(system="", prompt="abcd", task="echo") == {"len": 4}
