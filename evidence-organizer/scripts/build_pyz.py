"""한 파일 배포본(evidence-organizer.pyz) 빌드.

  python scripts/build_pyz.py [--out dist/evidence-organizer.pyz]

코드(app.py, src/eo, scripts/*.py)와 합성 사건(data/synthetic)과 문서를 zipapp 하나로 묶는다.
실행: python evidence-organizer.pyz   (Windows 는 더블클릭, 파일 옆에 evidence-organizer-data/ 가 생긴다)
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE_SCRIPTS = ["run_all.py", "cross_cases.py", "gen_synthetic.py", "check_llm.py"]
SYN_SUFFIXES = {".txt", ".csv", ".json", ".png", ".jpg"}


def build(target: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        (stage / "scripts").mkdir(parents=True)
        shutil.copy(ROOT / "app.py", stage / "app.py")
        (stage / "__main__.py").write_text("import app\n\napp.main()\n", encoding="utf-8")
        shutil.copytree(ROOT / "src" / "eo", stage / "src" / "eo", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name in INCLUDE_SCRIPTS:
            shutil.copy(ROOT / "scripts" / name, stage / "scripts" / name)
        for p in (ROOT / "data" / "synthetic").rglob("*"):
            if p.is_file() and p.suffix.lower() in SYN_SUFFIXES and "variants" not in p.parts:
                dest = stage / p.relative_to(ROOT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(p, dest)
        for doc in ("README.md", "CLAUDE.md"):
            shutil.copy(ROOT / doc, stage / doc)
        target.parent.mkdir(parents=True, exist_ok=True)
        zipapp.create_archive(stage, target, interpreter="/usr/bin/env python3", compressed=True)
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "dist" / "evidence-organizer.pyz")
    args = ap.parse_args()
    out = build(args.out)
    print(f"빌드 완료: {out} ({out.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
