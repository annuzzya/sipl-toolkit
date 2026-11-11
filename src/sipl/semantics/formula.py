"""Мова тверджень для асистента доведення: арифметика, порівняння, логіка.

    арифметика:  + - * /  (/ — точний раціональний, напр. 3*k*(k+1)/2), дужки, числа, змінні
    порівняння:  =  !=  <  <=  >  >=  (також ≠ ≤ ≥), ланцюжки: 0 <= N <= n
    логіка:      and  or  not  ->  (також ∧ ∨ ¬ ⇒), true, false
Пріоритет: not > and > or > ->  (-> права асоціативність).
"""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Mapping, Optional

from .poly import NotPolynomial, Poly


class FormulaError(Exception):
    def __init__(self, message: str, pos: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.pos = pos


_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+)|(?P<id>[A-Za-z_][A-Za-z_0-9]*)|(?P<op><=|>=|!=|->|&&|\|\||≤|≥|≠|⇒|∧|∨|¬|[-+*/()=<>!]))"
)
_WORDS = {"and": "and", "or": "or", "not": "not", "true": "true", "false": "false"}
_ALIASES = {"≤": "<=", "≥": ">=", "≠": "!=", "⇒": "->", "∧": "and", "&&": "and", "∨": "or", "||": "or", "¬": "not", "!": "not"}
_RELOPS = {"=", "!=", "<", "<=", ">", ">="}


def _lex(text: str) -> list[tuple[str, str, int]]:
    out, pos = [], 0
    text = text.rstrip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise FormulaError(f"недопустимий символ {text[pos:].lstrip()[:1]!r}", pos)
        pos = m.end()
        if m.group("num"):
            out.append(("num", m.group("num"), m.start("num")))
        elif m.group("id"):
            w = m.group("id")
            out.append((_WORDS[w], w, m.start("id")) if w in _WORDS else ("id", w, m.start("id")))
        else:
            op = _ALIASES.get(m.group("op"), m.group("op"))
            out.append((op, op, m.start("op")))
    out.append(("eof", "", len(text)))
    return out


class _FParser:
    def __init__(self, text: str):
        self.text = text
        self.toks = _lex(text)
        self.i = 0

    @property
    def kind(self) -> str:
        return self.toks[self.i][0]

    def adv(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, k: str):
        if self.kind != k:
            raise FormulaError(f"очікувалось {k!r}, знайдено {self.toks[self.i][1] or 'кінець'!r}", self.toks[self.i][2])
        return self.adv()

    def parse(self):
        f = self.imp()
        if self.kind != "eof":
            raise FormulaError(f"зайвий текст {self.toks[self.i][1]!r}", self.toks[self.i][2])
        return f

    def imp(self):
        left = self.or_()
        if self.kind == "->":
            self.adv()
            return ("imp", left, self.imp())
        return left

    def or_(self):
        left = self.and_()
        while self.kind == "or":
            self.adv()
            left = ("or", left, self.and_())
        return left

    def and_(self):
        left = self.not_()
        while self.kind == "and":
            self.adv()
            left = ("and", left, self.not_())
        return left

    def not_(self):
        if self.kind == "not":
            self.adv()
            return ("not", self.not_())
        return self.atom()

    def atom(self):
        if self.kind in ("true", "false"):
            return ("bool", self.adv()[0] == "true")
        if self.kind == "(":
            save = self.i
            try:
                return self.cmp()
            except FormulaError:
                self.i = save
                self.adv()
                f = self.imp()
                self.expect(")")
                return f
        return self.cmp()

    def cmp(self):
        first = self.arith()
        if self.kind not in _RELOPS:
            raise FormulaError("очікувалось порівняння (=, !=, <, <=, >, >=)", self.toks[self.i][2])
        parts = []
        left = first
        while self.kind in _RELOPS:
            op = self.adv()[0]
            right = self.arith()
            parts.append(("cmp", op, left, right))
            left = right
        out = parts[0]
        for p in parts[1:]:
            out = ("and", out, p)
        return out

    def arith(self):
        left = self.term()
        while self.kind in ("+", "-"):
            op = self.adv()[0]
            left = ("bin", op, left, self.term())
        return left

    def term(self):
        left = self.unary()
        while self.kind in ("*", "/"):
            op = self.adv()[0]
            left = ("bin", op, left, self.unary())
        return left

    def unary(self):
        if self.kind == "-":
            self.adv()
            return ("neg", self.unary())
        return self.primary()

    def primary(self):
        if self.kind == "num":
            return ("num", Fraction(int(self.adv()[1])))
        if self.kind == "id":
            return ("var", self.adv()[1])
        if self.kind == "(":
            self.adv()
            e = self.arith()
            self.expect(")")
            return e
        raise FormulaError(f"очікувалось число, змінна або '(', знайдено {self.toks[self.i][1] or 'кінець виразу'!r}", self.toks[self.i][2])


def parse_formula(text: str):
    """Розбір твердження (булева формула)."""
    return _FParser(text).parse()


def parse_arith(text: str):
    """Розбір арифметичного виразу."""
    p = _FParser(text)
    e = p.arith()
    if p.kind != "eof":
        raise FormulaError(f"зайвий текст {p.toks[p.i][1]!r}", p.toks[p.i][2])
    return e


# ------------------------------------------------------------------ обчислення
def eval_arith(e, env: Mapping[str, object]) -> Fraction:
    k = e[0]
    if k == "num":
        return e[1]
    if k == "var":
        if e[1] not in env:
            raise FormulaError(f"змінна {e[1]} не визначена")
        return Fraction(env[e[1]])
    if k == "neg":
        return -eval_arith(e[1], env)
    a, b = eval_arith(e[2], env), eval_arith(e[3], env)
    if e[1] == "+":
        return a + b
    if e[1] == "-":
        return a - b
    if e[1] == "*":
        return a * b
    if b == 0:
        raise FormulaError("ділення на нуль")
    return a / b


def eval_formula(f, env: Mapping[str, object]) -> bool:
    k = f[0]
    if k == "bool":
        return f[1]
    if k == "cmp":
        a, b = eval_arith(f[2], env), eval_arith(f[3], env)
        return {"=": a == b, "!=": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[f[1]]
    if k == "and":
        return eval_formula(f[1], env) and eval_formula(f[2], env)
    if k == "or":
        return eval_formula(f[1], env) or eval_formula(f[2], env)
    if k == "not":
        return not eval_formula(f[1], env)
    if k == "imp":
        return (not eval_formula(f[1], env)) or eval_formula(f[2], env)
    raise ValueError(f)


def formula_vars(f) -> set:
    out: set = set()

    def rec(x):
        if isinstance(x, tuple):
            if x and x[0] == "var":
                out.add(x[1])
            else:
                for y in x[1:]:
                    rec(y)

    rec(f)
    return out


# -------------------------------------------------------------- символьно
def arith_to_poly(e, env: Mapping[str, Poly]) -> Poly:
    k = e[0]
    if k == "num":
        return Poly.const(e[1])
    if k == "var":
        return env[e[1]] if e[1] in env else Poly.var(e[1])
    if k == "neg":
        return -arith_to_poly(e[1], env)
    a, b = arith_to_poly(e[2], env), arith_to_poly(e[3], env)
    if e[1] == "+":
        return a + b
    if e[1] == "-":
        return a - b
    if e[1] == "*":
        return a * b
    if b.is_const() and not b.is_zero():
        return a.scale(1 / b.const_value())
    raise NotPolynomial("ділення на нестале значення виходить за межі многочленів")


def sym_truth(f, env: Mapping[str, Poly]) -> Optional[bool]:
    """Істинність тотожно (для всіх значень вільних змінних): True / False / None (невідомо)."""
    k = f[0]
    if k == "bool":
        return f[1]
    if k == "cmp":
        d = arith_to_poly(f[2], env) - arith_to_poly(f[3], env)
        if d.is_const():
            c = d.const_value()
            return {"=": c == 0, "!=": c != 0, "<": c < 0, "<=": c <= 0, ">": c > 0, ">=": c >= 0}[f[1]]
        if f[1] == "=" and d.is_zero():
            return True
        return None
    if k == "not":
        v = sym_truth(f[1], env)
        return None if v is None else not v
    if k in ("and", "or", "imp"):
        a, b = sym_truth(f[1], env), sym_truth(f[2], env)
        if k == "and":
            return False if a is False or b is False else (True if a and b else None)
        if k == "or":
            return True if a is True or b is True else (False if a is False and b is False else None)
        return True if a is False or b is True else (False if a is True and b is False else None)
    raise ValueError(f)


def format_formula(f) -> str:
    k = f[0]
    if k == "bool":
        return "true" if f[1] else "false"
    if k == "num":
        return str(f[1])
    if k == "var":
        return f[1]
    if k == "neg":
        return f"-{format_formula(f[1])}"
    if k == "bin":
        return f"({format_formula(f[2])} {f[1]} {format_formula(f[3])})"
    if k == "cmp":
        return f"{format_formula(f[2])} {f[1]} {format_formula(f[3])}"
    if k == "not":
        return f"not ({format_formula(f[1])})"
    return f"({format_formula(f[1])} {k} {format_formula(f[2])})"
