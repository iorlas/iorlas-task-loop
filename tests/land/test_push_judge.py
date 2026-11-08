"""One application judge owns profile, evidence, stack coverage, and the read-only receipt rule."""
import json
import re
import sys
from pathlib import Path
from unittest import mock

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.fakegit import FakeGit
from support.memstores import fake_stores

from tlgate.cache import InputKeys, RunMemo, plan_digest
from tlgate.domain.specs import gate_items
from tlkernel.checks import CheckResult
from tlkernel.config import load
from tlkernel.env import Env
from tlkernel.gitfacts import TreeEntry
from tlkernel.ids import TreeSha
from tlkernel.runkey import BaseSha
from tlkernel.slots import GitReadFailure
from tlland.push_judge import PushStatus, judge_push


class PushJudge(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = tmp.name
        self.profile = Path(self.repo) / ".task-loop.json"
        self.profile.write_text(json.dumps({"engine": {"checks": [{"id": "suite", "argv": ["true"], "run": "gate"}]}}))
        self.tip_profile = self.profile.read_text()
        self.git = FakeGit(rev_parse__HEAD="head", dirty=False, is_ancestor=False, merge_base="policy", symbolic_ref="")
        self.git.replies.update({("rev_parse", "origin/main"): "base", ("rev_parse", "head^{tree}"): "tree",
                                 ("rev_parse", "low^{tree}"): "lower", ("rev_parse", "policy^{tree}"): "policy-tree",
                                 ("rev_parse", "task/x^{tree}"): "task-tree",
                                 ("rev_parse", "old-base^{tree}"): "policy-tree"})
        self.git.replies[("diff",)] = ""
        self.stores = fake_stores()
        self.key = mock.patch("tlkernel.check_files.repo_key", return_value="repo")
        self.key.start()
        self.addCleanup(self.key.stop)
        self.entries = mock.patch.object(self.git, "ls_tree", return_value=[
            TreeEntry(mode="100644", kind="blob", oid="profile", path=".task-loop.json")])
        self.ls_tree = self.entries.start()
        self.addCleanup(self.entries.stop)
        self.show_patch = mock.patch.object(self.git, "show", side_effect=lambda *args: self.tip_profile)
        self.show = self.show_patch.start()
        self.addCleanup(self.show_patch.stop)
        self.env = Env({"PATH": "/tools"})

    def request(self, *tips, remote="refs/heads/main", old="0" * 40):
        return "".join(f"refs/heads/{tip} {tip} {remote} {old}\n" for tip in tips)

    def judge(self, text=None):
        return judge_push(self.repo, self.request("head") if text is None else text, self.stores, self.git,
                          profile_changes=self.stores.profile_changes, env=self.env)

    def stamp(self, tree="tree", base="base", profile=None, planned=False):
        from_env = {"TL_SLOT": "check"}
        cfg = load(json.loads(profile or self.tip_profile)).engine
        keys = InputKeys(self.git, self.repo, TreeSha(tree))
        memo = RunMemo(self.stores, "repo", keys, BaseSha(base), from_env)
        memo.checks = {c.id: c for c in gate_items(cfg)}
        for step in gate_items(cfg):
            result = CheckResult(id=step.id, cmd=step.cmd, group=step.group, exit=0, status="passed")
            key = memo.key(step)
            if planned:
                result = CheckResult.skipped(step, "no matching changes").replace(planned=True)
                key = memo.planned_key(step, plan_digest(cfg.plan_cmd))
            assert key is not None
            memo.remember(key, result, 1, "")

    def test_valid_profile_uses_the_application_evidence_store(self):
        self.stamp()
        assert self.judge().status == PushStatus.ALLOWED

    def test_non_base_tips_need_no_receipts_or_checks(self):
        self.git.replies[("rev_parse", "HEAD")] = "task/x"
        for remote in ("refs/heads/task/x", "refs/heads/wip/x", "refs/heads/topic"):
            with self.subTest(remote=remote), mock.patch("tlgate.authorization.results") as evidence:
                decision = self.judge(self.request("task/x", remote=remote))
                assert decision.status == PushStatus.ALLOWED
                assert decision.reasons == ()
                evidence.assert_not_called()

    def test_task_tip_pushed_to_base_still_needs_receipts(self):
        self.git.replies[("rev_parse", "HEAD")] = "task/x"
        decision = self.judge(self.request("task/x"))
        assert decision.status == PushStatus.REFUSED
        assert "suite (no green run of tree task-tree under `true`)" in decision.reasons[0]

    def test_mixed_push_checks_only_the_base_tip(self):
        request = self.request("task/x", remote="refs/heads/task/x") + self.request("head")
        with mock.patch("tlgate.authorization.results", return_value={"suite": None}) as evidence:
            decision = self.judge(request)
        assert decision.status == PushStatus.REFUSED
        assert len(decision.reasons) == 1
        assert decision.reasons[0].startswith("refs/heads/head ")
        assert evidence.call_count == 1
        assert evidence.call_args.args[4] == TreeSha("tree")
        self.stamp()
        assert self.judge(request).status == PushStatus.ALLOWED

    def test_non_base_tip_cannot_cover_an_unproven_base_tip(self):
        self.stamp()
        self.git.replies[("is_ancestor",)] = True
        request = self.request("head", remote="refs/heads/task/x") + self.request("low")
        assert self.judge(request).status == PushStatus.REFUSED

    def test_non_base_tip_still_refuses_profile_changes(self):
        original = self.ls_tree.return_value
        changed = [TreeEntry(mode="100644", kind="blob", oid="changed", path=".task-loop.json")]
        self.ls_tree.side_effect = lambda repo, rev, path: original if rev == "policy-tree" else changed
        decision = self.judge(self.request("task/x", remote="refs/heads/task/x"))
        assert decision.status == PushStatus.REFUSED
        assert decision.reasons[0].startswith("profile_changed: refs/heads/task/x ")

    def test_mixed_push_checks_every_profiles_policy_before_receipts(self):
        original = self.ls_tree.return_value
        changed = [TreeEntry(mode="100644", kind="blob", oid="changed", path=".task-loop.json")]
        self.ls_tree.side_effect = lambda repo, rev, path: changed if rev == "task-tree" else original
        request = self.request("head") + self.request("task/x", remote="refs/heads/task/x")
        with mock.patch("tlgate.authorization.results") as evidence:
            decision = self.judge(request)
        assert decision.status == PushStatus.REFUSED
        assert decision.reasons[0].startswith("profile_changed: refs/heads/task/x ")
        evidence.assert_not_called()

    def test_a_miss_refuses_naming_the_step_and_never_runs_the_gate(self):
        decision = self.judge()
        assert decision.status == PushStatus.REFUSED
        assert decision.reasons == ("refs/heads/head (head) is not green for suite (no green run of tree tree under `true`); "
                                    "run `tl check` in its worktree, then push",)

    def test_a_receipt_written_by_tl_check_allows_the_push(self):
        assert self.judge().status == PushStatus.REFUSED
        self.stamp()
        assert self.judge().status == PushStatus.ALLOWED

    def test_a_dirty_head_with_no_receipt_is_refused_too(self):
        self.git.replies[("dirty",)] = True
        assert self.judge().status == PushStatus.REFUSED

    def test_entire_stack_is_judged_and_only_a_pushed_green_top_covers_a_lower_tip(self):
        self.stamp()
        self.git.replies[("is_ancestor",)] = True
        assert self.judge(self.request("low", "head")).status == PushStatus.ALLOWED
        assert self.judge(self.request("low")).status == PushStatus.REFUSED

    def test_a_push_to_the_base_branch_must_fast_forward_it(self):
        self.stamp(base="old-base")
        rewind = self.request("head", remote="refs/heads/main", old="old-base")
        decision = self.judge(rewind)
        assert decision.status == PushStatus.REFUSED
        assert decision.reasons == ("refs/heads/head (head) rewinds refs/heads/main: old-base is not an ancestor of head; "
                                    "only a fast-forward may reach the base branch",)
        self.git.replies[("is_ancestor", "old-base")] = True
        assert self.judge(rewind).status == PushStatus.ALLOWED

    def test_a_feature_branch_may_be_rewritten_with_only_the_profile_check(self):
        for remote in ("refs/heads/task/x", "refs/heads/topic"):
            with self.subTest(remote=remote), mock.patch("tlgate.authorization.results") as evidence:
                decision = self.judge(self.request("head", remote=remote, old="elsewhere"))
                assert decision.status == PushStatus.ALLOWED
                evidence.assert_not_called()

    def test_moving_the_base_branch_uses_the_receivers_old_base(self):
        self.git.replies[("is_ancestor", "old-base")] = True
        self.stamp(base="old-base")
        assert self.judge(self.request("head", remote="refs/heads/main", old="old-base")).status == PushStatus.ALLOWED

    def test_config_drift_names_the_first_differing_key_field(self):
        old = json.dumps({"engine": {"checks": [
            {"id": "suite", "argv": ["true"], "run": "gate", "when": ["src/**"]}]}})
        self.stamp(profile=old)
        decision = self.judge()
        assert decision.status == PushStatus.REFUSED
        assert re.search(r"^refs/heads/head \(head\) is not green for suite \(config differs "
                         r"\(expected [0-9a-f]{12} found [0-9a-f]{12}\)\); "
                         r"run `tl check` in its worktree, then push$", decision.reasons[0])

    def test_moved_base_reports_no_receipt_on_the_judged_base(self):
        self.stamp(base="old-base")
        decision = self.judge()
        assert decision.status == PushStatus.REFUSED
        assert decision.reasons == (
            "refs/heads/head (head) is not green for suite (no green run of tree tree under `true`); "
            "run `tl check` in its worktree, then push",)

    def test_unreadable_or_undecodable_policy_profile_is_unavailable(self):
        for text in ("{", "null", "[]", '{"engine": {"checks": false}}'):
            self.tip_profile = text
            with self.subTest(text=text):
                assert self.judge().status == PushStatus.UNAVAILABLE
        self.show.side_effect = GitReadFailure("profile unreadable")
        assert self.judge().status == PushStatus.UNAVAILABLE

    def test_missing_profile_and_no_gate_are_allowed_but_malformed_push_input_is_not(self):
        self.ls_tree.return_value = []
        assert self.judge().status == PushStatus.ALLOWED
        self.show.assert_not_called()
        self.ls_tree.return_value = [TreeEntry(mode="100644", kind="blob", oid="profile", path=".task-loop.json")]
        self.tip_profile = "{}"
        assert self.judge().status == PushStatus.ALLOWED
        assert self.judge("truncated\n").status == PushStatus.UNAVAILABLE

    def test_git_failures_are_unavailable(self):
        with mock.patch.object(self.git, "rev_parse", side_effect=GitReadFailure("unknown")):
            assert self.judge().status == PushStatus.UNAVAILABLE

    def test_a_green_tip_that_adds_a_credential_is_refused_naming_the_kind(self):
        self.stamp()
        self.git.replies[("diff",)] = "+++ b/f\n+" + "-----BEGIN " + "RSA PRIVATE KEY-----\n"
        decision = self.judge()
        assert decision.status == PushStatus.REFUSED
        assert "private key" in decision.reasons[0]

    def test_a_task_branch_push_is_not_scanned(self):
        self.git.replies[("diff",)] = "+AKIA" + "ABCDEFGHIJKLMNOP\n"
        assert self.judge(self.request("head", remote="refs/heads/task/x")).status == PushStatus.ALLOWED

    def delete(self, remote):
        return f"(delete) {'0' * 40} refs/heads/{remote} {'a' * 40}\n"

    def test_deleting_a_task_branch_needs_no_gate_evidence(self):
        for remote in ("task/x", "wip/x", "topic"):
            assert self.judge(self.delete(remote)).status == PushStatus.ALLOWED, remote

    def test_deleting_the_base_branch_is_refused(self):
        decision = self.judge(self.delete("main"))
        assert decision.status == PushStatus.REFUSED
        assert "refs/heads/main" in decision.reasons[0]

    def test_a_deletion_cannot_hide_in_a_push_with_other_tips(self):
        decision = self.judge(self.request("head", remote="refs/heads/task/x") + self.delete("main"))
        assert decision.status == PushStatus.REFUSED

    def test_working_tree_profile_is_not_read_for_delivery(self):
        self.stamp()
        with mock.patch.object(Path, "read_text", side_effect=AssertionError("working-tree profile read")):
            assert self.judge().status == PushStatus.ALLOWED

    def test_a_missing_tip_tree_is_unavailable(self):
        self.git.replies[("rev_parse", "head^{tree}")] = ""
        decision = self.judge()
        assert decision.status == PushStatus.UNAVAILABLE
        assert "cannot name the tree" in decision.reasons[0]

    def test_each_tip_uses_the_base_policy_profile(self):
        self.show.side_effect = lambda repo, tree, path: self.tip_profile if tree == "policy-tree" else "{}"
        self.git.replies[("dirty",)] = True
        assert self.judge(self.request("head", "low")).status == PushStatus.REFUSED
        assert self.show.call_args_list == [mock.call(self.repo, "policy-tree", ".task-loop.json")] * 2

    def test_profile_changes_are_refused_before_evidence_or_checks(self):
        original = self.ls_tree.return_value
        changed = [TreeEntry(mode="100644", kind="blob", oid="changed", path=".task-loop.json")]
        for policy, tip in ((original, changed), (original, []), ([], changed)):
            with self.subTest(policy=policy, tip=tip):
                self.ls_tree.side_effect = lambda repo, rev, path, policy=policy, tip=tip: policy if rev == "policy-tree" else tip
                with mock.patch("tlgate.authorization.results") as evidence:
                    decision = self.judge()
                assert decision.status == PushStatus.REFUSED
                assert decision.reasons == (
                    "profile_changed: refs/heads/head changes .task-loop.json; only the owner may push a profile change "
                    "(git push --no-verify)",)
                evidence.assert_not_called()

    def test_profile_change_cannot_be_covered_by_a_green_descendant(self):
        original = self.ls_tree.return_value
        self.ls_tree.side_effect = lambda repo, rev, *paths, **kw: (
            [TreeEntry(mode="100644", kind="blob", oid="changed", path=".task-loop.json")] if rev == "lower" else original)
        self.stamp()
        self.git.replies[("is_ancestor",)] = True
        assert self.judge(self.request("low", "head")).status == PushStatus.REFUSED

    def test_unresolvable_policy_is_unavailable(self):
        self.git.replies[("merge_base",)] = ""
        assert self.judge().status == PushStatus.UNAVAILABLE

    def test_unresolvable_policy_tree_is_unavailable(self):
        self.git.replies[("rev_parse", "policy^{tree}")] = ""
        assert self.judge().status == PushStatus.UNAVAILABLE

    def test_default_base_target_is_used_instead_of_tip_configuration(self):
        self.git.replies[("symbolic_ref",)] = "refs/remotes/origin/trunk"
        self.git.replies[("rev_parse", "origin/trunk")] = "base"
        self.stamp()
        assert self.judge().status == PushStatus.ALLOWED
        assert self.git.ran("merge_base", "head", "origin/trunk")

    def test_configured_base_ref_is_delivery_even_from_a_task_branch(self):
        for base in ("origin/trunk", "trunk", "origin/release/stable", "release/stable"):
            with self.subTest(base=base):
                self.tip_profile = json.dumps({"engine": {"base": base, "checks": [
                    {"id": "suite", "argv": ["true"], "run": "gate"}]}})
                self.git.replies[("rev_parse", base)] = "base"
                remote = "refs/heads/" + base.removeprefix("origin/")
                assert self.judge(self.request("task/x", remote=remote)).status == PushStatus.REFUSED
                assert self.judge(self.request("task/x", remote="refs/heads/main")).status == PushStatus.ALLOWED

    def test_missing_profile_resolves_the_same_default_base_as_policy_commit(self):
        self.ls_tree.return_value = []
        self.git.replies[("symbolic_ref",)] = "refs/remotes/origin/trunk"
        self.git.replies[("rev_parse", "origin/trunk")] = "trunk-sha"
        with mock.patch("tlland.push_judge.PushJudge.is_green", return_value=True) as green:
            assert self.judge(self.request("head", remote="refs/heads/main")).status == PushStatus.ALLOWED
            green.assert_not_called()
            assert self.judge(self.request("head", remote="refs/heads/trunk")).status == PushStatus.ALLOWED
            green.assert_called_once()
        assert self.git.ran("merge_base", "head", "origin/trunk")

    def test_empty_base_gate_still_refuses_profile_changes(self):
        self.tip_profile = "{}"
        self.test_profile_changes_are_refused_before_evidence_or_checks()

    def test_empty_base_gate_allows_an_unchanged_profile(self):
        self.tip_profile = "{}"
        assert self.judge().status == PushStatus.ALLOWED

    def test_other_command_and_env_cannot_authorize_the_same_id(self):
        for change in ({"argv": ["false"]}, {"env": {"MODE": "other"}}):
            other = json.dumps({"engine": {"checks": [{"id": "suite", "argv": ["true"], "run": "gate", **change}]}})
            with self.subTest(change=change):
                self.stamp(profile=other)
                assert self.judge().status == PushStatus.REFUSED

    def test_planned_skip_requires_the_exact_producer(self):
        self.tip_profile = json.dumps({"engine": {"plan_cmd": ["new-plan"], "checks": [
            {"id": "suite", "argv": ["true"], "run": "gate", "when": ["src/**"]}]}})
        self.profile.write_text(self.tip_profile)
        old = json.loads(self.tip_profile)
        old["engine"]["plan_cmd"] = ["old-plan"]
        self.stamp(profile=json.dumps(old), planned=True)
        assert self.judge().status == PushStatus.REFUSED
        self.stamp(planned=True)
        assert self.judge().status == PushStatus.ALLOWED

    def test_every_gate_step_needs_evidence(self):
        self.stamp()
        profile = json.loads(self.tip_profile)
        profile["engine"]["checks"].append({"id": "other", "argv": ["true"], "run": "gate"})
        self.tip_profile = json.dumps(profile)
        self.profile.write_text(self.tip_profile)
        assert self.judge().status == PushStatus.REFUSED
