"""The hold operation (tl-8bh9.14.9 sections 5, 7.3 and 12) over a real factory.db with a semantic tracker and a scripted
abandon: the order (record, labels, abandon, comment), every partial rerun, each 5.2 answer (closed and missing write
nothing), each section 12 refusal and whether it comments now or waits, the comment lease against a concurrent caller,
a lost race, a hand-started task, and `clear_holds` with its re-hold and `superseded` cases."""

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from doubles import CHECKS, D, X
from sqlite_store import begin_immediate
from stream_proc import OwnedProcess

from taskloop.attempt_status import AttemptView
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AnswerState, AttemptKey, AttemptResult, Evidence, ExecutionFacts, FileRef, StoredExecution
from taskloop.check_status import ChecksView
from taskloop.check_store import CheckStore, ResultRow
from taskloop.evidence_files import EvidenceFiles
from taskloop.hold import HoldMove, HoldPorts, clear_holds, hold_task
from taskloop.hold_store import COMMENT_LEASE, HoldInsert, HoldRow, HoldStore
from taskloop.slot_release import AlreadyReleased, NotReleased, Released, ReleaseResult
from taskloop.tracker_client import HoldAnswer, HoldWrite, LabelStep, TrackerHolds

KEY = AttemptKey("a", "a-token", 1)
NEEDS_OWNER = AttemptResult("collected", "needs_owner")
RETURNED = Released("s1", D, True, "unclaimed", True)


def attempt(con: sqlite3.Connection, attempt_id: str = "a", *, seq: int = 1, label: str | None = "auto") -> None:
    """tl-1's captured plan attempt at `seq` on slot s1 (X stored, agent pid 42 group 41), taken under `label`."""
    con.execute(
        """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
        input_path,input_digest,schema_version,model,effort,sandbox,deadline,phase,base_commit,end_commit,worker_pid,worker_pgid,
        worker_start,worker_boot,number,seq,slot_head,label) VALUES (?,?,1,'plan','beads','tasks','tl-1','/tracker','r','s1','i',
        'd',1,'m','e','workspace-write',100,'captured',?,?,42,41,'st','boot',1,?,?,?)""",
        (attempt_id, attempt_id + "-token", D, X, seq, D, label))


@dataclass
class Tracker:
    """The tracker's hold writes as a semantic fake: each answer scripted, every call in `calls` (shared with the abandon)."""

    calls: list[str]
    labelled: LabelStep = "moved"
    commented: HoldWrite = "done"
    cleared: HoldWrite = "done"
    texts: list[str] = field(default_factory=list)
    during_comment: list[object] = field(default_factory=list)

    def labels(self, root: str, task: str, label: str) -> HoldAnswer[LabelStep]:
        self.calls.append(f"labels {root} {task} {label}")
        return HoldAnswer(self.labelled, "lock" if self.labelled == "unavailable" else "")

    def comment(self, root: str, task: str, text: str) -> HoldAnswer[HoldWrite]:
        self.calls.append(f"comment {task}")
        self.texts.append(text)
        for each in self.during_comment:
            assert callable(each)
            each()
        return HoldAnswer(self.commented)

    def clear(self, root: str, task: str) -> HoldAnswer[HoldWrite]:
        self.calls.append(f"clear {task}")
        return HoldAnswer(self.cleared)

    def holds(self) -> TrackerHolds:
        return TrackerHolds(self.labels, self.comment, self.clear)


@dataclass
class Abandon:
    """The release ports as `tl step release --abandon` reaches them: the agent attempt's and the checks attempt's."""

    calls: list[str]
    result: ReleaseResult = RETURNED
    checks_result: ReleaseResult = RETURNED

    def release(self, key: AttemptKey, abandon: bool, me: object = None) -> ReleaseResult:
        self.calls.append(f"release {key.attempt_id} {abandon}")
        return self.result

    def release_candidate(self, key: AttemptKey, abandon: bool, me: object = None) -> ReleaseResult:
        raise AssertionError("no land candidate here")


@dataclass
class ChecksAbandon(Abandon):
    def release(self, key: AttemptKey, abandon: bool, me: object = None) -> ReleaseResult:
        self.calls.append(f"checks release {key.attempt_id} {abandon}")
        return self.checks_result


@dataclass
class Bench:
    con: sqlite3.Connection
    root: Path
    now: float = 10.0
    calls: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.tracker = Tracker(self.calls)
        self.abandon = Abandon(self.calls)
        self.checks = ChecksAbandon(self.calls)

    def ports(self) -> HoldPorts:
        return HoldPorts(HoldStore(lambda: self.con), AttemptStore(lambda: self.con), self.tracker.holds(), self.abandon, self.checks,
                         lambda: self.now, EvidenceFiles(self.root))

    def hold(self, view: AttemptView | None = None, reason: str | None = None) -> HoldMove:
        return hold_task(self.ports(), view or VIEW, reason)

    def row(self, attempt_id: str = "a") -> HoldRow:
        return HoldStore(lambda: self.con).of_attempts((attempt_id,))[attempt_id]


VIEW = AttemptView("tasks", "tl-1", "plan", "a", "s1", "captured", "gone", NEEDS_OWNER, False, "hold", label="auto",
                   hold_due="failed:needs_owner")


@pytest.fixture
def bench(factory: sqlite3.Connection, tmp_path: Path) -> Bench:
    with begin_immediate(factory):
        factory.execute("INSERT INTO slot (repo_id,name,path) VALUES ('r','s1','/slots/s1'),('r','s2','/slots/s2')")
        attempt(factory)
    return Bench(factory, tmp_path)


def test_a_hold_records_moves_the_labels_abandons_then_comments_once(bench: Bench) -> None:
    assert bench.hold() == HoldMove("tl-1", "a", "plan", "failed:needs_owner", "held")
    assert bench.calls == ["labels /tracker tl-1 auto", "release a True", "comment tl-1"]
    row = bench.row()
    assert (row.cause_id, row.reason, row.held_at, row.labels, row.commented_at) == ("a", "failed:needs_owner", 10.0, "moved", 10.0)
    text = bench.tracker.texts[0]
    assert text.startswith("taskloop hold: failed:needs_owner\nStep plan, attempt 1 (a)")
    assert "task/tl-1 at not published." in text and "removed `auto` and added `held` and returned its claim." in text
    assert "`bd label add tl-1 auto`" in text and f"Evidence: {bench.root}/attempts/" in text


def test_a_finished_hold_called_again_writes_nothing_more(bench: Bench) -> None:
    bench.hold()
    bench.abandon.result = AlreadyReleased("s1", "unclaimed", True)
    assert bench.hold().word == "held"
    assert bench.calls[3:] == ["release a True"]


def test_with_no_cause_and_no_hold_nothing_is_written(bench: Bench) -> None:
    found = bench.hold(replace(VIEW, hold_due=None))
    assert (found.word, found.refusal) == ("refused", "refused:no_cause")
    assert bench.calls == [] and HoldStore(lambda: bench.con).of_attempts(("a",)) == {}


def test_an_explicit_reason_is_the_round_s_cause(bench: Bench) -> None:
    """The advance's or the publication's refusal (`branch_moved`) is passed by the round; the comment says to fix it."""
    assert bench.hold(replace(VIEW, hold_due=None), "branch_moved").reason == "branch_moved"
    assert bench.row().reason == "branch_moved" and f"Restore task/tl-1 to contain {X}" in bench.tracker.texts[0]


def test_a_task_started_by_hand_is_never_held(bench: Bench) -> None:
    bench.con.execute("UPDATE attempt SET label=NULL")
    assert (bench.hold().word, bench.hold().refusal) == ("refused", "refused:unlabelled")
    assert bench.calls == []


def test_a_task_taken_again_meanwhile_is_a_lost_race_with_no_tracker_call(bench: Bench) -> None:
    attempt(bench.con, "b", seq=2)
    found = bench.hold()
    assert (found.word, found.refusal, bench.calls) == ("refused", "refused:changed", [])


def test_the_label_step_checks_a_is_still_current_right_before_it(bench: Bench) -> None:
    """Recorded, then the task taken again before the label step: no tracker call; the row stays for `clear_holds`."""
    HoldStore(lambda: bench.con).insert(HoldInsert("a", "a", "failed:needs_owner", 5.0))
    attempt(bench.con, "b", seq=2)
    found = bench.hold()
    assert (found.word, found.missing, found.refusal, bench.calls) == ("refused", "labels", "refused:changed", [])
    assert bench.row().labels is None


@pytest.mark.parametrize(("answer", "comments", "claim"), [
    ("moved", True, "unclaimed"), ("absent", True, "unclaimed"), ("not_ours", True, "not_held"),
    ("closed", False, "not_held"), ("missing", False, "not_held"),
])
def test_each_label_answer_and_whether_it_comments(bench: Bench, answer: LabelStep, comments: bool, claim: str) -> None:
    bench.tracker.labelled = answer
    bench.abandon.result = Released("s1", D, True, "not_held" if claim == "not_held" else "unclaimed", True)
    assert bench.hold().word == "held"
    assert ("comment tl-1" in bench.calls) == comments and bench.calls[:2] == ["labels /tracker tl-1 auto", "release a True"]
    row = bench.row()
    assert row.labels == answer and (row.commented_at is not None) == comments
    if answer == "not_ours":
        assert "changed no label" in bench.tracker.texts[0] and "`tl step start tl-1`" in bench.tracker.texts[0]


@pytest.mark.parametrize(("answer", "refusal", "detail"), [
    ("precondition", "unavailable:tracker", "precondition: the task's assignee changed after it was read"),
    ("unavailable", "unavailable:tracker", "lock"), ("bad_label", "refused:bad_label", "The stored label 'auto' cannot be passed to bd"),
])
def test_a_label_step_that_wrote_nothing_is_retried_and_nothing_follows_it(bench: Bench, answer: LabelStep, refusal: str,
                                                                           detail: str) -> None:
    bench.tracker.labelled = answer
    assert bench.hold() == HoldMove("tl-1", "a", "plan", "failed:needs_owner", "pending", "labels", refusal, detail)
    assert bench.calls == ["labels /tracker tl-1 auto"] and bench.row().labels is None
    bench.tracker.labelled = "moved"
    assert bench.hold().word == "held"


def test_a_crash_after_the_labels_resumes_at_the_abandon(bench: Bench) -> None:
    row = HoldStore(lambda: bench.con).insert(HoldInsert("a", "a", "failed:needs_owner", 5.0))
    HoldStore(lambda: bench.con).labelled("a", row.rev, "moved", 6.0)
    assert bench.hold().word == "held"
    assert bench.calls == ["release a True", "comment tl-1"]


def test_a_stale_snapshot_never_abandons_the_task_s_new_attempt(bench: Bench) -> None:
    """Labelled, then the task taken again (`tl step start` after the hold's abandon) before a round with an older
    snapshot reruns the hold: the abandon would act on the new attempt, so nothing is done."""
    row = HoldStore(lambda: bench.con).insert(HoldInsert("a", "a", "failed:needs_owner", 5.0))
    HoldStore(lambda: bench.con).labelled("a", row.rev, "moved", 6.0)
    attempt(bench.con, "b", seq=2)
    found = bench.hold()
    assert (found.word, found.missing, found.refusal, bench.calls) == ("refused", "abandon", "refused:changed", [])


def test_a_crash_after_the_abandon_resumes_at_the_comment(bench: Bench) -> None:
    bench.abandon.result = NotReleased("unavailable", "store")
    assert bench.hold().missing == "abandon" and bench.tracker.texts == []
    bench.abandon.result = AlreadyReleased("s1", "unclaimed", True)  # the abandon finished, the process died before the comment
    assert bench.hold().word == "held"
    assert bench.calls.count("labels /tracker tl-1 auto") == 1 and bench.calls.count("comment tl-1") == 1


KEPT = [
    (NotReleased("refused", "slot_dirty"), "held:slot_dirty", "slot /slots/s1 has files left by this attempt"),
    (NotReleased("refused", "slot_branch"), "held:slot_branch", "slot /slots/s1 is not where the factory left it (slot_branch)"),
    (NotReleased("refused", "slot_redirected"), "held:slot_redirected", "(slot_redirected)"),
    (NotReleased("refused", "slot_unborn"), "held:slot_unborn", "(slot_unborn)"),
    (NotReleased("unsettled", "worker_alive"), "unsettled:worker_alive", "still runs (pid 42, group 41)"),
    (NotReleased("unsettled", "setup_running"), "unsettled:setup_running", "still runs (pid 77, group 76)"),
    (NotReleased("refused", "landing"), "refused:landing", "may be on origin (landing)"),
    (NotReleased("refused", "landed"), "refused:landed", "may be on origin (landed)"),
]
TRANSIENT = [
    (NotReleased("unavailable", "slot_busy"), "unavailable:slot_busy"),
    (NotReleased("unsettled", "worker_unknown"), "unsettled:worker_unknown"),
    (NotReleased("unavailable", "setup_unknown"), "unavailable:setup_unknown"),
    (NotReleased("unavailable", "store"), "unavailable:store"), (NotReleased("unavailable", "git"), "unavailable:git"),
    (NotReleased("unavailable", "tracker"), "unavailable:tracker"), (NotReleased("refused", "entry_running"), "refused:entry_running"),
]


@pytest.mark.parametrize(("result", "refusal", "said"), KEPT, ids=[each[1] for each in KEPT])
def test_a_refusal_only_the_person_clears_comments_now_that_the_claim_is_still_held(
    bench: Bench, result: NotReleased, refusal: str, said: str
) -> None:
    bench.con.execute("""INSERT INTO setup_run (attempt_id,run,dispatch_token,generation,commit_sha,digest,pid,pgid,proc_start,boot,
                      started_at) VALUES ('a',1,'a-token',1,?,?,77,76,'st','boot',1)""", (D, "e" * 64))
    bench.abandon.result = result
    found = bench.hold()
    assert (found.word, found.missing, found.refusal) == ("pending", "abandon", refusal)
    text = bench.tracker.texts[0]
    assert said in text and "but still holds the claim" in text and "returned its claim" not in text
    bench.abandon.result = AlreadyReleased("s1", "unclaimed", True)  # the person cleared it; the next round's abandon finished
    assert bench.hold().word == "held" and bench.calls.count("comment tl-1") == 1


@pytest.mark.parametrize(("result", "refusal"), TRANSIENT, ids=[each[1] for each in TRANSIENT])
def test_a_transient_refusal_waits_for_the_next_round_without_a_comment(bench: Bench, result: NotReleased, refusal: str) -> None:
    bench.abandon.result = result
    assert bench.hold() == HoldMove("tl-1", "a", "plan", "failed:needs_owner", "pending", "abandon", refusal, result.detail)
    assert "comment tl-1" not in bench.calls and bench.row().commenting_at is None


def test_an_unclaim_still_to_retry_is_no_returned_claim(bench: Bench) -> None:
    bench.abandon.result = AlreadyReleased("s1", "unclaiming", True)
    found = bench.hold()
    assert (found.missing, found.refusal, bench.tracker.texts) == ("abandon", "release:unclaiming", [])


def test_two_callers_comment_once(bench: Bench) -> None:
    """A second caller (`tl step next` beside `tl step rounds`) arriving while the first posts finds the lease taken."""
    seen: list[HoldMove] = []
    bench.tracker.during_comment.append(lambda: seen.append(bench.hold()))
    assert bench.hold().word == "held"
    assert (seen[0].word, seen[0].missing, seen[0].refusal) == ("pending", "comment", "refused:leased")
    assert bench.calls.count("comment tl-1") == 1


def test_a_lease_older_than_the_lease_time_is_taken_again(bench: Bench) -> None:
    """A caller died after taking the lease (maybe after posting): within `COMMENT_LEASE` nobody posts; after it, one does."""
    row = HoldStore(lambda: bench.con).insert(HoldInsert("a", "a", "failed:needs_owner", 5.0))
    row = HoldStore(lambda: bench.con).labelled("a", row.rev, "moved", 6.0)
    assert HoldStore(lambda: bench.con).commenting("a", row.rev, 9.0) is not None
    assert (bench.hold().missing, bench.tracker.texts) == ("comment", [])
    bench.now = 9.0 + COMMENT_LEASE + 1
    assert bench.hold().word == "held" and len(bench.tracker.texts) == 1


def test_a_failed_comment_keeps_its_lease_and_a_deleted_task_needs_none(bench: Bench) -> None:
    bench.tracker.commented = "unavailable"
    found = bench.hold()
    assert (found.missing, found.refusal) == ("comment", "unavailable:tracker")
    assert bench.row().commented_at is None and bench.row().commenting_at == 10.0
    bench.tracker.commented, bench.now = "missing", 10.0 + COMMENT_LEASE + 1
    assert bench.hold().word == "held" and bench.row().commented_at is not None


def test_a_kept_claim_whose_comment_failed_names_the_refusal_and_the_comment_s_failure(bench: Bench) -> None:
    bench.abandon.result, bench.tracker.commented = NotReleased("refused", "slot_dirty"), "unavailable"
    found = bench.hold()
    assert (found.missing, found.refusal, found.detail) == ("abandon", "held:slot_dirty", "unavailable:tracker")


def test_the_comment_quotes_the_agent_s_explanation_from_its_stored_answer(bench: Bench) -> None:
    answer = {"disposition": "needs_owner", "plan_path": None, "paths": [], "message": None, "explanation": "Which database?\nPick one."}
    files = EvidenceFiles(bench.root)
    path = bench.root / "answer.json"
    path.write_text(json.dumps(answer))
    ref = FileRef("answer.json", hashlib.sha256(path.read_bytes()).hexdigest())
    facts = ExecutionFacts(0, False, None, None, True, True, True, None, None, None, None, None, None)
    stored = StoredExecution(KEY, facts, Evidence(ref, ref, ref, ref), AnswerState("valid", "needs_owner", "none"), "complete")
    assert files.read(ref)
    bench.hold(replace(VIEW, result=AttemptResult("collected", "needs_owner", stored)))
    assert "The agent explained:\n> Which database?\n> Pick one.\n" in bench.tracker.texts[0]


def test_a_checks_cause_holds_the_implement_attempt_and_names_its_failed_checks(checking: sqlite3.Connection, tmp_path: Path) -> None:
    """The swapped checks view: A is the implement attempt it follows; the abandon releases the checks attempt first; a
    check command still running keeps the claim, named with its checks slot."""
    checking.execute("UPDATE attempt SET label='auto'")
    checking.execute("""INSERT INTO check_result VALUES ('checks',1,1,'test','checks-token',1,?,60,5,5,'st','boot',1,2,1,'lingering')""",
                     ("e" * 64,))
    bench = Bench(checking, tmp_path)
    row = CheckStore(lambda: checking).of_attempt("implement")[0]
    results = (ResultRow(1, 0, "check", None, None, None, 1.0, 2.0, 0, "passed"),
               ResultRow(1, 1, "test", "e" * 64, 60, OwnedProcess(5, 5, "st", "boot"), 1.0, 2.0, 1, "lingering"),
               ResultRow(1, 2, "lint", None, None, None, 1.0, None, None, "undefined"))
    failed = AttemptResult("collected", "failed:test:lingering")
    view = AttemptView("tasks", "tl-1", "check", CHECKS.attempt_id, "s2", "concluded", "gone", failed, False, "hold", label="auto",
                       hold_due="failed:test:lingering", checks=ChecksView(row, results))
    bench.checks.checks_result = NotReleased("unsettled", "check_running")
    found = bench.hold(view)
    assert (found.attempt_id, found.missing, found.refusal) == ("implement", "abandon", "unsettled:check_running")
    assert bench.calls[:2] == ["labels /tracker tl-1 auto", "checks release checks True"]
    assert bench.row("implement").cause_id == CHECKS.attempt_id
    text = bench.tracker.texts[0]
    assert "Failed checks: test lingering " in text and "check-1-test.log" in text and "Failed checks: lint undefined" in text
    assert "Failed checks: check" not in text and "Step check, attempt 1 (checks)" in text
    assert "a process of this attempt still runs (pid 5, group 5)" in text


def test_clear_removes_held_once_the_task_was_taken_again(bench: Bench) -> None:
    bench.hold()
    attempt(bench.con, "b", seq=2)
    store = HoldStore(lambda: bench.con)
    assert [each.word for each in clear_holds(store, bench.tracker.holds(), lambda: 20.0)] == ["cleared"]
    assert bench.calls[-1] == "clear tl-1" and bench.row().cleared_at == 20.0
    assert clear_holds(store, bench.tracker.holds(), lambda: 21.0) == ()


def test_clear_of_a_task_held_again_leaves_held_to_the_new_hold(bench: Bench) -> None:
    bench.hold()
    attempt(bench.con, "b", seq=2)
    bench.hold(replace(VIEW, attempt_id="b"))
    calls = len(bench.calls)
    found = clear_holds(HoldStore(lambda: bench.con), bench.tracker.holds(), lambda: 20.0)
    assert [(each.attempt_id, each.word) for each in found] == [("a", "cleared")] and len(bench.calls) == calls


def test_clear_of_an_unfinished_label_step_supersedes_it_and_removes_held(bench: Bench) -> None:
    HoldStore(lambda: bench.con).insert(HoldInsert("a", "a", "failed:needs_owner", 5.0))
    attempt(bench.con, "b", seq=2)
    assert [each.word for each in clear_holds(HoldStore(lambda: bench.con), bench.tracker.holds(), lambda: 20.0)] == ["cleared"]
    assert (bench.row().labels, bench.calls) == ("superseded", ["clear tl-1"])


def test_clear_is_retried_after_a_tracker_failure_and_never_lists_holds_that_wrote_no_label(bench: Bench) -> None:
    bench.hold()
    attempt(bench.con, "b", seq=2)
    bench.tracker.cleared = "unavailable"
    store = HoldStore(lambda: bench.con)
    assert [each.word for each in clear_holds(store, bench.tracker.holds(), lambda: 20.0)] == ["unavailable:tracker"]
    assert bench.row().cleared_at is None
    bench.tracker.cleared = "missing"
    assert [each.word for each in clear_holds(store, bench.tracker.holds(), lambda: 21.0)] == ["cleared"]
    bench.con.execute("UPDATE task_hold SET cleared_at=NULL,labels='not_ours'")
    assert clear_holds(store, bench.tracker.holds(), lambda: 22.0) == ()
