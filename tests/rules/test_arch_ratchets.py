"""Regression cases for the module graph and source size ratchets."""
import ast
import json
import unittest

from rules.arch_ratchets import cyclic_components, graph_of, growth_problems, metrics
from rules.gate_rules import RATCHET


class ArchitectureRatchets(unittest.TestCase):
    def test_repository_scc_fanout_and_sloc_match_the_ratchet(self):
        self.assertEqual(growth_problems(metrics(), json.loads(RATCHET.read_text())), [])

    def graph(self, sources):
        return graph_of({name: ast.parse(text) for name, text in sources.items()})

    def test_lazy_and_relative_imports_form_a_module_scc(self):
        graph = self.graph({"pkg.a": "def f():\n from . import b", "pkg.b": "from pkg.a import f"})
        self.assertEqual(cyclic_components(graph), [("pkg.a", "pkg.b")])

    def test_imports_of_siblings_in_package_init_are_edges(self):
        graph = self.graph({"pkg": "from . import a", "pkg.a": "import pkg"})
        self.assertEqual(cyclic_components(graph), [("pkg", "pkg.a")])

    def test_type_checking_imports_and_self_imports_are_included(self):
        graph = self.graph({"a": "if TYPE_CHECKING:\n import b", "b": "import a", "c": "import c"})
        self.assertEqual(cyclic_components(graph), [("a", "b"), ("c",)])

    def test_a_diamond_is_not_a_cycle(self):
        graph = self.graph({"a": "import b, c", "b": "import d", "c": "import d", "d": ""})
        self.assertEqual(cyclic_components(graph), [])

    def test_dotted_imports_and_literal_dynamic_imports_include_the_leaf_module(self):
        graph = self.graph({"a": "from importlib import import_module as load\nload('pkg.b')",
                            "pkg.b": "import a"})
        self.assertEqual(cyclic_components(graph), [("a", "pkg.b")])
        graph = self.graph({"a": "import pkg.b", "pkg.b": "import a"})
        self.assertEqual(cyclic_components(graph), [("a", "pkg.b")])

    def test_new_cycles_and_stale_cycle_budget_fail(self):
        self.assertTrue(growth_problems({"scc": 2}, {"scc": 1}))
        self.assertTrue(growth_problems({"scc": 0}, {"scc": 1}))
        self.assertEqual(growth_problems({"scc": 1}, {"scc": 1}), [])

    def test_sloc_growth_needs_a_reason_for_that_exact_increase(self):
        self.assertTrue(growth_problems({"sloc": 12}, {"sloc": 10}))
        self.assertTrue(growth_problems({"sloc": 8}, {"sloc": 10}))
        self.assertTrue(growth_problems({"sloc": 12}, {"sloc": 10, "sloc_growth": {"from": 10, "to": 12, "why": ""}}))
        self.assertEqual(growth_problems({"sloc": 12}, {
            "sloc": 10, "sloc_growth": {"from": 10, "to": 12, "why": "ENUMTOTAL adds architecture rules and regression tests"},
        }), [])

    def test_a_reason_does_not_buy_an_unrecorded_increase(self):
        self.assertTrue(growth_problems({"sloc": 13}, {
            "sloc": 10, "sloc_growth": {"from": 10, "to": 12, "why": "new invariant"},
        }))
