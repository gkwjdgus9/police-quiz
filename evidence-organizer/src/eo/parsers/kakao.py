"""카카오톡 대화 내보내기 파서.

지원 형식
  모바일(Android): "2026년 10월 15일 오후 3:17, 홍길동 : 메시지"
                   시스템 메시지: "2026년 10월 15일 오후 3:17, 홍길동님이 들어왔습니다."
                   날짜 구분선:   "2026년 10월 15일 목요일"
  PC:              날짜 헤더 "--------------- 2026년 10월 15일 목요일 ---------------"
                   메시지     "[홍길동] [오후 3:17] 메시지"

- 첫 20줄로 형식을 자동 감지한다. 감지 실패 시 추측하지 않고 ValueError.
- 여러 줄 메시지는 다음 타임스탬프 줄까지 이어 붙이고, line 은 첫 줄 번호다.
- 모든 ts 는 KST tz-aware. 내보내기에 초 단위가 없으므로 초는 0.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Literal

from eo.schema import KST, Event

Format = Literal["mobile", "pc"]

DETECT_LINES = 20
SYSTEM_ACTOR = "(system)"

_DATE = r"(?P<y>\d{4})년 (?P<mo>\d{1,2})월 (?P<d>\d{1,2})일"
_TIME = r"(?P<ap>오전|오후) (?P<h>\d{1,2}):(?P<mi>\d{2})"

# 모바일: 날짜 시각, 발신자 : 본문   (발신자에 ' : ' 가 들어갈 수 없다는 가정, 첫 ' : ' 에서 자른다)
RE_MOBILE_MSG = re.compile(rf"^{_DATE} {_TIME}, (?P<actor>[^:]+?) : (?P<text>.*)$")
# 모바일 시스템 메시지: 날짜 시각, 본문 (' : ' 없음)
RE_MOBILE_SYS = re.compile(rf"^{_DATE} {_TIME}, (?P<text>.*)$")
# 날짜 구분선(모바일/iOS) 및 PC 날짜 헤더(대시로 감쌈)
RE_DATE_SEP = re.compile(rf"^-*\s*{_DATE} (?P<wd>[월화수목금토일])요일\s*-*$")
# PC 메시지
RE_PC_MSG = re.compile(rf"^\[(?P<actor>[^\]]+)\] \[{_TIME}\] (?P<text>.*)$")
# PC 형식의 시스템 메시지는 시각 없이 한 줄로 나온다. 알려진 문구만 인식하고 그 외는 이어지는 줄로 본다.
RE_PC_SYS = re.compile(r"^(?P<text>.+님이 (들어왔습니다|나갔습니다|내보내졌습니다)\.)$")


def _to_24h(ap: str, h: int) -> int:
    h = h % 12
    return h + 12 if ap == "오후" else h


def _make_ts(y: int, mo: int, d: int, ap: str, h: int, mi: int) -> datetime:
    return datetime(y, mo, d, _to_24h(ap, h), mi, tzinfo=KST)


def detect_format(lines: Iterable[str]) -> Format:
    """첫 DETECT_LINES 줄에서 모바일/PC 메시지 패턴 수를 세어 결정한다."""
    mobile = pc = 0
    for i, line in enumerate(lines):
        if i >= DETECT_LINES:
            break
        line = line.rstrip("\n")
        if RE_MOBILE_MSG.match(line) or RE_MOBILE_SYS.match(line):
            mobile += 1
        elif RE_PC_MSG.match(line):
            pc += 1
        elif line.startswith("---") and RE_DATE_SEP.match(line):
            pc += 1
    if mobile == 0 and pc == 0:
        raise ValueError(f"카카오톡 내보내기 형식을 감지하지 못했습니다(첫 {DETECT_LINES}줄에 메시지 없음)")
    if mobile == pc:
        raise ValueError("카카오톡 형식이 모호합니다(모바일/PC 패턴 수가 같음)")
    return "mobile" if mobile > pc else "pc"


def _read_lines(path: Path) -> list[str]:
    # 카카오톡 내보내기는 UTF-8(BOM 가능). 실패하면 cp949 를 시도하되 그 외는 추측하지 않는다.
    data = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc).splitlines()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"인코딩을 판별하지 못했습니다: {path}")


def parse_kakao(path: Path, *, fmt: Format | None = None) -> Iterator[Event]:
    """카카오톡 내보내기 파일을 읽어 Event 를 yield 한다. src 는 파일명(basename)."""
    lines = _read_lines(path)
    fmt = fmt or detect_format(lines)
    yield from parse_kakao_lines(lines, src=path.name, fmt=fmt)


def parse_kakao_lines(lines: Iterable[str], *, src: str, fmt: Format) -> Iterator[Event]:
    cur: Event | None = None
    cur_date: tuple[int, int, int] | None = None  # PC 형식에서 날짜 헤더로 갱신
    last_ts: datetime | None = None  # PC 형식 시스템 메시지의 시각 추정용

    def flush() -> Iterator[Event]:
        nonlocal cur
        if cur is not None:
            cur.text = cur.text.rstrip("\n")
            yield cur
            cur = None

    for lineno, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")

        sep = RE_DATE_SEP.match(line)
        if sep:
            yield from flush()
            cur_date = (int(sep["y"]), int(sep["mo"]), int(sep["d"]))
            continue

        if fmt == "mobile":
            m = RE_MOBILE_MSG.match(line)
            if m:
                yield from flush()
                ts = _make_ts(int(m["y"]), int(m["mo"]), int(m["d"]), m["ap"], int(m["h"]), int(m["mi"]))
                cur = Event(ts=ts, kind="message", actor=m["actor"].strip(), text=m["text"], src=src, line=lineno)
                continue
            m = RE_MOBILE_SYS.match(line)
            if m:
                yield from flush()
                ts = _make_ts(int(m["y"]), int(m["mo"]), int(m["d"]), m["ap"], int(m["h"]), int(m["mi"]))
                cur = Event(ts=ts, kind="message", actor=SYSTEM_ACTOR, text=m["text"], src=src, line=lineno)
                continue
        else:
            m = RE_PC_MSG.match(line)
            if m:
                yield from flush()
                if cur_date is None:
                    raise ValueError(f"{src}:{lineno} 날짜 헤더보다 메시지가 먼저 나왔습니다")
                ts = _make_ts(*cur_date, m["ap"], int(m["h"]), int(m["mi"]))
                cur = Event(ts=ts, kind="message", actor=m["actor"].strip(), text=m["text"], src=src, line=lineno)
                last_ts = ts
                continue
            m = RE_PC_SYS.match(line)
            if m and cur_date is not None:
                # 시각이 없으므로 직전 메시지 시각(같은 날이 아니면 그날 0시)을 쓰고 meta 에 표시한다.
                yield from flush()
                ts = last_ts if (last_ts is not None and (last_ts.year, last_ts.month, last_ts.day) == cur_date) else datetime(*cur_date, tzinfo=KST)
                cur = Event(ts=ts, kind="message", actor=SYSTEM_ACTOR, text=m["text"], src=src, line=lineno, meta={"ts_inferred": True})
                continue

        # 타임스탬프가 없는 줄: 진행 중인 메시지의 이어지는 줄. 메시지 전(헤더)이라면 버린다.
        if cur is not None:
            cur.text += "\n" + line

    yield from flush()
