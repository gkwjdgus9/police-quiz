"""범죄일람표(ledger).

이체 CSV 의 출금 건마다 한 행을 만든다. 판정 규칙(1단계, 결정적):
  confirmed    : 이체의 상대 계좌가 대화에서 추출된 계좌와 일치하고, 이체 금액과 같은 명시 금액이 대화에 등장한다.
  needs_review : 그 외 전부(계좌만 일치, 금액만 일치, 둘 다 불일치, 상대 계좌 없음). notes 에 사유를 적는다.
입금 건은 피해자의 송금이 아니므로 일람표에 넣지 않는다.
모든 행의 evidence 에는 CSV 행이 반드시 들어가고, 일치한 대화 행이 덧붙는다.
캡처 OCR(screenshot) 행은 계좌·금액이 맞으면 evidence 에 덧붙이되 status 판정에는 쓰지 않는다
(피해자 본인의 이체 완료 화면은 이체가 있었다는 증거이지, 대화에서 유도됐다는 증거가 아니다).
"""

from __future__ import annotations

from collections.abc import Iterable

from eo.schema import Event, Evidence, LedgerRow


def _unique_sorted(evidence: Iterable[Evidence]) -> list[Evidence]:
    return sorted(set(evidence), key=lambda e: (e.src, e.line))


def build_ledger(events: Iterable[Event], *, victim: str) -> list[LedgerRow]:
    events = list(events)
    messages = [e for e in events if e.kind == "message"]
    screenshots = [e for e in events if e.kind == "screenshot" and e.line > 0]
    transfers = [e for e in events if e.kind == "transfer"]

    # 대화 속 계좌/금액 → 근거 행 색인
    account_index: dict[str, list[Evidence]] = {}
    amount_index: dict[int, list[Evidence]] = {}
    for m in messages:
        for acc in m.extracted.get("accounts", []):
            account_index.setdefault(str(acc), []).append(m.evidence)
        for amt in m.extracted.get("amounts", []):
            amount_index.setdefault(int(amt), []).append(m.evidence)

    # 캡처 색인(보조 근거)
    shot_account_index: dict[str, list[Evidence]] = {}
    shot_amount_index: dict[int, list[Evidence]] = {}
    for sh in screenshots:
        for acc in sh.extracted.get("accounts", []):
            shot_account_index.setdefault(str(acc), []).append(sh.evidence)
        for amt in sh.extracted.get("amounts", []):
            shot_amount_index.setdefault(int(amt), []).append(sh.evidence)

    rows: list[LedgerRow] = []
    for t in transfers:
        if t.meta.get("direction") != "withdraw":
            continue
        to_account = str(t.meta.get("to_account", ""))
        amount = int(t.extracted["amounts"][0]) if t.extracted.get("amounts") else 0
        evidence: list[Evidence] = [t.evidence]
        notes: list[str] = []

        account_hits = account_index.get(to_account, []) if to_account else []
        amount_hits = amount_index.get(amount, [])
        evidence += account_hits + amount_hits

        if not to_account:
            notes.append("상대 계좌 정보 없음(카드·ATM 등)")
            status = "needs_review"
        elif account_hits and amount_hits:
            status = "confirmed"
            notes.append(f"대화에서 계좌 {len(account_hits)}회, 금액 {len(amount_hits)}회 확인")
        elif account_hits:
            status = "needs_review"
            notes.append(f"대화에서 계좌는 {len(account_hits)}회 확인되나 금액 {amount:,}원의 명시 표기는 없음")
        elif amount_hits:
            status = "needs_review"
            notes.append(f"금액 {amount:,}원은 대화에 {len(amount_hits)}회 등장하나 계좌는 대화에 없음")
        else:
            status = "needs_review"
            notes.append("대화에서 계좌·금액 모두 확인되지 않음")

        shot_hits = (shot_account_index.get(to_account, []) if to_account else []) + shot_amount_index.get(amount, [])
        if shot_hits:
            evidence += shot_hits
            notes.append(f"캡처 OCR 에서 계좌/금액 {len(set(shot_hits))}건 일치(보조 근거)")

        rows.append(LedgerRow(
            ts=t.ts,
            victim=victim or t.actor,
            to_account=to_account,
            bank=str(t.meta.get("to_bank", "")),
            amount=amount,
            evidence=_unique_sorted(evidence),
            status=status,
            notes=notes,
        ))
    rows.sort(key=lambda r: r.ts)
    return rows
