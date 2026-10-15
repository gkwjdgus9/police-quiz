"""공통 스키마.

모든 산출물은 {"src": 파일명, "line": 행번호} 근거를 가진다.
모든 판정은 status("confirmed" | "needs_review")를 가지며 기본값은 needs_review 다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

# 한국 표준시. 모든 ts 는 이 tz 를 가진 aware datetime 이어야 한다.
KST = timezone(timedelta(hours=9), name="KST")

Status = Literal["confirmed", "needs_review"]
EventKind = Literal["message", "transfer", "screenshot"]

# extracted 딕셔너리가 항상 갖는 키. 값은 정규화된 문자열 목록(금액만 int 목록).
EXTRACTED_KEYS: tuple[str, ...] = ("accounts", "phones", "urls", "wallets", "amounts")


def empty_extracted() -> dict[str, list[Any]]:
    return {key: [] for key in EXTRACTED_KEYS}


@dataclass(frozen=True)
class Evidence:
    """근거 한 건: 원본 파일명과 행 번호(1부터)."""

    src: str
    line: int

    def to_dict(self) -> dict[str, Any]:
        return {"src": self.src, "line": self.line}

    def __str__(self) -> str:
        return f"[{self.src}:{self.line}]"


@dataclass
class Event:
    """타임라인의 기본 단위. 파서가 yield 한다."""

    ts: datetime
    kind: EventKind
    actor: str
    text: str
    src: str
    line: int
    extracted: dict[str, list[Any]] = field(default_factory=empty_extracted)
    # 파서가 알고 있는 부가 정보(이체 이벤트의 은행·상대계좌·입출금 구분 등).
    # 스키마에 없는 필드이므로 보고서 문장의 근거로는 쓰지 않고, src/line 만 근거가 된다.
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise ValueError(f"ts 는 tz-aware 여야 합니다: {self.src}:{self.line}")
        for key in EXTRACTED_KEYS:
            self.extracted.setdefault(key, [])

    @property
    def evidence(self) -> Evidence:
        return Evidence(self.src, self.line)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Event":
        return cls(
            ts=datetime.fromisoformat(d["ts"]),
            kind=d["kind"],
            actor=d["actor"],
            text=d["text"],
            src=d["src"],
            line=int(d["line"]),
            extracted=dict(d.get("extracted") or {}),
            meta=dict(d.get("meta") or {}),
        )


@dataclass
class LedgerRow:
    """범죄일람표 한 행."""

    ts: datetime
    victim: str
    to_account: str
    bank: str
    amount: int
    evidence: list[Evidence] = field(default_factory=list)
    status: Status = "needs_review"
    # 판정 사유(사람이 검토할 때 읽는 메모). 근거가 아니라 설명이다.
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "victim": self.victim,
            "to_account": self.to_account,
            "bank": self.bank,
            "amount": self.amount,
            "evidence": [e.to_dict() for e in self.evidence],
            "status": self.status,
            "notes": list(self.notes),
        }


@dataclass
class ReviewItem:
    """needs_review 로 빠진 항목. 무엇이, 왜, 어디서 나왔는지 기록한다."""

    category: str
    reason: str
    value: str
    evidence: list[Evidence] = field(default_factory=list)
    status: Status = "needs_review"

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "reason": self.reason,
            "value": self.value,
            "evidence": [e.to_dict() for e in self.evidence],
            "status": self.status,
        }
