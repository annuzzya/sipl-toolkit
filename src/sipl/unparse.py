"""Канонічний запис SIPL-фрагмента з AST (для пояснень і порівнянь)."""
from __future__ import annotations

from . import ast as A


def unparse(node: A.Node) -> str:
    """Одним рядком, з мінімумом пробілів: `T:=T+3; S:=S+T`."""
    if isinstance(node, A.Num):
        return str(node.value)
    if isinstance(node, A.Var):
        return node.name
    if isinstance(node, A.BinOp):
        return f"{unparse(node.left)}{node.op}{unparse(node.right)}"
    if isinstance(node, A.ParenA) or isinstance(node, A.ParenB):
        return f"({unparse(node.inner)})"
    if isinstance(node, A.Compare):
        return f"{unparse(node.left)}{node.op}{unparse(node.right)}"
    if isinstance(node, A.Or):
        return f"{unparse(node.left)}∨{unparse(node.right)}"
    if isinstance(node, A.Not):
        return f"¬{unparse(node.operand)}"
    if isinstance(node, A.Assign):
        return f"{unparse(node.target)}:={unparse(node.expr)}"
    if isinstance(node, A.Seq):
        return f"{unparse(node.left)}; {unparse(node.right)}"
    if isinstance(node, A.If):
        return f"if {unparse(node.cond)} then {unparse(node.then)} else {unparse(node.orelse)}"
    if isinstance(node, A.While):
        return f"while {unparse(node.cond)} do {unparse(node.body)}"
    if isinstance(node, A.Block):
        return f"begin {unparse(node.body)} end"
    if isinstance(node, A.Skip):
        return "skip"
    if isinstance(node, A.Program):
        return f"begin {unparse(node.body)} end"
    raise TypeError(f"невідомий вузол: {node!r}")


def sexpr(node: A.Node, indent: int = 0) -> str:
    """AST у вигляді дерева з відступами: `Assign(S) @1:7`."""
    pad = "  " * indent
    pos = f"@{node.span.line}:{node.span.col}"
    if isinstance(node, A.Num):
        return f"{pad}Num({node.value}) {pos}"
    if isinstance(node, A.Var):
        return f"{pad}Var({node.name}) {pos}"
    if isinstance(node, (A.BinOp, A.Compare)):
        head = f"{pad}{node.kind}({node.op}) {pos}"
    else:
        head = f"{pad}{node.kind} {pos}"
    return "\n".join([head] + [sexpr(c, indent + 1) for c in node.children()])
