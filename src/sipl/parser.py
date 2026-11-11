"""Рекурсивний спуск за БНФ SIPL із практикуму (CORE-02).

Граматика (ідеальна форма, без неоднозначності):

    Prog ::= begin Stm end
    Stm  ::= Seq
    Seq  ::= Atom { ';' Atom }            (зліва або справа, див. seq_assoc)
    Atom ::= Var ':=' Aexp
           | if Bexp then Atom else Atom
           | while Bexp do Atom
           | begin Stm end
           | skip
    Bexp ::= Not { '∨' Not }              (∨ ліво-асоціативний)
    Not  ::= '¬' Not | BAtom
    BAtom::= Aexp ('=' | '>') Aexp | '(' Bexp ')'
    Aexp ::= Term { ('+' | '-') Term }    (ліво-асоціативні)
    Term ::= Factor { '*' Factor }
    Factor ::= Num | Var | '(' Aexp ')'

Дозвіл неоднозначностей БНФ курсу (розд. «Побудова семантичного терму»): пріоритет
`*` вищий за `+`/`-`; `;` — ліво-асоціативна (за замовчуванням, як у підручнику);
тіла `if`/`while` — це Atom, тобто складені тіла записують у begin…end.
"""
from __future__ import annotations

from typing import Optional

from . import ast as A
from .errors import Diagnostic, SiplError, SiplSyntaxError
from .lexer import KIND_NAMES, Token, tokenize
from .spans import SourceSpan, SourceText

_STM_START = ["змінна", "'if'", "'while'", "'begin'", "'skip'"]
_AEXP_START = ["число", "змінна", "'('"]


class _Fail(Exception):
    """Внутрішній відкат для вибору між `(a) > b` та `(b1 ∨ b2)`."""

    def __init__(self, error: SiplSyntaxError, pos: int):
        self.error = error
        self.pos = pos


class Parser:
    def __init__(self, source: SourceText, seq_assoc: str = "left"):
        if seq_assoc not in ("left", "right"):
            raise ValueError("seq_assoc має бути 'left' або 'right'")
        self.source = source
        self.seq_assoc = seq_assoc
        self.tokens = tokenize(source)
        self.pos = 0

    # ---------------------------------------------------------------- утиліти
    @property
    def tok(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        t = self.tokens[self.pos]
        if t.kind != "EOF":
            self.pos += 1
        return t

    def _expect(self, kind: str, context: str = "") -> Token:
        if self.tok.kind == kind:
            return self._advance()
        raise self._unexpected([KIND_NAMES[kind]], context)

    def _unexpected(self, expected: list[str], context: str = "") -> SiplSyntaxError:
        t = self.tok
        exp = ", ".join(expected[:-1]) + " або " + expected[-1] if len(expected) > 1 else expected[0]
        ctx = f" {context}" if context else ""
        if t.kind == "EOF":
            return SiplSyntaxError(
                Diagnostic("E-PARSE-002", f"несподіваний кінець тексту{ctx}: очікувалось {exp}", t.span,
                           hint="перевірте, чи кожному 'begin' відповідає 'end'")
            )
        shown = KIND_NAMES[t.kind] if t.kind not in ("ID", "NUM") else f"{KIND_NAMES[t.kind]} '{t.text}'"
        return SiplSyntaxError(
            Diagnostic("E-PARSE-001", f"несподівана лексема {shown}{ctx}: очікувалось {exp}", t.span)
        )

    def _span(self, first: SourceSpan, last: SourceSpan) -> SourceSpan:
        return first.join(last)

    # ------------------------------------------------------------- програма
    def parse_program(self) -> A.Program:
        begin = self._expect("begin", "на початку програми")
        body = self._stm()
        end = self._expect("end", "після оператора")
        if self.tok.kind != "EOF":
            raise SiplSyntaxError(
                Diagnostic("E-PARSE-003", f"після 'end' програми знайдено зайвий текст: {self.tok.text!r}", self.tok.span,
                           hint="програма — це один блок begin … end")
            )
        return A.Program(body, self._span(begin.span, end.span), (begin, body, end))

    # ------------------------------------------------------------ оператори
    def _stm(self) -> A.Node:
        first = self._atom()
        items = [first]
        semis: list[Token] = []
        while self.tok.kind == "SEMI":
            semis.append(self._advance())
            items.append(self._atom())
        if len(items) == 1:
            return first
        if self.seq_assoc == "left":
            acc = items[0]
            for semi, nxt in zip(semis, items[1:]):
                acc = A.Seq(acc, nxt, self._span(acc.span, nxt.span), (acc, semi, nxt))
            return acc
        acc = items[-1]
        for semi, prev in zip(reversed(semis), reversed(items[:-1])):
            acc = A.Seq(prev, acc, self._span(prev.span, acc.span), (prev, semi, acc))
        return acc

    def _atom(self) -> A.Node:
        t = self.tok
        if t.kind == "ID":
            target_tok = self._advance()
            target = A.Var(target_tok.text, target_tok.span, (target_tok,))
            assign = self._expect("ASSIGN", f"після змінної '{target_tok.text}'")
            expr = self._aexp()
            return A.Assign(target, expr, self._span(target.span, expr.span), (target, assign, expr))
        if t.kind == "if":
            kw = self._advance()
            cond = self._bexp()
            then_kw = self._expect("then", "після умови if")
            then = self._atom()
            else_kw = self._expect("else", "після гілки then (в SIPL гілка else обов'язкова)")
            orelse = self._atom()
            return A.If(cond, then, orelse, self._span(kw.span, orelse.span), (kw, cond, then_kw, then, else_kw, orelse))
        if t.kind == "while":
            kw = self._advance()
            cond = self._bexp()
            do_kw = self._expect("do", "після умови while")
            body = self._atom()
            return A.While(cond, body, self._span(kw.span, body.span), (kw, cond, do_kw, body))
        if t.kind == "begin":
            begin = self._advance()
            body = self._stm()
            end = self._expect("end", "після оператора")
            return A.Block(body, self._span(begin.span, end.span), (begin, body, end))
        if t.kind == "skip":
            kw = self._advance()
            return A.Skip(kw.span, (kw,))
        raise self._unexpected(_STM_START, "на початку оператора")

    # ----------------------------------------------------- логічні вирази
    def _bexp(self) -> A.Node:
        acc = self._bnot()
        while self.tok.kind == "OR":
            op = self._advance()
            right = self._bnot()
            acc = A.Or(acc, right, self._span(acc.span, right.span), (acc, op, right))
        return acc

    def _bnot(self) -> A.Node:
        if self.tok.kind == "NOT":
            op = self._advance()
            operand = self._bnot()
            return A.Not(operand, self._span(op.span, operand.span), (op, operand))
        return self._batom()

    def _batom(self) -> A.Node:
        if self.tok.kind != "LPAR":
            return self._compare()
        # '(' може відкривати і арифметичний вираз `(a)+1 > 0`, і умову `(b)`.
        start = self.pos
        try:
            return self._compare()
        except SiplSyntaxError as first_error:
            first_pos = self.pos
            self.pos = start
            try:
                lpar = self._advance()
                inner = self._bexp()
                rpar = self._expect("RPAR", "після умови в дужках")
                return A.ParenB(inner, self._span(lpar.span, rpar.span), (lpar, inner, rpar))
            except SiplSyntaxError as second_error:
                # показуємо ту помилку, що виникла далі в тексті
                second_pos = self.pos
                raise (first_error if first_pos >= second_pos else second_error)

    def _compare(self) -> A.Node:
        left = self._aexp()
        if self.tok.kind not in ("EQ", "GT"):
            raise self._unexpected(["'='", "'>'"], "у порівнянні (умова має вигляд a1 = a2 або a1 > a2)")
        op = self._advance()
        right = self._aexp()
        return A.Compare(op.text, left, right, self._span(left.span, right.span), (left, op, right))

    # ------------------------------------------------ арифметичні вирази
    def _aexp(self) -> A.Node:
        acc = self._term()
        while self.tok.kind in ("PLUS", "MINUS"):
            op = self._advance()
            right = self._term()
            acc = A.BinOp(op.text, acc, right, self._span(acc.span, right.span), (acc, op, right))
        return acc

    def _term(self) -> A.Node:
        acc = self._factor()
        while self.tok.kind == "STAR":
            op = self._advance()
            right = self._factor()
            acc = A.BinOp("*", acc, right, self._span(acc.span, right.span), (acc, op, right))
        return acc

    def _factor(self) -> A.Node:
        t = self.tok
        if t.kind == "NUM":
            self._advance()
            return A.Num(int(t.text), t.span, (t,))
        if t.kind == "ID":
            self._advance()
            return A.Var(t.text, t.span, (t,))
        if t.kind == "LPAR":
            lpar = self._advance()
            inner = self._aexp()
            rpar = self._expect("RPAR", "після виразу в дужках")
            return A.ParenA(inner, self._span(lpar.span, rpar.span), (lpar, inner, rpar))
        raise self._unexpected(_AEXP_START, "у арифметичному виразі")


# ------------------------------------------------------------ публічне API
def parse(text: str, name: str = "<input>", seq_assoc: str = "left") -> A.Program:
    """Розібрати текст програми. Кидає SiplSyntaxError з діагностикою."""
    return Parser(SourceText(text, name), seq_assoc).parse_program()


def parse_source(source: SourceText, seq_assoc: str = "left") -> A.Program:
    return Parser(source, seq_assoc).parse_program()
