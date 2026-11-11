"""Командний рядок: sipl parse | check | tree | term | eval | prove.

Коди завершення:
  0  успіх
  1  синтаксична помилка / помилка діагностики вхідної програми
  2  помилка використання, вводу-виводу або специфікації
  3  значення терму не визначене (⊥): змінна без значення або перевищено ліміт кроків
  4  доведення спростовано (знайдено контрприклад)
  5  доведення не повне: перевірено лише на обмеженій області (контрприкладів немає)
Прапорець --json у кожній команді вмикає стабільний машинозчитуваний вивід (schema_version = 1).
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from . import __version__
from .analysis import analyze
from .errors import Diagnostic, SiplError, render_diagnostic
from .parser import parse_source
from .semantics.build import build_term, build_term_with_trace
from .semantics.evaluate import DEFAULT_MAX_STEPS, evaluate, format_trace
from .semantics.proof import ProofSpec, SpecError, format_report, prove
from .semantics.state import State, parse_state
from .semantics.term import format_term, term_from_dict, term_to_dict
from .spans import SourceText
from .unparse import sexpr, unparse
from .visualization import build_parse_tree, to_dict as tree_to_dict, to_dot, to_html, to_svg, to_text

EXIT_OK, EXIT_SYNTAX, EXIT_USAGE, EXIT_UNDEFINED, EXIT_REFUTED, EXIT_BOUNDED = 0, 1, 2, 3, 4, 5


class _UsageError(Exception):
    pass


def _read(path: str) -> SourceText:
    try:
        if path == "-":
            return SourceText(sys.stdin.read(), "<stdin>")
        with open(path, encoding="utf-8") as f:
            return SourceText(f.read(), path)
    except OSError as e:
        raise _UsageError(f"не вдалося прочитати '{path}': {e.strerror or e}") from None


def _emit_json(obj: dict) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _load_program(args, command: str):
    """Розібрати програму. Повертає (source, program) або (source, None) після виводу діагностики."""
    source = _read(args.file)
    try:
        return source, parse_source(source, seq_assoc=args.seq_assoc)
    except SiplError as e:
        if args.json:
            _emit_json({"schema_version": 1, "command": command, "ok": False, "diagnostics": [e.diagnostic.to_dict()]})
        else:
            print(render_diagnostic(e.diagnostic, source), file=sys.stderr)
        return source, None


# ----------------------------------------------------------------- команди
def cmd_parse(args) -> int:
    source, prog = _load_program(args, "parse")
    if prog is None:
        return EXIT_SYNTAX
    if args.json:
        _emit_json({"schema_version": 1, "command": "parse", "ok": True, "file": source.name, "ast": prog.to_dict()})
    else:
        print(sexpr(prog))
    return EXIT_OK


def cmd_check(args) -> int:
    source, prog = _load_program(args, "check")
    if prog is None:
        return EXIT_SYNTAX
    a = analyze(prog)
    if args.json:
        _emit_json({"schema_version": 1, "command": "check", "ok": True, "file": source.name, **a.to_dict()})
    else:
        print(f"{source.name}: синтаксис коректний")
        print(f"  змінні: {', '.join(a.variables) or '—'}")
        print(f"  вхідні змінні (їх значення задають у початковому стані): {', '.join(a.inputs) or '—'}")
        for d in a.diagnostics:
            print(render_diagnostic(d, source))
    return EXIT_OK


def cmd_tree(args) -> int:
    source, prog = _load_program(args, "tree")
    if prog is None:
        return EXIT_SYNTAX
    root = build_parse_tree(prog)
    ua = args.labels == "ua"
    fmt = args.format
    if fmt == "json":
        out = json.dumps({"command": "tree", "ok": True, **tree_to_dict(root, source, ua)}, ensure_ascii=False, indent=2)
    elif fmt == "dot":
        out = to_dot(root, source, ua)
    elif fmt == "svg":
        out = to_svg(root, source, ua)
    elif fmt == "html":
        out = to_html(root, source, ua)
    else:
        out = to_text(root, source, ua)
    _write_output(out, args.output)
    return EXIT_OK


def _write_output(text: str, path: Optional[str]) -> None:
    if path:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text + ("\n" if not text.endswith("\n") else ""))
        except OSError as e:
            raise _UsageError(f"не вдалося записати '{path}': {e.strerror or e}") from None
        print(f"записано: {path}", file=sys.stderr)
    else:
        print(text)


def cmd_term(args) -> int:
    source, prog = _load_program(args, "term")
    if prog is None:
        return EXIT_SYNTAX
    term, steps = build_term_with_trace(prog)
    if args.json:
        _emit_json(
            {
                "schema_version": 1,
                "command": "term",
                "ok": True,
                "term": format_term(term, args.style),
                "term_tree": term_to_dict(term),
                "rewrite_steps": [s.to_dict() for s in steps] if args.explain else None,
            }
        )
        return EXIT_OK
    if args.explain:
        print("Послідовність застосованих правил (зверху вниз):")
        for i, s in enumerate(steps, 1):
            print(f"{i:>3}. {s}")
        print()
        print("Семантичний терм:")
    print(format_term(term, args.style))
    return EXIT_OK


def cmd_eval(args) -> int:
    if args.term:
        try:
            with open(args.term, encoding="utf-8") as f:
                term = term_from_dict(json.load(f))
        except (OSError, ValueError) as e:
            raise _UsageError(f"терм з '{args.term}': {e}") from None
        source = None
    else:
        if not args.file:
            raise _UsageError("вкажіть файл програми або --term файл.json")
        source, prog = _load_program(args, "eval")
        if prog is None:
            return EXIT_SYNTAX
        term = build_term(prog)
    try:
        state = parse_state(args.state)
    except ValueError as e:
        raise _UsageError(f"--state: {e}") from None
    result = evaluate(term, state, max_steps=args.max_steps, trace=args.trace or args.json)
    if args.json:
        out = {"schema_version": 1, "command": "eval", "ok": result.defined, "initial_state": state.to_dict(), **result.to_dict()}
        if not args.trace:
            out["trace"] = None
        _emit_json(out)
    else:
        print(f"Терм: {format_term(term)}")
        print(f"Початковий стан: {state}")
        if args.trace:
            print()
            print(format_trace(result))
        elif result.defined:
            print(f"Результат: {result.state}   (кроків: {result.steps})")
        else:
            print(f"Результат: ⊥ (не визначено) [{result.error_code}]: {result.error_message}")
    return EXIT_OK if result.defined else EXIT_UNDEFINED


def cmd_prove(args) -> int:
    source, prog = _load_program(args, "prove")
    if prog is None:
        return EXIT_SYNTAX
    try:
        with open(args.spec, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        raise _UsageError(f"не вдалося прочитати специфікацію '{args.spec}': {e.strerror or e}") from None
    except json.JSONDecodeError as e:
        raise _UsageError(f"специфікація '{args.spec}' — некоректний JSON: {e}") from None
    if args.domain:
        data["domain"] = args.domain
    try:
        report = prove(prog, ProofSpec.from_dict(data))
    except SpecError as e:
        raise _UsageError(str(e)) from None
    if args.json:
        _emit_json({"command": "prove", **report.to_dict()})
    else:
        print(format_report(report))
    return report.exit_code


# ----------------------------------------------------------------- розбір аргументів
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sipl",
        description="SIPL Language Toolkit: парсер, дерево виводу, семантичні терми, асистент доведення.",
        epilog="Коди завершення: 0 успіх; 1 синтаксична помилка; 2 помилка використання/вводу; 3 значення ⊥; 4 доведення спростовано; 5 доведення лише на обмеженій області.",
    )
    p.add_argument("--version", action="version", version=f"sipl {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="команда")

    def common(sp, with_file=True):
        if with_file:
            sp.add_argument("file", help="файл програми SIPL ('-' — читати зі stdin)")
        sp.add_argument("--json", action="store_true", help="машинозчитуваний вивід (JSON)")
        sp.add_argument("--seq-assoc", choices=["left", "right"], default="left", help="асоціативність ';' (за замовчуванням left, як у підручнику)")

    sp = sub.add_parser("parse", help="розібрати програму і показати AST")
    common(sp)
    sp.set_defaults(func=cmd_parse)

    sp = sub.add_parser("check", help="перевірити синтаксис і показати вхідні змінні")
    common(sp)
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("tree", help="дерево синтаксичного виводу (text/json/dot/svg/html)")
    common(sp)
    sp.add_argument("--format", choices=["text", "json", "dot", "svg", "html"], default="text")
    sp.add_argument("--labels", choices=["bnf", "ua"], default="bnf", help="назви нетерміналів: Prog/Stm/… або <програма>/<оператор>/…")
    sp.add_argument("-o", "--output", help="записати результат у файл")
    sp.set_defaults(func=cmd_tree)

    sp = sub.add_parser("term", help="побудувати семантичний терм програми")
    common(sp)
    sp.add_argument("--style", choices=["unicode", "ascii", "latex"], default="unicode")
    sp.add_argument("--explain", action="store_true", help="показати послідовність застосованих правил NS_*")
    sp.set_defaults(func=cmd_term)

    sp = sub.add_parser("eval", help="застосувати семантичний терм до стану (покроково з --trace)")
    sp.add_argument("file", nargs="?", help="файл програми SIPL")
    sp.add_argument("--term", help="замість програми: JSON-файл із термом")
    sp.add_argument("--state", default="", help="початковий стан, напр. \"N=3\" або \"X=5, Y=2\"")
    sp.add_argument("--trace", action="store_true", help="показати покрокове обчислення")
    sp.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS, help=f"ліміт кроків (за замовчуванням {DEFAULT_MAX_STEPS})")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--seq-assoc", choices=["left", "right"], default="left")
    sp.set_defaults(func=cmd_eval)

    sp = sub.add_parser("prove", help="асистент доведення коректності циклу")
    common(sp)
    sp.add_argument("--spec", required=True, help="JSON зі специфікацією (pre, post, invariant/closed_form, …)")
    sp.add_argument("--domain", type=int, default=0, help="верхня межа значень для перевірок на обмеженій області")
    sp.set_defaults(func=cmd_prove)
    return p


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except _UsageError as e:
        print(f"sipl: помилка: {e}", file=sys.stderr)
        return EXIT_USAGE
    except BrokenPipeError:
        return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
