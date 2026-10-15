"""수사보고서 초안(markdown) 생성 - 템플릿 기반, LLM 없음.

규칙
- 모든 문장(불릿)과 표의 모든 행은 끝에 [src:line] 각주를 가진다.
- 근거가 비어 있는 문장은 쓰지 않고 ReviewItem(category="report_sentence_no_evidence") 으로 뺀다.
- 생성 시각·git hash 같은 메타는 문장이 아니라 HTML 주석으로 남긴다(근거가 있을 수 없는 정보이므로).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from eo.schema import EXTRACTED_KEYS, Event, Evidence, LedgerRow, ReviewItem

if TYPE_CHECKING:
    from eo.narrative import NarrativeSentence
    from eo.roles import RoleJudgement

CATEGORY_LABELS = {"accounts": "계좌번호", "phones": "전화번호", "urls": "URL", "wallets": "가상자산 주소", "amounts": "금액"}


def fmt_ts(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d %H:%M") + " KST"


def footnotes(evidence: Iterable[Evidence]) -> str:
    uniq = sorted(set(evidence), key=lambda e: (e.src, e.line))
    return "".join(str(e) for e in uniq)


@dataclass
class ReportBuilder:
    lines: list[str] = field(default_factory=list)
    dropped: list[ReviewItem] = field(default_factory=list)
    sentence_count: int = 0

    def heading(self, text: str, level: int = 2) -> None:
        self.lines += ["", "#" * level + " " + text, ""]

    def comment(self, text: str) -> None:
        self.lines.append(f"<!-- {text} -->")

    def sentence(self, text: str, evidence: Sequence[Evidence]) -> bool:
        """근거가 있으면 불릿 한 줄로 쓰고 True. 없으면 needs_review 로 빼고 False."""
        if not evidence:
            self.dropped.append(ReviewItem(category="report_sentence_no_evidence", reason="근거(src,line)를 붙일 수 없어 보고서에서 제외", value=text))
            return False
        self.lines.append(f"- {text} {footnotes(evidence)}")
        self.sentence_count += 1
        return True

    def table(self, header: Sequence[str], rows: Sequence[tuple[Sequence[str], Sequence[Evidence]]]) -> int:
        """마지막 열을 '근거' 로 하는 표. 근거 없는 행은 제외한다. 쓴 행 수를 돌려준다."""
        kept = [(cells, ev) for cells, ev in rows if ev]
        for cells, ev in rows:
            if not ev:
                self.dropped.append(ReviewItem(category="report_row_no_evidence", reason="근거 없는 표 행 제외", value=" | ".join(cells)))
        if not kept:
            return 0
        if self.lines and self.lines[-1] != "":
            self.lines.append("")  # 불릿 뒤에 바로 표가 오면 markdown 이 합쳐 버린다
        self.lines.append("| " + " | ".join([*header, "근거"]) + " |")
        self.lines.append("|" + "---|" * (len(header) + 1))
        for cells, ev in kept:
            self.lines.append("| " + " | ".join([*(c.replace("|", "\\|") for c in cells), footnotes(ev)]) + " |")
            self.sentence_count += 1
        self.lines.append("")
        return len(kept)

    def render(self) -> str:
        return "\n".join(self.lines).strip() + "\n"


def build_report(
    *,
    case_name: str,
    events: Sequence[Event],
    ledger: Sequence[LedgerRow],
    reviews: Sequence[ReviewItem],
    extracted: dict[str, dict[str, list[dict]]],
    generated_at: datetime,
    git_hash: str,
    roles: Sequence["RoleJudgement"] = (),
    narrative: Sequence["NarrativeSentence"] = (),
    llm_name: str = "",
) -> tuple[str, list[ReviewItem]]:
    """보고서 markdown 과, 근거가 없어 제외된 문장 목록을 돌려준다.

    roles / narrative 는 2단계(로컬 LLM) 산출물이며 비어 있으면 해당 절을 쓰지 않는다.
    """
    b = ReportBuilder()
    b.lines.append(f"# 수사보고서 초안 - {case_name}")
    stage = f"stage2 (로컬 LLM: {llm_name})" if llm_name else "stage1 (LLM 미사용)"
    b.comment(f"generated_at={generated_at.isoformat()} git={git_hash} tool=evidence-organizer {stage}")
    b.comment("이 문서는 자동 생성된 초안이다. 모든 문장은 [파일명:행번호] 근거를 가지며, 확정은 수사관이 한다.")

    messages = [e for e in events if e.kind == "message"]
    transfers = [e for e in events if e.kind == "transfer"]

    # 1. 자료 개요 --------------------------------------------------------------
    b.heading("1. 분석 자료")
    by_src: dict[str, list[Event]] = {}
    for e in events:
        by_src.setdefault(e.src, []).append(e)
    for src, evs in sorted(by_src.items()):
        kinds = Counter(e.kind for e in evs)
        desc = ", ".join(f"{k} {n}건" for k, n in sorted(kinds.items()))
        b.sentence(f"파일 `{src}`에서 이벤트 {len(evs)}건({desc})을 읽었다.", [evs[0].evidence, evs[-1].evidence])

    # 2. 대화 개요 --------------------------------------------------------------
    b.heading("2. 대화 개요")
    if messages:
        first, last = messages[0], messages[-1]
        b.sentence(f"대화는 {fmt_ts(first.ts)}에 시작하여 {fmt_ts(last.ts)}에 끝났다(메시지 {len(messages)}건).", [first.evidence, last.evidence])
        per_actor: dict[str, list[Event]] = {}
        for m in messages:
            per_actor.setdefault(m.actor, []).append(m)
        role_by_actor = {r.actor: r for r in roles}
        for actor, evs in sorted(per_actor.items(), key=lambda kv: -len(kv[1])):
            b.sentence(f"참여자 '{actor}'은(는) 메시지 {len(evs)}건을 보냈다(첫 메시지 {fmt_ts(evs[0].ts)}, 마지막 {fmt_ts(evs[-1].ts)}).", [evs[0].evidence, evs[-1].evidence])
            r = role_by_actor.get(actor)
            if r is not None and r.role != "unknown":
                from eo.roles import ROLE_LABELS  # 순환 import 방지

                tag = "확정" if r.status == "confirmed" else "제안, 검토 필요"
                b.sentence(f"'{actor}'의 역할은 {ROLE_LABELS.get(r.role, r.role)}로 판단된다({tag}, 신뢰도 {r.confidence:.0%}): {r.reason}", r.evidence)
    else:
        b.sentence("대화 자료가 없다.", [])  # 근거 없음 → 제외됨

    # 3. 범죄일람표 ---------------------------------------------------------------
    confirmed = [r for r in ledger if r.status == "confirmed"]
    review_rows = [r for r in ledger if r.status != "confirmed"]
    b.heading("3. 범죄일람표 (confirmed)")
    if confirmed:
        total = sum(r.amount for r in confirmed)
        transfer_srcs = {t.src for t in transfers}
        # 합계 문장의 근거는 이체내역 행들이다(대화 행은 각 표 행에 붙는다).
        b.sentence(
            f"대화 속 계좌·금액과 일치하는 피해 이체는 {len(confirmed)}건, 합계 {total:,}원이다.",
            [e for r in confirmed for e in r.evidence if e.src in transfer_srcs],
        )
        b.table(
            ["순번", "일시", "피해자", "입금은행", "입금계좌(숫자만)", "금액(원)"],
            [([str(i), fmt_ts(r.ts), r.victim, r.bank, r.to_account, f"{r.amount:,}"], r.evidence) for i, r in enumerate(confirmed, 1)],
        )
    else:
        b.comment("확정된 피해 이체 없음")

    # 4. 확인 필요 이체 -----------------------------------------------------------
    b.heading("4. 확인 필요 이체 (needs_review)")
    if review_rows:
        b.table(
            ["순번", "일시", "입금은행", "입금계좌(숫자만)", "금액(원)", "사유"],
            [([str(i), fmt_ts(r.ts), r.bank or "-", r.to_account or "-", f"{r.amount:,}", "; ".join(r.notes)], r.evidence) for i, r in enumerate(review_rows, 1)],
        )
    else:
        b.comment("확인 필요 이체 없음")

    # 5. 추출된 식별정보 ----------------------------------------------------------
    b.heading("5. 대화에서 추출된 식별정보")
    for key in EXTRACTED_KEYS:
        if key == "amounts":
            continue
        values = extracted.get(key, {})
        if not values:
            continue
        b.heading(f"5.{list(EXTRACTED_KEYS).index(key) + 1} {CATEGORY_LABELS[key]}", level=3)
        for value, evs in sorted(values.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            evidence = [Evidence(d["src"], int(d["line"])) for d in evs]
            actors = sorted({e.actor for e in messages if e.evidence in set(evidence)})
            who = f" (발신: {', '.join(actors)})" if actors else ""
            b.sentence(f"{CATEGORY_LABELS[key]} `{value}`이(가) 대화에 {len(evs)}회 등장한다{who}.", evidence)

    # 6. 사건 경위 (LLM 서술) --------------------------------------------------------
    if narrative:
        b.heading("6. 사건 경위 (로컬 LLM 서술 초안, 전부 검토 필요)")
        for sent in narrative:
            b.sentence(sent.text, sent.evidence)

    # 7. 검토 필요 항목 -----------------------------------------------------------
    b.heading("7. 검토 필요 항목 (needs_review)" if narrative else "6. 검토 필요 항목 (needs_review)")
    wrote = 0
    for item in reviews:
        wrote += b.sentence(f"[{item.category}] '{item.value}': {item.reason}", item.evidence)
    if not wrote:
        b.comment("검토 필요 항목 없음")

    return b.render(), b.dropped


def write_report(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
