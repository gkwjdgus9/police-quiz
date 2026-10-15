"""타임라인: 여러 파서의 Event 를 시각순으로 병합하고, 추출값을 근거와 함께 집계한다."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from eo.extract import enrich_event
from eo.schema import EXTRACTED_KEYS, Event, Evidence, ReviewItem


def build_timeline(events: Iterable[Event]) -> tuple[list[Event], list[ReviewItem]]:
    """이벤트를 추출·병합한다. 반환: (시각순 이벤트 목록, 해석 보류 항목 목록).

    같은 시각이면 입력 순서를 유지한다(stable sort).
    """
    out: list[Event] = []
    reviews: list[ReviewItem] = []
    for ev in events:
        for raw in enrich_event(ev):
            reviews.append(ReviewItem(
                category="amount_ambiguous",
                reason="금액 표기가 모호해('3천' 처럼 원·만 단위 없음) 환산하지 않음",
                value=raw,
                evidence=[ev.evidence],
            ))
        out.append(ev)
    out.sort(key=lambda e: e.ts)
    return out, reviews


def aggregate_extracted(events: Iterable[Event], *, kinds: tuple[str, ...] = ("message", "screenshot")) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """추출값별 근거 목록. {"accounts": {"3521234567893": [{"src","line"}, ...]}, ...}

    기본적으로 대화(message)와 캡처 OCR(screenshot)에서 추출된 값을 집계한다. 이체 CSV 의 계좌는 구조화 컬럼에서 온 것이라 따로 다룬다.
    """
    agg: dict[str, dict[str, list[dict[str, Any]]]] = {k: {} for k in EXTRACTED_KEYS}
    for ev in events:
        if ev.kind not in kinds:
            continue
        for key in EXTRACTED_KEYS:
            for value in ev.extracted.get(key, []):
                agg[key].setdefault(str(value), []).append(ev.evidence.to_dict())
    return agg


def write_timeline_jsonl(events: Iterable[Event], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev.to_dict(), ensure_ascii=False) + "\n")


def read_timeline_jsonl(path: Path) -> list[Event]:
    events: list[Event] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                events.append(Event.from_dict(json.loads(line)))
    return events


def write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def _json_default(o: Any) -> Any:
    if isinstance(o, Evidence):
        return o.to_dict()
    if hasattr(o, "to_dict"):
        return o.to_dict()
    raise TypeError(f"JSON 직렬화 불가: {type(o)}")
