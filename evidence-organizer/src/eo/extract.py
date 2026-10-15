"""식별정보 추출 정규식 모음.

대상: 계좌번호, 전화번호, URL, 가상자산 주소(BTC/ETH/TRON), 금액.
모든 패턴은 이 모듈에만 두고, 패턴마다 tests/test_extract.py 에 테스트가 있다.

정규화 규칙
  accounts : 숫자만 (하이픈 제거). 10~14자리. 전화번호 모양이면 제외.
  phones   : 숫자만. 휴대폰(01x), 지역번호(02, 0xx), 인터넷전화(070), 대표번호(15xx/16xx/18xx).
  urls     : 표기 그대로(끝의 문장부호만 제거).
  wallets  : 표기 그대로.
  amounts  : int. '3,000,000원'/'3000000원'/'₩3,000,000' 처럼 자릿수가 명시된 것만.
             '500만원'/'2천만원' 같은 한국어 단위 표기는 해석 규칙이 확정되지 않았으므로
             amounts 에 넣지 않고 unresolved_amounts 로 따로 돌려준다(needs_review 대상).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from eo.schema import EXTRACTED_KEYS, Event

# 한글이 URL 뒤에 바로 붙는 경우("...com으로")를 끊기 위한 문자 집합
_HANGUL = "ㄱ-ㆎ가-힣"
_URL_STOP = rf"\s<>\"'\]\)\[\(,{_HANGUL}"

# --- 계좌번호 -----------------------------------------------------------------
# 하이픈 구분(2~4그룹) 또는 하이픈 없는 10~14자리 숫자. 날짜(2026-08-20, 8자리)는 자릿수로 걸러진다.
RE_ACCOUNT_HYPHEN = re.compile(r"(?<![\d-])(\d{2,6}(?:-\d{2,8}){1,3})(?![\d-])")
RE_ACCOUNT_BARE = re.compile(r"(?<![\d-])(\d{10,14})(?![\d-])")
ACCOUNT_MIN_DIGITS, ACCOUNT_MAX_DIGITS = 10, 14

# --- 전화번호 -----------------------------------------------------------------
RE_PHONE = re.compile(
    r"(?<![\d-])("
    r"01[016789]-?\d{3,4}-?\d{4}"          # 휴대폰
    r"|0(?:2|[3-6]\d|[57]0)-?\d{3,4}-?\d{4}"  # 지역번호, 070/050
    r"|1[5-9]\d{2}-?\d{4}"                 # 15xx/16xx/18xx 대표번호
    r")(?![\d-])"
)
# 정규화된 숫자열이 전화번호인지 (계좌와의 충돌 제거용)
RE_PHONE_DIGITS = re.compile(r"^(?:01[016789]\d{7,8}|02\d{7,8}|0[3-6]\d\d{7,8}|0[57]0\d{7,8}|1[5-9]\d{6})$")

# --- URL ----------------------------------------------------------------------
_TLDS = r"(?:com|net|org|io|kr|xyz|top|vip|site|app|info|me|cc|link|shop|biz|club|co|ly)"
RE_URL = re.compile(
    rf"(?<![\w./-])("
    rf"(?:https?://|www\.)[^{_URL_STOP}]+"                                 # 스킴 또는 www.
    rf"|(?:[a-z0-9-]+\.)+{_TLDS}(?![a-z])(?:/[^{_URL_STOP}]*)?"            # 스킴 없는 도메인(+경로)
    rf")",
    re.IGNORECASE,
)
_URL_TRAIL = ".,;:!?"

# --- 가상자산 주소 --------------------------------------------------------------
RE_WALLET_ETH = re.compile(r"(?<![A-Za-z0-9])(0x[a-fA-F0-9]{40})(?![A-Za-z0-9])")
RE_WALLET_TRON = re.compile(r"(?<![A-Za-z0-9])(T[1-9A-HJ-NP-Za-km-z]{33})(?![A-Za-z0-9])")
RE_WALLET_BTC = re.compile(r"(?<![A-Za-z0-9])(bc1[ac-hj-np-z02-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})(?![A-Za-z0-9])")

# --- 금액 ----------------------------------------------------------------------
# 자릿수가 명시된 금액: 3,000,000원 / 3000000원 / ₩3,000,000 / 3,000,000 원
RE_AMOUNT_EXPLICIT = re.compile(r"(?<![\d,.])(?:₩\s*(\d{1,3}(?:,\d{3})+|\d+)|(\d{1,3}(?:,\d{3})+|\d+)\s*원)(?![\d,])")
# 한국어 단위 표기: 500만원 / 2천만원 / 1억 2천만 원 / 5만원 — 해석하지 않고 원문만 수집
RE_AMOUNT_KOREAN_UNIT = re.compile(r"(?<![\d,])((?:\d[\d,]*\s*(?:억|천만|백만|만|천)\s*)+원?)")


@dataclass
class Extraction:
    accounts: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    wallets: list[str] = field(default_factory=list)
    amounts: list[int] = field(default_factory=list)
    # 해석을 보류한 금액 표기 원문(needs_review)
    unresolved_amounts: list[str] = field(default_factory=list)

    def as_extracted(self) -> dict[str, list[Any]]:
        return {"accounts": self.accounts, "phones": self.phones, "urls": self.urls, "wallets": self.wallets, "amounts": self.amounts}


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def is_phone_digits(s: str) -> bool:
    return bool(RE_PHONE_DIGITS.match(s))


def extract_phones(text: str) -> list[str]:
    return _dedupe(digits(m.group(1)) for m in RE_PHONE.finditer(text))


def extract_accounts(text: str) -> list[str]:
    found: list[str] = []
    for m in RE_ACCOUNT_HYPHEN.finditer(text):
        d = digits(m.group(1))
        if ACCOUNT_MIN_DIGITS <= len(d) <= ACCOUNT_MAX_DIGITS and not is_phone_digits(d):
            found.append(d)
    for m in RE_ACCOUNT_BARE.finditer(text):
        d = m.group(1)
        if not is_phone_digits(d):
            found.append(d)
    return _dedupe(found)


def extract_urls(text: str) -> list[str]:
    out: list[str] = []
    for m in RE_URL.finditer(text):
        u = m.group(1).rstrip(_URL_TRAIL)
        # "bit.ly/..." 처럼 스킴 없는 짧은 도메인도 허용. 단 'e.g' 같은 오탐을 막기 위해 TLD 뒤에 글자가 없어야 함(정규식에서 처리).
        if u:
            out.append(u)
    return _dedupe(out)


def extract_wallets(text: str) -> list[str]:
    found: list[str] = []
    for rx in (RE_WALLET_ETH, RE_WALLET_TRON, RE_WALLET_BTC):
        found.extend(m.group(1) for m in rx.finditer(text))
    return _dedupe(found)


def extract_amounts(text: str) -> tuple[list[int], list[str]]:
    """(명시 금액 int 목록, 해석 보류 원문 목록)."""
    explicit: list[int] = []
    for m in RE_AMOUNT_EXPLICIT.finditer(text):
        raw = m.group(1) or m.group(2)
        explicit.append(int(raw.replace(",", "")))
    unresolved = [m.group(1).strip() for m in RE_AMOUNT_KOREAN_UNIT.finditer(text)]
    return _dedupe_ints(explicit), _dedupe(unresolved)


def _dedupe_ints(items: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def extract_all(text: str) -> Extraction:
    amounts, unresolved = extract_amounts(text)
    return Extraction(
        accounts=extract_accounts(text),
        phones=extract_phones(text),
        urls=extract_urls(text),
        wallets=extract_wallets(text),
        amounts=amounts,
        unresolved_amounts=unresolved,
    )


def enrich_event(event: Event) -> list[str]:
    """message 이벤트의 text 에서 추출해 event.extracted 를 채운다. 보류 금액 원문을 돌려준다.

    transfer 이벤트는 파서가 구조화 컬럼에서 이미 채웠으므로 건드리지 않는다.
    """
    if event.kind != "message":
        return []
    ex = extract_all(event.text)
    event.extracted = ex.as_extracted()
    for key in EXTRACTED_KEYS:
        event.extracted.setdefault(key, [])
    return ex.unresolved_amounts
