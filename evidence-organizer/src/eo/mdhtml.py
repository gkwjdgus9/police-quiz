"""보고서·평가표 markdown 을 앱 화면용 HTML 로 바꾸는 작은 변환기.

지원: 제목(#~###), 불릿, 표, 인라인 코드, [파일:행] 각주(칩으로), HTML 주석(버림), 그 외 문단.
외부 라이브러리 없음. 모든 텍스트는 이스케이프한다.
"""

from __future__ import annotations

import html
import re

_FOOTNOTE = re.compile(r"\[([^\[\]:]+):(\d+)\]")
_CODE = re.compile(r"`([^`]+)`")
_TABLE_SEP = re.compile(r"\|(?:\s*:?-+:?\s*\|)+")


def _inline(text: str) -> str:
    t = html.escape(text)
    t = _CODE.sub(r"<code>\1</code>", t)
    t = _FOOTNOTE.sub(lambda m: f'<span class="fn">{m.group(1)}:{m.group(2)}</span>', t)
    return t


def md_to_html(md: str) -> str:
    out: list[str] = []
    lines = md.splitlines()
    in_ul = in_tbl = False

    def close() -> None:
        nonlocal in_ul, in_tbl
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_tbl:
            out.append("</tbody></table></div>")
            in_tbl = False

    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("<!--"):
            continue
        if s.startswith("### "):
            close(); out.append(f"<h4>{_inline(s[4:])}</h4>")
        elif s.startswith("## "):
            close(); out.append(f"<h3>{_inline(s[3:])}</h3>")
        elif s.startswith("# "):
            close(); out.append(f"<h3>{_inline(s[2:])}</h3>")
        elif s.startswith("- "):
            if not in_ul:
                close(); out.append("<ul>"); in_ul = True
            out.append(f"<li>{_inline(s[2:])}</li>")
        elif s.startswith("|"):
            if _TABLE_SEP.fullmatch(s):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if _TABLE_SEP.fullmatch(nxt):
                close()
                out.append('<div class="scroll"><table><thead><tr>' + "".join(f"<th>{_inline(c)}</th>" for c in cells) + "</tr></thead><tbody>")
                in_tbl = True
            elif in_tbl:
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
        elif s == "":
            if in_ul:
                out.append("</ul>"); in_ul = False
            if in_tbl:
                out.append("</tbody></table></div>"); in_tbl = False
        else:
            close(); out.append(f"<p>{_inline(s)}</p>")
    close()
    return "\n".join(out)
