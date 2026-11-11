import glob
import json
import os
import unittest
import xml.etree.ElementTree as ET

from sipl import SourceText, parse_source
from sipl.visualization.parse_tree import build_parse_tree, to_dict, to_dot, to_json, to_text
from sipl.visualization.svg import to_html, to_svg

from .helpers import EXAMPLES, FIXTURES, read


def load(path):
    src = SourceText(read(path), path)
    return src, build_parse_tree(parse_source(src))


class ParseTreeTests(unittest.TestCase):
    def setUp(self):
        self.src, self.root = load(os.path.join(EXAMPLES, "sum_ap.sipl"))

    def test_variant_18_program_has_34_numbered_leaves(self):
        leaves = self.root.leaves()
        self.assertEqual(len(leaves), 34)
        self.assertEqual(leaves[0].label(), "begin")
        self.assertEqual(leaves[-1].label(), "end")

    def test_leaves_concatenate_to_program_tokens(self):
        words = [l.label() for l in self.root.leaves()]
        self.assertEqual(" ".join(words).split()[:4], ["begin", "S", ":=", "0"])

    def test_nonterminal_symbols(self):
        symbols = {n.symbol for n in self.root.walk()}
        self.assertTrue({"Prog", "Stm", "Aexp", "Bexp", "Var", "Num"} <= symbols)
        self.assertEqual(self.root.symbol, "Prog")

    def test_json_contains_spans_and_rules(self):
        full = to_dict(self.root, self.src)
        self.assertEqual(full["leaf_count"], 34)
        self.assertEqual(full["schema_version"], 1)
        d = full["tree"]
        self.assertEqual(d["symbol"], "Prog")
        self.assertIn("rule", d)
        self.assertEqual(d["span"]["line"], 3)

        def walk(n):
            yield n
            for c in n.get("children", []):
                yield from walk(c)

        nodes = list(walk(d))
        self.assertTrue(all("span" in n and "symbol" in n for n in nodes))
        self.assertEqual(sum(1 for n in nodes if n["kind"] == "terminal"), 34)
        self.assertEqual(json.loads(to_json(self.root, self.src))["tree"]["symbol"], "Prog")

    def test_dot_is_well_formed(self):
        dot = to_dot(self.root, self.src)
        self.assertTrue(dot.startswith("digraph"))
        self.assertEqual(dot.count("{"), dot.count("}"))
        self.assertEqual(dot.count(" -> "), sum(1 for _ in self.root.walk()) - 1)

    def test_text_rendering_has_all_leaves(self):
        text = to_text(self.root, self.src)
        for i in (1, 17, 34):
            self.assertIn(f"{i}. ", text)

    def test_ukrainian_labels(self):
        text = to_text(self.root, self.src, ua=True)
        self.assertNotEqual(text, to_text(self.root, self.src, ua=False))


class SvgTests(unittest.TestCase):
    def test_svg_is_valid_xml_with_all_nodes(self):
        src, root = load(os.path.join(EXAMPLES, "sum_ap.sipl"))
        svg = to_svg(root, src)
        tree = ET.fromstring(svg)
        self.assertTrue(tree.tag.endswith("svg"))
        n_nodes = sum(1 for _ in root.walk())
        texts = [e for e in tree.iter() if e.tag.endswith("text")]
        self.assertGreaterEqual(len(texts), n_nodes)

    def test_svg_tooltips_link_nodes_to_source(self):
        src, root = load(os.path.join(EXAMPLES, "sum_ap.sipl"))
        self.assertIn("[4:3–4:9]", to_svg(root, src))

    def test_svg_escapes_special_characters(self):
        src, root = load(os.path.join(FIXTURES, "valid", "unicode_logic.sipl"))
        ET.fromstring(to_svg(root, src))  # не кидає — все екрановано

    def test_svg_for_every_valid_fixture(self):
        for f in sorted(glob.glob(os.path.join(FIXTURES, "valid", "*.sipl"))):
            with self.subTest(file=os.path.basename(f)):
                src, root = load(f)
                ET.fromstring(to_svg(root, src))

    def test_html_embeds_svg_and_source(self):
        src, root = load(os.path.join(EXAMPLES, "gcd.sipl"))
        html = to_html(root, src)
        self.assertIn("<svg", html)
        self.assertTrue(html.lstrip().lower().startswith("<!doctype html>"))

    def test_visualization_reflects_input_not_hardcoded(self):
        a = to_svg(*reversed(load(os.path.join(EXAMPLES, "gcd.sipl"))))
        b = to_svg(*reversed(load(os.path.join(EXAMPLES, "power.sipl"))))
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
