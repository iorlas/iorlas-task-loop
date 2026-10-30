"""tl-7y6.24: a worker that leaves the task branch or adds a worktree fails the bead (FAULT_ENGINE) with what moved."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as te
from support import fake_route, gitq
from support.spawn import port_git, real_spawner

from taskloop.app.run import engine
from taskloop.app.wire import slots as wslots
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId


class Stray(fake_route.Script):
    """A script whose writer runs `git ARGS` in its cwd, the first time it is called."""

    def __init__(self, answers, args=None):
        super().__init__(answers)
        self.args = args

    def reply(self, role, prompt, schema, cwd, resume, *a, **kw):
        if role == "worker" and self.args:
            gitq.git(*self.args(cwd), cwd=cwd)
            self.args = None
        return super().reply(role, prompt, schema, cwd, resume, *a, **kw)


class Strays(te.EngineTest):
    def go(self, args=None):
        script = Stray({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]}, args)
        self.raised = []
        real = engine.Engine.blocked_for

        def spy(this, why, kind, *a, **kw):
            self.raised.append((kind, why))
            return real(this, why, kind, *a, **kw)

        with te.delegate_stack(script), mock.patch.object(engine.Engine, "blocked_for", spy):
            eng = engine.Engine(
                BeadId("t-1"),
                str(self.wt),
                wslots.load_cfg(str(self.wt)),
                store=self.store,
                env=snapshot(),
                spawner=real_spawner(),
                git=port_git(),
            )
            return eng.run(), eng

    def test_a_worker_that_stays_passes(self):
        rc, _ = self.go()
        self.assertEqual(rc, 0)
        self.assertEqual(self.raised, [])

    def test_a_worker_that_checks_out_another_branch_fails_the_bead_with_the_branch_it_left(self):
        self.go(lambda cwd: ("checkout", "-b", "elsewhere"))
        self.assertEqual(self.raised, [("FAULT_ENGINE", "failed: the worker left task/t-1 for elsewhere")])

    def test_a_worker_that_adds_a_worktree_in_its_slot_fails_the_bead_with_its_path(self):
        path = {}
        def add(cwd):
            path["p"] = str((Path(cwd) / ".wt" / "extra").resolve())
            return ("worktree", "add", "--detach", path["p"])
        self.go(add)
        self.assertEqual(self.raised, [("FAULT_ENGINE", f"failed: the worker added worktree {path['p']}")])

    def test_a_worktree_added_outside_the_slot_is_not_the_workers(self):
        self.go(lambda cwd: ("worktree", "add", "--detach", str(Path(self.tmp.name) / "other-slot")))  # another slot, a base check
        self.assertEqual(self.raised, [])


if __name__ == "__main__":
    unittest.main()
