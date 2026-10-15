# evidence-organizer (1·2단계)

사이버사기 피해자 제출 자료(카카오톡 내보내기, 은행 이체내역 CSV)에서 타임라인·추출물·범죄일람표·수사보고서 초안을 만든다.
설계 원칙과 구조는 [CLAUDE.md](CLAUDE.md) 참고. 1단계는 LLM 없이 결정적 코드만 쓰고, 2단계는 localhost 의 Ollama 로 참여자 역할 분류와 사건 경위 서술을 '제안'한다.

## 실행

```bash
pip install pytest                      # 의존성은 표준 라이브러리뿐
python scripts/gen_synthetic.py         # 합성 사건 data/synthetic/case01 생성(이미 커밋돼 있음)
python scripts/run_all.py --case data/synthetic/case01   # out/case01/ 에 산출물, 평가표는 stdout
python -m pytest
```

2단계(로컬 LLM)는 `--llm auto`(기본)에서 127.0.0.1 의 Ollama 에 모델이 있을 때만 돌고, 없으면 건너뛰고 run.log 에 남긴다.

```bash
ollama pull qwen2.5:7b                                    # 한국어 되는 소형 모델이면 무엇이든
python scripts/check_llm.py --model qwen2.5:7b            # 연결·모델·속도 점검, 예상 소요 시간 출력
python scripts/run_all.py --case data/synthetic/case01 --llm ollama --model qwen2.5:7b
```

사건 하나당 LLM 호출은 6회(역할 5 + 경위 1)뿐이라 GPU 없이 CPU 로도 된다. 메모리가 작으면 모델을 줄인다: 8GB 는 `qwen2.5:1.5b`, 16GB 는 `qwen2.5:3b`. CPU 가 느려 끊기면 `--llm-timeout 600`.

루프백이 아닌 주소는 `--ollama-url` 로 줘도 거부한다. 프롬프트와 응답은 전부 `out/<case>/llm_log.jsonl` 에 남는다.

## 산출물 (out/<case>/)

| 파일 | 내용 |
|---|---|
| manifest.json | raw 파일 SHA-256, 실행 시각·git hash. 재실행 시 해시가 다르면 중단 |
| timeline.jsonl | 대화·이체 Event 를 시각순으로 병합 (extracted 포함) |
| extracted.json | 대화에서 추출한 계좌·전화·URL·지갑주소·금액과 근거 행 |
| ledger.json | 범죄일람표. 계좌+명시 금액이 대화와 일치하면 confirmed, 아니면 needs_review |
| report.md | 보고서 초안. 모든 문장·표 행에 `[파일:행]` 각주 |
| needs_review.json | 해석 보류 금액, needs_review 일람표 행, 근거 없어 제외된 문장 |
| roles.json | 참여자 역할 판정(2단계). 피해자만 confirmed, 나머지는 LLM 제안 + 근거 행, needs_review |
| narrative.json | 사건 경위 문장(2단계). 통과 문장과 버린 문장·사유 |
| llm_log.jsonl | LLM 프롬프트·응답 원문(2단계) |
| evaluate.md / .json | labels.json 대비 재현율·정밀도, 보고서 근거 없는 비율, 역할 정확도, 경위 통과 비율 |
| run.log | 실행 로그 |

## 판정 규칙 (1단계)

- 금액: `3,000,000원` 같은 명시 표기와 `500만원`, `2천만원`, `1억 2천만 원` 같은 단위 표기를 모두 정수로 환산한다(억=10^8, 만=10^4, 천=10^3). `3천`처럼 원·만 단위가 없어 모호한 표기만 needs_review 로 보류한다.
- 일람표 confirmed: 이체의 상대 계좌가 대화에 등장하고, 같은 금액이 대화에 등장할 때. 둘 중 하나라도 없으면 needs_review.
- 이 규칙은 무관한 참여자가 자기 계좌와 금액을 올린 경우(case01 의 모임 회비)도 confirmed 로 잡는다. 역할 분류는 2단계(로컬 LLM) 몫이고, 1단계에서는 수사관이 표를 보고 제외한다. labels.json 의 `known_false_positives` 에 적어 두었다.

## 2단계 LLM 출력의 검증 규칙

- 역할: 참여자별 서류철(통계 + 번호 붙은 표본 메시지)만 보여 주고, 표본에 있는 행 번호만 근거로 인정한다. 근거가 없으면 unknown. 피해자는 사건 정보로 고정.
- 사건 경위: confirmed 일람표의 근거 행과 역할 근거 행만 '자료 묶음'으로 준다. 문장마다 (1) 인용이 자료 묶음 안에 있고 (2) 금액·계좌·전화·긴 숫자열이 인용 행에 실제로 있고 (3) 참여자 이름이 인용 행의 발신자이거나 본문에 있어야 통과한다. 하나라도 어기면 needs_review 로 뺀다.
- 통과한 문장도 보고서에서 "검토 필요"로 표시된다. 확정은 사람이 한다.

## 확인이 필요한 것

- 은행 CSV 컬럼 매핑(`parsers/bank_csv.py` 의 `BANKS`)은 합성 데이터용 샘플이다. 실제 내보내기 헤더를 확인한 뒤 매핑을 추가·수정한다. 모르는 헤더를 만나면 헤더 전체를 에러 메시지에 출력한다.
