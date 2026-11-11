"""Многочлени від кількох змінних із раціональними коефіцієнтами (точна арифметика).

Потрібні для символьної перевірки кроку індукції: st_k ↦ st_{k+1} — тотожність многочленів.
"""
from __future__ import annotations

from fractions import Fraction
from typing import Mapping

Mono = tuple  # ((змінна, степінь), …), відсортовано за іменем


class NotPolynomial(Exception):
    pass


_SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


class Poly:
    __slots__ = ("terms",)

    def __init__(self, terms: Mapping[Mono, Fraction] | None = None):
        self.terms = {m: Fraction(c) for m, c in (terms or {}).items() if c != 0}

    # --- конструктори
    @staticmethod
    def const(c) -> "Poly":
        return Poly({(): Fraction(c)})

    @staticmethod
    def var(name: str) -> "Poly":
        return Poly({((name, 1),): Fraction(1)})

    # --- арифметика
    def __add__(self, other: "Poly") -> "Poly":
        out = dict(self.terms)
        for m, c in other.terms.items():
            out[m] = out.get(m, Fraction(0)) + c
        return Poly(out)

    def __neg__(self) -> "Poly":
        return Poly({m: -c for m, c in self.terms.items()})

    def __sub__(self, other: "Poly") -> "Poly":
        return self + (-other)

    def __mul__(self, other: "Poly") -> "Poly":
        out: dict[Mono, Fraction] = {}
        for m1, c1 in self.terms.items():
            for m2, c2 in other.terms.items():
                m = _mul_mono(m1, m2)
                out[m] = out.get(m, Fraction(0)) + c1 * c2
        return Poly(out)

    def scale(self, c) -> "Poly":
        return Poly({m: v * Fraction(c) for m, v in self.terms.items()})

    def __eq__(self, other) -> bool:
        return isinstance(other, Poly) and self.terms == other.terms

    def __hash__(self):
        return hash(frozenset(self.terms.items()))

    # --- властивості
    def is_zero(self) -> bool:
        return not self.terms

    def is_const(self) -> bool:
        return all(m == () for m in self.terms)

    def const_value(self) -> Fraction:
        return self.terms.get((), Fraction(0))

    def variables(self) -> set:
        return {v for m in self.terms for v, _ in m}

    # --- підстановка та обчислення
    def subst(self, mapping: Mapping[str, "Poly"]) -> "Poly":
        result = Poly()
        for mono, coef in self.terms.items():
            term = Poly.const(coef)
            for v, e in mono:
                base = mapping.get(v, Poly.var(v))
                for _ in range(e):
                    term = term * base
            result = result + term
        return result

    def evaluate(self, env: Mapping[str, object]) -> Fraction:
        total = Fraction(0)
        for mono, coef in self.terms.items():
            v = coef
            for name, e in mono:
                v *= Fraction(env[name]) ** e
            total += v
        return total

    # --- запис
    def __str__(self) -> str:
        if not self.terms:
            return "0"
        items = sorted(self.terms.items(), key=lambda mc: mc[0], reverse=True)
        items.sort(key=lambda mc: -sum(e for _, e in mc[0]))
        out = ""
        for i, (mono, coef) in enumerate(items):
            sign = "-" if coef < 0 else "+"
            a = abs(coef)
            body = "·".join(_pow(v, e) for v, e in mono)
            if not mono:
                piece = str(a)
            elif a == 1:
                piece = body
            else:
                piece = f"{a}·{body}"
            if i == 0:
                out = ("-" if coef < 0 else "") + piece
            else:
                out += f" {sign} {piece}"
        return out

    __repr__ = __str__


def _pow(v: str, e: int) -> str:
    return v if e == 1 else v + str(e).translate(_SUP)


def _mul_mono(a: Mono, b: Mono) -> Mono:
    d: dict[str, int] = dict(a)
    for v, e in b:
        d[v] = d.get(v, 0) + e
    return tuple(sorted(d.items()))
