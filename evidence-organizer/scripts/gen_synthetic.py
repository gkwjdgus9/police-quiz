"""합성 사건 데이터 생성기.

투자리딩방 사기 시나리오를 합성해 data/synthetic/<case>/ 에 저장한다.
실제 사건 데이터는 절대 넣지 않는다. 등장하는 이름·계좌·번호·주소는 전부 가공이다.

시나리오
  case01  기본 사건. 피해자 이수진, 골드라인 리딩방.
  case02  다른 피해자·다른 방이지만 대포통장 하나(카카오뱅크), 고객센터 번호, 텔레그램 링크를 case01 과 공유한다.
          → 3단계 사건 간 교차 조회 검증용.

생성물 (사건마다)
  raw/kakao_mobile.txt            카카오톡 모바일(Android) 내보내기 형식, 약 500줄
  raw/transfers_kb.csv            KB국민은행 형식 이체내역 20건
  raw/Screenshot_<일시>.png       첫 피해 이체의 '이체 완료' 화면 캡처 (PIL + 한글 폰트가 있을 때만 생성)
  variants/kakao_pc.txt           같은 대화의 PC 내보내기 형식(파서 테스트용, raw 가 아니므로 파이프라인 입력 아님)
  labels.json                     정답 라벨(피해 이체, 등장한 계좌·번호·URL·지갑주소, 캡처 내용, 다른 사건과 공유하는 값)
  case.json                       사건 메타(피해자 이름)

실행: python scripts/gen_synthetic.py [--case case01|case02|all] [--out data/synthetic]
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

WEEKDAYS_KO = ["월", "화", "수", "목", "금", "토", "일"]
BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


# ----------------------------------------------------------------------------
# 시나리오 (전부 가공)
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Scenario:
    case: str
    seed: int
    start: date                      # 대화 시작일. 사건은 start 기준 +36일까지
    room: str                        # 리딩방 브랜드
    victim: str
    operator: str
    assistant: str
    others: tuple[str, str]
    # 대포통장 3개 (표기 형태는 대화에 등장하는 그대로)
    acc_nh: str
    acc_kakao: str
    acc_shinhan: str
    owner_kakao: str                 # 카카오뱅크 계좌 명의
    owner_shinhan: str               # 신한 계좌 명의
    acc_member: str                  # 무관한 참여자(others[1]) 의 회비 계좌 (국민)
    phone_assistant: str
    phone_operator: str
    phone_cs: str
    phone_restaurant: str
    url_app: str
    url_tg: str
    url_login: str
    url_short: str
    url_naver: str
    amounts: tuple[int, ...]         # 피해 이체 12건 금액(시간순). 2·5·9·11번째는 대화에 '만원' 단위로 표기
    profit_claim: int                # "현재 수익 포함 N 넘으셨어요" 에 쓰는 금액 (만원 단위 표기)
    fee: int                         # 모임 회비 (만원 단위 표기)
    saved_at: datetime

    def day(self, offset: int) -> date:
        return self.start + timedelta(days=offset)

    def shares_with(self) -> dict[str, list[str]]:
        """다른 사건과 공유하는 값(교차 조회 정답). case01 기준으로 적는다."""
        return {}


CASE01 = Scenario(
    case="case01", seed=20261015, start=date(2026, 8, 20), room="골드라인",
    victim="이수진", operator="박대표", assistant="김실장", others=("최민수", "정하나"),
    acc_nh="352-1234-5678-93", acc_kakao="3333-05-1234567", acc_shinhan="110-456-789012",
    owner_kakao="최영철", owner_shinhan="강민호", acc_member="123456-04-567890",
    phone_assistant="010-4567-8910", phone_operator="010-2233-4455", phone_cs="1600-1234", phone_restaurant="02-512-3456",
    url_app="https://goldline-invest.top/app", url_tg="https://t.me/goldline_vip", url_login="www.kstock-pro.xyz/login",
    url_short="http://bit.ly/4gL9xQz", url_naver="https://finance.naver.com/item/main.naver?code=005930",
    amounts=(3_000_000, 5_000_000, 10_000_000, 2_000_000, 7_000_000, 4_500_000, 15_000_000, 3_000_000, 20_000_000, 6_000_000, 8_000_000, 12_000_000),
    profit_claim=60_000_000, fee=50_000,
    saved_at=datetime(2026, 9, 26, 20, 12, tzinfo=KST),
)

CASE02 = Scenario(
    case="case02", seed=20261016, start=date(2026, 7, 6), room="블루칩",
    victim="박민재", operator="최대표", assistant="이팀장", others=("강서연", "윤태호"),
    acc_nh="301-0987-6543-21", acc_kakao=CASE01.acc_kakao, acc_shinhan="140-012-345678",   # 카카오뱅크 계좌는 case01 과 공유
    owner_kakao=CASE01.owner_kakao, owner_shinhan="서정우", acc_member="654321-01-234567",
    phone_assistant="010-9876-5432", phone_operator="010-5555-1212", phone_cs=CASE01.phone_cs, phone_restaurant="031-777-8888",  # 고객센터 공유
    url_app="https://bluechip-lab.vip/app", url_tg=CASE01.url_tg, url_login="www.bluechip-trade.site/login",            # 텔레그램 공유
    url_short="http://bit.ly/3kQw9Zx", url_naver="https://finance.naver.com/item/main.naver?code=000660",
    amounts=(2_000_000, 3_000_000, 8_000_000, 1_500_000, 4_000_000, 3_500_000, 12_000_000, 2_000_000, 10_000_000, 5_000_000, 6_000_000, 9_000_000),
    profit_claim=40_000_000, fee=30_000,
    saved_at=datetime(2026, 8, 12, 19, 40, tzinfo=KST),
)

SCENARIOS = {"case01": CASE01, "case02": CASE02}
SHARED_WITH_CASE01 = {"accounts": ["3333051234567"], "phones": ["16001234"], "urls": ["https://t.me/goldline_vip"]}


def _make_wallets(rng: random.Random) -> dict[str, str]:
    tron = "T" + "".join(rng.choice(BASE58) for _ in range(33))
    eth = "0x" + "".join(rng.choice("0123456789abcdef") for _ in range(40))
    btc = "bc1q" + "".join(rng.choice(BECH32) for _ in range(38))
    return {"tron": tron, "eth": eth, "btc": btc}


def norm_digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def won(n: int) -> str:
    """3000000 → '3,000,000원'"""
    return f"{n:,}원"


def man(n: int) -> str:
    """한국어 단위 표기. 20000000 → '2천만원', 5000000 → '500만원', 50000 → '5만원'"""
    if n % 10_000_000 == 0 and n < 100_000_000:
        return f"{n // 10_000_000}천만원"
    if n % 10_000 == 0:
        return f"{n // 10_000}만원"
    raise ValueError(f"만원 단위로 표기할 수 없는 금액: {n}")


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


def build_transfers(sc: Scenario) -> list[Transfer]:
    def at(offset: int, t: str) -> datetime:
        return datetime.combine(sc.day(offset), time.fromisoformat(t), tzinfo=KST)

    a = sc.amounts
    nh, kk, sh = sc.acc_nh, sc.acc_kakao, sc.acc_shinhan
    nh_name, kk_name, sh_name = f"주식회사 {sc.room}", sc.owner_kakao, sc.owner_shinhan
    return [
        Transfer(at(1, "09:00:12"), "급여 (주)한빛테크", 0, 2_850_000, "", "", "", False),
        Transfer(at(2, "10:30:41"), f"{sc.room} 증거금", a[0], 0, nh, "농협", nh_name, True),
        Transfer(at(5, "14:10:05"), f"{sc.room} 추가증거금", a[1], 0, nh, "농협", nh_name, True),
        Transfer(at(6, "12:33:50"), "쿠팡", 45_900, 0, "", "", "", False),
        Transfer(at(8, "11:05:17"), "VIP방 입금", a[2], 0, kk, "카카오뱅크", kk_name, True),
        Transfer(at(10, "18:20:33"), "월세", 650_000, 0, "1002-345-678901", "우리", "김영호", False),
        Transfer(at(12, "09:50:02"), "증거금", a[3], 0, kk, "카카오뱅크", kk_name, True),
        Transfer(at(13, "08:10:00"), "KT 통신요금", 89_000, 0, "", "", "", False),
        Transfer(at(14, "16:20:48"), "증거금 추가", a[4], 0, nh, "농협", nh_name, True),
        Transfer(at(16, "10:15:29"), "해외선물 계정", a[5], 0, sh, "신한", sh_name, True),
        Transfer(at(17, "20:05:11"), "모임 회비", sc.fee, 0, sc.acc_member, "국민", sc.others[1], False),
        Transfer(at(19, "13:40:36"), "VIP 2차", a[6], 0, kk, "카카오뱅크", kk_name, True),
        Transfer(at(20, "09:00:00"), "예금이자", 0, 1_230, "", "", "", False),
        Transfer(at(21, "11:30:54"), "증거금", a[7], 0, nh, "농협", nh_name, True),
        Transfer(at(23, "15:05:22"), "출금수수료 보증금", a[8], 0, sh, "신한", sh_name, True),
        Transfer(at(25, "17:45:09"), "어머니 생활비", a[0], 0, "456-910234-56789", "하나", "이정숙", False),  # 피해 금액과 같은 금액·다른 계좌 (함정)
        Transfer(at(26, "10:40:47"), "세금", a[9], 0, kk, "카카오뱅크", kk_name, True),
        Transfer(at(29, "14:25:15"), "보증금 추가", a[10], 0, sh, "신한", sh_name, True),
        Transfer(at(31, "11:11:11"), "ATM출금", 300_000, 0, "", "", "", False),
        Transfer(at(33, "09:55:38"), "최종 보증금", a[11], 0, nh, "농협", nh_name, True),
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


def scripted_beats(sc: Scenario, w: dict[str, str]) -> list[Msg]:
    """사건의 뼈대가 되는 메시지. 계좌·번호·URL·지갑주소·금액이 여기 들어 있다."""
    V, O, A, C, H = sc.victim, sc.operator, sc.assistant, sc.others[0], sc.others[1]
    a = sc.amounts

    def m(offset: int, t: str, actor: str, text: str) -> Msg:
        return Msg(sc.day(offset), time.fromisoformat(t), actor, text)

    return [
        m(0, "09:00", "", f"{V}님이 들어왔습니다."),
        m(0, "09:02", O, f"{V}님 환영합니다! {sc.room} 투자연구소 공식 리딩방입니다.\n매일 아침 종목 브리핑 드리고, 매수/매도 타이밍은 실시간으로 안내합니다.\n궁금한 건 언제든 {A}에게 물어보세요."),
        m(0, "09:05", A, f"안녕하세요 {V}님, 담당 {A}입니다. 개인 문의는 {sc.phone_assistant} 으로 연락주셔도 됩니다."),
        m(0, "09:11", V, "안녕하세요. 지인 소개로 왔는데 주식은 처음이라 잘 모릅니다. 잘 부탁드려요."),
        m(0, "09:13", C, "여기 들어오시면 돈 버십니다 ㅎㅎ 저도 지난달 40% 먹었어요"),
        m(0, "09:14", H, "환영해요~ 저도 초보였는데 실장님이 다 알려주세요"),
        m(1, "10:20", O, f"오늘부터 전용 매매앱 사용합니다. 아래 링크에서 설치하세요.\n{sc.url_app}\n설치 후 아이디는 실장에게 받으시면 됩니다."),
        m(1, "10:31", V, "설치했습니다. 아이디는 어떻게 받나요?"),
        m(1, "10:33", A, f"{V}님 아이디 발급해드렸습니다. 로그인은 {sc.url_login} 에서 하시면 됩니다."),
        m(1, "10:40", C, f"참고로 삼성전자 차트 {sc.url_naver} 보시면 지금 바닥입니다"),
        m(2, "09:40", O, "오늘 1차 공략주 매수 들어갑니다. 증거금 입금 완료하신 분부터 수량 배정합니다."),
        m(2, "09:52", A, f"{V}님 첫 증거금은 {won(a[0])}입니다.\n입금계좌: 농협 {sc.acc_nh} (주식회사 {sc.room})\n입금 후 꼭 캡처 보내주세요."),
        m(2, "10:32", V, f"방금 {won(a[0])} 보냈습니다. 확인 부탁드려요."),
        m(2, "10:35", A, "입금 확인했습니다. 앱에서 잔고 반영된 것 확인하세요!"),
        m(2, "15:10", O, "1차 공략주 +12% 마감입니다. 축하드립니다 👏"),
        m(2, "15:12", V, "앱에서 보니까 정말 올랐네요! 신기합니다"),
        m(4, "09:30", O, "이번 주 2차 공략주는 배정 수량이 제한적입니다. 증거금 추가하신 분 우선입니다."),
        m(5, "13:50", A, f"{V}님 2차 증거금 {man(a[1])} 추가하시면 배정 2배로 드립니다. 계좌는 동일하게 농협 {sc.acc_nh} 입니다."),
        m(5, "14:12", V, f"{man(a[1])} 보냈어요. 확인해주세요."),
        m(5, "14:15", A, "확인 완료! 2차 배정 들어갔습니다."),
        m(7, "16:00", O, f"VIP방 안내드립니다. 기관 블록딜 물량을 받는 방이라 인원 제한 있습니다.\n참여 희망자는 {A}에게 개별 문의하세요. 텔레그램 {sc.url_tg} 도 운영합니다."),
        m(8, "10:40", A, f"{V}님 VIP방 참여금은 {won(a[2])}입니다.\nVIP 전용 계좌: 카카오뱅크 {sc.acc_kakao} ({sc.owner_kakao})\n이 계좌는 VIP 전용이라 외부에 공유 금지입니다."),
        m(8, "11:07", V, f"{won(a[2])} 입금했습니다. 금액이 커서 좀 떨리네요.."),
        m(8, "11:09", A, "걱정 마세요. 블록딜은 손실 날 수가 없는 구조입니다. 확인했습니다."),
        m(12, "09:20", A, f"{V}님 오늘 블록딜 추가 수량 나왔습니다. {won(a[3])}만 추가하시면 됩니다. 카카오뱅크 {sc.acc_kakao}"),
        m(12, "09:52", V, f"{won(a[3])} 보냈습니다."),
        m(14, "15:55", A, f"{V}님 지금 잔고 기준 수익 23%입니다. {man(a[4])} 추가하시면 다음 공략주 수량 더 배정됩니다. 농협 {norm_digits(sc.acc_nh)} 으로 보내주세요."),
        m(14, "16:22", V, f"{man(a[4])} 넣었습니다. 이번엔 꼭 수익 났으면 좋겠어요"),
        m(15, "11:00", O, f"해외선물 파트 신설합니다. 수익률이 국내보다 훨씬 높습니다. 고객센터 {sc.phone_cs} 로 문의 가능합니다."),
        m(16, "09:48", A, f"{V}님 해외선물 계정 개설비 {won(a[5])}입니다.\n계좌: 신한은행 {sc.acc_shinhan} ({sc.owner_shinhan})\n해외 계정 충전은 USDT(TRC20)로만 가능하고 주소는 아래입니다.\n{w['tron']}"),
        m(16, "10:17", V, f"{won(a[5])} 보냈습니다. USDT는 어떻게 사는 건가요?"),
        m(16, "10:20", A, "그건 저희가 대신 처리해 드립니다. 입금만 해주시면 됩니다."),
        m(17, "19:30", H, f"이번 주 토요일 오프모임 회비 {man(sc.fee)}이에요~ 제 계좌 국민 {sc.acc_member} 으로 보내주세요. 장소는 역삼동 한우집 {sc.phone_restaurant} 예약했어요"),
        m(17, "20:07", V, "회비 보냈습니다~ 토요일에 봬요"),
        m(19, "13:20", A, f"{V}님 VIP 2차 블록딜 {won(a[6])}입니다. 카카오뱅크 {sc.acc_kakao} 로 부탁드립니다."),
        m(19, "13:42", V, f"{won(a[6])} 보냈습니다. 이제 총 얼마 들어간 거죠?"),
        m(19, "13:45", A, f"앱 잔고 확인하시면 됩니다. 현재 수익 포함 {man(sc.profit_claim)} 넘으셨어요."),
        m(21, "11:10", A, f"{V}님 공략주 추가 {won(a[7])} 부탁드립니다. 농협 {sc.acc_nh}"),
        m(21, "11:32", V, f"{won(a[7])} 보냈습니다."),
        m(22, "17:40", V, "대표님 저 이제 출금 좀 하고 싶은데요. 생활비가 필요해서요."),
        m(22, "17:55", O, f"출금은 {A}이 처리합니다. 다만 수익금 출금 시 세무 처리 때문에 보증금이 먼저 필요합니다."),
        m(23, "14:40", A, f"{V}님 출금 보증금은 수익금의 20%인 {man(a[8])}입니다. 출금 후 보증금은 바로 환급됩니다.\n신한은행 {sc.acc_shinhan} ({sc.owner_shinhan})"),
        m(23, "15:08", V, f"{man(a[8])} 보냈습니다. 그럼 언제 출금되나요?"),
        m(23, "15:10", A, "영업일 기준 3일 이내입니다."),
        m(26, "10:20", A, f"{V}님 출금 심사 중 세금 {won(a[9])}이 추가로 발생했습니다. 카카오뱅크 {sc.acc_kakao} 로 입금해주셔야 출금 진행됩니다."),
        m(26, "10:42", V, f"{won(a[9])} 보냈습니다. 정말 출금되는 거 맞죠? 불안합니다."),
        m(26, "10:45", O, f"{V}님 걱정 마세요. 본사 대표 직통 {sc.phone_operator} 입니다. 책임지고 처리합니다."),
        m(28, "09:30", C, f"저는 비트코인도 하는데 요즘 지갑 {w['btc']} 로 옮겨놨어요 ㅋㅋ"),
        m(29, "14:00", A, f"{V}님 출금 승인 직전인데 보증금 {man(a[10])}이 부족합니다. 신한은행 {sc.acc_shinhan} 으로 오늘 중 부탁드립니다."),
        m(29, "14:27", V, f"{man(a[10])} 보냈습니다. 이게 마지막이죠?"),
        m(30, "16:10", O, f"VIP 회원 대상 이더리움 프라이빗 세일 진행합니다. ETH 전용 주소: {w['eth']}"),
        m(33, "09:30", A, f"{V}님 최종 보증금 {won(a[11])} 입금하시면 전액 출금 처리됩니다. 농협 {sc.acc_nh} (주식회사 {sc.room})"),
        m(33, "09:57", V, f"{won(a[11])} 보냈습니다. 오늘 꼭 출금 부탁드립니다."),
        m(34, "10:00", V, "실장님 출금 언제 되나요? 연락 부탁드립니다."),
        m(34, "15:30", V, f"실장님 전화도 안 받으시네요. {sc.phone_assistant} 맞죠?"),
        m(35, "09:10", V, "대표님 답변 부탁드립니다. 출금이 안 됩니다."),
        m(35, "18:00", V, "앱 로그인도 안 되는데 무슨 일인가요?"),
        m(36, "10:30", C, f"다들 조용하네요.. 단축링크 {sc.url_short} 는 이제 안 열리는데요?"),
        m(36, "11:00", V, "경찰에 신고하겠습니다."),
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


def filler_for_day(rng: random.Random, sc: Scenario, d: date) -> list[Msg]:
    """하루치 잡담. 식별정보는 넣지 않는다(라벨과 불일치 방지)."""
    others = list(sc.others)
    msgs: list[Msg] = []
    if d.weekday() >= 5:  # 주말은 조용
        if rng.random() < 0.5:
            msgs.append(Msg(d, time(11, rng.randrange(0, 59)), rng.choice(others), rng.choice(REACTIONS).format(p=rng.randrange(3, 30))))
        return msgs
    stock = rng.choice(MORNING_STOCKS)
    brief = (
        f"[{sc.room} 데일리 브리핑]\n"
        f"오늘의 관심 종목: {stock}\n"
        f"목표가 +{rng.randrange(5, 20)}% / 손절 -{rng.randrange(2, 5)}%\n"
        "매수 타이밍은 방에서 실시간 안내드립니다."
    )
    msgs.append(Msg(d, time(8, 50 + rng.randrange(0, 9)), sc.operator, brief))
    n_react = rng.randrange(5, 10)
    for _ in range(n_react):
        actor = rng.choice(others + others + [sc.victim])
        pool = VICTIM_FILLER if actor == sc.victim else REACTIONS
        msgs.append(Msg(d, time(rng.randrange(9, 15), rng.randrange(0, 60)), actor, rng.choice(pool).format(p=rng.randrange(3, 30))))
    if rng.random() < 0.8:
        msgs.append(Msg(d, time(rng.randrange(13, 16), rng.randrange(0, 60)), sc.operator, rng.choice(OPERATOR_NOTICES)))
        for _ in range(rng.randrange(2, 5)):
            msgs.append(Msg(d, time(rng.randrange(14, 18), rng.randrange(0, 60)), rng.choice(others), rng.choice(REACTIONS).format(p=rng.randrange(3, 30))))
    return msgs


def build_messages(rng: random.Random, sc: Scenario, w: dict[str, str]) -> list[Msg]:
    msgs = scripted_beats(sc, w)
    d = sc.start
    while d <= sc.day(36):
        msgs.extend(filler_for_day(rng, sc, d))
        d += timedelta(days=1)
    # 날짜·시각 순 정렬. 같은 시각이면 입력 순서 유지(stable).
    msgs.sort(key=lambda x: (x.d, x.t))
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


def render_mobile(sc: Scenario, msgs: list[Msg]) -> str:
    lines = [f"{sc.operator} 님과 카카오톡 대화", f"저장한 날짜 : {ko_date(sc.saved_at.date())} {ko_ampm(sc.saved_at.time())}", ""]
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


def render_pc(sc: Scenario, msgs: list[Msg]) -> str:
    lines = [f"{sc.operator} 님과 카카오톡 대화", f"저장한 날짜 : {sc.saved_at.strftime('%Y-%m-%d %H:%M:%S')}", ""]
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
# 캡처 이미지 (첫 피해 이체의 '이체 완료' 화면)
# ----------------------------------------------------------------------------
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/unifont/unifont_jp.otf",
    "C:/Windows/Fonts/malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]


def screenshot_lines(sc: Scenario, first: Transfer) -> list[str]:
    """캡처에 그려 넣는 글줄. labels 에도 그대로 적어 OCR 정답으로 쓴다."""
    return [
        "이체가 완료되었습니다",
        f"받는 분  {first.to_name}",
        f"{first.to_bank}  {first.to_account}",
        f"이체 금액  {first.withdraw:,}원",
        f"출금 계좌  KB국민 ****-**-**1234",
        f"거래 일시  {first.ts.strftime('%Y.%m.%d %H:%M')}",
        "확인",
    ]


def screenshot_name(first: Transfer) -> str:
    shot_at = first.ts + timedelta(seconds=11)
    return f"Screenshot_{shot_at.strftime('%Y%m%d-%H%M%S')}.png"


def render_screenshot(lines: list[str], path: Path) -> bool:
    """PIL 과 한글 폰트가 있으면 PNG 를 그리고 True. 없으면 False (추측해서 다른 걸 만들지 않는다)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    font_path = next((p for p in FONT_CANDIDATES if Path(p).exists()), None)
    if font_path is None:
        return False
    W, H = 720, 1280
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 90], fill=(245, 196, 0))
    title = ImageFont.truetype(font_path, 40)
    body = ImageFont.truetype(font_path, 34)
    d.text((40, 24), lines[0], font=title, fill=(20, 20, 20))
    y = 220
    for text in lines[1:-1]:
        d.text((60, y), text, font=body, fill=(30, 30, 30))
        y += 110
        d.line([60, y - 30, W - 60, y - 30], fill=(225, 225, 225), width=2)
    d.rectangle([60, H - 200, W - 60, H - 100], fill=(245, 196, 0))
    d.text((W // 2 - 30, H - 175), lines[-1], font=body, fill=(20, 20, 20))
    img.save(path, format="PNG", optimize=True)
    return True


# ----------------------------------------------------------------------------
# 라벨
# ----------------------------------------------------------------------------
def build_labels(sc: Scenario, msgs: list[Msg], transfers: list[Transfer], csv_lines: list[int], w: dict[str, str], shot: dict | None) -> dict:
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
    unit_mentions = {man(sc.amounts[i]): sc.amounts[i] for i in (1, 4, 8, 10)}
    unit_mentions[man(sc.fee)] = sc.fee
    unit_mentions[man(sc.profit_claim)] = sc.profit_claim
    labels = {
        "case": sc.case,
        "victim": sc.victim,
        "participants": {sc.victim: "victim", sc.operator: "operator", sc.assistant: "assistant", sc.others[0]: "unrelated", sc.others[1]: "unrelated"},
        "fraud_transfers": fraud,
        "fraud_total": sum(r["amount"] for r in fraud),
        # 대화(kakao_mobile.txt)에 등장하는 식별정보. 정규화 규칙: 계좌·전화는 숫자만, URL·지갑은 표기 그대로.
        "chat": {
            "accounts": sorted({norm_digits(x) for x in [sc.acc_nh, sc.acc_kakao, sc.acc_shinhan, sc.acc_member]}),
            "fraud_accounts": sorted({norm_digits(x) for x in [sc.acc_nh, sc.acc_kakao, sc.acc_shinhan]}),
            "phones": sorted({norm_digits(p) for p in [sc.phone_assistant, sc.phone_operator, sc.phone_cs, sc.phone_restaurant]}),
            "urls": sorted([sc.url_app, sc.url_tg, sc.url_login, sc.url_short, sc.url_naver]),
            "wallets": sorted(w.values()),
            # 대화에 등장하는 한국어 단위 금액 표기와 환산값(억=10^8, 만=10^4, 천=10^3)
            "amount_mentions_korean_unit": unit_mentions,
        },
        # 피해가 아닌데도 1단계 규칙(계좌+금액이 대화와 일치)으로는 confirmed 되는 이체.
        # 대화 참여자가 자기 계좌와 회비 금액을 올렸기 때문이며, 역할 분류(2단계)로 걸러야 한다.
        "known_false_positives": [
            {"to_account": norm_digits(sc.acc_member), "amount": sc.fee, "reason": "모임 회비 - 무관한 참여자의 계좌·금액이 대화에 등장"},
        ],
        # 캡처 이미지 정답: 그려 넣은 글줄 그대로 (OCR 평가용). 이미지가 생성되지 않았으면 비어 있다.
        "screenshots": {shot["name"]: {"ts": shot["ts"], "lines": shot["lines"], "accounts": shot["accounts"], "amounts": shot["amounts"]}} if shot else {},
        # 다른 사건과 공유하는 값 (3단계 교차 조회 정답)
        "shared_with": {"case01": SHARED_WITH_CASE01} if sc.case == "case02" else ({"case02": SHARED_WITH_CASE01} if sc.case == "case01" else {}),
        "message_count": len(msgs),
    }
    return labels


# ----------------------------------------------------------------------------
def generate(sc: Scenario, out: Path) -> None:
    rng = random.Random(sc.seed)
    w = _make_wallets(rng)
    msgs = build_messages(rng, sc, w)
    transfers = build_transfers(sc)

    (out / "raw").mkdir(parents=True, exist_ok=True)
    (out / "variants").mkdir(parents=True, exist_ok=True)

    mobile = render_mobile(sc, msgs)
    pc = render_pc(sc, msgs)
    csv_text, csv_lines = render_kb_csv(transfers)

    (out / "raw" / "kakao_mobile.txt").write_text(mobile, encoding="utf-8")
    (out / "variants" / "kakao_pc.txt").write_text(pc, encoding="utf-8")
    (out / "raw" / "transfers_kb.csv").write_text(csv_text, encoding="utf-8-sig")

    first = next(t for t in sorted(transfers, key=lambda x: x.ts) if t.fraud)
    lines = screenshot_lines(sc, first)
    name = screenshot_name(first)
    shot: dict | None = None
    if render_screenshot(lines, out / "raw" / name):
        shot = {"name": name, "ts": (first.ts + timedelta(seconds=11)).isoformat(), "lines": lines,
                "accounts": [norm_digits(first.to_account)], "amounts": [first.withdraw]}
    else:
        print("  경고: PIL 또는 한글 폰트가 없어 캡처 이미지를 만들지 않음 (labels.screenshots 비움)")

    labels = build_labels(sc, msgs, transfers, csv_lines, w, shot)
    (out / "labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "case.json").write_text(json.dumps({"case": sc.case, "victim": sc.victim, "synthetic": True}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    n_lines = mobile.count("\n")
    assert 450 <= n_lines <= 560, f"대화 줄 수가 목표(약 500줄)를 벗어남: {n_lines}"
    assert len(transfers) == 20
    print(f"생성 완료: {out}")
    print(f"  kakao_mobile.txt {n_lines}줄 / 메시지 {len(msgs)}건")
    print(f"  transfers_kb.csv {len(transfers)}건 (피해 {sum(t.fraud for t in transfers)}건, 합계 {labels['fraud_total']:,}원)")
    print(f"  캡처: {name if shot else '없음'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", default="all", choices=["all", *SCENARIOS])
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "synthetic", help="사건 디렉터리들의 상위 폴더")
    args = ap.parse_args()
    for name, sc in SCENARIOS.items():
        if args.case in ("all", name):
            generate(sc, args.out / name)


if __name__ == "__main__":
    main()
