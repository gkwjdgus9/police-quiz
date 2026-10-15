"""report: 각주 규칙, 근거 없는 문장 제외, 합성 사건 보고서 구조."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from eo.ledger import build_ledger
from eo.parsers.bank_csv import parse_bank_csv
from eo.parsers.kakao import parse_kakao
from eo.report import ReportBuilder, build_report, footnotes
from eo.schema import KST, Evidence, ReviewItem
from eo.timeline import aggregate_extracted, build_timeline

CASE = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "case01"
FOOTNOTE = re.compile(r"\[([^\[\]:]+):(\d+)\]")


def test_footnotes_sorted_unique() -> None:
    assert footnotes([Evidence("b.csv", 3), Evidence("a.txt", 9), Evidence("a.txt", 2), Evidence("a.txt", 9)]) == "[a.txt:2][a.txt:9][b.csv:3]"


def test_sentence_without_evidence_is_dropped() -> None:
    b = ReportBuilder()
    assert b.sentence("근거 있음", [Evidence("a.txt", 1)]) is True
    assert b.sentence("근거 없음", []) is False
    text = b.render()
    assert "근거 있음 [a.txt:1]" in text
    assert "근거 없음" not in text
    assert len(b.dropped) == 1 and b.dropped[0].status == "needs_review" and b.dropped[0].value == "근거 없음"


def test_table_rows_without_evidence_are_dropped() -> None:
    b = ReportBuilder()
    n = b.table(["a", "b"], [(["1", "x"], [Evidence("f", 1)]), (["2", "y"], [])])
    assert n == 1
    text = b.render()
    assert "| 1 | x | [f:1] |" in text and "| 2 | y |" not in text
    assert any(d.category == "report_row_no_evidence" for d in b.dropped)


def _content_lines(md: str) -> list[str]:
    out: list[str] = []
    lines = md.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("- "):
            out.append(line)
        elif line.startswith("|"):
            is_sep = re.fullmatch(r"\|(?:\s*:?-+:?\s*\|)+", line) is not None
            next_is_sep = i + 1 < len(lines) and re.fullmatch(r"\|(?:\s*:?-+:?\s*\|)+", lines[i + 1]) is not None
            if not is_sep and not next_is_sep:
                out.append(line)
    return out


@pytest.fixture(scope="module")
def synthetic_report() -> tuple[str, list[ReviewItem], dict]:
    labels = json.loads((CASE / "labels.json").read_text(encoding="utf-8"))
    events = list(parse_kakao(CASE / "raw" / "kakao_mobile.txt")) + list(parse_bank_csv(CASE / "raw" / "transfers_kb.csv", victim=labels["victim"]))
    tl, reviews = build_timeline(events)
    ledger = build_ledger(tl, victim=labels["victim"])
    md, dropped = build_report(
        case_name="case01", events=tl, ledger=ledger, reviews=reviews, extracted=aggregate_extracted(tl),
        generated_at=datetime(2026, 10, 15, 12, 0, tzinfo=KST), git_hash="test",
    )
    return md, dropped, labels


@pytest.mark.skipif(not CASE.exists(), reason="case01 미생성")
def test_every_content_line_has_valid_footnote(synthetic_report) -> None:
    md, dropped, _ = synthetic_report
    sizes = {p.name: len(p.read_text(encoding="utf-8-sig").splitlines()) for p in (CASE / "raw").iterdir()}
    content = _content_lines(md)
    assert len(content) > 20
    for line in content:
        refs = FOOTNOTE.findall(line)
        assert refs, line
        for src, ln in refs:
            assert src in sizes and 1 <= int(ln) <= sizes[src], line
    assert dropped == []


@pytest.mark.skipif(not CASE.exists(), reason="case01 미생성")
def test_synthetic_report_sections(synthetic_report) -> None:
    md, _, labels = synthetic_report
    assert "## 3. 범죄일람표 (confirmed)" in md and "## 4. 확인 필요 이체 (needs_review)" in md
    assert "피해 이체는 8건" in md
    for acc in labels["chat"]["accounts"]:
        assert f"`{acc}`" in md
    for unit in labels["chat"]["amount_mentions_korean_unit"]:
        assert f"'{unit}'" in md
    assert "<!-- generated_at=" in md


def test_report_with_no_messages_drops_sentence() -> None:
    md, dropped = build_report(case_name="x", events=[], ledger=[], reviews=[], extracted={}, generated_at=datetime(2026, 1, 1, tzinfo=KST), git_hash="g")
    assert "대화 자료가 없다" not in md
    assert [d.value for d in dropped] == ["대화 자료가 없다."]
