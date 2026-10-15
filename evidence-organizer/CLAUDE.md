# 사이버사기 증거 정리기 (evidence-organizer)

피해자가 제출한 날것 자료(메신저 대화 내보내기, 이체내역 CSV, 캡처 이미지)를 읽어 타임라인·추출물·범죄일람표·수사보고서 초안을 만드는 도구. 수사관이 손으로 옮겨 적는 구간을 없애는 게 목적.

## 절대 원칙
1. 원본은 수정하지 않는다. data/raw/는 읽기 전용. 산출물은 data/work/와 out/에만 쓴다. 원본을 처음 읽을 때 SHA-256을 out/manifest.json에 기록하고 매 실행마다 검증한다.
2. 근거 없는 출력은 없다. 추출값, 일람표 행, 보고서의 모든 문장은 {"src": 파일명, "line": 행번호} 근거를 가진다. 근거를 못 붙이는 문장은 출력하지 말고 needs_review로 뺀다.
3. 외부 API 호출 금지. 네트워크로 나가는 코드는 쓰지 않는다. LLM은 로컬(Ollama)만 쓰고, 2단계 전까지는 LLM을 아예 쓰지 않는다.
4. 실제 사건 데이터는 절대 넣지 않는다. 테스트는 scripts/gen_synthetic.py가 만든 합성 데이터로만.
5. AI는 제안, 확정은 사람. 모든 판정은 status: "confirmed" | "needs_review"를 가지며 기본값은 needs_review.

## 폴더 구조
src/eo/ (hashing.py, parsers/kakao.py, parsers/telegram.py, parsers/bank_csv.py, extract.py, timeline.py, ledger.py, report.py, evaluate.py, schema.py), scripts/ (gen_synthetic.py, run_all.py), data/ (raw, work, synthetic), out/, tests/

## 공통 스키마 (schema.py)
Event: ts(datetime, KST tz-aware), kind("message"|"transfer"|"screenshot"), actor, text, src, line, extracted(dict: accounts, phones, urls, wallets, amounts)
LedgerRow: ts, victim, to_account, bank, amount(int), evidence(list of {src,line}), status

## 파서 스펙
- 카카오톡 모바일(Android) 내보내기: "2026년 10월 15일 오후 3:17, 홍길동 : 메시지" 형식, 날짜 구분선 처리. PC 내보내기: "[홍길동] [오후 3:17] 메시지" + 날짜 헤더. 첫 20줄로 자동 감지. 여러 줄 메시지는 다음 타임스탬프까지 이어 붙이고 line은 첫 줄 번호.
- 이체내역 CSV: 은행별 컬럼 매핑 테이블. 모르는 은행이면 추측하지 말고 실패.
- 추출 정규식은 extract.py에 모으고 패턴마다 테스트. 한국 계좌번호는 하이픈 유무·은행별 자릿수 변형 허용.

## 단계
- 1단계(LLM 없음): hashing → parsers → extract → timeline → ledger → report(템플릿) → evaluate. 전부 결정적 코드.
- 2단계(로컬 LLM): Ollama로 참여자 역할 분류, 보고서 서술 생성. 인용 없는 문장은 버린다.
- 3단계: 사건 간 계좌·번호 교차, 캡처 OCR.

## 코딩 규칙
Python 3.11+, 타입 힌트, pytest. 의존성 최소(표준 라이브러리 + pandas). 파서는 Event를 yield하는 제너레이터. 로그는 out/run.log, 실행 시 git hash를 manifest.json에 기록. 한국어 주석, 영어 변수명. 애매하면 추측하지 말고 needs_review로 빼거나 질문.
