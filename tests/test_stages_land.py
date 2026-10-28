"""Stage tests, part 3: the stale tree, slot hygiene, dead lanes, contracts and follow-ups. Split from test_stages."""
import json
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "task-loop"))
from support import fake_route  # noqa: E402
from support import tlbd  # noqa: E402
from support.fakes import FakeBeadStore  # noqa: E402
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from support.builders import make_engine  # noqa: E402
import test_engine as te  # noqa: E402
from test_engine import BEAD, CLEAN, FALSE, HAS_F, PLAN, WRITE, engine, lint, tl  # noqa: E402,F401


_REAL_CMD_BLOCK = tl.cmd_block  # te's harness patches it per test; this is the real one
from test_stages import StagesTest  # noqa: E402


class StaleTree(StagesTest):
    """tl-fsj: the tree a check runs on must have what the base's config names."""

    stop_at = te.EngineTest.stop_at
    stopped_run = te.EngineTest.stopped_run

    def main_moves(self, name="moved.txt"):
        base = Path(self.tmp.name, "base-moves")
        if not base.exists():
            te.sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        te.sh("git", "pull", "-q", "origin", "main", cwd=base)
        (base / name).write_text("main moved on\n")
        te.sh("git", "add", "-A", cwd=base)
        te.sh("git", "commit", "-qm", "main moves", cwd=base)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)

    def test_a_resume_mid_stage_rebases_first_and_goes_on(self):
        self.stopped_run()
        self.main_moves()
        rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        text = self.eng.log_path.read_text()
        self.assertIn("rebased the task branch onto the latest origin/main", text)
        self.assertNotIn("planner", [c[0] for c in s.calls])  # the plan was kept
        self.assertEqual(self.eng.stage_tree, "")

    def junk_and_moving_main(self):
        """The slot has Unity's untracked log (the base ignores it) and main has moved on with a new recipe file."""
        base = Path(self.tmp.name, "base-ignore")
        te.sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        (base / ".gitignore").write_text("client/log.txt\n")
        (base / "justfile").write_text("fmt-check-changed:\n\techo ok\n")
        te.sh("git", "add", "-A", cwd=base)
        te.sh("git", "commit", "-qm", "recipe and ignore", cwd=base)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
        te.sh("git", "fetch", "-q", "origin", cwd=self.wt)
        (self.wt / "client").mkdir(exist_ok=True)
        (self.wt / "client" / "log.txt").write_text("unity wrote this\n")

    def test_a_resume_start_rebases_even_with_a_base_ignored_file_in_the_slot(self):
        # lifesim-fld.27.12-20261024-230954: started_because resume, 75 commits behind, no rebase, the check named a recipe the tree lacked
        self.stopped_run()
        te.sh("git", "checkout", "-q", "task/t-1", cwd=self.wt)
        self.junk_and_moving_main()
        rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("rebased the task branch onto the latest origin/main", self.eng.log_path.read_text())
        self.assertTrue(Path(self.wt, "justfile").exists() or "justfile" in self.eng.git("ls-tree", "-r", "--name-only", "HEAD"))

    def test_an_answer_start_rebases_even_with_a_base_ignored_file_in_the_slot(self):
        # lifesim-6pld-20261024-224705: started_because answer, the same
        te.sh("git", "checkout", "-q", "-b", "task/t-1", cwd=self.wt)
        (self.wt / "g.txt").write_text("earlier work\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "wip (t-1): blocked", cwd=self.wt)
        te.sh("git", "checkout", "-q", "-", cwd=self.wt)
        self.junk_and_moving_main()
        te.sh("git", "checkout", "-q", "task/t-1", cwd=self.wt)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("rebased the task branch onto the latest origin/main", self.eng.log_path.read_text())

    def test_a_tracked_change_in_the_slot_still_stops_the_rebase(self):
        te.sh("git", "checkout", "-q", "-b", "task/t-1", cwd=self.wt)
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)), store=self.store)
        self.junk_and_moving_main()
        (self.wt / "a.txt").write_text("edited and not committed\n")
        self.assertEqual(e.rebase_onto_base(), "")

    def test_the_writer_is_told_the_check_variables_exist_only_inside_the_engines_checks(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        writer = s.prompts[1]
        self.assertIn("exist only while the engine runs the checks, never in your session", writer)
        self.assertIn("do not call it a blocker", writer)

    def test_a_resume_that_conflicts_with_main_starts_again(self):
        te.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        (self.wt / "a.txt").write_text("my work\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "wip", cwd=self.wt)
        te.sh("git", "checkout", "-q", "-", cwd=self.wt)
        self.main_moves("a.txt")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("resume_conflict", self.eng.log_path.read_text())

    def test_a_configured_check_the_tree_lacks_is_the_engines_error_not_a_writers_amend(self):
        miss = [{"id": "fmt", "cmd": te.PY + " -c \"import sys; sys.stderr.write('error: Justfile does not contain recipe `fmt-check-changed`.'); sys.exit(1)\"",
                 "group": "static"}]
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE]}, checks=miss)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker"])  # no second write: nothing was sent back to the writer
        self.assertTrue(self.eng.why.startswith("failed: infrastructure: the configured check `fmt` needs something this tree lacks"), self.eng.why)

    @te.no_repo
    def test_words_in_the_middle_of_a_long_output_are_not_a_stale_tree(self):
        noisy = "a test about justfile prints: This checkout has no recipe x\n" + "ok\n" * 300 + "2 failed: Foo"
        self.assertTrue(engine.STALE_TREE.search(noisy))  # the whole log matches...
        self.assertFalse(engine.STALE_TREE.search(noisy[-500:]))  # ...its last lines, which the engine reads, do not

    def test_the_checkpoint_head_follows_a_squash_and_rebase_over_the_wip_commit(self):
        te.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        (self.wt / "g.txt").write_text("work\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "work", cwd=self.wt)
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)), store=self.store)
        before = e.git("rev-parse", "HEAD")
        (self.wt / "g.txt").write_text("more work\n")
        te.sh("git", "commit", "-qam", "wip (t-1): blocked", cwd=self.wt)  # what reset() does with a dirty tree
        e.left_dirty = True
        e.checkpoint_path().parent.mkdir(exist_ok=True)
        e.checkpoint_path().write_text(json.dumps({"v": 1, "head": before}))
        self.main_moves()
        te.sh("git", "fetch", "-q", "origin", cwd=self.wt)
        self.assertEqual(e.rebase_onto_base(), "rebased")
        self.assertEqual(json.loads(e.checkpoint_path().read_text())["head"], e.git("rev-parse", "HEAD"))  # tl-7y6.2.19: the wip commit is squashed in
        self.assertEqual(e.git("rev-list", "--count", "origin/main..HEAD"), "1")

    def test_the_lifesim_wording_is_found_too_and_a_plain_red_check_is_not(self):
        self.assertTrue(engine.STALE_TREE.search("This checkout has no fmt-check-changed; rebase onto main"))
        self.assertFalse(engine.STALE_TREE.search("2 tests failed: FooTests.Bar"))
        plain = [{"id": "unit", "cmd": FALSE, "group": "tests"}]
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE, WRITE]}, checks=plain, max_check_tries=2)
        self.assertNotIn("infrastructure", self.eng.why)

    def test_a_plan_check_that_prints_the_same_words_is_the_writers_not_the_engines(self):
        words = te.PY + " -c \"import sys; sys.stderr.write('Justfile does not contain recipe x'); sys.exit(1)\""
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[words])])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE, WRITE]}, max_check_tries=2)
        self.assertNotIn("infrastructure", self.eng.why)


class SlotHygiene(StagesTest):
    """tl-g6a: base-ignored files do not make a slot dirty; a parked bead leaves the slot at the base."""

    def put_ignore_on_main(self, text, name=".gitignore", sub=""):
        base = Path(self.tmp.name, "base-ignore")
        if not base.exists():
            te.sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        te.sh("git", "pull", "-q", "origin", "main", cwd=base)
        d = base / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text)
        te.sh("git", "add", "-A", cwd=base)
        te.sh("git", "commit", "-qm", "gitignore", cwd=base)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
        te.sh("git", "fetch", "-q", "origin", cwd=self.wt)

    def test_files_the_base_ignores_do_not_count_as_dirty_work(self):
        self.put_ignore_on_main("client/log.txt\n")
        self.put_ignore_on_main("*.log\n!keep.log\n", sub="client")
        (self.wt / "client").mkdir()
        for f in ("client/log.txt", "client/Logs.log", "client/deep/x.log"):
            Path(self.wt, f).parent.mkdir(parents=True, exist_ok=True)
            Path(self.wt, f).write_text("noise\n")
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)), store=self.store)
        self.assertEqual(e.dirty_status(), "")
        self.assertIn("?? client/", e.git("status", "--porcelain"))  # git alone calls it dirty: the old tree has no such rule
        Path(self.wt, "client/keep.log").write_text("real\n")  # negated by the base: real work
        Path(self.wt, "client/src.cs").write_text("real\n")
        self.assertEqual(sorted(l[3:] for l in e.dirty_status().splitlines()), ["client/keep.log", "client/src.cs"])

    def test_the_users_own_global_excludes_still_apply(self):
        self.put_ignore_on_main("client/log.txt\n")
        glob = Path(self.tmp.name, "global-ignore")
        glob.write_text("*.swp\n")
        te.sh("git", "config", "core.excludesFile", str(glob), cwd=self.wt)
        (self.wt / "notes.swp").write_text("editor\n")
        (self.wt / "client").mkdir()
        (self.wt / "client" / "log.txt").write_text("unity\n")
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)), store=self.store)
        self.assertEqual(e.dirty_status(), "")

    def test_files_the_base_does_not_ignore_keep_a_parked_slot_where_it_is(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Which format?")]})
        self.assertEqual(rc, 2)
        # the bead's branch is checked out again by the next run; a stray untracked file the commit left out blocks the detach
        e = self.eng
        e.git("checkout", "-q", "task/t-1")
        (self.wt / "stray.dat").write_text("not ignored, not committed\n")
        e.leave_slot("blocked", "task/t-1")
        self.assertEqual(e.git("symbolic-ref", "--short", "-q", "HEAD"), "task/t-1")

    def test_a_slot_left_on_an_old_branch_with_only_ignored_files_is_not_another_branchs_work(self):
        te.sh("git", "checkout", "-qb", "task/old-bead", cwd=self.wt)
        self.put_ignore_on_main("client/log.txt\nclient/log-previous.txt\n")
        (self.wt / "client").mkdir()
        (self.wt / "client" / "log.txt").write_text("unity\n")
        (self.wt / "client" / "log-previous.txt").write_text("unity\n")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertNotIn("another branch", self.eng.why)

    def test_real_work_of_another_branch_still_stops_the_run(self):
        te.sh("git", "checkout", "-qb", "task/old-bead", cwd=self.wt)
        (self.wt / "keep.py").write_text("work\n")
        rc, s = self.run_engine({"plan": [PLAN]})
        self.assertNotEqual(rc, 0)
        self.assertIn("uncommitted work of another branch", self.eng.why)

    def test_a_parked_bead_leaves_the_slot_at_the_detached_base(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Which format?")]})
        self.assertEqual(rc, 2)
        head = engine.subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=self.wt, capture_output=True, text=True)
        self.assertNotEqual(head.returncode, 0)  # detached
        self.assertEqual(self.eng.git("rev-parse", "HEAD"), self.eng.git("rev-parse", "origin/main"))
        self.assertTrue(self.eng.git("rev-parse", "--verify", "-q", "refs/heads/task/t-1"))  # the branch keeps the bead's work

    def test_a_parked_bead_with_work_commits_it_to_its_branch_first(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Which format?")]})
        self.assertEqual(rc, 2)
        log = self.eng.git("log", "--format=%s", "task/t-1")
        self.assertIn("wip (t-1)", log)  # f.txt was written by the writer: kept on the bead's branch
        self.assertEqual(Path(self.wt, "f.txt").exists(), False)  # and gone from the slot

    def test_the_beads_new_files_go_to_its_branch_when_it_parks_and_the_base_ignored_junk_does_not(self):
        self.put_ignore_on_main("client/log.txt\n")
        (self.wt / "tests").mkdir(exist_ok=True)

        class Writer(fake_route.Script):  # a writer that makes a new feature file nothing in the plan names, and Unity's log
            def reply(this, role, prompt, schema, cwd, *a, **kw):
                if role == "worker":
                    Path(cwd, "tests", "edit_content.feature").write_text("Feature: x\n")
                    (Path(cwd) / "client").mkdir(exist_ok=True)
                    (Path(cwd) / "client" / "log.txt").write_text("unity\n")
                return super().reply(role, prompt, schema, cwd, *a, **kw)
        with mock.patch.object(fake_route, "Script", Writer):
            rc, s = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Which format?")]})
        self.assertEqual(rc, 2)
        branch_files = self.eng.git("ls-tree", "-r", "--name-only", "task/t-1").splitlines()
        self.assertIn("tests/edit_content.feature", branch_files)  # not lost: it is on the bead's branch
        self.assertNotIn("client/log.txt", branch_files)  # the base ignores it: no junk on the branch
        self.assertFalse(Path(self.wt, "tests", "edit_content.feature").exists())  # and the slot is at the base
        self.assertFalse(self.eng.git("symbolic-ref", "--short", "-q", "HEAD"))


class DeadLane(StagesTest):
    """A lane that fails to start without being marked out must not hold a read-only step for ten minutes."""

    def blips(self, n, lane="GROK_SUBSCRIPTION"):
        """vendor_blip (lane / transient / poll): the lane failed to start. Three polls wait for it, the next try goes elsewhere."""
        return [te.stop("vendor_blip", family="xai", lane=lane, say="opencode failed before any work: spending limit")] * n

    def test_a_retry_from_a_failing_family_routes_the_next_try_past_it(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": self.blips(4) + [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        reviews = [c for c in s.calls if c[0] == "reviewer"]
        self.assertEqual(len(reviews), 5)  # three polls of the lane, then the route is asked again
        self.assertEqual(reviews[4][2], "xai")  # authored-by the failing family: the route puts the others first
        self.assertNotEqual(reviews[0][2], "xai")

    def test_the_writers_own_family_after_a_dead_lane_is_flagged_same_family(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": self.blips(4) + [CLEAN]},
                                j_extra={"review": [{"family": "openai"}]})  # the route landed on openai, the writer's family
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(self.eng.last_flag, "same_family")
        self.assertIn("review is from the writer's own model family", self.eng.log_path.read_text())

    def test_a_same_family_step_with_delegates_warning_is_logged_traced_and_commented_never_paused(self):
        extra = {"review": [{"flag": "same_family", "warning": "only the Codex lane is up: the review is the writer's own model"}]}
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, j_extra=extra)
        self.assertEqual(rc, 0, self.blocked)
        note = "the review step ran on the writer's own model family: only the Codex lane is up"
        self.assertIn(note, self.eng.log_path.read_text())
        comments = [c[3] for c in self.bd_calls if c[:2] == ("comments", "add") and c[3].startswith("Lane (engine)")]
        self.assertEqual(len(comments), 1)
        self.assertIn(note, comments[0])
        last = json.loads((tl.config_dir() / "traces.jsonl").read_text().splitlines()[-1])
        self.assertEqual(last["lane_notes"], [note + last["lane_notes"][0][len(note):]])
        self.assertIn("only the Codex lane is up", [s_["warning"] for s_ in last["sessions"] if s_["node"] == "review"][0])
        self.assertTrue(self.closed)  # it landed

    def test_one_family_failing_twice_is_not_switched_back_and_forth(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": self.blips(5, "GROK") + [CLEAN]})
        reviews = [c for c in s.calls if c[0] == "reviewer"]
        self.assertEqual([c[2] for c in reviews][4:], ["xai", "xai"])  # rebound once, kept

    def test_a_busy_lane_is_waited_for_as_before(self):
        busy = te.stop("busy", family="openai", lane="OPENAI_SUBSCRIPTION", say="no free slot")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [busy, CLEAN]})
        reviews = [c for c in s.calls if c[0] == "reviewer"]
        self.assertEqual(reviews[1][2], reviews[0][2])


class Contracts(StagesTest):
    """tl-bxk.13.16: infrastructure is retried with a rest, never asked; the version is recorded."""

    FLAKY = ("import os, subprocess, sys\nm = %r\nn = int(open(m).read()) if os.path.exists(m) else 0\n"
             "open(m, 'w').write(str(n + 1))\n"
             "if n < %d:\n    sys.stderr.write('error: RPC failed; curl 56 Send failure: Broken pipe\\nfatal: the remote end hung up unexpectedly\\n'); sys.exit(1)\n"
             "sys.exit(subprocess.call(['git', 'push', 'origin', 'HEAD:main']))\n")

    def land_with(self, fails):
        script = Path(self.tmp.name, "flaky_push.py")
        script.write_text(self.FLAKY % (str(Path(self.tmp.name, "flaky-count")), fails))
        return te.PY + " " + str(script).replace("\\", "/")

    def test_a_network_failure_on_the_push_is_retried_with_a_rest_and_lands(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, land=self.land_with(2))
        self.assertEqual(rc, 0, self.blocked)
        text = self.eng.log_path.read_text()
        self.assertEqual(text.count("the push failed with a network error"), 2)
        self.assertIsNone(self.eng.__dict__.get("asked") or None)
        self.assertTrue(self.closed and self.closed[0].startswith("merged"))

    def test_a_push_that_keeps_failing_pauses_the_bead_and_asks_nobody(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, land=self.land_with(99))
        self.assertNotEqual(rc, 0)
        self.assertTrue(self.eng.why.startswith("paused: the land push failed 3 times"), self.eng.why)
        self.assertFalse(self.eng.asked)

    @te.no_repo
    def test_a_hooks_test_output_before_the_push_is_not_a_network_error(self):
        tail = "tests: Connection refused by the fake server (expected)\n" + "ok test passed\n" * 60 + "error: failed to push some refs\n"
        self.assertTrue(engine.TRANSIENT_PUSH.search(tail))  # the whole output would match
        self.assertFalse(engine.TRANSIENT_PUSH.search(tail[-600:]))  # the engine reads only the push's own last lines

    @te.no_repo
    def test_a_rejected_or_other_push_failure_is_not_retried_as_the_network(self):
        self.assertFalse(engine.TRANSIENT_PUSH.search("! [rejected] HEAD -> main (non-fast-forward)"))
        self.assertFalse(engine.TRANSIENT_PUSH.search("remote: error: GH006: Protected branch update failed"))
        self.assertTrue(engine.TRANSIENT_PUSH.search("fatal: unable to access 'https://x/': Could not resolve host: x"))

    def test_a_delegate_crash_is_retried_fresh_and_the_run_goes_on(self):
        crash = fake_route.NO_ANSWER  # route.py died: delegate printed no answer
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [crash, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer", "reviewer"])
        self.assertIn("delegate crashed", self.eng.log_path.read_text())

    def test_the_wip_commit_skips_the_pre_commit_hook_and_a_failed_one_is_loud(self):
        import os
        import subprocess
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        eng = self.eng
        hook = Path(eng.git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "hooks" / "pre-commit"
        hook.parent.mkdir(exist_ok=True)
        hook.write_text("#!/bin/sh\necho 'csharpier: unformatted' >&2\nexit 1\n")
        os.chmod(str(hook), 0o755)
        (Path(eng.wt) / "wip-file.txt").write_text("x\n")
        self.assertTrue(eng.wip("paused"))
        self.assertEqual(eng.git("status", "--porcelain"), "")
        self.assertIn("wip (t-1): paused", eng.git("log", "-1", "--format=%s"))
        (Path(eng.wt) / "wip-file2.txt").write_text("y\n")
        with mock.patch.object(eng, "sh", return_value=(1, "fatal: boom")), mock.patch.object(eng, "warn") as warn:
            self.assertFalse(eng.wip("paused"))
        self.assertIn("wip commit", warn.call_args[0][0])
        self.assertIn("boom", warn.call_args[0][0])

    def test_a_lane_that_is_out_for_hours_pauses_with_its_reset_time_and_is_not_waited_for(self):
        # lifesim r0yc/rl4s: the dead lane's own reset time is hours away; delegate re-routes inside the call, so a stop is final
        import time
        due = time.time() + 3 * 3600
        out = te.stop("rate_limited", say="lane_out: ZAI", lane="ZAI", at=due)
        rc, s = self.run_engine({"plan": [PLAN], "write": [out, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker"])
        self.assertAlmostEqual(self.eng.retry_after, due, delta=1)
        self.assertTrue(any(c[:3] == ("comments", "add", "t-1") and c[3].startswith("Engine paused:") and "paused: no lane for write until" in c[3]
                            for c in self.bd_calls))

    def test_a_lane_that_is_out_with_no_reset_time_pauses_at_once(self):
        out = te.stop("rate_limited", say="lane_out: ZAI", lane="ZAI")
        rc, s = self.run_engine({"plan": [PLAN], "write": [out], "review": [CLEAN]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker"])
        self.assertTrue(any(c[:3] == ("comments", "add", "t-1") and c[3].startswith("Engine paused:") and "paused: no lane for write" in c[3] for c in self.bd_calls))

    def test_a_delegate_that_keeps_crashing_pauses_the_bead_and_asks_nobody(self):
        crash = fake_route.NO_ANSWER
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [crash, crash, crash]})
        self.assertNotEqual(rc, 0)
        self.assertTrue(self.eng.why.startswith("failed: delegate crashed 3 times on the review step"), self.eng.why)
        self.assertFalse(self.eng.asked)  # a machine fault: the bead stays open, labelled engine-fault, nobody is asked
        self.assertEqual(self.blocked, [])
        self.assertTrue(any(c[:3] == ("label", "add", "t-1") and c[3] == "engine-fault" for c in self.bd_calls), self.bd_calls)

    def test_a_run_again_answer_keeps_the_plan_and_is_no_amend(self):
        ask = dict(WRITE, question="Which format?")
        rc, _ = self.run_engine({"plan": [PLAN], "write": [ask]})
        self.assertEqual(rc, 2)
        path = tl.config_dir() / "asks" / "t-1.json"
        a = json.loads(path.read_text())
        path.write_text(json.dumps(dict(a, kind="stuck")))  # an over-budget or stuck ask, which has a Run again button
        with self.store.stub(comments=[{"author": "denis", "text": "Run again."}]):
            rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertNotIn("planner", [c[0] for c in s.calls])
        self.assertIn("only asks for a rerun", self.eng.log_path.read_text())
        for text in ("run-again", "Retry!", "re-run", "try again"):
            self.assertTrue(engine.RERUN_ANSWER.fullmatch(" ".join(text.lower().replace("-", " ").split()).strip(" .!")), text)
        for text in ("yes", "use option A", "run again with more budget", "continue", "go on", "resume"):
            self.assertFalse(engine.RERUN_ANSWER.fullmatch(text), text)

    def test_a_real_answer_still_amends(self):
        ask = dict(WRITE, question="Which format?")
        self.run_engine({"plan": [PLAN], "write": [ask]})
        with self.store.stub(comments=[{"author": "denis", "text": "Use the new format, then run again."}]):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(s.calls[0][0], "planner")

    def test_asks_of_closed_or_missing_beads_are_closed_and_others_left(self):
        asks = tl.config_dir() / "asks"
        asks.mkdir(exist_ok=True)
        other = Path(self.tmp.name) / "other-repo"
        (other / ".beads").mkdir(parents=True)
        (Path(self.wt) / ".beads").mkdir(exist_ok=True)
        for bead in ("b-open", "b-closed", "b-gone", "b-hidden"):
            (asks / ("%s.json" % bead)).write_text(json.dumps({"v": 1, "id": bead + "-1", "bead": bead, "status": "open", "kind": "stuck",
                                                                "repo": str(self.wt)}))
        (asks / "b-flaky.json").write_text(json.dumps({"v": 1, "id": "f-1", "bead": "b-flaky", "status": "open", "kind": "stuck",
                                                        "repo": str(other)}))  # its tracker fails: nothing is learned, the ask stays
        (asks / "b-norepo.json").write_text(json.dumps({"v": 1, "id": "n-1", "bead": "b-norepo", "status": "open", "kind": "stuck"}))
        (asks / "b-answered.json").write_text(json.dumps({"v": 1, "id": "x", "bead": "b-answered", "status": "answered"}))
        calls = []

        def fake_bd(*a, **k):
            calls.append((a, k.get("cwd")))
            if k.get("cwd") == str(other):
                return mock.Mock(returncode=1, stdout="", stderr="dolt: database not found")
            if a[0] == "show":  # absent from the list: only a bead bd really does not know is gone (a gate or wisp is hidden from lists)
                return (mock.Mock(returncode=0, stdout="[{}]", stderr="") if a[1] == "b-hidden"
                        else mock.Mock(returncode=1, stdout="", stderr="Error: no issue found matching %s" % a[1]))
            return mock.Mock(returncode=0, stderr="", stdout=json.dumps([{"id": "b-open", "status": "open"}, {"id": "b-closed", "status": "closed"}]))
        with tlbd.bd_boundary(fake_bd):
            closed = tl.close_stale_asks(every=0)
            self.assertEqual(sorted(closed), ["b-closed", "b-gone"])
            self.assertEqual(tl.close_stale_asks(), [])  # throttled
        self.assertEqual([c[0][0] for c in calls].count("list"), 2)  # one list per repo, not one read per ask (a show only for an absent id)
        state = {b: json.loads((asks / ("%s.json" % b)).read_text())["status"] for b in ("b-open", "b-closed", "b-gone", "b-hidden", "b-flaky", "b-answered", "b-norepo")}
        self.assertEqual(state, {"b-hidden": "open", "b-open": "open", "b-closed": "closed", "b-gone": "closed", "b-flaky": "open", "b-answered": "answered",
                                 "b-norepo": "open"})  # no repo recorded: which tracker to ask is unknown, the ask stays


class PlanTimeout(StagesTest):
    """tl-btt: a check that sets a limit above the engine's check limit is sent back at plan time."""

    @te.no_repo
    def test_the_limits_a_check_sets_for_itself_are_read_in_minutes(self):
        for check, minutes in (("just play --timeout_ms 2400000", 40.0), ("tool -testTimeoutMs=1800000", 30.0), ("run --timeout=40m", 40.0),
                               ("run --timeout 2h", 120.0), ("timeout 2400 python3 t.py", 40.0), ("x --timeout-min 45", 45.0),
                               ("x timeout_seconds=600", 10.0), ("x --timeout 90", 1.5)):
            got = [m for m, _ in lint.own_timeouts(check)]
            self.assertEqual(got, [minutes], check)
        for check in ("pytest tests", "grep -q timeout config.yaml", "x --timeouts 5", "x --no-timeout", "x timeout_msg"):
            self.assertEqual(lint.own_timeouts(check), [], check)

    @te.no_repo
    def test_yxbb3s_play_test_of_40_minutes_under_a_30_minute_cap_is_found(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["just unity-play-tests --timeout_ms 2400000", HAS_F])])
        got = lint.timeout_problems(plan, 30)
        self.assertEqual(len(got), 1)
        self.assertIn("= 40 min, above the engine's check limit of 30 min", got[0])
        self.assertEqual(lint.timeout_problems(plan, 40), [])  # equal is fine
        self.assertEqual(lint.timeout_problems(plan, 60), [])
        cases = dict(PLAN, cases=[{"criterion": "c", "check": "x --timeout 5400", "class": "test"}])
        self.assertEqual(len(lint.timeout_problems(cases, 60)), 1)  # cases are checks too

    def test_the_plan_goes_back_to_the_planner_once_with_the_reason(self):
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[HAS_F + " ; true --timeout_ms 2400000"])])
        rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]}, check_timeout_min=30)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn("above the engine's check limit of 30 min", s.prompts[1])

    def test_a_plan_inside_the_limit_is_not_sent_back(self):
        ok = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[HAS_F + " ; true --timeout_ms 600000"])])
        rc, s = self.run_engine({"plan": [ok], "write": [WRITE], "review": [CLEAN]}, check_timeout_min=30)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])


class ClaimPerBead(StagesTest):
    """tl-kwo: a claim is live when an engine runs that bead, not because the claiming actor's loop is alive."""

    def reclaim(self, bead, slots, running, hand_live=False):
        import loop
        with self.store.stub(show=bead), mock.patch.object(tl, "slot_beads", return_value=slots), \
                mock.patch.object(tl, "live_actors", return_value={"tl-2be89f88"} if hand_live or slots else set()), \
                mock.patch.object(loop, "running", return_value=running), self.store.stub(comments=[]), \
                self.store.stub(bd_fn=lambda *a, **k: mock.Mock(returncode=0)):
            return engine.reclaim("o67g", str(self.wt), store=self.store)

    BEAD = {"id": "o67g", "status": "open", "assignee": "tl-2be89f88", "lease_expires_at": "2999-01-01T00:00:00Z", "dependencies": []}
    SLOT = {"id": "sl-5", "status": "in_progress", "assignee": "tl-2be89f88", "lease_expires_at": "2999-01-01T00:00:00Z",
            "metadata": {"held_bead": "fld.27.12"}, "title": "slot h s5"}

    def test_a_bead_the_loop_left_for_another_is_takeable(self):
        ok, why = self.reclaim(self.BEAD, [self.SLOT], {"fld.27.12": "s5"})
        self.assertTrue(ok, why)
        self.assertIn("released tl-2be89f88", why)

    def test_an_engine_running_the_bead_is_a_live_claim(self):
        ok, why = self.reclaim(self.BEAD, [self.SLOT], {"fld.27.12": "s5", "o67g": "s2"})
        self.assertFalse(ok)
        self.assertIn("a live claim", why)

    def test_the_loop_running_this_very_bead_keeps_its_claim(self):
        slot = dict(self.SLOT, metadata={"held_bead": "o67g"})
        ok, why = self.reclaim(self.BEAD, [slot], {})  # the slot says it, the engine is just starting
        self.assertFalse(ok)

    def test_a_session_working_by_hand_keeps_its_claim(self):
        ok, why = self.reclaim(self.BEAD, [], {}, hand_live=True)
        self.assertFalse(ok)
        self.assertIn("a live claim", why)

    def test_the_release_is_conditional_on_the_claim_just_read(self):
        import loop
        calls = []
        with self.store.stub(show=self.BEAD), mock.patch.object(tl, "slot_beads", return_value=[self.SLOT]), \
                mock.patch.object(tl, "live_actors", return_value={"tl-2be89f88"}), mock.patch.object(loop, "running", return_value={}), \
                self.store.stub(comments=[]), \
                self.store.stub(bd_fn=lambda *a, **k: calls.append(a) or mock.Mock(returncode=0)):
            ok, why = engine.reclaim("o67g", str(self.wt), store=self.store)
        self.assertTrue(ok, why)
        self.assertEqual(calls[-1], ("update", "o67g", "--if-assignee", "tl-2be89f88", "--assignee", ""))

    def test_a_claim_that_changed_hands_meanwhile_is_not_taken(self):
        import loop
        with self.store.stub(show=self.BEAD), mock.patch.object(tl, "slot_beads", return_value=[self.SLOT]), \
                mock.patch.object(tl, "live_actors", return_value={"tl-2be89f88"}), mock.patch.object(loop, "running", return_value={}), \
                self.store.stub(comments=[]), self.store.stub(bd_fn=lambda *a, **k: mock.Mock(returncode=1)):
            ok, why = engine.reclaim("o67g", str(self.wt), store=self.store)
        self.assertFalse(ok)
        self.assertIn("changed hands", why)

    def test_a_loop_that_pauses_a_bead_clears_its_assignee(self):
        late = te.stop("no_lane", at=engine.time.time() + 3600, family="openai", lane="OPENAI", say="no lane")
        rc, s = self.run_engine({"plan": [late]})
        self.assertTrue(self.eng.why.startswith("paused:"), self.eng.why)
        updates = [c for c in self.bd_calls if c[:2] == ("update", "t-1") and "--append-notes" not in c]
        self.assertTrue(updates and updates[-1][2:6] == ("--status", "open", "--assignee", ""), updates)
        self.assertTrue([c for c in self.bd_calls if c[:3] == ("comments", "add", "t-1") and c[3].startswith("Engine paused:")], self.bd_calls)


class FreshAside(StagesTest):
    """--fresh (lifesim-6pld): the old branch is kept as task/<id>-stale-<time> and the task starts again on the base."""

    def old_branch(self, commits=1):
        te.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        for k in range(commits):
            (self.wt / ("old%d.txt" % k)).write_text("earlier work\n")
            te.sh("git", "add", "-A", cwd=self.wt)
            te.sh("git", "commit", "-qm", "wip %d" % k, cwd=self.wt)
        te.sh("git", "checkout", "-q", "-", cwd=self.wt)

    def branches(self):
        return self.eng.git("branch", "--list", "task/t-1*", "--format=%(refname:short)").split()

    def test_fresh_keeps_the_old_branch_aside_and_starts_on_the_base(self):
        self.old_branch(2)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, fresh=True)
        self.assertEqual(rc, 0, self.blocked)
        text = self.eng.log_path.read_text()
        self.assertIn("--fresh: the old branch task/t-1 is kept as task/t-1-stale-", text)
        self.assertNotIn("git checkout -q task/t-1\n", text)  # the old branch was never checked out
        stale = [b for b in self.branches() if "-stale-" in b]
        self.assertEqual(len(stale), 1)
        kept = self.eng.git("ls-tree", "-r", "--name-only", stale[0]).split()
        self.assertIn("old1.txt", kept)  # the earlier work is there
        self.assertNotIn("old0.txt", self.eng.git("ls-tree", "-r", "--name-only", "origin/main").split())
        self.assertTrue(any("Fresh (engine)" in str(c) for c in self.bd_calls))

    def test_fresh_on_a_branch_with_no_work_of_its_own_just_starts_on_the_base(self):
        te.sh("git", "branch", "task/t-1", "HEAD", cwd=self.wt)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, fresh=True)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([b for b in self.branches() if "-stale-" in b], [])

    def test_without_fresh_the_old_branch_is_used_as_before(self):
        self.old_branch(1)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual([b for b in self.branches() if "-stale-" in b], [])
        self.assertIn("git checkout -q task/t-1", self.eng.log_path.read_text())


class FollowUps(StagesTest):
    """tl-7y6.7.9: a follow-up is filed only when bd's create worked; lint sections are added once; a refused one is never 'filed'."""
    LO = {"title": "Rename x", "why": "found in passing"}
    LINT = "missing required sections for task: ## Acceptance Criteria, ## Touches"

    def lint_bd(self, always=False):
        def fake(*a, **kw):
            r = self.fake_bd(*a, **kw)
            if a[:1] == ("create",):
                body = a[a.index("--description") + 1] if "--description" in a else ""
                if always or not ("## Touches" in body and "## Acceptance Criteria" in body):
                    return mock.Mock(returncode=1, stdout="", stderr=self.LINT)
            return r
        return fake

    def reflect_comments(self):
        return [c[3] for c in self.bd_calls if c[:2] == ("comments", "add") and c[3].startswith("Reflect (engine)")]

    def test_a_follow_up_bd_lint_refuses_is_filed_again_with_the_sections_it_names(self):
        with self.store.stub(bd_fn=self.lint_bd()):
            rc, _ = self.run_engine({"plan": [dict(PLAN, leftovers=[self.LO])], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        creates = [c for c in self.bd_calls if c[:2] == ("create", "Rename x")]
        self.assertEqual(len(creates), 2)
        body = creates[1][creates[1].index("--description") + 1]
        self.assertIn("found in passing", body)
        self.assertIn("## Touches", body)
        self.assertIn("## Acceptance Criteria", body)
        self.assertIn("filed=1", self.reflect_comments()[0])
        self.assertNotIn("unfiled", self.reflect_comments()[0])

    def test_a_follow_up_bd_will_not_take_is_reported_unfiled_the_run_still_lands(self):
        with self.store.stub(bd_fn=self.lint_bd(always=True)):
            rc, _ = self.run_engine({"plan": [dict(PLAN, leftovers=[self.LO])], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(self.eng.filed, [])
        self.assertIn("filed=0", self.reflect_comments()[0])
        self.assertIn("unfiled=1", self.reflect_comments()[0])
        self.assertTrue(any(c[:2] == ("comments", "add") and c[3].startswith("Follow-up (engine)") and "Rename x" in c[3]
                            for c in self.bd_calls))
        self.assertEqual(len([c for c in self.bd_calls if c[:2] == ("create", "Rename x")]), 2)  # one retry, no more

    @te.no_repo
    def test_lint_sections_reads_the_headings_bd_names(self):
        self.assertEqual(engine.lint_sections("Error: missing required sections for bug: ## Steps to Reproduce, ## Acceptance Criteria"),
                         ["Steps to Reproduce", "Acceptance Criteria"])
        self.assertEqual(engine.lint_sections("some other failure"), [])
        body = engine.with_sections("why\n\n## Touches\nx.py", ["Touches", "Acceptance Criteria"], "t-1")
        self.assertEqual(body.count("## Touches"), 1)
        self.assertIn("## Acceptance Criteria", body)


if __name__ == "__main__":
    unittest.main()
