"""캡처 이미지 OCR (3단계).

- TesseractOCR: 로컬에 설치된 tesseract 실행 파일을 subprocess 로 부른다. 네트워크 없음.
- FakeOCR: 테스트용. 파일명별로 미리 정한 줄 목록을 돌려준다.
- 엔진이 없으면 OCR 을 하지 않고, 호출하는 쪽이 needs_review 로 뺀다. 추측하지 않는다.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Protocol


class OCRError(RuntimeError):
    pass


class OCREngine(Protocol):
    name: str

    def recognize(self, path: Path) -> list[str]:
        """이미지에서 읽은 텍스트를 줄 단위로 돌려준다(빈 줄 제거 전)."""
        ...


class TesseractOCR:
    name = "tesseract"

    def __init__(self, *, lang: str = "kor+eng", psm: int = 6, binary: str = "tesseract", timeout: float = 120.0):
        self.lang = lang
        self.psm = psm
        self.binary = binary
        self.timeout = timeout

    def is_available(self) -> bool:
        if shutil.which(self.binary) is None:
            return False
        try:
            out = subprocess.run([self.binary, "--list-langs"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return False
        langs = {l.strip() for l in (out.stdout + out.stderr).splitlines()}
        return all(part in langs for part in self.lang.split("+"))

    def recognize(self, path: Path) -> list[str]:
        cmd = [self.binary, str(path), "stdout", "-l", self.lang, "--psm", str(self.psm)]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, check=True)
        except (OSError, subprocess.SubprocessError) as e:
            raise OCRError(f"tesseract 실행 실패 ({path.name}): {e}") from e
        return out.stdout.splitlines()


class FakeOCR:
    name = "fake"

    def __init__(self, texts: dict[str, list[str]] | None = None):
        self.texts = texts or {}
        self.calls: list[str] = []

    def recognize(self, path: Path) -> list[str]:
        self.calls.append(path.name)
        if path.name not in self.texts:
            raise OCRError(f"FakeOCR 에 {path.name} 응답이 없습니다")
        return list(self.texts[path.name])
