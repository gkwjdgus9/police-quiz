"""로컬 앱: 목록, 새 사건 업로드, 실행, 결과 화면이 돌아가는지 (실제 HTTP 로)."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
import urllib.request
from urllib.parse import quote
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from eo.mdhtml import md_to_html

ROOT = Path(__file__).resolve().parents[1]


def test_md_to_html_basic() -> None:
    md = "# 제목\n<!-- 주석 -->\n- 문장 `코드` [a.txt:3]\n\n| h1 | h2 |\n|---|---|\n| 1 | [b.csv:2] |\n\n본문 <b>\n"
    out = md_to_html(md)
    assert "<h3>제목</h3>" in out and "주석" not in out
    assert '<li>문장 <code>코드</code> <span class="fn">a.txt:3</span></li>' in out
    assert "<th>h1</th>" in out and '<td><span class="fn">b.csv:2</span></td>' in out
    assert "<p>본문 &lt;b&gt;</p>" in out


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("eo_app", ROOT / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["eo_app"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    # 저장소를 더럽히지 않게 경로를 임시 폴더로 돌린다
    mod.DATA_RAW = tmp_path / "raw"
    mod.OUT = tmp_path / "out"
    mod.WORK = tmp_path / "work"
    mod.JOBS.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), mod.Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield mod, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _get(url: str) -> tuple[int, str]:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(url, timeout=10) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def _post_multipart(url: str, fields: dict[str, str], files: list[tuple[str, bytes]]) -> tuple[int, str]:
    boundary = "----eoTestBoundary"
    body = b""
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8")
    for name, data in files:
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode("utf-8") + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def test_app_flow(app) -> None:
    mod, base = app
    code, body = _get(base + "/")
    assert code == 200 and "새 사건 만들기" in body

    syn = ROOT / "data" / "synthetic" / "case01" / "raw"
    files = [("kakao_mobile.txt", (syn / "kakao_mobile.txt").read_bytes()), ("transfers_kb.csv", (syn / "transfers_kb.csv").read_bytes())]
    code, body = _post_multipart(base + "/new", {"case": "테스트사건", "victim": "이수진"}, files)
    assert code == 303, body
    assert (mod.DATA_RAW / "테스트사건" / "raw" / "kakao_mobile.txt").exists()
    assert json.loads((mod.DATA_RAW / "테스트사건" / "case.json").read_text(encoding="utf-8"))["victim"] == "이수진"

    # 잘못된 입력은 400
    assert _post_multipart(base + "/new", {"case": "bad name!", "victim": "x"}, files)[0] == 400
    assert _post_multipart(base + "/new", {"case": "ok", "victim": "x"}, [("evil.exe", b"x")])[0] == 400

    code, _ = _get(base + "/run?case=" + quote("테스트사건"))
    assert code == 303
    for _ in range(100):
        if mod.JOBS.get("테스트사건", {}).get("status") in ("done", "error"):
            break
        time.sleep(0.1)
    assert mod.JOBS["테스트사건"]["status"] == "done", mod.JOBS["테스트사건"]
    code, body = _get(base + "/result?case=" + quote("테스트사건"))
    assert code == 200 and "범죄일람표" in body and "수사보고서 초안" in body and "3521234567893" in body
    code, body = _get(base + "/file?case=" + quote("테스트사건") + "&name=ledger.json")
    assert code == 200 and json.loads(body)
    assert _get(base + "/file?case=" + quote("테스트사건") + "&name=../../app.py")[0] == 404
    assert _get(base + "/run?case=" + quote("없는사건"))[0] == 404
