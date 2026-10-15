"""로컬 Ollama 점검. 2단계를 돌리기 전에 노트북에서 되는지 본다.

  python scripts/check_llm.py [--model qwen2.5:7b] [--ollama-url http://127.0.0.1:11434]

확인 항목: 연결 → 설치된 모델 목록 → 지정 모델로 짧은 한국어 JSON 생성 한 번 → 소요 시간·초당 토큰.
네트워크는 루프백만 쓴다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eo.llm import DEFAULT_MODEL, DEFAULT_OLLAMA_URL, LLMError, OllamaClient  # noqa: E402

# RAM 별 권장 모델. 한국어가 되는 소형 모델 기준이며, 품질은 위로 갈수록 좋다.
SUGGESTIONS = [
    ("8GB", "qwen2.5:1.5b 또는 gemma3:1b"),
    ("16GB", "qwen2.5:3b 또는 gemma3:4b"),
    ("16GB+ (GPU 없음)", "qwen2.5:7b (느리지만 됨)"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    args = ap.parse_args()

    try:
        client = OllamaClient(url=args.ollama_url, model=args.model, timeout=600)
    except LLMError as e:
        print(f"✗ {e}")
        return 2

    # 1. 연결
    try:
        with urllib.request.urlopen(f"{client.url}/api/tags", timeout=3) as r:
            tags = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"✗ Ollama 에 연결 못 함: {client.url} ({e})")
        print("  → Ollama 를 설치하고 실행한 뒤 다시 시도. https://ollama.com/download")
        return 1
    names = [m.get("name", "") for m in tags.get("models", [])]
    print(f"✓ Ollama 연결됨: {client.url}")
    print(f"  설치된 모델: {', '.join(names) if names else '(없음)'}")

    # 2. 모델
    if not client.is_available():
        print(f"✗ 모델 {args.model} 이 없음")
        print(f"  → ollama pull {args.model}")
        print("  노트북 RAM 에 따른 권장:")
        for ram, m in SUGGESTIONS:
            print(f"    {ram:18s} {m}")
        return 1
    print(f"✓ 모델 있음: {args.model}")

    # 3. 짧은 생성 (JSON 모드, 역할 분류와 같은 형식)
    system = '수사 보조다. 반드시 JSON 으로만 답한다: {"role": "<operator|assistant|unrelated|unknown>", "reason": "<한 문장>"}'
    prompt = "참여자 '김실장'의 표본 메시지: (line 12) 입금계좌는 농협 352-1234-5678-93 입니다. 입금 후 캡처 보내주세요. 역할은?"
    t0 = time.perf_counter()
    try:
        obj = client.complete_json(system=system, prompt=prompt, task="check")
    except LLMError as e:
        print(f"✗ 생성 실패: {e}")
        return 1
    dt = time.perf_counter() - t0
    resp = client.log.entries[-1]["response"]
    approx_tokens = max(1, len(resp) // 2)  # 한국어 대략 2자=1토큰으로 어림
    print(f"✓ 생성 성공: {dt:.1f}초, 응답 {len(resp)}자 (약 {approx_tokens / dt:.1f} 토큰/초)")
    print(f"  응답: {json.dumps(obj, ensure_ascii=False)[:200]}")
    est = dt * 6 * 4  # 호출 6회, 실제 프롬프트는 점검용의 4배쯤
    print(f"  case01 2단계 예상 소요: 약 {est / 60:.0f}분 이내")
    if dt > 60:
        print("  → 느리다면 더 작은 모델을 쓰거나 run_all 에 --llm-timeout 600 을 준다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
