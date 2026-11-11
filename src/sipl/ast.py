"""Власні AST-вузли SIPL (не сире дерево сторонньої бібліотеки).

Кожен вузол має `span` (SourceSpan) та `parts` — конкретний склад вузла в порядку
запису в тексті (піддерева і лексеми). За `parts` будується дерево синтаксичного
виводу (parse tree), а за полями вузла — абстрактне дерево (AST).
Порівняння вузлів (==) ігнорує позиції та parts, тобто порівнюється лише структура.
Дужки та begin/end-блоки збережено як окремі вузли (ParenA, ParenB, Block):
у семантиці курсу для них є власні правила (NS_A_Par, NS_B_Par, NS_Stm_BE).
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Iterator, Optional, Union

from .lexer import Token
from .spans import SourceSpan


class Node:
    """Базовий клас вузла AST."""

    kind: str = "Node"
    span: SourceSpan
    parts: tuple

    def children(self) -> Iterator["Node"]:
        for f in fields(self):
            if f.name in ("span", "parts"):
                continue
            value = getattr(self, f.name)
            if isinstance(value, Node):
                yield value

    def walk(self) -> Iterator["Node"]:
        yield self
        for child in self.children():
            yield from child.walk()

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"node": self.kind, "span": self.span.to_dict()}
        for f in fields(self):
            if f.name in ("span", "parts"):
                continue
            value = getattr(self, f.name)
            out[f.name] = value.to_dict() if isinstance(value, Node) else value
        return out


def _node(cls):
    return dataclass(eq=True, frozen=True)(cls)


_SPAN = field(compare=False, repr=False)
_PARTS = field(compare=False, repr=False, default=())


# ----------------------------- арифметичні вирази ---------------------------
@_node
class Num(Node):
    value: int
    span: SourceSpan = _SPAN
    parts: tuple = _PARTS
    kind = "Num"


@_node
class Var(Node):
    name: str
    span: SourceSpan = _SPAN
    parts: tuple = _PARTS
    kind = "Var"


@_node
class BinOp(Node):
    op: str  # '+', '-', '*'
    left: "Aexp"
    right: "Aexp"
    span: SourceSpan = _SPAN
    parts: tuple = _PARTS
    kind = "BinOp"


@_node
class ParenA(Node):
    inner: "Aexp"
    span: SourceSpan = _SPAN
    parts: tuple = _PARTS
    kind = "ParenA"


Aexp = Union[Num, Var, BinOp, ParenA]


# ----------------------------- логічні вирази -------------------------------
@_node
class Compare(Node):
    op: str  # '=' або '>'
    left: Aexp
    right: Aexp
    span: SourceSpan = _SPAN
    parts: tuple = _PARTS
    kind = "Compare"


@_node
class Or(Node):
    left: "Bexp"
    right: "Bexp"
    span: SourceSpan = _SPAN
    parts: tuple = _PARTS
    kind = "Or"


@_node
class Not(Node):
    operand: "Bexp"
    span: SourceSpan = _SPAN
    parts: tuple = _PARTS
    kind = "Not"


@_node
class ParenB(Node):
    inner: "Bexp"
    span: SourceSpan = _SPAN
    parts: tuple = _PARTS
    kind = "ParenB"


Bexp = Union[Compare, Or, Not, ParenB]


# ----------------------------- оператори ------------------------------------
@_node
class Assign(Node):
    target: Var
    expr: Aexp
    span: SourceSpan = _SPAN
    parts: tuple = _PARTS
    kind = "Assign"


@_node
class Seq(Node):
    left: "Stm"
    right: "Stm"
    span: SourceSpan = _SPAN
    parts: tuple = _PARTS
    kind = "Seq"


@_node
class If(Node):
    cond: Bexp
    then: "Stm"
    orelse: "Stm"
    span: SourceSpan = _SPAN
    parts: tuple = _PARTS
    kind = "If"


@_node
class While(Node):
    cond: Bexp
    body: "Stm"
    span: SourceSpan = _SPAN
    parts: tuple = _PARTS
    kind = "While"


@_node
class Block(Node):
    body: "Stm"
    span: SourceSpan = _SPAN
    parts: tuple = _PARTS
    kind = "Block"


@_node
class Skip(Node):
    span: SourceSpan = _SPAN
    parts: tuple = _PARTS
    kind = "Skip"


Stm = Union[Assign, Seq, If, While, Block, Skip]


@_node
class Program(Node):
    body: Stm
    span: SourceSpan = _SPAN
    parts: tuple = _PARTS
    kind = "Prog"


ARITH_NODES = (Num, Var, BinOp, ParenA)
BOOL_NODES = (Compare, Or, Not, ParenB)
STM_NODES = (Assign, Seq, If, While, Block, Skip)
