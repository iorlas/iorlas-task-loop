"""tl-7k8.8: a bead labelled needs:<resource> is picked only on a host that has the resource, with a typed skip that says why; the
engine only adds the label (never removes one), under the claim's fence."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from taskloop.app.loop import hosts
from taskloop.app.loop.queue import QueueRule
from taskloop.contracts.bead import Bead
from taskloop.contracts.checks import Check
from taskloop.contracts.config import EngineConfig, HostResources, ResourceSpec
from taskloop.contracts.ids import BeadId, CheckId
from taskloop.domain.checks import affinity

CFG = EngineConfig(resources={"unity": ResourceSpec(limit=1)})
NONE = HostResources(resources=[])
UNITY = HostResources(resources=["unity"])


def bead(*labels):
    return Bead(id=BeadId("t-1"), title="t", status="open", description="do it", acceptance_criteria="- works", labels=list(labels))


class Pick(unittest.TestCase):
    def rank(self, rec, *labels):
        rule = QueueRule(mock.Mock(), CFG, {}, lambda _b: "", hosted=lambda b: hosts.skip_of(CFG, rec, b))
        return rule.rank([bead(*labels)], "")

    def test_a_host_without_the_resource_skips_the_bead_and_says_why(self):
        q = self.rank(NONE, "needs:unity")
        self.assertEqual((q.ranked, [(s.bead, s.skip.kind) for s in q.skipped]), ([], [("t-1", "needs")]))
        self.assertIn("needs unity", q.skipped[0].skip.why)

    def test_a_host_with_the_resource_takes_it(self):
        self.assertEqual([r.bead.id for r in self.rank(UNITY, "needs:unity").ranked], ["t-1"])

    def test_no_host_file_means_every_declared_resource(self):
        self.assertEqual([r.bead.id for r in self.rank(None, "needs:unity").ranked], ["t-1"])

    def test_a_bead_with_no_needs_or_an_undeclared_one_is_taken_anywhere(self):
        self.assertEqual([r.bead.id for r in self.rank(NONE).ranked], ["t-1"])
        self.assertEqual([r.bead.id for r in self.rank(NONE, "needs:nobody-declared").ranked], ["t-1"])


class Planned(unittest.TestCase):
    def test_the_resources_a_host_lacks_that_a_touched_check_needs(self):
        unity = Check(id=CheckId("u"), cmd="u", inputs=["client/**"], needs=["unity"])
        other = Check(id=CheckId("o"), cmd="o", inputs=["docs/**"])
        self.assertEqual(affinity.planned([unity, other], ["client/a.cs"], CFG, NONE), ["unity"])
        self.assertEqual(affinity.planned([unity, other], ["docs/a.md"], CFG, NONE), [])
        self.assertEqual(affinity.planned([unity, other], ["client/a.cs"], CFG, UNITY), [])


if __name__ == "__main__":
    unittest.main()
