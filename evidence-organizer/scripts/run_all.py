"""전체 파이프라인 실행기 (1단계, LLM 없음).

  hashing → parsers → extract → timeline → ledger → report → evaluate

사용:
  python scripts/run_all.py --case data/synthetic/case01 [--out out/case01] [--victim 이름]

입력: <case>/raw/ 아래의 원본(읽기 전용). *.txt 는 카카오톡 내보내기, *.csv 는 은행 이체내역으로 본다.
      <case>/labels.json 이 있으면 평가까지 한다. <case>/case.json 의 victim 을 기본 피해자 이름으로 쓴다.
출력: <out>/manifest.json, run.log, timeline.jsonl, extracted.json, ledger.json, needs_review.json, report.md, evaluate.md|json
네트워크·외부 API 는 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eo.evaluate import evaluate_all, format_table  # noqa: E402
from eo.hashing import build_or_verify_manifest, git_hash  # noqa: E402
from eo.ledger import build_ledger  # noqa: E402
from eo.parsers.bank_csv import parse_bank_csv  # noqa: E402
from eo.parsers.kakao import parse_kakao  # noqa: E402
from eo.report import build_report, write_report  # noqa: E402
from eo.schema import KST, Event, LedgerRow, ReviewItem  # noqa: E402
from eo.timeline import aggregate_extracted, build_timeline, write_json, write_timeline_jsonl  # noqa: E402


def setup_logging(out_dir: Path) -> logging.Logger:
    out_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("eo")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(out_dir / "run.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def parse_raw(raw_dir: Path, victim: str, log: logging.Logger) -> list[Event]:
    events: list[Event] = []
    for path in sorted(p for p in raw_dir.rglob("*") if p.is_file() and not p.name.startswith(".")):
        suffix = path.suffix.lower()
        if suffix == ".txt":
            evs = list(parse_kakao(path))
            log.info("카카오톡 파싱 %s → %d건", path.name, len(evs))
        elif suffix == ".csv":
            evs = list(parse_bank_csv(path, victim=victim))
            log.info("이체내역 파싱 %s → %d건 (%s)", path.name, len(evs), evs[0].meta.get("bank_format") if evs else "-")
        else:
            log.warning("지원하지 않는 파일은 건너뜀: %s", path.name)
            continue
        events.extend(evs)
    return events


def run(case_dir: Path, out_dir: Path, victim: str | None = None) -> dict:
    log = setup_logging(out_dir)
    raw_dir = case_dir / "raw"
    now = datetime.now(KST)
    commit = git_hash(ROOT)
    log.info("실행 시작 case=%s out=%s git=%s", case_dir, out_dir, commit)

    if victim is None:
        case_meta = case_dir / "case.json"
        victim = json.loads(case_meta.read_text(encoding="utf-8")).get("victim", "피해자") if case_meta.exists() else "피해자"

    # 1. 무결성
    manifest = build_or_verify_manifest(raw_dir, out_dir / "manifest.json", repo_dir=ROOT, now=now)
    log.info("manifest: 파일 %d개, 실행 %d회째", len(manifest.files), len(manifest.runs))

    # 2~4. 파싱 → 추출 → 타임라인
    events = parse_raw(raw_dir, victim, log)
    timeline, reviews = build_timeline(events)
    write_timeline_jsonl(timeline, out_dir / "timeline.jsonl")
    extracted = aggregate_extracted(timeline)
    write_json(extracted, out_dir / "extracted.json")
    log.info("타임라인 %d건, 추출: %s, 해석 보류 금액 %d건", len(timeline), {k: len(v) for k, v in extracted.items()}, len(reviews))

    # 5. 일람표
    ledger = build_ledger(timeline, victim=victim)
    write_json([r.to_dict() for r in ledger], out_dir / "ledger.json")
    n_conf = sum(r.status == "confirmed" for r in ledger)
    log.info("일람표 %d행 (confirmed %d, needs_review %d)", len(ledger), n_conf, len(ledger) - n_conf)

    # 6. 보고서
    md, dropped = build_report(case_name=case_dir.name, events=timeline, ledger=ledger, reviews=reviews, extracted=extracted, generated_at=now, git_hash=commit)
    write_report(md, out_dir / "report.md")
    all_reviews = [*reviews, *dropped]
    for r in ledger:
        if r.status != "confirmed":
            all_reviews.append(_ledger_review(r))
    write_json([r.to_dict() for r in all_reviews], out_dir / "needs_review.json")
    log.info("보고서 작성, 근거 없어 제외된 문장 %d건, needs_review 총 %d건", len(dropped), len(all_reviews))

    # 7. 평가
    result: dict = {}
    labels_path = case_dir / "labels.json"
    if labels_path.exists():
        labels = json.loads(labels_path.read_text(encoding="utf-8"))
        result = evaluate_all(labels=labels, extracted=extracted, ledger=[r.to_dict() for r in ledger], report_md=md, raw_dir=raw_dir)
        write_json(result, out_dir / "evaluate.json")
        table = format_table(result)
        (out_dir / "evaluate.md").write_text(f"# 평가 - {case_dir.name}\n\n{table}", encoding="utf-8")
        log.info("평가 완료")
        print(table)
    else:
        log.info("labels.json 없음 → 평가 생략")
    log.info("실행 완료")
    return result


def _ledger_review(row: LedgerRow) -> ReviewItem:
    return ReviewItem(category="ledger_row", reason="; ".join(row.notes), value=f"{row.ts.isoformat()} {row.bank} {row.to_account} {row.amount:,}원", evidence=list(row.evidence))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", type=Path, default=ROOT / "data" / "synthetic" / "case01", help="사건 디렉터리 (raw/ 포함)")
    ap.add_argument("--out", type=Path, default=None, help="출력 디렉터리 (기본 out/<case name>)")
    ap.add_argument("--victim", default=None, help="피해자 이름 (기본: case.json 의 victim)")
    args = ap.parse_args(argv)
    out = args.out or (ROOT / "out" / args.case.name)
    run(args.case, out, args.victim)
    return 0


if __name__ == "__main__":
    sys.exit(main())
