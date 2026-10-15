"""카카오톡 파서: 형식 감지, 시각 변환, 여러 줄 메시지, 모바일·PC 동치성."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from eo.parsers.kakao import SYSTEM_ACTOR, detect_format, parse_kakao, parse_kakao_lines
from eo.schema import KST

CASE = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "case01"

MOBILE = """홍길동 님과 카카오톡 대화
저장한 날짜 : 2026년 10월 15일 오후 3:30

2026년 10월 15일 목요일
2026년 10월 15일 오전 12:05, 홍길동 : 자정 넘어 보낸 메시지
2026년 10월 15일 오후 12:30, 김영희 : 점심 메시지
2026년 10월 15일 오후 3:17, 홍길동 : 첫 줄
둘째 줄
셋째 줄
2026년 10월 15일 오후 3:18, 김영희님이 들어왔습니다.
2026년 10월 15일 오후 3:20, 김영희 : 콜론 : 포함 : 메시지
""".splitlines()

PC = """홍길동 님과 카카오톡 대화
저장한 날짜 : 2026-10-15 15:30:00

--------------- 2026년 10월 15일 목요일 ---------------
[홍길동] [오전 12:05] 자정 넘어 보낸 메시지
[김영희] [오후 12:30] 점심 메시지
[홍길동] [오후 3:17] 첫 줄
둘째 줄
셋째 줄
--------------- 2026년 10월 16일 금요일 ---------------
[김영희] [오전 9:00] 다음 날
""".splitlines()


def test_detect_mobile_and_pc() -> None:
    assert detect_format(MOBILE) == "mobile"
    assert detect_format(PC) == "pc"


def test_detect_fails_on_unknown() -> None:
    with pytest.raises(ValueError):
        detect_format(["이건 대화가 아닙니다", "그냥 텍스트"])


def test_mobile_times_and_lines() -> None:
    ev = list(parse_kakao_lines(MOBILE, src="m.txt", fmt="mobile"))
    assert [e.line for e in ev] == [5, 6, 7, 10, 11]
    assert ev[0].ts == datetime(2026, 10, 15, 0, 5, tzinfo=KST)   # 오전 12:05 → 00:05
    assert ev[1].ts == datetime(2026, 10, 15, 12, 30, tzinfo=KST)  # 오후 12:30 → 12:30
    assert ev[2].ts == datetime(2026, 10, 15, 15, 17, tzinfo=KST)
    assert all(e.ts.tzinfo is not None for e in ev)
    assert all(e.src == "m.txt" and e.kind == "message" for e in ev)


def test_mobile_multiline_joined_with_first_line_number() -> None:
    ev = list(parse_kakao_lines(MOBILE, src="m.txt", fmt="mobile"))
    assert ev[2].actor == "홍길동"
    assert ev[2].text == "첫 줄\n둘째 줄\n셋째 줄"
    assert ev[2].line == 7


def test_mobile_system_message_and_colon_in_text() -> None:
    ev = list(parse_kakao_lines(MOBILE, src="m.txt", fmt="mobile"))
    assert ev[3].actor == SYSTEM_ACTOR and ev[3].text == "김영희님이 들어왔습니다."
    assert ev[4].actor == "김영희" and ev[4].text == "콜론 : 포함 : 메시지"


def test_pc_date_header_and_multiline() -> None:
    ev = list(parse_kakao_lines(PC, src="p.txt", fmt="pc"))
    assert [e.line for e in ev] == [5, 6, 7, 11]
    assert ev[0].ts == datetime(2026, 10, 15, 0, 5, tzinfo=KST)
    assert ev[2].text == "첫 줄\n둘째 줄\n셋째 줄"
    assert ev[3].ts == datetime(2026, 10, 16, 9, 0, tzinfo=KST)


def test_pc_system_message_without_time() -> None:
    lines = ["--------------- 2026년 10월 15일 목요일 ---------------", "[홍길동] [오전 9:00] 안녕", "김영희님이 들어왔습니다.", "[김영희] [오전 9:01] 네"]
    ev = list(parse_kakao_lines(lines, src="p.txt", fmt="pc"))
    assert [e.actor for e in ev] == ["홍길동", SYSTEM_ACTOR, "김영희"]
    assert ev[1].ts == ev[0].ts and ev[1].meta == {"ts_inferred": True}
    assert ev[0].text == "안녕"


def test_pc_message_before_header_fails() -> None:
    with pytest.raises(ValueError):
        list(parse_kakao_lines(["[홍길동] [오전 9:00] 날짜 없음"], src="p.txt", fmt="pc"))


def test_header_lines_are_ignored() -> None:
    ev = list(parse_kakao_lines(MOBILE, src="m.txt", fmt="mobile"))
    assert not any("저장한 날짜" in e.text for e in ev)


@pytest.mark.skipif(not CASE.exists(), reason="case01 미생성")
def test_synthetic_mobile_and_pc_are_equivalent() -> None:
    mobile = list(parse_kakao(CASE / "raw" / "kakao_mobile.txt"))
    pc = list(parse_kakao(CASE / "variants" / "kakao_pc.txt"))
    assert len(mobile) == len(pc)
    for a, b in zip(mobile, pc):
        assert (a.actor, a.text) == (b.actor, b.text)
        if a.actor == SYSTEM_ACTOR:
            # PC 변형은 시스템 메시지에 시각이 없어 직전 메시지 시각으로 추정하고 표시한다.
            assert b.meta.get("ts_inferred") is True and b.ts.date() == a.ts.date()
        else:
            assert a.ts == b.ts
    assert len(mobile) >= 300
    assert mobile == sorted(mobile, key=lambda e: e.ts)


@pytest.mark.skipif(not CASE.exists(), reason="case01 미생성")
def test_synthetic_mobile_line_numbers_point_at_source() -> None:
    lines = (CASE / "raw" / "kakao_mobile.txt").read_text(encoding="utf-8").splitlines()
    for e in parse_kakao(CASE / "raw" / "kakao_mobile.txt"):
        first = e.text.split("\n", 1)[0]
        assert first in lines[e.line - 1]
