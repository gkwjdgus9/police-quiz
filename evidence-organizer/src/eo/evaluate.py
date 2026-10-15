"""평가: labels.json(정답) 대비 산출물 품질을 표로 낸다.

- 추출 재현율·정밀도: 대화에서 추출된 계좌·전화·URL·지갑 집합 vs labels.chat.*
- 일람표 재현율·정밀도: confirmed 행 vs labels.fraud_transfers (계좌·금액·CSV 행 번호로 대조)
  보조 지표로 needs_review 까지 포함했을 때의 재현율도 낸다.
- 보고서: 내용 줄(불릿·표 행) 중 각주가 없거나, 각주가 가리키는 파일·행이 실제로 없는 비율.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FOOTNOTE = re.compile(r"\[([^\[\]:]+):(\d+)\]")
TABLE_SEP = re.compile(r"\|(?:\s*:?-+:?\s*\|)+")
EXTRACT_KEYS = ("accounts", "phones", "urls", "wallets")


@dataclass
class PR:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn, "precision": round(self.precision, 4), "recall": round(self.recall, 4), "missing": self.missing, "extra": self.extra}


def _pr(pred: set[str], gold: set[str]) -> PR:
    return PR(tp=len(pred & gold), fp=len(pred - gold), fn=len(gold - pred), missing=sorted(gold - pred), extra=sorted(pred - gold))


def evaluate_extraction(extracted: dict[str, dict[str, Any]], labels: dict[str, Any]) -> dict[str, PR]:
    gold_chat = labels.get("chat", {})
    return {key: _pr(set(extracted.get(key, {})), set(gold_chat.get(key, []))) for key in EXTRACT_KEYS}


def _ledger_key(row: dict[str, Any], csv_src_hint: str | None) -> tuple[str, int, int | None]:
    csv_lines = [e["line"] for e in row.get("evidence", []) if csv_src_hint is None or e["src"] == csv_src_hint]
    return (str(row["to_account"]), int(row["amount"]), min(csv_lines) if csv_lines else None)


def evaluate_ledger(ledger: list[dict[str, Any]], labels: dict[str, Any]) -> dict[str, PR]:
    fraud = labels.get("fraud_transfers", [])
    srcs = {f["evidence"]["src"] for f in fraud if "evidence" in f}
    src_hint = next(iter(srcs)) if len(srcs) == 1 else None
    gold = {(str(f["to_account"]), int(f["amount"]), int(f["evidence"]["line"])) for f in fraud}
    confirmed = {_ledger_key(r, src_hint) for r in ledger if r.get("status") == "confirmed"}
    all_rows = {_ledger_key(r, src_hint) for r in ledger}
    fmt = lambda s: {f"{a}/{amt}/line{ln}" for a, amt, ln in s}  # noqa: E731
    return {"confirmed": _pr(fmt(confirmed), fmt(gold)), "confirmed_or_review": _pr(fmt(all_rows), fmt(gold))}


def report_content_lines(md: str) -> list[str]:
    """보고서에서 '문장'으로 치는 줄: 불릿, 표의 본문 행. 제목·주석·표 머리글·구분선은 제외."""
    lines = md.splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        if line.startswith("- "):
            out.append(line)
        elif line.startswith("|"):
            if TABLE_SEP.fullmatch(line.strip()):
                continue
            if i + 1 < len(lines) and TABLE_SEP.fullmatch(lines[i + 1].strip()):
                continue  # 머리글
            out.append(line)
    return out


def evaluate_report(md: str, raw_dir: Path) -> dict[str, Any]:
    sizes: dict[str, int] = {}
    for p in raw_dir.rglob("*"):
        if p.is_file():
            sizes[p.name] = len(p.read_bytes().decode("utf-8-sig", errors="replace").splitlines())
    content = report_content_lines(md)
    no_footnote: list[str] = []
    bad_ref: list[str] = []
    for line in content:
        refs = FOOTNOTE.findall(line)
        if not refs:
            no_footnote.append(line)
            continue
        for src, ln in refs:
            if src not in sizes or not (1 <= int(ln) <= sizes[src]):
                bad_ref.append(f"{line[:60]}… → [{src}:{ln}]")
                break
    total = len(content)
    unsupported = len(no_footnote) + len(bad_ref)
    return {
        "sentences": total,
        "no_footnote": len(no_footnote),
        "bad_reference": len(bad_ref),
        "unsupported_ratio": round(unsupported / total, 4) if total else 0.0,
        "examples": (no_footnote + bad_ref)[:5],
    }


def evaluate_roles(roles: list[dict[str, Any]], labels: dict[str, Any]) -> dict[str, Any]:
    """labels.participants 대비 역할 정확도. 피해자는 사건 정보로 주어지므로 제외한다."""
    gold = labels.get("participants", {})
    victim = labels.get("victim")
    judged = {r["actor"]: r for r in roles}
    total = correct = unknown = 0
    mismatches: list[str] = []
    for actor, role in gold.items():
        if actor == victim:
            continue
        total += 1
        pred = judged.get(actor, {}).get("role", "unknown")
        if pred == role:
            correct += 1
        elif pred == "unknown":
            unknown += 1
        else:
            mismatches.append(f"{actor}: 정답 {role}, 예측 {pred}")
    return {"total": total, "correct": correct, "unknown": unknown, "wrong": total - correct - unknown,
            "accuracy": round(correct / total, 4) if total else 0.0, "mismatches": mismatches,
            "uncited": sum(1 for r in roles if r.get("role") != "unknown" and not r.get("evidence"))}


def evaluate_narrative(narrative: list[dict[str, Any]], dropped: list[dict[str, Any]], raw_dir: Path) -> dict[str, Any]:
    """통과한 문장 수, 버린 문장 수, 통과 문장의 각주가 실제 행을 가리키는지."""
    sizes: dict[str, int] = {}
    for p in raw_dir.rglob("*"):
        if p.is_file():
            sizes[p.name] = len(p.read_bytes().decode("utf-8-sig", errors="replace").splitlines())
    bad = 0
    for s in narrative:
        evs = s.get("evidence", [])
        if not evs or any(e["src"] not in sizes or not (1 <= int(e["line"]) <= sizes[e["src"]]) for e in evs):
            bad += 1
    kept, drop = len(narrative), len(dropped)
    return {"kept": kept, "dropped": drop, "bad_reference": bad,
            "kept_ratio": round(kept / (kept + drop), 4) if kept + drop else 0.0,
            "drop_reasons": [d.get("reason", "") for d in dropped][:5]}


def evaluate_all(*, labels: dict[str, Any], extracted: dict[str, Any], ledger: list[dict[str, Any]], report_md: str, raw_dir: Path,
                 roles: list[dict[str, Any]] | None = None, narrative: list[dict[str, Any]] | None = None, narrative_dropped: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "extraction": {k: v.to_dict() for k, v in evaluate_extraction(extracted, labels).items()},
        "ledger": {k: v.to_dict() for k, v in evaluate_ledger(ledger, labels).items()},
        "report": evaluate_report(report_md, raw_dir),
    }
    if roles is not None:
        result["roles"] = evaluate_roles(roles, labels)
    if narrative is not None:
        result["narrative"] = evaluate_narrative(narrative, narrative_dropped or [], raw_dir)
    return result


def format_table(result: dict[str, Any]) -> str:
    rows = ["| 항목 | 정답 | 예측 | TP | 재현율 | 정밀도 | 누락/오탐 |", "|---|---|---|---|---|---|---|"]
    labels_ko = {"accounts": "추출: 계좌번호", "phones": "추출: 전화번호", "urls": "추출: URL", "wallets": "추출: 가상자산 주소", "confirmed": "일람표: confirmed", "confirmed_or_review": "일람표: confirmed+needs_review"}
    for section in ("extraction", "ledger"):
        for key, pr in result[section].items():
            gold = pr["tp"] + pr["fn"]
            pred = pr["tp"] + pr["fp"]
            note = ", ".join([*(f"누락 {m}" for m in pr["missing"][:3]), *(f"오탐 {e}" for e in pr["extra"][:3])]) or "-"
            rows.append(f"| {labels_ko[key]} | {gold} | {pred} | {pr['tp']} | {pr['recall']:.0%} | {pr['precision']:.0%} | {note} |")
    r = result["report"]
    rows.append("")
    rows.append("| 보고서 | 문장 수 | 각주 없음 | 잘못된 각주 | 근거 없는 비율 |")
    rows.append("|---|---|---|---|---|")
    rows.append(f"| report.md | {r['sentences']} | {r['no_footnote']} | {r['bad_reference']} | {r['unsupported_ratio']:.1%} |")
    if "roles" in result:
        ro = result["roles"]
        rows.append("")
        rows.append("| 역할 분류 (LLM) | 대상 | 정답 | unknown | 오답 | 정확도 | 근거 없는 판정 |")
        rows.append("|---|---|---|---|---|---|---|")
        rows.append(f"| 피해자 제외 참여자 | {ro['total']} | {ro['correct']} | {ro['unknown']} | {ro['wrong']} | {ro['accuracy']:.0%} | {ro['uncited']} |")
    if "narrative" in result:
        na = result["narrative"]
        rows.append("")
        rows.append("| 사건 경위 (LLM) | 통과 문장 | 버린 문장 | 잘못된 각주 | 통과 비율 |")
        rows.append("|---|---|---|---|---|")
        rows.append(f"| narrative | {na['kept']} | {na['dropped']} | {na['bad_reference']} | {na['kept_ratio']:.0%} |")
    return "\n".join(rows) + "\n"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
