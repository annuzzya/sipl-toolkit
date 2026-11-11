import glob
import json
import os
import unittest

from sipl import SiplSyntaxError, SourceText, parse
from sipl import ast as A
from sipl.lexer import tokenize
from sipl.unparse import unparse

from .helpers import FIXTURES, read


class LexerTests(unittest.TestCase):
    def kinds(self, text):
        return [t.kind for t in tokenize(SourceText(text))]

    def test_keywords_and_symbols(self):
        self.assertEqual(
            self.kinds("begin x := 1 + 2 * y; skip end"),
            ["begin", "ID", "ASSIGN", "NUM", "PLUS", "NUM", "STAR", "ID", "SEMI", "skip", "end", "EOF"],
        )

    def test_logic_words_and_unicode_are_equivalent(self):
        self.assertEqual(self.kinds("a ∨ ¬b"), self.kinds("a or not b"))

    def test_comment_is_skipped(self):
        self.assertEqual(self.kinds("x // коментар\n y"), ["ID", "ID", "EOF"])

    def test_token_positions_multiline(self):
        toks = tokenize(SourceText("begin\n  x := 1\nend"))
        x = next(t for t in toks if t.text == "x")
        self.assertEqual((x.span.line, x.span.col, x.span.start, x.span.end), (2, 3, 8, 9))

    def test_identifiers_may_contain_digits_and_underscore(self):
        self.assertEqual(self.kinds("x1_a"), ["ID", "EOF"])


class ValidProgramsTests(unittest.TestCase):
    def test_every_valid_fixture_parses(self):
        files = sorted(glob.glob(os.path.join(FIXTURES, "valid", "*.sipl")))
        self.assertGreaterEqual(len(files), 10)
        for f in files:
            with self.subTest(file=os.path.basename(f)):
                prog = parse(read(f), f)
                self.assertIsInstance(prog, A.Program)

    def test_unparse_roundtrip_is_structurally_equal(self):
        for f in sorted(glob.glob(os.path.join(FIXTURES, "valid", "*.sipl"))):
            with self.subTest(file=os.path.basename(f)):
                first = parse(read(f))
                second = parse(unparse(first))
                self.assertEqual(first, second)  # == ігнорує позиції

    def test_nodes_are_own_ast_types(self):
        prog = parse("begin x := 1 end")
        self.assertIs(type(prog), A.Program)
        self.assertIs(type(prog.body), A.Assign)
        self.assertIs(type(prog.body.expr), A.Num)
        self.assertEqual(prog.body.expr.value, 1)

    def test_spans_point_to_source_fragments(self):
        text = "begin\n  S := S + 10;\n  skip\nend"
        src = SourceText(text)
        from sipl.parser import parse_source

        prog = parse_source(src)
        assign = prog.body.left
        self.assertEqual(src.fragment(assign.span), "S := S + 10")
        self.assertEqual((assign.span.line, assign.span.col), (2, 3))
        self.assertEqual(src.fragment(assign.expr.right.span), "10")
        self.assertEqual(src.fragment(prog.span), text)

    def test_multiplication_binds_tighter(self):
        e = parse("begin x := 1 + 2 * 3 end").body.expr
        self.assertEqual(e.op, "+")
        self.assertEqual(e.right.op, "*")

    def test_subtraction_is_left_associative(self):
        e = parse("begin x := 10 - 3 - 2 end").body.expr
        self.assertEqual(e.op, "-")
        self.assertEqual(e.left.op, "-")
        self.assertEqual(e.right.value, 2)

    def test_semicolon_assoc_left_default_and_right_option(self):
        left = parse("begin a := 1; b := 2; c := 3 end").body
        self.assertIsInstance(left.left, A.Seq)
        right = parse("begin a := 1; b := 2; c := 3 end", seq_assoc="right").body
        self.assertIsInstance(right.right, A.Seq)

    def test_negation_binds_tighter_than_or(self):
        b = parse("begin while ¬a > 0 ∨ b = 1 do skip end").body.cond
        self.assertIsInstance(b, A.Or)
        self.assertIsInstance(b.left, A.Not)

    def test_parenthesised_arithmetic_and_condition_are_distinguished(self):
        self.assertIsInstance(parse("begin while (x) > 0 do skip end").body.cond, A.Compare)
        self.assertIsInstance(parse("begin while (x > 0) do skip end").body.cond, A.ParenB)

    def test_while_body_is_single_statement(self):
        prog = parse("begin while x > 0 do x := x - 1; y := 1 end")
        self.assertIsInstance(prog.body, A.Seq)  # (while …) ; y := 1
        self.assertIsInstance(prog.body.left, A.While)


class InvalidProgramsTests(unittest.TestCase):
    def test_every_invalid_fixture_reports_expected_code_and_position(self):
        expected = json.loads(read(os.path.join(FIXTURES, "invalid", "EXPECTED.json")))
        files = sorted(glob.glob(os.path.join(FIXTURES, "invalid", "*.sipl")))
        self.assertGreaterEqual(len(files), 10)
        self.assertEqual({os.path.basename(f) for f in files}, set(expected))
        for f in files:
            name = os.path.basename(f)
            with self.subTest(file=name):
                with self.assertRaises(SiplSyntaxError) as ctx:
                    parse(read(f), f)
                d = ctx.exception.diagnostic
                self.assertEqual(d.code, expected[name]["code"])
                self.assertEqual((d.span.line, d.span.col), (expected[name]["line"], expected[name]["col"]))
                self.assertTrue(d.message)

    def test_diagnostic_rendering_contains_caret_under_error(self):
        from sipl import render_diagnostic

        text = "begin\n  x := 1 +;\nend"
        with self.assertRaises(SiplSyntaxError) as ctx:
            parse(text, "t.sipl")
        out = render_diagnostic(ctx.exception.diagnostic, SourceText(text, "t.sipl"))
        self.assertIn("t.sipl:2:", out)
        self.assertIn("x := 1 +;", out)
        self.assertIn("^", out)


if __name__ == "__main__":
    unittest.main()
