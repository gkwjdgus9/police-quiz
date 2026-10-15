# evidence-organizer (1단계)

사이버사기 피해자 제출 자료(카카오톡 내보내기, 은행 이체내역 CSV)에서 타임라인·추출물·범죄일람표·수사보고서 초안을 만든다.
설계 원칙과 구조는 [CLAUDE.md](CLAUDE.md) 참고. 1단계는 LLM 없이 결정적 코드만 쓴다.

## 실행

```bash
pip install pytest                      # 의존성은 표준 라이브러리뿐
python scripts/gen_synthetic.py         # 합성 사건 data/synthetic/case01 생성(이미 커밋돼 있음)
python scripts/run_all.py --case data/synthetic/case01   # out/case01/ 에 산출물, 평가표는 stdout
python -m pytest
```

## 산출물 (out/<case>/)

| 파일 | 내용 |
|---|---|
| manifest.json | raw 파일 SHA-256, 실행 시각·git hash. 재실행 시 해시가 다르면 중단 |
| timeline.jsonl | 대화·이체 Event 를 시각순으로 병합 (extracted 포함) |
| extracted.json | 대화에서 추출한 계좌·전화·URL·지갑주소·금액과 근거 행 |
| ledger.json | 범죄일람표. 계좌+명시 금액이 대화와 일치하면 confirmed, 아니면 needs_review |
| report.md | 보고서 초안. 모든 문장·표 행에 `[파일:행]` 각주 |
| needs_review.json | 해석 보류 금액, needs_review 일람표 행, 근거 없어 제외된 문장 |
| evaluate.md / .json | labels.json 대비 재현율·정밀도, 보고서 근거 없는 비율 |
| run.log | 실행 로그 |

## 아직 정하지 않은 것 (needs_review 로 빠짐)

- `500만원`, `2천만원` 같은 한국어 단위 금액은 해석하지 않고 보류한다. 규칙이 정해지면 `extract.py` 의 `extract_amounts` 만 바꾸면 된다.
- 은행 CSV 컬럼 매핑(`parsers/bank_csv.py` 의 `BANKS`)은 합성 데이터용 샘플이다. 실제 내보내기 형식 확인 후 수정한다.
