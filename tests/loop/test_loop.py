"""The loop verbs: the engine loop's pick, run and stop."""
import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401

# isort: split
import tl  # noqa: E402
from support import (  # noqa: E402
    looptest,
    tlbd,
)
from support.narrow import must  # noqa: E402

from taskloop.adapters import (  # noqa: E402
    ident,
)
from taskloop.app.launch import loop as wloop  # noqa: E402
from taskloop.app.loop.core import Core  # noqa: E402
from taskloop.app.loop.loop import parse_handover  # noqa: E402
from taskloop.app.loop.take import Taker  # noqa: E402
from taskloop.app.track import trail  # noqa: E402
from taskloop.contracts import wire  # noqa: E402
from taskloop.contracts.loop import Carry, LoopState  # noqa: E402
from taskloop.contracts.ports import WaitTimeout  # noqa: E402


def bead(id, priority=2, parent=None, labels=(), type="task"):
    b = {"id": id, "title": "bead " + id, "status": "open", "priority": priority, "issue_type": type,
         "description": "do " + id, "acceptance_criteria": "- " + id + " works"}  # what the bead lint asks of a bead
    if parent:
        b["parent"] = parent
    if labels:
        b["labels"] = list(labels)
    return b


LIVE_PID = "a live pid that is not this process: a real sleep child (an engine lock, a second loop, a waiter)"


class FakeBd:
    """bd as the loop calls it: ready, show, claim, unclaim, heartbeat and the slot beads."""

    def __init__(self, beads=(), slots=0, parents=None):
        self.beads: dict[str, dict[str, Any]] = {b["id"]: dict(b) for b in beads}
        self.parents = dict(parents or {})  # beads not in the ready list (epics): id -> parent
        self.slots: dict[str, dict[str, Any]] = {f"sl-{i}": {"id": f"sl-{i}", "title": f"slot {ident.hostname()} s{i}", "status": "open",
                                    "assignee": ""} for i in range(1, slots + 1)}
        self.taken_by_other = set()  # claims another session wins
        self.calls = []

    def __call__(self, *a, cwd=None, check=False):
        self.calls.append(a)
        if a[0] == "update" and ("--set-metadata" in a or "--unset-metadata" in a):
            self._metadata(a)
        out, rc = self._answer(a)
        return mock.Mock(returncode=rc, stdout=out, stderr="")

    def _metadata(self, a):
        meta = (self.beads.get(a[1]) or self.slots.get(a[1]) or {}).setdefault("metadata", {})
        for i, x in enumerate(a[:-1]):
            if x == "--set-metadata":
                k, _, v = a[i + 1].partition("=")
                meta[k] = v
            elif x == "--unset-metadata":
                meta.pop(a[i + 1], None)

    def _answer(self, a):
        """(stdout, returncode) of one bd call."""
        out, rc = "", 0
        if a[0] == "ready":
            label = a[a.index("--label") + 1] if "--label" in a else None
            out = json.dumps([b for b in self.beads.values() if b["status"] == "open"
                              and (label is None or label in b.get("labels", []))])
        elif a[0] == "list" and "slot" in a:
            out = json.dumps(list(self.slots.values()))
        elif a[0] == "list" and "in_progress" in a:
            out = json.dumps([b for b in list(self.beads.values()) + list(self.slots.values())
                              if b.get("status") == "in_progress"])
        elif a[0] == "show":
            b = self.beads.get(a[1]) or self.slots.get(a[1])
            out = json.dumps([b] if b else [{"id": a[1], "parent": self.parents.get(a[1])}])
        elif a[0] == "update" and "--claim" in a:
            rc = self._claim(a)
        elif a[0] == "unclaim":  # as bd: only the current assignee frees its own claim; --force frees another's
            rc = self._unclaim(a)
        elif a[0] == "update" and ("--status" in a or "--assignee" in a):
            rc = self._set_status(a)
        return out, rc

    def _claim(self, a):
        b = self.beads.get(a[1]) or self.slots.get(a[1])
        if a[1] in self.taken_by_other or must(b).get("status") != "open" or must(b).get("assignee") not in (None, "", ident.actor()):
            return 1  # bd 1.3: an open bead still assigned to another actor (a paused run's) refuses the claim
        must(b).update(status="in_progress", assignee=ident.actor())
        return 0

    def _unclaim(self, a):
        b = self.beads.get(a[1]) or self.slots.get(a[1])
        if "--force" in a or must(b).get("assignee") in (None, "", ident.actor()):
            must(b).update(status="open", assignee="")
            return 0
        return 1

    def _set_status(self, a):
        b = self.beads.get(a[1]) or self.slots[a[1]]
        if any(flag in a and b.get(key) != a[a.index(flag) + 1]
               for flag, key in (("--if-assignee", "assignee"), ("--if-status", "status"))):
            return 13
        for flag, key in (("--status", "status"), ("--assignee", "assignee")):
            if flag in a:
                b[key] = a[a.index(flag) + 1]
        return 0


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.repo = self.home / "repo"
        self.repo.mkdir()
        env = {"XDG_CONFIG_HOME": str(self.home / "cfg"), "APPDATA": str(self.home / "cfg"), "CLAUDE_CONFIG_DIR": str(self.home / "claude"),
               "CLAUDE_CODE_SESSION_ID": "abcdef12-3456"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        self.addCleanup(self.env.stop)  # last: the patches a subclass starts restore their snapshot first
        os.environ.pop("TASK_LOOP_ACTOR", None)
        self.cwd = os.getcwd()
        os.chdir(self.repo)  # the repo `tl` helpers see when no --repo is given

    def main(self, argv, **kw):
        """tl.main on this test's clock and install (`self.clock`, `self.here`, when the test has them)."""
        clock = getattr(self, "clock", trail.now)
        kw.setdefault("now", clock.now if hasattr(clock, "now") else clock)
        kw.setdefault("here", getattr(self, "here", None) or tl.HERE)
        return tl.main(argv, **kw)

    @contextlib.contextmanager
    def running_from(self, here):
        """The loop runs from the install `here` for the length of a `with` (a newer version, after the move)."""
        before = getattr(self, "here", None)
        self.here = here
        try:
            yield
        finally:
            self.here = before

    def tearDown(self):
        os.chdir(self.cwd)

        def force(fn, path, _):
            os.chmod(path, stat.S_IWRITE)
            fn(path)
        shutil.rmtree(self.tmp.name, onerror=force)
        with contextlib.suppress(OSError):
            self.tmp.cleanup()

    def config(self, **engine_cfg):
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": engine_cfg}))

    def fake(self, *beads, **kw):
        f = FakeBd(beads, **kw)
        tlbd.install(self, f)
        return f


def rec(outcome, **kw):
    return dict({"v": 2, "bead": "x", "outcome": outcome, "why": "", "run": "run-1", "log": "/e.jsonl", "minutes": 1.0, "rounds": 1,
                 "tests_added": 2, "asked": outcome == "parked", "retry_after": 0.0}, **kw)


class Clock:
    def __init__(self):
        self.t, self.naps = 1_800_000_000.0, []
        self.t0 = self.t

    def __call__(self):
        return self.t

    def nap(self, secs, *a, **kw):
        self.naps.append(round(secs))
        self.t += max(secs, 1)


class FakeChild:
    """run-task as the loop starts it: writes its outcome file and leaves the bead as the engine would."""
    AFTER: ClassVar[Any] = {"landed": "closed", "parked": "blocked", "failed": "blocked", "paused": "open", "taken": "open"}

    def __init__(self, test, cmd, extra=None):
        self.test, self.cmd, self.extra = test, cmd, extra or {}
        self.bead = cmd[cmd.index("run-task") + 1]
        self.out = cmd[cmd.index("--outcome-file") + 1]
        self.pid, self.terminated = 4242, False
        self.returncode: int | None = None
        self.polls = test.hold.pop(self.bead, 0)
        test.started.append((self.bead, cmd[cmd.index("--slot") + 1] if "--slot" in cmd else None))
        if test.during:
            test.during.pop(0)()

    def wait(self, timeout=None):
        if self.polls and not self.terminated:
            self.polls -= 1
            self.test.clock.t += timeout or 0
            must(timeout)
            raise WaitTimeout(str(timeout))
        r = rec("failed", why="failed: stopped (SIGTERM)") if self.terminated else self.test.script[self.bead].pop(0)
        after = r.pop("after", None) if r is not None else None
        if r is not None:
            Path(self.out).write_text(json.dumps(dict(r, bead=self.bead)))
            b = self.test.bd.beads[self.bead]
            b["status"] = after or (
                "open" if r.get("kind", "").startswith(("fault_", "pause_")) else self.AFTER.get(r["outcome"], b["status"])
            )
            if b["status"] != "in_progress":
                b["assignee"] = b["assignee"] if b["status"] == "blocked" else ""
        self.returncode = 0 if r and r["outcome"] == "landed" else 2
        return self.returncode

    def terminate(self):
        self.terminated, self.returncode = True, -15

    def stop(self, grace):
        self.terminate()

    def stop_async(self, grace):
        self.terminate()


class LoopBase(Base):
    """The loop with run-task faked (FakeChild) and slot setup skipped; no tests of its own."""

    def setUp(self):
        super().setUp()
        self.clock = Clock()
        self.roles: Callable[[], dict[str, dict[str, Any]]] = lambda: {
            "worker": {"usable": True}
        }  # delegate's `status --json` roles{}: a test makes it a function of the clock
        self.script, self.hold, self.started, self.during = {}, {}, [], []
        for p in (mock.patch.object(Core, "nap", self.clock.nap),
                  mock.patch.object(wloop, "delegate_route", return_value="/fake/route.py"),
                  mock.patch.object(wloop.dg, "role_status", side_effect=lambda route, env: self.roles()),
                  mock.patch.object(wloop.real, "spawner", return_value=mock.Mock(
                      start_held=lambda cmd, out=None, extra=None, **kw: (FakeChild(self, cmd, extra), mock.Mock()))),
                  mock.patch.object(Taker, "prepare", return_value=None)):
            p.start()
            self.addCleanup(p.stop)
        (self.repo / ".task-loop.json").write_text(json.dumps({"slots": {"count": 2}, "engine": {}}))

    def beads(self, script, slots=2, **kw):
        """script: {bead id: [outcome record, ...]} in id order."""
        self.script = {k: list(v) for k, v in script.items()}
        self.bd = self.fake(*[bead(i) for i in script], slots=slots, **kw)
        return self.bd

    def run_loop(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = self.main(["loop", "--repo", str(self.repo), *args])
        self.out = out.getvalue()
        return rc

    def lines(self):
        f = looptest.log(str(self.repo))
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


class Loop(LoopBase):


    # tl-7y6.2.8: a paused bead wakes when delegate says its role is usable, not at a clock


    def test_the_held_beads_go_across_a_move_to_a_newer_install(self):
        st = LoopState(pid=1, started=1.0, t=1.0, repo="r", version="0.0.1", code_dir="/x", actor="tl-a",
                       carry=Carry(gated={"x-1": ("worker", 5.0)}, ran=1))
        got, why = parse_handover(json.dumps(wire.dump(st)))
        assert got is not None
        self.assertEqual((got.carry.gated, got.carry.ran, why), ({"x-1": ("worker", 5.0)}, 1, ""))
        got, why = parse_handover(json.dumps({"gated": {"x-1": ["worker", 5.0]}, "ran": 1}))  # an old shape: absent, never trusted
        self.assertIsNone(got)
        self.assertIn("v=None", why)


    def other_loop(self):
        """A second live loop on the repo: its state names a live process that is not this one."""
        k = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (k.kill(), k.wait()))
        looptest.write_state(str(self.repo), pid=k.pid, started=self.clock.t, bead="x-9", slot="s2", since=self.clock.t)
        return k


if __name__ == "__main__":
    unittest.main()
