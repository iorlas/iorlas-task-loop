"""Owner profile changes authorize one tip and patch, while retaining the base gate."""
import argparse
import hashlib
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import pytest

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.fakegit import FakeGit
from support.memstores import fake_stores
from support.narrow_hosts import FakePushHost, Stopped

from taskloop.app.land.cmds import Cmds, Stop
from taskloop.app.land.gate import mint, owner_refusal
from taskloop.app.land.host import Land
from taskloop.app.land.push import Pusher
from taskloop.app.land.push_judge import PushStatus, judge_push
from taskloop.app.land.stack import Stack
from taskloop.app.land.stackgate import StackGate
from taskloop.app.launch.check import run_check
from taskloop.app.wire.slotfx import FX
from taskloop.cli.land_stack import add_parser, cmd_land_stack
from tlkernel.config import load
from tlkernel.env import Env
from tlkernel.envvars import EnvVar, registered
from tlkernel.forge import StackItem
from tlkernel.gitfacts import TreeEntry
from tlkernel.ids import TreeSha
from tlkernel.profile_changes import ProfileChange
from tlkernel.runkey import BaseSha
from tltestkit.fake_clock import FakeClock

TEXT = 'Denis: "I approve this profile" 2026-11-02T12:00Z'
PATCH = 'diff --git a/.task-loop.json b/.task-loop.json\n-old\n+new\n'
DIFF_SHA = hashlib.sha256(PATCH.encode()).hexdigest()


def entry(oid):
    return [TreeEntry(mode="100644", kind="blob", oid=oid, path=".task-loop.json")]


class OwnerText(Case):
    def test_invalid_text_exits_two_in_one_line_before_creating_a_run(self):
        parser = argparse.ArgumentParser()
        add_parser(parser.add_subparsers())
        for text in ("", " " * 20, "yes 2026", "I approve this profile"):
            with self.subTest(text=text):
                args = parser.parse_args(["land-stack", "topic", "--profile-change", text])
                out = io.StringIO()
                with redirect_stdout(out), mock.patch("taskloop.app.land.stack.RunLocator") as locator:
                    rc = cmd_land_stack(args, mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock(), ["tl"], env=Env())
                assert rc == 2
                assert len(out.getvalue().splitlines()) == 1
                locator.assert_not_called()

    def test_engine_loop_run_and_lane_markers_refuse_even_when_empty(self):
        markers = [var.value for var in EnvVar if not var.name.startswith("TASK_LOOP_DASH_")]
        for name in (*markers, "TL_CHECK_LOG_SUITE", "TL_CHECK_RC_SUITE"):
            with self.subTest(name=name):
                assert registered(name)
                assert owner_refusal(TEXT, Env({name: ""})) == "profile change is an owner decision; not available to the engine or a lane"
        assert owner_refusal(TEXT, Env()) == ""
        assert owner_refusal(None, Env({EnvVar.TL_RUN_ID: "run"})) == ""

    def test_cli_engine_context_refuses_before_any_write(self):
        args = argparse.Namespace(profile_change=TEXT)
        out = io.StringIO()
        with redirect_stdout(out), mock.patch("taskloop.app.land.stack.RunLocator") as locator:
            rc = cmd_land_stack(args, mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock(), ["tl"],
                                env=Env({EnvVar.TL_RUN_ID: "run"}))
        assert rc == 2
        assert out.getvalue().strip() == "profile change is an owner decision; not available to the engine or a lane"
        locator.assert_not_called()


class OwnerGate(Case):
    def setup_method(self):
        self.git = FakeGit(**{"rev_parse__origin/main": "base", "rev_parse__tip^{tree}": "tree", "rev_parse__HEAD": "tip"})
        self.cmds = mock.Mock(spec=Cmds)
        self.cmds.port.side_effect = lambda text, fn: fn()
        self.stores = fake_stores()
        self.gate = StackGate(self.cmds, self.git, self.stores, "/repo", "origin/main", ["tl"])
        self.policy = json.dumps({"engine": {"checks": [{"id": "base-check", "argv": ["true"], "run": "gate"}]}})
        patch = mock.patch.object(self.git, "ls_tree", side_effect=lambda repo, rev, path: entry(rev))
        patch.start()
        self.addCleanup(patch.stop)

    def test_without_flag_profile_changed_still_stops(self):
        self.stores.profile_changes.append(ProfileChange(t=1000.0, owner_text=TEXT, repo="/repo", branch="topic",
                                                        tip="tip", base="base", diff_sha=DIFF_SHA, pid=42))
        with pytest.raises(Stop) as raised:
            self.gate.require("topic", "tip")
        assert "profile_changed:" in raised.value.why
        self.cmds.run.assert_not_called()
        assert len(self.stores.profile_changes.read_from().items) == 1

    def test_engine_context_cannot_pass_the_option_at_the_application_boundary(self):
        self.gate.env = Env({EnvVar.TASK_LOOP_WORKER: "1"})
        with pytest.raises(Stop) as raised:
            self.gate.require("topic", "tip", profile_change=TEXT)
        assert raised.value.rc == 2
        assert raised.value.why == "profile change is an owner decision; not available to the engine or a lane"
        self.cmds.port.assert_not_called()

    def test_owner_uses_base_gate_and_still_requires_evidence(self):
        with (mock.patch.object(self.git, "show", return_value=self.policy),
              mock.patch.object(self.gate, "worktree", return_value=""),
              mock.patch.object(self.gate, "red", return_value=[]) as red):
            assert self.gate.require("topic", "tip", profile_change=TEXT) == "base"
        assert [check.id for check in red.call_args.args[0].gate_checks] == ["base-check"]
        with (mock.patch.object(self.git, "show", return_value=self.policy),
              mock.patch.object(self.gate, "red", return_value=["base-check"]),
              mock.patch.object(self.gate, "worktree", return_value=""),
              mock.patch.object(self.gate, "fresh", return_value="/fresh"), pytest.raises(Stop)):
            self.gate.require("topic", "tip", profile_change=TEXT)
        assert self.stores.profile_changes.read_from().items == []

    def test_owner_runs_the_base_policy_and_rechecks_evidence(self):
        with (mock.patch.object(self.git, "show", return_value=self.policy),
              mock.patch.object(self.gate, "worktree", return_value="/worktree"),
              mock.patch.object(self.gate, "red", side_effect=[["base-check"], ["base-check"], []])):
            assert self.gate.require("topic", "tip", profile_change=TEXT) == "base"
        self.cmds.run.assert_called_once_with(["tl", "check", "--repo", "/worktree", "--policy-commit", "base"],
                                              extra={"TL_GREEN_LEDGER": "1"})

    def test_stack_records_exactly_one_row_after_gate_before_push(self):
        log, forge = mock.Mock(), mock.Mock()
        log.stamp = {}
        stack = Stack(forge, self.cmds, log, self.git, "/repo", Path("/lock"), mock.Mock(), mock.Mock(),
                      "owner", "session", self.gate, mock.Mock(), cfg=mock.Mock(), profile_change=TEXT,
                          fx=FX, queue_docs=self.stores.queue, queue_state=self.stores.queue_state,
                      profile_changes=self.stores.profile_changes)
        pr = mock.Mock(state="OPEN", head_oid="tip")

        def prepared(*args):
            rows = [item.rec for item in self.stores.profile_changes.read_from().items]
            assert len(rows) == 1
            row = rows[0]
            assert (
                (row.owner_text, row.repo, row.branch, row.tip, row.base, row.diff_sha)
                == (TEXT, "/repo", "topic", "tip", "base", DIFF_SHA)
            )
            assert (row.t, row.pid) == (1000, 42)
            return pr

        with (mock.patch.object(stack, "resolve", return_value=("topic", "tip", pr)),
              mock.patch.object(self.git, "show", return_value="{}"),
              mock.patch.object(self.git, "profile_diff", return_value=PATCH) as diff,
              mock.patch("taskloop.app.land.stack.time.time", return_value=1000),
              mock.patch("taskloop.app.land.stack.os.getpid", return_value=42),
              mock.patch.object(stack, "prepare", side_effect=prepared),
              mock.patch.object(stack, "merged", return_value="merged"), mock.patch.object(stack, "after")):
            stack.item(StackItem(branch="topic"))
        diff.assert_called_once_with("/repo", "base", "tip")
        assert len(self.stores.profile_changes.read_from().items) == 1

    def test_a_failed_audit_stops_before_push_or_merge(self):
        log = mock.Mock(stamp={})
        stack = Stack(mock.Mock(), self.cmds, log, self.git, "/repo", Path("/lock"), mock.Mock(), mock.Mock(),
                      "owner", "session", self.gate, mock.Mock(), cfg=mock.Mock(), profile_change=TEXT,
                          fx=FX, queue_docs=self.stores.queue, queue_state=self.stores.queue_state,
                      profile_changes=self.stores.profile_changes)
        with (mock.patch.object(stack, "resolve", return_value=("topic", "tip", None)),
              mock.patch.object(self.git, "show", return_value="{}"),
              mock.patch.object(self.git, "profile_diff", return_value=PATCH),
              mock.patch.object(self.stores.profile_changes, "append", side_effect=OSError("disk full")),
              mock.patch.object(stack, "prepare") as prepare, mock.patch.object(stack, "merged") as merged,
              pytest.raises(Stop) as raised):
            stack.item(StackItem(branch="topic"))
        assert raised.value.rc == 1
        assert "cannot append profile change audit" in raised.value.why
        prepare.assert_not_called()
        merged.assert_not_called()


class OwnerJudge(Case):
    def setup_method(self):
        self.clock = FakeClock(1000)
        self.git = FakeGit(merge_base="base", symbolic_ref="", dirty=True,
                           **{"rev_parse__base^{tree}": "base-tree", "rev_parse__tip^{tree}": "tree",
                              "rev_parse__HEAD^{tree}": "tree", "rev_parse__origin/main": "base", "rev_parse__HEAD": "tip", "diff": ""})
        self.stores = fake_stores()
        self.profile = json.dumps({"engine": {"checks": [{"id": "base-check", "argv": ["true"], "run": "gate"}]}})
        for patch in (mock.patch.object(self.git, "ls_tree", side_effect=lambda repo, rev, path: entry(rev)),
                      mock.patch.object(self.git, "show", side_effect=lambda repo, rev, path: self.profile),
                      mock.patch.object(self.git, "profile_diff", return_value=PATCH)):
            patch.start()
            self.addCleanup(patch.stop)

    def audit(self, **changes):
        row = ProfileChange(t=self.clock.now(), owner_text=TEXT, repo="/repo", branch="topic", tip="tip", base="base",
                            diff_sha=DIFF_SHA, pid=42)
        self.stores.profile_changes.append(row.replace(**changes))

    def judge(self):
        return judge_push("/repo", f"refs/heads/topic tip refs/heads/main {'0' * 40}\n", self.stores, self.git,
                          profile_changes=self.stores.profile_changes, env=Env(), clock=self.clock)

    def test_fresh_matching_row_allows_but_only_with_base_evidence(self):
        self.audit()
        with mock.patch("tlgate.authorization.results", return_value={"base-check": mock.Mock()}) as results:
            assert self.judge().status == PushStatus.ALLOWED
        assert [step.id for step in results.call_args.args[3].gate_checks] == ["base-check"]
        with (mock.patch("tlgate.authorization.results", return_value={"base-check": None}),
              mock.patch("tlgate.authorization.explain", return_value={"base-check": "env differs (expected a1 found b2)"})):
            decision = self.judge()
        assert decision.status == PushStatus.REFUSED
        assert "base-check (env differs (expected a1 found b2))" in decision.reasons[0]

    def test_missing_stale_wrong_tip_or_patch_never_authorizes(self):
        for change in (None, {"t": 399}, {"tip": "other"}, {"diff_sha": "wrong"}, {"t": 1001}):
            with self.subTest(change=change):
                self.stores = fake_stores()
                if change is not None:
                    self.audit(**change)
                result = self.judge()
                assert result.status == PushStatus.REFUSED
                assert "profile_changed:" in result.reasons[0]

    def test_fake_clock_expiry_at_six_hundred_seconds(self):
        self.profile = "{}"
        self.audit()
        self.clock.advance(600)
        assert self.judge().status == PushStatus.ALLOWED
        self.clock.advance(0.01)
        assert self.judge().status == PushStatus.REFUSED

    def test_constructed_engine_push_path_cannot_authorize_a_profile_change(self):
        def push(argv, **kwargs):
            decision = self.judge()
            return int(decision.status), "\n".join(decision.reasons)

        host = FakePushHost(self.git, push)
        pusher = Pusher(host, mock.Mock(lfs_push=mock.Mock(return_value=(0, ""))))
        with pytest.raises(Stopped) as raised:
            pusher.push(Land(), mint(TreeSha("tree"), BaseSha("base")))
        assert "profile_changed:" in str(raised.value)
        assert self.stores.profile_changes.read_from().items == []


class PolicyCheck(Case):
    def test_explicit_policy_commit_supplies_the_base_registry(self):
        git = FakeGit()
        cfg = load({"engine": {"checks": [{"id": "base-check", "argv": ["true"], "run": "gate"}]}}).engine
        args = argparse.Namespace(policy_commit="base", ids=[], all=False, staged=False, list=False)
        stage = mock.Mock()
        stage.bundle.repo = "/repo"
        with (mock.patch("tlgate.authorization.profile", return_value=cfg) as profile,
              mock.patch("taskloop.app.launch.check.profile_of", side_effect=AssertionError("tip profile used")),
              mock.patch("taskloop.app.launch.check.CliHost") as host,
              mock.patch("taskloop.app.launch.check.Checker") as checker, redirect_stdout(io.StringIO())):
            checker.return_value.run_items.return_value.results = []
            assert run_check(args, stage, env=Env(), spawner=mock.Mock(), git=git) == 0
        assert host.call_args.args[1] == cfg
        assert [step.id for step in checker.return_value.run_items.call_args.args[0]] == ["base-check"]
        profile.assert_called_once_with(git, "/repo", TreeSha("base"))
