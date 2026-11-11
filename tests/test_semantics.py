import json
import os
import unittest

from sipl import parse
from sipl.semantics.build import build_term, build_term_with_trace
from sipl.semantics.evaluate import Undefined, eval_condition, evaluate, format_trace
from sipl.semantics.state import State, format_state, parse_state
from sipl.semantics.term import SupT, ConstT, DenomT, format_term, term_from_dict, term_to_dict

from .helpers import FIXTURES, read

GOLDEN = json.loads(read(os.path.join(FIXTURES, "..", "golden", "terms.json")))["cases"]


class GoldenTermTests(unittest.TestCase):
    def test_terms_match_course_notation(self):
        for case in GOLDEN:
            with self.subTest(case=case["name"]):
                self.assertEqual(format_term(build_term(parse(case["program"]))), case["term"])

    def test_evaluation_results(self):
        for case in GOLDEN:
            term = build_term(parse(case["program"]))
            for ev in case["evals"]:
                with self.subTest(case=case["name"], state=ev["state"]):
                    res = evaluate(term, ev["state"])
                    self.assertTrue(res.defined)
                    self.assertEqual(res.state.to_dict(), ev["result"])

    def test_term_json_roundtrip(self):
        for case in GOLDEN:
            with self.subTest(case=case["name"]):
                t = build_term(parse(case["program"]))
                self.assertEqual(term_from_dict(json.loads(json.dumps(term_to_dict(t)))), t)

    def test_ascii_and_latex_styles(self):
        t = build_term(parse("begin x := y + 1 end"))
        self.assertEqual(format_term(t, "ascii"), "AS[x](S2(add, den(y), c(1)))")
        self.assertEqual(format_term(t, "latex"), "AS^{x}(S^{2}(add, y\\Rightarrow, \\overline{1}))")


class RewriteTraceTests(unittest.TestCase):
    def test_rules_are_named_as_in_the_course(self):
        _, steps = build_term_with_trace(parse("begin S := 0; while N > 0 do N := N - 1 end"))
        rules = [s.rule for s in steps]
        for expected in ["NS_Prog", "NS_Stm_Seq", "NS_Stm_As", "NS_A_Num", "NS_Stm_Wh", "NS_B_gr", "NS_A_Var", "NS_A_Sub"]:
            self.assertIn(expected, rules)
        self.assertEqual(rules[0], "NS_Prog")

    def test_every_step_has_source_span_and_equation(self):
        _, steps = build_term_with_trace(parse("begin x := (1 + 2) * 3 end"))
        self.assertIn("NS_A_Par", [s.rule for s in steps])
        for s in steps:
            self.assertIsNotNone(s.span)
            self.assertTrue(s.lhs.startswith("sem_"))

    def test_first_step_matches_textbook(self):
        _, steps = build_term_with_trace(parse("begin R := 1; while Y > 0 do begin R := R * X; Y := Y - 1 end end"))
        self.assertEqual(str(steps[0]), "NS_Prog: sem_P(begin R:=1; while Y>0 do begin R:=R*X; Y:=Y-1 end end) = sem_S(R:=1; while Y>0 do begin R:=R*X; Y:=Y-1 end)")


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.sum_term = build_term(parse(read(os.path.join(FIXTURES, "valid", "sum_ap.sipl"))))

    def test_state_update_does_not_mutate_old_state(self):
        st = State({"x": 1})
        new = st.update("x", 2).update("y", 3)
        self.assertEqual(st.to_dict(), {"x": 1})
        self.assertEqual(new.to_dict(), {"x": 2, "y": 3})
        self.assertEqual(format_state(new), "[x ↦ 2, y ↦ 3]")

    def test_parse_state_formats(self):
        self.assertEqual(parse_state("X=5, Y=2").to_dict(), {"X": 5, "Y": 2})
        self.assertEqual(parse_state("[N ↦ 3]").to_dict(), {"N": 3})
        self.assertEqual(parse_state("").to_dict(), {})
        with self.assertRaises(ValueError):
            parse_state("X=abc")

    def test_undefined_variable_gives_bottom(self):
        res = evaluate(self.sum_term, {})
        self.assertFalse(res.defined)
        self.assertEqual(res.error_code, "E-EVAL-UNDEF")
        self.assertIn("N", res.error_message)

    def test_step_limit_turns_infinite_loop_into_bottom(self):
        res = evaluate(build_term(parse("begin while 1 > 0 do skip end")), {}, max_steps=200)
        self.assertFalse(res.defined)
        self.assertEqual(res.error_code, "E-EVAL-LIMIT")

    def test_negative_numbers_via_subtraction(self):
        res = evaluate(build_term(parse("begin x := 0 - 5 end")), {})
        self.assertEqual(res.state["x"], -5)

    def test_trace_follows_af_formulas_and_loop_heads(self):
        res = evaluate(self.sum_term, {"N": 3})
        heads = [e for e in res.events if e.rule == "AF_WH"]
        self.assertEqual([e.loop_head for e in heads], [0, 1, 2, 3])
        self.assertEqual([e.before["N"] for e in heads], [3, 2, 1, 0])
        self.assertIn("AF_AS", {e.rule for e in res.events})
        self.assertIn("AF_SEQ", {e.rule for e in res.events})
        # стани st_k з практичної роботи
        self.assertEqual(heads[1].before, {"N": 2, "S": 3, "T": 3})
        self.assertEqual(heads[2].before, {"N": 1, "S": 9, "T": 6})
        self.assertEqual(heads[3].before, {"N": 0, "S": 18, "T": 9})

    def test_trace_text_mentions_result(self):
        text = format_trace(evaluate(self.sum_term, {"N": 2}))
        self.assertIn("Результат: [N ↦ 0, S ↦ 9, T ↦ 6]", text)

    def test_trace_can_be_disabled(self):
        self.assertEqual(evaluate(self.sum_term, {"N": 4}, trace=False).events, [])

    def test_trace_limit_truncates_but_result_is_correct(self):
        res = evaluate(self.sum_term, {"N": 50}, trace_limit=10)
        self.assertTrue(res.trace_truncated)
        self.assertEqual(res.state["S"], 3 * 50 * 51 // 2)

    def test_if_takes_only_chosen_branch(self):
        term = build_term(parse("begin if x > 0 then y := 1 else y := z end"))
        self.assertTrue(evaluate(term, {"x": 1}).defined)  # z не читається
        self.assertFalse(evaluate(term, {"x": 0}).defined)  # z читається

    def test_condition_helper(self):
        cond = SupT("gr", (DenomT("x"), ConstT(0)))
        self.assertTrue(eval_condition(cond, {"x": 1}))
        with self.assertRaises(Undefined):
            eval_condition(cond, {})

    def test_evaluation_of_hand_written_term_from_json(self):
        term = term_from_dict({"term": "assign", "var": "y", "expr": {"term": "sup", "func": "mult", "args": [{"term": "denom", "var": "x"}, {"term": "const", "value": 4}]}})
        self.assertEqual(evaluate(term, {"x": 3}).state.to_dict(), {"x": 3, "y": 12})
        with self.assertRaises(ValueError):
            term_from_dict({"term": "bogus"})


if __name__ == "__main__":
    unittest.main()
