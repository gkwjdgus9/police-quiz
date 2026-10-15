"""증거 정리기 로컬 앱.

더블클릭(실행.bat / 실행.command)하거나 `python app.py` 로 띄우면 브라우저가 열린다.
표준 라이브러리만 쓰고, 127.0.0.1 에서만 듣는다. 밖으로 나가는 요청은 없다.

할 수 있는 것
  - 새 사건 만들기: 사건 이름, 피해자 이름, 원본 파일(카카오톡 txt, 은행 CSV, 캡처 이미지) 업로드 → data/raw/<사건>/raw/
  - 실행: 1단계(항상) + 2단계(로컬 Ollama 있을 때) + 3단계 OCR(로컬 tesseract 있을 때)
  - 결과 보기: 평가표, 범죄일람표, 보고서 초안, 검토 필요 목록, 산출물 파일
  - 사건 간 교차 조회
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import threading
import traceback
import webbrowser
import zipfile
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

ROOT = Path(__file__).resolve().parent
# 한 파일(.pyz)로 묶여 실행 중이면 ROOT 의 상위 어딘가가 '파일'이다. 그 파일 옆의 <이름>-data/ 를 쓰기 공간으로 쓴다.
ARCHIVE: Path | None = next((p for p in [ROOT, *ROOT.parents] if p.is_file()), None)
HOME = ARCHIVE.parent / f"{ARCHIVE.stem}-data" if ARCHIVE else ROOT
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_all  # noqa: E402  (scripts/run_all.py)
import cross_cases  # noqa: E402

from eo.mdhtml import md_to_html  # noqa: E402

DATA_RAW = HOME / "data" / "raw"
DATA_SYN = HOME / "data" / "synthetic"
OUT = HOME / "out"
WORK = HOME / "data" / "work"


def unpack_bundled_synthetic() -> None:
    """.pyz 안에 묶인 합성 사건을 쓰기 공간에 한 번 풀어 둔다 (이미 있으면 건드리지 않는다)."""
    if ARCHIVE is None:
        return
    with zipfile.ZipFile(ARCHIVE) as z:
        for info in z.infolist():
            if not info.filename.startswith("data/synthetic/") or info.is_dir():
                continue
            target = HOME / info.filename
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))
ALLOWED_SUFFIXES = {".txt", ".csv", ".png", ".jpg", ".jpeg"}
CASE_NAME = re.compile(r"^[A-Za-z0-9가-힣_-]{1,40}$")

# 실행 상태 (사건 이름 → {"status": running|done|error, "error": str})
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()

E = html.escape

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root{{--bg:#f6f7f4;--fg:#1d2420;--muted:#5f6b64;--line:#d6dbd4;--panel:#fff;--accent:#0f6e62;--accent-soft:#dcefe9;--ok:#1c7a3e;--ok-bg:#dff3e4;--warn:#9a5b00;--warn-bg:#fdf0d5;--bad:#9f2c2c;--bad-bg:#f9e0e0}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151a18;--fg:#e6ebe7;--muted:#9aa69f;--line:#2d3632;--panel:#1d2421;--accent:#5fc2b1;--accent-soft:#1d3b36;--ok:#7bd49a;--ok-bg:#1c3a27;--warn:#f0c46b;--warn-bg:#3d2f12;--bad:#f09a9a;--bad-bg:#3f1e1e}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;padding:24px 16px 60px}}
main{{max-width:1040px;margin:0 auto;display:grid;gap:28px}}
h1{{font-size:1.5rem;margin:0}} h2{{font-size:1.1rem;margin:0 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}} h3{{font-size:1rem;margin:16px 0 6px}} h4{{font-size:.95rem;margin:14px 0 6px}}
.muted{{color:var(--muted);font-size:.86rem}}
.panel{{background:var(--panel);border:1px solid var(--line);padding:16px 18px}}
table{{border-collapse:collapse;width:100%;font-size:.86rem}} th,td{{padding:6px 10px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}} th{{color:var(--muted);font-weight:500;font-size:.76rem;white-space:nowrap}}
.scroll{{overflow-x:auto;border:1px solid var(--line);background:var(--panel)}}
code,.mono{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.85em}}
.fn{{display:inline-block;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.68rem;padding:1px 5px;border-radius:3px;background:var(--accent-soft);color:var(--accent);margin:0 1px;white-space:nowrap}}
.pill{{display:inline-block;font-size:.72rem;padding:1px 8px;border-radius:10px;white-space:nowrap}} .ok{{background:var(--ok-bg);color:var(--ok)}} .warn{{background:var(--warn-bg);color:var(--warn)}} .bad{{background:var(--bad-bg);color:var(--bad)}}
a{{color:var(--accent)}} a.btn,button{{display:inline-block;background:var(--accent);color:#fff;border:0;padding:7px 14px;border-radius:4px;font-size:.9rem;cursor:pointer;text-decoration:none}} a.btn.ghost,button.ghost{{background:transparent;color:var(--accent);border:1px solid var(--accent)}}
form label{{display:block;margin:8px 0 2px;font-size:.86rem;color:var(--muted)}} input[type=text]{{width:100%;max-width:360px;padding:6px 8px;border:1px solid var(--line);border-radius:4px;background:var(--bg);color:var(--fg)}}
ul.cases{{list-style:none;padding:0;margin:0;display:grid;gap:8px}} ul.cases li{{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)}}
pre{{background:var(--panel);border:1px solid var(--line);padding:10px 12px;overflow-x:auto;font-size:.8rem;margin:0;white-space:pre-wrap}}
.report ul{{padding-left:18px}} .report li{{margin:4px 0;font-size:.9rem}}
</style></head><body><main>
<header><div class="muted">사이버사기 증거 정리기 · 로컬 앱 (127.0.0.1, 외부 연결 없음)</div><h1>{title}</h1></header>
{body}
<footer class="muted">원본은 읽기만 한다. 모든 산출물은 out/ 과 data/work/ 에만 쓴다. 확정은 사람이 한다.</footer>
</main></body></html>"""


def page(title: str, body: str) -> bytes:
    return PAGE.format(title=E(title), body=body).encode("utf-8")


# ----------------------------------------------------------------------------
# 사건 목록
# ----------------------------------------------------------------------------
def list_cases() -> list[dict]:
    cases = []
    for root, kind in ((DATA_RAW, "실제"), (DATA_SYN, "합성")):
        if not root.exists():
            continue
        for d in sorted(p for p in root.iterdir() if p.is_dir() and (p / "raw").is_dir()):
            meta = {}
            if (d / "case.json").exists():
                try:
                    meta = json.loads((d / "case.json").read_text(encoding="utf-8"))
                except ValueError:
                    meta = {}
            files = [p.name for p in sorted((d / "raw").iterdir()) if p.is_file()]
            cases.append({"name": d.name, "dir": d, "kind": kind, "victim": meta.get("victim", ""), "files": files, "has_out": (OUT / d.name / "report.md").exists()})
    return cases


def case_dir(name: str) -> Path | None:
    if not CASE_NAME.match(name):
        return None
    for root in (DATA_RAW, DATA_SYN):
        if (root / name / "raw").is_dir():
            return root / name
    return None


def index_body() -> str:
    cases = list_cases()
    items = ""
    for c in cases:
        job = JOBS.get(c["name"], {})
        state = {"running": '<span class="pill warn">실행 중</span>', "error": '<span class="pill bad">오류</span>', "done": '<span class="pill ok">완료</span>'}.get(job.get("status"), "")
        files = ", ".join(c["files"][:5]) + (" …" if len(c["files"]) > 5 else "")
        items += (f'<li><b>{E(c["name"])}</b> <span class="muted">{c["kind"]} · 피해자 {E(c["victim"] or "-")} · {E(files)}</span> {state} '
                  f'<a class="btn" href="/run?case={quote(c["name"])}">실행</a> '
                  + (f'<a class="btn ghost" href="/result?case={quote(c["name"])}">결과 보기</a>' if c["has_out"] else "") + "</li>")
    if not items:
        items = '<li class="muted">사건이 없습니다. 아래에서 새 사건을 만드세요.</li>'
    tools = (
        '<div class="panel"><h2>도구</h2>'
        '<form method="post" action="/cross" style="display:inline"><button>사건 간 교차 조회 실행</button></form> '
        + ('<a class="btn ghost" href="/crossresult">교차 조회 결과 보기</a>' if (OUT / "crosscase" / "shared.md").exists() else "")
        + '<p class="muted">실행한 사건이 2건 이상 있어야 합니다. 로컬 Ollama(2단계)와 tesseract(3단계 OCR)는 있으면 자동으로 쓰고 없으면 건너뜁니다.</p></div>'
    )
    new = (
        '<div class="panel"><h2>새 사건 만들기</h2>'
        '<form method="post" action="/new" enctype="multipart/form-data">'
        '<label>사건 이름 (영문·숫자·한글·-_, 폴더 이름이 됩니다)</label><input type="text" name="case" required pattern="[A-Za-z0-9가-힣_-]{1,40}">'
        '<label>피해자 이름 (대화에 나오는 표기 그대로)</label><input type="text" name="victim" required>'
        '<label>원본 파일: 카카오톡 내보내기 .txt, 은행 이체내역 .csv, 캡처 .png/.jpg (여러 개 선택 가능)</label><input type="file" name="files" multiple required>'
        '<p><button>사건 만들기</button></p>'
        '<p class="muted">파일은 data/raw/&lt;사건&gt;/raw/ 에 복사만 되고 이후 절대 수정하지 않습니다. 처음 실행할 때 SHA-256 을 기록합니다.</p></form></div>'
    )
    return f'<div class="panel"><h2>사건</h2><ul class="cases">{items}</ul></div>{new}{tools}'


# ----------------------------------------------------------------------------
# 결과 화면
# ----------------------------------------------------------------------------
def result_body(name: str) -> str:
    out = OUT / name
    if not (out / "report.md").exists():
        return f'<div class="panel">아직 실행 결과가 없습니다. <a class="btn" href="/run?case={quote(name)}">실행</a></div>'
    parts = [f'<p><a href="/">← 사건 목록</a> · <a class="btn ghost" href="/run?case={quote(name)}">다시 실행</a></p>']
    ev_md = out / "evaluate.md"
    if ev_md.exists():
        parts.append(f'<div class="panel"><h2>평가 (labels.json 대비)</h2>{md_to_html(ev_md.read_text(encoding="utf-8"))}</div>')
    ledger = json.loads((out / "ledger.json").read_text(encoding="utf-8"))
    conf = [r for r in ledger if r["status"] == "confirmed"]
    rev = [r for r in ledger if r["status"] != "confirmed"]

    def rows(rs: list[dict], notes: bool) -> str:
        h = ""
        for i, r in enumerate(rs, 1):
            fns = "".join(f'<span class="fn">{E(e["src"])}:{e["line"]}</span>' for e in r["evidence"])
            n = f'<td class="muted">{E("; ".join(r["notes"]))}</td>' if notes else ""
            h += f'<tr><td>{i}</td><td class="mono">{E(r["ts"][:16].replace("T", " "))}</td><td>{E(r["bank"] or "-")}</td><td class="mono">{E(r["to_account"] or "-")}</td><td class="mono" style="text-align:right">{r["amount"]:,}</td>{n}<td>{fns}</td></tr>'
        return h

    parts.append(
        f'<div class="panel"><h2>범죄일람표 <span class="muted">confirmed {len(conf)}건 · 합계 {sum(r["amount"] for r in conf):,}원</span></h2>'
        f'<div class="scroll"><table><thead><tr><th>#</th><th>일시</th><th>은행</th><th>계좌(숫자만)</th><th>금액(원)</th><th>근거</th></tr></thead><tbody>{rows(conf, False)}</tbody></table></div>'
        f'<h3>확인 필요 이체 <span class="muted">{len(rev)}건</span></h3>'
        f'<div class="scroll"><table><thead><tr><th>#</th><th>일시</th><th>은행</th><th>계좌</th><th>금액(원)</th><th>사유</th><th>근거</th></tr></thead><tbody>{rows(rev, True)}</tbody></table></div></div>'
    )
    parts.append(f'<div class="panel report"><h2>수사보고서 초안 <span class="muted">report.md</span></h2>{md_to_html((out / "report.md").read_text(encoding="utf-8"))}</div>')
    reviews = json.loads((out / "needs_review.json").read_text(encoding="utf-8"))
    items = "".join(f'<li><span class="pill warn">{E(r["category"])}</span> <span class="mono">{E(r["value"])}</span> <span class="muted">{E(r["reason"])}</span> '
                    + "".join(f'<span class="fn">{E(e["src"])}:{e["line"]}</span>' for e in r.get("evidence", [])) + "</li>" for r in reviews)
    parts.append(f'<div class="panel"><h2>검토 필요 항목 <span class="muted">{len(reviews)}건</span></h2><ul>{items or "<li class=muted>없음</li>"}</ul></div>')
    files = "".join(f'<li><a href="/file?case={quote(name)}&name={quote(p.name)}">{E(p.name)}</a> <span class="muted">{p.stat().st_size:,} B</span></li>' for p in sorted(out.iterdir()) if p.is_file())
    parts.append(f'<div class="panel"><h2>산출물 파일 <span class="muted">out/{E(name)}/</span></h2><ul>{files}</ul></div>')
    return "".join(parts)


def status_body(name: str) -> str:
    job = JOBS.get(name, {})
    log = OUT / name / "run.log"
    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:] if log.exists() else []
    st = job.get("status", "unknown")
    if st == "running":
        head = '<meta http-equiv="refresh" content="2"><span class="pill warn">실행 중…</span> <span class="muted">2단계(LLM)는 수 분 걸릴 수 있습니다. 이 페이지는 2초마다 새로고침됩니다.</span>'
    elif st == "done":
        head = f'<span class="pill ok">완료</span> <a class="btn" href="/result?case={quote(name)}">결과 보기</a> <a href="/">사건 목록</a>'
    elif st == "error":
        head = f'<span class="pill bad">오류</span> <pre>{E(job.get("error", ""))}</pre><a href="/">사건 목록</a>'
    else:
        head = '<a href="/">사건 목록</a>'
    return f'<div class="panel"><h2>실행: {E(name)}</h2>{head}<h3>run.log</h3><pre>{E(chr(10).join(tail))}</pre></div>'


def start_job(name: str, cdir: Path) -> None:
    with JOBS_LOCK:
        if JOBS.get(name, {}).get("status") == "running":
            return
        JOBS[name] = {"status": "running"}

    def work() -> None:
        try:
            run_all.run(cdir, OUT / name, llm_mode="auto", ocr_mode="auto", work_dir=WORK)
            JOBS[name] = {"status": "done"}
        except BaseException as e:  # SystemExit 포함
            JOBS[name] = {"status": "error", "error": f"{e}\n{traceback.format_exc()[-1500:]}"}

    threading.Thread(target=work, daemon=True).start()


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # 콘솔 소음 줄이기
        pass

    def _send(self, body: bytes, ctype: str = "text/html; charset=utf-8", code: int = 200, download: str | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, to: str) -> None:
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def do_GET(self) -> None:
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        name = q.get("case", "")
        if u.path == "/":
            self._send(page("증거 정리기", index_body()))
        elif u.path == "/run":
            cdir = case_dir(name)
            if cdir is None:
                self._send(page("오류", '<div class="panel">사건을 찾을 수 없습니다. <a href="/">목록</a></div>'), code=404)
                return
            start_job(name, cdir)
            self._redirect(f"/status?case={quote(name)}")
        elif u.path == "/status":
            self._send(page(f"실행 - {name}", status_body(name)))
        elif u.path == "/result":
            if case_dir(name) is None:
                self._send(page("오류", '<div class="panel">사건을 찾을 수 없습니다.</div>'), code=404)
                return
            self._send(page(f"결과 - {name}", result_body(name)))
        elif u.path == "/file":
            fname = Path(q.get("name", "")).name
            p = OUT / name / fname
            if case_dir(name) is None or not p.is_file() or ".." in fname:
                self._send(b"not found", "text/plain", 404)
                return
            ctype = "application/json" if p.suffix == ".json" else "text/plain; charset=utf-8"
            self._send(p.read_bytes(), ctype, download=fname)
        elif u.path == "/crossresult":
            md = OUT / "crosscase" / "shared.md"
            ev = OUT / "crosscase" / "evaluate.md"
            body = '<p><a href="/">← 사건 목록</a></p>'
            if md.exists():
                body += f'<div class="panel">{md_to_html(md.read_text(encoding="utf-8"))}</div>'
                if ev.exists():
                    body += f'<div class="panel">{md_to_html(ev.read_text(encoding="utf-8"))}</div>'
            else:
                body += '<div class="panel">아직 교차 조회 결과가 없습니다.</div>'
            self._send(page("사건 간 교차 조회", body))
        else:
            self._send(b"not found", "text/plain", 404)

    def do_POST(self) -> None:
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if u.path == "/cross":
            try:
                cross_cases.run(OUT, labels_root=DATA_SYN)
            except SystemExit as e:
                self._send(page("교차 조회", f'<div class="panel"><span class="pill bad">실패</span> {E(str(e))} <a href="/">목록</a></div>'))
                return
            self._redirect("/crossresult")
        elif u.path == "/new":
            msg = self._handle_new(raw)
            if msg:
                self._send(page("새 사건", f'<div class="panel"><span class="pill bad">실패</span> {E(msg)} <a href="/">목록</a></div>'), code=400)
            else:
                self._redirect("/")
        else:
            self._send(b"not found", "text/plain", 404)

    def _handle_new(self, raw: bytes) -> str:
        """multipart 업로드를 data/raw/<사건>/raw/ 에 저장한다. 오류면 메시지를 돌려준다."""
        ctype = self.headers.get("Content-Type", "")
        msg = BytesParser(policy=email_policy).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + raw)
        fields: dict[str, str] = {}
        files: list[tuple[str, bytes]] = []
        for part in msg.iter_parts():
            cd = part.get("Content-Disposition", "")
            m = re.search(r'name="([^"]*)"', cd)
            if not m:
                continue
            field = m.group(1)
            fn = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if fn:
                files.append((Path(fn).name, payload))
            else:
                fields[field] = payload.decode("utf-8", errors="replace").strip()
        name, victim = fields.get("case", ""), fields.get("victim", "")
        if not CASE_NAME.match(name):
            return "사건 이름이 비어 있거나 허용되지 않는 문자가 있습니다."
        if not victim:
            return "피해자 이름을 입력하세요."
        files = [(n, b) for n, b in files if n and b]
        if not files:
            return "파일을 하나 이상 올리세요."
        bad = [n for n, _ in files if Path(n).suffix.lower() not in ALLOWED_SUFFIXES]
        if bad:
            return f"지원하지 않는 파일 형식: {', '.join(bad)} (txt, csv, png, jpg 만)"
        target = DATA_RAW / name
        if target.exists():
            return f"이미 있는 사건 이름입니다: {name}"
        (target / "raw").mkdir(parents=True)
        for n, b in files:
            (target / "raw" / n).write_bytes(b)
        (target / "case.json").write_text(json.dumps({"case": name, "victim": victim, "synthetic": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return ""


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="증거 정리기 로컬 앱")
    ap.add_argument("--port", type=int, default=0, help="고정 포트 (기본: 빈 포트 자동)")
    ap.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음")
    args = ap.parse_args(argv)

    DATA_RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    unpack_bundled_synthetic()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    print(f"증거 정리기 앱: {url}  (이 창을 닫으면 앱이 종료됩니다)")
    print(f"자료·산출물 폴더: {HOME}")
    sys.stdout.flush()
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if ARCHIVE is None:
            shutil.rmtree(ROOT / "__pycache__", ignore_errors=True)


if __name__ == "__main__":
    main()
