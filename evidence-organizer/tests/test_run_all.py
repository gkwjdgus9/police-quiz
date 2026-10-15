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
    assert {r["category"] for r in reviews} == {"ledger_row", "role"}  # LLM 없음 → 역할은 전부 unknown/needs_review
    roles = json.loads((out / "roles.json").read_text(encoding="utf-8"))
    assert {r["actor"]: r["role"] for r in roles if r["actor"] == "이수진"} == {"이수진": "victim"}
    assert result["roles"]["accuracy"] == 0.0 and result["roles"]["unknown"] == 4
    assert "narrative" not in result
    assert "사건 경위" not in (out / "report.md").read_text(encoding="utf-8")

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


@pytest.mark.skipif(not CASE.exists(), reason="case01 미생성")
def test_end_to_end_with_fake_llm(tmp_path: Path) -> None:
    """2단계: 가짜 LLM 으로 역할·경위가 보고서와 평가에 들어가고, 근거 없는 문장은 걸러지는지."""
    from eo.llm import FakeLLM

    run_all = _load_run_all()
    labels = json.loads((CASE / "labels.json").read_text(encoding="utf-8"))

    def roles_answer(system: str, prompt: str):
        d = json.loads(prompt.split("서류철(JSON):\n", 1)[1])
        return {"role": labels["participants"][d["actor"]], "confidence": 0.85, "evidence_lines": [d["samples"][0]["line"]], "reason": "표본 근거"}

    def narrative_answer(system: str, prompt: str):
        lines = [json.loads(l) for l in prompt.split("자료 묶음(인용 가능한 행):\n", 1)[1].splitlines() if l.startswith("{")]
        csv_rows = [l for l in lines if l["src"].endswith(".csv")][:3]
        sents = [{"text": f"{l['ts']} 피해자가 {l['text']}", "cites": [{"src": l["src"], "line": l["line"]}]} for l in csv_rows]
        sents.append({"text": "박대표가 1억원을 요구했다.", "cites": [{"src": csv_rows[0]["src"], "line": csv_rows[0]["line"]}]})  # 지어낸 금액 → 버림
        return {"sentences": sents}

    out = tmp_path / "out"
    result = run_all.run(CASE, out, llm=FakeLLM({"roles": roles_answer, "narrative": narrative_answer}, log=None))
    assert result["roles"]["accuracy"] == 1.0 and result["roles"]["uncited"] == 0
    assert result["narrative"] == {**result["narrative"], "kept": 3, "dropped": 1, "bad_reference": 0}
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "## 6. 사건 경위" in md and "## 7. 검토 필요 항목" in md
    assert "1억원" not in md
    assert "운영자(리딩방 주도)" in md and "제안, 검토 필요" in md
    reviews = json.loads((out / "needs_review.json").read_text(encoding="utf-8"))
    assert any(r["category"] == "narrative_dropped" for r in reviews)
    assert (out / "narrative.json").exists() and (out / "roles.json").exists()
    assert result["report"]["unsupported_ratio"] == 0.0
