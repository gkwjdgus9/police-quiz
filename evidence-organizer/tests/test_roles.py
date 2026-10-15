"""roles: 서류철 구성, 인용 검증, LLM 실패 처리, 합성 사건."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from eo.llm import FakeLLM
from eo.parsers.kakao import parse_kakao
from eo.roles import build_dossier, classify_roles
from eo.schema import KST, Event, Evidence
from eo.timeline import build_timeline

CASE = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "case01"


def msg(line: int, actor: str, text: str) -> Event:
    return Event(ts=datetime(2026, 8, 20, 9, line % 60, tzinfo=KST), kind="message", actor=actor, text=text, src="chat.txt", line=line)


EVENTS = [
    msg(1, "박대표", "환영합니다 리딩방입니다"),
    msg(2, "김실장", "입금계좌 농협 352-1234-5678-93 로 3,000,000원"),
    msg(3, "이수진", "보냈습니다"),
    msg(4, "최민수", "ㅋㅋ 대박"),
    msg(5, "김실장", "확인했습니다"),
]


def test_dossier_prefers_messages_with_ids() -> None:
    tl, _ = build_timeline(list(EVENTS))
    d = build_dossier("김실장", tl, max_samples=1)
    assert [s["line"] for s in d["samples"]] == [2]
    assert d["stats"]["messages"] == 2 and d["stats"]["with_accounts"] == 1
    d = build_dossier("김실장", tl)
    assert [s["line"] for s in d["samples"]] == [2, 5]


def test_victim_is_fixed_and_no_llm_means_unknown() -> None:
    tl, _ = build_timeline(list(EVENTS))
    rs = classify_roles(tl, victim="이수진", llm=None)
    by = {r.actor: r for r in rs}
    assert by["이수진"].role == "victim" and by["이수진"].status == "confirmed" and by["이수진"].evidence == [Evidence("chat.txt", 3)]
    assert all(r.role == "unknown" and r.status == "needs_review" for a, r in by.items() if a != "이수진")


def test_llm_roles_with_citation_validation() -> None:
    tl, _ = build_timeline(list(EVENTS))

    def answer(system: str, prompt: str):
        actor = json.loads(prompt.split("서류철(JSON):\n", 1)[1])["actor"]
        return {
            "박대표": {"role": "operator", "confidence": 0.9, "evidence_lines": [1], "reason": "방을 주도"},
            "김실장": {"role": "assistant", "confidence": 0.95, "evidence_lines": [2, 999], "reason": "계좌 안내"},   # 999 는 표본에 없음 → 버림
            "최민수": {"role": "operator", "confidence": 0.8, "evidence_lines": [], "reason": "느낌상"},            # 근거 없음 → unknown
        }[actor]

    fake = FakeLLM({"roles": answer})
    by = {r.actor: r for r in classify_roles(tl, victim="이수진", llm=fake)}
    assert by["박대표"].role == "operator" and by["박대표"].evidence == [Evidence("chat.txt", 1)]
    assert by["김실장"].role == "assistant" and by["김실장"].evidence == [Evidence("chat.txt", 2)]
    assert by["최민수"].role == "unknown" and by["최민수"].confidence == 0.0 and "근거 없음" in by["최민수"].reason
    assert all(r.status == "needs_review" for a, r in by.items() if a != "이수진")
    assert len(fake.calls) == 3 and all(c["task"] == "roles" for c in fake.calls)


def test_bad_role_or_broken_json_is_unknown() -> None:
    tl, _ = build_timeline(list(EVENTS))
    fake = FakeLLM({"roles": lambda s, p: '{"role": "mastermind", "evidence_lines": [1]}' if "박대표" in p else "깨진 응답"})
    by = {r.actor: r for r in classify_roles(tl, victim="이수진", llm=fake)}
    assert by["박대표"].role == "unknown"
    assert by["최민수"].role == "unknown" and by["최민수"].source == "error"


@pytest.mark.skipif(not CASE.exists(), reason="case01 미생성")
def test_synthetic_roles_with_scripted_llm() -> None:
    labels = json.loads((CASE / "labels.json").read_text(encoding="utf-8"))
    tl, _ = build_timeline(list(parse_kakao(CASE / "raw" / "kakao_mobile.txt")))

    def answer(system: str, prompt: str):
        d = json.loads(prompt.split("서류철(JSON):\n", 1)[1])
        role = labels["participants"][d["actor"]]
        return {"role": role, "confidence": 0.9, "evidence_lines": [d["samples"][0]["line"]], "reason": "표본 근거"}

    rs = classify_roles(tl, victim=labels["victim"], llm=FakeLLM({"roles": answer}))
    assert {r.actor: r.role for r in rs} == labels["participants"]
    assert all(r.evidence for r in rs)
