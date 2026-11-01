"""One application judge owns profile, evidence, stack coverage, and check retry policy."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fakegit import FakeGit

from taskloop.app.checks.cache import key_digest
from taskloop.app.land.push_judge import PushStatus, judge_push
from taskloop.contracts.checks import CheckResult, PassRecord
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.runkey import BaseSha, Digest, RunKey
from taskloop.contracts.slots import GitReadFailure
from taskloop.stores.memory import fake_stores


class PushJudge(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = tmp.name
        self.profile = Path(self.repo) / ".task-loop.json"
        self.profile.write_text(json.dumps({"engine": {"checks": [{"id": "suite", "argv": ["true"], "run": "gate"}]}}))
        self.git = FakeGit(rev_parse__HEAD="head", dirty=False, is_ancestor=False)
        self.git.replies.update({("rev_parse", "origin/main"): "base", ("rev_parse", "head^{tree}"): "tree",
                                 ("rev_parse", "low^{tree}"): "lower"})
        self.stores = fake_stores()
        self.check = mock.Mock(return_value=1)
        self.key = mock.patch("taskloop.app.land.push_judge.check_files.repo_key", return_value="repo")
        self.key.start()
        self.addCleanup(self.key.stop)

    def request(self, *tips, remote="refs/heads/topic", old="0" * 40):
        return "".join(f"refs/heads/{tip} {tip} {remote} {old}\n" for tip in tips)

    def judge(self, text=None):
        return judge_push(self.repo, self.request("head") if text is None else text, self.stores, self.git, self.check)

    def stamp(self, tree="tree", base="base"):
        key = RunKey(check=CheckId("suite"), cmd=Digest("c"), config=Digest("g"), toolchain=Digest("t"),
                     tree=TreeSha(tree), base=BaseSha(base), inputs=Digest("i"), selected=Digest(""), env=Digest("e"))
        result = CheckResult(id=key.check, cmd="true", group="gate", exit=0, status="passed")
        self.stores.results("repo", key.check).of(key_digest(key)).write(
            PassRecord(key=key, result=result, tree=key.tree, base=key.base))

    def test_valid_profile_uses_the_application_evidence_store(self):
        self.stamp()
        self.assertEqual(self.judge().status, PushStatus.ALLOWED)
        self.check.assert_not_called()

    def test_unknown_tip_is_refused_and_a_clean_head_can_run_checks(self):
        self.assertEqual(self.judge().status, PushStatus.REFUSED)
        self.check.assert_called_once_with()
        self.check.reset_mock()
        self.git.replies[("dirty",)] = True
        self.assertEqual(self.judge().status, PushStatus.REFUSED)
        self.check.assert_not_called()

    def test_successful_check_requires_evidence_and_unchanged_inputs(self):
        self.check.return_value = 0
        self.assertEqual(self.judge().status, PushStatus.REFUSED)

        def checked():
            self.stamp()
            return 0

        self.check.side_effect = checked
        self.assertEqual(self.judge().status, PushStatus.ALLOWED)

    def test_a_profile_change_during_checks_refuses(self):
        def checked():
            self.stamp()
            self.profile.write_text("{}")
            return 0

        self.check.side_effect = checked
        self.assertEqual(self.judge().status, PushStatus.UNAVAILABLE)

    def test_entire_stack_is_judged_and_only_a_pushed_green_top_covers_a_lower_tip(self):
        self.stamp()
        self.git.replies[("is_ancestor",)] = True
        self.assertEqual(self.judge(self.request("low", "head")).status, PushStatus.ALLOWED)
        self.assertEqual(self.judge(self.request("low")).status, PushStatus.REFUSED)

    def test_moving_the_base_branch_uses_the_receivers_old_base(self):
        self.stamp(base="old-base")
        self.assertEqual(self.judge(self.request("head", remote="refs/heads/main", old="old-base")).status, PushStatus.ALLOWED)

    def test_unreadable_or_undecodable_profile_is_unavailable_even_for_deletes(self):
        for text in ("{", "null", "[]", '{"engine": {"checks": false}}'):
            self.profile.write_text(text)
            with self.subTest(text=text):
                self.assertEqual(self.judge().status, PushStatus.UNAVAILABLE)
                self.assertEqual(self.judge(self.request("0" * 40)).status, PushStatus.UNAVAILABLE)
        with mock.patch.object(Path, "read_text", side_effect=PermissionError("unreadable")):
            self.assertEqual(self.judge().status, PushStatus.UNAVAILABLE)

    def test_missing_profile_and_no_gate_are_allowed_but_malformed_push_input_is_not(self):
        self.profile.unlink()
        self.assertEqual(self.judge().status, PushStatus.ALLOWED)
        self.profile.write_text("{}")
        self.assertEqual(self.judge().status, PushStatus.ALLOWED)
        self.assertEqual(self.judge("truncated\n").status, PushStatus.UNAVAILABLE)

    def test_git_and_check_failures_are_unavailable(self):
        with mock.patch.object(self.git, "rev_parse", side_effect=GitReadFailure("unknown")):
            self.assertEqual(self.judge().status, PushStatus.UNAVAILABLE)
        self.check.side_effect = OSError("runner unavailable")
        self.assertEqual(self.judge().status, PushStatus.UNAVAILABLE)

    def test_a_deleted_ref_needs_no_gate_evidence(self):
        self.assertEqual(self.judge(self.request("0" * 40)).status, PushStatus.ALLOWED)
        self.check.assert_not_called()
