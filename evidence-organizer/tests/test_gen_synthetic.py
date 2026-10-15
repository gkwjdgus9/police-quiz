"""합성 데이터 생성기 검증: 결정적이고, 라벨이 실제 파일 내용과 맞아야 한다."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_synthetic", ROOT / "scripts" / "gen_synthetic.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod  # dataclass 가 모듈 네임스페이스를 찾을 수 있게 먼저 등록
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gen_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("synthetic")
    gen = _load_gen()
    sys.argv = ["gen_synthetic.py", "--out", str(out)]
    gen.main()
    return out


@pytest.fixture(scope="module")
def case_dir(gen_root: Path) -> Path:
    return gen_root / "case01"


def test_files_exist(case_dir: Path) -> None:
    for rel in ["raw/kakao_mobile.txt", "raw/transfers_kb.csv", "variants/kakao_pc.txt", "labels.json", "case.json"]:
        assert (case_dir / rel).exists(), rel


def test_chat_line_count_about_500(case_dir: Path) -> None:
    n = len((case_dir / "raw" / "kakao_mobile.txt").read_text(encoding="utf-8").splitlines())
    assert 450 <= n <= 560


def test_csv_has_20_rows(case_dir: Path) -> None:
    lines = (case_dir / "raw" / "transfers_kb.csv").read_text(encoding="utf-8-sig").splitlines()
    assert len(lines) == 21  # 헤더 + 20


def test_labels_match_chat_text(case_dir: Path) -> None:
    labels = json.loads((case_dir / "labels.json").read_text(encoding="utf-8"))
    chat = (case_dir / "raw" / "kakao_mobile.txt").read_text(encoding="utf-8")
    digits_in_chat = chat  # 하이픈 유무가 섞여 있으므로 숫자만 비교
    for acc in labels["chat"]["accounts"]:
        assert acc in "".join(ch if ch.isdigit() else " " for ch in digits_in_chat.replace("-", "")), acc
    for url in labels["chat"]["urls"]:
        assert url in chat, url
    for wallet in labels["chat"]["wallets"]:
        assert wallet in chat, wallet
    for unit in labels["chat"]["amount_mentions_korean_unit"]:
        assert unit in chat, unit


def test_labels_fraud_rows_point_at_csv(case_dir: Path) -> None:
    labels = json.loads((case_dir / "labels.json").read_text(encoding="utf-8"))
    lines = (case_dir / "raw" / "transfers_kb.csv").read_text(encoding="utf-8-sig").splitlines()
    assert len(labels["fraud_transfers"]) == 12
    for row in labels["fraud_transfers"]:
        ev = row["evidence"]
        assert ev["src"] == "transfers_kb.csv"
        csv_line = lines[ev["line"] - 1]
        assert row["to_account_raw"] in csv_line
        assert f"{row['amount']:,}" in csv_line
    assert labels["fraud_total"] == sum(r["amount"] for r in labels["fraud_transfers"])


def test_deterministic(gen_root: Path, tmp_path: Path) -> None:
    gen = _load_gen()
    sys.argv = ["gen_synthetic.py", "--out", str(tmp_path)]
    gen.main()
    for case in ("case01", "case02"):
        for rel in ["raw/kakao_mobile.txt", "raw/transfers_kb.csv", "labels.json"]:
            assert (tmp_path / case / rel).read_bytes() == (gen_root / case / rel).read_bytes(), f"{case}/{rel}"


@pytest.mark.parametrize("case", ["case01", "case02"])
def test_committed_cases_are_up_to_date(gen_root: Path, case: str) -> None:
    """저장소에 커밋된 data/synthetic/<case> 가 생성기 출력과 같아야 한다 (PNG 는 PIL 버전에 따라 바이트가 달라 제외)."""
    committed = ROOT / "data" / "synthetic" / case
    if not committed.exists():
        pytest.skip(f"{case} 미생성")
    for rel in ["raw/kakao_mobile.txt", "raw/transfers_kb.csv", "variants/kakao_pc.txt", "labels.json"]:
        assert (committed / rel).read_bytes() == (gen_root / case / rel).read_bytes(), rel


def test_case02_shares_values_with_case01(gen_root: Path) -> None:
    l1 = json.loads((gen_root / "case01" / "labels.json").read_text(encoding="utf-8"))
    l2 = json.loads((gen_root / "case02" / "labels.json").read_text(encoding="utf-8"))
    shared = l2["shared_with"]["case01"]
    for key in ("accounts", "phones", "urls"):
        assert set(shared[key]) <= set(l1["chat"][key]) and set(shared[key]) <= set(l2["chat"][key]), key
    # 공유하지 않는 값은 실제로 달라야 한다
    assert set(l1["chat"]["accounts"]) & set(l2["chat"]["accounts"]) == set(shared["accounts"])
    assert set(l1["chat"]["phones"]) & set(l2["chat"]["phones"]) == set(shared["phones"])
    assert l1["victim"] != l2["victim"]


def test_screenshot_labels_match_image(case_dir: Path) -> None:
    labels = json.loads((case_dir / "labels.json").read_text(encoding="utf-8"))
    if not labels["screenshots"]:
        pytest.skip("PIL/한글 폰트 없음")
    (name, shot), = labels["screenshots"].items()
    png = case_dir / "raw" / name
    assert png.exists() and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert name.startswith("Screenshot_20260822-1030")
    joined = "\n".join(shot["lines"])
    assert "352-1234-5678-93" in joined and "3,000,000원" in joined
    assert shot["accounts"] == ["3521234567893"] and shot["amounts"] == [3_000_000]
