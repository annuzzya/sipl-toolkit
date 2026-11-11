"""Обчислення (аплікація) семантичного терму на стані (SEM-02).

Формули курсу: AF_S, AF_AS, AF_SEQ, AF_IF, AF_WH, AF_DNM, AF_ID. Результат — або кінцевий
стан, або явна НЕВИЗНАЧЕНІСТЬ ⊥ з причиною (змінна без значення; перевищено ліміт кроків).
Усі кроки записуються в trace (список подій) — його можна вивести текстом або як JSON.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import term as T
from .state import State, format_state

DEFAULT_MAX_STEPS = 100_000
DEFAULT_TRACE_LIMIT = 20_000


class Undefined(Exception):
    """Значення ⊥: терм не визначений на даному стані."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Event:
    index: int
    depth: int
    rule: str  # AF_AS, AF_SEQ, AF_IF, AF_WH, AF_ID
    term: str  # запис терму, до якого застосовано формулу
    before: dict
    after: Optional[dict]
    note: str = ""
    loop_head: Optional[int] = None  # k для подій перевірки умови циклу: стан st_k

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "depth": self.depth,
            "rule": self.rule,
            "term": self.term,
            "before": self.before,
            "after": self.after,
            "note": self.note,
            "loop_head": self.loop_head,
        }


@dataclass
class EvalResult:
    defined: bool
    state: Optional[State]
    steps: int
    events: list = field(default_factory=list)
    trace_truncated: bool = False
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "defined": self.defined,
            "state": self.state.to_dict() if self.state is not None else None,
            "steps": self.steps,
            "trace_truncated": self.trace_truncated,
            "error": None if self.defined else {"code": self.error_code, "message": self.error_message},
            "trace": [e.to_dict() for e in self.events],
        }


class _Evaluator:
    def __init__(self, max_steps: int, record: bool, trace_limit: int):
        self.max_steps = max_steps
        self.record = record
        self.trace_limit = trace_limit
        self.steps = 0
        self.events: list[Event] = []
        self.truncated = False

    def _tick(self) -> None:
        self.steps += 1
        if self.steps > self.max_steps:
            raise Undefined(
                "E-EVAL-LIMIT",
                f"перевищено ліміт кроків ({self.max_steps}): цикл, імовірно, нескінченний — значення терму ⊥ (не визначене)",
            )

    def _emit(self, depth, rule, term, before, after, note="", loop_head=None):
        if not self.record:
            return
        if len(self.events) >= self.trace_limit:
            self.truncated = True
            return
        self.events.append(Event(len(self.events) + 1, depth, rule, term, before.to_dict(), None if after is None else after.to_dict(), note, loop_head))

    # --- арифметика та логіка (терми типу TFA / TFB): повертають значення і «пояснення»
    def value(self, t: T.Term, st: State):
        if isinstance(t, T.ConstT):
            return t.value, f"{T.format_term(t)}(st) = {t.value}"
        if isinstance(t, T.DenomT):
            if t.var not in st:
                raise Undefined("E-EVAL-UNDEF", f"змінна {t.var} не має значення у стані {format_state(st)} (x⇒(st) не визначено)")
            return st[t.var], f"{t.var}⇒(st) = {st[t.var]}"
        if isinstance(t, T.SupT):
            vals, parts = [], []
            for a in t.args:
                v, _ = self.value(a, st)
                vals.append(v)
                parts.append(f"{T.format_term(a)}(st)")
            res = _apply(t.func, vals)
            shown = ", ".join(_show(v) for v in vals)
            expl = f"{t.func}({', '.join(parts)}) = {t.func}({shown}) = {_show(res)}"
            return res, expl
        raise TypeError(f"очікувався терм виразу/умови, отримано {t!r}")

    # --- оператори (терми типу TFS): стан -> стан
    def run(self, t: T.Term, st: State, depth: int = 0) -> State:
        self._tick()
        if isinstance(t, T.IdT):
            self._emit(depth, "AF_ID", "id", st, st, "id(st) = st")
            return st
        if isinstance(t, T.AsT):
            v, expl = self.value(t.expr, st)
            new = st.update(t.var, v)
            self._emit(depth, "AF_AS", T.format_term(t), st, new, f"{expl}; st∇[{t.var} ↦ {v}]")
            return new
        if isinstance(t, T.SeqT):
            self._emit(depth, "AF_SEQ", T.format_term(t), st, None, "f_S1 · f_S2 (st) = f_S2(f_S1(st))")
            mid = self.run(t.left, st, depth + 1)
            return self.run(t.right, mid, depth + 1)
        if isinstance(t, T.IfT):
            b, expl = self.value(t.cond, st)
            branch = t.then if b else t.orelse
            self._emit(depth, "AF_IF", T.format_term(t.cond), st, None, f"{expl}: виконується гілка {'then' if b else 'else'}")
            return self.run(branch, st, depth + 1)
        if isinstance(t, T.WhT):
            k = 0
            cur = st
            while True:
                self._tick()
                b, expl = self.value(t.cond, cur)
                self._emit(depth, "AF_WH", T.format_term(t.cond), cur, None, f"{expl} — " + ("умова істинна, виконуємо тіло" if b else f"умова хибна, цикл завершено, результат st_{k}"), loop_head=k)
                if not b:
                    return cur
                cur = self.run(t.body, cur, depth + 1)
                k += 1
        raise TypeError(f"очікувався терм оператора, отримано {t!r}")


def _show(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _apply(func: str, vals: list):
    if func == "add":
        return vals[0] + vals[1]
    if func == "sub":
        return vals[0] - vals[1]
    if func == "mult":
        return vals[0] * vals[1]
    if func == "gr":
        return vals[0] > vals[1]
    if func == "eq":
        return vals[0] == vals[1]
    if func == "or":
        return vals[0] or vals[1]
    if func == "neg":
        return not vals[0]
    raise ValueError(func)


def evaluate(
    term: T.Term,
    state: dict | State,
    max_steps: int = DEFAULT_MAX_STEPS,
    trace: bool = True,
    trace_limit: int = DEFAULT_TRACE_LIMIT,
) -> EvalResult:
    """term(state). Ніколи не кидає виняток через цикл/невизначеність — повертає EvalResult."""
    st = state if isinstance(state, State) else State(state)
    ev = _Evaluator(max_steps, trace, trace_limit)
    try:
        out = ev.run(term, st)
    except Undefined as u:
        return EvalResult(False, None, ev.steps, ev.events, ev.truncated, u.code, u.message)
    return EvalResult(True, out, ev.steps, ev.events, ev.truncated)


def format_trace(result: EvalResult) -> str:
    """Покрокове пояснення переходів (текст, українською)."""
    lines = []
    for e in result.events:
        pad = "  " * e.depth
        if e.rule == "AF_AS":
            lines.append(f"{pad}[{e.index}] AF_AS  {e.term}")
            lines.append(f"{pad}      {e.note}")
            lines.append(f"{pad}      {format_state_dict(e.before)}  →  {format_state_dict(e.after)}")
        elif e.rule == "AF_WH":
            lines.append(f"{pad}[{e.index}] AF_WH  умова {e.term} на {format_state_dict(e.before)}: {e.note}")
        elif e.rule == "AF_IF":
            lines.append(f"{pad}[{e.index}] AF_IF  умова {e.term} на {format_state_dict(e.before)}: {e.note}")
        elif e.rule == "AF_SEQ":
            lines.append(f"{pad}[{e.index}] AF_SEQ  послідовне виконання на {format_state_dict(e.before)}")
        else:
            lines.append(f"{pad}[{e.index}] {e.rule}  {format_state_dict(e.before)}")
    if result.trace_truncated:
        lines.append("… (trace обрізано: перевищено ліміт подій)")
    if result.defined:
        lines.append(f"Результат: {format_state(result.state)}   (кроків: {result.steps})")
    else:
        lines.append(f"Результат: ⊥ (не визначено) [{result.error_code}]: {result.error_message}")
    return "\n".join(lines)


def format_state_dict(d: Optional[dict]) -> str:
    return "?" if d is None else format_state(d)


def eval_condition(cond: T.Term, state: dict | State) -> bool:
    """Значення умови f_b(st). Кидає Undefined, якщо умова на стані не визначена."""
    st = state if isinstance(state, State) else State(state)
    value, _ = _Evaluator(DEFAULT_MAX_STEPS, False, 0).value(cond, st)
    return bool(value)
