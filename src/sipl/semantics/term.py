"""Семантичні терми програмної алгебри A_SIPL у нотації курсу.

    n̄            ConstT      константна функція
    x⇒           DenomT      функція розіменування (denomination)
    Sⁿ(f,g1..gn) SupT        суперпозиція; f ∈ {add, sub, mult, gr, eq, or, neg}
    ASˣ(fa)      AsT         присвоювання
    f1 · f2      SeqT        послідовне виконання
    IF(fb,f1,f2) IfT         умовний оператор
    WH(fb,fS)    WhT         цикл
    id           IdT         тотожна функція
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union

ARITH_FUNCS = ("add", "sub", "mult")
BOOL_FUNCS = ("gr", "eq", "or", "neg")
FUNC_ARITY = {"add": 2, "sub": 2, "mult": 2, "gr": 2, "eq": 2, "or": 2, "neg": 1}


@dataclass(frozen=True)
class ConstT:
    value: int


@dataclass(frozen=True)
class DenomT:
    var: str


@dataclass(frozen=True)
class SupT:
    func: str
    args: tuple

    def __post_init__(self):
        if self.func not in FUNC_ARITY:
            raise ValueError(f"невідома функція {self.func!r}")
        if len(self.args) != FUNC_ARITY[self.func]:
            raise ValueError(f"{self.func} має {FUNC_ARITY[self.func]} аргумент(и), отримано {len(self.args)}")


@dataclass(frozen=True)
class AsT:
    var: str
    expr: "Term"


@dataclass(frozen=True)
class SeqT:
    left: "Term"
    right: "Term"


@dataclass(frozen=True)
class IfT:
    cond: "Term"
    then: "Term"
    orelse: "Term"


@dataclass(frozen=True)
class WhT:
    cond: "Term"
    body: "Term"


@dataclass(frozen=True)
class IdT:
    pass


Term = Union[ConstT, DenomT, SupT, AsT, SeqT, IfT, WhT, IdT]


# --------------------------------------------------------------- форматування
_OVERLINE = "\u0304"


def flatten_seq(term: Term) -> list:
    """Розгортає вкладені SeqT у плоский список (· асоціативна)."""
    if isinstance(term, SeqT):
        return flatten_seq(term.left) + flatten_seq(term.right)
    return [term]


def format_term(term: Term, style: str = "unicode") -> str:
    """Запис терму.

    style='unicode' — як у підручнику: AS^S(0̄) · WH(S²(gr, N⇒, 0̄), …)
    style='ascii'   — AS[S](c(0)) . WH(S2(gr, den(N), c(0)), …)
    style='latex'   — AS^{S}(\\overline{0}) \\cdot WH(S^{2}(gr, N\\Rightarrow, \\overline{0}), …)
    """
    if style not in ("unicode", "ascii", "latex"):
        raise ValueError("style: unicode | ascii | latex")
    return _fmt(term, style)


def _fmt(t: Term, style: str) -> str:
    if isinstance(t, ConstT):
        if style == "ascii":
            return f"c({t.value})"
        if style == "latex":
            return f"\\overline{{{t.value}}}"
        return "".join(ch + _OVERLINE for ch in str(t.value))
    if isinstance(t, DenomT):
        if style == "ascii":
            return f"den({t.var})"
        if style == "latex":
            return f"{t.var}\\Rightarrow"
        return f"{t.var}⇒"
    if isinstance(t, SupT):
        args = ", ".join(_fmt(a, style) for a in t.args)
        n = len(t.args)
        head = {"unicode": f"S{'²' if n == 2 else '¹'}", "ascii": f"S{n}", "latex": f"S^{{{n}}}"}[style]
        return f"{head}({t.func}, {args})"
    if isinstance(t, AsT):
        head = {"unicode": f"AS^{t.var}", "ascii": f"AS[{t.var}]", "latex": f"AS^{{{t.var}}}"}[style]
        return f"{head}({_fmt(t.expr, style)})"
    if isinstance(t, SeqT):
        dot = {"unicode": " · ", "ascii": " . ", "latex": " \\cdot "}[style]
        return dot.join(_fmt(x, style) for x in flatten_seq(t))
    if isinstance(t, IfT):
        return f"IF({_fmt(t.cond, style)}, {_fmt(t.then, style)}, {_fmt(t.orelse, style)})"
    if isinstance(t, WhT):
        return f"WH({_fmt(t.cond, style)}, {_fmt(t.body, style)})"
    if isinstance(t, IdT):
        return "id"
    raise TypeError(f"невідомий терм: {t!r}")


# ------------------------------------------------------------------ JSON
def term_to_dict(t: Term) -> dict:
    if isinstance(t, ConstT):
        return {"term": "const", "value": t.value}
    if isinstance(t, DenomT):
        return {"term": "denom", "var": t.var}
    if isinstance(t, SupT):
        return {"term": "sup", "func": t.func, "args": [term_to_dict(a) for a in t.args]}
    if isinstance(t, AsT):
        return {"term": "assign", "var": t.var, "expr": term_to_dict(t.expr)}
    if isinstance(t, SeqT):
        return {"term": "seq", "left": term_to_dict(t.left), "right": term_to_dict(t.right)}
    if isinstance(t, IfT):
        return {"term": "if", "cond": term_to_dict(t.cond), "then": term_to_dict(t.then), "else": term_to_dict(t.orelse)}
    if isinstance(t, WhT):
        return {"term": "while", "cond": term_to_dict(t.cond), "body": term_to_dict(t.body)}
    if isinstance(t, IdT):
        return {"term": "id"}
    raise TypeError(f"невідомий терм: {t!r}")


def term_from_dict(d: dict) -> Term:
    try:
        kind = d["term"]
        if kind == "const":
            return ConstT(int(d["value"]))
        if kind == "denom":
            return DenomT(str(d["var"]))
        if kind == "sup":
            return SupT(d["func"], tuple(term_from_dict(a) for a in d["args"]))
        if kind == "assign":
            return AsT(d["var"], term_from_dict(d["expr"]))
        if kind == "seq":
            return SeqT(term_from_dict(d["left"]), term_from_dict(d["right"]))
        if kind == "if":
            return IfT(term_from_dict(d["cond"]), term_from_dict(d["then"]), term_from_dict(d["else"]))
        if kind == "while":
            return WhT(term_from_dict(d["cond"]), term_from_dict(d["body"]))
        if kind == "id":
            return IdT()
    except (KeyError, TypeError) as e:
        raise ValueError(f"некоректний JSON терму: {e}") from e
    raise ValueError(f"невідомий вид терму {d.get('term')!r}")
