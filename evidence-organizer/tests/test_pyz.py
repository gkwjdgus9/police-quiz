"""한 파일 배포본: 빌드 → 임시 폴더에서 실제로 띄움 → 합성 사건 실행 → 결과 화면."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _get(url: str, timeout: float = 10) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8")


def test_build_and_run_pyz(tmp_path: Path) -> None:
    build = _load("build_pyz", ROOT / "scripts" / "build_pyz.py")
    pyz = build.build(tmp_path / "dist" / "evidence-organizer.pyz")
    assert pyz.exists() and pyz.stat().st_size > 100_000

    proc = subprocess.Popen([sys.executable, str(pyz), "--no-browser"], cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        url = None
        deadline = time.time() + 20
        while time.time() < deadline:
            line = proc.stdout.readline()
            m = re.search(r"http://127\.0\.0\.1:\d+/", line)
            if m:
                url = m.group(0)
                break
            if proc.poll() is not None:
                break
        assert url, "앱이 주소를 출력하지 않음"
        data_home = tmp_path / "dist" / "evidence-organizer-data"
        assert (data_home / "data" / "synthetic" / "case01" / "raw" / "kakao_mobile.txt").exists()  # 번들이 풀렸다

        body = _get(url)
        assert "case01" in body and "case02" in body
        _get(url + "run?case=case01")
        for _ in range(100):
            body = _get(url + "status?case=case01")
            if "완료" in body or "오류" in body:
                break
            time.sleep(0.2)
        assert "완료" in body, body[-800:]
        ledger = json.loads((data_home / "out" / "case01" / "ledger.json").read_text(encoding="utf-8"))
        assert sum(r["status"] == "confirmed" for r in ledger) == 13
        result = _get(url + "result?case=case01")
        assert "범죄일람표" in result and "3521234567893" in result
        assert (data_home / "out" / "case01" / "manifest.json").exists()  # 산출물은 .pyz 옆 데이터 폴더에
    finally:
        proc.kill()
        proc.wait(timeout=5)
