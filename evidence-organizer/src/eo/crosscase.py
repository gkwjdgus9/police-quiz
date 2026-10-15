"""사건 간 교차 조회 (3단계).

여러 사건의 out/<case>/extracted.json 과 ledger.json 을 읽어, 두 사건 이상에 같은 값(계좌·전화·URL·지갑주소)이
등장하면 묶어서 보여 준다. 어떤 사건에서든 confirmed 일람표의 입금 계좌였으면 '피해 계좌' 로 표시한다.
결과는 전부 needs_review 다. 같은 계좌가 나왔다는 사실만 보여 주고, 같은 조직이라는 판단은 사람이 한다.
근거는 사건 이름을 붙인 {case, src, line} 으로 적는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CATEGORIES = ("accounts", "phones", "urls", "wallets")
CATEGORY_LABELS = {"accounts": "계좌번호", "phones": "전화번호", "urls": "URL", "wallets": "가상자산 주소"}


@dataclass
class CaseIndex:
    case: str
    values: dict[str, dict[str, list[dict[str, Any]]]]   # category → value → [{src,line}]
    fraud_accounts: set[str]                             # confirmed 일람표의 입금 계좌
    victim: str = ""

    @classmethod
    def load(cls, out_dir: Path) -> "CaseIndex":
        extracted = json.loads((out_dir / "extracted.json").read_text(encoding="utf-8"))
        ledger_path = out_dir / "ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else []
        fraud = {str(r["to_account"]) for r in ledger if r.get("status") == "confirmed" and r.get("to_account")}
        victim = next((str(r.get("victim", "")) for r in ledger), "")
        return cls(case=out_dir.name, values={c: dict(extracted.get(c, {})) for c in CATEGORIES}, fraud_accounts=fraud, victim=victim)


@dataclass
class SharedValue:
    category: str
    value: str
    cases: list[dict[str, Any]] = field(default_factory=list)   # [{case, mentions, fraud_account, evidence:[{case,src,line}]}]
    status: str = "needs_review"

    @property
    def is_fraud_account(self) -> bool:
        return any(c["fraud_account"] for c in self.cases)

    def to_dict(self) -> dict[str, Any]:
        return {"category": self.category, "value": self.value, "cases": self.cases, "fraud_account": self.is_fraud_account, "status": self.status}


def find_shared(cases: list[CaseIndex], *, max_evidence: int = 3) -> list[SharedValue]:
    """두 사건 이상에 등장하는 값. 피해 계좌 → 사건 수 많은 순 → 값 순으로 정렬."""
    out: list[SharedValue] = []
    for category in CATEGORIES:
        values: dict[str, list[CaseIndex]] = {}
        for ci in cases:
            for v in ci.values.get(category, {}):
                values.setdefault(v, []).append(ci)
        for value, holders in values.items():
            if len(holders) < 2:
                continue
            sv = SharedValue(category=category, value=value)
            for ci in holders:
                evs = ci.values[category][value]
                sv.cases.append({
                    "case": ci.case,
                    "mentions": len(evs),
                    "fraud_account": category == "accounts" and value in ci.fraud_accounts,
                    "evidence": [{"case": ci.case, **e} for e in evs[:max_evidence]],
                })
            out.append(sv)
    out.sort(key=lambda s: (not s.is_fraud_account, -len(s.cases), CATEGORIES.index(s.category), s.value))
    return out


def fmt_evidence(evs: list[dict[str, Any]]) -> str:
    return "".join(f"[{e['case']}/{e['src']}:{e['line']}]" for e in evs)


def render_markdown(shared: list[SharedValue], cases: list[CaseIndex]) -> str:
    lines = ["# 사건 간 교차 조회", "", f"대상 사건: {', '.join(c.case for c in cases)} ({len(cases)}건). 모든 행은 needs_review 이며, 같은 값이 등장했다는 사실만 적는다.", ""]
    if not shared:
        lines.append("<!-- 두 사건 이상에 공통으로 등장하는 값 없음 -->")
        return "\n".join(lines) + "\n"
    lines += ["| 구분 | 값 | 사건 수 | 피해 계좌 | 사건별 등장 | 근거 |", "|---|---|---|---|---|---|"]
    for sv in shared:
        per_case = ", ".join(f"{c['case']} {c['mentions']}회" + (" (confirmed 입금계좌)" if c["fraud_account"] else "") for c in sv.cases)
        evidence = fmt_evidence([e for c in sv.cases for e in c["evidence"]])
        lines.append(f"| {CATEGORY_LABELS[sv.category]} | `{sv.value}` | {len(sv.cases)} | {'예' if sv.is_fraud_account else '-'} | {per_case} | {evidence} |")
    lines.append("")
    return "\n".join(lines) + "\n"


def evaluate_shared(shared: list[SharedValue], labels_by_case: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """labels.shared_with 대비. 정답 = (category, value) 가 어떤 사건 라벨에든 공유로 적힌 것."""
    gold: set[tuple[str, str]] = set()
    for labels in labels_by_case.values():
        for _other, cats in labels.get("shared_with", {}).items():
            for category, values in cats.items():
                gold |= {(category, v) for v in values}
    pred = {(s.category, s.value) for s in shared}
    tp = len(pred & gold)
    return {
        "tp": tp, "fp": len(pred - gold), "fn": len(gold - pred),
        "recall": round(tp / len(gold), 4) if gold else 0.0,
        "precision": round(tp / len(pred), 4) if pred else 0.0,
        "missing": sorted(f"{c}:{v}" for c, v in gold - pred),
        "extra": sorted(f"{c}:{v}" for c, v in pred - gold),
    }
