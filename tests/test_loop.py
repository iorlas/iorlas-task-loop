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
        self.t0 = self.t

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
            b["status"] = "open" if "infrastructure" in r.get("why", "") else self.AFTER.get(r["outcome"], b["status"])
            if b["status"] != "in_progress":
                b["assignee"] = b["assignee"] if b["status"] == "blocked" else ""
        self.returncode = 0 if r and r["outcome"] == "landed" else 2
        return self.returncode

    def terminate(self):
        self.terminated = True


class Margin(unittest.TestCase):
    def test_the_wake_margin_is_a_jitter_of_30_to_90_seconds(self):
        got = [loop.margin() for _ in range(200)]
        self.assertTrue(all(30 <= m <= 90 for m in got))
        self.assertGreater(len(set(got)), 1)  # two loops paused on one lane do not wake in the same second


class LoopBase(Base):
    """The loop with run-task faked (FakeChild) and slot setup skipped; no tests of its own."""

    def setUp(self):
        super().setUp()
        self.clock = Clock()
        self.script, self.hold, self.started, self.during = {}, {}, [], []
        for p in (mock.patch.object(loop, "clock", self.clock), mock.patch.object(loop, "nap", self.clock.nap),
                  mock.patch.object(loop, "margin", return_value=45),
                  mock.patch.object(loop, "spawn", side_effect=lambda cmd, log: FakeChild(self, cmd)),
                  mock.patch.object(loop, "prepare", return_value=(0, ""))):
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
            return 0, ""
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

    def test_two_infrastructure_failures_in_a_row_stop_the_loop_and_leave_the_beads_open(self):
        # tl-bxk.10.31: Codex rejected the schema for every bead; the loop drained 53 of them. Two stop it.
        infra = lambda: rec("failed", why="failed: infrastructure: bad_request: codex rejected the request: Invalid schema ...")
        self.beads({"x-1": [infra()], "x-2": [infra()], "x-3": [rec("landed")]})
        self.assertEqual(self.run_loop(), 2)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])
        self.assertIn("2 failures in a row", self.out)
        self.assertEqual([self.bd.beads[b]["status"] for b in ("x-1", "x-2")], ["open", "open"])
        self.assertEqual([l["outcome"] for l in self.lines()], ["failed", "failed"])
        self.assertIn("infrastructure", self.lines()[0]["why"])
        self.assertEqual(sorted(loop.read_rests(str(self.repo))), ["x-1", "x-2"])  # rests an hour for every loop

    def test_two_instant_failures_on_one_slot_set_the_slot_aside_and_the_loop_goes_on(self):
        # tl-g6a: s4 fed 7 beads in under a minute each, 'worktree has uncommitted work of another branch'
        bad = lambda: rec("failed", minutes=0.3, why="failed: worktree /w/.slots/s1 has uncommitted work of another branch")
        self.beads({"x-1": [bad()], "x-2": [bad()], "x-3": [rec("landed")]}, slots=2)
        holds = []
        real = tl.cmd_slot
        with mock.patch.object(tl, "cmd_slot", side_effect=lambda a: holds.append((a.op, a.name, a.why, a.for_min)) or 0 if a.op == "hold" else real(a)):
            rc = self.run_loop()
        self.assertEqual([h[:2] for h in holds], [("hold", "s1")])
        self.assertIn("SET ASIDE", self.out)
        self.assertIn("set aside by tl loop: 2 runs failed", holds[0][2])
        self.assertEqual(holds[0][3], loop.SLOT_ASIDE_MIN)
        self.assertNotIn("2 failures in a row", self.out)  # the slot's failures are not the beads' or the loop's
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2", "x-3"])

    def test_one_instant_failure_or_a_slow_one_or_another_reason_sets_nothing_aside(self):
        holds = []
        real = tl.cmd_slot
        guard = mock.patch.object(tl, "cmd_slot", side_effect=lambda a: holds.append(a.name) or 0 if a.op == "hold" else real(a))
        with guard:
            self.beads({"x-1": [rec("failed", minutes=0.3, why="failed: worktree X has uncommitted work of another branch")],
                        "x-2": [rec("landed")], "x-3": [rec("failed", minutes=0.3, why="failed: worktree X has uncommitted work of another branch")],
                        "x-4": [rec("landed")]})
            self.run_loop()
        self.assertEqual(holds, [])  # a landing ends the run of failures
        with guard:
            self.beads({"x-1": [rec("failed", minutes=40, why="failed: worktree X has uncommitted work")], "x-2": [rec("failed", minutes=40, why="failed: worktree X has uncommitted work")]})
            self.run_loop()
        self.assertEqual(holds, [])  # slow ones
        with guard:
            self.beads({"x-1": [rec("failed", minutes=0.2, why="failed: the plan has no stages")], "x-2": [rec("failed", minutes=0.2, why="failed: the plan has no stages")]})
            self.run_loop()
        self.assertEqual(holds, [])  # not the slot's

    def test_a_slot_that_cannot_be_held_is_said_so_and_the_failures_still_count(self):
        bad = lambda: rec("failed", minutes=0.3, why="failed: worktree /w/.slots/s1 has uncommitted work of another branch")
        self.beads({"x-1": [bad()], "x-2": [bad()], "x-3": [rec("landed")]}, slots=2)
        real = tl.cmd_slot
        with mock.patch.object(tl, "cmd_slot", side_effect=lambda a: 1 if a.op == "hold" else real(a)):
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

    def test_a_pause_with_the_lane_back_soon_waits_for_it_and_runs_the_bead_again(self):
        self.beads({"x-1": [rec("paused", retry_after=self.clock.t + 600), rec("landed")], "x-2": [rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-1", "x-2"])
        self.assertIn(645, self.clock.naps)  # tl-bxk.10.6: retry_after plus a margin, never a fixed step

    def test_a_pause_beyond_the_cap_is_retried_at_its_retry_after_plus_the_margin(self):
        # lifesim-d5f.58 2026-10-21: Codex was back at 09:02 and the bead's first Codex call came 47 min later
        self.beads({"x-1": [rec("paused", retry_after=self.clock.t + 2 * 3600), rec("landed")],
                    "x-2": [rec("paused", retry_after=self.clock.t + 3 * 3600), rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2", "x-1", "x-2"])
        self.assertIn(2 * 3600 + 45, self.clock.naps)  # asleep until x-1's retry_after + margin, no fixed step
        due = time.strftime("%H:%M:%S", time.localtime(self.clock.t0 + 2 * 3600 + 45))
        self.assertIn("sleeping until %s" % due, self.out)

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

    def other_loop(self):
        """A second live loop on the repo: its state names a live process that is not this one."""
        k = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(lambda: (k.kill(), k.wait()))
        loop.write_state(str(self.repo), pid=k.pid, started=self.clock.t, bead="x-9", slot="s2", since=self.clock.t)
        return k

    def test_a_second_loop_on_a_repo_runs_beside_the_first_with_its_own_state(self):
        # tl-bxk.11.1: N loops on one repo; the first's state, stop and log stay as they were
        self.beads({"x-1": [rec("landed")]})
        k = self.other_loop()
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.started, [("x-1", "s1")])
        self.assertEqual([s["pid"] for s in loop.live_loops(str(self.repo))], [k.pid])
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(tl.main(["loop", "status", "--repo", str(self.repo)]), 0)
        self.assertIn("pid %d" % k.pid, out.getvalue())
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
                    _claims.append(tl.actor())
                return _bd(*a, **kw)
            with mock.patch.object(tl, "bd", side_effect=spy):
                self.run_loop()
            seen.append(claims[0])
            os.environ.pop("TASK_LOOP_ACTOR", None)
        session_actor = tl.actor()
        self.assertNotEqual(seen[0], seen[1])
        self.assertNotIn(session_actor, seen)  # a hand run from the session claims as the session
        self.assertTrue(all(a.startswith(session_actor + "-") for a in seen), seen)  # still names its session

    def test_a_loop_started_on_the_old_code_is_seen_by_stop_and_status(self):
        # before tl-bxk.11.1 the state was <key>.json, one per repo: a loop still running from then is a live loop
        k = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(lambda: (k.kill(), k.wait()))
        d, key = loop.paths(str(self.repo))["states"]
        (d / (key + ".json")).write_text(json.dumps({"pid": k.pid, "started": self.clock.t, "repo": str(self.repo)}))
        self.assertEqual([s["pid"] for s in loop.live_loops(str(self.repo))], [k.pid])
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(tl.main(["loop", "status", "--repo", str(self.repo)]), 0)
            self.assertEqual(tl.main(["stop", "--repo", str(self.repo)]), 0)
        self.assertIn("LOOP pid %d" % k.pid, out.getvalue())
        self.assertIn("STOP after the current bead: loop pid %d" % k.pid, out.getvalue())

    def test_without_slots_each_loop_start_reuses_its_sessions_worktree(self):
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": {}}))
        names = []
        with mock.patch.object(tl, "start_worktree", side_effect=lambda repo, name=None: names.append(name) or
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
        d, key = loop.paths(str(self.repo))["states"]
        f = d / ("%s.%d.json" % (key, k.pid))
        f.write_text(json.dumps(dict(json.loads(f.read_text()), worktree=str(self.repo / ".worktrees" / "loop-abcdef12"))))
        names = []
        with mock.patch.object(tl, "start_worktree", side_effect=lambda repo, name=None: names.append(name) or
                               str(self.home / "wt")):
            self.run_loop()
        self.assertNotEqual(names[0], "abcdef12")
        self.assertTrue(names[0].startswith("abcdef12-"), names)

    def test_sunset_keeps_a_sessions_worktree_while_a_loop_of_that_session_holds_a_lease(self):
        bd = self.beads({"x-1": []}, slots=0)
        bd.beads["x-1"].update(status="in_progress", assignee="tl-other000-a1b2c3", lease_expires_at="2999-01-01T00:00:00Z")
        wt = self.repo / ".worktrees" / "loop-other000"
        wt.mkdir(parents=True)
        with mock.patch.object(tl, "git", return_value=""), mock.patch.object(tl.subprocess, "run") as run, \
                redirect_stdout(io.StringIO()):
            tl.main(["worktree", "sunset"])
        self.assertFalse([c for c in run.call_args_list if "remove" in c[0][0]])

    def test_a_stop_reaches_every_loop_and_a_loop_started_later_ignores_it(self):
        self.beads({"x-1": [rec("landed")]})
        k = self.other_loop()
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(tl.main(["stop", "--repo", str(self.repo)]), 0)
        self.assertIn(str(k.pid), out.getvalue())
        time.sleep(0.05)
        self.assertEqual(self.run_loop(), 0)  # started after the stop: runs
        self.assertEqual(self.started, [("x-1", "s1")])
        self.assertTrue(loop.paths(str(self.repo))["stop"].exists())  # still there for the loop it was meant for

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


class Moved(Exception):
    """What the mocked os.execv raises: the real one never returns."""


class LoopSelfUpdate(LoopBase):
    """Between beads the loop re-execs into the newest complete install of the plugin (fake version trees)."""

    def setUp(self):
        super().setUp()
        self.cache = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cache, True)
        self.execs = []

        def execv(exe, argv):
            self.execs.append((exe, argv, os.environ.get("TL_LOOP_STATE"), os.getcwd()))
            raise Moved()
        for p in (mock.patch.object(os, "execv", side_effect=execv),
                  mock.patch.dict(os.environ, {}), mock.patch.object(tl, "HERE", self.install("0.1.0"))):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("TL_LOOP_STATE", None)

    def install(self, ver, tl_py="import sys\n", missing=(), loop_py=""):
        d = self.cache / ver / "skills" / "task-loop"
        d.mkdir(parents=True)
        (d.parents[1] / ".claude-plugin").mkdir()
        (d.parents[1] / ".claude-plugin" / "plugin.json").write_text("{}")
        for f in ("tl.py", "loop.py", "engine.py"):
            if f not in missing:
                (d / f).write_text(tl_py if f == "tl.py" else loop_py if f == "loop.py" else "")
        return d

    def test_it_moves_to_a_newer_complete_install_between_beads_with_the_same_argv(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.during.append(lambda: self.install("0.2.0"))
        with self.assertRaises(Moved):
            self.run_loop("--max-beads", "5")
        self.assertEqual([b for b, _ in self.started], ["x-1"])  # never mid-bead: x-1 ran to its end on 0.1.0
        self.assertEqual([l["outcome"] for l in self.lines()], ["landed"])
        exe, argv, state, _ = self.execs[0]
        self.assertEqual(exe, sys.executable)
        self.assertEqual(argv[:2], [sys.executable, str(self.cache / "0.2.0" / "skills" / "task-loop" / "tl.py")])
        self.assertEqual(argv[2:], ["loop", "--repo", str(self.repo), "--max-beads", "5"])
        self.assertEqual(json.loads(state)["ran"], 1)

    def test_the_move_is_logged_and_the_newest_of_several_wins(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0")
        self.install("0.10.0")  # 0.10 is newer than 0.9: numbers, not text
        self.install("0.9.0")
        with self.assertRaises(Moved), redirect_stdout(io.StringIO()) as out:
            tl.main(["loop", "--repo", str(self.repo)])
        self.assertIn("loop: moving to 0.10.0 (was 0.1.0)", out.getvalue())
        self.assertIn("0.10.0", self.execs[0][1][1])
        self.assertEqual(self.started, [])  # the first look is before any bead

    def test_an_incomplete_or_failing_install_is_ignored_and_warned_once_per_version(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.install("0.2.0", missing=("engine.py",))
        self.install("0.3.0", tl_py="raise SystemExit(3)\n")
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.execs, [])
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])
        self.assertEqual(self.out.count("not moving to 0.3.0"), 1)  # three looks, one warn (and one check)
        self.assertEqual(self.out.count("not moving to 0.2.0"), 1)  # once 0.3.0 failed, 0.2.0 is the newest left

    def test_an_incomplete_newest_warns_once(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.install("0.2.0", missing=("engine.py",))
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.out.count("not moving to 0.2.0: engine.py is missing"), 1)

    def test_a_half_copied_loop_py_is_not_moved_to(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0", loop_py="def broken(:\n")  # --help alone would pass; the import does not
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.execs, [])
        self.assertIn("not moving to 0.2.0", self.out)

    def test_an_install_without_plugin_json_is_not_moved_to(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0")
        (self.cache / "0.2.0" / ".claude-plugin" / "plugin.json").unlink()
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.execs, [])
        self.assertIn("plugin.json is missing", self.out)

    def test_a_relative_repo_is_resolved_from_the_start_directory_at_the_exec(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0")
        start = self.repo.parent
        with mock.patch.dict(os.environ), mock.patch("os.getcwd", wraps=os.getcwd):
            old = os.getcwd()
            os.chdir(start)
            try:
                with self.assertRaises(Moved), redirect_stdout(io.StringIO()):
                    tl.main(["loop", "--repo", self.repo.name])
            finally:
                os.chdir(old)
        self.assertEqual(os.path.realpath(self.execs[0][3]), os.path.realpath(start))
        self.assertIn(self.repo.name, self.execs[0][1])

    def test_a_stop_written_during_the_check_cancels_the_move(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0")

        def slow_check(d):
            loop.paths(str(self.repo))["stop"].write_text("after")
        with mock.patch.object(loop, "complete", side_effect=slow_check):
            self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.execs, [])
        self.assertEqual(self.started, [])
        self.assertIn("stopped on request", self.out)

    def test_a_bad_state_field_is_dropped_with_a_warning(self):
        self.beads({"x-1": [rec("landed")]})
        os.environ["TL_LOOP_STATE"] = json.dumps({"ran": "many", "fails": ["x-0"], "later": [1]})
        self.assertEqual(self.run_loop(), 0)
        self.assertIn("'ran' has a bad value", self.out)
        self.assertIn("'later' has a bad value", self.out)
        self.assertNotIn("'fails'", self.out)

    def test_a_help_that_hangs_is_not_moved_to(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0", tl_py="import time\ntime.sleep(60)\n")
        with mock.patch.object(loop, "HELP_WAIT", 0.5):
            self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.execs, [])
        self.assertIn("did not finish", self.out)

    def test_the_failure_counter_and_the_actor_survive_the_move(self):
        self.beads({"x-1": [rec("failed")], "x-2": [rec("failed")], "x-3": [rec("landed")]})
        self.during.append(lambda: self.install("0.2.0"))
        with self.assertRaises(Moved):
            self.run_loop()
        actor = os.environ["TASK_LOOP_ACTOR"]
        state = json.loads(self.execs[0][2])
        self.assertEqual(state["fails"], ["x-1"])
        # the new process: same pid, the state in the environment, the new install as the running code
        os.environ["TL_LOOP_STATE"] = self.execs[0][2]
        with mock.patch.object(tl, "HERE", self.cache / "0.2.0" / "skills" / "task-loop"):
            self.assertEqual(self.run_loop(), 2)  # one more failure is the second in a row
        self.assertIn("STOPPED: 2 failures in a row (x-1, x-2)", self.out)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])
        self.assertEqual(os.environ["TASK_LOOP_ACTOR"], actor)
        self.assertNotIn("TL_LOOP_STATE", os.environ)  # not handed on to children

    def test_max_beads_counts_the_beads_run_before_the_move(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")], "x-3": [rec("landed")]})
        self.during.append(lambda: self.install("0.2.0"))
        with self.assertRaises(Moved):
            self.run_loop("--max-beads", "2")
        os.environ["TL_LOOP_STATE"] = self.execs[0][2]
        with mock.patch.object(tl, "HERE", self.cache / "0.2.0" / "skills" / "task-loop"):
            self.run_loop("--max-beads", "2")
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])

    def test_pin_stays_on_the_running_install(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.install("0.2.0")
        self.assertEqual(self.run_loop("--pin"), 0)
        self.assertEqual(self.execs, [])
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])

    def test_a_dev_checkout_never_moves(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0")
        dev = self.cache / "checkout" / "skills" / "task-loop"
        dev.mkdir(parents=True)
        with mock.patch.object(tl, "HERE", dev):
            self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.execs, [])


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
        with mock.patch.object(loop, "spawn", spawn), mock.patch.object(loop, "prepare", return_value=(0, "")), \
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
