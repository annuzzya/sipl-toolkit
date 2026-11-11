"""Автоматична побудова семантичного терму з AST (SEM-01).

Кожне правило таблиці 1.6 курсу має власне ім'я (NS_Prog, NS_Stm_As, …). Побудова
рекурсивна за структурою AST; одночасно можна записати ПОСЛІДОВНІСТЬ ЗАСТОСУВАНИХ
ПРАВИЛ (explanation trace) у вигляді рівностей, як у практичній роботі 2.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .. import ast as A
from ..spans import SourceSpan
from ..unparse import unparse
from . import term as T


@dataclass(frozen=True)
class RewriteStep:
    """Один крок: застосування правила NS_* до фрагмента тексту."""

    rule: str
    lhs: str  # напр. sem_S(S:=0; T:=0)
    rhs: str  # напр. sem_S(S:=0) · sem_S(T:=0)
    span: Optional[SourceSpan] = None

    def to_dict(self) -> dict:
        return {"rule": self.rule, "lhs": self.lhs, "rhs": self.rhs, "span": self.span.to_dict() if self.span else None}

    def __str__(self) -> str:
        return f"{self.rule}: {self.lhs} = {self.rhs}"


class _Builder:
    def __init__(self, record: bool):
        self.steps: list[RewriteStep] = [] if record else None

    def _rec(self, rule: str, lhs: str, rhs: str, node: A.Node) -> None:
        if self.steps is not None:
            self.steps.append(RewriteStep(rule, lhs, rhs, node.span))

    # --- sem_P
    def prog(self, p: A.Program) -> T.Term:
        self._rec("NS_Prog", f"sem_P({unparse(p)})", f"sem_S({unparse(p.body)})", p)
        return self.stm(p.body)

    # --- sem_S
    def stm(self, s: A.Node) -> T.Term:
        if isinstance(s, A.Assign):
            self._rec("NS_Stm_As", f"sem_S({unparse(s)})", f"AS^{s.target.name}(sem_A({unparse(s.expr)}))", s)
            return T.AsT(s.target.name, self.aexp(s.expr))
        if isinstance(s, A.Seq):
            self._rec("NS_Stm_Seq", f"sem_S({unparse(s)})", f"sem_S({unparse(s.left)}) · sem_S({unparse(s.right)})", s)
            return T.SeqT(self.stm(s.left), self.stm(s.right))
        if isinstance(s, A.If):
            self._rec(
                "NS_Stm_If",
                f"sem_S({unparse(s)})",
                f"IF(sem_B({unparse(s.cond)}), sem_S({unparse(s.then)}), sem_S({unparse(s.orelse)}))",
                s,
            )
            return T.IfT(self.bexp(s.cond), self.stm(s.then), self.stm(s.orelse))
        if isinstance(s, A.While):
            self._rec("NS_Stm_Wh", f"sem_S({unparse(s)})", f"WH(sem_B({unparse(s.cond)}), sem_S({unparse(s.body)}))", s)
            return T.WhT(self.bexp(s.cond), self.stm(s.body))
        if isinstance(s, A.Block):
            self._rec("NS_Stm_BE", f"sem_S({unparse(s)})", f"(sem_S({unparse(s.body)}))", s)
            return self.stm(s.body)
        if isinstance(s, A.Skip):
            self._rec("NS_Stm_skip", "sem_S(skip)", "id", s)
            return T.IdT()
        raise TypeError(f"очікувався оператор, отримано {s!r}")

    # --- sem_A
    def aexp(self, a: A.Node) -> T.Term:
        if isinstance(a, A.Num):
            self._rec("NS_A_Num", f"sem_A({a.value})", f"{a.value}̄", a)
            return T.ConstT(a.value)
        if isinstance(a, A.Var):
            self._rec("NS_A_Var", f"sem_A({a.name})", f"{a.name}⇒", a)
            return T.DenomT(a.name)
        if isinstance(a, A.BinOp):
            func, rule = {"+": ("add", "NS_A_Add"), "-": ("sub", "NS_A_Sub"), "*": ("mult", "NS_A_Mult")}[a.op]
            self._rec(rule, f"sem_A({unparse(a)})", f"S²({func}, sem_A({unparse(a.left)}), sem_A({unparse(a.right)}))", a)
            return T.SupT(func, (self.aexp(a.left), self.aexp(a.right)))
        if isinstance(a, A.ParenA):
            self._rec("NS_A_Par", f"sem_A({unparse(a)})", f"sem_A({unparse(a.inner)})", a)
            return self.aexp(a.inner)
        raise TypeError(f"очікувався арифметичний вираз, отримано {a!r}")

    # --- sem_B
    def bexp(self, b: A.Node) -> T.Term:
        if isinstance(b, A.Compare):
            func, rule = ("eq", "NS_B_eq") if b.op == "=" else ("gr", "NS_B_gr")
            self._rec(rule, f"sem_B({unparse(b)})", f"S²({func}, sem_A({unparse(b.left)}), sem_A({unparse(b.right)}))", b)
            return T.SupT(func, (self.aexp(b.left), self.aexp(b.right)))
        if isinstance(b, A.Or):
            self._rec("NS_B_or", f"sem_B({unparse(b)})", f"S²(or, sem_B({unparse(b.left)}), sem_B({unparse(b.right)}))", b)
            return T.SupT("or", (self.bexp(b.left), self.bexp(b.right)))
        if isinstance(b, A.Not):
            self._rec("NS_B_neg", f"sem_B({unparse(b)})", f"S¹(neg, sem_B({unparse(b.operand)}))", b)
            return T.SupT("neg", (self.bexp(b.operand),))
        if isinstance(b, A.ParenB):
            self._rec("NS_B_Par", f"sem_B({unparse(b)})", f"sem_B({unparse(b.inner)})", b)
            return self.bexp(b.inner)
        raise TypeError(f"очікувалась умова, отримано {b!r}")


def build_term(program: A.Program) -> T.Term:
    """sem_P(program) — семантичний терм програми."""
    return _Builder(record=False).prog(program)


def build_term_with_trace(program: A.Program) -> tuple[T.Term, list[RewriteStep]]:
    """Терм + послідовність застосованих правил NS_* (у порядку обходу «зверху вниз»)."""
    b = _Builder(record=True)
    term = b.prog(program)
    return term, b.steps


def build_stm_term(stm: A.Node) -> T.Term:
    """sem_S(stm) для окремого оператора."""
    return _Builder(record=False).stm(stm)


def build_bexp_term(cond: A.Node) -> T.Term:
    """sem_B(cond) для окремої умови."""
    return _Builder(record=False).bexp(cond)
