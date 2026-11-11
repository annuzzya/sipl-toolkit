import unittest
from fractions import Fraction

from sipl.semantics.formula import (
    FormulaError, arith_to_poly, eval_arith, eval_formula, format_formula,
    formula_vars, parse_arith, parse_formula,
)
from sipl.semantics.poly import NotPolynomial, Poly


class PolyTests(unittest.TestCase):
    def test_arithmetic_and_canonical_equality(self):
        n, k = Poly.var("n"), Poly.var("k")
        self.assertEqual((n + k) * (n + k), n * n + k * n + k * n + k * k)
        self.assertTrue((n - n).is_zero())

    def test_printing_order(self):
        n, k = Poly.var("n"), Poly.var("k")
        self.assertEqual(str((n - k) * k), "-k² + k·n")
        self.assertEqual(str(n - k), "n - k")

    def test_substitution_and_evaluation(self):
        n, k = Poly.var("n"), Poly.var("k")
        p = (n - k) * k
        self.assertEqual(p.subst({"k": Poly.const(2)}), n.scale(2) - Poly.const(4))
        self.assertEqual(p.evaluate({"n": 5, "k": 2}), 6)

    def test_rational_coefficients_are_exact(self):
        p = arith_to_poly(parse_arith("3*k*(k+1)/2"), {})
        self.assertEqual(p.evaluate({"k": 3}), Fraction(18))
        self.assertEqual(str(p), "3/2·k² + 3/2·k")


class FormulaTests(unittest.TestCase):
    def test_precedence_and_evaluation(self):
        f = parse_formula("0 <= N and N <= n or not (a = 1)")
        self.assertTrue(eval_formula(f, {"N": 1, "n": 2, "a": 1}))
        self.assertTrue(eval_formula(f, {"N": 5, "n": 2, "a": 2}))
        self.assertFalse(eval_formula(f, {"N": 5, "n": 2, "a": 1}))

    def test_implication(self):
        f = parse_formula("x > 0 -> y > 0")
        self.assertTrue(eval_formula(f, {"x": 0, "y": 0}))
        self.assertFalse(eval_formula(f, {"x": 1, "y": 0}))

    def test_vars_and_format(self):
        f = parse_formula("2*S = 3*n*(n+1)")
        self.assertEqual(formula_vars(f), {"S", "n"})
        self.assertIn("S", format_formula(f))

    def test_syntax_error_is_reported(self):
        for bad in ["N >", "x = ", "(x", "x = 1 and"]:
            with self.subTest(bad=bad):
                with self.assertRaises(FormulaError):
                    parse_formula(bad)

    def test_non_polynomial_is_rejected(self):
        with self.assertRaises(NotPolynomial):
            arith_to_poly(parse_arith("n/k"), {})

    def test_eval_arith(self):
        self.assertEqual(eval_arith(parse_arith("2*(x+1)-3"), {"x": 4}), 7)


if __name__ == "__main__":
    unittest.main()
