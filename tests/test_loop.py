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
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
import loop  # noqa: E402
import tl  # noqa: E402


def bead(id, priority=2, parent=None, labels=(), type="task"):
    b = {"id": id, "title": "bead " + id, "status": "open", "priority": priority, "issue_type": type}
    if parent:
        b["parent"] = parent
    if labels:
        b["labels"] = list(labels)
    return b


class FakeBd:
    """bd as the loop calls it: ready, show, claim, unclaim, heartbeat, reclaim and the slot beads."""

    def __init__(self, beads=(), slots=0, parents=None):
        self.beads = {b["id"]: dict(b) for b in beads}
        self.parents = dict(parents or {})  # beads not in the ready list (epics): id -> parent
        self.slots = {"sl-%d" % i: {"id": "sl-%d" % i, "title": "slot %s s%d" % (tl.HOST, i), "status": "open",
                                    "assignee": ""} for i in range(1, slots + 1)}
        self.taken_by_other = set()  # claims another session wins
        self.calls = []

    def __call__(self, *a, cwd=None, check=False):
        self.calls.append(a)
        out, rc = "", 0
        if a[0] == "update" and ("--set-metadata" in a or "--unset-metadata" in a):
            meta = (self.beads.get(a[1]) or self.slots.get(a[1]) or {}).setdefault("metadata", {})
            for i, x in enumerate(a[:-1]):
                if x == "--set-metadata":
                    k, _, v = a[i + 1].partition("=")
                    meta[k] = v
                elif x == "--unset-metadata":
                    meta.pop(a[i + 1], None)
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
            b = self.beads.get(a[1]) or self.slots.get(a[1])
            if a[1] in self.taken_by_other or b.get("status") != "open" or b.get("assignee") not in (None, "", tl.actor()):
                rc = 1  # bd 1.3: an open bead still assigned to another actor (a paused run's) refuses the claim
            else:
                b.update(status="in_progress", assignee=tl.actor())
        elif a[0] == "unclaim":
            (self.beads.get(a[1]) or self.slots.get(a[1])).update(status="open", assignee="")
        elif a[0] == "update" and ("--status" in a or "--assignee" in a):
            for flag, key in (("--status", "status"), ("--assignee", "assignee")):
                if flag in a:
                    (self.beads.get(a[1]) or self.slots[a[1]])[key] = a[a.index(flag) + 1]
        return mock.Mock(returncode=rc, stdout=out, stderr="")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.repo = self.home / "repo"
        self.repo.mkdir()
        env = {"XDG_CONFIG_HOME": str(self.home / "cfg"), "APPDATA": str(self.home / "cfg"),
               "CLAUDE_CODE_SESSION_ID": "abcdef12-3456"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        os.environ.pop("TASK_LOOP_ACTOR", None)
        self.cwd = os.getcwd()
        for p in (mock.patch.object(tl, "repo_root", return_value=str(self.repo)),
                  mock.patch.object(tl, "event", return_value={}),
                  mock.patch.object(tl, "provenance")):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        os.chdir(self.cwd)
        self.env.stop()

        def force(fn, path, _):
            os.chmod(path, stat.S_IWRITE)
            fn(path)
        shutil.rmtree(self.tmp.name, onerror=force)
        try:
            self.tmp.cleanup()
        except OSError:
            pass

    def config(self, **engine_cfg):
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": engine_cfg}))

    def fake(self, *beads, **kw):
        f = FakeBd(beads, **kw)
        p = mock.patch.object(tl, "bd", side_effect=f)
        p.start()
        self.addCleanup(p.stop)
        return f


class Queue(Base):
    def order(self):
        ranked, _ = loop.queue(str(self.repo))
        return [b["id"] for b, _ in ranked]

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
        self.assertIn(("ready", "--json", "-n", "0", "--label", "auto"), f.calls)

    def test_skip_labels_epics_and_slots_are_skipped_with_a_reason(self):
        self.config(skip_labels=["owner-taste", "needs-info"])
        self.fake(bead("x-1", labels=["owner-taste"]), bead("x-2"), bead("x-3", type="epic"), bead("x-4", labels=["slot"]),
                  bead("x-5", labels=["needs-info"]))
        ranked, skipped = loop.queue(str(self.repo))
        self.assertEqual([b["id"] for b, _ in ranked], ["x-2"])
        self.assertEqual(dict(skipped), {"x-1": "label owner-taste", "x-3": "an epic", "x-4": "a slot",
                                         "x-5": "label needs-info"})

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
        ranked, skipped = loop.queue(str(self.repo))
        self.assertEqual([b["id"] for b, _ in ranked], ["x-1"])
        self.assertEqual(dict(skipped), {"x-2": "under no epic in epic_order (epic_only)"})

    def test_each_place_says_which_rule_put_it_there(self):
        self.config(epic_order=["e-1"])
        self.fake(bead("x-1", 1), bead("x-2", 2, parent="e-1"), bead("x-3", 2), bead("x-4", 2))
        ranked, _ = loop.queue(str(self.repo))
        self.assertEqual([r for _, r in ranked], ["priority P1 before P2", "epic e-1 (1st in epic_order)",
                                                  "lowest id", "last"])

    def test_tl_next_prints_the_pick_the_reason_and_the_next_few_without_claiming(self):
        self.config(skip_labels=["owner-taste"])
        f = self.fake(bead("x-1"), bead("x-2"), bead("x-3", labels=["owner-taste"]))
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(tl.main(["next", "--repo", str(self.repo)]), 0)
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
            tl.main(["next", "--repo", str(self.repo), "--json"])
        d = json.loads(buf.getvalue())
        self.assertEqual(d["pick"]["id"], "x-1")
        self.fake()
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(tl.main(["next", "--repo", str(self.repo)]), 1)
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
            self.assertEqual(tl.main(["next", "--repo", str(self.repo)]), 0)
        out = buf.getvalue()
        self.assertIn("NEXT x-2", out)
        self.assertIn("skip x-1: label later", out)
        self.assertIn("owner-taste", (self.repo / ".task-loop.json").read_text())  # the working tree stays behind

    def test_the_loop_queue_fetches_before_it_reads_the_rule(self):
        self.push_rule({"engine": {"epic_order": [], "pick_label": "go"}})
        self.fake(bead("x-1"), bead("x-2", labels=["go"]))
        ranked, _ = loop.queue(str(self.repo))
        self.assertEqual([b["id"] for b, _ in ranked], ["x-2"])

    def test_engine_load_cfg_reads_the_base_branch_with_the_base_the_working_tree_names(self):
        self.push_rule({"engine": {"brief_kb": 7}})
        self.sh("git", "fetch", "-q", "origin", cwd=self.repo)
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": {"brief_kb": 99}}))
        self.assertEqual(loop.engine.load_cfg(str(self.repo))["brief_kb"], 7)

    def test_no_remote_falls_back_to_the_working_tree(self):
        self.sh("git", "remote", "remove", "origin", cwd=self.repo)
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": {"skip_labels": ["later"]}}))
        self.fake(bead("x-1", labels=["later"]), bead("x-2"))
        ranked, skipped = loop.queue(str(self.repo))
        self.assertEqual([b["id"] for b, _ in ranked], ["x-2"])
        self.assertEqual(skipped, [("x-1", "label later")])


def rec(outcome, **kw):
    return dict({"v": 1, "outcome": outcome, "why": "", "run": "run-1", "log": "/e.jsonl", "minutes": 1.0, "rounds": 1,
                 "tests_added": 2, "asked": outcome == "parked", "retry_after": 0.0}, **kw)


class Clock:
    def __init__(self):
        self.t, self.naps = 1_800_000_000.0, []

    def __call__(self):
        return self.t

    def nap(self, secs, *a, **kw):
        self.naps.append(round(secs))
        self.t += max(secs, 1)


class FakeChild:
    """run-task as the loop starts it: writes its outcome file and leaves the bead as the engine would."""
    AFTER = {"landed": "closed", "parked": "blocked", "failed": "blocked", "paused": "open", "taken": "open"}

    def __init__(self, test, cmd):
        self.test, self.cmd = test, cmd
        self.bead = cmd[cmd.index("run-task") + 1]
        self.out = cmd[cmd.index("--outcome-file") + 1]
        self.pid, self.terminated, self.returncode = 4242, False, None
        self.polls = test.hold.pop(self.bead, 0)
        test.started.append((self.bead, cmd[cmd.index("--slot") + 1] if "--slot" in cmd else None))
        if test.during:
            test.during.pop(0)()

    def wait(self, timeout=None):
        if self.polls and not self.terminated:
            self.polls -= 1
            self.test.clock.t += timeout or 0
            raise subprocess.TimeoutExpired(self.cmd, timeout)
        r = rec("failed", why="failed: stopped (SIGTERM)") if self.terminated else self.test.script[self.bead].pop(0)
        if r is not None:
            Path(self.out).write_text(json.dumps(dict(r, bead=self.bead)))
            b = self.test.bd.beads[self.bead]
            b["status"] = self.AFTER.get(r["outcome"], b["status"])
            if b["status"] != "in_progress":
                b["assignee"] = b["assignee"] if b["status"] == "blocked" else ""
        self.returncode = 0 if r and r["outcome"] == "landed" else 2
        return self.returncode

    def terminate(self):
        self.terminated = True


class LoopBase(Base):
    """The loop with run-task faked (FakeChild) and slot setup skipped; no tests of its own."""

    def setUp(self):
        super().setUp()
        self.clock = Clock()
        self.script, self.hold, self.started, self.during = {}, {}, [], []
        for p in (mock.patch.object(loop, "clock", self.clock), mock.patch.object(loop, "nap", self.clock.nap),
                  mock.patch.object(loop, "spawn", side_effect=lambda cmd, log: FakeChild(self, cmd)),
                  mock.patch.object(loop, "prepare", return_value=0)):
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
            rc = tl.main(["loop", "--repo", str(self.repo)] + list(args))
        self.out = out.getvalue()
        return rc

    def lines(self):
        f = loop.paths(str(self.repo))["log"]
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


class Loop(LoopBase):
    def test_runs_ready_beads_in_a_row_each_in_a_free_slot_then_drains(self):
        bd = self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")], "x-3": [rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2", "x-3"])
        self.assertTrue(all(s == "s1" for _, s in self.started))
        self.assertTrue(all(s["status"] == "open" and not s["assignee"] for s in bd.slots.values()))  # released
        self.assertIn("DRAINED", self.out)
        self.assertEqual([l["outcome"] for l in self.lines()], ["landed"] * 3)

    def test_each_bead_is_claimed_by_the_loop_before_it_runs_and_the_child_gets_its_actor(self):
        bd = self.beads({"x-1": [rec("landed")]})
        self.run_loop()
        self.assertIn(("update", "x-1", "--claim"), bd.calls)
        self.assertTrue(os.environ.get("TASK_LOOP_ACTOR"))

    def test_a_log_line_per_bead_has_the_fields_the_owner_reviews(self):
        self.beads({"x-1": [rec("parked", run="tr-9", log="/eng/x-1.jsonl")]})
        self.run_loop()
        l = self.lines()[0]
        for k in ("ts", "bead", "slot", "outcome", "minutes", "rounds", "tests_added", "asked", "trace", "engine_log",
                  "run_log", "why"):
            self.assertIn(k, l)
        self.assertEqual((l["bead"], l["slot"], l["trace"], l["engine_log"], l["asked"]),
                         ("x-1", "s1", "tr-9", "/eng/x-1.jsonl", True))

    def test_a_bead_another_session_takes_is_skipped_for_the_next(self):
        bd = self.beads({"x-1": [], "x-2": [rec("landed")]})
        bd.taken_by_other.add("x-1")
        self.run_loop("--max-beads", "1")
        self.assertEqual([b for b, _ in self.started], ["x-2"])
        self.assertEqual([l["outcome"] for l in self.lines()], ["taken", "landed"])

    def test_a_bead_a_dead_run_left_assigned_is_released_and_run_a_live_claim_is_taken(self):
        # the engine's pause leaves the bead open but assigned; a restarted loop has a new actor
        bd = self.beads({"x-1": [rec("landed")], "x-2": []})
        bd.beads["x-1"].update(assignee="tl-dead", lease_expires_at="2020-01-01T00:00:00Z")
        bd.beads["x-2"].update(assignee="tl-live", lease_expires_at="2999-01-01T00:00:00Z")
        self.run_loop("--max-beads", "1")
        self.assertEqual([b for b, _ in self.started], ["x-1"])
        self.assertIn(("update", "x-1", "--assignee", ""), bd.calls)

    def test_when_every_ready_bead_is_held_elsewhere_the_loop_sleeps_instead_of_spinning(self):
        bd = self.beads({"x-1": []})
        bd.taken_by_other.add("x-1")
        until = time.strftime("%H:%M", time.localtime(self.clock.t + 3600))
        self.assertEqual(self.run_loop("--until", until), 0)
        self.assertLessEqual(len(self.lines()), 5)
        self.assertIn(loop.PAUSE_RETRY, self.clock.naps)

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

        def slow(repo, slot, bead_id):  # lifesim's agent-setup: 5-12 minutes when its inputs changed
            t = time.time()
            while time.time() - t < 2 and not ({("heartbeat", "x-1"), ("heartbeat", "sl-1")} <= set(bd.calls)):
                time.sleep(0.02)
            beats.extend(c for c in bd.calls if c[0] == "heartbeat")
            return 0
        with mock.patch.object(loop, "HEARTBEAT", 0.05), mock.patch.object(loop, "prepare", slow):
            self.run_loop()
        self.assertIn(("heartbeat", "x-1"), beats)
        self.assertIn(("heartbeat", "sl-1"), beats)

    def test_the_child_is_told_the_slot_bead_so_it_keeps_the_slot_if_the_loop_dies(self):
        self.beads({"x-1": [rec("landed")]})
        seen = {}
        real = FakeChild.__init__

        def init(child, test, cmd):
            seen["slot_bead"] = os.environ.get("TASK_LOOP_SLOT_BEAD")
            real(child, test, cmd)
        with mock.patch.object(FakeChild, "__init__", init):
            self.run_loop()
        self.assertEqual(seen["slot_bead"], "sl-1")

    def test_an_error_while_a_bead_runs_stops_the_child_before_the_slot_is_freed(self):
        bd = self.beads({"x-1": []})
        self.hold["x-1"] = 5
        children = []
        real = FakeChild.__init__

        def init(child, test, cmd):
            real(child, test, cmd)
            children.append(child)
        with mock.patch.object(FakeChild, "__init__", init), \
                mock.patch.object(loop, "stop_mode", side_effect=["", "", RuntimeError("disk full")] + [""] * 50):
            with self.assertRaises(RuntimeError):
                self.run_loop()
        self.assertTrue(children[0].terminated)
        self.assertIsNotNone(children[0].returncode)
        self.assertTrue(all(s["status"] == "open" for s in bd.slots.values()))

    def test_a_stop_now_that_lands_anyway_never_reopens_the_bead(self):
        bd = self.beads({"x-1": [], "x-2": [rec("landed")]})
        self.hold["x-1"] = 3
        self.during.append(lambda: tl.main(["stop", "--repo", str(self.repo), "--now"]))
        with mock.patch.object(loop, "landed_on_base", return_value=True):
            self.run_loop()
        self.assertNotIn(("update", "x-1", "--status", "open", "--assignee", ""), bd.calls)
        self.assertIn("on the base", self.lines()[0]["why"])

    def test_a_taken_answer_from_run_task_is_not_picked_again_at_once(self):
        self.beads({"x-1": [rec("taken"), rec("landed")], "x-2": [rec("landed")]})
        self.run_loop("--max-beads", "2")
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2", "x-1"])

    def test_a_bead_paused_three_times_waits_an_hour_while_others_run(self):
        def soon():
            return rec("paused", retry_after=self.clock.t + 60)
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

    def test_a_landed_bead_ends_a_run_of_failures(self):
        self.beads({"x-1": [rec("failed")], "x-2": [rec("landed")], "x-3": [rec("failed")], "x-4": [rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(len(self.started), 4)

    def test_a_crash_with_no_outcome_is_a_failure(self):
        self.beads({"x-1": [None], "x-2": [None], "x-3": [rec("landed")]})
        self.assertEqual(self.run_loop(), 2)
        self.assertEqual(self.lines()[0]["outcome"], "failed")
        self.assertIn("no outcome", self.lines()[0]["why"])

    def test_a_pause_with_the_lane_back_soon_waits_for_it_and_runs_the_bead_again(self):
        self.beads({"x-1": [rec("paused", retry_after=self.clock.t + 600), rec("landed")], "x-2": [rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-1", "x-2"])
        self.assertIn(600, self.clock.naps)

    def test_a_pause_with_no_time_tries_the_next_bead_and_when_all_pause_sleeps_to_the_earliest(self):
        self.beads({"x-1": [rec("paused"), rec("landed")], "x-2": [rec("paused"), rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2", "x-1", "x-2"])
        self.assertTrue(any(n >= 60 for n in self.clock.naps))
        self.assertIn("lane", self.out)

    def test_a_pause_beyond_the_cap_tries_the_next_bead(self):
        far = self.clock.t + 5 * 3600
        self.beads({"x-1": [rec("paused", retry_after=far)], "x-2": [rec("landed")]})
        self.run_loop("--max-beads", "2")
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])
        self.assertFalse([n for n in self.clock.naps if n > 3600])

    def test_drained_waits_when_asked_and_polls_until_the_end_time(self):
        self.beads({})
        until = time.strftime("%H:%M", time.localtime(self.clock.t + 3600))
        self.assertEqual(self.run_loop("--wait-drained", "--until", until), 0)
        self.assertGreaterEqual(len([n for n in self.clock.naps if n == loop.DRAINED_POLL]), 5)

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
        with mock.patch.object(loop, "nap", nap):
            self.assertEqual(self.run_loop("--wait-slot-min", "1"), 0)
        self.assertEqual(self.started, [("x-1", "s1")])
        self.assertEqual(self.clock.naps[:3], sorted(self.clock.naps[:3]))
        self.assertIn("no free slot", self.out)

    def test_without_slots_the_loop_uses_its_worktree(self):
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": {}}))
        self.beads({"x-1": [rec("landed")]}, slots=0)
        with mock.patch.object(tl, "start_worktree", return_value=str(self.home / "wt")):
            self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.started, [("x-1", None)])

    def test_max_beads_stops_after_that_many(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.assertEqual(self.run_loop("--max-beads", "1"), 0)
        self.assertEqual(len(self.started), 1)

    def test_stop_lets_the_current_bead_finish_then_ends(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.during.append(lambda: tl.main(["stop", "--repo", str(self.repo)]))
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([l["outcome"] for l in self.lines()], ["landed"])
        self.assertFalse(loop.paths(str(self.repo))["stop"].exists())

    def test_stop_now_ends_the_child_and_leaves_no_held_slot_or_claimed_bead(self):
        bd = self.beads({"x-1": [], "x-2": [rec("landed")]})
        self.hold["x-1"] = 3
        self.during.append(lambda: tl.main(["stop", "--repo", str(self.repo), "--now"]))
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(len(self.started), 1)
        self.assertEqual(bd.beads["x-1"]["status"], "open")
        self.assertFalse(bd.beads["x-1"].get("assignee"))
        self.assertTrue(all(s["status"] == "open" for s in bd.slots.values()))
        self.assertIn("stopped", self.lines()[0]["why"])

    def test_stop_with_no_loop_running_says_so(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(tl.main(["stop", "--repo", str(self.repo)]), 1)
        self.assertIn("no loop", out.getvalue())

    def test_a_second_loop_on_a_repo_is_refused(self):
        self.beads({"x-1": [rec("landed")]})
        loop.write_state(str(self.repo), pid=os.getpid(), started=self.clock.t)
        self.assertEqual(self.run_loop(), 1)
        self.assertIn("already", self.out)
        self.assertEqual(self.started, [])

    def test_status_shows_the_running_bead_and_the_last_lines(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("parked")]})
        self.run_loop()
        loop.write_state(str(self.repo), pid=os.getpid(), started=self.clock.t, bead="x-3", slot="s2", since=self.clock.t)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(tl.main(["loop", "status", "--repo", str(self.repo)]), 0)
        s = out.getvalue()
        self.assertIn("pid %d" % os.getpid(), s)
        self.assertIn("x-3", s)
        self.assertIn("s2", s)
        self.assertIn("x-1", s)
        self.assertIn("parked", s)


class LandedOnBase(Base):
    def git_repo(self):
        def sh(*a, cwd):
            subprocess.run(list(a), cwd=cwd, check=True, capture_output=True)
        os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        origin, wt = self.home / "o.git", self.home / "wt"
        sh("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=self.home)
        sh("git", "clone", "-q", str(origin), str(wt), cwd=self.home)
        sh("git", "commit", "-q", "--allow-empty", "-m", "init", cwd=wt)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=wt)
        return wt, lambda *a: sh(*a, cwd=wt)

    def test_only_a_land_commit_of_the_bead_on_the_base_counts(self):
        wt, sh = self.git_repo()
        self.fake(bead("x-1"), bead("x-2"), bead("x-3"))
        sh("git", "checkout", "-q", "-b", "task/x-1")
        sh("git", "commit", "-q", "--allow-empty", "-m", "Add f (x-1)")
        sh("git", "push", "-q", "origin", "HEAD:main")
        sh("git", "checkout", "-q", "-b", "task/x-2", "origin/main")
        sh("git", "commit", "-q", "--allow-empty", "-m", "wip (x-2): failed")
        sh("git", "checkout", "-q", "-b", "task/x-3", "origin/main")
        self.assertTrue(loop.landed_on_base(str(self.repo), str(wt), "x-1"))
        self.assertFalse(loop.landed_on_base(str(self.repo), str(wt), "x-2"))  # work not on main
        self.assertFalse(loop.landed_on_base(str(self.repo), str(wt), "x-3"))  # no work: the tip is someone else's
        self.assertFalse(loop.landed_on_base(str(self.repo), str(wt), "x-9"))  # no branch

@unittest.skipIf(os.name == "nt", "POSIX signals")
class LoopStopNow(Base):
    """A real child: --now reaches it as SIGTERM, which it traps to write its outcome (as the engine's close does)."""
    CHILD = (
        "import json, signal, sys, time\n"
        "out = sys.argv[sys.argv.index('--outcome-file') + 1]\n"
        "def stop(*_):\n"
        "    open(out, 'w').write(json.dumps({'outcome': 'failed', 'why': 'failed: stopped (SIGTERM)'}))\n"
        "    sys.exit(2)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        "print('running', flush=True)\n"
        "time.sleep(60)\n")

    def test_stop_now_sigterms_a_real_child(self):
        script = self.home / "child.py"
        script.write_text(self.CHILD)
        self.config()
        bd = self.fake(bead("x-1"))
        real = loop.spawn
        threads = []

        def spawn(cmd, log):
            p = real([sys.executable, str(script)] + cmd[2:], log)
            import threading
            t = threading.Timer(1.0, lambda: loop.cmd_stop(mock.Mock(repo=str(self.repo), now=True)))
            t.start()
            threads.append(t)
            return p
        with mock.patch.object(loop, "spawn", spawn), mock.patch.object(loop, "prepare", return_value=0), \
                mock.patch.object(tl, "start_worktree", return_value=str(self.home)), redirect_stdout(io.StringIO()):
            t0 = time.time()
            self.assertEqual(tl.main(["loop", "--repo", str(self.repo)]), 0)
        self.assertLess(time.time() - t0, 30)
        self.assertEqual(bd.beads["x-1"]["status"], "open")
        line = json.loads(loop.paths(str(self.repo))["log"].read_text().splitlines()[0])
        self.assertEqual(line["outcome"], "failed")
        self.assertIn("running", Path(line["run_log"]).read_text())


if __name__ == "__main__":
    unittest.main()
