"""은행 이체내역 CSV 파서.

- 은행별 컬럼 매핑 테이블(BANKS)로만 읽는다. 헤더가 어떤 매핑과도 맞지 않으면 추측하지 않고 UnknownBankError.
- 행마다 Event(kind="transfer") 를 yield 한다. line 은 CSV 파일의 물리적 행 번호(헤더가 1행).
- 상대 계좌(숫자만)와 금액은 extracted 에, 은행·상대명·입출금 구분은 meta 에 둔다.

주의: 아래 컬럼 매핑은 합성 데이터용 샘플 형식이다. 실제 은행 내보내기 형식을 확인한 뒤 추가·수정한다.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from eo.schema import KST, Event


class UnknownBankError(ValueError):
    """헤더가 알려진 은행 매핑과 맞지 않을 때."""


@dataclass(frozen=True)
class BankMapping:
    name: str
    date_col: str
    time_col: str | None       # 날짜와 시각이 분리된 형식이면 시각 컬럼
    datetime_fmt: str          # date(+time) 을 이어 붙인 문자열의 strptime 형식
    memo_col: str
    withdraw_col: str
    deposit_col: str
    balance_col: str
    to_account_col: str
    to_bank_col: str
    to_name_col: str

    @property
    def required_columns(self) -> frozenset[str]:
        cols = {self.date_col, self.memo_col, self.withdraw_col, self.deposit_col, self.balance_col, self.to_account_col, self.to_bank_col, self.to_name_col}
        if self.time_col:
            cols.add(self.time_col)
        return frozenset(cols)


BANKS: dict[str, BankMapping] = {
    "KB국민은행": BankMapping(
        name="KB국민은행",
        date_col="거래일시", time_col=None, datetime_fmt="%Y.%m.%d %H:%M:%S",
        memo_col="적요", withdraw_col="출금액", deposit_col="입금액", balance_col="잔액",
        to_account_col="상대계좌번호", to_bank_col="상대은행", to_name_col="받는분",
    ),
    "신한은행": BankMapping(
        name="신한은행",
        date_col="거래일", time_col="거래시간", datetime_fmt="%Y-%m-%d %H:%M:%S",
        memo_col="내용", withdraw_col="출금(원)", deposit_col="입금(원)", balance_col="잔액(원)",
        to_account_col="상대방계좌번호", to_bank_col="상대방은행", to_name_col="상대방이름",
    ),
}


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"인코딩을 판별하지 못했습니다: {path}")


def detect_bank(header: list[str]) -> BankMapping:
    cols = {h.strip() for h in header}
    matches = [m for m in BANKS.values() if m.required_columns <= cols]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise UnknownBankError(f"알 수 없는 은행 CSV 형식입니다. 헤더: {header}")
    raise UnknownBankError(f"여러 은행 매핑과 맞아 모호합니다: {[m.name for m in matches]}")


def parse_amount(s: str) -> int:
    """'3,000,000' / '3000000' / '' → int. 빈 값은 0."""
    s = s.strip().replace(",", "").replace("원", "")
    if not s:
        return 0
    if not s.lstrip("-").isdigit():
        raise ValueError(f"금액을 해석할 수 없습니다: {s!r}")
    return int(s)


def norm_account(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def parse_bank_csv(path: Path, *, bank: str | None = None, victim: str = "") -> Iterator[Event]:
    """이체내역 CSV 를 읽어 transfer Event 를 yield 한다.

    bank 를 주면 그 매핑을 쓰고(헤더 검증은 함), 없으면 헤더로 감지한다.
    """
    text = _read_text(path)
    lines = text.splitlines()
    if not lines:
        raise ValueError(f"빈 CSV: {path}")
    header = next(csv.reader([lines[0]]))
    if bank is not None:
        if bank not in BANKS:
            raise UnknownBankError(f"매핑 테이블에 없는 은행: {bank}")
        mapping = BANKS[bank]
        if not mapping.required_columns <= {h.strip() for h in header}:
            raise UnknownBankError(f"{bank} 매핑과 헤더가 맞지 않습니다: {header}")
    else:
        mapping = detect_bank(header)
    index = {h.strip(): i for i, h in enumerate(header)}

    for lineno, raw in enumerate(lines[1:], start=2):
        if not raw.strip():
            continue
        row = next(csv.reader([raw]))
        if len(row) < len(header):
            raise ValueError(f"{path.name}:{lineno} 컬럼 수가 헤더보다 적습니다")

        def col(name: str) -> str:
            return row[index[name]].strip()

        dt_text = col(mapping.date_col)
        if mapping.time_col:
            dt_text = f"{dt_text} {col(mapping.time_col)}"
        try:
            ts = datetime.strptime(dt_text, mapping.datetime_fmt).replace(tzinfo=KST)
        except ValueError as e:
            raise ValueError(f"{path.name}:{lineno} 거래일시 해석 실패 {dt_text!r}") from e

        withdraw = parse_amount(col(mapping.withdraw_col))
        deposit = parse_amount(col(mapping.deposit_col))
        if (withdraw > 0) == (deposit > 0):
            raise ValueError(f"{path.name}:{lineno} 출금/입금이 둘 다 있거나 둘 다 없습니다")
        direction = "withdraw" if withdraw else "deposit"
        amount = withdraw or deposit
        to_account_raw = col(mapping.to_account_col)
        to_account = norm_account(to_account_raw)
        to_bank = col(mapping.to_bank_col)
        to_name = col(mapping.to_name_col)
        memo = col(mapping.memo_col)

        label = "출금" if direction == "withdraw" else "입금"
        text_parts = [f"{label} {amount:,}원", memo]
        if to_account_raw:
            text_parts.append(f"→ {to_bank} {to_account_raw} ({to_name})" if to_name else f"→ {to_bank} {to_account_raw}")
        yield Event(
            ts=ts,
            kind="transfer",
            actor=victim,
            text=" ".join(p for p in text_parts if p),
            src=path.name,
            line=lineno,
            extracted={"accounts": [to_account] if to_account else [], "phones": [], "urls": [], "wallets": [], "amounts": [amount]},
            meta={
                "bank_format": mapping.name,
                "direction": direction,
                "memo": memo,
                "to_account": to_account,
                "to_account_raw": to_account_raw,
                "to_bank": to_bank,
                "to_name": to_name,
                "balance": parse_amount(col(mapping.balance_col)),
            },
        )
