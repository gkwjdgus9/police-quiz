"""캡처 이미지 파서 (3단계).

- 시각은 파일명에서 읽는다 (KakaoTalk_20260822_103052xxx.png, Screenshot_20260822-103052.png, IMG_20260822_103052.jpg,
  20260822_103052.png). 파일명에 없으면 파일 수정 시각을 쓰되 meta.ts_inferred=True 로 표시한다.
- OCR 엔진이 있으면 줄마다 Event(kind="screenshot") 를 yield 한다. line 은 OCR 결과의 줄 번호이고,
  OCR 전문은 work_dir/<이미지명>.txt 에 그대로 저장해 [이미지명:줄] 근거를 사람이 확인할 수 있게 한다.
- 엔진이 없으면 text 가 빈 Event 하나를 line=0 으로 yield 하고 meta.ocr="none" 을 남긴다.
  (line=0 은 '행 없음'을 뜻하며 보고서 근거로는 쓰이지 않는다.)
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from eo.ocr import OCREngine, OCRError
from eo.schema import KST, Event

SCREENSHOT_ACTOR = "(screenshot)"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

_TS_PATTERNS = [
    re.compile(r"(?P<y>20\d{2})(?P<mo>\d{2})(?P<d>\d{2})[-_](?P<h>\d{2})(?P<mi>\d{2})(?P<s>\d{2})"),  # 20260822_103052 / 20260822-103052
    re.compile(r"(?P<y>20\d{2})-(?P<mo>\d{2})-(?P<d>\d{2})[ T_-](?P<h>\d{2})[.:-](?P<mi>\d{2})[.:-](?P<s>\d{2})"),  # 2026-08-22 10.30.52
]


def ts_from_filename(name: str) -> datetime | None:
    for rx in _TS_PATTERNS:
        m = rx.search(name)
        if m:
            try:
                return datetime(int(m["y"]), int(m["mo"]), int(m["d"]), int(m["h"]), int(m["mi"]), int(m["s"]), tzinfo=KST)
            except ValueError:
                continue
    return None


def parse_screenshot(path: Path, *, ocr: OCREngine | None, work_dir: Path | None = None) -> Iterator[Event]:
    ts = ts_from_filename(path.name)
    meta: dict = {"image": path.name}
    if ts is None:
        ts = datetime.fromtimestamp(path.stat().st_mtime, tz=KST)
        meta["ts_inferred"] = True
        meta["ts_source"] = "mtime"
    else:
        meta["ts_source"] = "filename"

    if ocr is None:
        yield Event(ts=ts, kind="screenshot", actor=SCREENSHOT_ACTOR, text="", src=path.name, line=0, meta={**meta, "ocr": "none"})
        return

    try:
        lines = ocr.recognize(path)
    except OCRError as e:
        yield Event(ts=ts, kind="screenshot", actor=SCREENSHOT_ACTOR, text="", src=path.name, line=0, meta={**meta, "ocr": "error", "error": str(e)})
        return

    if work_dir is not None:
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / f"{path.name}.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    any_line = False
    for lineno, text in enumerate(lines, start=1):
        if not text.strip():
            continue
        any_line = True
        yield Event(ts=ts, kind="screenshot", actor=SCREENSHOT_ACTOR, text=text.rstrip(), src=path.name, line=lineno, meta={**meta, "ocr": ocr.name})
    if not any_line:
        yield Event(ts=ts, kind="screenshot", actor=SCREENSHOT_ACTOR, text="", src=path.name, line=0, meta={**meta, "ocr": ocr.name, "empty": True})
