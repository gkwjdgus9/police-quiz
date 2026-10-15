"""전체 파이프라인 실행기.

  1단계: hashing → parsers → extract → timeline → ledger
  2단계: roles(참여자 역할) → narrative(사건 경위)   ※ 로컬 Ollama 가 있을 때만
  3단계: 캡처 이미지 OCR(로컬 tesseract 가 있을 때만), 사건 간 교차는 scripts/cross_cases.py
  마무리: report → evaluate

사용:
  python scripts/run_all.py --case data/synthetic/case01 [--out out/case01] [--victim 이름]
                            [--llm auto|ollama|none] [--model qwen2.5:7b] [--ollama-url http://127.0.0.1:11434] [--llm-timeout 300]
                            [--ocr auto|tesseract|none] [--work data/work]
  --llm auto(기본): 127.0.0.1 의 Ollama 에 모델이 있으면 2단계를 돌리고, 없으면 건너뛰고 로그에 남긴다.

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
from eo.llm import DEFAULT_MODEL, DEFAULT_OLLAMA_URL, CallLog, LLMClient, LLMError, OllamaClient  # noqa: E402
from eo.narrative import generate_narrative  # noqa: E402
from eo.ocr import OCREngine, TesseractOCR  # noqa: E402
from eo.parsers.bank_csv import parse_bank_csv  # noqa: E402
from eo.parsers.kakao import parse_kakao  # noqa: E402
from eo.parsers.screenshot import IMAGE_SUFFIXES, parse_screenshot  # noqa: E402
from eo.report import build_report, write_report  # noqa: E402
from eo.roles import classify_roles  # noqa: E402
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


def make_ocr(mode: str, log: logging.Logger) -> OCREngine | None:
    if mode == "none":
        log.info("OCR 미사용(--ocr none)")
        return None
    engine = TesseractOCR()
    if engine.is_available():
        log.info("로컬 OCR 사용: tesseract (%s)", engine.lang)
        return engine
    if mode == "tesseract":
        raise SystemExit("tesseract 가 없거나 kor 언어 데이터가 없습니다. (apt install tesseract-ocr tesseract-ocr-kor 등)")
    log.info("tesseract 없음 → 캡처는 해시만 기록하고 OCR 은 needs_review")
    return None


def parse_raw(raw_dir: Path, victim: str, log: logging.Logger, *, ocr: OCREngine | None = None, ocr_work_dir: Path | None = None) -> list[Event]:
    events: list[Event] = []
    for path in sorted(p for p in raw_dir.rglob("*") if p.is_file() and not p.name.startswith(".")):
        suffix = path.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            evs = list(parse_screenshot(path, ocr=ocr, work_dir=ocr_work_dir))
            n_text = sum(1 for e in evs if e.line > 0)
            log.info("캡처 %s → OCR 줄 %d건 (%s)", path.name, n_text, evs[0].meta.get("ocr"))
        elif suffix == ".txt":
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


def make_llm(mode: str, *, model: str, url: str, out_dir: Path, log: logging.Logger, timeout: float = 300.0) -> LLMClient | None:
    """--llm 옵션에 따라 클라이언트를 만든다. auto 는 Ollama 가 응답할 때만."""
    if mode == "none":
        log.info("LLM 미사용(--llm none): 2단계 건너뜀")
        return None
    try:
        client = OllamaClient(url=url, model=model, timeout=timeout, log=CallLog(path=out_dir / "llm_log.jsonl"))
    except LLMError as e:
        raise SystemExit(f"LLM 설정 오류: {e}") from e
    if client.is_available():
        log.info("로컬 LLM 사용: %s @ %s (model=%s)", client.name, url, model)
        return client
    if mode == "ollama":
        raise SystemExit(f"Ollama 에 연결할 수 없거나 모델 {model} 이 없습니다: {url}")
    log.info("Ollama 없음(%s, model=%s) → 2단계 건너뜀, 역할은 전부 unknown/needs_review", url, model)
    return None


def run(case_dir: Path, out_dir: Path, victim: str | None = None, *, llm: LLMClient | None = None, llm_mode: str = "none",
        model: str = DEFAULT_MODEL, ollama_url: str = DEFAULT_OLLAMA_URL, llm_timeout: float = 300.0,
        ocr: OCREngine | None = None, ocr_mode: str = "none", work_dir: Path | None = None) -> dict:
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

    # 2~4. 파싱 → 추출 → 타임라인 (캡처는 3단계 OCR)
    if ocr is None:
        ocr = make_ocr(ocr_mode, log)
    ocr_work_dir = (work_dir or (ROOT / "data" / "work")) / case_dir.name / "ocr"
    events = parse_raw(raw_dir, victim, log, ocr=ocr, ocr_work_dir=ocr_work_dir)
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

    # 6~7. 2단계: 역할 분류, 사건 경위 (로컬 LLM)
    if llm is None:
        llm = make_llm(llm_mode, model=model, url=ollama_url, out_dir=out_dir, log=log, timeout=llm_timeout)
    roles = classify_roles(timeline, victim=victim, llm=llm)
    write_json([r.to_dict() for r in roles], out_dir / "roles.json")
    log.info("역할 판정: %s", {r.actor: r.role for r in roles})
    narrative, narrative_dropped = generate_narrative(timeline, ledger, roles, victim=victim, llm=llm)
    write_json({"kept": [s.to_dict() for s in narrative], "dropped": [d.to_dict() for d in narrative_dropped]}, out_dir / "narrative.json")
    if llm is not None:
        log.info("사건 경위: 통과 %d문장, 버림 %d문장", len(narrative), len(narrative_dropped))

    # 8. 보고서
    md, dropped = build_report(case_name=case_dir.name, events=timeline, ledger=ledger, reviews=reviews, extracted=extracted, generated_at=now, git_hash=commit,
                               roles=roles, narrative=narrative, llm_name=f"{llm.name}/{getattr(llm, 'model', '')}" if llm else "")
    write_report(md, out_dir / "report.md")
    all_reviews = [*reviews, *dropped, *narrative_dropped]
    for e in timeline:
        if e.kind == "screenshot" and e.line == 0:
            why = {"none": "OCR 엔진 없음", "error": f"OCR 실패: {e.meta.get('error', '')}"}.get(str(e.meta.get("ocr")), "OCR 결과 비어 있음")
            all_reviews.append(ReviewItem(category="screenshot_no_ocr", reason=f"{why} — 캡처 내용은 사람이 확인", value=e.src))
    for r in roles:
        if r.status != "confirmed":
            all_reviews.append(ReviewItem(category="role", reason=f"{r.role} ({r.confidence:.0%}) {r.reason}", value=r.actor, evidence=list(r.evidence)))
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
        ocr_sizes = {p.name[:-4]: len(p.read_text(encoding="utf-8").splitlines()) for p in ocr_work_dir.glob("*.txt")} if ocr_work_dir.exists() else {}
        result = evaluate_all(labels=labels, extracted=extracted, ledger=[r.to_dict() for r in ledger], report_md=md, raw_dir=raw_dir,
                              extra_sizes=ocr_sizes, ocr_ran=ocr is not None,
                              roles=[r.to_dict() for r in roles],
                              narrative=[s.to_dict() for s in narrative] if llm else None,
                              narrative_dropped=[d.to_dict() for d in narrative_dropped])
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
    ap.add_argument("--llm", choices=["auto", "ollama", "none"], default="auto", help="2단계 로컬 LLM 사용 여부 (기본 auto)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama 모델 이름 (기본 {DEFAULT_MODEL})")
    ap.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL, help="Ollama 주소. 루프백만 허용")
    ap.add_argument("--llm-timeout", type=float, default=300.0, help="LLM 호출 1회 제한 시간(초). 느린 CPU 면 늘린다 (기본 300)")
    ap.add_argument("--ocr", choices=["auto", "tesseract", "none"], default="auto", help="캡처 이미지 OCR (기본 auto: tesseract 있으면 사용)")
    ap.add_argument("--work", type=Path, default=ROOT / "data" / "work", help="OCR 결과 텍스트 등 중간 산출물 폴더")
    args = ap.parse_args(argv)
    out = args.out or (ROOT / "out" / args.case.name)
    run(args.case, out, args.victim, llm_mode=args.llm, model=args.model, ollama_url=args.ollama_url, llm_timeout=args.llm_timeout,
        ocr_mode=args.ocr, work_dir=args.work)
    return 0


if __name__ == "__main__":
    sys.exit(main())
