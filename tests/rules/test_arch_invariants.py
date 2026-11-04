"""Application import allow-table and domain effect boundaries, checked over syntax."""
import ast
import unittest

from rules.arch_invariants import domain_world_problems, slice_problems
from rules.arch_ratchets import graph_of, production_trees


class ArchitectureInvariants(unittest.TestCase):
    def test_slices_follow_the_allow_table(self):
        self.assertEqual(slice_problems(graph_of(production_trees())), [])

    def test_sideways_imports_and_new_slices_cannot_evade_the_allow_table(self):
        for source, target in (("taskloop.app.asks.x", "taskloop.app.checks.x"),
                               ("taskloop.app.new.x", "taskloop.app.asks.x")):
            self.assertTrue(slice_problems({source: {target}}))
        self.assertEqual(slice_problems({"taskloop.app.land.x": {"taskloop.app.checks.x"}}), [])

    def test_domain_touches_no_world(self):
        bad = [problem for module, tree in production_trees().items() if module.startswith('taskloop.domain.')
               for problem in domain_world_problems(module, tree)]
        self.assertEqual(bad, [])

    def test_domain_rejects_aliases_of_world_calls_but_allows_pure_path_operations(self):
        for text in ('import os as o\no.getenv("X")', 'from time import time as clock\nclock()',
                     'import subprocess as s\ns.run(argv)', 'open(path)', 'p.read_text()',
                     'from socket import socket as S\nS()'):
            self.assertTrue(domain_world_problems('taskloop.domain.bad', ast.parse(text)), text)
        self.assertEqual(domain_world_problems('taskloop.domain.good', ast.parse(
            "import os\nfrom pathlib import Path\nname = os.path.basename(path)\n"
            "name = Path(path).name\nprobe.exists(path)\n# open(path)\n"
        )), [])
