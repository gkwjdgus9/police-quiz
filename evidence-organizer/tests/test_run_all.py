"""run_all: case01 전체 실행, 산출물 존재, 재실행 시 무결성 검증."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "data" / "synthetic" / "case01"


def _load_run_all():
    spec = importlib.util.spec_from_file_location("run_all", ROOT / "scripts" / "run_all.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(not CASE.exists(), reason="case01 미생성")
def test_end_to_end(tmp_path: Path) -> None:
    run_all = _load_run_all()
    out = tmp_path / "out"
    result = run_all.run(CASE, out)
    for name in ["manifest.json", "run.log", "timeline.jsonl", "extracted.json", "ledger.json", "needs_review.json", "report.md", "evaluate.md", "evaluate.json"]:
        assert (out / name).exists(), name

    # 추출 100%, confirmed 재현율 12/12, 오탐은 라벨에 적힌 회비 1건뿐, 보고서 근거 없는 문장 0
    for key in ("accounts", "phones", "urls", "wallets"):
        assert result["extraction"][key]["recall"] == 1.0 and result["extraction"][key]["precision"] == 1.0, key
    assert result["ledger"]["confirmed"]["recall"] == 1.0
    assert result["ledger"]["confirmed"]["tp"] == 12 and result["ledger"]["confirmed"]["fp"] == 1
    assert result["ledger"]["confirmed_or_review"]["recall"] == 1.0
    assert result["report"]["unsupported_ratio"] == 0.0

    reviews = json.loads((out / "needs_review.json").read_text(encoding="utf-8"))
    assert all(r["status"] == "needs_review" for r in reviews)
    assert {r["category"] for r in reviews} == {"ledger_row"}

    # 재실행: manifest 검증 통과, runs 2회
    run_all.run(CASE, out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["runs"]) == 2 and set(manifest["files"]) == {"kakao_mobile.txt", "transfers_kb.csv"}


@pytest.mark.skipif(not CASE.exists(), reason="case01 미생성")
def test_tampered_raw_is_rejected(tmp_path: Path) -> None:
    import shutil

    from eo.hashing import IntegrityError

    run_all = _load_run_all()
    case = tmp_path / "case"
    shutil.copytree(CASE, case)
    out = tmp_path / "out"
    run_all.run(case, out)
    p = case / "raw" / "transfers_kb.csv"
    p.write_text(p.read_text(encoding="utf-8-sig").replace("3,000,000", "3,000,001", 1), encoding="utf-8-sig")
    with pytest.raises(IntegrityError):
        run_all.run(case, out)
