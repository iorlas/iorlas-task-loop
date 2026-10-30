"""The gate runs before the land lock (land_optimistic_tries); the lock covers fetch, rebase and push, and the gate only when main moved
under the outside gate more often than allowed. The pushed tree is always one the gate passed on the same base. Git is a small world
(a base tip that moves on fetch; a rebase gives the tree of the base it lands on); the gate's cache is a recorder with the engine's rule: a
green gate is a fact about a tree and its base (the per-check cache itself is tests/checks/test_gate_steps.py)."""
import contextlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.land.lander import Lander
from taskloop.contracts import fence
from taskloop.contracts.checks import CacheHit, CheckCacheEntry, CheckResult, CheckRun
from taskloop.contracts.config import CheckSpec, EngineConfig
from taskloop.contracts.ids import CheckId

REJECTED = (1, " ! [rejected]        HEAD -> main (fetch first)")
PUSHED = (0, "")


class Stop(Exception):
    def __init__(self, why: str, kind: str) -> None:
        super().__init__(why)
        self.why, self.kind = why, kind


class Doc:
    def __init__(self) -> None:
        self.rec: CheckCacheEntry | None = None

    def read(self) -> CheckCacheEntry | None:
        return self.rec

    def write(self, rec: CheckCacheEntry) -> None:
        self.rec = rec


class World:
    """origin/main moves to the next of `tips` on each fetch; the rebased tree is named after the base it sits on."""

    def __init__(self, tips: list[str], pushes: list[tuple[int, str]], reds: int = 0, tries: int = 2) -> None:
        self.tips, self.pushes, self.reds = list(tips), list(pushes), reds
        self.base, self.sat_on, self.events, self.gated, self.pushed, self.emitted = "b0", "b0", [], [], [], []
        self.doc, self.held, self.fixes = Doc(), False, []

        @contextlib.contextmanager
        def locked(*_):
            self.held = True
            self.events.append("enter")
            try:
                yield
            finally:
                self.held = False
                self.events.append("exit")

        @contextlib.contextmanager
        def stop_deferred():
            yield []
        self.host = SimpleNamespace(
            git=self.git, sh=self.sh, halt_point=lambda *a, **k: None,
            cfg=EngineConfig(base="origin/main", checks=[CheckSpec(id=CheckId("gate"), argv=["gate"], run="gate")], land=["git", "push"],
                             land_optimistic_tries=tries, max_fix_rounds=2, gate_timeout_min=1),
            wt=Path("/nonexistent"),
            store=None, claim=fence.offline("t-1"),
            bead="t-1", dry=False, landed_sha="", pending_land_validation="", fixes=0, gate_log=None, run_dir=Path("run"), killed=False,
            steps=SimpleNamespace(begin=lambda *a, **k: None, outcome=lambda *a: None, move=lambda *a: None),
            newfiles=SimpleNamespace(quarantine_strays=lambda: None), checkout=SimpleNamespace(fetch=self.fetch),
            log=SimpleNamespace(emit=self.emitted.append, note=lambda *_: None), waits=SimpleNamespace(locked=locked),
            land_lock_path=lambda: "lock", stop_deferred=stop_deferred, record_land=lambda sha: None, warn=lambda m: None,
            stores=SimpleNamespace(check_cache=SimpleNamespace(of=lambda _bead: self.doc)),
            checker=SimpleNamespace(gate_green=self.gate_green, run_items=self.run_items),
            plan_data=None, cases=SimpleNamespace(case_checks=lambda: []), checkpoints=SimpleNamespace(save=lambda **kw: None),
            stage_checks=SimpleNamespace(stoppable=lambda *a: self.events.append("checks") or SimpleNamespace(failed=[], unverified=[])),
            blocked_for=lambda why, kind, **kw: Stop(why, kind), fixer=SimpleNamespace(fix=self.fix))
        self.lander = Lander(self.host)

    def fetch(self) -> tuple[int, str]:
        self.events.append("fetch" + ("*" if self.held else ""))
        if self.tips:
            self.base = self.tips.pop(0)
        return 0, ""

    def git(self, *argv: str) -> str:
        if argv == ("rev-parse", "origin/main"):
            return self.base
        if argv == ("rev-parse", "HEAD^{tree}"):
            return f"tree@{self.sat_on}"
        if argv == ("rev-parse", "HEAD"):
            return f"head@{self.sat_on}"
        if argv == ("rev-parse", "--verify", "-q", "HEAD"):
            return ""  # the task branch's tip is not a landed commit
        raise AssertionError(argv)

    def sh(self, argv: list[str], **kw: Any) -> tuple[int, str]:
        if argv[:2] == ["git", "rebase"]:
            self.events.append("rebase")
            self.sat_on = self.base
            return 0, ""
        if argv == ["git", "push", "--no-verify"]:
            self.events.append("push")
            self.pushed.append((self.sat_on, self.base, self.held, f"tree@{self.sat_on}" in self.gate_passed()))
            return self.pushes.pop(0)
        if argv == ["gate"]:
            self.events.append("gate*" if self.held else "gate")
            self.gated.append(self.sat_on)
            if self.reds:
                self.reds -= 1
                return 1, "red"
            return 0, ""
        raise AssertionError(argv)

    def gate_green(self) -> bool:
        return f"tree@{self.sat_on}" in self.gate_passed()

    def run_items(self, items: list[Any]) -> CheckRun:
        rc, tail = self.sh(["gate"])
        res = CheckResult(id=CheckId("gate"), cmd="gate", group="tests", exit=rc, status="failed" if rc else "passed", tail=tail)
        if not rc:
            self.doc.rec = CheckCacheEntry(key=f"tree@{self.sat_on} {self.base}", whole={"gate": CacheHit(result=res)})
        return CheckRun(round=1, results=[res])

    def gate_passed(self) -> list[str]:
        rec = self.doc.rec
        return [rec.key.split()[0]] if rec and rec.whole and rec.key.split()[1] == self.base else []

    def fix(self, kind: str, text: str) -> str:
        self.events.append("fix:" + kind)
        self.fixes.append(kind)
        return "accept"

    def land(self) -> str:
        self.host.sh = self.sh
        return self.lander.land()


class GateOutsideLock(unittest.TestCase):
    def test_main_unchanged_gates_once_outside_and_the_push_needs_no_second_gate(self):
        w = World(["b0", "b0"], [PUSHED])
        w.land()
        self.assertEqual(w.gated, ["b0"])
        self.assertEqual(w.events, ["fetch", "rebase", "gate", "enter", "fetch*", "rebase", "push", "exit"])
        self.assertEqual(w.pushed, [("b0", "b0", True, True)])
        self.assertEqual([(t.gate, t.failing) for t in w.emitted if hasattr(t, "gate")], [("outside", ""), ("cached", "")])

    def test_main_moved_lets_the_lock_go_and_gates_outside_again_up_to_the_tries_then_inside(self):
        w = World(["b0", "b1", "b1", "b2", "b2", "b3", "b3"], [PUSHED])
        w.land()
        self.assertEqual(w.gated, ["b0", "b1", "b2", "b3"])  # outside, again outside twice, then inside the lock
        self.assertEqual(w.events.count("gate"), 3)
        self.assertEqual(w.events.count("gate*"), 1)
        self.assertEqual(w.events.count("enter"), 3)
        self.assertEqual([p[:2] for p in w.pushed], [("b3", "b3")])
        wheres = [t.gate for t in w.emitted if hasattr(t, "gate")]
        self.assertEqual(wheres, ["outside", "", "outside", "", "outside", "inside"])
        self.assertEqual([t.failing for t in w.emitted if hasattr(t, "gate")][1], "stale")

    def test_no_tries_gates_inside_the_lock_as_before(self):
        w = World(["b0"], [PUSHED], tries=0)
        w.land()
        self.assertEqual(w.events, ["enter", "fetch*", "rebase", "gate*", "push", "exit"])

    def test_a_lost_push_race_gates_outside_again_and_every_pushed_tree_passed_on_its_base(self):
        w = World(["b0", "b0", "b1", "b1", "b1"], [REJECTED, PUSHED])
        w.land()
        self.assertEqual(w.gated, ["b0", "b1"])
        self.assertEqual(w.events.count("gate"), 2)
        self.assertTrue(all(p[3] and p[0] == p[1] for p in w.pushed))
        self.assertEqual(len(w.pushed), 2)

    def test_a_red_gate_outside_goes_to_a_fix_round_without_ever_taking_the_lock(self):
        w = World(["b0", "b0", "b0"], [PUSHED], reds=1)
        w.land()
        self.assertEqual(w.events[:5], ["fetch", "rebase", "gate", "fix:gate", "fetch"])
        self.assertEqual(w.events.index("enter"), w.events.index("fix:gate") + 4)  # a second gate (green) before the lock
        first = next(t for t in w.emitted if hasattr(t, "gate"))
        self.assertEqual((first.gate, first.failing), ("outside", "gate"))

    def test_main_moving_under_the_gate_is_not_a_fix_round(self):
        w = World(["b0", "b1", "b1", "b1", "b1"], [PUSHED])
        w.land()
        self.assertEqual(w.fixes, [])


if __name__ == "__main__":
    unittest.main()
