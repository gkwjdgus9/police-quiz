"""hashing: 최초 기록, 재실행 검증, 변조·삭제 감지."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from eo.hashing import IntegrityError, build_or_verify_manifest, sha256_file


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    d = tmp_path / "raw"
    d.mkdir()
    (d / "a.txt").write_text("hello\n", encoding="utf-8")
    (d / "sub").mkdir()
    (d / "sub" / "b.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    return d


def test_sha256_file(tmp_path: Path) -> None:
    p = tmp_path / "f.bin"
    p.write_bytes(b"abc")
    assert sha256_file(p) == hashlib.sha256(b"abc").hexdigest()


def test_first_run_records_all_files(raw: Path, tmp_path: Path) -> None:
    mp = tmp_path / "out" / "manifest.json"
    m = build_or_verify_manifest(raw, mp)
    assert set(m.files) == {"a.txt", "sub/b.csv"}
    assert m.files["a.txt"]["sha256"] == hashlib.sha256(b"hello\n").hexdigest()
    assert len(m.runs) == 1 and "git_hash" in m.runs[0]
    saved = json.loads(mp.read_text(encoding="utf-8"))
    assert saved["files"] == m.files


def test_second_run_verifies_and_appends_run(raw: Path, tmp_path: Path) -> None:
    mp = tmp_path / "out" / "manifest.json"
    build_or_verify_manifest(raw, mp)
    m = build_or_verify_manifest(raw, mp)
    assert len(m.runs) == 2
    assert m.runs[1]["verified"] == ["a.txt", "sub/b.csv"]
    assert m.runs[1]["added"] == []


def test_modified_file_is_detected(raw: Path, tmp_path: Path) -> None:
    mp = tmp_path / "out" / "manifest.json"
    build_or_verify_manifest(raw, mp)
    (raw / "a.txt").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(IntegrityError, match="a.txt"):
        build_or_verify_manifest(raw, mp)


def test_deleted_file_is_detected(raw: Path, tmp_path: Path) -> None:
    mp = tmp_path / "out" / "manifest.json"
    build_or_verify_manifest(raw, mp)
    (raw / "sub" / "b.csv").unlink()
    with pytest.raises(IntegrityError, match="b.csv"):
        build_or_verify_manifest(raw, mp)


def test_new_file_is_added(raw: Path, tmp_path: Path) -> None:
    mp = tmp_path / "out" / "manifest.json"
    build_or_verify_manifest(raw, mp)
    (raw / "c.txt").write_text("new\n", encoding="utf-8")
    m = build_or_verify_manifest(raw, mp)
    assert "c.txt" in m.files
    assert m.runs[1]["added"] == ["c.txt"]


def test_raw_dir_untouched(raw: Path, tmp_path: Path) -> None:
    before = {p: p.read_bytes() for p in raw.rglob("*") if p.is_file()}
    build_or_verify_manifest(raw, tmp_path / "out" / "manifest.json")
    after = {p: p.read_bytes() for p in raw.rglob("*") if p.is_file()}
    assert before == after
