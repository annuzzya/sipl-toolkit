import copy
import json
import os
import unittest

from sipl import parse
from sipl.semantics.proof import ProofSpec, SpecError, format_report, prove

from .helpers import EXAMPLES, read


def load(name):
    prog = parse(read(os.path.join(EXAMPLES, name + ".sipl")))
    spec = json.loads(read(os.path.join(EXAMPLES, name + ".proof.json")))
    return prog, spec


def run(prog, spec):
    return prove(prog, ProofSpec.from_dict(copy.deepcopy(spec)))


def step(report, sid):
    return next(s for s in report.steps if s.id == sid)


class ProvedTests(unittest.TestCase):
    def test_variant_18_sum_is_proved_symbolically(self):
        prog, spec = load("sum_ap")
        rep = run(prog, spec)
        self.assertEqual(rep.verdict, "proved")
        self.assertEqual(rep.exit_code, 0)
        for sid in ("A2", "A3", "A4", "A5"):
            self.assertEqual(step(rep, sid).kind, "exact")
            self.assertEqual(step(rep, sid).status, "ok")

    def test_induction_step_shows_intermediate_states(self):
        prog, spec = load("sum_ap")
        text = "\n".join(step(run(prog, spec), "A3").lines)
        self.assertIn("T:=T+3", text)
        self.assertIn("S:=S+T", text)
        self.assertIn("N:=N-1", text)

    def test_unchanged_variables_are_treated_as_constants(self):
        prog, spec = load("mult_by_add")
        rep = run(prog, spec)
        self.assertEqual(rep.verdict, "proved")
        self.assertIn("сталими", "\n".join(step(rep, "A2").lines))

    def test_invariant_only_mode_is_bounded_not_proved(self):
        prog, spec = load("sum_ap")
        spec.pop("closed_form"), spec.pop("iterations")
        rep = run(prog, spec)
        self.assertEqual(rep.verdict, "bounded")
        self.assertEqual(rep.exit_code, 5)
        for sid in ("B1", "B2", "B3", "B4", "B5"):
            self.assertEqual(step(rep, sid).status, "ok")

    def test_report_has_conclusion_and_limits(self):
        prog, spec = load("sum_ap")
        text = format_report(run(prog, spec))
        self.assertIn("ВИСНОВОК", text)
        self.assertIn("Межі асистента", text)


class RefutedTests(unittest.TestCase):
    def test_wrong_closed_form_gives_counterexample(self):
        prog, spec = load("sum_ap")
        spec["closed_form"]["S"] = "3*k*k"
        rep = run(prog, spec)
        self.assertEqual(rep.verdict, "refuted")
        self.assertEqual(rep.exit_code, 4)
        a3 = step(rep, "A3")
        self.assertEqual(a3.status, "fail")
        self.assertIsNotNone(a3.counterexample)

    def test_wrong_postcondition_is_refuted_with_final_state(self):
        prog, spec = load("sum_ap")
        spec["post"] = "S = 3*n*(n+1)"
        rep = run(prog, spec)
        self.assertEqual(rep.verdict, "refuted")
        cx = step(rep, "A5").counterexample
        self.assertIn("кінцевий стан", json.dumps(cx, ensure_ascii=False))

    def test_wrong_invariant_is_found_empirically(self):
        prog, spec = load("sum_ap")
        spec.pop("closed_form"), spec.pop("iterations")
        spec["invariant"] = "T = 3*(n-N) and 2*S = 3*(n-N)*(n-N+1) + 1"
        rep = run(prog, spec)
        self.assertEqual(rep.verdict, "refuted")

    def test_wrong_iteration_count_is_refuted(self):
        prog, spec = load("sum_ap")
        spec["iterations"] = "n + 1"
        self.assertEqual(run(prog, spec).verdict, "refuted")

    def test_bundled_bad_spec_is_refuted(self):
        prog = parse(read(os.path.join(EXAMPLES, "sum_ap.sipl")))
        spec = json.loads(read(os.path.join(EXAMPLES, "bad_sum.proof.json")))
        self.assertEqual(run(prog, spec).verdict, "refuted")


class SpecErrorTests(unittest.TestCase):
    def test_program_without_loop(self):
        with self.assertRaises(SpecError):
            prove(parse("begin x := 1 end"), ProofSpec.from_dict({"pre": "x = x", "post": "x = 1", "invariant": "x = x"}))

    def test_nested_loops_are_out_of_scope(self):
        prog = parse("begin while a > 0 do begin while b > 0 do b := b - 1; a := a - 1 end end")
        with self.assertRaises(SpecError):
            prove(prog, ProofSpec.from_dict({"pre": "a >= 0", "post": "a = 0", "invariant": "a >= 0"}))

    def test_unknown_field(self):
        with self.assertRaises(SpecError):
            ProofSpec.from_dict({"pre": "x = x", "post": "x = x", "invariant": "x = x", "oops": 1})

    def test_missing_invariant_and_formula(self):
        with self.assertRaises(SpecError):
            ProofSpec.from_dict({"pre": "x = x", "post": "x = x"})

    def test_closed_form_requires_iterations(self):
        with self.assertRaises(SpecError):
            ProofSpec.from_dict({"pre": "x = x", "post": "x = x", "closed_form": {"x": "k"}})


class FallbackTests(unittest.TestCase):
    def test_if_inside_body_falls_back_to_bounded(self):
        prog = parse("begin s := 0; while n > 0 do begin if n > 1 then s := s + 2 else s := s + 1; n := n - 1 end end")
        spec = {
            "params": ["m"], "pre": "n = m and m > 0", "post": "s >= m",
            "inputs": {"n": "m"}, "invariant": "0 <= n and n <= m and s >= m - n", "variant": "n",
        }
        rep = run(prog, spec)
        self.assertIn(rep.verdict, ("bounded", "proved"))
        self.assertNotEqual(rep.verdict, "refuted")


if __name__ == "__main__":
    unittest.main()
