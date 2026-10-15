"""합성 사건 데이터 생성기.

투자리딩방 사기 시나리오 1건(case01)을 만들어 data/synthetic/case01/ 에 저장한다.
실제 사건 데이터는 절대 넣지 않는다. 등장하는 이름·계좌·번호·주소는 전부 가공이다.

생성물
  raw/kakao_mobile.txt   카카오톡 모바일(Android) 내보내기 형식, 약 500줄
  raw/transfers_kb.csv   KB국민은행 형식 이체내역 20건
  variants/kakao_pc.txt  같은 대화의 PC 내보내기 형식(파서 테스트용, raw 가 아니므로 파이프라인 입력 아님)
  labels.json            정답 라벨(실제 피해 이체, 등장한 계좌·번호·URL·지갑주소)
  case.json              사건 메타(피해자 이름)

실행: python scripts/gen_synthetic.py [--out data/synthetic/case01]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eo.schema import KST  # noqa: E402

SEED = 20261015
WEEKDAYS_KO = ["월", "화", "수", "목", "금", "토", "일"]

# ----------------------------------------------------------------------------
# 등장인물 / 식별정보 (전부 가공)
# ----------------------------------------------------------------------------
VICTIM = "이수진"
OPERATOR = "박대표"
ASSISTANT = "김실장"
OTHERS = ["최민수", "정하나"]

# 대포통장 3개 (표기 형태는 대화에 등장하는 그대로, 정규화 값은 숫자만)
ACC_NH = "352-1234-5678-93"      # 농협, 13자리
ACC_KAKAO = "3333-05-1234567"    # 카카오뱅크, 13자리
ACC_SHINHAN = "110-456-789012"   # 신한, 12자리
# 무관한 계좌 (회원 회비)
ACC_HANA_MEMBER = "123456-04-567890"  # 국민, 12자리 (정하나)

PHONE_ASSISTANT = "010-4567-8910"
PHONE_OPERATOR = "010-2233-4455"
PHONE_CS = "1600-1234"
PHONE_RESTAURANT = "02-512-3456"

URL_APP = "https://goldline-invest.top/app"
URL_TG = "https://t.me/goldline_vip"
URL_LOGIN = "www.kstock-pro.xyz/login"
URL_SHORT = "http://bit.ly/4gL9xQz"
URL_NAVER = "https://finance.naver.com/item/main.naver?code=005930"

BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _make_wallets(rng: random.Random) -> dict[str, str]:
    tron = "T" + "".join(rng.choice(BASE58) for _ in range(33))
    eth = "0x" + "".join(rng.choice("0123456789abcdef") for _ in range(40))
    btc = "bc1q" + "".join(rng.choice(BECH32) for _ in range(38))
    return {"tron": tron, "eth": eth, "btc": btc}


def norm_digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


# ----------------------------------------------------------------------------
# 이체내역 (피해 12건 + 무관 8건)
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Transfer:
    ts: datetime
    memo: str
    withdraw: int
    deposit: int
    to_account: str
    to_bank: str
    to_name: str
    fraud: bool


def _dt(d: str, t: str) -> datetime:
    return datetime.combine(date.fromisoformat(d), time.fromisoformat(t), tzinfo=KST)


TRANSFERS: list[Transfer] = [
    Transfer(_dt("2026-08-21", "09:00:12"), "급여 (주)한빛테크", 0, 2_850_000, "", "", "", False),
    Transfer(_dt("2026-08-22", "10:30:41"), "골드라인 증거금", 3_000_000, 0, ACC_NH, "농협", "주식회사 골드라인", True),
    Transfer(_dt("2026-08-25", "14:10:05"), "골드라인 추가증거금", 5_000_000, 0, ACC_NH, "농협", "주식회사 골드라인", True),
    Transfer(_dt("2026-08-26", "12:33:50"), "쿠팡", 45_900, 0, "", "", "", False),
    Transfer(_dt("2026-08-28", "11:05:17"), "VIP방 입금", 10_000_000, 0, ACC_KAKAO, "카카오뱅크", "최영철", True),
    Transfer(_dt("2026-08-30", "18:20:33"), "월세", 650_000, 0, "1002-345-678901", "우리", "김영호", False),
    Transfer(_dt("2026-09-01", "09:50:02"), "증거금", 2_000_000, 0, ACC_KAKAO, "카카오뱅크", "최영철", True),
    Transfer(_dt("2026-09-02", "08:10:00"), "KT 통신요금", 89_000, 0, "", "", "", False),
    Transfer(_dt("2026-09-03", "16:20:48"), "증거금 추가", 7_000_000, 0, ACC_NH, "농협", "주식회사 골드라인", True),
    Transfer(_dt("2026-09-05", "10:15:29"), "해외선물 계정", 4_500_000, 0, ACC_SHINHAN, "신한", "강민호", True),
    Transfer(_dt("2026-09-06", "20:05:11"), "모임 회비", 50_000, 0, ACC_HANA_MEMBER, "국민", "정하나", False),
    Transfer(_dt("2026-09-08", "13:40:36"), "VIP 2차", 15_000_000, 0, ACC_KAKAO, "카카오뱅크", "최영철", True),
    Transfer(_dt("2026-09-09", "09:00:00"), "예금이자", 0, 1_230, "", "", "", False),
    Transfer(_dt("2026-09-10", "11:30:54"), "증거금", 3_000_000, 0, ACC_NH, "농협", "주식회사 골드라인", True),
    Transfer(_dt("2026-09-12", "15:05:22"), "출금수수료 보증금", 20_000_000, 0, ACC_SHINHAN, "신한", "강민호", True),
    Transfer(_dt("2026-09-14", "17:45:09"), "어머니 생활비", 3_000_000, 0, "456-910234-56789", "하나", "이정숙", False),
    Transfer(_dt("2026-09-15", "10:40:47"), "세금", 6_000_000, 0, ACC_KAKAO, "카카오뱅크", "최영철", True),
    Transfer(_dt("2026-09-18", "14:25:15"), "보증금 추가", 8_000_000, 0, ACC_SHINHAN, "신한", "강민호", True),
    Transfer(_dt("2026-09-20", "11:11:11"), "ATM출금", 300_000, 0, "", "", "", False),
    Transfer(_dt("2026-09-22", "09:55:38"), "최종 보증금", 12_000_000, 0, ACC_NH, "농협", "주식회사 골드라인", True),
]

OPENING_BALANCE = 48_500_000

# ----------------------------------------------------------------------------
# 대화 시나리오
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Msg:
    d: date
    t: time
    actor: str  # "" 이면 시스템 메시지
    text: str


def _m(d: str, t: str, actor: str, text: str) -> Msg:
    return Msg(date.fromisoformat(d), time.fromisoformat(t), actor, text)


def scripted_beats(w: dict[str, str]) -> list[Msg]:
    """사건의 뼈대가 되는 메시지. 계좌·번호·URL·지갑주소·금액이 여기 들어 있다."""
    V, O, A, C, H = VICTIM, OPERATOR, ASSISTANT, OTHERS[0], OTHERS[1]
    return [
        _m("2026-08-20", "09:00", "", f"{V}님이 들어왔습니다."),
        _m("2026-08-20", "09:02", O, f"{V}님 환영합니다! 골드라인 투자연구소 공식 리딩방입니다.\n매일 아침 종목 브리핑 드리고, 매수/매도 타이밍은 실시간으로 안내합니다.\n궁금한 건 언제든 {A}에게 물어보세요."),
        _m("2026-08-20", "09:05", A, f"안녕하세요 {V}님, 담당 김실장입니다. 개인 문의는 {PHONE_ASSISTANT} 으로 연락주셔도 됩니다."),
        _m("2026-08-20", "09:11", V, "안녕하세요. 지인 소개로 왔는데 주식은 처음이라 잘 모릅니다. 잘 부탁드려요."),
        _m("2026-08-20", "09:13", C, "여기 들어오시면 돈 버십니다 ㅎㅎ 저도 지난달 40% 먹었어요"),
        _m("2026-08-20", "09:14", H, "환영해요~ 저도 초보였는데 실장님이 다 알려주세요"),
        _m("2026-08-21", "10:20", O, f"오늘부터 전용 매매앱 사용합니다. 아래 링크에서 설치하세요.\n{URL_APP}\n설치 후 아이디는 실장에게 받으시면 됩니다."),
        _m("2026-08-21", "10:31", V, "설치했습니다. 아이디는 어떻게 받나요?"),
        _m("2026-08-21", "10:33", A, f"{V}님 아이디 발급해드렸습니다. 로그인은 {URL_LOGIN} 에서 하시면 됩니다."),
        _m("2026-08-21", "10:40", C, f"참고로 삼성전자 차트 {URL_NAVER} 보시면 지금 바닥입니다"),
        _m("2026-08-22", "09:40", O, "오늘 1차 공략주 매수 들어갑니다. 증거금 입금 완료하신 분부터 수량 배정합니다."),
        _m("2026-08-22", "09:52", A, f"{V}님 첫 증거금은 3,000,000원입니다.\n입금계좌: 농협 {ACC_NH} (주식회사 골드라인)\n입금 후 꼭 캡처 보내주세요."),
        _m("2026-08-22", "10:32", V, "방금 3,000,000원 보냈습니다. 확인 부탁드려요."),
        _m("2026-08-22", "10:35", A, "입금 확인했습니다. 앱에서 잔고 반영된 것 확인하세요!"),
        _m("2026-08-22", "15:10", O, "1차 공략주 +12% 마감입니다. 축하드립니다 👏"),
        _m("2026-08-22", "15:12", V, "앱에서 보니까 정말 올랐네요! 신기합니다"),
        _m("2026-08-24", "09:30", O, "이번 주 2차 공략주는 배정 수량이 제한적입니다. 증거금 추가하신 분 우선입니다."),
        _m("2026-08-25", "13:50", A, f"{V}님 2차 증거금 500만원 추가하시면 배정 2배로 드립니다. 계좌는 동일하게 농협 {ACC_NH} 입니다."),
        _m("2026-08-25", "14:12", V, "500만원 보냈어요. 확인해주세요."),
        _m("2026-08-25", "14:15", A, "확인 완료! 2차 배정 들어갔습니다."),
        _m("2026-08-27", "16:00", O, f"VIP방 안내드립니다. 기관 블록딜 물량을 받는 방이라 인원 제한 있습니다.\n참여 희망자는 {A}에게 개별 문의하세요. 텔레그램 {URL_TG} 도 운영합니다."),
        _m("2026-08-28", "10:40", A, f"{V}님 VIP방 참여금은 10,000,000원입니다.\nVIP 전용 계좌: 카카오뱅크 {ACC_KAKAO} (최영철)\n이 계좌는 VIP 전용이라 외부에 공유 금지입니다."),
        _m("2026-08-28", "11:07", V, "10,000,000원 입금했습니다. 금액이 커서 좀 떨리네요.."),
        _m("2026-08-28", "11:09", A, "걱정 마세요. 블록딜은 손실 날 수가 없는 구조입니다. 확인했습니다."),
        _m("2026-09-01", "09:20", A, f"{V}님 오늘 블록딜 추가 수량 나왔습니다. 2,000,000원만 추가하시면 됩니다. 카카오뱅크 {ACC_KAKAO}"),
        _m("2026-09-01", "09:52", V, "2,000,000원 보냈습니다."),
        _m("2026-09-03", "15:55", A, f"{V}님 지금 잔고 기준 수익 23%입니다. 700만원 추가하시면 다음 공략주 수량 더 배정됩니다. 농협 3521234567893 으로 보내주세요."),
        _m("2026-09-03", "16:22", V, "700만원 넣었습니다. 이번엔 꼭 수익 났으면 좋겠어요"),
        _m("2026-09-04", "11:00", O, f"해외선물 파트 신설합니다. 수익률이 국내보다 훨씬 높습니다. 고객센터 {PHONE_CS} 로 문의 가능합니다."),
        _m("2026-09-05", "09:48", A, f"{V}님 해외선물 계정 개설비 4,500,000원입니다.\n계좌: 신한은행 {ACC_SHINHAN} (강민호)\n해외 계정 충전은 USDT(TRC20)로만 가능하고 주소는 아래입니다.\n{w['tron']}"),
        _m("2026-09-05", "10:17", V, "4,500,000원 보냈습니다. USDT는 어떻게 사는 건가요?"),
        _m("2026-09-05", "10:20", A, "그건 저희가 대신 처리해 드립니다. 입금만 해주시면 됩니다."),
        _m("2026-09-06", "19:30", H, f"이번 주 토요일 오프모임 회비 5만원이에요~ 제 계좌 국민 {ACC_HANA_MEMBER} 으로 보내주세요. 장소는 역삼동 한우집 {PHONE_RESTAURANT} 예약했어요"),
        _m("2026-09-06", "20:07", V, "회비 보냈습니다~ 토요일에 봬요"),
        _m("2026-09-08", "13:20", A, f"{V}님 VIP 2차 블록딜 15,000,000원입니다. 카카오뱅크 {ACC_KAKAO} 로 부탁드립니다."),
        _m("2026-09-08", "13:42", V, "15,000,000원 보냈습니다. 이제 총 얼마 들어간 거죠?"),
        _m("2026-09-08", "13:45", A, "앱 잔고 확인하시면 됩니다. 현재 수익 포함 6천만원 넘으셨어요."),
        _m("2026-09-10", "11:10", A, f"{V}님 공략주 추가 3,000,000원 부탁드립니다. 농협 {ACC_NH}"),
        _m("2026-09-10", "11:32", V, "3,000,000원 보냈습니다."),
        _m("2026-09-11", "17:40", V, "대표님 저 이제 출금 좀 하고 싶은데요. 생활비가 필요해서요."),
        _m("2026-09-11", "17:55", O, f"출금은 {A}이 처리합니다. 다만 수익금 출금 시 세무 처리 때문에 보증금이 먼저 필요합니다."),
        _m("2026-09-12", "14:40", A, f"{V}님 출금 보증금은 수익금의 20%인 2천만원입니다. 출금 후 보증금은 바로 환급됩니다.\n신한은행 {ACC_SHINHAN} (강민호)"),
        _m("2026-09-12", "15:08", V, "2천만원 보냈습니다. 그럼 언제 출금되나요?"),
        _m("2026-09-12", "15:10", A, "영업일 기준 3일 이내입니다."),
        _m("2026-09-15", "10:20", A, f"{V}님 출금 심사 중 세금 6,000,000원이 추가로 발생했습니다. 카카오뱅크 {ACC_KAKAO} 로 입금해주셔야 출금 진행됩니다."),
        _m("2026-09-15", "10:42", V, "6,000,000원 보냈습니다. 정말 출금되는 거 맞죠? 불안합니다."),
        _m("2026-09-15", "10:45", O, f"{V}님 걱정 마세요. 본사 대표 직통 {PHONE_OPERATOR} 입니다. 책임지고 처리합니다."),
        _m("2026-09-17", "09:30", C, f"저는 비트코인도 하는데 요즘 지갑 {w['btc']} 로 옮겨놨어요 ㅋㅋ"),
        _m("2026-09-18", "14:00", A, f"{V}님 출금 승인 직전인데 보증금 800만원이 부족합니다. 신한은행 {ACC_SHINHAN} 으로 오늘 중 부탁드립니다."),
        _m("2026-09-18", "14:27", V, "800만원 보냈습니다. 이게 마지막이죠?"),
        _m("2026-09-19", "16:10", O, f"VIP 회원 대상 이더리움 프라이빗 세일 진행합니다. ETH 전용 주소: {w['eth']}"),
        _m("2026-09-22", "09:30", A, f"{V}님 최종 보증금 12,000,000원 입금하시면 전액 출금 처리됩니다. 농협 {ACC_NH} (주식회사 골드라인)"),
        _m("2026-09-22", "09:57", V, "12,000,000원 보냈습니다. 오늘 꼭 출금 부탁드립니다."),
        _m("2026-09-23", "10:00", V, "실장님 출금 언제 되나요? 연락 부탁드립니다."),
        _m("2026-09-23", "15:30", V, f"실장님 전화도 안 받으시네요. {PHONE_ASSISTANT} 맞죠?"),
        _m("2026-09-24", "09:10", V, "대표님 답변 부탁드립니다. 출금이 안 됩니다."),
        _m("2026-09-24", "18:00", V, "앱 로그인도 안 되는데 무슨 일인가요?"),
        _m("2026-09-25", "10:30", C, f"다들 조용하네요.. 단축링크 {URL_SHORT} 는 이제 안 열리는데요?"),
        _m("2026-09-25", "11:00", V, "경찰에 신고하겠습니다."),
    ]


MORNING_STOCKS = ["에코프로", "한화오션", "두산에너빌리티", "포스코퓨처엠", "LG에너지솔루션", "HD현대중공업", "삼성바이오로직스", "셀트리온", "카카오", "현대차"]
REACTIONS = [
    "감사합니다 대표님!", "오늘도 잘 부탁드립니다", "들어갔습니다~", "저도 매수 완료", "ㅋㅋㅋ 대박", "수익 인증합니다 ㅎㅎ",
    "실장님 감사해요", "오늘 수익률 {p}% 찍었네요", "역시 대표님", "다음 공략주 기대됩니다", "저 어제 {p}% 수익 났어요!!",
    "오늘 점심 뭐 드세요 ㅋㅋ", "장 마감 전에 정리하는 게 맞을까요?", "네네 확인했습니다", "👍👍",
]
OPERATOR_NOTICES = [
    "오늘 장 변동성 큽니다. 지시 전까지 절대 개별 매매 하지 마세요.",
    "공략주 목표가 도달했습니다. 전량 매도 지시드립니다.",
    "내일 장 전 브리핑은 오전 8시 50분입니다.",
    "앱 점검 안내: 오늘 밤 11시부터 1시간 점검입니다.",
    "신규 회원 분들은 실장에게 증거금 안내 받으세요.",
]
VICTIM_FILLER = ["네 알겠습니다", "확인했습니다", "감사합니다", "오늘은 어떤 종목인가요?", "매도 타이밍 알려주세요"]


def filler_for_day(rng: random.Random, d: date, w: dict[str, str]) -> list[Msg]:
    """하루치 잡담. 식별정보는 넣지 않는다(라벨과 불일치 방지)."""
    msgs: list[Msg] = []
    if d.weekday() >= 5:  # 주말은 조용
        if rng.random() < 0.5:
            msgs.append(Msg(d, time(11, rng.randrange(0, 59)), rng.choice(OTHERS), rng.choice(REACTIONS).format(p=rng.randrange(3, 30))))
        return msgs
    stock = rng.choice(MORNING_STOCKS)
    brief = (
        "[골드라인 데일리 브리핑]\n"
        f"오늘의 관심 종목: {stock}\n"
        f"목표가 +{rng.randrange(5, 20)}% / 손절 -{rng.randrange(2, 5)}%\n"
        "매수 타이밍은 방에서 실시간 안내드립니다."
    )
    msgs.append(Msg(d, time(8, 50 + rng.randrange(0, 9)), OPERATOR, brief))
    n_react = rng.randrange(5, 10)
    for _ in range(n_react):
        actor = rng.choice(OTHERS + OTHERS + [VICTIM])
        pool = VICTIM_FILLER if actor == VICTIM else REACTIONS
        msgs.append(Msg(d, time(rng.randrange(9, 15), rng.randrange(0, 60)), actor, rng.choice(pool).format(p=rng.randrange(3, 30))))
    if rng.random() < 0.8:
        msgs.append(Msg(d, time(rng.randrange(13, 16), rng.randrange(0, 60)), OPERATOR, rng.choice(OPERATOR_NOTICES)))
        for _ in range(rng.randrange(2, 5)):
            msgs.append(Msg(d, time(rng.randrange(14, 18), rng.randrange(0, 60)), rng.choice(OTHERS), rng.choice(REACTIONS).format(p=rng.randrange(3, 30))))
    return msgs


def build_messages(rng: random.Random, w: dict[str, str]) -> list[Msg]:
    beats = scripted_beats(w)
    start, end = date(2026, 8, 20), date(2026, 9, 25)
    msgs = list(beats)
    d = start
    while d <= end:
        msgs.extend(filler_for_day(rng, d, w))
        d += timedelta(days=1)
    # 날짜·시각 순 정렬. 같은 시각이면 입력 순서 유지(stable).
    msgs.sort(key=lambda m: (m.d, m.t))
    return msgs


# ----------------------------------------------------------------------------
# 렌더링
# ----------------------------------------------------------------------------
def ko_ampm(t: time) -> str:
    """'오전 9:02' / '오후 12:05' 형태. 카카오톡 표기 규칙(12시간제, 시 0패딩 없음)."""
    h = t.hour
    ampm = "오전" if h < 12 else "오후"
    h12 = h % 12
    if h12 == 0:
        h12 = 12
    return f"{ampm} {h12}:{t.minute:02d}"


def ko_date(d: date) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일"


def ko_date_weekday(d: date) -> str:
    return f"{ko_date(d)} {WEEKDAYS_KO[d.weekday()]}요일"


def render_mobile(msgs: list[Msg], saved_at: datetime) -> str:
    lines = [f"{OPERATOR} 님과 카카오톡 대화", f"저장한 날짜 : {ko_date(saved_at.date())} {ko_ampm(saved_at.time())}", ""]
    cur: date | None = None
    for m in msgs:
        if m.d != cur:
            lines.append(ko_date_weekday(m.d))  # 날짜 구분선
            cur = m.d
        stamp = f"{ko_date(m.d)} {ko_ampm(m.t)}"
        if m.actor == "":
            lines.append(f"{stamp}, {m.text}")
        else:
            lines.append(f"{stamp}, {m.actor} : {m.text}")  # 여러 줄 메시지는 \n 그대로 이어짐
    return "\n".join(lines) + "\n"


def render_pc(msgs: list[Msg], saved_at: datetime) -> str:
    lines = [f"{OPERATOR} 님과 카카오톡 대화", f"저장한 날짜 : {saved_at.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    cur: date | None = None
    for m in msgs:
        if m.d != cur:
            lines.append(f"--------------- {ko_date_weekday(m.d)} ---------------")
            cur = m.d
        if m.actor == "":
            lines.append(m.text)  # PC 형식의 시스템 메시지는 시각 없이 한 줄
        else:
            lines.append(f"[{m.actor}] [{ko_ampm(m.t)}] {m.text}")
    return "\n".join(lines) + "\n"


def render_kb_csv(transfers: list[Transfer]) -> tuple[str, list[int]]:
    """KB국민은행 형식 CSV. 반환: (본문, 각 이체의 행 번호 목록)."""
    header = ["거래일시", "적요", "출금액", "입금액", "잔액", "거래점", "상대계좌번호", "상대은행", "받는분"]
    rows = [",".join(header)]
    balance = OPENING_BALANCE
    line_numbers: list[int] = []
    for tr in sorted(transfers, key=lambda x: x.ts):
        balance = balance - tr.withdraw + tr.deposit
        row = [
            tr.ts.strftime("%Y.%m.%d %H:%M:%S"),
            tr.memo,
            f"{tr.withdraw:,}" if tr.withdraw else "",
            f"{tr.deposit:,}" if tr.deposit else "",
            f"{balance:,}",
            "인터넷뱅킹" if tr.to_account or tr.memo.startswith("쿠팡") else "본점",
            tr.to_account,
            tr.to_bank,
            tr.to_name,
        ]
        rows.append(",".join(f'"{c}"' for c in row))
        line_numbers.append(len(rows))
    return "\n".join(rows) + "\n", line_numbers


# ----------------------------------------------------------------------------
# 라벨
# ----------------------------------------------------------------------------
def build_labels(msgs: list[Msg], transfers: list[Transfer], csv_lines: list[int], w: dict[str, str]) -> dict:
    ordered = sorted(transfers, key=lambda x: x.ts)
    fraud = [
        {
            "ts": tr.ts.isoformat(),
            "to_account": norm_digits(tr.to_account),
            "to_account_raw": tr.to_account,
            "bank": tr.to_bank,
            "amount": tr.withdraw,
            "evidence": {"src": "transfers_kb.csv", "line": ln},
        }
        for tr, ln in zip(ordered, csv_lines)
        if tr.fraud
    ]
    return {
        "case": "case01",
        "victim": VICTIM,
        "participants": {VICTIM: "victim", OPERATOR: "operator", ASSISTANT: "assistant", OTHERS[0]: "unrelated", OTHERS[1]: "unrelated"},
        "fraud_transfers": fraud,
        "fraud_total": sum(r["amount"] for r in fraud),
        # 대화(kakao_mobile.txt)에 등장하는 식별정보. 정규화 규칙: 계좌·전화는 숫자만, URL·지갑은 표기 그대로.
        "chat": {
            "accounts": sorted({norm_digits(a) for a in [ACC_NH, ACC_KAKAO, ACC_SHINHAN, ACC_HANA_MEMBER]}),
            "fraud_accounts": sorted({norm_digits(a) for a in [ACC_NH, ACC_KAKAO, ACC_SHINHAN]}),
            "phones": sorted({norm_digits(p) for p in [PHONE_ASSISTANT, PHONE_OPERATOR, PHONE_CS, PHONE_RESTAURANT]}),
            "urls": sorted([URL_APP, URL_TG, URL_LOGIN, URL_SHORT, URL_NAVER]),
            "wallets": sorted(w.values()),
            # '500만원' 식 한국어 단위 표기는 해석 규칙이 확정되지 않아 라벨에서 분리해 둔다.
            "amount_mentions_korean_unit": ["500만원", "700만원", "2천만원", "800만원", "5만원", "6천만원"],
        },
        "message_count": len(msgs),
    }


# ----------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "synthetic" / "case01")
    args = ap.parse_args()

    rng = random.Random(SEED)
    w = _make_wallets(rng)
    msgs = build_messages(rng, w)
    saved_at = datetime(2026, 9, 26, 20, 12, tzinfo=KST)

    out: Path = args.out
    (out / "raw").mkdir(parents=True, exist_ok=True)
    (out / "variants").mkdir(parents=True, exist_ok=True)

    mobile = render_mobile(msgs, saved_at)
    pc = render_pc(msgs, saved_at)
    csv_text, csv_lines = render_kb_csv(TRANSFERS)

    (out / "raw" / "kakao_mobile.txt").write_text(mobile, encoding="utf-8")
    (out / "variants" / "kakao_pc.txt").write_text(pc, encoding="utf-8")
    (out / "raw" / "transfers_kb.csv").write_text(csv_text, encoding="utf-8-sig")

    labels = build_labels(msgs, TRANSFERS, csv_lines, w)
    (out / "labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "case.json").write_text(json.dumps({"case": "case01", "victim": VICTIM, "synthetic": True}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    n_lines = mobile.count("\n")
    assert 450 <= n_lines <= 560, f"대화 줄 수가 목표(약 500줄)를 벗어남: {n_lines}"
    assert len(TRANSFERS) == 20
    print(f"생성 완료: {out}")
    print(f"  kakao_mobile.txt {n_lines}줄 / 메시지 {len(msgs)}건")
    print(f"  transfers_kb.csv {len(TRANSFERS)}건 (피해 {sum(t.fraud for t in TRANSFERS)}건, 합계 {labels['fraud_total']:,}원)")


if __name__ == "__main__":
    main()
