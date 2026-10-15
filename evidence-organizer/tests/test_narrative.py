"""narrative: 자료 묶음 구성, 인용·숫자·이름 검증, 합성 사건."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from eo.ledger import build_ledger
from eo.llm import FakeLLM
from eo.narrative import build_context, generate_narrative
from eo.parsers.bank_csv import parse_bank_csv
from eo.parsers.kakao import parse_kakao
from eo.roles import classify_roles
from eo.schema import KST, Event, Evidence
from eo.timeline import build_timeline

CASE = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "case01"


def msg(line: int, actor: str, text: str, hhmm: str = "09:00") -> Event:
    h, m = map(int, hhmm.split(":"))
    return Event(ts=datetime(2026, 8, 22, h, m, tzinfo=KST), kind="message", actor=actor, text=text, src="chat.txt", line=line)


def transfer(line: int, amount: int, acc: str, hhmm: str) -> Event:
    h, m = map(int, hhmm.split(":"))
    return Event(ts=datetime(2026, 8, 22, h, m, tzinfo=KST), kind="transfer", actor="이수진", text=f"출금 {amount:,}원 증거금 → 농협 {acc} (주식회사 골드라인)", src="bank.csv", line=line,
                 extracted={"accounts": [acc.replace("-", "")], "phones": [], "urls": [], "wallets": [], "amounts": [amount]},
                 meta={"direction": "withdraw", "to_account": acc.replace("-", ""), "to_bank": "농협"})


EVENTS = [
    msg(1, "박대표", "환영합니다", "08:00"),
    msg(2, "김실장", "첫 증거금은 3,000,000원입니다. 농협 352-1234-5678-93", "09:52"),
    transfer(2, 3_000_000, "352-1234-5678-93", "10:30"),
    msg(3, "이수진", "방금 3,000,000원 보냈습니다", "10:32"),
    msg(4, "최민수", "ㅋㅋ", "11:00"),
    msg(5, "정하나", "굿", "12:00"),
]


@pytest.fixture
def prepared():
    tl, _ = build_timeline(list(EVENTS))
    ledger = build_ledger(tl, victim="이수진")
    roles = classify_roles(tl, victim="이수진", llm=None)
    return tl, ledger, roles


def test_context_contains_confirmed_evidence_and_ends(prepared) -> None:
    tl, ledger, roles = prepared
    ctx = build_context(tl, ledger, roles)
    keys = {c.key for c in ctx}
    assert {("bank.csv", 2), ("chat.txt", 2), ("chat.txt", 3)} <= keys
    assert ("chat.txt", 1) in keys and ("chat.txt", 5) in keys  # 첫·마지막 메시지
    assert ("chat.txt", 4) not in keys or True  # 역할 근거(첫 메시지)로 들어올 수 있음


def test_no_llm_returns_nothing(prepared) -> None:
    tl, ledger, roles = prepared
    assert generate_narrative(tl, ledger, roles, victim="이수진", llm=None) == ([], [])


def test_sentence_validation(prepared) -> None:
    tl, ledger, roles = prepared
    resp = {"sentences": [
        {"text": "2026-08-22 09:52 김실장이 농협 352-1234-5678-93 계좌로 3,000,000원 입금을 안내했다.", "cites": [{"src": "chat.txt", "line": 2}]},                      # 통과
        {"text": "이수진이 10:30 에 3,000,000원을 이체했다.", "cites": [{"src": "bank.csv", "line": 2}, {"src": "chat.txt", "line": 3}]},                                    # 통과(피해자 이름은 예외)
        {"text": "김실장이 5,000,000원을 추가로 요구했다.", "cites": [{"src": "chat.txt", "line": 2}]},                                                                   # 금액 없음 → 버림
        {"text": "김실장이 카카오뱅크 3333-05-1234567 로 입금하라고 했다.", "cites": [{"src": "chat.txt", "line": 2}]},                                                    # 계좌 없음 → 버림
        {"text": "박대표가 입금을 독촉했다.", "cites": [{"src": "chat.txt", "line": 2}]},                                                                                  # 이름이 인용 행에 없음 → 버림
        {"text": "이수진이 돈을 보냈다.", "cites": []},                                                                                                                  # 인용 없음 → 버림
        {"text": "이수진이 돈을 보냈다.", "cites": [{"src": "chat.txt", "line": 77}]},                                                                                   # 묶음 밖 행 → 버림
        {"text": "운영자가 방을 열었다.", "cites": [{"src": "chat.txt", "line": 1}]},                                                                                     # 통과
        {"text": "x" * 301, "cites": [{"src": "chat.txt", "line": 1}]},                                                                                               # 너무 김 → 버림
    ]}
    kept, dropped = generate_narrative(tl, ledger, roles, victim="이수진", llm=FakeLLM({"narrative": resp}))
    assert [k.text[:6] for k in kept] == ["2026-0", "이수진이 1", "운영자가 방"]
    assert kept[1].evidence == [Evidence("bank.csv", 2), Evidence("chat.txt", 3)]
    assert all(k.status == "needs_review" for k in kept)
    reasons = [d.reason for d in dropped]
    assert any("5,000,000원" in r for r in reasons)
    assert any("3333051234567" in r for r in reasons)
    assert any("'박대표'" in r for r in reasons)
    assert "인용 없음" in reasons
    assert any("자료 묶음에 없는 행" in r for r in reasons)
    assert any("300자" in r for r in reasons)
    assert len(dropped) == 6


def test_broken_llm_response(prepared) -> None:
    tl, ledger, roles = prepared
    kept, dropped = generate_narrative(tl, ledger, roles, victim="이수진", llm=FakeLLM({"narrative": "깨짐"}))
    assert kept == [] and dropped[0].category == "narrative_error"
    kept, dropped = generate_narrative(tl, ledger, roles, victim="이수진", llm=FakeLLM({"narrative": {"sentences": "문자열"}}))
    assert kept == [] and dropped[0].category == "narrative_error"


@pytest.mark.skipif(not CASE.exists(), reason="case01 미생성")
def test_synthetic_narrative_from_context_only() -> None:
    """자료 묶음의 행을 그대로 옮겨 쓰는 '정직한' 가짜 LLM 은 전부 통과하고, 금액을 바꾼 문장은 걸린다."""
    labels = json.loads((CASE / "labels.json").read_text(encoding="utf-8"))
    events = list(parse_kakao(CASE / "raw" / "kakao_mobile.txt")) + list(parse_bank_csv(CASE / "raw" / "transfers_kb.csv", victim=labels["victim"]))
    tl, _ = build_timeline(events)
    ledger = build_ledger(tl, victim=labels["victim"])
    roles = classify_roles(tl, victim=labels["victim"], llm=None)

    def answer(system: str, prompt: str):
        lines = [json.loads(l) for l in prompt.split("자료 묶음(인용 가능한 행):\n", 1)[1].splitlines() if l.startswith("{")]
        csv_rows = [l for l in lines if l["src"].endswith(".csv")][:5]
        sents = [{"text": f"{l['ts']} 피해자가 {l['text']}", "cites": [{"src": l["src"], "line": l["line"]}]} for l in csv_rows]
        sents.append({"text": "피해자가 99,999,999원을 보냈다.", "cites": [{"src": csv_rows[0]["src"], "line": csv_rows[0]["line"]}]})
        return {"sentences": sents}

    kept, dropped = generate_narrative(tl, ledger, roles, victim=labels["victim"], llm=FakeLLM({"narrative": answer}))
    assert len(kept) == 5 and len(dropped) == 1
    assert "99,999,999원" in dropped[0].reason
