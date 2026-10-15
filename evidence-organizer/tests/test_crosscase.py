"""crosscase: 공유 값 탐지, 피해 계좌 표시, markdown 근거, 합성 두 사건 종단."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from eo.crosscase import CaseIndex, evaluate_shared, find_shared, render_markdown

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data" / "synthetic"


def _write_case(root: Path, name: str, extracted: dict, ledger: list) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "extracted.json").write_text(json.dumps(extracted, ensure_ascii=False), encoding="utf-8")
    (d / "ledger.json").write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    return d


def test_find_shared_and_markdown(tmp_path: Path) -> None:
    a = _write_case(tmp_path, "caseA", {"accounts": {"111": [{"src": "a.txt", "line": 1}], "222": [{"src": "a.txt", "line": 2}]}, "phones": {"01011112222": [{"src": "a.txt", "line": 3}]}, "urls": {}, "wallets": {}},
                    [{"to_account": "111", "status": "confirmed", "victim": "갑"}])
    b = _write_case(tmp_path, "caseB", {"accounts": {"111": [{"src": "b.txt", "line": 9}, {"src": "b.txt", "line": 10}], "333": [{"src": "b.txt", "line": 4}]}, "phones": {"01011112222": [{"src": "b.txt", "line": 5}]}, "urls": {}, "wallets": {}},
                    [{"to_account": "111", "status": "needs_review", "victim": "을"}])
    c = _write_case(tmp_path, "caseC", {"accounts": {"333": [{"src": "c.txt", "line": 1}]}, "phones": {}, "urls": {}, "wallets": {}}, [])
    cases = [CaseIndex.load(d) for d in (a, b, c)]
    shared = find_shared(cases)
    assert [(s.category, s.value, len(s.cases), s.is_fraud_account) for s in shared] == [
        ("accounts", "111", 2, True),     # caseA 에서 confirmed 피해 계좌 → 맨 위
        ("accounts", "333", 2, False),
        ("phones", "01011112222", 2, False),
    ]
    assert all(s.status == "needs_review" for s in shared)
    assert shared[0].cases[1]["mentions"] == 2 and shared[0].cases[1]["evidence"][0] == {"case": "caseB", "src": "b.txt", "line": 9}
    md = render_markdown(shared, cases)
    assert "| 계좌번호 | `111` | 2 | 예 | caseA 1회 (confirmed 입금계좌), caseB 2회 | [caseA/a.txt:1][caseB/b.txt:9][caseB/b.txt:10] |" in md


def test_no_shared(tmp_path: Path) -> None:
    a = _write_case(tmp_path, "A", {"accounts": {"1": [{"src": "a", "line": 1}]}, "phones": {}, "urls": {}, "wallets": {}}, [])
    b = _write_case(tmp_path, "B", {"accounts": {"2": [{"src": "b", "line": 1}]}, "phones": {}, "urls": {}, "wallets": {}}, [])
    cases = [CaseIndex.load(a), CaseIndex.load(b)]
    assert find_shared(cases) == []
    assert "공통으로 등장하는 값 없음" in render_markdown([], cases)


def test_evaluate_shared() -> None:
    from eo.crosscase import SharedValue

    shared = [SharedValue("accounts", "111"), SharedValue("phones", "999")]
    labels = {"case02": {"shared_with": {"case01": {"accounts": ["111"], "urls": ["u"]}}}}
    ev = evaluate_shared(shared, labels)
    assert (ev["tp"], ev["fp"], ev["fn"]) == (1, 1, 1) and ev["missing"] == ["urls:u"] and ev["extra"] == ["phones:999"]


@pytest.mark.skipif(not (SYN / "case02").exists(), reason="case02 미생성")
def test_synthetic_two_cases_end_to_end(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("run_all", ROOT / "scripts" / "run_all.py")
    run_all = importlib.util.module_from_spec(spec); sys.modules["run_all"] = run_all; spec.loader.exec_module(run_all)  # type: ignore[union-attr]
    spec2 = importlib.util.spec_from_file_location("cross_cases", ROOT / "scripts" / "cross_cases.py")
    cross = importlib.util.module_from_spec(spec2); sys.modules["cross_cases"] = cross; spec2.loader.exec_module(cross)  # type: ignore[union-attr]

    out = tmp_path / "out"
    for case in ("case01", "case02"):
        r = run_all.run(SYN / case, out / case, work_dir=tmp_path / "work")
        assert r["ledger"]["confirmed"]["recall"] == 1.0, case
    result = cross.run(out, labels_root=SYN)
    assert result["cases"] == ["case01", "case02"]
    ev = result["evaluate"]
    assert ev["recall"] == 1.0 and ev["precision"] == 1.0, ev
    shared = json.loads((out / "crosscase" / "shared.json").read_text(encoding="utf-8"))
    acc = next(s for s in shared if s["category"] == "accounts")
    assert acc["value"] == "3333051234567" and acc["fraud_account"] is True
    assert all(c["fraud_account"] for c in acc["cases"])  # 두 사건 모두에서 confirmed 입금계좌
    md = (out / "crosscase" / "shared.md").read_text(encoding="utf-8")
    assert "[case01/kakao_mobile.txt:" in md and "[case02/kakao_mobile.txt:" in md
    assert "`16001234`" in md and "`https://t.me/goldline_vip`" in md
