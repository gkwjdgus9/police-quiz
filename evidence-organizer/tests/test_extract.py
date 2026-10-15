"""extract: 패턴마다 양성·음성 케이스."""

from __future__ import annotations

import pytest

from eo.extract import extract_accounts, extract_all, extract_amounts, extract_phones, extract_urls, extract_wallets

# --- 계좌 ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("농협 352-1234-5678-93 (주식회사 골드라인)", ["3521234567893"]),
        ("카카오뱅크 3333-05-1234567", ["3333051234567"]),
        ("신한은행 110-456-789012 로", ["110456789012"]),
        ("국민 123456-04-567890", ["12345604567890"]),
        ("하이픈 없이 3521234567893 으로", ["3521234567893"]),
        ("두 개: 352-1234-5678-93 그리고 110-456-789012", ["3521234567893", "110456789012"]),
        ("중복 352-1234-5678-93 / 3521234567893", ["3521234567893"]),
    ],
)
def test_accounts_positive(text: str, expected: list[str]) -> None:
    assert extract_accounts(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "전화 010-4567-8910 주세요",          # 휴대폰
        "02-512-3456 예약",                   # 지역번호
        "1600-1234 고객센터",                 # 대표번호
        "2026-08-20 날짜",                    # 날짜
        "금액 3,000,000원",                   # 금액
        "주문번호 123-45",                    # 너무 짧음
        "123456789012345 열다섯자리",         # 너무 김
    ],
)
def test_accounts_negative(text: str) -> None:
    assert extract_accounts(text) == []


# --- 전화번호 -----------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("010-4567-8910 으로", ["01045678910"]),
        ("01045678910", ["01045678910"]),
        ("011-234-5678", ["0112345678"]),
        ("02-512-3456", ["025123456"]),
        ("031-1234-5678", ["03112345678"]),
        ("070-7777-8888", ["07077778888"]),
        ("고객센터 1600-1234 / 1588-5678", ["16001234", "15885678"]),
    ],
)
def test_phones_positive(text: str, expected: list[str]) -> None:
    assert extract_phones(text) == expected


@pytest.mark.parametrize("text", ["352-1234-5678-93", "3333-05-1234567", "2026-08-20", "3,000,000원", "100-200"])
def test_phones_negative(text: str) -> None:
    assert extract_phones(text) == []


# --- URL ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("설치 https://goldline-invest.top/app 하세요", ["https://goldline-invest.top/app"]),
        ("텔레그램 https://t.me/goldline_vip 도", ["https://t.me/goldline_vip"]),
        ("로그인은 www.kstock-pro.xyz/login 에서", ["www.kstock-pro.xyz/login"]),
        ("단축 http://bit.ly/4gL9xQz 는", ["http://bit.ly/4gL9xQz"]),
        ("차트 https://finance.naver.com/item/main.naver?code=005930 보세요", ["https://finance.naver.com/item/main.naver?code=005930"]),
        ("https://example.com으로 접속", ["https://example.com"]),
        ("끝에 마침표 https://example.com/a.", ["https://example.com/a"]),
        ("괄호 (https://example.com/x) 안", ["https://example.com/x"]),
        ("스킴 없음 goldline-invest.top/app", ["goldline-invest.top/app"]),
    ],
)
def test_urls_positive(text: str, expected: list[str]) -> None:
    assert extract_urls(text) == expected


@pytest.mark.parametrize("text", ["그냥 문장입니다.", "e.g. 예시", "3.5% 수익", "v1.2.3 버전"])
def test_urls_negative(text: str) -> None:
    assert extract_urls(text) == []


# --- 지갑 ---------------------------------------------------------------------
ETH = "0x" + "ab12" * 10
TRON = "T" + "9" * 33
BTC_BECH32 = "bc1q" + "q" * 38
BTC_LEGACY = "1" + "A" * 30


@pytest.mark.parametrize(
    "text,expected",
    [
        (f"ETH 주소: {ETH}", [ETH]),
        (f"USDT(TRC20) {TRON} 로", [TRON]),
        (f"지갑 {BTC_BECH32} 입니다", [BTC_BECH32]),
        (f"legacy {BTC_LEGACY}", [BTC_LEGACY]),
        (f"{ETH} {TRON} {BTC_BECH32}", [ETH, TRON, BTC_BECH32]),
    ],
)
def test_wallets_positive(text: str, expected: list[str]) -> None:
    assert extract_wallets(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "0x1234 짧음",
        "T12345 짧음",
        "3521234567893",            # 계좌
        "TRON 이라는 단어",
        "0x" + "g" * 40,            # hex 아님
        "T" + "0" * 33,             # base58 에 0 없음
    ],
)
def test_wallets_negative(text: str) -> None:
    assert extract_wallets(text) == []


# --- 금액 ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,explicit,unresolved",
    [
        ("증거금은 3,000,000원입니다", [3_000_000], []),
        ("3000000원 보냈어요", [3_000_000], []),
        ("₩4,500,000", [4_500_000], []),
        ("15,000,000 원", [15_000_000], []),
        ("500만원 추가", [], ["500만원"]),
        ("2천만원입니다", [], ["2천만원"]),
        ("1억 2천만 원", [], ["1억 2천만 원"]),
        ("회비 5만원이에요", [], ["5만원"]),
        ("3,000,000원 과 500만원", [3_000_000], ["500만원"]),
        ("수익 23%", [], []),
        ("2026년 8월 20일", [], []),
        ("10명 모집", [], []),
    ],
)
def test_amounts(text: str, explicit: list[int], unresolved: list[str]) -> None:
    assert extract_amounts(text) == (explicit, unresolved)


# --- 통합 ---------------------------------------------------------------------
def test_extract_all_mixed() -> None:
    text = (
        "첫 증거금은 3,000,000원입니다.\n입금계좌: 농협 352-1234-5678-93 (주식회사 골드라인)\n"
        f"문의 010-4567-8910, 앱 https://goldline-invest.top/app, USDT {TRON}"
    )
    ex = extract_all(text)
    assert ex.accounts == ["3521234567893"]
    assert ex.phones == ["01045678910"]
    assert ex.urls == ["https://goldline-invest.top/app"]
    assert ex.wallets == [TRON]
    assert ex.amounts == [3_000_000]
    assert ex.unresolved_amounts == []
    assert set(ex.as_extracted()) == {"accounts", "phones", "urls", "wallets", "amounts"}
