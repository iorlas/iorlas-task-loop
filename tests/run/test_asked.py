"""A worker answer's updates to the run's threads: the value, and its one transaction with the done-memo."""
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
import support.paths  # noqa: F401
from support.narrow import must

from taskloop.app.run import asked, done_memo
from taskloop.app.run.call import Call
from taskloop.contracts import wire
from taskloop.contracts.asked import Fallback, SessionUpdate, Updates
from taskloop.contracts.checkpoint import Checkpoint, RunState, WriterSession
from taskloop.contracts.delegate import DelegateResult
from taskloop.contracts.docrows import RowDocs
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunManifest
from taskloop.contracts.runrows import RunRows


def call(node="write", resume_key=True, writer_family=None):
    return Call(node, "worker", {}, "/repo", "full", "text", None, None, ("k", 1), resume_key, writer_family, None, "t")


@pytest.mark.parametrize(("res", "resume_key", "want"), [
    (DelegateResult(ref="r1"), True, Updates(SessionUpdate("r1", 4.0, ("h",)), None)),
    (DelegateResult(ref="r1"), False, Updates()),
    (DelegateResult(), True, Updates()),
    (DelegateResult(ref="r1", fallback=True, first_lane="grok"), True,
     Updates(SessionUpdate("r1", 4.0, ("h",)), Fallback(True, "grok"))),
    (DelegateResult(ref="r1", fallback=False, first_lane="grok"), True,
     Updates(SessionUpdate("r1", 4.0, ("h",)), Fallback(False, ""))),
])
def test_the_writers_thread_comes_from_the_answer(res, resume_key, want):
    assert asked.thread_updates(call(resume_key=resume_key), res, "held", 4.0, ["h"]) == want


def test_a_fallback_with_no_lane_named_keeps_the_lane_held():
    got = asked.thread_updates(call(), DelegateResult(ref="r", fallback=True), "held", None, [])
    assert got.fallback == Fallback(True, "held")


@pytest.mark.parametrize(("node", "family", "flag", "want"), [
    ("review", "claude", None, "same_family"),  # a read-only node routed to the writer's own family
    ("review", "codex", None, ""),
    ("review", "claude", "degraded", "degraded"),
    ("write", "claude", None, ""),
])
def test_the_flag_names_a_read_only_call_on_the_writers_family(node, family, flag, want):
    res = DelegateResult(family=family, flag=flag)
    assert asked.done_updates(call(node, writer_family="claude"), res, Updates()).flag == want


def test_only_the_plan_node_moves_the_planner_ref():
    assert asked.done_updates(call("plan"), DelegateResult(ref="p"), Updates()).planner_ref == "p"
    assert asked.done_updates(call("write"), DelegateResult(ref="p"), Updates()).planner_ref == ""


AmendWith = Callable[[Callable[[Checkpoint], Checkpoint], Callable[[sqlite3.Connection | None], None]], bool]


class Amender:
    def __init__(self, amend_with: AmendWith) -> None:
        self.amend_with = amend_with


class Engine:
    """What settle reads of the engine: RunState's thread fields, the run's folder and the checkpoint's writer."""

    def __init__(self, run_dir: Path, state: RunState, amend_with: AmendWith) -> None:
        self.run_dir, self.state = run_dir, state
        self.writer: WriterSession = state.writer
        self.writer_fallback, self.fallback_lane, self.planner_ref = state.writer_fallback, state.fallback_lane, state.planner_ref
        self.checkpoints = Amender(amend_with)


class Settled:
    """A run row, its checkpoint row, and an engine that holds the thread fields settle persists."""

    def __init__(self, folder):
        self.cfg = ConfigDir(folder)
        self.run_dir = self.cfg.run_dir("run-1")
        self.run_dir.mkdir(parents=True)
        RunRows(self.cfg).put(RunManifest(run="run-1", repo="/repo", bead="t-1", started=1.0))
        self.docs = RowDocs(self.cfg, Checkpoint, table="checkpoint", key_col="bead", body_col="body", revisioned=True)
        self.doc = self.docs.of("t-1")
        self.doc.write(Checkpoint(bead="t-1", run="run-1", t=1.0, step="write", stage=2, applied=["a"]))
        self.answer = self.run_dir / "answer.json"
        self.answer.write_text('{"x": 1}')
        self.state = RunState(writer=WriterSession(delegate="r2", ctx=9.0, seen=["h"]), writer_fallback=True, fallback_lane="grok",
                              planner_ref="p2")
        self.engine = Engine(self.run_dir, self.state, self.doc.modify_with)
        self.c = call()
        self.c.sha = "sha"

    def settle(self):
        asked.settle(self.engine, self.c, str(self.answer), None)

    def memo(self):
        return done_memo.recall(self.run_dir, self.c.key, "sha")

    def stored(self):
        return self.doc.get()


def test_the_memo_and_the_thread_fields_land_together_and_nothing_else_moves(workdir):
    s = Settled(workdir)
    s.settle()
    ck = must(s.stored())
    assert s.memo() == {"x": 1}
    assert (ck.state.writer.delegate, ck.state.writer.ctx, ck.state.writer_fallback, ck.state.fallback_lane, ck.state.planner_ref) == (
        "r2", 9.0, True, "grok", "p2")
    assert (ck.step, ck.stage, ck.applied, ck.ended, ck.closed) == ("write", 2, ["a"], None, False)


def test_a_failure_after_the_memo_row_leaves_neither(workdir):
    s = Settled(workdir)
    before = s.stored()
    boom = s.engine.checkpoints
    boom.amend_with = lambda fn, also: s.doc.modify_with(lambda ck: (_ for _ in ()).throw(RuntimeError("crash")), also)
    with pytest.raises(RuntimeError):
        s.settle()
    assert s.memo() is None
    assert s.stored() == before


def test_a_crash_after_settle_resumes_from_the_memo_without_asking_again(workdir):
    s = Settled(workdir)
    s.settle()
    # the process dies before consumed(): a new one reads the same factory.db
    again = Settled.__new__(Settled)
    again.cfg, again.run_dir, again.c = s.cfg, s.run_dir, s.c
    again.doc = RowDocs(s.cfg, Checkpoint, table="checkpoint", key_col="bead", body_col="body", revisioned=True).of("t-1")
    assert again.memo() == {"x": 1}
    stored = must(again.stored())
    assert stored.state.planner_ref == "p2"
    assert stored.state.writer.delegate == "r2"


def test_a_missing_checkpoint_keeps_the_memo_alone(workdir):
    s = Settled(workdir)
    s.doc.delete()
    s.settle()
    assert s.memo() == {"x": 1}
    assert s.stored() is None


def test_a_checkpoint_from_before_the_updates_still_loads(workdir):
    s = Settled(workdir)
    old = json.loads(must(s.docs.of("t-1").raw()))
    old["state"].pop("planner_ref", None)
    with s.docs.rows.transaction() as con:
        con.execute("UPDATE checkpoint SET body=? WHERE bead='t-1'", (json.dumps(old),))
    assert must(s.stored()).state.planner_ref == ""


def test_the_last_flag_is_not_a_checkpoint_field():
    assert "last_flag" not in wire.keys(RunState)
