"""timeline + ledger: 병합 순서, 추출 집계, 판정 규칙."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from eo.ledger import build_ledger
from eo.parsers.bank_csv import parse_bank_csv
from eo.parsers.kakao import parse_kakao
from eo.schema import KST, Event, Evidence
from eo.timeline import aggregate_extracted, build_timeline, read_timeline_jsonl, write_timeline_jsonl

CASE = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "case01"


def msg(ts: str, actor: str, text: str, line: int) -> Event:
    return Event(ts=datetime.fromisoformat(ts).replace(tzinfo=KST), kind="message", actor=actor, text=text, src="chat.txt", line=line)


def transfer(ts: str, amount: int, to_account: str, line: int, *, direction: str = "withdraw", bank: str = "농협") -> Event:
    return Event(
        ts=datetime.fromisoformat(ts).replace(tzinfo=KST), kind="transfer", actor="피해자", text="", src="bank.csv", line=line,
        extracted={"accounts": [to_account] if to_account else [], "phones": [], "urls": [], "wallets": [], "amounts": [amount]},
        meta={"direction": direction, "to_account": to_account, "to_bank": bank},
    )


def test_timeline_sorted_and_enriched() -> None:
    ev = [
        msg("2026-08-22T10:00", "김실장", "계좌 352-1234-5678-93 로 3,000,000원", 10),
        transfer("2026-08-22T09:00", 100, "", 2),
        msg("2026-08-22T09:30", "이수진", "500만원 보낼게요, 수수료는 3천 정도?", 9),
    ]
    tl, reviews = build_timeline(ev)
    assert [e.line for e in tl] == [2, 9, 10]
    assert tl[2].extracted["accounts"] == ["3521234567893"] and tl[2].extracted["amounts"] == [3_000_000]
    assert tl[1].extracted["amounts"] == [5_000_000]  # '500만원' 은 환산
    assert len(reviews) == 1 and reviews[0].value == "3천" and reviews[0].status == "needs_review"  # '3천' 은 모호 → 보류
    assert reviews[0].evidence == [Evidence("chat.txt", 9)]


def test_aggregate_extracted_with_evidence() -> None:
    ev = [
        msg("2026-08-22T10:00", "김실장", "352-1234-5678-93", 10),
        msg("2026-08-23T10:00", "김실장", "3521234567893 다시", 20),
        transfer("2026-08-22T09:00", 100, "3521234567893", 2),
    ]
    tl, _ = build_timeline(ev)
    agg = aggregate_extracted(tl)
    assert agg["accounts"] == {"3521234567893": [{"src": "chat.txt", "line": 10}, {"src": "chat.txt", "line": 20}]}
    assert agg["phones"] == {}


def test_jsonl_roundtrip(tmp_path: Path) -> None:
    ev = [msg("2026-08-22T10:00", "김실장", "352-1234-5678-93", 10), transfer("2026-08-22T09:00", 100, "", 2)]
    tl, _ = build_timeline(ev)
    p = tmp_path / "timeline.jsonl"
    write_timeline_jsonl(tl, p)
    back = read_timeline_jsonl(p)
    assert [e.to_dict() for e in back] == [e.to_dict() for e in tl]
    assert all(e.ts.tzinfo is not None for e in back)


def test_ledger_rules() -> None:
    ev = [
        msg("2026-08-22T09:50", "김실장", "증거금 3,000,000원 농협 352-1234-5678-93", 5),
        msg("2026-08-25T13:50", "김실장", "추가 입금 부탁드립니다, 계좌 동일 352-1234-5678-93", 6),
        transfer("2026-08-22T10:30", 3_000_000, "3521234567893", 2),   # 계좌+금액 → confirmed
        transfer("2026-08-25T14:10", 5_000_000, "3521234567893", 3),   # 계좌만(금액 언급 없음) → needs_review
        transfer("2026-09-14T17:45", 3_000_000, "45691023456789", 4),  # 금액만 → needs_review
        transfer("2026-08-30T18:20", 650_000, "1002345678901", 5),     # 둘 다 없음
        transfer("2026-08-26T12:33", 45_900, "", 6),                   # 상대 계좌 없음
        transfer("2026-08-21T09:00", 2_850_000, "", 7, direction="deposit"),  # 입금 → 제외
    ]
    tl, _ = build_timeline(ev)
    rows = build_ledger(tl, victim="이수진")
    # 시각순: 08-22(확정), 08-25, 08-26, 08-30, 09-14
    assert [r.status for r in rows] == ["confirmed", "needs_review", "needs_review", "needs_review", "needs_review"]
    confirmed = next(r for r in rows if r.status == "confirmed")
    assert confirmed.amount == 3_000_000 and confirmed.to_account == "3521234567893" and confirmed.bank == "농협"
    assert confirmed.victim == "이수진"
    # 계좌는 5·6행, 금액은 5행에 등장 → 세 근거 모두
    assert set(confirmed.evidence) == {Evidence("bank.csv", 2), Evidence("chat.txt", 5), Evidence("chat.txt", 6)}
    account_only = next(r for r in rows if r.amount == 5_000_000)
    assert account_only.status == "needs_review" and "금액" in account_only.notes[0]
    assert set(account_only.evidence) == {Evidence("bank.csv", 3), Evidence("chat.txt", 5), Evidence("chat.txt", 6)}
    amount_only = next(r for r in rows if r.to_account == "45691023456789")
    assert amount_only.status == "needs_review" and "계좌는 대화에 없음" in amount_only.notes[0]
    assert all(any(e.src == "bank.csv" for e in r.evidence) for r in rows)
    assert all(r.ts == sorted(rows, key=lambda x: x.ts)[i].ts for i, r in enumerate(rows))


@pytest.mark.skipif(not CASE.exists(), reason="case01 미생성")
def test_synthetic_ledger_against_labels() -> None:
    labels = json.loads((CASE / "labels.json").read_text(encoding="utf-8"))
    events = list(parse_kakao(CASE / "raw" / "kakao_mobile.txt")) + list(parse_bank_csv(CASE / "raw" / "transfers_kb.csv", victim=labels["victim"]))
    tl, reviews = build_timeline(events)
    rows = build_ledger(tl, victim=labels["victim"])
    assert len(rows) == 18  # 출금 18건 (입금 2건 제외)
    confirmed = [r for r in rows if r.status == "confirmed"]
    fraud_keys = {(f["to_account"], f["amount"], f["evidence"]["line"]) for f in labels["fraud_transfers"]}
    conf_keys = {(r.to_account, r.amount, next(e.line for e in r.evidence if e.src == "transfers_kb.csv")) for r in confirmed}
    # 피해 이체 12건 전부 confirmed ('만원' 표기도 환산되므로)
    assert fraud_keys <= conf_keys
    # 규칙상 confirmed 되는 무관 이체(회비)는 라벨의 known_false_positives 와 정확히 일치해야 한다
    extra = {(k[0], k[1]) for k in conf_keys - fraud_keys}
    assert extra == {(f["to_account"], f["amount"]) for f in labels["known_false_positives"]}
    assert reviews == []  # case01 의 단위 표기는 전부 환산 가능
