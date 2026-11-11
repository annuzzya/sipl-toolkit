"""Статичний аналіз: вхідні змінні програми та можливе читання без значення.

Змінна — ВХІДНА, якщо де-небудь прочитана раніше, ніж гарантовано (на всіх шляхах)
присвоєна. Це змінні, значення яких треба задати у початковому стані (напр. N, X, Y).
"""
from __future__ import annotations

from dataclasses import dataclass

from . import ast as A
from .errors import Diagnostic


@dataclass
class Analysis:
    inputs: list  # впорядкований список вхідних змінних
    assigned: list  # усі змінні, яким присвоюють
    variables: list  # усі змінні програми
    diagnostics: list

    def to_dict(self) -> dict:
        return {
            "inputs": self.inputs,
            "assigned": self.assigned,
            "variables": self.variables,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
        }


def reads_aexp(a: A.Node) -> list[A.Var]:
    return [n for n in a.walk() if isinstance(n, A.Var)]


def analyze(program: A.Program) -> Analysis:
    inputs: list[str] = []
    assigned: list[str] = []
    variables: list[str] = []
    diags: list[Diagnostic] = []
    reported: set[str] = set()

    def read(expr: A.Node, defined: set) -> None:
        for v in (n for n in expr.walk() if isinstance(n, A.Var)):
            if v.name not in variables:
                variables.append(v.name)
            if v.name not in defined and v.name not in inputs:
                inputs.append(v.name)
            if v.name not in defined and v.name not in reported:
                reported.add(v.name)
                diags.append(
                    Diagnostic(
                        "I-ANA-001",
                        f"змінна {v.name} читається до присвоювання — вона вхідна (її значення треба задати в початковому стані)",
                        v.span,
                        severity="info",
                    )
                )

    def stm(s: A.Node, defined: set) -> set:
        if isinstance(s, A.Assign):
            read(s.expr, defined)
            if s.target.name not in variables:
                variables.append(s.target.name)
            if s.target.name not in assigned:
                assigned.append(s.target.name)
            return defined | {s.target.name}
        if isinstance(s, A.Seq):
            return stm(s.right, stm(s.left, defined))
        if isinstance(s, A.Block):
            return stm(s.body, defined)
        if isinstance(s, A.If):
            read(s.cond, defined)
            return stm(s.then, set(defined)) & stm(s.orelse, set(defined))
        if isinstance(s, A.While):
            read(s.cond, defined)
            stm(s.body, set(defined))  # тіло може не виконатись: після циклу defined не росте
            return defined
        return defined

    stm(program.body, set())
    return Analysis(inputs, assigned, variables, diags)
