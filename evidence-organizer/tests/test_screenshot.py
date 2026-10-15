"""screenshot 파서 + OCR 어댑터."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from eo.ocr import FakeOCR, TesseractOCR
from eo.parsers.screenshot import SCREENSHOT_ACTOR, parse_screenshot, ts_from_filename
from eo.schema import KST
from eo.timeline import build_timeline


@pytest.mark.parametrize(
    "name,expected",
    [
        ("KakaoTalk_20260822_103052123.png", datetime(2026, 8, 22, 10, 30, 52, tzinfo=KST)),
        ("Screenshot_20260822-103052.png", datetime(2026, 8, 22, 10, 30, 52, tzinfo=KST)),
        ("IMG_20260905_101729.jpg", datetime(2026, 9, 5, 10, 17, 29, tzinfo=KST)),
        ("2026-08-22 10.30.52.png", datetime(2026, 8, 22, 10, 30, 52, tzinfo=KST)),
        ("capture.png", None),
        ("20261399_999999.png", None),  # 말이 안 되는 날짜
    ],
)
def test_ts_from_filename(name: str, expected: datetime | None) -> None:
    assert ts_from_filename(name) == expected


def test_no_engine_yields_empty_event(tmp_path: Path) -> None:
    p = tmp_path / "Screenshot_20260822-103052.png"
    p.write_bytes(b"\x89PNG")
    ev = list(parse_screenshot(p, ocr=None))
    assert len(ev) == 1 and ev[0].kind == "screenshot" and ev[0].line == 0 and ev[0].text == ""
    assert ev[0].meta["ocr"] == "none" and ev[0].meta["ts_source"] == "filename"


def test_fake_ocr_lines_become_events_with_line_numbers(tmp_path: Path) -> None:
    p = tmp_path / "Screenshot_20260822-103052.png"
    p.write_bytes(b"\x89PNG")
    ocr = FakeOCR({p.name: ["이체가 완료되었습니다", "", "받는분 주식회사 골드라인", "농협 352-1234-5678-93", "3,000,000원"]})
    work = tmp_path / "work"
    ev = list(parse_screenshot(p, ocr=ocr, work_dir=work))
    assert [e.line for e in ev] == [1, 3, 4, 5]  # 빈 줄은 건너뛰되 줄 번호는 유지
    assert all(e.actor == SCREENSHOT_ACTOR and e.src == p.name for e in ev)
    saved = (work / f"{p.name}.txt").read_text(encoding="utf-8").splitlines()
    assert saved[3] == "농협 352-1234-5678-93"  # [이미지:4] 가 실제로 그 줄을 가리킨다
    tl, _ = build_timeline(ev)
    assert tl[2].extracted["accounts"] == ["3521234567893"] and tl[3].extracted["amounts"] == [3_000_000]


def test_mtime_fallback_is_flagged(tmp_path: Path) -> None:
    p = tmp_path / "capture.png"
    p.write_bytes(b"\x89PNG")
    ev = list(parse_screenshot(p, ocr=FakeOCR({"capture.png": []})))
    assert ev[0].meta["ts_inferred"] is True and ev[0].meta.get("empty") is True and ev[0].line == 0


def test_ocr_error_is_recorded(tmp_path: Path) -> None:
    p = tmp_path / "IMG_20260905_101729.jpg"
    p.write_bytes(b"\xff\xd8")
    ev = list(parse_screenshot(p, ocr=FakeOCR({})))  # 응답 없음 → OCRError
    assert ev[0].meta["ocr"] == "error" and "error" in ev[0].meta


def test_tesseract_unavailable_here() -> None:
    assert TesseractOCR(binary="tesseract-does-not-exist").is_available() is False
