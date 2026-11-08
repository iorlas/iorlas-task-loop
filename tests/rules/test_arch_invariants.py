"""Application import allow-table and domain effect boundaries, checked over syntax."""
import ast

from rules.arch_invariants import domain_world_problems, slice_problems
from rules.arch_rules import graph_of, production_trees
from tltestkit.case import Case


class ArchitectureInvariants(Case):
    def test_slices_follow_the_allow_table(self):
        assert slice_problems(graph_of(production_trees())) == []

    def test_sideways_imports_and_new_slices_cannot_evade_the_allow_table(self):
        for source, target in (("taskloop.app.track.x", "tlgate.x"),
                               ("taskloop.app.new.x", "tlasks.x")):
            assert slice_problems({source: {target}})
        assert slice_problems({"tlland.x": {"tlgate.x"}}) == []

    def test_domain_touches_no_world(self):
        bad = [problem for module, tree in production_trees().items() if module.startswith(
            ('taskloop.domain.', 'tlgate.domain.', 'tlslots.liveness', 'tlslots.slot_env',
             'tlkernel.holds', 'tlasks.similar', 'tlasks.matchers', 'tlasks.timespec',
             'tlwork.write.matchers', 'tlwork.look.matchers', 'tlwork.plan.matchers', 'tlwork.plan.stored',
             'tlwork.work.', 'tlwork.prompts.', 'tlkernel.reviewunavailable', 'tlwork.review.findings'))
               for problem in domain_world_problems(module, tree)]
        assert bad == []

    def test_domain_rejects_aliases_of_world_calls_but_allows_pure_path_operations(self):
        for text in ('import os as o\no.getenv("X")', 'from time import time as clock\nclock()',
                     'import subprocess as s\ns.run(argv)', 'open(path)', 'p.read_text()',
                     'from socket import socket as S\nS()'):
            assert domain_world_problems('taskloop.domain.bad', ast.parse(text)), text
        assert domain_world_problems('taskloop.domain.good', ast.parse(
            "import os\nfrom pathlib import Path\nname = os.path.basename(path)\n"
            "name = Path(path).name\nprobe.exists(path)\n# open(path)\n"
        )) == []
