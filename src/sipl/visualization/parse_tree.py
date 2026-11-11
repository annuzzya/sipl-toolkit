"""Дерево синтаксичного виводу (parse tree) SIPL-програми за БНФ курсу (VIS-01).

Дерево будується з реального AST (поле `parts` кожного вузла зберігає лексеми та
піддерева в порядку запису), а не малюється вручну. Кожен вузол прив'язаний до
фрагмента вихідного тексту (span). Нетермінали: Prog, Stm, Aexp, Bexp, Var, Num;
листки — термінали (лексеми програми).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from .. import ast as A
from ..lexer import Token
from ..spans import SourceSpan, SourceText

UA_LABELS = {
    "Prog": "програма",
    "Stm": "оператор",
    "Aexp": "вираз",
    "Bexp": "умова",
    "Var": "змінна",
    "Num": "число",
}


@dataclass
class PNode:
    symbol: str  # Prog / Stm / … або текст терміналу
    terminal: bool
    span: SourceSpan
    children: list = field(default_factory=list)
    leaf_index: Optional[int] = None  # номер листка зліва направо (з 1)
    token_kind: Optional[str] = None

    def label(self, ua: bool = False) -> str:
        if self.terminal:
            return self.symbol
        return f"<{UA_LABELS[self.symbol]}>" if ua else self.symbol

    def production(self, ua: bool = False) -> Optional[str]:
        """Застосоване правило БНФ: `Stm → Var := Aexp`."""
        if self.terminal:
            return None
        rhs = " ".join(c.label(ua) for c in self.children)
        return f"{self.label(ua)} → {rhs}"

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def leaves(self) -> list["PNode"]:
        return [n for n in self.walk() if n.terminal]


def _symbol_of(node: A.Node) -> str:
    if isinstance(node, A.Program):
        return "Prog"
    if isinstance(node, A.STM_NODES):
        return "Stm"
    if isinstance(node, A.ARITH_NODES):
        return "Aexp"
    if isinstance(node, A.BOOL_NODES):
        return "Bexp"
    raise TypeError(node)


def build_parse_tree(program: A.Program) -> PNode:
    """Дерево виводу для AST програми. Листки нумеруються зліва направо."""
    root = _build(program, None)
    for i, leaf in enumerate(root.leaves(), start=1):
        leaf.leaf_index = i
    return root


def _terminal(tok: Token) -> PNode:
    return PNode(tok.text, True, tok.span, [], None, tok.kind)


def _build(node: A.Node, parent: Optional[A.Node]) -> PNode:
    # Var/Num: у позиції арифметичного виразу це Aexp → Var / Aexp → Num;
    # ліва частина присвоювання — просто Var.
    if isinstance(node, (A.Var, A.Num)):
        inner = PNode("Var" if isinstance(node, A.Var) else "Num", False, node.span, [_terminal(node.parts[0])])
        if isinstance(parent, A.Assign) and parent.target is node:
            return inner
        return PNode("Aexp", False, node.span, [inner])
    children = []
    for part in node.parts:
        children.append(_terminal(part) if isinstance(part, Token) else _build(part, node))
    return PNode(_symbol_of(node), False, node.span, children)


# ---------------------------------------------------------------- вивід: JSON
def to_dict(root: PNode, source: SourceText, ua: bool = False) -> dict:
    def conv(n: PNode) -> dict:
        d = {
            "symbol": n.label(ua),
            "kind": "terminal" if n.terminal else "nonterminal",
            "span": n.span.to_dict(),
            "source": source.fragment(n.span),
        }
        if n.terminal:
            d["leaf_index"] = n.leaf_index
            d["token_kind"] = n.token_kind
        else:
            d["rule"] = n.production(ua)
            d["children"] = [conv(c) for c in n.children]
        return d

    return {
        "schema_version": 1,
        "file": source.name,
        "leaf_count": len(root.leaves()),
        "tree": conv(root),
    }


def to_json(root: PNode, source: SourceText, ua: bool = False) -> str:
    return json.dumps(to_dict(root, source, ua), ensure_ascii=False, indent=2)


# --------------------------------------------------------------- вивід: текст
def to_text(root: PNode, source: SourceText, ua: bool = False) -> str:
    lines: list[str] = []

    def rec(n: PNode, prefix: str, last: bool, top: bool) -> None:
        connector = "" if top else ("└── " if last else "├── ")
        pos = f"{n.span.line}:{n.span.col}"
        if n.terminal:
            lines.append(f"{prefix}{connector}{n.leaf_index}. {n.symbol}    [{pos}]")
        else:
            frag = " ".join(source.fragment(n.span).split())
            if len(frag) > 48:
                frag = frag[:45] + "…"
            lines.append(f"{prefix}{connector}{n.label(ua)}   ⟨{frag}⟩ [{pos}]")
        child_prefix = prefix + ("" if top else ("    " if last else "│   "))
        for i, c in enumerate(n.children):
            rec(c, child_prefix, i == len(n.children) - 1, False)

    rec(root, "", True, True)
    return "\n".join(lines)


# ---------------------------------------------------------------- вивід: DOT
def to_dot(root: PNode, source: SourceText, ua: bool = False) -> str:
    ids: dict[int, str] = {}
    for i, n in enumerate(root.walk()):
        ids[id(n)] = f"n{i}"
    out = ["digraph ParseTree {", '  node [fontname="Helvetica"];', "  edge [arrowhead=none];"]
    leaf_ids = []
    for n in root.walk():
        nid = ids[id(n)]
        tip = _esc(f"{source.fragment(n.span)} ({n.span.line}:{n.span.col}-{n.span.end_line}:{n.span.end_col})")
        if n.terminal:
            out.append(f'  {nid} [label="{n.leaf_index}. {_esc(n.symbol)}", shape=plaintext, tooltip="{tip}"];')
            leaf_ids.append(nid)
        else:
            out.append(f'  {nid} [label="{_esc(n.label(ua))}", shape=box, style=rounded, tooltip="{tip}"];')
    for n in root.walk():
        for c in n.children:
            out.append(f"  {ids[id(n)]} -> {ids[id(c)]};")
    out.append("  { rank=same; " + "; ".join(leaf_ids) + "; }")
    out.append("}")
    return "\n".join(out)


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
