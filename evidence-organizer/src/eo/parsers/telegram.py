"""텔레그램 내보내기 파서. 1단계 범위 밖이라 자리만 잡아 둔다."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from eo.schema import Event


def parse_telegram(path: Path) -> Iterator[Event]:
    """아직 구현되지 않았다. 추측으로 파싱하지 않고 명시적으로 실패한다."""
    raise NotImplementedError("텔레그램 파서는 아직 구현되지 않았습니다.")
