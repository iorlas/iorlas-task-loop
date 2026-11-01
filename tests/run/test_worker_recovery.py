"""C07: recovery proves execution identity, including completed writer effects."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import support.paths  # noqa: F401
from support.narrow import must

from taskloop.app.run import done_memo, worker_call
from taskloop.contracts.delegate import RunRequest
from taskloop.stores import call_state


class Recovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.host = SimpleNamespace(
            wt="/repo", bead="t-1", run_id="run-1", run_dir=self.root,
            call_dir=lambda: self.root / "calls", log=mock.Mock(),
            git=mock.Mock(),
        )
        self.host.git.tree_of.return_value = "tree-before"
        self.host.git.rev_parse.return_value = "head-1"
        self.worker = worker_call.WorkerCall(self.host, mock.Mock())
        self.worker.limits = mock.Mock(return_value=(60, 30))
        self.req = RunRequest(role="worker", brief_path="", cwd="/repo", schema_path="")
        self.worker.request = mock.Mock(side_effect=lambda c, *args: self.req.replace(cwd=str(c.cwd)))

    def call(self, cwd="/repo", schema=None):
        return worker_call.Call(
            "write", "worker", schema or {"type": "object"}, cwd, "same prompt", "same prompt",
            None, None, ("write", 1, 0, 0), True, None, "write", "Write",
        )

    def saved(self, memo=False):
        c = self.call()
        self.worker.attach(c)
        st = call_state.begin(
            self.host.call_dir(), "run-1", "t-1", c.key, execution_id=c.sha,
        )
        raw = {"contract": 3, "stop": None, "data": {"summary": "done"}, "ref": "writer-1"}
        st.returned(raw, self.root / "answer.json")
        if memo:
            st.consumed()
            done_memo.keep(self.root, c.key, c.sha, st.answer_file)
        return st

    def test_completed_answers_require_the_same_cwd_tree_and_head(self):
        for memo in (False, True):
            for change in ("cwd", "tree", "head"):
                with self.subTest(memo=memo, change=change):
                    self.host.git.tree_of.return_value = "tree-before"
                    self.host.git.rev_parse.return_value = "head-1"
                    self.saved(memo)
                    c = self.call("/other" if change == "cwd" else "/repo")
                    if change == "tree":
                        self.host.git.tree_of.return_value = "tree-after"
                    if change == "head":
                        self.host.git.rev_parse.return_value = "head-2"
                    self.worker.attach(c)
                    self.assertIsNone(c.finished)
                    self.assertIsNone(c.resume)

    def test_nonsemantic_destinations_allow_completed_reuse(self):
        for memo in (False, True):
            with self.subTest(memo=memo):
                self.saved(memo)
                self.req = self.req.replace(live_file="other.log", title="other title", parent="other session")
                c = self.call()
                self.worker.attach(c)
                self.assertIsNotNone(c.finished)

    def test_policy_schema_and_producer_changes_require_an_explicit_decision(self):
        base = self.req
        for memo in (False, True):
            self.req = base
            self.saved(memo)
            for changes in ({"engine_only": ["check"]}, {"only_family": ["openai"]},
                            {"engine_only_advisory": True}, {"timeout_s": 9}):
                with self.subTest(memo=memo, changes=changes):
                    self.req = base.replace(**changes)
                    c = self.call()
                    self.worker.attach(c)
                    self.assertIsNone(c.finished)
                    self.host.log.note.assert_called_with(
                        "write: execution context/policy/schema/producer changed; execute again",
                    )
            self.req = base
            c = self.call(schema={"type": "array"})
            self.worker.attach(c)
            self.assertIsNone(c.finished)
            with mock.patch("taskloop.app.run.worker_recovery.PRODUCER", "future"):
                c = self.call()
                self.worker.attach(c)
                self.assertIsNone(c.finished)

    def test_matching_interrupted_thread_resumes_but_legacy_identity_does_not(self):
        c = self.call()
        self.worker.attach(c)
        st = call_state.begin(self.host.call_dir(), "run-1", "t-1", c.key, execution_id=c.sha)
        st.note_ref("thread-1")
        c = self.call()
        self.worker.attach(c)
        self.assertEqual(c.resume, "thread-1")
        self.assertIsNone(c.finished)
        st.execution_id = ""
        st.save()
        c = self.call()
        self.worker.attach(c)
        self.assertIsNone(c.resume)
        self.assertIsNone(c.finished)

    def test_returned_writer_is_bound_to_its_resulting_tree(self):
        c = self.call()
        self.worker.attach(c)
        c.state = call_state.begin(self.host.call_dir(), "run-1", "t-1", c.key, execution_id=c.sha)
        self.host.git.tree_of.return_value = "written-tree"
        self.host.stats = {"nodes": 1}
        self.host.clock = SimpleNamespace(now=lambda: 1.0)
        raw = {"contract": 3, "stop": None, "data": {"summary": "done"}}
        ans = worker_call.dg.Answer(worker_call.delegate_wire.result_of(raw), raw)
        self.worker.note_result(c, ans, mock.Mock())
        again = self.call()
        self.worker.attach(again)
        self.assertIsNotNone(again.finished)
        self.host.git.tree_of.return_value = "unrelated-tree"
        again = self.call()
        self.worker.attach(again)
        self.assertIsNone(again.finished)

    def test_consumed_writer_keeps_pre_call_identity_across_checks_and_wip_save(self):
        c = self.call()
        self.worker.attach(c)
        admitted = c.prepared
        before = c.sha
        c.state = call_state.begin(self.host.call_dir(), "run-1", "t-1", c.key, execution_id=c.sha)
        self.host.git.tree_of.return_value = "written-tree"
        self.host.stats = {"nodes": 1}
        self.host.clock = SimpleNamespace(now=lambda: 1.0)
        raw = {"contract": 3, "stop": None, "data": {"summary": "done"}}
        ans = worker_call.dg.Answer(worker_call.delegate_wire.result_of(raw), raw)
        self.worker.note_result(c, ans, mock.Mock())
        self.assertEqual(c.sha, before)
        self.assertIs(c.prepared, admitted)
        self.assertNotEqual(c.state.execution_id, before)
        c.state.consumed()
        done_memo.keep(self.root, c.key, c.sha, c.state.answer_file, must(c.prepared).snapshot)
        self.assertEqual(done_memo.recall(self.root, c.key, before), raw)

        self.host.git.tree_of.return_value = "checks-and-wip-tree"
        self.host.git.rev_parse.return_value = "wip-head"
        again = self.call()
        self.worker.attach(again)
        self.assertIsNotNone(again.finished)
        self.assertEqual(must(again.finished).raw, raw)

    def test_consumed_snapshot_still_rejects_changed_request_or_directory(self):
        c = self.call()
        self.worker.attach(c)
        st = call_state.begin(self.host.call_dir(), "run-1", "t-1", c.key, execution_id=c.sha)
        st.returned({"contract": 3, "stop": None, "data": {}}, self.root / "answer.json")
        st.consumed()
        done_memo.keep(self.root, c.key, c.sha, st.answer_file, must(c.prepared).snapshot)
        self.host.git.tree_of.return_value = "wip-tree"
        self.host.git.rev_parse.return_value = "wip-head"
        changed = self.call()
        changed.full = "changed prompt"
        for again in (changed, self.call("/other"), self.call(schema={"type": "array"})):
            self.worker.attach(again)
            self.assertIsNone(again.finished)
        self.req = self.req.replace(engine_only=["check"])
        again = self.call()
        self.worker.attach(again)
        self.assertIsNone(again.finished)
        self.req = self.req.replace(engine_only=[])
        with mock.patch("taskloop.app.run.worker_recovery.PRODUCER", "future"):
            again = self.call()
            self.worker.attach(again)
            self.assertIsNone(again.finished)
        self.host.wt = "/other-worktree"
        again = self.call()
        self.worker.attach(again)
        self.assertIsNone(again.finished)

    def test_wip_save_rebinds_the_paused_thread_to_the_saved_tree_and_head(self):
        c = self.call()
        self.worker.attach(c)
        c.state = call_state.begin(self.host.call_dir(), "run-1", "t-1", c.key, execution_id=c.sha)
        c.state.note_ref("thread-1")
        before = c.sha
        self.host.git.tree_of.return_value = "wip-tree"
        self.host.git.rev_parse.return_value = "wip-head"
        self.worker.saved()
        self.assertNotEqual(c.sha, before)
        st = call_state.load_for(self.host.call_dir(), "t-1", c.key)
        assert st is not None
        self.assertEqual(st.execution_id, c.sha)
        again = self.call()
        self.worker.attach(again)
        self.assertEqual(again.resume, "thread-1")
        self.host.log.note.assert_called_with("write: compatible interrupted thread thread-1: resuming")

    def test_wip_save_does_not_admit_changed_request_semantics(self):
        c = self.call()
        self.worker.attach(c)
        c.state = call_state.begin(self.host.call_dir(), "run-1", "t-1", c.key, execution_id=c.sha)
        c.state.note_ref("thread-1")
        self.host.git.tree_of.return_value = "wip-tree"
        self.host.git.rev_parse.return_value = "wip-head"
        self.worker.saved()
        changed = self.call()
        changed.full = "changed prompt"
        for again in (changed, self.call("/other"), self.call(schema={"type": "array"})):
            self.worker.attach(again)
            self.assertIsNone(again.resume)
        self.req = self.req.replace(engine_only=["check"])
        again = self.call()
        self.worker.attach(again)
        self.assertIsNone(again.resume)
        self.req = self.req.replace(engine_only=[])
        with mock.patch("taskloop.app.run.worker_recovery.PRODUCER", "future"):
            again = self.call()
            self.worker.attach(again)
            self.assertIsNone(again.resume)

    def test_unknown_tree_cannot_prove_completed_effects(self):
        self.saved()
        self.host.git.tree_of.return_value = ""
        with self.assertRaisesRegex(ValueError, "execution identity"):
            self.worker.attach(self.call())

    def test_changing_worktree_with_identical_contents_requires_execution(self):
        self.saved()
        self.host.wt = "/other-worktree"
        c = self.call()
        self.worker.attach(c)
        self.assertIsNone(c.finished)

    def test_failed_completion_observation_keeps_output_without_proving_effects(self):
        c = self.call()
        self.worker.attach(c)
        c.state = call_state.begin(self.host.call_dir(), "run-1", "t-1", c.key, execution_id=c.sha)
        self.host.git.tree_of.return_value = ""
        self.host.stats = {"nodes": 1}
        self.host.clock = SimpleNamespace(now=lambda: 1.0)
        raw = {"contract": 3, "stop": None, "data": {"summary": "done"}}
        ans = worker_call.dg.Answer(worker_call.delegate_wire.result_of(raw), raw)
        with self.assertRaises(ValueError):
            self.worker.note_result(c, ans, mock.Mock())
        st = call_state.load_for(self.host.call_dir(), "t-1", c.key)
        assert st is not None
        self.assertEqual(st.execution_id, "")
        self.assertEqual(st.phase, "returned")
        self.assertTrue(Path(st.answer_file).is_file())

    def test_legacy_memo_is_not_upgraded_from_its_prompt_hash(self):
        c = self.call()
        answer = self.root / "legacy.json"
        answer.write_text('{"contract": 3, "stop": null, "data": {}}')
        done_memo.keep(self.root, c.key, "old-prompt-sha", str(answer))
        self.worker.attach(c)
        self.assertIsNone(c.finished)
