"""Асистент доведення семантичної коректності циклічних SIPL-програм (SEM-04).

Це АСИСТЕНТ, а не універсальний верифікатор: він перевіряє кроки, які задає студент
(інваріант / формула стану після k ітерацій), і шукає контрприклади.

Режим А — «індукція за k» (як у практичній роботі 3). Студент задає:
  inputs      початковий стан вхідних змінних через параметри (напр. N ↦ n),
  closed_form формулу стану st_k після k ітерацій (напр. N ↦ n−k, S ↦ 3k(k+1)/2),
  iterations  кількість ітерацій K (напр. n),
  pre / post  передумова та післяумова.
Асистент ТОЧНО (многочленами з раціональними коефіцієнтами) перевіряє: базу індукції,
крок індукції, поведінку умови циклу (істинна при k<K, хибна при k=K ⇒ завершення),
післяумову на стані st_K. Клас, де перевірка точна: присвоювання з +, −, ·, умова-порівняння.
Поза цим класом (if у тілі, нелінійні умови) відповідні кроки перевіряються на скінченній області
і позначаються «bounded» — це свідчення, а не доведення.

Режим Б — «інваріант» (Хоар). Студент задає invariant (та variant). Асистент перевіряє
умови: ініціалізація, збереження, післяумова, обмеженість/спадання варіанта — виконуючи
справжні семантичні терми на всіх станах зі скінченної області (bounded) і виводячи контрприклад.

В обох режимах додатково виконується «емпірична» перевірка: програма реально обчислюється
семантичним термом на вхідних станах, що задовольняють pre.
"""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional

from .. import ast as A
from ..analysis import analyze
from . import term as T
from .build import build_bexp_term, build_stm_term
from .evaluate import Undefined, evaluate, eval_condition
from .formula import (
    FormulaError,
    arith_to_poly,
    eval_arith,
    eval_formula,
    format_formula,
    formula_vars,
    parse_arith,
    parse_formula,
    sym_truth,
)
from .poly import NotPolynomial, Poly
from .state import State, format_state

DEFAULT_DOMAIN = 8
GRID_LIMIT = 150_000


class SpecError(Exception):
    """Некоректна специфікація доведення (або програма поза підтримуваним класом)."""


# ------------------------------------------------------------------ специфікація
@dataclass
class ProofSpec:
    name: str = ""
    params: list = field(default_factory=list)
    pre: str = "true"
    post: str = "true"
    inputs: dict = field(default_factory=dict)
    invariant: Optional[str] = None
    variant: Optional[str] = None
    closed_form: dict = field(default_factory=dict)
    iterations: Optional[str] = None
    counter: str = "k"
    loop: int = 0
    domain: int = DEFAULT_DOMAIN
    max_steps: int = 20_000

    @staticmethod
    def from_dict(d: dict) -> "ProofSpec":
        known = {"name", "params", "pre", "post", "inputs", "invariant", "variant", "closed_form", "iterations", "counter", "loop", "domain", "max_steps"}
        unknown = set(d) - known
        if unknown:
            raise SpecError(f"невідомі поля специфікації: {', '.join(sorted(unknown))}")
        spec = ProofSpec(**{k: v for k, v in d.items() if k in known})
        spec.params = list(spec.params or [])
        spec.inputs = dict(spec.inputs or {})
        spec.closed_form = dict(spec.closed_form or {})
        if not spec.invariant and not spec.closed_form:
            raise SpecError("задайте або 'invariant' (режим інваріанта), або 'closed_form' + 'iterations' (режим індукції за k)")
        if spec.closed_form and spec.iterations is None:
            raise SpecError("для 'closed_form' потрібне поле 'iterations' (кількість ітерацій циклу, напр. \"n\")")
        for fname in ("pre", "post", "invariant"):
            val = getattr(spec, fname)
            if val is not None:
                _parse(val, fname, formula=True)
        for fname in ("variant", "iterations"):
            val = getattr(spec, fname)
            if val is not None:
                _parse(val, fname, formula=False)
        for var, expr in {**spec.inputs, **spec.closed_form}.items():
            _parse(expr, f"вираз для {var}", formula=False)
        return spec


def _parse(text: str, what: str, formula: bool):
    try:
        return parse_formula(text) if formula else parse_arith(text)
    except FormulaError as e:
        pos = f" (позиція {e.pos})" if e.pos is not None else ""
        raise SpecError(f"поле '{what}': {e.message}{pos} у виразі {text!r}") from None


# ------------------------------------------------------------------ звіт
@dataclass
class ProofStep:
    id: str
    title: str
    kind: str  # exact | bounded | empirical | info
    status: str  # ok | fail | unknown
    lines: list = field(default_factory=list)
    counterexample: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "status": self.status,
            "details": self.lines,
            "counterexample": self.counterexample,
        }


@dataclass
class ProofReport:
    name: str
    mode: str
    steps: list
    verdict: str  # proved | bounded | refuted
    assumptions: list = field(default_factory=list)
    limits: list = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return {"proved": 0, "refuted": 4, "bounded": 5}[self.verdict]

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "name": self.name,
            "mode": self.mode,
            "verdict": self.verdict,
            "assumptions": self.assumptions,
            "limits": self.limits,
            "steps": [s.to_dict() for s in self.steps],
        }


_VERDICT_UA = {
    "proved": "ДОВЕДЕНО символьно (для всіх значень параметрів у підтримуваному класі)",
    "bounded": "ПЕРЕВІРЕНО на обмеженій області — контрприкладів немає, але це не доведення для всіх вхідних даних",
    "refuted": "СПРОСТОВАНО: знайдено контрприклад",
}
_KIND_UA = {"exact": "точно", "bounded": "обмежена область", "empirical": "запуск програми", "info": "інформація"}
_STATUS_UA = {"ok": "ВИКОНУЄТЬСЯ", "fail": "ПОРУШЕНО", "unknown": "НЕ ВДАЛОСЬ ВСТАНОВИТИ"}


def format_report(report: ProofReport) -> str:
    out = [f"Доведення коректності: {report.name or '(без назви)'}", f"Режим: {report.mode}", ""]
    for s in report.steps:
        out.append(f"[{s.id}] {s.title} — {_STATUS_UA[s.status]} ({_KIND_UA[s.kind]})")
        out.extend(f"      {line}" for line in s.lines)
        if s.counterexample:
            out.append(f"      контрприклад: {json.dumps(s.counterexample, ensure_ascii=False)}")
        out.append("")
    if report.assumptions:
        out.append("Припущення:")
        out.extend(f"  • {a}" for a in report.assumptions)
    out.append("Межі асистента:")
    out.extend(f"  • {l}" for l in report.limits)
    out.append("")
    out.append(f"ВИСНОВОК: {_VERDICT_UA[report.verdict]}")
    return "\n".join(out)


# ------------------------------------------------------------------ допоміжне
def _flatten(stm: A.Node) -> list:
    if isinstance(stm, A.Seq):
        return _flatten(stm.left) + _flatten(stm.right)
    if isinstance(stm, A.Block):
        return _flatten(stm.body)
    return [stm]


def _seq_term(stmts: list) -> T.Term:
    if not stmts:
        return T.IdT()
    term = build_stm_term(stmts[0])
    for s in stmts[1:]:
        term = T.SeqT(term, build_stm_term(s))
    return term


def _choose_domain(n_names: int, requested: int) -> int:
    r = max(1, requested)
    while r > 1 and (r + 1) ** n_names > GRID_LIMIT:
        r -= 1
    return r


def _grid(names: list, r: int):
    for values in itertools.product(range(r + 1), repeat=len(names)):
        yield dict(zip(names, values))


def _fmt_env(env: dict) -> dict:
    return {k: (int(v) if isinstance(v, Fraction) and v.denominator == 1 else str(v) if isinstance(v, Fraction) else v) for k, v in env.items()}


def _unwrap_bexp(b: A.Node) -> A.Node:
    while isinstance(b, A.ParenB):
        b = b.inner
    return b


def _unwrap_aexp(a: A.Node) -> A.Node:
    while isinstance(a, A.ParenA):
        a = a.inner
    return a


class _Unsupported(Exception):
    pass


def _aexp_poly(a: A.Node, env: dict) -> Poly:
    a = _unwrap_aexp(a)
    if isinstance(a, A.Num):
        return Poly.const(a.value)
    if isinstance(a, A.Var):
        if a.name not in env:
            raise _Unsupported(f"змінна {a.name} не має значення в символьному стані")
        return env[a.name]
    if isinstance(a, A.BinOp):
        l, r = _aexp_poly(a.left, env), _aexp_poly(a.right, env)
        return l + r if a.op == "+" else l - r if a.op == "-" else l * r
    raise _Unsupported("невідомий вираз")


def _sym_exec(stmts: list, env: dict) -> list:
    """Символьне виконання присвоювань. Повертає стани після кожного оператора."""
    states = []
    cur = dict(env)
    for s in stmts:
        if not isinstance(s, A.Assign):
            raise _Unsupported(f"оператор '{s.kind}' (символьно підтримуються лише присвоювання)")
        cur = {**cur, s.target.name: _aexp_poly(s.expr, cur)}
        states.append(cur)
    return states


def _fmt_poly_state(env: dict, order: Optional[list] = None) -> str:
    keys = order or list(env)
    return "[" + ", ".join(f"{k} ↦ {env[k]}" for k in keys if k in env) + "]"


# ------------------------------------------------------------------ основна функція
def prove(program: A.Program, spec: ProofSpec) -> ProofReport:
    analysis = analyze(program)
    stmts = _flatten(program.body)
    loops = [i for i, s in enumerate(stmts) if isinstance(s, A.While)]
    if not loops:
        raise SpecError("у програмі немає циклу верхнього рівня (while) — доводити нічого")
    if spec.loop >= len(loops):
        raise SpecError(f"loop={spec.loop}, але циклів верхнього рівня лише {len(loops)}")
    li = loops[spec.loop]
    init, loop, after = stmts[:li], stmts[li], stmts[li + 1 :]
    if any(isinstance(n, A.While) for n in loop.body.walk()):
        raise SpecError("тіло циклу містить вкладений цикл: асистент підтримує прості (невкладені) цикли")

    ctx = _Ctx(program, spec, analysis, init, loop, after)
    steps: list[ProofStep] = []
    if spec.closed_form:
        mode = "індукція за кількістю ітерацій (closed_form)"
        steps.extend(_induction_mode(ctx))
    if spec.invariant:
        mode = "інваріант циклу (Хоар)" if not spec.closed_form else "індукція за k + інваріант"
        steps.extend(_invariant_mode(ctx))
    steps.append(_empirical(ctx))

    if any(s.status == "fail" for s in steps):
        verdict = "refuted"
    elif spec.closed_form and all(s.status == "ok" and s.kind in ("exact", "info") for s in steps if s.id.startswith("A")):
        # символьне доведення (кроки A*) повне; кроки B* та E — додаткові свідчення
        verdict = "proved"
    else:
        verdict = "bounded"
    assumptions = list(ctx.assumptions)
    limits = [
        "Асистент перевіряє ЗАДАНІ студентом інваріант/формулу стану; сам їх не вигадує.",
        f"Перевірки «обмежена область» охоплюють значення 0..{ctx.R_note} змінних і параметрів; вони можуть знайти контрприклад, але не доводять твердження для всіх n.",
        "Точна символьна перевірка діє для присвоювань із +, −, ·, ділення на сталу та умови-порівняння (=, >).",
        "Вкладені цикли та нелінійна поведінка умови виходять за межі підтримуваного класу.",
    ]
    return ProofReport(spec.name, mode, steps, verdict, assumptions, limits)


@dataclass
class _Ctx:
    program: A.Program
    spec: ProofSpec
    analysis: object
    init: list
    loop: A.While
    after: list
    assumptions: list = field(default_factory=list)
    R_note: int = 0

    def __post_init__(self):
        self.pre = parse_formula(self.spec.pre)
        self.post = parse_formula(self.spec.post)
        self.cond_term = build_bexp_term(self.loop.cond)
        self.body_term = build_stm_term(self.loop.body)
        self.init_term = _seq_term(self.init)
        self.after_term = _seq_term(self.after)
        self.inputs = self.analysis.inputs
        self.allvars = self.analysis.variables
        self.R_note = self.spec.domain

    def run(self, term: T.Term, st: State):
        r = evaluate(term, st, max_steps=self.spec.max_steps, trace=False)
        return r

    def env(self, st: dict, params: dict) -> dict:
        return {**params, **st}


def _split_env(ctx: _Ctx, env: dict):
    params = {p: env[p] for p in ctx.spec.params}
    state = {v: env[v] for v in env if v not in ctx.spec.params}
    return params, state


# ------------------------------------------------------------------ режим А
def _induction_mode(ctx: _Ctx) -> list:
    spec = ctx.spec
    steps: list[ProofStep] = []
    k = spec.counter
    params_poly = {p: Poly.var(p) for p in spec.params}
    kvar = Poly.var(k)
    order = list(spec.closed_form)

    try:
        cf = {v: arith_to_poly(parse_arith(e), {}) for v, e in spec.closed_form.items()}
        K = arith_to_poly(parse_arith(spec.iterations), {})
    except NotPolynomial as e:
        return [ProofStep("A0", "Формула стану", "info", "unknown", [f"формула виходить за межі многочленів: {e}"])]

    # ---- A0: початковий стан
    inputs = dict(spec.inputs)
    if not inputs:
        inputs = _infer_inputs(ctx)
    missing = [v for v in ctx.inputs if v not in inputs]
    if missing:
        return [ProofStep("A0", "Початковий стан", "info", "unknown",
                          [f"не задано початкові значення вхідних змінних: {', '.join(missing)}. Додайте поле \"inputs\", напр. {{\"{missing[0]}\": \"n\"}}"])]
    env0 = {v: arith_to_poly(parse_arith(e), {}) for v, e in inputs.items()}
    steps.append(ProofStep("A0", "Початковий стан st", "info", "ok", [f"st = {_fmt_poly_state(env0)};  передумова: {spec.pre}"]))

    # ---- A1: ініціалізація
    try:
        init_states = _sym_exec(ctx.init, env0)
        st0 = init_states[-1] if init_states else env0
        lines = []
        prev = env0
        for i, (s, cur) in enumerate(zip(ctx.init, init_states)):
            lines.append(f"після '{_short(s)}': {_fmt_poly_state(cur)}")
        lines.append(f"отже st₀ = {_fmt_poly_state(st0, order)}")
        steps.append(ProofStep("A1", "Ініціалізація (початкові присвоювання)", "exact", "ok", lines))
    except _Unsupported as e:
        return steps + [ProofStep("A1", "Ініціалізація", "bounded", "unknown", [f"символьно не вдалось: {e}"])]

    # ---- A2: база індукції
    base_lines, base_ok, cx = [], True, None
    for v in order:
        want = cf[v].subst({k: Poly.const(0)})
        got = st0.get(v)
        if got is None:
            base_ok = False
            base_lines.append(f"змінна {v} описана у формулі, але не має значення в st₀")
        elif got == want:
            base_lines.append(f"{v}: st₀({v}) = {got} = формула при k=0 ✓")
        else:
            base_ok = False
            base_lines.append(f"{v}: st₀({v}) = {got}, а формула при k=0 дає {want} ✗")
            cx = cx or _poly_cx(got - want, spec, k, {k: 0})
    for v in st0:
        if v not in cf:
            base_lines.append(f"увага: змінна {v} є в st₀, але не описана у closed_form")
    steps.append(ProofStep("A2", "База індукції (k = 0)", "exact", "ok" if base_ok else "fail", base_lines, cx))

    # ---- A3: крок індукції
    body_stmts = _flatten(ctx.loop.body)
    try:
        symb = _sym_exec(body_stmts, cf)
        final = symb[-1] if symb else cf
        lines = [f"припустимо, st_k = {_fmt_poly_state(cf, order)}"]
        for i, (s, cur) in enumerate(zip(body_stmts, symb), start=1):
            lines.append(f"st_k^{i} після '{_short(s)}': {_fmt_poly_state(cur, order)}")
        step_ok, cx = True, None
        nxt = {v: cf[v].subst({k: kvar + Poly.const(1)}) for v in order}
        for v in order:
            got = final.get(v)
            if got == nxt[v]:
                lines.append(f"{v}: {got} = формула при k+1 ✓")
            else:
                step_ok = False
                lines.append(f"{v}: після тіла {got}, а формула при k+1 дає {nxt[v]} ✗")
                if got is not None:
                    cx = cx or _poly_cx(got - nxt[v], spec, k, {})
        steps.append(ProofStep("A3", "Крок індукції (k → k+1)", "exact", "ok" if step_ok else "fail", lines, cx))
    except _Unsupported as e:
        steps.append(ProofStep("A3", "Крок індукції (k → k+1)", "bounded", "unknown", [f"символьно не вдалось: {e}", "перевірте крок на обмеженій області (див. емпіричну перевірку)"]))

    # ---- A4: поведінка умови циклу, завершення
    steps.append(_loop_condition_step(ctx, cf, K, k))

    # ---- A5: післяумова
    steps.append(_post_step(ctx, cf, K, k, order))
    # ---- A6: застосовність (припущення про параметри)
    _pre_assumptions(ctx)
    return steps


def _short(stmt: A.Node) -> str:
    from ..unparse import unparse

    return unparse(stmt)


def _infer_inputs(ctx: _Ctx) -> dict:
    """Початкові значення вхідних змінних з рівностей виду `N = n` у передумові."""
    out: dict = {}

    def conjuncts(f):
        if f[0] == "and":
            return conjuncts(f[1]) + conjuncts(f[2])
        return [f]

    for c in conjuncts(ctx.pre):
        if c[0] == "cmp" and c[1] == "=":
            for a, b in ((c[2], c[3]), (c[3], c[2])):
                if a[0] == "var" and a[1] in ctx.inputs and a[1] not in out and not (formula_vars(b) & set(ctx.inputs)):
                    out[a[1]] = _expr_text(b)
                    break
    return out


def _expr_text(e) -> str:
    return format_formula(e)


def _poly_cx(diff: Poly, spec: ProofSpec, k: str, fixed: dict) -> Optional[dict]:
    names = [p for p in spec.params] + ([k] if k not in fixed else [])
    r = min(spec.domain, 6)
    for env in _grid(names, r):
        full = {**env, **fixed}
        if diff.evaluate(full) != 0:
            return {"значення": _fmt_env(full), "різниця (після тіла − формула)": str(diff.evaluate(full))}
    return None


def _loop_condition_step(ctx: _Ctx, cf: dict, K: Poly, k: str) -> ProofStep:
    spec = ctx.spec
    cond = _unwrap_bexp(ctx.loop.cond)
    title = "Умова циклу та завершення"
    if not isinstance(cond, A.Compare):
        return _loop_condition_bounded(ctx, cf, K, k, title, "умова не є простим порівнянням")
    try:
        d = _aexp_poly(cond.left, cf) - _aexp_poly(cond.right, cf)
    except _Unsupported as e:
        return _loop_condition_bounded(ctx, cf, K, k, title, str(e))
    from ..unparse import unparse

    lines = [f"умова циклу {unparse(cond)} на st_k: {unparse(cond.left)} − ({unparse(cond.right)}) = {d}"]
    at_K = d.subst({k: K})
    status, kind = "ok", "exact"
    if cond.op == ">":
        lines.append(f"при k = {spec.iterations}: {at_K} ≤ 0 ?")
        if at_K.is_const() and at_K.const_value() <= 0:
            lines.append(f"так: {at_K} ≤ 0, тож умова ХИБНА на st_{{{spec.iterations}}} — цикл зупиняється")
            stops = True
        else:
            stops = False
            lines.append("не вдалось довести, що умова хибна при k = K")
        j = "j"
        dj = d.subst({k: K - Poly.const(1) - Poly.var(j)})
        nonneg = dj.terms and all(c >= 0 for m, c in dj.terms.items() if m != ()) and dj.const_value() > 0
        lines.append(f"при k = {spec.iterations} − 1 − j (j ≥ 0): {dj}")
        if nonneg:
            lines.append("усі коефіцієнти невід'ємні, вільний член > 0 ⇒ умова ІСТИННА для всіх 0 ≤ k < K (параметри невід'ємні)")
            runs = True
        else:
            runs = False
            lines.append("не вдалось довести істинність умови для всіх k < K")
        if stops and runs:
            lines.append(f"висновок: цикл виконає рівно {spec.iterations} ітерацій і завершиться (повна коректність: завершуваність)")
            ctx.assumptions.append("усі параметри — невід'ємні цілі числа (використано при перевірці знаків коефіцієнтів)")
            return ProofStep("A4", title, "exact", "ok", lines)
        st, kd = _bounded_loop_numeric(ctx, d, K, k, cond.op)
        lines.extend(kd["lines"])
        return ProofStep("A4", title, "bounded", st, lines, kd.get("cx"))
    # '=' : лише обмежена область
    return _loop_condition_bounded(ctx, cf, K, k, title, "для умови '=' символьний аналіз не реалізовано")


def _bounded_loop_numeric(ctx: _Ctx, d: Poly, K: Poly, k: str, op: str):
    spec = ctx.spec
    r = _choose_domain(len(spec.params), spec.domain)
    checked, lines = 0, []
    for env in _grid(list(spec.params), r):
        if not _pre_holds(ctx, _full_env(ctx, env)):
            continue
        kk = int(K.evaluate(env)) if K.evaluate(env).denominator == 1 else None
        if kk is None or kk < 0:
            return "fail", {"lines": [f"кількість ітерацій K не є невід'ємним цілим при {env}"], "cx": _fmt_env(env)}
        for t in range(0, kk + 1):
            val = d.evaluate({**env, k: t})
            truth = val > 0 if op == ">" else val == 0
            checked += 1
            if truth != (t < kk):
                return "fail", {
                    "lines": [f"умова при k={t} має значення {truth}, а очікувалось {t < kk}"],
                    "cx": _fmt_env({**env, k: t}),
                }
    return ("ok" if checked else "unknown"), {"lines": [f"перевірено {checked} пар (параметри, k) на області 0..{r}: умова істинна при k<K і хибна при k=K"]}


def _loop_condition_bounded(ctx, cf, K, k, title, why) -> ProofStep:
    # чисельно: для кожного значення параметрів обчислюємо cf(k) і умову циклу через семантичний терм
    spec = ctx.spec
    r = _choose_domain(len(spec.params), spec.domain)
    lines = [f"символьний аналіз неможливий ({why}); перевірка на області 0..{r}"]
    checked = 0
    for env in _grid(list(spec.params), r):
        try:
            if not _pre_holds(ctx, _full_env(ctx, env)):
                continue
            kk = K.evaluate(env)
            if kk.denominator != 1 or kk < 0:
                return ProofStep("A4", title, "bounded", "fail", lines + ["K не є невід'ємним цілим"], _fmt_env(env))
            for t in range(0, int(kk) + 1):
                st = {v: int(p.evaluate({**env, k: t})) for v, p in cf.items()}
                truth = eval_condition(ctx.cond_term, st)
                checked += 1
                if truth != (t < kk):
                    return ProofStep("A4", title, "bounded", "fail", lines + [f"при k={t} умова = {truth}, очікувалось {t < kk}"], _fmt_env({**env, k: t}))
        except Undefined as u:
            return ProofStep("A4", title, "bounded", "unknown", lines + [u.message])
    lines.append(f"перевірено {checked} пар (параметри, k)")
    return ProofStep("A4", title, "bounded", "ok" if checked else "unknown", lines)


def _full_env(ctx: _Ctx, penv: dict) -> dict:
    """Параметри + початкові значення вхідних змінних (з inputs або з pre)."""
    env = dict(penv)
    for v, poly in _inputs_poly(ctx).items():
        env[v] = poly.evaluate(penv)
    return env


def _pre_holds(ctx: _Ctx, env: dict) -> bool:
    try:
        return eval_formula(ctx.pre, env)
    except FormulaError:
        return False


def _post_step(ctx: _Ctx, cf: dict, K: Poly, k: str, order: list) -> ProofStep:
    spec = ctx.spec
    title = "Післяумова на кінцевому стані st_K"
    stK = {v: cf[v].subst({k: K}) for v in cf}
    lines = [f"st_{spec.iterations} = {_fmt_poly_state(stK, order)}"]
    try:
        final_states = _sym_exec(ctx.after, stK)
        fin = final_states[-1] if final_states else stK
        if ctx.after:
            lines.append(f"після завершальних присвоювань: {_fmt_poly_state(fin)}")
        env = {**fin, **{p: Poly.var(p) for p in spec.params}}
        truth = sym_truth(ctx.post, env)
    except (_Unsupported, NotPolynomial) as e:
        truth, fin = None, None
        lines.append(f"символьно не вдалось: {e}")
    lines.append(f"післяумова: {spec.post}")
    if truth is True:
        lines.append("після підстановки обидві частини співпадають як многочлени ✓")
        return ProofStep("A5", title, "exact", "ok", lines)
    # чисельна перевірка на області
    r = _choose_domain(len(spec.params), spec.domain)
    checked = 0
    for env in _grid(list(spec.params), r):
        if not _pre_holds(ctx, _full_env(ctx, env)):
            continue
        kk = K.evaluate(env)
        if kk.denominator != 1 or kk < 0:
            continue
        st = {v: p.evaluate({**env, k: kk}) for v, p in cf.items()}
        st = {v: int(x) if x.denominator == 1 else x for v, x in st.items()}
        checked += 1
        if ctx.after:
            res = ctx.run(ctx.after_term, State({v: x for v, x in st.items()}))
            if not res.defined:
                return ProofStep("A5", title, "bounded", "fail", lines + [res.error_message], _fmt_env(env))
            st = res.state.to_dict()
        if not eval_formula(ctx.post, {**env, **st}):
            return ProofStep("A5", title, "bounded", "fail", lines + ["післяумова хибна"], {"параметри": _fmt_env(env), "кінцевий стан": _fmt_env(st)})
    lines.append(f"символьно тотожність не встановлено; чисельно перевірено {checked} значень параметрів на області 0..{r}")
    return ProofStep("A5", title, "bounded", "ok" if checked else "unknown", lines)


def _inputs_poly(ctx: _Ctx) -> dict:
    inputs = dict(ctx.spec.inputs) or _infer_inputs(ctx)
    return {v: arith_to_poly(parse_arith(e), {}) for v, e in inputs.items()}


def _pre_assumptions(ctx: _Ctx) -> None:
    """Попереджає, якщо pre не гарантує невід'ємності параметрів (доведення це припускає)."""
    spec = ctx.spec
    for p in spec.params:
        others = [q for q in spec.params if q != p]
        for val in (-1, -2, -3):
            env = {p: val, **{q: 1 for q in others}}
            for v, poly in _inputs_poly(ctx).items():
                env[v] = poly.evaluate(env)
            if _pre_holds(ctx, env):
                ctx.assumptions.append(f"передумова не забороняє {p} < 0 (напр. {p} = {val}); доведення припускає {p} ≥ 0")
                break


# ------------------------------------------------------------------ режим Б
def _invariant_mode(ctx: _Ctx) -> list:
    spec = ctx.spec
    inv = parse_formula(spec.invariant)
    variant = parse_arith(spec.variant) if spec.variant else None
    steps: list[ProofStep] = []
    params = list(spec.params)
    allvars = ctx.allvars

    def inv_true(env) -> Optional[bool]:
        try:
            return eval_formula(inv, env)
        except FormulaError as e:
            raise SpecError(f"інваріант: {e.message}") from None

    # --- B1: ініціалізація
    r1 = _choose_domain(len(ctx.inputs) + len(params), spec.domain)
    names = list(dict.fromkeys(ctx.inputs + params))
    n_ok = 0
    step = ProofStep("B1", "Ініціалізація: pre ⇒ інваріант після початкових присвоювань", "bounded", "unknown")
    for env in _grid(names, r1):
        if not _pre_holds(ctx, env):
            continue
        st = State({v: env[v] for v in ctx.inputs})
        res = ctx.run(ctx.init_term, st)
        if not res.defined:
            step.status, step.lines, step.counterexample = "fail", [res.error_message], _fmt_env(env)
            break
        env0 = {**{p: env[p] for p in params}, **res.state.to_dict()}
        n_ok += 1
        if not inv_true(env0):
            step.status = "fail"
            step.lines = [f"після ініціалізації стан {format_state(res.state)} не задовольняє інваріант"]
            step.counterexample = {"параметри": _fmt_env({p: env[p] for p in params}), "стан після ініціалізації": res.state.to_dict()}
            break
    else:
        step.status = "ok" if n_ok else "unknown"
        step.lines = [f"перевірено {n_ok} початкових станів (область 0..{r1})" if n_ok else "жоден стан області не задовольняє pre"]
    steps.append(step)

    # --- B2..B5: на всіх станах області
    r2 = _choose_domain(len(allvars) + len(params), spec.domain)
    ctx.R_note = min(ctx.R_note, r2) if ctx.R_note else r2
    names2 = list(dict.fromkeys(allvars + params))
    s2 = ProofStep("B2", "Збереження інваріанта: I ∧ b ⇒ I після тіла циклу", "bounded", "unknown")
    s3 = ProofStep("B3", "Післяумова: I ∧ ¬b ⇒ post після завершальних операторів", "bounded", "unknown")
    s4 = ProofStep("B4", "Змінна циклу невід'ємна: I ⇒ V ≥ 0", "bounded", "unknown")
    s5 = ProofStep("B5", "Змінна циклу спадає: I ∧ b ⇒ V(після тіла) < V", "bounded", "unknown")
    cnt = {"B2": 0, "B3": 0, "B4": 0, "B5": 0}
    fail: dict[str, bool] = {}
    for env in _grid(names2, r2):
        st_d = {v: env[v] for v in allvars}
        if not inv_true(env):
            continue
        st = State(st_d)
        penv = {p: env[p] for p in params}
        if variant is not None and "B4" not in fail:
            cnt["B4"] += 1
            if eval_arith(variant, env) < 0:
                fail["B4"] = True
                s4.status, s4.lines = "fail", [f"V = {eval_arith(variant, env)} < 0 на стані, що задовольняє інваріант"]
                s4.counterexample = _fmt_env(env)
        try:
            b = eval_condition(ctx.cond_term, st)
        except Undefined as u:
            continue
        if b and "B2" not in fail:
            res = ctx.run(ctx.body_term, st)
            if not res.defined:
                fail["B2"] = True
                s2.status, s2.lines, s2.counterexample = "fail", [f"тіло циклу не визначене: {res.error_message}"], _fmt_env(env)
            else:
                cnt["B2"] += 1
                env2 = {**penv, **res.state.to_dict()}
                if not inv_true(env2):
                    fail["B2"] = True
                    s2.status = "fail"
                    s2.lines = [f"інваріант виконується до тіла, але не після: {format_state(st)} → {format_state(res.state)}"]
                    s2.counterexample = {"стан до": _fmt_env(env), "стан після тіла": res.state.to_dict()}
                if variant is not None and "B5" not in fail:
                    cnt["B5"] += 1
                    if not (eval_arith(variant, env2) < eval_arith(variant, env)):
                        fail["B5"] = True
                        s5.status = "fail"
                        s5.lines = [f"V не зменшується: {eval_arith(variant, env)} → {eval_arith(variant, env2)}"]
                        s5.counterexample = {"стан до": _fmt_env(env), "стан після тіла": res.state.to_dict()}
        if not b and "B3" not in fail:
            res = ctx.run(ctx.after_term, st)
            if not res.defined:
                fail["B3"] = True
                s3.status, s3.lines, s3.counterexample = "fail", [res.error_message], _fmt_env(env)
            else:
                cnt["B3"] += 1
                if not eval_formula(ctx.post, {**penv, **res.state.to_dict()}):
                    fail["B3"] = True
                    s3.status = "fail"
                    s3.lines = [f"на виході з циклу післяумова хибна: стан {format_state(res.state)}"]
                    s3.counterexample = {"стан на виході з циклу": _fmt_env(env), "кінцевий стан": res.state.to_dict()}
    for s, key in ((s2, "B2"), (s3, "B3"), (s4, "B4"), (s5, "B5")):
        if s.status == "unknown" and cnt[key]:
            s.status = "ok"
            s.lines = [f"перевірено {cnt[key]} станів області 0..{r2}, що задовольняють умови"]
        elif s.status == "unknown":
            s.lines = [f"на області 0..{r2} немає станів, що задовольняють умови цієї перевірки"]
    steps.extend([s2, s3])
    if variant is not None:
        steps.extend([s4, s5])
    else:
        steps.append(ProofStep("B4", "Завершуваність", "info", "unknown", ["variant не задано: завершуваність перевіряється лише запуском (див. емпіричну перевірку)"]))
    return steps


# ------------------------------------------------------------------ емпірична перевірка
def _empirical(ctx: _Ctx) -> ProofStep:
    """Виконує справжній семантичний терм на вхідних станах, що задовольняють pre."""
    spec = ctx.spec
    names = list(dict.fromkeys(ctx.inputs + spec.params))
    r = _choose_domain(len(names), spec.domain)
    inv = parse_formula(spec.invariant) if spec.invariant else None
    cf = {v: arith_to_poly(parse_arith(e), {}) for v, e in spec.closed_form.items()} if spec.closed_form else {}
    K = arith_to_poly(parse_arith(spec.iterations), {}) if spec.iterations else None
    full_term = build_stm_term(ctx.program.body)
    from .term import format_term

    cond_text = format_term(ctx.cond_term)
    step = ProofStep("E", "Емпірична перевірка: запуск програми на вхідних станах", "empirical", "unknown")
    runs = 0
    for env in _grid(names, r):
        if not _pre_holds(ctx, env):
            continue
        st0 = State({v: env[v] for v in ctx.inputs})
        res = evaluate(full_term, st0, max_steps=spec.max_steps, trace=True, trace_limit=spec.max_steps)
        runs += 1
        penv = {p: env[p] for p in spec.params}
        if not res.defined:
            step.status = "fail"
            step.lines = [f"програма не завершилась коректно: {res.error_message}"]
            step.counterexample = {"вхід": _fmt_env(env)}
            return step
        heads = [e for e in res.events if e.rule == "AF_WH" and e.term == cond_text and e.loop_head is not None]
        for e in heads:
            kk = e.loop_head
            if inv is not None and not eval_formula(inv, {**penv, **e.before}):
                step.status = "fail"
                step.lines = [f"інваріант хибний на початку ітерації {kk}: {format_state(e.before)}"]
                step.counterexample = {"вхід": _fmt_env(env), "стан st_k": e.before, "k": kk}
                return step
            for v, p in cf.items():
                want = p.evaluate({**penv, ctx.spec.counter: kk})
                if v not in e.before or Fraction(e.before[v]) != want:
                    step.status = "fail"
                    step.lines = [f"формула st_k для {v} не збігається з реальним станом при k={kk}: формула дає {want}, програма — {e.before.get(v)}"]
                    step.counterexample = {"вхід": _fmt_env(env), "стан st_k": e.before, "k": kk}
                    return step
        if K is not None:
            expect = K.evaluate(penv)
            actual = max(0, len(heads) - 1)
            if expect != actual:
                step.status = "fail"
                step.lines = [f"кількість ітерацій: формула {expect}, фактично {actual}"]
                step.counterexample = {"вхід": _fmt_env(env)}
                return step
        if not eval_formula(ctx.post, {**penv, **res.state.to_dict()}):
            step.status = "fail"
            step.lines = [f"післяумова хибна на кінцевому стані {format_state(res.state)}"]
            step.counterexample = {"вхід": _fmt_env(env), "кінцевий стан": res.state.to_dict()}
            return step
    if runs:
        what = ["післяумова", "завершення"]
        if inv is not None:
            what.append("інваріант на початку кожної ітерації")
        if cf:
            what.append("формула st_k на початку кожної ітерації")
        step.status = "ok"
        step.lines = [f"програму виконано на {runs} вхідних станах (область 0..{r}); перевірено: {', '.join(what)}"]
    else:
        step.lines = ["жоден вхідний стан області не задовольняє pre"]
    return step
