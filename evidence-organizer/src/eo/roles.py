"""참여자 역할 분류 (2단계, 로컬 LLM).

참여자마다 '서류철(dossier)'을 만든다: 메시지 통계 + 번호 붙은 표본 메시지(계좌·금액·URL 이 들어간 것 우선).
LLM 에게 역할과 근거 행 번호를 JSON 으로 받되,
- 근거 행은 표본에 있는 행만 인정한다. 하나도 없으면 역할을 unknown 으로 바꾼다.
- 결과는 항상 needs_review 다 (AI 는 제안, 확정은 사람). 피해자는 사건 정보로 주어지므로 LLM 에 묻지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from eo.llm import LLMClient, LLMError
from eo.parsers.kakao import SYSTEM_ACTOR
from eo.schema import Event, Evidence, Status

ROLES: tuple[str, ...] = ("operator", "assistant", "victim", "unrelated", "unknown")
ROLE_LABELS = {"operator": "운영자(리딩방 주도)", "assistant": "보조(입금 안내·관리)", "victim": "피해자", "unrelated": "무관한 참여자", "unknown": "판단 불가"}

SYSTEM_PROMPT = """당신은 사이버사기 수사관을 돕는 분석 보조다. 투자리딩방 등 메신저 대화의 참여자 한 명이 어떤 역할인지 판단한다.
역할은 다음 중 하나다.
- operator: 방을 주도하고 종목·수익을 선전하며 입금을 유도하는 운영자
- assistant: 입금 계좌·금액을 안내하고 확인해 주는 보조(실장 등)
- victim: 돈을 보내고 출금을 요구하는 피해자
- unrelated: 사기 수행과 무관해 보이는 일반 참여자(바람잡이일 수도 있으나 입금 유도·계좌 안내를 직접 하지 않음)
- unknown: 표본만으로는 판단할 수 없음
규칙: 제공된 표본 메시지의 행 번호(line)만 근거로 인용한다. 표본에 없는 사실을 지어내지 않는다. 확신이 없으면 unknown.
반드시 아래 JSON 형식으로만 답한다.
{"role": "<operator|assistant|victim|unrelated|unknown>", "confidence": <0~1 숫자>, "evidence_lines": [<행 번호 정수>...], "reason": "<한두 문장, 한국어>"}"""


@dataclass
class RoleJudgement:
    actor: str
    role: str
    confidence: float
    reason: str
    evidence: list[Evidence] = field(default_factory=list)
    status: Status = "needs_review"
    source: str = "llm"  # "llm" | "case" | "error"

    def to_dict(self) -> dict[str, Any]:
        return {"actor": self.actor, "role": self.role, "role_label": ROLE_LABELS.get(self.role, self.role), "confidence": self.confidence,
                "reason": self.reason, "evidence": [e.to_dict() for e in self.evidence], "status": self.status, "source": self.source}


def build_dossier(actor: str, messages: Sequence[Event], *, max_samples: int = 12, max_chars: int = 200) -> dict[str, Any]:
    """참여자 한 명의 통계와 표본. 식별정보가 든 메시지를 먼저, 그다음 처음·끝 메시지를 넣는다."""
    mine = [m for m in messages if m.actor == actor]
    if not mine:
        raise ValueError(f"메시지가 없는 참여자: {actor}")

    def has_ids(m: Event) -> bool:
        ex = m.extracted
        return any(ex.get(k) for k in ("accounts", "amounts", "urls", "wallets", "phones"))

    chosen: list[Event] = []
    seen: set[int] = set()
    for m in [m for m in mine if has_ids(m)] + mine[:3] + mine[-2:] + mine:
        if m.line not in seen and len(chosen) < max_samples:
            seen.add(m.line)
            chosen.append(m)
    chosen.sort(key=lambda m: m.line)
    return {
        "actor": actor,
        "stats": {
            "messages": len(mine),
            "first_ts": mine[0].ts.isoformat(), "last_ts": mine[-1].ts.isoformat(),
            "with_accounts": sum(1 for m in mine if m.extracted.get("accounts")),
            "with_amounts": sum(1 for m in mine if m.extracted.get("amounts")),
            "with_urls": sum(1 for m in mine if m.extracted.get("urls")),
            "with_wallets": sum(1 for m in mine if m.extracted.get("wallets")),
        },
        "samples": [{"line": m.line, "ts": m.ts.strftime("%Y-%m-%d %H:%M"), "text": m.text[:max_chars]} for m in chosen],
    }


def _judge_one(dossier: dict[str, Any], llm: LLMClient, src: str, victim: str) -> RoleJudgement:
    actor = dossier["actor"]
    prompt = f"피해자(사건 정보로 확인됨): {victim}\n분류할 참여자: {actor}\n\n서류철(JSON):\n{json.dumps(dossier, ensure_ascii=False, indent=1)}"
    try:
        obj = llm.complete_json(system=SYSTEM_PROMPT, prompt=prompt, task="roles")
    except LLMError as e:
        return RoleJudgement(actor=actor, role="unknown", confidence=0.0, reason=f"LLM 호출 실패: {e}", source="error")

    role = str(obj.get("role", "unknown"))
    if role not in ROLES:
        role = "unknown"
    try:
        confidence = max(0.0, min(1.0, float(obj.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    reason = str(obj.get("reason", "")).strip()[:300]

    allowed = {s["line"] for s in dossier["samples"]}
    raw_lines = obj.get("evidence_lines", [])
    cited: list[int] = []
    if isinstance(raw_lines, list):
        for x in raw_lines:
            try:
                n = int(x)
            except (TypeError, ValueError):
                continue
            if n in allowed and n not in cited:
                cited.append(n)
    if not cited and role != "unknown":
        reason = f"[근거 없음 → unknown] {reason}"
        role, confidence = "unknown", 0.0
    return RoleJudgement(actor=actor, role=role, confidence=confidence, reason=reason, evidence=[Evidence(src, n) for n in sorted(cited)])


def classify_roles(events: Sequence[Event], *, victim: str, llm: LLMClient | None, max_samples: int = 12) -> list[RoleJudgement]:
    """모든 참여자의 역할 판정. llm 이 None 이면 피해자 외 전원 unknown(needs_review)."""
    messages = [e for e in events if e.kind == "message" and e.actor != SYSTEM_ACTOR]
    actors: list[str] = []
    for m in messages:
        if m.actor not in actors:
            actors.append(m.actor)
    out: list[RoleJudgement] = []
    for actor in actors:
        mine = [m for m in messages if m.actor == actor]
        if actor == victim:
            out.append(RoleJudgement(actor=actor, role="victim", confidence=1.0, reason="사건 정보(case.json/--victim)로 지정된 피해자", evidence=[mine[0].evidence], status="confirmed", source="case"))
            continue
        if llm is None:
            out.append(RoleJudgement(actor=actor, role="unknown", confidence=0.0, reason="LLM 미사용(1단계 모드)", evidence=[mine[0].evidence], source="none"))
            continue
        out.append(_judge_one(build_dossier(actor, messages, max_samples=max_samples), llm, mine[0].src, victim))
    return out
