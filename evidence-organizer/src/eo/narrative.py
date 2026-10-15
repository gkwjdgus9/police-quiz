"""사건 경위 서술 생성 (2단계, 로컬 LLM).

확정된 일람표 행의 근거(이체 행 + 대화 행)와 역할 판정 근거를 '자료 묶음'으로 주고,
시간순 서술을 문장 단위 JSON 으로 받는다. 문장마다 검증한다.
  1. 인용이 하나 이상 있고, 전부 자료 묶음 안의 행이어야 한다.
  2. 문장 속 금액·계좌·전화번호·긴 숫자열은 인용한 행의 본문에 실제로 있어야 한다.
  3. 문장 속 참여자 이름은 인용한 행의 발신자이거나 본문에 있어야 한다(피해자 이름은 사건 정보이므로 예외).
하나라도 어기면 보고서에 쓰지 않고 needs_review 로 뺀다. 통과한 문장도 status 는 needs_review 다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from eo.extract import digits, extract_accounts, extract_amounts, extract_phones
from eo.llm import LLMClient, LLMError
from eo.parsers.kakao import SYSTEM_ACTOR
from eo.roles import RoleJudgement
from eo.schema import Event, Evidence, LedgerRow, ReviewItem, Status

MAX_SENTENCE_CHARS = 300
_LONG_DIGITS = re.compile(r"\d{5,}")

SYSTEM_PROMPT = """당신은 사이버사기 수사관을 돕는 분석 보조다. 제공된 자료 묶음만으로 사건 경위를 시간순 한국어 문장으로 쓴다.
규칙:
- 문장마다 근거 행을 cites 에 넣는다. 자료 묶음에 있는 src 와 line 만 쓴다.
- 자료에 없는 사실, 금액, 계좌, 이름, 날짜를 지어내지 않는다. 금액·계좌는 자료에 적힌 그대로 쓴다.
- 추측·평가("사기로 보인다" 등)는 쓰지 않고 자료에 적힌 사실만 쓴다.
- 문장은 짧게, 하나의 사실만. 최대 {max_sentences}문장.
반드시 아래 JSON 형식으로만 답한다.
{{"sentences": [{{"text": "<문장>", "cites": [{{"src": "<파일명>", "line": <행번호>}}]}}]}}"""


@dataclass
class NarrativeSentence:
    text: str
    evidence: list[Evidence] = field(default_factory=list)
    status: Status = "needs_review"

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "evidence": [e.to_dict() for e in self.evidence], "status": self.status}


@dataclass(frozen=True)
class ContextLine:
    src: str
    line: int
    ts: str
    actor: str
    text: str

    @property
    def key(self) -> tuple[str, int]:
        return (self.src, self.line)


def build_context(events: Sequence[Event], ledger: Sequence[LedgerRow], roles: Sequence[RoleJudgement] = (), *, max_lines: int = 60) -> list[ContextLine]:
    """인용 가능한 자료 묶음. confirmed 일람표 근거 → 역할 근거 → 첫·마지막 메시지 순으로 채운다."""
    by_key = {(e.src, e.line): e for e in events}
    wanted: list[tuple[str, int]] = []

    def add(src: str, line: int) -> None:
        if (src, line) in by_key and (src, line) not in wanted:
            wanted.append((src, line))

    for row in ledger:
        if row.status != "confirmed":
            continue
        for ev in row.evidence:
            add(ev.src, ev.line)
    for r in roles:
        for ev in r.evidence:
            add(ev.src, ev.line)
    messages = [e for e in events if e.kind == "message" and e.actor != SYSTEM_ACTOR]
    if messages:
        add(messages[0].src, messages[0].line)
        add(messages[-1].src, messages[-1].line)

    out: list[ContextLine] = []
    for key in wanted[:max_lines]:
        e = by_key[key]
        out.append(ContextLine(src=e.src, line=e.line, ts=e.ts.strftime("%Y-%m-%d %H:%M"), actor=e.actor, text=e.text[:240]))
    out.sort(key=lambda c: (c.ts, c.src, c.line))
    return out


def _check_grounding(text: str, cited: Sequence[ContextLine], *, actors: set[str], victim: str) -> str | None:
    """위반 사유를 돌려준다. 문제없으면 None."""
    # 인용 행의 시각·발신자·본문이 모두 근거다 (문장이 날짜를 쓰면 그 행의 ts 와 맞아야 한다)
    cited_text = "\n".join(f"{c.ts} {c.actor} {c.text}" for c in cited)
    cited_digits = digits(cited_text)
    cited_amounts, _ = extract_amounts(cited_text)
    cited_accounts = set(extract_accounts(cited_text))
    cited_phones = set(extract_phones(cited_text))

    amounts, _ = extract_amounts(text)
    for a in amounts:
        if a not in cited_amounts:
            return f"금액 {a:,}원이 인용 행에 없음"
    for acc in extract_accounts(text):
        if acc not in cited_accounts:
            return f"계좌 {acc}가 인용 행에 없음"
    for ph in extract_phones(text):
        if ph not in cited_phones:
            return f"전화번호 {ph}가 인용 행에 없음"
    for run in _LONG_DIGITS.findall(text.replace(",", "").replace("-", "")):
        if run not in cited_digits:
            return f"숫자열 {run}이 인용 행에 없음"
    cited_actors = {c.actor for c in cited}
    for name in actors:
        if name == victim or name == SYSTEM_ACTOR:
            continue
        if name in text and name not in cited_actors and name not in cited_text:
            return f"참여자 '{name}'이 인용 행에 없음"
    return None


def generate_narrative(
    events: Sequence[Event],
    ledger: Sequence[LedgerRow],
    roles: Sequence[RoleJudgement],
    *,
    victim: str,
    llm: LLMClient | None,
    max_sentences: int = 10,
    max_context_lines: int = 60,
) -> tuple[list[NarrativeSentence], list[ReviewItem]]:
    """(통과한 문장, 버린 문장) 을 돌려준다. llm 이 None 이면 둘 다 비어 있다."""
    if llm is None:
        return [], []
    context = build_context(events, ledger, roles, max_lines=max_context_lines)
    if not context:
        return [], []
    by_key = {c.key: c for c in context}
    actors = {e.actor for e in events if e.kind == "message"}

    role_lines = [f"- {r.actor}: {r.role} ({'확정' if r.status == 'confirmed' else '제안'})" for r in roles]
    prompt = (
        f"피해자: {victim}\n참여자 역할(참고용, 인용 불가):\n" + "\n".join(role_lines) +
        "\n\n자료 묶음(인용 가능한 행):\n" +
        "\n".join(json.dumps({"src": c.src, "line": c.line, "ts": c.ts, "actor": c.actor, "text": c.text}, ensure_ascii=False) for c in context)
    )
    try:
        obj = llm.complete_json(system=SYSTEM_PROMPT.format(max_sentences=max_sentences), prompt=prompt, task="narrative")
    except LLMError as e:
        return [], [ReviewItem(category="narrative_error", reason=f"LLM 호출 실패: {e}", value="")]

    kept: list[NarrativeSentence] = []
    dropped: list[ReviewItem] = []
    raw_sentences = obj.get("sentences", [])
    if not isinstance(raw_sentences, list):
        return [], [ReviewItem(category="narrative_error", reason="sentences 가 목록이 아님", value=json.dumps(obj, ensure_ascii=False)[:200])]

    for item in raw_sentences[:max_sentences]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        if len(text) > MAX_SENTENCE_CHARS:
            dropped.append(ReviewItem(category="narrative_dropped", reason=f"문장이 {MAX_SENTENCE_CHARS}자를 넘음", value=text))
            continue
        cites: list[ContextLine] = []
        bad_cite = None
        for c in item.get("cites", []) if isinstance(item.get("cites"), list) else []:
            try:
                key = (str(c["src"]), int(c["line"]))
            except (KeyError, TypeError, ValueError):
                bad_cite = f"인용 형식 오류: {c!r}"
                break
            if key not in by_key:
                bad_cite = f"자료 묶음에 없는 행 인용: {key[0]}:{key[1]}"
                break
            if by_key[key] not in cites:
                cites.append(by_key[key])
        if bad_cite:
            dropped.append(ReviewItem(category="narrative_dropped", reason=bad_cite, value=text))
            continue
        if not cites:
            dropped.append(ReviewItem(category="narrative_dropped", reason="인용 없음", value=text))
            continue
        problem = _check_grounding(text, cites, actors=actors, victim=victim)
        if problem:
            dropped.append(ReviewItem(category="narrative_dropped", reason=problem, value=text, evidence=[Evidence(c.src, c.line) for c in cites]))
            continue
        kept.append(NarrativeSentence(text=text, evidence=[Evidence(c.src, c.line) for c in cites]))
    return kept, dropped
