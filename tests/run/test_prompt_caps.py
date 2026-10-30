"""PROMPTCAP: every delegate call checks its input against its role's cap before it spawns. Over the cap, the run ends with a
Task fault (ASK_TICKET: the bead's brief is too big) and the call is never made; at the cap, it goes through."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as te
from support import fake_route

from taskloop.app.run import engine
from taskloop.app.wire import slots as wslots
from taskloop.contracts.ids import BeadId
from taskloop.domain import outcome as oc
from taskloop.domain.lanes import caps
from taskloop.domain.lanes.roles import ROLES


class Table(unittest.TestCase):
    def test_every_role_the_engine_calls_has_a_cap(self):
        self.assertLessEqual(set(ROLES.values()), set(caps.CAPS))

    def test_at_the_cap_passes_and_one_byte_over_is_refused(self):
        for role, cap in caps.CAPS.items():
            with self.subTest(role):
                self.assertIsNone(caps.check(role, "x" * cap))
                over = caps.check(role, "x" * (cap + 1))
                self.assertEqual(over, caps.Over(role, cap + 1, cap))

    def test_the_size_is_bytes_not_characters(self):
        self.assertIsNone(caps.check("worker", "é" * (caps.CAPS["worker"] // 2)))
        self.assertIsNotNone(caps.check("worker", "é" * (caps.CAPS["worker"] // 2 + 1)))

    def test_an_over_cap_brief_is_a_task_fault(self):
        self.assertIsInstance(oc.fault_of(oc.Kind.ASK_TICKET), oc.Task)

    def test_the_caps_clear_the_real_prompts(self):
        biggest = max(p.stat().st_size for p in (Path(__file__).resolve().parents[1] / "fixtures" / "prompts").glob("*.txt"))
        self.assertLess(biggest * 2, min(caps.CAPS.values()))


class Refusal(te.EngineTest):
    def go(self, role, script):
        c = wslots.load_cfg(str(self.wt))
        with te.delegate_stack(script), mock.patch.dict(caps.CAPS, {role: 1}):
            self.eng = engine.Engine(BeadId("t-1"), str(self.wt), c, store=self.store)
            rc = self.eng.run()
        return rc

    def refused(self, role, answers):
        script = fake_route.Script(answers)
        rc = self.go(role, script)
        self.assertNotEqual(rc, 0)
        self.assertNotIn(role, [r for r, _, _ in script.calls])  # nothing spawned for the refused role
        self.assertEqual(self.eng.kind, oc.Kind.ASK_TICKET)
        self.assertIsInstance(oc.fault_of(self.eng.kind), oc.Task)
        self.assertIn(f"over the 0 KB cap of the {role} role", self.eng.why)
        return script

    def test_an_over_cap_planner_brief_spawns_nothing(self):
        script = self.refused("planner", {"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        self.assertEqual(script.calls, [])

    def test_an_over_cap_writer_brief_spawns_no_writer_and_no_reviewer(self):
        script = self.refused("worker", {"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        self.assertEqual([r for r, _, _ in script.calls], ["planner"])

    def test_an_over_cap_reviewer_brief_spawns_no_reviewer(self):
        self.refused("reviewer", {"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})


for _name in dir(te.EngineTest):  # the engine fixture only
    if _name.startswith("test_") and _name not in Refusal.__dict__:
        setattr(Refusal, _name, None)


if __name__ == "__main__":
    unittest.main()
