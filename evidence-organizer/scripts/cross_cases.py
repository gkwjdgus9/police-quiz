"""사건 간 교차 조회 실행기 (3단계).

  python scripts/cross_cases.py [--out out] [--cases case01 case02 ...] [--labels-root data/synthetic]

out/<case>/extracted.json 이 있는 사건을 모두 읽어(또는 --cases 로 지정) out/crosscase/ 에
shared.json, shared.md, evaluate.md 를 쓴다. 먼저 사건마다 run_all.py 를 돌려 둬야 한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eo.crosscase import CaseIndex, evaluate_shared, find_shared, render_markdown  # noqa: E402


def run(out_root: Path, case_names: list[str] | None = None, labels_root: Path | None = None) -> dict:
    dirs = [d for d in sorted(out_root.iterdir()) if d.is_dir() and (d / "extracted.json").exists()] if not case_names else [out_root / c for c in case_names]
    cases = [CaseIndex.load(d) for d in dirs]
    if len(cases) < 2:
        raise SystemExit(f"교차 조회에는 사건이 2건 이상 필요합니다 (발견 {len(cases)}건): 먼저 run_all.py 를 사건마다 실행")
    shared = find_shared(cases)
    target = out_root / "crosscase"
    target.mkdir(parents=True, exist_ok=True)
    (target / "shared.json").write_text(json.dumps([s.to_dict() for s in shared], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = render_markdown(shared, cases)
    (target / "shared.md").write_text(md, encoding="utf-8")
    print(md)

    result: dict = {"cases": [c.case for c in cases], "shared": len(shared)}
    labels_by_case = {}
    for c in cases:
        lp = (labels_root or ROOT / "data" / "synthetic") / c.case / "labels.json"
        if lp.exists():
            labels_by_case[c.case] = json.loads(lp.read_text(encoding="utf-8"))
    if labels_by_case:
        ev = evaluate_shared(shared, labels_by_case)
        result["evaluate"] = ev
        table = "| 교차 조회 | 정답 | 예측 | TP | 재현율 | 정밀도 | 누락/오탐 |\n|---|---|---|---|---|---|---|\n"
        note = ", ".join([*(f"누락 {m}" for m in ev["missing"][:3]), *(f"오탐 {x}" for x in ev["extra"][:3])]) or "-"
        table += f"| 공유 값 | {ev['tp'] + ev['fn']} | {ev['tp'] + ev['fp']} | {ev['tp']} | {ev['recall']:.0%} | {ev['precision']:.0%} | {note} |\n"
        (target / "evaluate.md").write_text(f"# 교차 조회 평가\n\n{table}", encoding="utf-8")
        print(table)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "out")
    ap.add_argument("--cases", nargs="*", default=None)
    ap.add_argument("--labels-root", type=Path, default=None)
    args = ap.parse_args(argv)
    run(args.out, args.cases, args.labels_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
