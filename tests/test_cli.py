import glob
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout

from sipl.cli import main

from .helpers import EXAMPLES, FIXTURES, ROOT


def cli(*argv, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    old = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = main(list(argv))
            except SystemExit as e:  # argparse
                code = e.code
    finally:
        sys.stdin = old
    return code, out.getvalue(), err.getvalue()


def ex(name):
    return os.path.join(EXAMPLES, name)


class ExitCodeTests(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(cli("check", ex("sum_ap.sipl"))[0], 0)

    def test_syntax_error_is_1_with_caret_on_stdout_or_stderr(self):
        code, out, err = cli("check", ex("bad_example.sipl"))
        self.assertEqual(code, 1)
        self.assertIn("E-PARSE-001", out + err)
        self.assertIn("3:11", out + err)

    def test_usage_error_is_2(self):
        self.assertEqual(cli("check", "no_such_file.sipl")[0], 2)
        self.assertEqual(cli("eval", ex("sum_ap.sipl"), "--state", "N=abc")[0], 2)
        self.assertEqual(cli("prove", ex("sum_ap.sipl"), "--spec", "nope.json")[0], 2)

    def test_bottom_is_3(self):
        self.assertEqual(cli("eval", ex("loop_forever.sipl"), "--max-steps", "100")[0], 3)
        self.assertEqual(cli("eval", ex("sum_ap.sipl"))[0], 3)  # N не задано

    def test_prove_exit_codes(self):
        self.assertEqual(cli("prove", ex("sum_ap.sipl"), "--spec", ex("sum_ap.proof.json"))[0], 0)
        self.assertEqual(cli("prove", ex("sum_ap.sipl"), "--spec", ex("bad_sum.proof.json"))[0], 4)

    def test_version(self):
        code, out, _ = cli("--version")
        self.assertEqual(code, 0)
        self.assertIn("0.1.0", out)


class CommandTests(unittest.TestCase):
    def test_parse_json_contract(self):
        code, out, _ = cli("parse", ex("gcd.sipl"), "--json")
        d = json.loads(out)
        self.assertEqual((code, d["schema_version"], d["command"], d["ok"]), (0, 1, "parse", True))
        self.assertEqual(d["ast"]["node"], "Prog")
        self.assertIn("span", d["ast"])

    def test_check_json_error_contract(self):
        code, out, _ = cli("check", ex("bad_example.sipl"), "--json")
        d = json.loads(out)
        self.assertEqual(code, 1)
        self.assertFalse(d["ok"])
        diag = d["diagnostics"][0]
        self.assertEqual((diag["code"], diag["severity"], diag["span"]["line"], diag["span"]["col"]), ("E-PARSE-001", "error", 3, 11))

    def test_term_matches_textbook(self):
        code, out, _ = cli("term", ex("power.sipl"))
        self.assertEqual(code, 0)
        self.assertIn("AS^R(1̄) · WH(S²(gr, Y⇒, 0̄), AS^R(S²(mult, R⇒, X⇒)) · AS^Y(S²(sub, Y⇒, 1̄)))", out)

    def test_term_explain_lists_rules(self):
        _, out, _ = cli("term", ex("power.sipl"), "--explain")
        for r in ("NS_Prog", "NS_Stm_Wh", "NS_A_Mult"):
            self.assertIn(r, out)

    def test_term_json_and_styles(self):
        d = json.loads(cli("term", ex("power.sipl"), "--json")[1])
        self.assertEqual(d["term_tree"]["term"], "seq")
        self.assertIn("AS[R]", cli("term", ex("power.sipl"), "--style", "ascii")[1])
        self.assertIn("\\Rightarrow", cli("term", ex("power.sipl"), "--style", "latex")[1])

    def test_eval_sum_ap(self):
        code, out, _ = cli("eval", ex("sum_ap.sipl"), "--state", "N=3")
        self.assertEqual(code, 0)
        self.assertIn("[N ↦ 0, S ↦ 18, T ↦ 9]", out)

    def test_eval_trace_and_json(self):
        _, out, _ = cli("eval", ex("sum_ap.sipl"), "--state", "N=2", "--trace")
        self.assertIn("AF_WH", out)
        d = json.loads(cli("eval", ex("sum_ap.sipl"), "--state", "N=3", "--json")[1])
        self.assertEqual((d["defined"], d["state"], d["steps"]), (True, {"N": 0, "S": 18, "T": 9}, 24))

    def test_eval_bottom_json(self):
        code, out, _ = cli("eval", ex("loop_forever.sipl"), "--max-steps", "50", "--json")
        d = json.loads(out)
        self.assertEqual(code, 3)
        self.assertFalse(d["defined"])
        self.assertEqual(d["error"]["code"], "E-EVAL-LIMIT")

    def test_eval_other_examples(self):
        cases = [("power.sipl", "X=2, Y=10", "R ↦ 1024"), ("fact.sipl", "N=5", "F ↦ 120"),
                 ("gcd.sipl", "a=48, b=18", "a ↦ 6"), ("mult_by_add.sipl", "A=7, B=6", "P ↦ 42")]
        for f, st, want in cases:
            with self.subTest(file=f):
                code, out, _ = cli("eval", ex(f), "--state", st)
                self.assertEqual(code, 0)
                self.assertIn(want, out)

    def test_eval_from_term_file(self):
        term = {"term": "assign", "var": "y", "expr": {"term": "sup", "func": "add", "args": [{"term": "denom", "var": "x"}, {"term": "const", "value": 1}]}}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.json")
            with open(p, "w") as f:
                json.dump(term, f)
            code, out, _ = cli("eval", "--term", p, "--state", "x=4")
            self.assertEqual(code, 0)
            self.assertIn("y ↦ 5", out)

    def test_stdin_input(self):
        code, out, _ = cli("check", "-", stdin="begin x := 1 end")
        self.assertEqual(code, 0)

    def test_seq_assoc_option(self):
        code, out, _ = cli("parse", ex("sum_ap.sipl"), "--seq-assoc", "right", "--json")
        self.assertEqual(code, 0)

    def test_prove_json(self):
        code, out, _ = cli("prove", ex("mult_by_add.sipl"), "--spec", ex("mult_by_add.proof.json"), "--json")
        d = json.loads(out)
        self.assertEqual((code, d["verdict"], d["schema_version"]), (0, "proved", 1))
        self.assertTrue(any(s["id"] == "A3" for s in d["steps"]))

    def test_prove_refuted_json_has_counterexample(self):
        code, out, _ = cli("prove", ex("sum_ap.sipl"), "--spec", ex("bad_sum.proof.json"), "--json")
        d = json.loads(out)
        self.assertEqual(code, 4)
        self.assertTrue(any(s["counterexample"] for s in d["steps"]))


class TreeOutputTests(unittest.TestCase):
    def test_all_formats(self):
        for fmt in ("text", "json", "dot", "svg", "html"):
            with self.subTest(fmt=fmt):
                code, out, _ = cli("tree", ex("sum_ap.sipl"), "--format", fmt)
                self.assertEqual(code, 0)
                self.assertTrue(out.strip())

    def test_output_file_is_valid_svg(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.svg")
            code, _, _ = cli("tree", ex("sum_ap.sipl"), "--format", "svg", "-o", p)
            self.assertEqual(code, 0)
            ET.parse(p)

    def test_tree_json_flag(self):
        d = json.loads(cli("tree", ex("sum_ap.sipl"), "--json")[1])
        self.assertEqual(d["leaf_count"], 34)

    def test_tree_of_invalid_program_fails_cleanly(self):
        self.assertEqual(cli("tree", ex("bad_example.sipl"))[0], 1)


class ExamplesSmokeTests(unittest.TestCase):
    def test_every_valid_example_and_fixture_passes_all_front_commands(self):
        files = sorted(glob.glob(os.path.join(EXAMPLES, "*.sipl")) + glob.glob(os.path.join(FIXTURES, "valid", "*.sipl")))
        for f in files:
            if os.path.basename(f) == "bad_example.sipl":
                continue
            for cmd in ("check", "parse", "term", "tree"):
                with self.subTest(file=os.path.basename(f), cmd=cmd):
                    self.assertEqual(cli(cmd, f)[0], 0)

    def test_at_least_three_examples(self):
        self.assertGreaterEqual(len(glob.glob(os.path.join(EXAMPLES, "*.sipl"))), 3)


class SubprocessTests(unittest.TestCase):
    """Запуск як окремого процесу: python -m sipl."""

    def test_python_m_sipl(self):
        env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"), PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, "-m", "sipl", "eval", ex("sum_ap.sipl"), "--state", "N=4"],
                           capture_output=True, text=True, env=env, encoding="utf-8")
        self.assertEqual(r.returncode, 0)
        self.assertIn("S ↦ 30", r.stdout)


if __name__ == "__main__":
    unittest.main()
