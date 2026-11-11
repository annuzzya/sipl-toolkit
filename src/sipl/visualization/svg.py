"""SVG- та HTML-подання дерева виводу, згенероване з реальної структури PNode."""
from __future__ import annotations

import html
import json

from ..spans import SourceText
from .parse_tree import PNode, to_dict


def _width(text: str) -> int:
    return max(44, 9 * len(text) + 22)


def to_svg(root: PNode, source: SourceText, ua: bool = False) -> str:
    # --- висоти: нетермінали за глибиною, термінали в нижньому ряду
    depth: dict[int, int] = {}

    def set_depth(n: PNode, d: int) -> None:
        depth[id(n)] = d
        for c in n.children:
            set_depth(c, d + 1)

    set_depth(root, 0)
    max_depth = max(depth.values())
    level_y = lambda d: 36 + d * 56  # noqa: E731
    bottom_y = level_y(max_depth)

    # --- координати x: кожному піддереву відводиться смуга не вужча за підписи його вузлів
    def label_of(n: PNode) -> str:
        return f"{n.leaf_index}. {n.symbol}" if n.terminal else n.label(ua)

    GAP = 10
    span_w: dict[int, float] = {}

    def measure(n: PNode) -> float:
        own = _width(label_of(n)) + GAP
        kids = sum(measure(c) for c in n.children)
        span_w[id(n)] = max(own, kids)
        return span_w[id(n)]

    xs: dict[int, float] = {}

    def place(n: PNode, x0: float) -> None:
        kids_w = sum(span_w[id(c)] for c in n.children)
        cur = x0 + (span_w[id(n)] - kids_w) / 2
        for c in n.children:
            place(c, cur)
            cur += span_w[id(c)]
        if n.children:
            xs[id(n)] = (xs[id(n.children[0])] + xs[id(n.children[-1])]) / 2
        else:
            xs[id(n)] = x0 + span_w[id(n)] / 2

    measure(root)
    place(root, 14.0)
    total_w = int(span_w[id(root)] + 28)
    total_h = int(bottom_y + 40)

    def ypos(n: PNode) -> float:
        return level_y(depth[id(n)])

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="{total_h}" viewBox="0 0 {total_w} {total_h}" '
        f'font-family="Helvetica, Arial, sans-serif" font-size="13">',
        f'<title>Дерево синтаксичного виводу: {html.escape(source.name)}</title>',
        f'<rect width="{total_w}" height="{total_h}" fill="#ffffff"/>',
    ]
    # ребра
    for n in root.walk():
        for c in n.children:
            parts.append(
                f'<line x1="{xs[id(n)]:.1f}" y1="{ypos(n) + 13:.1f}" x2="{xs[id(c)]:.1f}" y2="{ypos(c) - 13:.1f}" '
                f'stroke="#8a94a6" stroke-width="1.2"/>'
            )
    # вузли
    for n in root.walk():
        x, y = xs[id(n)], ypos(n)
        frag = source.fragment(n.span)
        tip = f"{frag}  [{n.span.line}:{n.span.col}–{n.span.end_line}:{n.span.end_col}]"
        if n.terminal:
            label = f"{n.leaf_index}. {n.symbol}"
            w = _width(label)
            parts.append(
                f'<g class="node terminal" data-start="{n.span.start}" data-end="{n.span.end}"><title>{html.escape(tip)}</title>'
                f'<rect x="{x - w / 2:.1f}" y="{y - 13:.1f}" width="{w}" height="26" rx="4" fill="#fff7e6" stroke="#d9a441"/>'
                f'<text x="{x:.1f}" y="{y + 5:.1f}" text-anchor="middle" fill="#3b2f0b">{html.escape(label)}</text></g>'
            )
        else:
            label = n.label(ua)
            w = _width(label)
            rule = n.production(ua) or ""
            parts.append(
                f'<g class="node nonterminal" data-start="{n.span.start}" data-end="{n.span.end}">'
                f'<title>{html.escape(rule)}&#10;{html.escape(tip)}</title>'
                f'<rect x="{x - w / 2:.1f}" y="{y - 13:.1f}" width="{w}" height="26" rx="13" fill="#e8f0ff" stroke="#4a6fd1"/>'
                f'<text x="{x:.1f}" y="{y + 5:.1f}" text-anchor="middle" fill="#14264f">{html.escape(label)}</text></g>'
            )
    parts.append("</svg>")
    return "\n".join(parts)


_HTML = """<!doctype html>
<html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Дерево виводу SIPL — {name}</title>
<style>
  body {{ font-family: Helvetica, Arial, sans-serif; margin: 16px; color: #1b1f29; background: #fff; }}
  pre#src {{ background: #f5f7fb; padding: 12px; border-radius: 6px; font-size: 14px; line-height: 1.5; overflow-x: auto; }}
  mark {{ background: #ffe08a; }}
  #info {{ min-height: 1.4em; color: #3a465e; font-size: 14px; margin: 6px 0 12px; }}
  .wrap {{ overflow: auto; border: 1px solid #d5dbe8; border-radius: 6px; }}
  g.node {{ cursor: pointer; }}
  g.node:hover rect {{ stroke-width: 2.4; }}
</style></head><body>
<h2>Дерево синтаксичного виводу</h2>
<p>Клацніть на вузол — відповідний фрагмент вихідного коду підсвітиться.</p>
<pre id="src"></pre>
<div id="info"></div>
<div class="wrap">{svg}</div>
<script>
const SRC = {src_json};
const pre = document.getElementById('src');
const info = document.getElementById('info');
function show(s, e, text) {{
  pre.textContent = '';
  pre.append(document.createTextNode(SRC.slice(0, s)));
  const m = document.createElement('mark'); m.textContent = SRC.slice(s, e); pre.append(m);
  pre.append(document.createTextNode(SRC.slice(e)));
  info.textContent = text;
}}
show(0, 0, '');
document.querySelectorAll('g.node').forEach(g => g.addEventListener('click', () => {{
  const s = +g.dataset.start, e = +g.dataset.end;
  show(s, e, g.querySelector('title').textContent.replace(/\\n/g, ' — '));
}}));
</script></body></html>
"""


def to_html(root: PNode, source: SourceText, ua: bool = False) -> str:
    return _HTML.format(name=html.escape(source.name), svg=to_svg(root, source, ua), src_json=json.dumps(source.text, ensure_ascii=False).replace("</", "<\\/"))
