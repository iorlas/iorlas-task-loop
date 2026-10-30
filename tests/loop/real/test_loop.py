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
import time
import unittest
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: E402, F401

# isort: split
import tl  # noqa: E402
from support import (  # noqa: E402
    looptest,
    tlbd,
)
from support.narrow import must  # noqa: E402
from support.waits import until  # noqa: E402

from taskloop.adapters import (  # noqa: E402
    gitrepo,
    ident,
)
from taskloop.adapters.storm import storm_path, write_storm  # noqa: E402
from taskloop.app.launch import loop as wloop  # noqa: E402
from taskloop.app.loop.core import Core  # noqa: E402
from taskloop.app.loop.take import Taker  # noqa: E402
from taskloop.app.slots import verbs  # noqa: E402
from taskloop.app.track import trail  # noqa: E402
from taskloop.app.wire import slots as wslots  # noqa: E402
from taskloop.contracts.config import LoopConfig  # noqa: E402
from taskloop.domain import outcome as oc  # noqa: E402


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
    """bd as the loop calls it: ready, show, claim, unclaim, heartbeat, reclaim and the slot beads."""

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


class Queue(Base):
    def order(self):
        ranked, _ = looptest.queue(str(self.repo))
        return [b.id for b, _ in ranked]

    def test_defaults_take_every_ready_bead_by_priority_then_lowest_id(self):
        self.fake(bead("x-3", 2), bead("x-10", 1), bead("x-2", 2))
        self.assertEqual(self.order(), ["x-10", "x-2", "x-3"])

    def test_ids_sort_naturally(self):
        self.fake(bead("fld.26.10"), bead("fld.26.9"), bead("fld.3"))
        self.assertEqual(self.order(), ["fld.3", "fld.26.9", "fld.26.10"])

    def test_pick_label_limits_the_queue(self):
        self.config(pick_label="auto")
        f = self.fake(bead("x-1"), bead("x-2", labels=["auto"]))
        self.assertEqual(self.order(), ["x-2"])
        self.assertIn(("ready", "-n", "0", "--label", "auto"), f.calls)

    def test_skip_labels_epics_and_slots_are_skipped_with_a_reason(self):
        self.config(skip_labels=["owner-taste", "needs-info"])
        self.fake(bead("x-1", labels=["owner-taste"]), bead("x-2"), bead("x-3", type="epic"), bead("x-4", labels=["slot"]),
                  bead("x-5", labels=["needs-info"]))
        ranked, skipped = looptest.queue(str(self.repo))
        self.assertEqual([b.id for b, _ in ranked], ["x-2"])
        self.assertEqual(dict(skipped), {"x-1": "label owner-taste", "x-3": "an epic", "x-4": "a slot",
                                         "x-5": "label needs-info"})

    def test_a_bead_citing_material_outside_the_repo_is_skipped_as_needing_inlined_facts(self):
        """tl-f52: the Drop study that no worktree can read stopped tl-7y6.6.15 after 4 minutes."""
        cites = dict(bead("x-1"), description="Follow section 2 of ~/Documents/Drop/arch-study-1025/84-self-hosting.md")
        clean = dict(bead("x-2"), description="Edit skills/task-loop/engine.py; see docs/design/stages.md")
        escaped = dict(bead("x-3", labels=["facts-inline"]), description="Per study 84 s.2 (facts below): do X")
        self.fake(cites, clean, escaped)
        ranked, skipped = looptest.queue(str(self.repo))
        self.assertEqual([b.id for b, _ in ranked], ["x-2", "x-3"])
        self.assertEqual([i for i, _ in skipped], ["x-1"])
        self.assertIn("needs inlined facts", skipped[0][1])

    def test_priority_comes_before_epic_order(self):
        self.config(epic_order=["e-1", "e-2"])
        self.fake(bead("x-1", 2, parent="e-1"), bead("x-2", 1, parent="e-2"))
        self.assertEqual(self.order(), ["x-2", "x-1"])

    def test_epic_order_within_a_priority_nested_parents_count_and_others_come_last(self):
        self.config(epic_order=["e-2", "e-1"])
        self.fake(bead("x-1", parent="e-1"), bead("x-2"), bead("x-3", parent="e-2.1"), bead("x-4", parent="e-1"),
                  parents={"e-2.1": "e-2", "e-2": None, "e-1": None})
        self.assertEqual(self.order(), ["x-3", "x-1", "x-4", "x-2"])

    def test_epic_only_drops_beads_under_no_listed_epic(self):
        self.config(epic_order=["e-1"], epic_only=True)
        self.fake(bead("x-1", parent="e-1"), bead("x-2", parent="e-9"), parents={"e-9": None})
        ranked, skipped = looptest.queue(str(self.repo))
        self.assertEqual([b.id for b, _ in ranked], ["x-1"])
        self.assertEqual(dict(skipped), {"x-2": "under no epic in epic_order (epic_only)"})

    def test_each_place_says_which_rule_put_it_there(self):
        self.config(epic_order=["e-1"])
        self.fake(bead("x-1", 1), bead("x-2", 2, parent="e-1"), bead("x-3", 2), bead("x-4", 2))
        ranked, _ = looptest.queue(str(self.repo))
        self.assertEqual([r for _, r in ranked], ["priority P1 before P2", "epic e-1 (1st in epic_order)",
                                                  "lowest id", "last"])

    def test_tl_next_prints_the_pick_the_reason_and_the_next_few_without_claiming(self):
        self.config(skip_labels=["owner-taste"])
        f = self.fake(bead("x-1"), bead("x-2"), bead("x-3", labels=["owner-taste"]))
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(self.main(["next", "--repo", str(self.repo)]), 0)
        out = buf.getvalue()
        self.assertIn("NEXT x-1", out)
        self.assertIn("lowest id", out)
        self.assertIn("x-2", out)
        self.assertIn("skip x-3: label owner-taste", out)
        self.assertFalse([c for c in f.calls if "--claim" in c])

    def test_tl_next_json_and_an_empty_queue(self):
        self.fake(bead("x-1"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.main(["next", "--repo", str(self.repo), "--json"])
        d = json.loads(buf.getvalue())
        self.assertEqual(d["pick"]["id"], "x-1")
        self.fake()
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(self.main(["next", "--repo", str(self.repo)]), 1)
        self.assertIn("NONE", buf.getvalue())


class QueueRuleFromBase(Base):
    """The queue rule is read from the base branch after a fetch, not from a main checkout nobody pulled."""

    def setUp(self):
        super().setUp()
        os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        self.origin, self.other = self.home / "o.git", self.home / "other"
        self.repo.rmdir()
        self.sh("git", "init", "-q", "--bare", "-b", "main", str(self.origin), cwd=self.home)
        self.sh("git", "clone", "-q", str(self.origin), str(self.other), cwd=self.home)
        self.push_rule({"engine": {"skip_labels": ["owner-taste"]}})
        self.sh("git", "clone", "-q", str(self.origin), str(self.repo), cwd=self.home)

    def sh(self, *a, cwd):
        subprocess.run(list(a), cwd=cwd, check=True, capture_output=True)

    def push_rule(self, cfg):
        """Another worktree pushes a new .task-loop.json; the main checkout is not pulled."""
        (self.other / ".task-loop.json").write_text(json.dumps(cfg))
        self.sh("git", "add", "-A", cwd=self.other)
        self.sh("git", "commit", "-qm", "queue rule", cwd=self.other)
        self.sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.other)

    def test_tl_next_uses_the_rule_pushed_to_the_base_branch_not_the_stale_working_tree(self):
        self.push_rule({"engine": {"skip_labels": ["later"]}})
        self.fake(bead("x-1", labels=["later"]), bead("x-2", labels=["owner-taste"]))
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(self.main(["next", "--repo", str(self.repo)]), 0)
        out = buf.getvalue()
        self.assertIn("NEXT x-2", out)
        self.assertIn("skip x-1: label later", out)
        self.assertIn("owner-taste", (self.repo / ".task-loop.json").read_text())  # the working tree stays behind

    def test_the_loop_queue_fetches_before_it_reads_the_rule(self):
        self.push_rule({"engine": {"epic_order": [], "pick_label": "go"}})
        self.fake(bead("x-1"), bead("x-2", labels=["go"]))
        ranked, _ = looptest.queue(str(self.repo))
        self.assertEqual([b.id for b, _ in ranked], ["x-2"])

    def test_engine_load_cfg_reads_the_base_branch_with_the_base_the_working_tree_names(self):
        self.push_rule({"engine": {"brief_kb": 7}})
        self.sh("git", "fetch", "-q", "origin", cwd=self.repo)
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": {"brief_kb": 99}}))
        self.assertEqual(wloop.wslots.load_cfg(str(self.repo)).brief_kb, 7)

    def test_no_remote_falls_back_to_the_working_tree(self):
        self.sh("git", "remote", "remove", "origin", cwd=self.repo)
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": {"skip_labels": ["later"]}}))
        self.fake(bead("x-1", labels=["later"]), bead("x-2"))
        ranked, skipped = looptest.queue(str(self.repo))
        self.assertEqual([b.id for b, _ in ranked], ["x-2"])
        self.assertEqual(skipped, [("x-1", "label later")])


def rec(outcome, **kw):
    return dict({"v": 1, "outcome": outcome, "why": "", "run": "run-1", "log": "/e.jsonl", "minutes": 1.0, "rounds": 1,
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
            raise subprocess.TimeoutExpired(self.cmd, must(timeout))
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
                  mock.patch.object(wloop.dg, "role_status", side_effect=lambda route: self.roles()),
                  mock.patch.object(wloop, "spawn", side_effect=lambda cmd, log, extra: (FakeChild(self, cmd, extra), mock.Mock())),
                  mock.patch.object(wloop.sproc, "stop_tree", side_effect=lambda p, **kw: p.terminate() or ()),
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
    def test_runs_ready_beads_in_a_row_each_in_a_free_slot_then_drains(self):
        bd = self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")], "x-3": [rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2", "x-3"])
        self.assertTrue(all(s == "s1" for _, s in self.started))
        self.assertTrue(all(s["status"] == "open" and not s["assignee"] for s in bd.slots.values()))  # released
        self.assertIn("DRAINED", self.out)
        self.assertEqual([ln["outcome"] for ln in self.lines()], ["landed"] * 3)

    def test_each_bead_is_claimed_by_the_loop_before_it_runs_and_the_child_gets_its_actor(self):
        bd = self.beads({"x-1": [rec("landed")]})
        self.run_loop()
        self.assertIn(("update", "x-1", "--claim"), bd.calls)
        self.assertTrue(os.environ.get("TASK_LOOP_ACTOR"))

    def test_a_log_line_per_bead_has_the_fields_the_owner_reviews(self):
        self.beads({"x-1": [rec("parked", run="tr-9", log="/eng/x-1.jsonl")]})
        self.run_loop()
        ln = self.lines()[0]
        for k in ("ts", "bead", "slot", "outcome", "minutes", "rounds", "tests_added", "asked", "trace", "engine_log",
                  "run_log", "why"):
            self.assertIn(k, ln)
        self.assertEqual((ln["bead"], ln["slot"], ln["trace"], ln["engine_log"], ln["asked"]),
                         ("x-1", "s1", "tr-9", "/eng/x-1.jsonl", True))

    def test_a_bead_another_session_takes_is_skipped_for_the_next(self):
        bd = self.beads({"x-1": [], "x-2": [rec("landed")]})
        bd.taken_by_other.add("x-1")
        self.run_loop("--max-beads", "1")
        self.assertEqual([b for b, _ in self.started], ["x-2"])
        self.assertEqual([ln["outcome"] for ln in self.lines()], ["taken", "landed"])

    def test_a_bead_a_dead_run_left_assigned_is_released_and_run_a_live_claim_is_taken(self):
        # the engine's pause leaves the bead open but assigned; a restarted loop has a new actor
        bd = self.beads({"x-1": [rec("landed")], "x-2": []})
        bd.beads["x-1"].update(assignee="tl-dead", lease_expires_at="2020-01-01T00:00:00Z")
        bd.beads["x-2"].update(assignee="tl-live", lease_expires_at="2999-01-01T00:00:00Z")
        self.run_loop("--max-beads", "1")
        self.assertEqual([b for b, _ in self.started], ["x-1"])
        self.assertIn(("update", "x-1", "--if-assignee", "tl-dead", "--assignee", ""), bd.calls)

    def test_when_every_ready_bead_is_held_elsewhere_the_loop_sleeps_instead_of_spinning(self):
        bd = self.beads({"x-1": []})
        bd.taken_by_other.add("x-1")
        until = time.strftime("%H:%M", time.localtime(self.clock.t + 3600))
        self.assertEqual(self.run_loop("--until", until), 0)
        self.assertLessEqual(len(self.lines()), 5)
        self.assertIn(LoopConfig().pause_retry, self.clock.naps)

    def test_reclaim_returns_only_beads_of_tl_actors_never_a_persons_claim(self):
        bd = self.beads({"x-1": [rec("landed")], "x-2": [], "x-3": []})
        bd.beads["x-2"].update(status="in_progress", assignee="tl-dead0000")
        bd.beads["x-3"].update(status="in_progress", assignee="denis")
        self.run_loop("--max-beads", "1")
        reclaims = [c for c in bd.calls if c[0] == "reclaim"]
        self.assertTrue(reclaims)
        for c in reclaims:
            self.assertIn("--assignee", c)
            self.assertIn("tl-dead0000", c)
            self.assertNotIn("denis", c)

    def test_no_tl_claim_means_no_reclaim_at_all(self):
        bd = self.beads({"x-1": [rec("landed")], "x-3": []})
        bd.beads["x-3"].update(status="in_progress", assignee="denis")
        self.run_loop("--max-beads", "1")
        self.assertFalse([c for c in bd.calls if c[0] == "reclaim"])

    def test_bead_and_slot_leases_are_kept_alive_through_a_slow_slot_setup(self):
        bd = self.beads({"x-1": [rec("landed")]})
        beats = []

        def slow(taker, slot, bead_id):  # lifesim's agent-setup: 5-12 minutes when its inputs changed
            until(lambda: {("heartbeat", "x-1"), ("heartbeat", "sl-1")} <= set(bd.calls), limit=2.0, poll=0.02)
            beats.extend(c for c in bd.calls if c[0] == "heartbeat")
        (self.repo / ".task-loop.json").write_text(json.dumps({"slots": {"count": 2}, "loop": {"heartbeat": 0.05}}))
        with mock.patch.object(Taker, "prepare", slow):
            self.run_loop()
        self.assertIn(("heartbeat", "x-1"), beats)
        self.assertIn(("heartbeat", "sl-1"), beats)

    def test_the_child_is_told_the_slot_bead_so_it_keeps_the_slot_if_the_loop_dies(self):
        self.beads({"x-1": [rec("landed")]})
        seen = {}
        real = FakeChild.__init__

        def init(child, test, cmd, extra=None):
            seen["slot_bead"] = (extra or {}).get("TASK_LOOP_SLOT_BEAD")
            real(child, test, cmd, extra)
        with mock.patch.object(FakeChild, "__init__", init):
            self.run_loop()
        self.assertEqual(seen["slot_bead"], "sl-1")

    def test_an_error_while_a_bead_runs_stops_the_child_before_the_slot_is_freed(self):
        bd = self.beads({"x-1": []})
        self.hold["x-1"] = 5
        children = []
        real = FakeChild.__init__

        def init(child, test, cmd, extra=None):
            real(child, test, cmd, extra)
            children.append(child)
        with mock.patch.object(FakeChild, "__init__", init), \
                mock.patch.object(Core, "beat", side_effect=[None, RuntimeError("disk full")]), self.assertRaises(RuntimeError):
            self.run_loop()
        self.assertTrue(children[0].terminated)
        self.assertIsNotNone(children[0].returncode)
        self.assertTrue(all(s["status"] == "open" for s in bd.slots.values()))

    def test_a_stop_now_that_lands_anyway_never_reopens_the_bead(self):
        bd = self.beads({"x-1": [], "x-2": [rec("landed")]})
        self.hold["x-1"] = 3
        self.during.append(lambda: self.main(["stop", "--repo", str(self.repo), "--now"]))
        with mock.patch.object(wloop, "landed_on_base", return_value=True):
            self.run_loop()
        self.assertNotIn(("update", "x-1", "--status", "open", "--assignee", ""), bd.calls)
        self.assertIn("on the base", self.lines()[0]["why"])

    def test_a_taken_answer_from_run_task_is_not_picked_again_at_once(self):
        self.beads({"x-1": [rec("taken"), rec("landed")], "x-2": [rec("landed")]})
        self.run_loop("--max-beads", "2")
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2", "x-1"])

    def test_a_bead_paused_three_times_waits_an_hour_while_others_run(self):
        def soon():
            return rec("paused", kind="pause_lane", role="worker", retry_after=self.clock.t + 60)
        self.beads({"x-1": [None, None, None, rec("landed")], "x-2": [rec("landed")]})
        self.script["x-1"][:3] = [soon(), soon(), soon()]
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-1", "x-1", "x-2", "x-1"])
        self.assertTrue(any(n >= 3000 for n in self.clock.naps))

    def test_a_park_moves_on_and_two_failures_in_a_row_stop_parks_never_count(self):
        self.beads({"x-1": [rec("failed")], "x-2": [rec("parked")], "x-3": [rec("failed")], "x-4": [rec("landed")]})
        self.assertEqual(self.run_loop(), 2)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2", "x-3"])
        self.assertIn("2 failures in a row", self.out)

    def test_faults_with_a_kind_cool_their_bead_and_do_not_count_toward_a_stop(self):
        # tl-7y6.2.3: a FAULT_* is the storm detector's, not a failure count. Two different faults: both beads rest, the third runs.
        def fault(fp):
            return rec("failed", why="failed: infrastructure: x", kind="fault_infra", fingerprint=fp)
        self.beads({"x-1": [fault("FAULT_INFRA a")], "x-2": [fault("FAULT_INFRA b")], "x-3": [rec("landed")]})
        self.assertEqual(self.run_loop("--max-beads", "3"), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2", "x-3"])
        self.assertEqual([self.bd.beads[b]["status"] for b in ("x-1", "x-2")], ["open", "open"])
        rests = looptest.rests(str(self.repo))
        self.assertEqual(sorted(rests), ["x-1", "x-2"])
        self.assertTrue(all(abs(t - (self.clock.t0 + 1800)) < 600 for t in rests.values()))  # fault_cooldown_s, not an hour

    def test_a_run_that_tripped_the_storm_stops_the_loop_with_its_banner_and_leaves_the_beads_open(self):
        # tl-bxk.10.31: Codex rejected the schema for every bead; the loop drained 53 of them. The second bead trips the storm.
        banner = "STOPPED: storm FAULT_BAD_REQUEST bad_request on x-1,x-2 (the beads stay open; look at their logs)"
        def bad(**kw):
            return rec(
                "failed",
                why="failed: infrastructure: bad_request",
                kind="fault_bad_request",
                fingerprint="FAULT_BAD_REQUEST bad_request",
                **kw,
            )

        self.beads({"x-1": [bad()], "x-2": [bad(storm=banner)], "x-3": [rec("landed")]})
        self.assertEqual(self.run_loop(), 2)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])
        self.assertEqual(self.out.count("STOPPED: storm"), 1)
        self.assertEqual([self.bd.beads[b]["status"] for b in ("x-1", "x-2")], ["open", "open"])
        self.assertEqual(looptest.last_exit(str(self.repo))["reason"], "storm")

    def test_a_live_storm_record_stops_a_loop_before_any_claim_with_one_line(self):
        self.beads({"x-1": [rec("landed")]})
        path = storm_path(ident.config_dir(), (gitrepo.git('remote', 'get-url', 'origin', cwd=str(self.repo)) or str(self.repo)))
        write_storm(path, "FAULT_INFRA y", ("x-8", "x-9"), self.clock.t, self.clock.t, oc.KNOBS["storm_window_s"])
        self.assertEqual(self.run_loop(), 2)
        self.assertEqual(self.started, [])
        self.assertEqual(self.out.count("STOPPED: storm FAULT_INFRA y on x-8,x-9"), 1)
        self.assertIn(str(path), self.out)
        self.clock.t += 31 * 60  # it expires by itself
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1"])

    def test_two_instant_failures_on_one_slot_set_the_slot_aside_and_the_loop_goes_on(self):
        # tl-g6a: s4 fed 7 beads in under a minute each, 'worktree has uncommitted work of another branch'
        def bad():
            return rec(
                "failed",
                minutes=0.3,
                kind="fault_slot",
                after="blocked",
                why="failed: worktree /w/.slots/s1 has uncommitted work of another branch",
            )

        self.beads({"x-1": [bad()], "x-2": [bad()], "x-3": [rec("landed")]}, slots=2)
        holds = []
        real = verbs.hold
        with mock.patch.object(
            verbs, "hold", side_effect=lambda env, a: holds.append(("hold", a.name, a.why, a.for_min)) or 0 if True else real(env, a)
        ):
            self.run_loop()
        self.assertEqual([h[:2] for h in holds], [("hold", "s1")])
        self.assertIn("SET ASIDE", self.out)
        self.assertIn("set aside by tl loop: 2 runs failed", holds[0][2])
        self.assertEqual(holds[0][3], LoopConfig().slot_aside_min)
        self.assertNotIn("2 failures in a row", self.out)  # the slot's failures are not the beads' or the loop's
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2", "x-3"])

    def test_one_instant_failure_or_a_slow_one_or_another_reason_sets_nothing_aside(self):
        holds = []
        guard = mock.patch.object(verbs, "hold", side_effect=lambda env, a: holds.append(a.name) or 0)
        with guard:
            self.beads(
                {
                    "x-1": [
                        rec(
                            "failed",
                            minutes=0.3,
                            kind="fault_slot",
                            after="blocked",
                            why="failed: worktree X has uncommitted work of another branch",
                        )
                    ],
                    "x-2": [rec("landed")],
                    "x-3": [
                        rec(
                            "failed",
                            minutes=0.3,
                            kind="fault_slot",
                            after="blocked",
                            why="failed: worktree X has uncommitted work of another branch",
                        )
                    ],
                    "x-4": [rec("landed")],
                }
            )
            self.run_loop()
        self.assertEqual(holds, [])  # a landing ends the run of failures
        with guard:
            self.beads(
                {
                    "x-1": [rec("failed", minutes=40, kind="fault_slot", after="blocked", why="failed: worktree X has uncommitted work")],
                    "x-2": [rec("failed", minutes=40, kind="fault_slot", after="blocked", why="failed: worktree X has uncommitted work")],
                }
            )
            self.run_loop()
        self.assertEqual(holds, [])  # slow ones
        with guard:
            self.beads(
                {
                    "x-1": [rec("failed", minutes=0.2, why="failed: the plan has no stages")],
                    "x-2": [rec("failed", minutes=0.2, why="failed: the plan has no stages")],
                }
            )
            self.run_loop()
        self.assertEqual(holds, [])  # not the slot's

    def test_a_slot_that_cannot_be_held_is_said_so_and_the_failures_still_count(self):
        def bad():
            return rec(
                "failed",
                minutes=0.3,
                kind="fault_slot",
                after="blocked",
                why="failed: worktree /w/.slots/s1 has uncommitted work of another branch",
            )

        self.beads({"x-1": [bad()], "x-2": [bad()], "x-3": [rec("landed")]}, slots=2)
        with mock.patch.object(verbs, "hold", side_effect=lambda env, a: 1):
            self.run_loop()
        self.assertIn("could not be set aside", self.out)
        self.assertNotIn("SET ASIDE", self.out)

    def test_a_landed_bead_ends_a_run_of_failures(self):
        self.beads({"x-1": [rec("failed")], "x-2": [rec("landed")], "x-3": [rec("failed")], "x-4": [rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(len(self.started), 4)

    def test_a_crash_with_no_outcome_is_a_failure(self):
        self.beads({"x-1": [None], "x-2": [None], "x-3": [rec("landed")]})
        self.assertEqual(self.run_loop(), 2)
        self.assertEqual(self.lines()[0]["outcome"], "failed")
        self.assertIn("no outcome", self.lines()[0]["why"])

    # tl-7y6.2.8: a paused bead wakes when delegate says its role is usable, not at a clock
    def test_a_lane_pause_wakes_when_the_role_is_usable_not_at_the_hint(self):
        up_at = self.clock.t0 + 200
        self.roles = lambda: {"worker": {"usable": self.clock.t >= up_at, "until": self.clock.t0 + 2 * 3600}}
        self.beads({"x-1": [rec("paused", kind="pause_lane", role="worker", retry_after=self.clock.t + 2 * 3600), rec("landed")],
                    "x-2": [rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2", "x-1"])  # the next bead runs while the role is down
        self.assertLess(self.clock.t - self.clock.t0, 600)  # woken by the role coming back, 2 hours before the hint
        self.assertFalse([n for n in self.clock.naps if n > LoopConfig().gate_cache + 1])
        self.assertIn("worker role", self.out)

    def test_a_stale_hint_never_blocks_a_usable_role(self):
        self.beads({"x-1": [rec("paused", kind="pause_lane", role="worker", retry_after=self.clock.t + 5 * 3600), rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-1"])
        self.assertFalse([n for n in self.clock.naps if n > 60])

    def test_a_role_delegate_cannot_judge_fails_open_after_the_unknown_wait(self):
        self.roles = lambda: {}
        self.beads({"x-1": [rec("paused", kind="pause_lane", role="worker"), rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-1"])
        self.assertGreaterEqual(self.clock.t - self.clock.t0, LoopConfig().gate_unknown)
        self.assertLess(self.clock.t - self.clock.t0, LoopConfig().gate_unknown + 2 * LoopConfig().gate_cache)

    def test_a_role_that_stays_down_keeps_the_bead_waiting_while_others_run(self):
        self.roles = lambda: {"worker": {"usable": False}}
        self.beads({"x-1": [rec("paused", kind="pause_lane", role="worker")], "x-2": [rec("landed")]})
        self.assertEqual(self.run_loop("--until", time.strftime("%H:%M", time.localtime(self.clock.t + 300))), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])  # x-1 is never run again while its role is down

    def test_a_pause_with_no_role_rests_pause_retry(self):
        self.beads({"x-1": [rec("paused"), rec("landed")], "x-2": [rec("paused"), rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2", "x-1", "x-2"])
        self.assertIn(LoopConfig().pause_retry, self.clock.naps)


    def test_drained_waits_when_asked_and_polls_until_the_end_time(self):
        self.beads({})
        until = time.strftime("%H:%M", time.localtime(self.clock.t + 3600))
        self.assertEqual(self.run_loop("--wait-drained", "--until", until), 0)
        self.assertGreaterEqual(len([n for n in self.clock.naps if n == LoopConfig().drained_poll]), 5)

    def test_no_free_slot_waits_with_backoff_then_takes_the_one_freed(self):
        bd = self.beads({"x-1": [rec("landed")]}, slots=1)
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-other")
        frees = {"n": 0}

        def nap(secs, *a, **kw):
            self.clock.naps.append(round(secs))
            self.clock.t += secs
            frees["n"] += 1
            if frees["n"] == 3:
                bd.slots["sl-1"].update(status="open", assignee="")
        with mock.patch.object(Core, "nap", staticmethod(nap)):
            self.assertEqual(self.run_loop("--wait-slot-min", "1"), 0)
        self.assertEqual(self.started, [("x-1", "s1")])
        self.assertEqual(self.clock.naps[:3], sorted(self.clock.naps[:3]))
        self.assertIn("no free slot", self.out)

    def test_without_slots_the_loop_uses_its_worktree(self):
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": {}}))
        self.beads({"x-1": [rec("landed")]}, slots=0)
        with mock.patch.object(wslots, "start_worktree", return_value=str(self.home / "wt")):
            self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.started, [("x-1", None)])

    def test_max_beads_stops_after_that_many(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.assertEqual(self.run_loop("--max-beads", "1"), 0)
        self.assertEqual(len(self.started), 1)

    def test_stop_lets_the_current_bead_finish_then_ends(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.during.append(lambda: self.main(["stop", "--repo", str(self.repo)]))
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([ln["outcome"] for ln in self.lines()], ["landed"])
        self.assertFalse(looptest.command(str(self.repo)).exists())

    def test_stop_now_ends_the_child_and_leaves_no_held_slot_or_claimed_bead(self):
        bd = self.beads({"x-1": [], "x-2": [rec("landed")]})
        self.hold["x-1"] = 3
        self.during.append(lambda: self.main(["stop", "--repo", str(self.repo), "--now"]))
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(len(self.started), 1)
        self.assertEqual(bd.beads["x-1"]["status"], "open")
        self.assertFalse(bd.beads["x-1"].get("assignee"))
        self.assertTrue(all(s["status"] == "open" for s in bd.slots.values()))
        self.assertIn("stopped", self.lines()[0]["why"])

    def test_stop_with_no_loop_running_says_so(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.main(["stop", "--repo", str(self.repo)]), 1)
        self.assertIn("no loop", out.getvalue())

    def other_loop(self):
        """A second live loop on the repo: its state names a live process that is not this one."""
        k = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (k.kill(), k.wait()))
        looptest.write_state(str(self.repo), pid=k.pid, started=self.clock.t, bead="x-9", slot="s2", since=self.clock.t)
        return k
    def test_a_second_loop_on_a_repo_runs_beside_the_first_with_its_own_state(self):
        # tl-bxk.11.1: N loops on one repo; the first's state, stop and log stay as they were
        self.beads({"x-1": [rec("landed")]})
        k = self.other_loop()
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.started, [("x-1", "s1")])
        self.assertEqual([s.pid for s in looptest.live(str(self.repo))], [k.pid])
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.main(["loop", "status", "--repo", str(self.repo)]), 0)
        self.assertIn(f"pid {k.pid}", out.getvalue())
        self.assertIn("x-9", out.getvalue())

    def test_two_loops_started_from_one_session_claim_as_two_actors(self):
        # one coordinator session starting two loops gave both its actor: bd lets an actor re-claim its own bead, so
        # the second loop claimed the bead the first (or the session's hand run) was running (race test, tl-bxk.11.1)
        seen = []
        for _ in range(2):
            bd = self.beads({"x-1": [rec("landed")]})
            claims = []

            def spy(*a, _bd=bd, _claims=claims, **kw):
                if a[:1] == ("update",) and "--claim" in a and a[1] == "x-1":
                    _claims.append(ident.actor())
                return _bd(*a, **kw)
            with tlbd.bd_boundary(spy):
                self.run_loop()
            seen.append(claims[0])
            os.environ.pop("TASK_LOOP_ACTOR", None)
        session_actor = ident.actor()
        self.assertNotEqual(seen[0], seen[1])
        self.assertNotIn(session_actor, seen)  # a hand run from the session claims as the session
        self.assertTrue(all(a.startswith(session_actor + "-") for a in seen), seen)  # still names its session

    def test_without_slots_each_loop_start_reuses_its_sessions_worktree(self):
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": {}}))
        names = []
        with mock.patch.object(wslots, "start_worktree", side_effect=lambda repo, name=None: names.append(name) or
                               str(self.home / "wt")):
            for _ in range(2):
                self.beads({"x-1": [rec("landed")]}, slots=0)
                self.run_loop()
                os.environ.pop("TASK_LOOP_ACTOR", None)
        self.assertEqual(names, ["abcdef12"] * 2)  # tl-abcdef12: the session's actor, not the per-loop one
    def test_without_slots_a_second_loop_of_the_session_takes_its_own_worktree(self):
        # two loops in one worktree would reset it under each other's engine
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": {}}))
        self.beads({"x-1": [rec("landed")]}, slots=0)
        k = self.other_loop()
        looptest.write_state(str(self.repo), pid=k.pid, started=self.clock.t, worktree=str(self.repo / ".worktrees" / "loop-abcdef12"))
        names = []
        with mock.patch.object(wslots, "start_worktree", side_effect=lambda repo, name=None: names.append(name) or
                               str(self.home / "wt")):
            self.run_loop()
        self.assertNotEqual(names[0], "abcdef12")
        self.assertTrue(names[0].startswith("abcdef12-"), names)

    def test_sunset_keeps_a_sessions_worktree_while_a_loop_of_that_session_holds_a_lease(self):
        bd = self.beads({"x-1": []}, slots=0)
        bd.beads["x-1"].update(status="in_progress", assignee="tl-other000-a1b2c3", lease_expires_at="2999-01-01T00:00:00Z")
        wt = self.repo / ".worktrees" / "loop-other000"
        wt.mkdir(parents=True)
        out = io.StringIO()
        with redirect_stdout(out):
            self.main(["worktree", "sunset"])
        self.assertNotIn("REMOVED", out.getvalue())
        self.assertTrue(wt.is_dir())
    def test_a_stop_reaches_every_loop_and_a_loop_started_later_ignores_it(self):
        self.beads({"x-1": [rec("landed")]})
        k = self.other_loop()
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.main(["stop", "--repo", str(self.repo)]), 0)
        self.assertIn(str(k.pid), out.getvalue())
        time.sleep(0.05)
        self.assertEqual(self.run_loop(), 0)  # started after the stop: runs
        self.assertEqual(self.started, [("x-1", "s1")])
        self.assertTrue(looptest.command(str(self.repo)).exists())  # still there for the loop it was meant for

    def test_status_shows_the_running_bead_and_the_last_lines(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("parked")]})
        self.run_loop()
        looptest.write_state(str(self.repo), pid=os.getpid(), started=self.clock.t, bead="x-3", slot="s2", since=self.clock.t)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.main(["loop", "status", "--repo", str(self.repo)]), 0)
        s = out.getvalue()
        self.assertIn(f"pid {os.getpid()}", s)
        self.assertIn("x-3", s)
        self.assertIn("s2", s)
        self.assertIn("x-1", s)
        self.assertIn("parked", s)


if __name__ == "__main__":
    unittest.main()
