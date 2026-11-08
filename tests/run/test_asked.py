"""A worker answer's updates to the run's threads: the value, and its one transaction with the done-memo."""
import json
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from taskloop.app.workers import asked, done_memo
from taskloop.app.workers.call import Call
from tlkernel import wire
from tlkernel.asked import SessionUpdate, Updates
from tlkernel.checkpoint import Checkpoint, RunState, WriterSession
from tlkernel.delegate import DelegateResult
from tlkernel.docrows import RowDocs
from tlkernel.paths import ConfigDir
from tlkernel.run import RunManifest
from tlkernel.runrows import RunRows
from tltestkit.narrow import must


def call(node="write", resume_key=True):
    return Call(node, "worker", {}, "/repo", "full", "text", None, ("k", 1),
                "writer" if resume_key else "k/1", None, "t")


@pytest.mark.parametrize(("res", "resume_key", "want"), [
    (DelegateResult(ref="r1"), True, Updates(SessionUpdate(("h",)))),
    (DelegateResult(ref="r1"), False, Updates()),
    (DelegateResult(), True, Updates()),
    (DelegateResult(ref="r1", fallback=True, first_account="grok"), True,
     Updates(SessionUpdate(("h",)))),
    (DelegateResult(ref="r1", fallback=False, first_account="grok"), True,
     Updates(SessionUpdate(("h",)))),
])
def test_the_writers_thread_comes_from_the_answer(res, resume_key, want):
    assert asked.thread_updates(call(resume_key=resume_key), res, ["h"]) == want


@pytest.mark.parametrize(("node", "family", "flag", "want"), [
    ("review", "claude", None, ""),  # a read-only node routed to the writer's own family
    ("review", "codex", None, ""),
    ("review", "codex", "same_family", "same_family"),
    ("review", "claude", "degraded", "degraded"),
    ("write", "claude", None, ""),
])
def test_the_flag_names_a_read_only_call_on_the_writers_family(node, family, flag, want):
    res = DelegateResult(family=family, flag=flag)
    assert asked.done_updates(call(node), res, Updates()).flag == want


def test_only_the_plan_node_moves_the_planner_ref():
    assert asked.done_updates(call("plan"), DelegateResult(ref="p"), Updates()).planner_ref == "p"
    assert asked.done_updates(call("write"), DelegateResult(ref="p"), Updates()).planner_ref == ""


AmendWith = Callable[[Callable[[Checkpoint], Checkpoint], Callable[[sqlite3.Connection | None], None]], bool]


class Amender:
    def __init__(self, amend_with: AmendWith) -> None:
        self.write = amend_with

    def amend_with(self, fn: Callable[[Checkpoint], Checkpoint], also: Callable[[sqlite3.Connection | None], None]) -> bool:
        return self.write(fn, also)


class Engine:
    """What settle reads of the engine: the run's folder and the checkpoint's writer."""

    def __init__(self, run_dir: Path, amend_with: AmendWith) -> None:
        self.run_dir = run_dir
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
        self.updates = Updates(SessionUpdate(("h",)), "p2", "same_family")
        self.engine = Engine(self.run_dir, self.doc.modify_with)
        self.c = call()
        self.c.sha = "sha"

    def settle(self):
        asked.settle(self.engine, self.c, self.updates, str(self.answer), None)

    def memo(self):
        return done_memo.recall(self.run_dir, self.c.key, "sha")

    def stored(self):
        return self.doc.get()


def test_the_memo_and_the_thread_fields_land_together_and_nothing_else_moves(workdir):
    s = Settled(workdir)
    s.settle()
    ck = must(s.stored())
    assert s.memo() == {"x": 1}
    assert (ck.state.writer.seen, ck.state.planner_ref) == (
        ["h"], "p2")
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
    assert stored.state.writer.seen == ["h"]


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


def test_updates_over_updates_keep_what_the_later_does_not_say():
    first = Updates(flag="degraded")
    later = Updates(session=SessionUpdate(()), planner_ref="p")
    assert asked.then(first, later) == Updates(later.session, "p", "degraded")


def test_with_updates_sets_only_what_is_named_and_the_rest_of_the_writer_stays():
    state = RunState(writer=WriterSession(last_stage=True), planner_ref="keep")
    got = asked.with_updates(state, Updates(session=SessionUpdate(("h",))))
    assert (got.writer.seen, got.writer.last_stage) == (["h"], True)
    assert got.planner_ref == "keep"


class Threaded:
    def __init__(self):
        self.writer = WriterSession()
        self.planner_ref, self.last_flag = "", "old"


def test_apply_assigns_the_thread_fields_and_the_flag():
    e = Threaded()
    asked.apply(e, Updates(SessionUpdate(("h",)), "p", "same_family"))
    assert (e.writer.seen, e.planner_ref, e.last_flag) == (
        ["h"], "p", "same_family")
    asked.apply(e, Updates())
    assert (e.planner_ref, e.last_flag) == ("p", "")  # an update that names nothing keeps the fields; the flag is per call


def test_worker_call_assigns_no_engine_field():
    source = (Path(__file__).resolve().parents[2] / "src/taskloop/app/workers/worker_call.py").read_text(encoding="utf-8")
    assert re.findall(r"\be\.(?:writer\b[.\w]*|writer_fallback|fallback_lane|planner_ref|last_flag)\s*=[^=]", source) == []
