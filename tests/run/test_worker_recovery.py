"""C07: recovery proves execution identity, including completed writer effects."""

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import support.paths  # noqa: F401
from support.narrow import must

from taskloop.app.workers import call, call_state, done_memo, worker_call
from tlkernel import factorydb, wire
from tlkernel.delegate import RunRequest
from tlkernel.delegateport import Answer
from tlkernel.locator import RunLocator
from tlkernel.paths import ConfigDir
from tlkernel.run import DoneEntry, RunManifest
from tlkernel.runrows import RunRows
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory


class Recovery(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = ConfigDir(Path(self.tmp.name))
        self.root = self.cfg.run_dir("run-1")
        self.root.mkdir(parents=True)
        self.rows = RunRows(self.cfg)
        self.rows.put(RunManifest(run="run-1", repo="/repo", bead="t-1", started=1.0))
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
        return call.Call(
            "write", "worker", schema or {"type": "object"}, cwd, "same prompt", "same prompt",
            None, None, ("write", 1, 0, 0), True, None, "write", "Write",
        )

    def saved(self, memo=False):
        c = self.call()
        self.worker.attach(c)
        st = call_state.begin(
            self.host.call_dir(), "run-1", "t-1", c.key, execution_id=c.sha,
        )
        raw = {"contract": 4, "stop": None, "data": {"summary": "done"}, "ref": "writer-1"}
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
                    assert c.finished is None
                    assert c.resume is None

    def test_nonsemantic_destinations_allow_completed_reuse(self):
        for memo in (False, True):
            with self.subTest(memo=memo):
                self.saved(memo)
                self.req = self.req.replace(live_file="other.log", title="other title", parent="other session")
                c = self.call()
                self.worker.attach(c)
                assert c.finished is not None

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
                    assert c.finished is None
                    self.host.log.note.assert_called_with(
                        "write: execution context/policy/schema/producer changed; execute again",
                    )
            self.req = base
            c = self.call(schema={"type": "array"})
            self.worker.attach(c)
            assert c.finished is None
            with mock.patch("taskloop.app.workers.worker_recovery.PRODUCER", "future"):
                c = self.call()
                self.worker.attach(c)
                assert c.finished is None

    def test_matching_interrupted_thread_resumes_but_legacy_identity_does_not(self):
        c = self.call()
        self.worker.attach(c)
        st = call_state.begin(self.host.call_dir(), "run-1", "t-1", c.key, execution_id=c.sha)
        st.note_ref("thread-1")
        c = self.call()
        self.worker.attach(c)
        assert c.resume == "thread-1"
        assert c.finished is None
        st.execution_id = ""
        st.save()
        c = self.call()
        self.worker.attach(c)
        assert c.resume is None
        assert c.finished is None

    def test_returned_writer_is_bound_to_its_resulting_tree(self):
        c = self.call()
        self.worker.attach(c)
        c.state = call_state.begin(self.host.call_dir(), "run-1", "t-1", c.key, execution_id=c.sha)
        self.host.git.tree_of.return_value = "written-tree"
        self.host.stats = {"nodes": 1}
        self.host.clock = SimpleNamespace(now=lambda: 1.0)
        raw = {"contract": 4, "stop": None, "data": {"summary": "done"}}
        ans = Answer(worker_call.delegate_wire.result_of(raw), raw)
        self.worker.note_result(c, ans, mock.Mock())
        again = self.call()
        self.worker.attach(again)
        assert again.finished is not None
        self.host.git.tree_of.return_value = "unrelated-tree"
        again = self.call()
        self.worker.attach(again)
        assert again.finished is None

    def test_consumed_writer_keeps_pre_call_identity_across_checks_and_wip_save(self):
        c = self.call()
        self.worker.attach(c)
        admitted = c.prepared
        before = c.sha
        c.state = call_state.begin(self.host.call_dir(), "run-1", "t-1", c.key, execution_id=c.sha)
        self.host.git.tree_of.return_value = "written-tree"
        self.host.stats = {"nodes": 1}
        self.host.clock = SimpleNamespace(now=lambda: 1.0)
        raw = {"contract": 4, "stop": None, "data": {"summary": "done"}}
        ans = Answer(worker_call.delegate_wire.result_of(raw), raw)
        self.worker.note_result(c, ans, mock.Mock())
        assert c.sha == before
        assert c.prepared is admitted
        assert c.state.execution_id != before
        c.state.consumed()
        done_memo.keep(self.root, c.key, c.sha, c.state.answer_file, must(c.prepared).snapshot)
        assert done_memo.recall(self.root, c.key, before) == raw

        self.host.git.tree_of.return_value = "checks-and-wip-tree"
        self.host.git.rev_parse.return_value = "wip-head"
        again = self.call()
        self.worker.attach(again)
        assert again.finished is not None
        assert must(again.finished).raw == raw

    def test_consumed_snapshot_still_rejects_changed_request_or_directory(self):
        c = self.call()
        self.worker.attach(c)
        st = call_state.begin(self.host.call_dir(), "run-1", "t-1", c.key, execution_id=c.sha)
        st.returned({"contract": 4, "stop": None, "data": {}}, self.root / "answer.json")
        st.consumed()
        done_memo.keep(self.root, c.key, c.sha, st.answer_file, must(c.prepared).snapshot)
        self.host.git.tree_of.return_value = "wip-tree"
        self.host.git.rev_parse.return_value = "wip-head"
        changed = self.call()
        changed.full = "changed prompt"
        for again in (changed, self.call("/other"), self.call(schema={"type": "array"})):
            self.worker.attach(again)
            assert again.finished is None
        self.req = self.req.replace(engine_only=["check"])
        again = self.call()
        self.worker.attach(again)
        assert again.finished is None
        self.req = self.req.replace(engine_only=[])
        with mock.patch("taskloop.app.workers.worker_recovery.PRODUCER", "future"):
            again = self.call()
            self.worker.attach(again)
            assert again.finished is None
        self.host.wt = "/other-worktree"
        again = self.call()
        self.worker.attach(again)
        assert again.finished is None

    def test_wip_save_rebinds_the_paused_thread_to_the_saved_tree_and_head(self):
        c = self.call()
        self.worker.attach(c)
        c.state = call_state.begin(self.host.call_dir(), "run-1", "t-1", c.key, execution_id=c.sha)
        c.state.note_ref("thread-1")
        before = c.sha
        self.host.git.tree_of.return_value = "wip-tree"
        self.host.git.rev_parse.return_value = "wip-head"
        self.worker.saved()
        assert c.sha != before
        st = call_state.load_for(self.host.call_dir(), "t-1", c.key)
        assert st is not None
        assert st.execution_id == c.sha
        again = self.call()
        self.worker.attach(again)
        assert again.resume == "thread-1"
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
            assert again.resume is None
        self.req = self.req.replace(engine_only=["check"])
        again = self.call()
        self.worker.attach(again)
        assert again.resume is None
        self.req = self.req.replace(engine_only=[])
        with mock.patch("taskloop.app.workers.worker_recovery.PRODUCER", "future"):
            again = self.call()
            self.worker.attach(again)
            assert again.resume is None

    def test_unknown_tree_cannot_prove_completed_effects(self):
        self.saved()
        self.host.git.tree_of.return_value = ""
        with pytest.raises(ValueError, match="execution identity"):
            self.worker.attach(self.call())

    def test_changing_worktree_with_identical_contents_requires_execution(self):
        self.saved()
        self.host.wt = "/other-worktree"
        c = self.call()
        self.worker.attach(c)
        assert c.finished is None

    def test_failed_completion_observation_keeps_output_without_proving_effects(self):
        c = self.call()
        self.worker.attach(c)
        c.state = call_state.begin(self.host.call_dir(), "run-1", "t-1", c.key, execution_id=c.sha)
        self.host.git.tree_of.return_value = ""
        self.host.stats = {"nodes": 1}
        self.host.clock = SimpleNamespace(now=lambda: 1.0)
        raw = {"contract": 4, "stop": None, "data": {"summary": "done"}}
        ans = Answer(worker_call.delegate_wire.result_of(raw), raw)
        with pytest.raises(ValueError):
            self.worker.note_result(c, ans, mock.Mock())
        st = call_state.load_for(self.host.call_dir(), "t-1", c.key)
        assert st is not None
        assert st.execution_id == ""
        assert st.phase == "returned"
        assert Path(st.answer_file).is_file()

    def test_legacy_memo_is_not_upgraded_from_its_prompt_hash(self):
        c = self.call()
        answer = self.root / "legacy.json"
        answer.write_text('{"contract": 4, "stop": null, "data": {}}')
        done_memo.keep(self.root, c.key, "old-prompt-sha", str(answer))
        self.worker.attach(c)
        assert c.finished is None

    def test_consumed_memo_upserts_step_with_current_attempt_and_rejects_changed_sha(self):
        answer = self.root / "answer.json"
        answer.write_text('{"answer": 1}')
        key = ("write", 1)
        with mock.patch.object(done_memo.time, "time", return_value=10):
            done_memo.keep(self.root, key, "sha-1", str(answer))
        assert done_memo.recall(self.root, key, "sha-1") == {"answer": 1}
        assert done_memo.recall(self.root, key, "changed") is None
        RunLocator(self.cfg).take_up("run-1", "/repo", "t-1", 15)
        with mock.patch.object(done_memo.time, "time", return_value=20):
            done_memo.keep(self.root, key, "sha-2", str(answer))
        with self.rows.transaction() as con:
            rows = con.execute("SELECT key,try,attempt,status,started,ended,input_digest,result,calls FROM step").fetchall()
        assert len(rows) == 1
        assert rows[0][:7] == ('["write", 1]', 1, 2, "done", 20, 20, "sha-2")
        assert wire.load(DoneEntry, rows[0][7]) == DoneEntry(sha="sha-2", file=str(answer))
        assert rows[0][8] == 0
        assert done_memo.recall(self.root, key, "sha-1") is None
        assert done_memo.recall(self.root, key, "sha-2") == {"answer": 1}

    def test_corrupt_step_and_database_raise_instead_of_reading_legacy_state(self):
        answer = self.root / "answer.json"
        answer.write_text('{}')
        done_memo.keep(self.root, (1,), "sha", str(answer))
        with self.rows.transaction() as con:
            con.execute("UPDATE step SET input_digest='different' WHERE run='run-1'")
        with pytest.raises(factorydb.DatabaseError):
            done_memo.recall(self.root, (1,), "sha")
        with self.rows.transaction() as con:
            con.execute("UPDATE step SET result='{' WHERE run='run-1'")
        with pytest.raises(factorydb.DatabaseError):
            done_memo.recall(self.root, (1,), "sha")
        self.cfg.factory_db().write_bytes(b"broken database")
        with pytest.raises(factorydb.DatabaseError):
            done_memo.recall(self.root, (1,), "sha")
        with pytest.raises(factorydb.DatabaseError):
            done_memo.keep(self.root, (1,), "sha", str(answer))


def test_the_memo_is_published_before_the_answer_is_marked_consumed(tmp_path):
    order = []
    state = mock.Mock()
    state.consumed.side_effect = lambda: order.append("consumed")
    c = mock.Mock(state=state, key=(1,), sha="x", node="plan", writer_family=None)
    host = SimpleNamespace(run_dir=tmp_path)
    worker = worker_call.WorkerCall(host, mock.Mock())
    keep = mock.patch.object(worker_call.asked, "settle", side_effect=lambda *a: order.append("keep"))
    nothing = mock.patch.object(worker_call.asked, "done_updates", return_value=worker_call.asked.Updates())
    with keep, nothing, pytest.raises(TypeError):  # the rest of end_call needs a whole host; only the order matters here
        worker.end_call(c, mock.Mock())
    assert order == ["keep", "consumed"]
