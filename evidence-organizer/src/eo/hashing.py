"""원본 무결성 관리.

- 원본(raw) 파일을 처음 읽을 때 SHA-256 을 out/manifest.json 에 기록한다.
- 이후 실행마다 같은 파일의 해시를 다시 계산해 기록과 비교한다. 다르면 IntegrityError 로 즉시 중단한다.
- 매 실행의 시각과 git hash 를 runs 목록에 남긴다.
- 이 모듈은 raw 디렉터리를 읽기만 하고 절대 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from eo.schema import KST

MANIFEST_VERSION = 1
CHUNK = 1 << 20


class IntegrityError(RuntimeError):
    """원본 파일이 기록된 해시와 다를 때."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def git_hash(repo_dir: Path | None = None) -> str:
    """현재 커밋 해시. git 이 없거나 저장소가 아니면 'unknown'. (로컬 명령, 네트워크 없음)"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir or Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def list_raw_files(raw_dir: Path) -> list[Path]:
    """raw 디렉터리의 일반 파일 목록(숨김 파일 제외, 경로순 정렬)."""
    return sorted(p for p in raw_dir.rglob("*") if p.is_file() and not p.name.startswith("."))


@dataclass
class Manifest:
    raw_dir: str
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    runs: list[dict[str, Any]] = field(default_factory=list)
    version: int = MANIFEST_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "raw_dir": self.raw_dir, "files": self.files, "runs": self.runs}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Manifest":
        return cls(raw_dir=d["raw_dir"], files=dict(d.get("files", {})), runs=list(d.get("runs", [])), version=int(d.get("version", 1)))


def load_manifest(path: Path) -> Manifest | None:
    if not path.exists():
        return None
    return Manifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_manifest(manifest: Manifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_or_verify_manifest(raw_dir: Path, manifest_path: Path, *, repo_dir: Path | None = None, now: datetime | None = None) -> Manifest:
    """raw 파일 해시를 기록(최초)하거나 검증(재실행)하고, 실행 기록을 덧붙여 저장한다.

    - 기록된 파일의 해시가 다르면 IntegrityError.
    - 기록된 파일이 사라져도 IntegrityError (원본이 바뀐 것이므로).
    - 새 파일은 기록에 추가한다.
    """
    raw_dir = raw_dir.resolve()
    if not raw_dir.is_dir():
        raise FileNotFoundError(f"raw 디렉터리가 없습니다: {raw_dir}")
    now = now or datetime.now(KST)
    manifest = load_manifest(manifest_path) or Manifest(raw_dir=str(raw_dir))

    current = {p.relative_to(raw_dir).as_posix(): p for p in list_raw_files(raw_dir)}
    mismatches: list[str] = []
    for rel, rec in manifest.files.items():
        p = current.get(rel)
        if p is None:
            mismatches.append(f"{rel}: 기록된 원본이 없음")
            continue
        digest = sha256_file(p)
        if digest != rec["sha256"]:
            mismatches.append(f"{rel}: 기록 {rec['sha256'][:12]}… ≠ 현재 {digest[:12]}…")
    if mismatches:
        raise IntegrityError("원본 무결성 검증 실패:\n  " + "\n  ".join(mismatches))

    added: list[str] = []
    for rel, p in current.items():
        if rel not in manifest.files:
            manifest.files[rel] = {"sha256": sha256_file(p), "size": p.stat().st_size, "first_seen": now.isoformat()}
            added.append(rel)

    manifest.runs.append({"ts": now.isoformat(), "git_hash": git_hash(repo_dir), "verified": sorted(set(current) - set(added)), "added": added})
    save_manifest(manifest, manifest_path)
    return manifest
