"""bank_csv: 은행 매핑 2종, 감지, 모르는 은행 실패, 인코딩."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from eo.parsers.bank_csv import UnknownBankError, detect_bank, parse_amount, parse_bank_csv
from eo.schema import KST

CASE = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "case01"

KB = """거래일시,적요,출금액,입금액,잔액,거래점,상대계좌번호,상대은행,받는분
"2026.08.22 10:30:41","증거금","3,000,000","","1,000,000","인터넷뱅킹","352-1234-5678-93","농협","주식회사 골드라인"
"2026.08.23 09:00:00","급여","","2,850,000","3,850,000","본점","","",""
"""

SHINHAN = """거래일,거래시간,내용,출금(원),입금(원),잔액(원),거래점,상대방계좌번호,상대방은행,상대방이름
2026-09-05,10:15:29,해외선물,4500000,,500000,영업부,110-456-789012,신한,강민호
"""


def test_parse_amount() -> None:
    assert parse_amount("3,000,000") == 3_000_000
    assert parse_amount("45900") == 45_900
    assert parse_amount("") == 0
    with pytest.raises(ValueError):
        parse_amount("삼백만")


def test_detect_bank() -> None:
    assert detect_bank(KB.splitlines()[0].split(",")).name == "KB국민은행"
    assert detect_bank(SHINHAN.splitlines()[0].split(",")).name == "신한은행"


def test_unknown_bank_fails(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    p.write_text("날짜,금액,비고\n2026-01-01,100,테스트\n", encoding="utf-8")
    with pytest.raises(UnknownBankError):
        list(parse_bank_csv(p))
    with pytest.raises(UnknownBankError):
        list(parse_bank_csv(p, bank="우리은행"))


def test_explicit_bank_must_match_header(tmp_path: Path) -> None:
    p = tmp_path / "kb.csv"
    p.write_text(KB, encoding="utf-8")
    with pytest.raises(UnknownBankError):
        list(parse_bank_csv(p, bank="신한은행"))


def test_kb_rows(tmp_path: Path) -> None:
    p = tmp_path / "kb.csv"
    p.write_text(KB, encoding="utf-8-sig")
    ev = list(parse_bank_csv(p, victim="이수진"))
    assert len(ev) == 2
    w, d = ev
    assert w.kind == "transfer" and w.actor == "이수진" and w.src == "kb.csv" and w.line == 2
    assert w.ts == datetime(2026, 8, 22, 10, 30, 41, tzinfo=KST)
    assert w.extracted["accounts"] == ["3521234567893"] and w.extracted["amounts"] == [3_000_000]
    assert w.meta["direction"] == "withdraw" and w.meta["to_bank"] == "농협" and w.meta["to_name"] == "주식회사 골드라인"
    assert w.meta["to_account_raw"] == "352-1234-5678-93"
    assert d.meta["direction"] == "deposit" and d.extracted["accounts"] == [] and d.extracted["amounts"] == [2_850_000]
    assert d.line == 3


def test_shinhan_cp949(tmp_path: Path) -> None:
    p = tmp_path / "shinhan.csv"
    p.write_bytes(SHINHAN.encode("cp949"))
    ev = list(parse_bank_csv(p))
    assert len(ev) == 1
    e = ev[0]
    assert e.ts == datetime(2026, 9, 5, 10, 15, 29, tzinfo=KST)
    assert e.meta["bank_format"] == "신한은행" and e.extracted["accounts"] == ["110456789012"]
    assert e.extracted["amounts"] == [4_500_000]


def test_both_or_neither_amount_fails(tmp_path: Path) -> None:
    p = tmp_path / "kb.csv"
    p.write_text(KB.splitlines()[0] + '\n"2026.08.22 10:30:41","x","1","1","2","본점","","",""\n', encoding="utf-8")
    with pytest.raises(ValueError):
        list(parse_bank_csv(p))


@pytest.mark.skipif(not CASE.exists(), reason="case01 미생성")
def test_synthetic_case_csv() -> None:
    ev = list(parse_bank_csv(CASE / "raw" / "transfers_kb.csv", victim="이수진"))
    assert len(ev) == 20
    assert sum(1 for e in ev if e.meta["direction"] == "withdraw") == 18
    assert all(e.ts.tzinfo is not None for e in ev)
    assert [e.line for e in ev] == list(range(2, 22))
