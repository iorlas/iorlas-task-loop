"""Stage tests, part 3: the stale tree, slot hygiene, dead lanes, contracts and follow-ups. Split from test_stages."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from run.test_stages import StagesTest
from support import engine_case as te
from support import gitq, homes, procsim, tlbd
from support.checkpoints import put_ck, read_ck
from support.engine_case import engine, lint
from support.pushsim import pusher
from support.spawn import port_git, real_spawner
from support.who import who

import tltestkit.shellkit
from taskloop.adapters import (
    bd,
    bdcreate,
)
from taskloop.app.asks import admission
from taskloop.app.run import running as wrunning
from taskloop.app.slots import config as wslots_config
from taskloop.app.wire import asks as wasks
from taskloop.domain.checks.cmd import matchers as sh_matchers
from tlkernel import checkmatchers as matchers
from tlkernel import wire
from tlkernel.ask import Ask
from tlkernel.env import snapshot
from tlkernel.gitfacts import GitOutcome
from tlkernel.ids import BeadId
from tlkernel.landmatchers import _TRANSIENT as TRANSIENT_PUSH
from tltestkit import fake_route
from tltestkit.checks import typed
from tltestkit.plans import CLEAN, FALSE, HAS_F, PLAN, WRITE


class StaleTree(StagesTest):
    """tl-fsj: the tree a check runs on must have what the base's config names."""

    def main_moves(self, name="moved.txt"):
        base = Path(self.tmp.name, "base-moves")
        if not base.exists():
            tltestkit.shellkit.sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        tltestkit.shellkit.sh("git", "pull", "-q", "origin", "main", cwd=base)
        (base / name).write_text("main moved on\n")
        tltestkit.shellkit.sh("git", "add", "-A", cwd=base)
        tltestkit.shellkit.sh("git", "commit", "-qm", "main moves", cwd=base)
        tltestkit.shellkit.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)

    def test_a_land_logs_its_try_with_the_bases_and_whether_the_rebase_moved(self):
        self.stopped_run()
        self.main_moves()
        rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert "rebased the task branch onto the latest origin/main" in self.eng.log_path.read_text()
        assert "planner" not in [c[0] for c in s.calls]  # the plan was kept
        assert self.eng.stage_tree == ""
        tries = [json.loads(line) for line in self.eng.log_path.read_text().splitlines() if '"land_try"' in line]
        assert [(t["n"], t["rebase_moved"], t["failing"]) for t in tries] == [(1, False, "")]  # the resume rebased already
        assert tries[0]["base_before"] == tries[0]["base_after"]
        assert len(tries[0]["base_after"]) == 12

    def junk_and_moving_main(self):
        """The slot has Unity's untracked log (the base ignores it) and main has moved on with a new recipe file."""
        base = Path(self.tmp.name, "base-ignore")
        tltestkit.shellkit.sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        (base / ".gitignore").write_text("client/log.txt\n")
        (base / "justfile").write_text("fmt-check-changed:\n\techo ok\n")
        tltestkit.shellkit.sh("git", "add", "-A", cwd=base)
        tltestkit.shellkit.sh("git", "commit", "-qm", "recipe and ignore", cwd=base)
        tltestkit.shellkit.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
        tltestkit.shellkit.sh("git", "fetch", "-q", "origin", cwd=self.wt)
        (self.wt / "client").mkdir(exist_ok=True)
        (self.wt / "client" / "log.txt").write_text("unity wrote this\n")

    def test_a_resume_start_rebases_even_with_a_base_ignored_file_in_the_slot(self):
        # lifesim-fld.27.12-20261024-230954: started_because resume, 75 commits behind, no rebase, the check named a recipe the tree lacked
        self.stopped_run()
        tltestkit.shellkit.sh("git", "checkout", "-q", "task/t-1", cwd=self.wt)
        self.junk_and_moving_main()
        rc, _s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert "rebased the task branch onto the latest origin/main" in self.eng.log_path.read_text()
        assert Path(self.wt, "justfile").exists() or "justfile" in gitq.git("ls-tree", "-r", "--name-only", "HEAD", cwd=self.eng.wt)

    def test_an_answer_start_rebases_even_with_a_base_ignored_file_in_the_slot(self):
        # lifesim-6pld-20261024-224705: started_because answer, the same
        tltestkit.shellkit.sh("git", "checkout", "-q", "-b", "task/t-1", cwd=self.wt)
        (self.wt / "g.txt").write_text("earlier work\n")
        tltestkit.shellkit.sh("git", "add", "-A", cwd=self.wt)
        tltestkit.shellkit.sh("git", "commit", "-qm", "wip (t-1): blocked", cwd=self.wt)
        tltestkit.shellkit.sh("git", "checkout", "-q", "-", cwd=self.wt)
        self.junk_and_moving_main()
        tltestkit.shellkit.sh("git", "checkout", "-q", "task/t-1", cwd=self.wt)
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert "rebased the task branch onto the latest origin/main" in self.eng.log_path.read_text()

    def test_a_tracked_change_in_the_slot_still_stops_the_rebase(self):
        tltestkit.shellkit.sh("git", "checkout", "-q", "-b", "task/t-1", cwd=self.wt)
        e = engine.Engine(
            BeadId("t-1"),
            str(self.wt),
            wslots_config.load_cfg(str(self.wt), port_git()),
            store=self.store,
            env=snapshot(),
            spawner=real_spawner(),
            git=port_git(),
            who=who(),
        )
        self.junk_and_moving_main()
        (self.wt / "a.txt").write_text("edited and not committed\n")
        assert e.rebase.onto_base() == ""

    def test_the_writer_is_told_the_check_variables_exist_only_inside_the_engines_checks(self):
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        writer = s.prompts[1]
        assert "exist only while the engine runs the checks, never in your session" in writer
        assert "do not call it a blocker" in writer

    def test_a_configured_check_the_tree_lacks_is_the_engines_error_not_a_writers_amend(self):
        miss = [
            {
                "id": "fmt",
                "cmd": procsim.fake("fmt", procsim.exits(1, "error: Justfile does not contain recipe `fmt-check-changed`.")),
                "group": "static",
            }
        ]
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE]}, checks=miss)
        assert [c[0] for c in s.calls] == ["planner", "worker"]  # no second write: nothing was sent back to the writer
        assert self.eng.why.startswith("failed: infrastructure: the configured check `fmt` needs something this tree lacks"), self.eng.why

    @te.no_repo
    def test_words_in_the_middle_of_a_long_output_are_not_a_stale_tree(self):
        noisy = "a test about justfile prints: This checkout has no recipe x\n" + "ok\n" * 300 + "2 failed: Foo"
        assert matchers.STALE_TREE.search(noisy)  # the whole log matches...
        assert not matchers.stale_tree(noisy)  # ...its last lines, which the engine reads, do not

    def test_the_checkpoint_head_follows_a_squash_and_rebase_over_the_wip_commit(self):
        tltestkit.shellkit.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        (self.wt / "g.txt").write_text("work\n")
        tltestkit.shellkit.sh("git", "add", "-A", cwd=self.wt)
        tltestkit.shellkit.sh("git", "commit", "-qm", "work", cwd=self.wt)
        e = engine.Engine(
            BeadId("t-1"),
            str(self.wt),
            wslots_config.load_cfg(str(self.wt), port_git()),
            store=self.store,
            env=snapshot(),
            spawner=real_spawner(),
            git=port_git(),
            who=who(),
        )
        before = gitq.git("rev-parse", "HEAD", cwd=e.wt)
        (self.wt / "g.txt").write_text("more work\n")
        tltestkit.shellkit.sh("git", "commit", "-qam", "wip (t-1): blocked", cwd=self.wt)  # what reset() does with a dirty tree
        e.left_dirty = True
        put_ck(e, head=before)
        self.main_moves()
        tltestkit.shellkit.sh("git", "fetch", "-q", "origin", cwd=self.wt)
        assert e.rebase.onto_base() == "rebased"
        assert read_ck(e).head == gitq.git("rev-parse", "HEAD", cwd=e.wt)  # tl-7y6.2.19: the wip commit is squashed in
        assert gitq.git("rev-list", "--count", "origin/main..HEAD", cwd=e.wt) == "1"

    def test_the_lifesim_wording_is_found_too_and_a_plain_red_check_is_not(self):
        assert matchers.stale_tree("This checkout has no fmt-check-changed; rebase onto main")
        assert not matchers.stale_tree("2 tests failed: FooTests.Bar")
        plain = [{"id": "unit", "cmd": FALSE, "group": "tests"}]
        _rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE, WRITE]}, checks=plain, max_check_tries=2)
        assert "infrastructure" not in self.eng.why

    def test_a_plan_check_that_prints_the_same_words_is_the_writers_not_the_engines(self):
        words = procsim.fake("prints-justfile-words", procsim.exits(1, "Justfile does not contain recipe x"))
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[words])])
        _rc, _s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE, WRITE]}, max_check_tries=2)
        assert "infrastructure" not in self.eng.why


class SlotHygiene(StagesTest):
    """tl-g6a: base-ignored files do not make a slot dirty; a parked bead leaves the slot at the base."""

    def put_ignore_on_main(self, text, name=".gitignore", sub=""):
        base = Path(self.tmp.name, "base-ignore")
        if not base.exists():
            tltestkit.shellkit.sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        tltestkit.shellkit.sh("git", "pull", "-q", "origin", "main", cwd=base)
        d = base / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text)
        tltestkit.shellkit.sh("git", "add", "-A", cwd=base)
        tltestkit.shellkit.sh("git", "commit", "-qm", "gitignore", cwd=base)
        tltestkit.shellkit.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
        tltestkit.shellkit.sh("git", "fetch", "-q", "origin", cwd=self.wt)

    def test_files_the_base_ignores_do_not_count_as_dirty_work(self):
        self.put_ignore_on_main("client/log.txt\n")
        self.put_ignore_on_main("*.log\n!keep.log\n", sub="client")
        (self.wt / "client").mkdir()
        for f in ("client/log.txt", "client/Logs.log", "client/deep/x.log"):
            Path(self.wt, f).parent.mkdir(parents=True, exist_ok=True)
            Path(self.wt, f).write_text("noise\n")
        e = engine.Engine(
            BeadId("t-1"),
            str(self.wt),
            wslots_config.load_cfg(str(self.wt), port_git()),
            store=self.store,
            env=snapshot(),
            spawner=real_spawner(),
            git=port_git(),
            who=who(),
        )
        assert e.checkout.dirty_status() == ""
        assert "?? client/" in gitq.git("status", "--porcelain", cwd=e.wt)  # git alone calls it dirty: the old tree has no such rule
        Path(self.wt, "client/keep.log").write_text("real\n")  # negated by the base: real work
        Path(self.wt, "client/src.cs").write_text("real\n")
        assert sorted(ln[3:] for ln in e.checkout.dirty_status().splitlines()) == ["client/keep.log", "client/src.cs"]

    def test_files_the_base_does_not_ignore_keep_a_parked_slot_where_it_is(self):
        rc, _s = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Which format?")]})
        assert rc == 2
        # the bead's branch is checked out again by the next run; a stray untracked file the commit left out blocks the detach
        e = self.eng
        gitq.git("checkout", "-q", "task/t-1", cwd=e.wt)
        (self.wt / "stray.dat").write_text("not ignored, not committed\n")
        e.tree.leave_slot("blocked", "task/t-1")
        assert gitq.git("symbolic-ref", "--short", "-q", "HEAD", cwd=e.wt) == "task/t-1"

    def test_a_slot_left_on_an_old_branch_with_only_ignored_files_is_not_another_branchs_work(self):
        tltestkit.shellkit.sh("git", "checkout", "-qb", "task/old-bead", cwd=self.wt)
        self.put_ignore_on_main("client/log.txt\nclient/log-previous.txt\n")
        (self.wt / "client").mkdir()
        (self.wt / "client" / "log.txt").write_text("unity\n")
        (self.wt / "client" / "log-previous.txt").write_text("unity\n")
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert "another branch" not in self.eng.why

    def test_real_work_of_another_branch_still_stops_the_run(self):
        tltestkit.shellkit.sh("git", "checkout", "-qb", "task/old-bead", cwd=self.wt)
        (self.wt / "keep.py").write_text("work\n")
        rc, _s = self.run_engine({"plan": [PLAN]})
        assert rc != 0
        assert "uncommitted work of another branch" in self.eng.why

    def test_a_parked_bead_leaves_the_slot_at_the_detached_base(self):
        rc, _s = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Which format?")]})
        assert rc == 2
        head = subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=self.wt, capture_output=True, text=True, check=False)
        assert head.returncode != 0  # detached
        assert gitq.git("rev-parse", "HEAD", cwd=self.eng.wt) == gitq.git("rev-parse", "origin/main", cwd=self.eng.wt)
        assert gitq.git("rev-parse", "--verify", "-q", "refs/heads/task/t-1", cwd=self.eng.wt)  # the branch keeps the bead's work

    def test_a_parked_bead_with_work_commits_it_to_its_branch_first(self):
        rc, _s = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Which format?")]})
        assert rc == 2
        log = gitq.git("log", "--format=%s", "task/t-1", cwd=self.eng.wt)
        assert "wip (t-1)" in log  # f.txt was written by the writer: kept on the bead's branch
        assert Path(self.wt, "f.txt").exists() is False  # and gone from the slot

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
            rc, _s = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Which format?")]})
        assert rc == 2
        branch_files = gitq.git("ls-tree", "-r", "--name-only", "task/t-1", cwd=self.eng.wt).splitlines()
        assert "tests/edit_content.feature" in branch_files  # not lost: it is on the bead's branch
        assert "client/log.txt" not in branch_files  # the base ignores it: no junk on the branch
        assert not Path(self.wt, "tests", "edit_content.feature").exists()  # and the slot is at the base
        assert not gitq.git("symbolic-ref", "--short", "-q", "HEAD", cwd=self.eng.wt)


class DeadLane(StagesTest):
    """A lane that fails to start without being marked out must not hold a read-only step for ten minutes."""

    def blips(self, n, lane="GROK_SUBSCRIPTION"):
        """vendor_blip (lane / transient / poll): the lane failed to start. Three polls wait for it, the next try goes elsewhere."""
        return [te.stop("vendor_blip", family="xai", lane=lane, say="opencode failed before any work: spending limit")] * n

    def test_a_reviewer_retry_still_avoids_the_writers_family(self):  # tl-9un.15: the failing family was sent as the writer
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [*self.blips(4), CLEAN]})
        assert rc == 0, self.blocked
        reviews = [c for c in s.calls if c[0] == "reviewer"]
        assert len(reviews) == 5  # three polls of the lane, then the route is asked again
        assert all(r.reviewer_other_family for r in s.requests if r.role == "reviewer")
        assert s.results[1]["family"] == "openai"
        assert s.results[-1]["family"] != "openai"

    def test_a_reviewer_retry_after_a_writer_reroute_avoids_the_family_that_wrote(self):
        fallback = te.full(WRITE, "w2", family="xai")  # the write was routed to xai
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[])])  # the fallback write leaves no f.txt
        rc, s = self.run_engine({"plan": [plan], "write": [fallback], "review": [*self.blips(4, "OTHER"), CLEAN]})
        assert rc == 0, self.blocked
        assert all(r.reviewer_other_family for r in s.requests if r.role == "reviewer")
        assert s.results[1]["family"] == "xai"
        assert s.results[-1]["family"] != "xai"

    def test_a_review_that_only_the_writers_family_could_give_pauses_the_step(self):
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [*self.blips(4), te.full(CLEAN, "r", family="openai")]})
        assert rc != 0
        assert not self.closed
        assert (self.eng.retry_after or 0) > 0  # a missing lane is transient: it is retried on a timer
        assert "no lane of another family" in self.eng.log_path.read_text()

    def test_delegates_same_family_flag_pauses_the_step_too(self):
        extra = {"review": [{"flag": "same_family", "warning": "only the Codex lane is up: the review is the writer's own model"}]}
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, j_extra=extra)
        assert rc != 0
        assert not self.closed

    def test_a_busy_lane_is_waited_for_as_before(self):
        busy = te.stop("busy", family="openai", lane="OPENAI_SUBSCRIPTION", say="no free slot")
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [busy, CLEAN]})
        reviews = [c for c in s.calls if c[0] == "reviewer"]
        assert reviews[1][2] == reviews[0][2]


class Contracts(StagesTest):
    """tl-bxk.13.16: infrastructure is retried with a rest, never asked; the version is recorded."""

    def land_with(self, fails):
        return pusher("flaky-push", Path(self.tmp.name, "flaky-count"), cut_first=fails)

    def test_a_push_that_keeps_failing_pauses_the_bead_and_asks_nobody(self):
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, land=self.land_with(99))
        assert rc != 0
        assert self.eng.why.startswith("paused: the land push failed 3 times"), self.eng.why
        assert not self.eng.asked

    @te.no_repo
    def test_a_hooks_test_output_before_the_push_is_not_a_network_error(self):
        tail = "tests: Connection refused by the fake server (expected)\n" + "ok test passed\n" * 60 + "error: failed to push some refs\n"
        assert TRANSIENT_PUSH.search(tail)  # the whole output would match
        assert not TRANSIENT_PUSH.search(tail[-600:])  # the engine reads only the push's own last lines

    @te.no_repo
    def test_a_rejected_or_other_push_failure_is_not_retried_as_the_network(self):
        assert not TRANSIENT_PUSH.search("! [rejected] HEAD -> main (non-fast-forward)")
        assert not TRANSIENT_PUSH.search("remote: error: GH006: Protected branch update failed")
        assert TRANSIENT_PUSH.search("fatal: unable to access 'https://x/': Could not resolve host: x")

    def test_a_delegate_crash_fails_at_once(self):
        crash = fake_route.NO_ANSWER  # route.py died: delegate printed no answer
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [crash, CLEAN]})
        assert rc == 2
        assert self.eng.kind.value == "fault_crashed"
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer"]
        assert "delegate crashed" in self.eng.log_path.read_text()

    def test_the_wip_commit_skips_the_pre_commit_hook_and_a_failed_one_is_loud(self):
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        eng = self.eng
        hook = Path(gitq.git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=eng.wt)) / "hooks" / "pre-commit"
        hook.parent.mkdir(exist_ok=True)
        hook.write_text("#!/bin/sh\necho 'csharpier: unformatted' >&2\nexit 1\n")
        os.chmod(str(hook), 0o755)
        (Path(eng.wt) / "wip-file.txt").write_text("x\n")
        assert eng.tree.wip("paused")
        assert gitq.git("status", "--porcelain", cwd=eng.wt) == ""
        assert "wip (t-1): paused" in gitq.git("log", "-1", "--format=%s", cwd=eng.wt)
        (Path(eng.wt) / "wip-file2.txt").write_text("y\n")
        boom = GitOutcome(ok=False, output="fatal: boom")
        with mock.patch.object(type(eng.git), "try_commit", return_value=boom), mock.patch.object(eng, "warn") as warn:
            assert not eng.tree.wip("paused")
        assert "wip commit" in warn.call_args[0][0]
        assert "boom" in warn.call_args[0][0]

    def test_a_lane_that_is_out_for_hours_pauses_with_its_reset_time_and_is_not_waited_for(self):
        # lifesim r0yc/rl4s: the dead lane's own reset time is hours away; delegate re-routes inside the call, so a stop is final
        due = time.time() + 3 * 3600
        out = te.stop("rate_limited", say="lane_out: ZAI", lane="ZAI", at=due)
        rc, s = self.run_engine({"plan": [PLAN], "write": [out, WRITE], "review": [CLEAN]})
        assert rc == 2
        assert [c[0] for c in s.calls] == ["planner", "worker"]
        assert self.eng.retry_after == pytest.approx(due, abs=1)
        assert any(
                c[:3] == ("comments", "add", "t-1") and c[3].startswith("Engine paused:") and "paused: no lane for write until" in c[3]
                for c in self.bd_calls
            )

    def test_a_lane_that_is_out_with_no_reset_time_pauses_at_once(self):
        out = te.stop("rate_limited", say="lane_out: ZAI", lane="ZAI")
        rc, s = self.run_engine({"plan": [PLAN], "write": [out], "review": [CLEAN]})
        assert rc == 2
        assert [c[0] for c in s.calls] == ["planner", "worker"]
        assert any(
                c[:3] == ("comments", "add", "t-1") and c[3].startswith("Engine paused:") and "paused: no lane for write" in c[3]
                for c in self.bd_calls
            )

    def test_a_delegate_crash_faults_without_asking(self):
        crash = fake_route.NO_ANSWER
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [crash]})
        assert rc != 0
        assert self.eng.why.startswith("failed: delegate crashed on the review step"), self.eng.why
        assert not self.eng.asked  # a machine fault: the bead stays open, labelled engine-fault, nobody is asked
        assert self.blocked == []
        assert any(c[:3] == ("label", "add", "t-1") and c[3] == "engine-fault" for c in self.bd_calls), self.bd_calls

    def test_a_run_again_answer_keeps_the_plan_and_is_no_amend(self):
        ask = dict(WRITE, question="Which format?")
        rc, _ = self.run_engine({"plan": [PLAN], "write": [ask]})
        assert rc == 2
        self.file_answer("rerun")  # an over-budget or stuck ask has a Run again button
        rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert "planner" not in [c[0] for c in s.calls]
        assert "only asks for a rerun" in self.eng.log_path.read_text()

    def test_a_real_answer_still_amends(self):
        ask = dict(WRITE, question="Which format?")
        self.run_engine({"plan": [PLAN], "write": [ask]})
        self.file_answer("text", "Use the new format, then run again.")
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert s.calls[0][0] == "planner"

    def test_asks_of_closed_or_missing_beads_are_closed_and_others_left(self):
        asks = self.asks()
        other = Path(self.tmp.name) / "other-repo"
        (other / ".beads").mkdir(parents=True)
        (Path(self.wt) / ".beads").mkdir(exist_ok=True)
        for bead in ("b-open", "b-closed", "b-gone", "b-hidden"):
            asks.put(wire.load(Ask, te.ask_rec(id=bead + "-1", bead=bead, repo=str(self.wt))))
        asks.put(wire.load(Ask, te.ask_rec(id="f-1", bead="b-flaky", repo=str(other))))  # its tracker fails: the ask stays
        asks.put(wire.load(Ask, te.ask_rec(id="n-1", bead="b-norepo", repo="")))
        asks.put(wire.load(Ask, te.ask_rec(id="x", bead="b-answered", status="answered")))
        calls = []

        def fake_bd(*a, **k):
            calls.append((a, k.get("cwd")))
            if k.get("cwd") == str(other):
                return mock.Mock(returncode=1, stdout="", stderr="dolt: database not found")
            if a[0] == "show":  # absent from the list: only a bead bd really does not know is gone (a gate or wisp is hidden from lists)
                return (
                    mock.Mock(returncode=0, stdout=json.dumps([{"id": "b-hidden", "status": "open"}]), stderr="")
                    if a[1] == "b-hidden"
                    else mock.Mock(returncode=1, stdout="", stderr=f"Error: no issue found matching {a[1]}")
                )
            return mock.Mock(
                returncode=0, stderr="", stdout=json.dumps([{"id": "b-open", "status": "open"}, {"id": "b-closed", "status": "closed"}])
            )

        with tlbd.bd_boundary(fake_bd):
            closed = wasks.sweep("close", who(), homes.cfg(), every=0)
            assert sorted(closed) == ["b-closed", "b-gone"]
            assert wasks.sweep("close", who(), homes.cfg()) == []  # throttled
        assert [c[0][0] for c in calls].count("list") == 2  # one list per repo, not one read per ask (a show only for an absent id)
        state = {a.bead: a.status.value for a in asks.all()}
        assert state == {
                "b-hidden": "open",
                "b-open": "open",
                "b-closed": "closed",
                "b-gone": "closed",
                "b-flaky": "open",
                "b-answered": "answered",
                "b-norepo": "open",
            }  # no repo recorded: which tracker to ask is unknown, the ask stays


class PlanTimeout(StagesTest):
    """tl-btt: a check that sets a limit above the engine's check limit is sent back at plan time."""

    @te.no_repo
    def test_the_limits_a_check_sets_for_itself_are_read_in_minutes(self):
        for check, minutes in (
            ("just play --timeout_ms 2400000", 40.0),
            ("tool -testTimeoutMs=1800000", 30.0),
            ("run --timeout=40m", 40.0),
            ("run --timeout 2h", 120.0),
            ("timeout 2400 python3 t.py", 40.0),
            ("x --timeout-min 45", 45.0),
            ("x timeout_seconds=600", 10.0),
            ("x --timeout 90", 1.5),
        ):
            got = [m for m, _ in sh_matchers.own_timeouts(check)]
            assert got == [minutes], check
        for check in ("pytest tests", "grep -q timeout config.yaml", "x --timeouts 5", "x --no-timeout", "x timeout_msg"):
            assert sh_matchers.own_timeouts(check) == [], check

    @te.no_repo
    def test_yxbb3s_play_test_of_40_minutes_under_a_30_minute_cap_is_found(self):
        plan = typed(dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["just unity-play-tests --timeout_ms 2400000", HAS_F])]))
        got = lint.own_timeout_problems(plan, 30)
        assert len(got) == 1
        assert "= 40 min, above the engine's check limit of 30 min" in got[0]
        assert lint.own_timeout_problems(plan, 40) == []  # equal is fine
        assert lint.own_timeout_problems(plan, 60) == []
        cases = typed(dict(PLAN, cases=[{"criterion": "c", "check": "x --timeout 5400", "class": "test"}]))
        assert len(lint.own_timeout_problems(cases, 60)) == 1  # cases are checks too

    def test_the_plan_goes_back_to_the_planner_once_with_the_reason(self):
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[HAS_F, "echo play --timeout_ms 2400000"])])
        rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]}, check_wall_min=30)
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls] == ["planner", "planner", "worker", "reviewer"]
        assert "above the engine's check limit of 30 min" in s.prompts[1]

    def test_a_plan_inside_the_limit_is_not_sent_back(self):
        ok = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[HAS_F, "echo play --timeout_ms 600000"])])
        _rc, s = self.run_engine({"plan": [ok], "write": [WRITE], "review": [CLEAN]}, check_wall_min=30)
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer"]


class ClaimPerBead(StagesTest):
    """tl-kwo: a claim that is left after the lease sweep is live. The dead ones (a loop that went on, an ended lease, a paused run) are
    given back by the reconcile lease rules, before admit: tests/prune/test_leases.py."""

    def admit_when(self, bead, running):
        with self.store.stub(show=bead), mock.patch.object(wrunning, "running", return_value=running), self.store.stub(comments=[]):
            return admission.admit(BeadId("o67g"), str(self.wt), port_git(), who(), store=self.store, running_now=wrunning.running)

    BEAD: ClassVar[Any] = {
        "id": "o67g",
        "status": "open",
        "assignee": "tl-2be89f88",
        "lease_expires_at": "2999-01-01T00:00:00Z",
        "dependencies": [],
    }

    def test_an_engine_running_a_blocked_bead_is_a_live_claim(self):
        ok, why = self.admit_when(dict(self.BEAD, status="blocked"), {"o67g": "s2"})
        assert not ok
        assert "a live claim" in why

    def test_a_claim_left_after_the_sweep_is_a_live_claim(self):
        ok, why = self.admit_when(self.BEAD, {})
        assert not ok
        assert "a live claim" in why

    def test_a_claim_that_changed_hands_meanwhile_is_not_taken(self):
        blocked = dict(self.BEAD, status="blocked")
        cs = [{"author": "tl-x", "text": "Blocked: stuck", "created_at": "2026-10-25T10:00:00Z"}]
        with (
            self.store.stub(show=blocked),
            mock.patch.object(wrunning, "running", return_value={}),
            self.store.stub(comments=cs),
            self.store.stub(bd_fn=lambda *a, **k: mock.Mock(returncode=1)),
        ):
            ok, why = admission.admit(BeadId("o67g"), str(self.wt), port_git(), who(), store=self.store, running_now=wrunning.running)
        assert not ok
        assert "changed hands" in why

    def test_a_loop_that_pauses_a_bead_clears_its_assignee(self):
        late = te.stop("no_lane", at=time.time() + 3600, family="openai", lane="OPENAI", say="no lane")
        _rc, _s = self.run_engine({"plan": [late]})
        assert self.eng.why.startswith("paused:"), self.eng.why
        updates = [c for c in self.bd_calls if c[:2] == ("update", "t-1") and "--append-notes" not in c]
        assert updates and updates[-1][2:6] == ("--status", "open", "--assignee", ""), updates
        assert [c for c in self.bd_calls if c[:3] == ("comments", "add", "t-1") and c[3].startswith("Engine paused:")], self.bd_calls


class FreshAside(StagesTest):
    """--fresh (lifesim-6pld): the old branch is kept as task/<id>-stale-<time> and the task starts again on the base."""

    def old_branch(self, commits=1):
        tltestkit.shellkit.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        for k in range(commits):
            (self.wt / (f"old{k}.txt")).write_text("earlier work\n")
            tltestkit.shellkit.sh("git", "add", "-A", cwd=self.wt)
            tltestkit.shellkit.sh("git", "commit", "-qm", f"wip {k}", cwd=self.wt)
        tltestkit.shellkit.sh("git", "checkout", "-q", "-", cwd=self.wt)

    def branches(self):
        return gitq.git("branch", "--list", "task/t-1*", "--format=%(refname:short)", cwd=self.eng.wt).split()

    def test_fresh_keeps_the_old_branch_aside_and_starts_on_the_base(self):
        self.old_branch(2)
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, fresh=True)
        assert rc == 0, self.blocked
        text = self.eng.log_path.read_text()
        assert "--fresh: the old branch task/t-1 is kept as task/t-1-stale-" in text
        assert "git checkout -q task/t-1\n" not in text  # the old branch was never checked out
        stale = [b for b in self.branches() if "-stale-" in b]
        assert len(stale) == 1
        kept = gitq.git("ls-tree", "-r", "--name-only", stale[0], cwd=self.eng.wt).split()
        assert "old1.txt" in kept  # the earlier work is there
        assert "old0.txt" not in gitq.git("ls-tree", "-r", "--name-only", "origin/main", cwd=self.eng.wt).split()
        assert any("Fresh (engine)" in str(c) for c in self.bd_calls)

    def test_fresh_on_a_branch_with_no_work_of_its_own_just_starts_on_the_base(self):
        tltestkit.shellkit.sh("git", "branch", "task/t-1", "HEAD", cwd=self.wt)
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, fresh=True)
        assert rc == 0, self.blocked
        assert [b for b in self.branches() if "-stale-" in b] == []

    def test_without_fresh_the_old_branch_is_used_as_before(self):
        self.old_branch(1)
        _rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert [b for b in self.branches() if "-stale-" in b] == []
        assert "task/t-1" in self.branches()  # the old branch itself, not a fresh one beside it


class FollowUps(StagesTest):
    """tl-7y6.7.9: a follow-up is filed only when bd's create worked; lint sections are added once; a refused one is never 'filed'."""

    LO: ClassVar[Any] = {"title": "Rename x", "why": "found in passing"}
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
        assert rc == 0, self.blocked
        creates = [c for c in self.bd_calls if c[:2] == ("create", "Rename x")]
        assert len(creates) == 2
        body = creates[1][creates[1].index("--description") + 1]
        assert "found in passing" in body
        assert "## Touches" in body
        assert "## Acceptance Criteria" in body
        assert "filed=1" in self.reflect_comments()[0]
        assert "unfiled" not in self.reflect_comments()[0]

    def test_a_follow_up_bd_will_not_take_is_reported_unfiled_the_run_still_lands(self):
        with self.store.stub(bd_fn=self.lint_bd(always=True)):
            rc, _ = self.run_engine({"plan": [dict(PLAN, leftovers=[self.LO])], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert self.eng.filed == []
        assert "filed=0" in self.reflect_comments()[0]
        assert "unfiled=1" in self.reflect_comments()[0]
        assert any(c[:2] == ("comments", "add") and c[3].startswith("Follow-up (engine)") and "Rename x" in c[3] for c in self.bd_calls)
        assert len([c for c in self.bd_calls if c[:2] == ("create", "Rename x")]) == 2  # one retry, no more

    @te.no_repo
    def test_the_headings_bd_names_come_out_of_its_error(self):
        err = bd.error_of("Error: missing required sections for bug: ## Steps to Reproduce, ## Acceptance Criteria", "")
        assert (err.kind, err.missing_sections) == ("lint", ["Steps to Reproduce", "Acceptance Criteria"])
        assert bd.error_of("some other failure", "").missing_sections == []
        body = bdcreate.with_sections("why\n\n## Touches\nx.py", ["Touches", "Acceptance Criteria"], "t-1")
        assert body.count("## Touches") == 1
        assert "## Acceptance Criteria" in body


class EngineOnlyFlags(StagesTest):
    """The write step's request lists the engine-only recipes (route.py run --engine-only); read-only steps pass none."""

    def test_only_the_write_step_names_the_recipes_the_writer_must_not_run(self):
        checks = [
            {"id": "slow", "cmd": procsim.fake("just slow", procsim.exits(0)), "group": "tests", "writer": False},
            {"id": "fmt", "cmd": procsim.fake("just fmt", procsim.exits(0)), "group": "static", "writer": True},
        ]
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, checks=checks)
        flags = {role: [a[i + 1] for i, x in enumerate(a) if x == "--engine-only"] for a in s.argvs for role in [a[3]]}
        assert flags.get("worker") == ["slow"]
        assert [r for r, v in flags.items() if v and r != "worker"] == []

    def test_an_engine_only_just_recipe_of_a_plan_stage_is_named_too(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[HAS_F, procsim.fake("just full-check", procsim.exits(0))])])
        _rc, s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE, WRITE], "review": [CLEAN]})
        flags = {role: [a[i + 1] for i, x in enumerate(a) if x == "--engine-only"] for a in s.argvs for role in [a[3]]}
        assert flags.get("worker") == ["full-check"]
        assert [r for r, v in flags.items() if v and r != "worker"] == []
