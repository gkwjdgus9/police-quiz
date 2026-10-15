"""evaluate: 추출 P/R, 일람표 P/R, 보고서 각주 검증."""

from __future__ import annotations

from pathlib import Path

from eo.evaluate import evaluate_extraction, evaluate_ledger, evaluate_report, format_table, report_content_lines

LABELS = {
    "chat": {"accounts": ["111", "222"], "phones": ["01011112222"], "urls": ["https://a.com"], "wallets": []},
    "fraud_transfers": [
        {"to_account": "111", "amount": 1000, "evidence": {"src": "t.csv", "line": 2}},
        {"to_account": "222", "amount": 2000, "evidence": {"src": "t.csv", "line": 3}},
    ],
}


def test_extraction_pr() -> None:
    extracted = {"accounts": {"111": [], "999": []}, "phones": {"01011112222": []}, "urls": {}, "wallets": {}}
    r = evaluate_extraction(extracted, LABELS)
    assert (r["accounts"].tp, r["accounts"].fp, r["accounts"].fn) == (1, 1, 1)
    assert r["accounts"].missing == ["222"] and r["accounts"].extra == ["999"]
    assert r["phones"].recall == 1.0 and r["phones"].precision == 1.0
    assert r["urls"].recall == 0.0
    assert r["wallets"].to_dict()["recall"] == 0.0  # 정답도 예측도 없음


def test_ledger_pr() -> None:
    ledger = [
        {"to_account": "111", "amount": 1000, "status": "confirmed", "evidence": [{"src": "t.csv", "line": 2}, {"src": "c.txt", "line": 9}]},
        {"to_account": "222", "amount": 2000, "status": "needs_review", "evidence": [{"src": "t.csv", "line": 3}]},
        {"to_account": "333", "amount": 50, "status": "confirmed", "evidence": [{"src": "t.csv", "line": 4}]},
    ]
    r = evaluate_ledger(ledger, LABELS)
    assert (r["confirmed"].tp, r["confirmed"].fp, r["confirmed"].fn) == (1, 1, 1)
    assert r["confirmed_or_review"].recall == 1.0


def test_report_content_lines_and_footnotes(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "c.txt").write_text("a\nb\nc\n", encoding="utf-8")
    md = "\n".join([
        "# 제목", "<!-- 주석 -->", "- 각주 있음 [c.txt:2]", "- 각주 없음", "- 없는 행 [c.txt:9]", "- 없는 파일 [x.txt:1]",
        "| h1 | 근거 |", "|---|---|", "| 행 | [c.txt:3] |", "| 행2 | 없음 |", "",
    ])
    assert len(report_content_lines(md)) == 6
    r = evaluate_report(md, raw)
    assert r["sentences"] == 6 and r["no_footnote"] == 2 and r["bad_reference"] == 2
    assert r["unsupported_ratio"] == round(4 / 6, 4)


def test_format_table_runs() -> None:
    extracted = {"accounts": {"111": []}, "phones": {}, "urls": {}, "wallets": {}}
    result = {
        "extraction": {k: v.to_dict() for k, v in evaluate_extraction(extracted, LABELS).items()},
        "ledger": {k: v.to_dict() for k, v in evaluate_ledger([], LABELS).items()},
        "report": {"sentences": 0, "no_footnote": 0, "bad_reference": 0, "unsupported_ratio": 0.0, "examples": []},
    }
    table = format_table(result)
    assert "추출: 계좌번호 | 2 | 1 | 1 | 50% | 100% | 누락 222" in table
    assert "| report.md | 0 | 0 | 0 | 0.0% |" in table
