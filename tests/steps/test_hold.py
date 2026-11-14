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

from taskloop.attempt_reads import ReleaseRow
from taskloop.attempt_status import AttemptView
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, AttemptResult
from taskloop.check_status import ChecksView
from taskloop.check_store import CheckStore, ResultRow
from taskloop.evidence_files import EvidenceFiles
from taskloop.hold import ROUND_CAUSES, HoldMove, HoldPorts, clear_holds, hold_task
from taskloop.hold_guide import pending_guide
from taskloop.hold_store import COMMENT_LEASE, HoldInsert, HoldRow, HoldStore, Uncleared
from taskloop.operations import Failed, Move, Round
from taskloop.slot_release import AlreadyReleased, NotReleased, Released, ReleaseResult
from taskloop.step_render import human
from taskloop.tracker_client import HoldAnswer, HoldWrite, LabelStep, TrackerHolds

NEEDS_OWNER = AttemptResult("collected", "needs_owner")
RETURNED = Released("s1", D, True, "unclaimed", True)


def attempt(con: sqlite3.Connection, attempt_id: str = "a", *, seq: int = 1, label: str | None = "auto") -> None:
    """tl-1's captured plan attempt at `seq` on slot s1 (X stored, agent pid 42 group 41), taken under `label`."""
    con.execute(
        """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
        input_path,input_digest,schema_version,model,effort,access_policy,deadline,phase,base_commit,end_commit,worker_pid,worker_pgid,
        worker_start,worker_boot,number,seq,slot_head,label) VALUES (?,?,1,'plan','beads','tasks','tl-1','/tracker','r','s1','i',
        'd',1,'m','e','{"harness":"codex","sandbox":"workspace-write"}',100,'captured',?,?,42,41,'st','boot',1,?,?,?)""",
        (attempt_id, attempt_id + "-token", D, X, seq, D, label))


@dataclass
class Tracker:
    """The tracker's hold writes as a semantic fake: each answer scripted, every call in `calls` (shared with the abandon)."""

    calls: list[str]
    labelled: LabelStep = "moved"
    assignee: str = "taskloop"  # the label step's read of a `moved` or `absent` task
    commented: HoldWrite = "done"
    cleared: HoldWrite = "done"
    texts: list[str] = field(default_factory=list)
    during_comment: list[object] = field(default_factory=list)

    def labels(self, root: str, task: str, label: str) -> HoldAnswer[LabelStep]:
        self.calls.append(f"labels {root} {task} {label}")
        detail = "lock" if self.labelled == "unavailable" else self.assignee if self.labelled in ("moved", "absent") else ""
        return HoldAnswer(self.labelled, detail)

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
    fresh: AttemptView | None = None

    def __post_init__(self) -> None:
        self.tracker = Tracker(self.calls)
        self.abandon = Abandon(self.calls)
        self.checks = ChecksAbandon(self.calls)

    def ports(self, view: AttemptView, reason: str | None = None) -> HoldPorts:
        """`fresh`, the task's status read now; None: the held view with its cause still standing (a stuck word, or the
        advance word of a round-passed refusal)."""
        standing = replace(view, next="advance" if reason in ROUND_CAUSES else "stuck:entry_lost")
        return HoldPorts(HoldStore(lambda: self.con), AttemptStore(lambda: self.con), self.tracker.holds(), self.abandon, self.checks,
                         lambda: self.now, EvidenceFiles(self.root), lambda _backlog, _task: self.fresh or standing)

    def hold(self, view: AttemptView | None = None, reason: str | None = None) -> HoldMove:
        return hold_task(self.ports(view or VIEW, reason), view or VIEW, reason)

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
    assert "task branch task/tl-1 is not published." in text and "removed `auto` and added `held` and returned its claim." in text
    assert "restore the approval label `auto`" in text and f"Evidence: {bench.root}/attempts/" in text


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
        assert "changed no label" in bench.tracker.texts[0] and "resolve its ownership with the current actor" in bench.tracker.texts[0]


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


def test_a_failed_comment_gives_its_lease_back_and_a_deleted_task_needs_none(bench: Bench) -> None:
    """A failed comment call (one capped try) frees the lease, so the next caller retries at once, inside what would have
    been the lease window, never `refused:leased`."""
    bench.tracker.commented = "unavailable"
    found = bench.hold()
    assert (found.missing, found.refusal) == ("comment", "unavailable:tracker")
    assert bench.row().commented_at is None and bench.row().commenting_at is None
    bench.now = 11.0
    assert (bench.hold().missing, bench.hold().refusal) == ("comment", "unavailable:tracker")
    assert bench.calls.count("comment tl-1") == 3
    bench.tracker.commented = "missing"
    assert bench.hold().word == "held" and bench.row().commented_at is not None


def test_a_kept_claim_whose_comment_failed_names_the_refusal_and_the_comment_s_failure(bench: Bench) -> None:
    bench.abandon.result, bench.tracker.commented = NotReleased("refused", "slot_dirty"), "unavailable"
    found = bench.hold()
    assert (found.missing, found.refusal, found.detail) == ("abandon", "held:slot_dirty", "unavailable:tracker")


def test_the_comment_quotes_the_agent_s_explanation_from_its_stored_answer(bench: Bench) -> None:
    """Read from A's stored execution, not from the view the caller has (a view without its result here)."""
    answer = {"disposition": "needs_owner", "plan_path": None, "paths": [], "message": None, "explanation": "Which database?\nPick one."}
    path = bench.root / "answer.json"
    path.write_text(json.dumps(answer))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    bench.con.execute("""INSERT INTO execution (attempt_id,dispatch_token,generation,rc,timed_out,work,stands,stdout_path,
        stdout_digest,stderr_path,stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,answer_kind,disposition,
        effect,session_state) VALUES ('a','a-token',1,0,0,1,1,'o','d','e','d','answer.json',?,'g','d','valid','needs_owner','none',
        'complete')""", (digest,))
    bench.hold(replace(VIEW, result=AttemptResult("pending", "")))
    assert "The agent explained:\n> Which database?\n> Pick one.\n" in bench.tracker.texts[0]


def test_a_checks_cause_holds_the_implement_attempt_and_names_its_failed_checks(checking: sqlite3.Connection, tmp_path: Path) -> None:
    """The swapped checks view: A is the implement attempt it follows; the abandon releases the checks attempt first; a
    check command still running keeps the claim, named with its checks slot."""
    checking.execute("UPDATE attempt SET label='auto'")
    checking.executemany("INSERT INTO check_result VALUES ('checks',1,?,?,'checks-token',1,?,?,?,?,?,?,1,?,?,?)", [
        (0, "check", "e" * 64, 60, None, None, None, None, 2, 0, "passed"),
        (1, "test", "e" * 64, 60, 5, 5, "st", "boot", 2, 1, "lingering"),
        (2, "lint", None, None, None, None, None, None, 2, None, "undefined")])
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
    assert [each.word for each in clear_holds(store, bench.tracker.holds(), lambda: 20.0, "tasks")] == ["cleared"]
    assert bench.calls[-1] == "clear tl-1" and bench.row().cleared_at == 20.0
    assert clear_holds(store, bench.tracker.holds(), lambda: 21.0, "tasks") == ()


def test_clear_of_a_task_held_again_leaves_held_to_the_new_hold(bench: Bench) -> None:
    bench.hold()
    attempt(bench.con, "b", seq=2)
    bench.hold(replace(VIEW, attempt_id="b"))
    calls = len(bench.calls)
    found = clear_holds(HoldStore(lambda: bench.con), bench.tracker.holds(), lambda: 20.0, "tasks")
    assert [(each.attempt_id, each.word) for each in found] == [("a", "cleared")] and len(bench.calls) == calls


def test_clear_of_an_unfinished_label_step_supersedes_it_and_removes_held(bench: Bench) -> None:
    HoldStore(lambda: bench.con).insert(HoldInsert("a", "a", "failed:needs_owner", 5.0))
    attempt(bench.con, "b", seq=2)
    assert [each.word for each in clear_holds(HoldStore(lambda: bench.con), bench.tracker.holds(), lambda: 20.0, "tasks")] == ["cleared"]
    assert (bench.row().labels, bench.calls) == ("superseded", ["clear tl-1"])


def test_clear_is_retried_after_a_tracker_failure_and_never_lists_holds_that_wrote_no_label(bench: Bench) -> None:
    bench.hold()
    attempt(bench.con, "b", seq=2)
    bench.tracker.cleared = "unavailable"
    store = HoldStore(lambda: bench.con)
    assert [each.word for each in clear_holds(store, bench.tracker.holds(), lambda: 20.0, "tasks")] == ["unavailable:tracker"]
    assert bench.row().cleared_at is None
    bench.tracker.cleared = "missing"
    assert [each.word for each in clear_holds(store, bench.tracker.holds(), lambda: 21.0, "tasks")] == ["cleared"]
    bench.con.execute("UPDATE task_hold SET cleared_at=NULL,labels='not_ours'")
    assert clear_holds(store, bench.tracker.holds(), lambda: 22.0, "tasks") == ()


def test_a_retried_comment_of_a_checks_cause_describes_the_checks_attempt_not_the_view_after_the_abandon(
    checking: sqlite3.Connection, tmp_path: Path
) -> None:
    """The first comment failed after the abandon finished; the next round's view is the implement attempt's (no checks
    view any more): the comment still names the checks attempt, its failed check and its evidence, with no explanation."""
    checking.execute("UPDATE attempt SET label='auto'")
    checking.execute("INSERT INTO check_result VALUES ('checks',1,0,'test','checks-token',1,?,60,NULL,NULL,NULL,NULL,1,2,1,'failed')",
                     ("e" * 64,))
    bench = Bench(checking, tmp_path)
    row = CheckStore(lambda: checking).of_attempt("implement")[0]
    failed = AttemptResult("collected", "failed:test:failed")
    view = AttemptView("tasks", "tl-1", "check", CHECKS.attempt_id, "s2", "concluded", "gone", failed, False, "hold", label="auto",
                       hold_due="failed:test:failed", checks=ChecksView(row, ()))
    bench.tracker.commented = "unavailable"
    assert bench.hold(view).missing == "comment"
    after = AttemptView("tasks", "tl-1", "implement", "implement", "s1", "captured", "gone", AttemptResult("collected", "verified"),
                        False, "hold", label="auto", release=ReleaseRow(D, 11.0, "unclaimed"))  # the hold's abandon is recorded
    bench.fresh = after
    bench.tracker.commented, bench.now = "done", 10.0 + COMMENT_LEASE + 1
    bench.abandon.result = AlreadyReleased("s1", "unclaimed", True)
    assert bench.hold(after).word == "held"
    text = bench.tracker.texts[-1]
    files = EvidenceFiles(tmp_path)
    assert text.startswith("taskloop hold: failed:test:failed\nStep check, attempt 1 (checks)")
    assert "Failed checks: test failed " in text and f"Evidence: {files.root / files.directory(CHECKS)}" in text
    assert "The agent explained" not in text


@pytest.mark.parametrize(("answer", "assignee", "said"), [
    ("not_ours", "", "(the claim is not the factory's)"), ("moved", "", "(the claim is not the factory's)"),
    ("absent", "", "(the claim is not the factory's)"), ("moved", "taskloop", "the next round returns the claim"),
], ids=["not_ours", "moved_unassigned", "absent_unassigned", "moved_ours"])
def test_a_kept_slot_promises_the_claim_only_when_the_label_step_read_it_as_the_factory_s(
    bench: Bench, answer: LabelStep, assignee: str, said: str
) -> None:
    bench.tracker.labelled, bench.tracker.assignee = answer, assignee
    bench.abandon.result = NotReleased("refused", "slot_dirty")
    bench.hold()
    text = bench.tracker.texts[0]
    assert said in text
    assert ("but still holds the claim" in text) == (assignee == "taskloop")
    assert ("keeps the attempt's slot" in text) == (assignee != "taskloop")


def test_a_kept_slot_after_a_label_step_of_an_earlier_round_does_not_assume_the_claim(bench: Bench) -> None:
    bench.abandon.result = NotReleased("unavailable", "store")
    bench.hold()  # labels done, the abandon transient: no comment
    bench.abandon.result = NotReleased("refused", "slot_dirty")
    bench.hold()
    assert "the next round frees the slot and returns the claim if it is still the factory's" in bench.tracker.texts[0]


def test_clear_waits_while_the_new_hold_s_label_step_is_unfinished_and_clears_once_it_wrote_no_label(bench: Bench) -> None:
    bench.hold()
    attempt(bench.con, "b", seq=2)
    store = HoldStore(lambda: bench.con)
    held = store.insert(HoldInsert("b", "b", "failed:needs_owner", 15.0))
    calls = len(bench.calls)
    found = clear_holds(store, bench.tracker.holds(), lambda: 20.0, "tasks")
    assert [(each.word, each.detail) for each in found] == [("pending:held_again", "b")] and len(bench.calls) == calls
    assert bench.row().cleared_at is None
    store.labelled("b", held.rev, "not_ours", 16.0)  # B wrote no label: A's `held` is still the factory's to remove
    assert [each.word for each in clear_holds(store, bench.tracker.holds(), lambda: 21.0, "tasks")] == ["cleared"]
    assert bench.calls[-1] == "clear tl-1"


class Racing(HoldStore):
    """The task is held again (labels moved) by another caller right after this round listed the uncleared holds."""

    def uncleared(self, backlog: str) -> tuple[Uncleared, ...]:
        found = super().uncleared(backlog)
        row = self.insert(HoldInsert("b", "b", "failed:needs_owner", 15.0))
        self.labelled("b", row.rev, "moved", 16.0)
        return found


def test_clear_reads_the_new_hold_again_right_before_the_tracker_call(bench: Bench) -> None:
    bench.hold()
    attempt(bench.con, "b", seq=2)
    calls = len(bench.calls)
    found = clear_holds(Racing(lambda: bench.con), bench.tracker.holds(), lambda: 20.0, "tasks")
    assert [each.word for each in found] == ["cleared"] and len(bench.calls) == calls  # `held` is B's now


def test_a_hold_whose_cause_is_gone_before_its_label_step_is_retired_with_no_tracker_call(bench: Bench) -> None:
    """The work was relaunched after the hold was recorded (the status read now: an entry runs, no hold cause): the hold
    never writes a label or abandons it; its row is deleted, so a later stop of A can be held afresh."""
    HoldStore(lambda: bench.con).insert(HoldInsert("a", "a", "stuck:expired_admitted", 5.0))
    bench.fresh = replace(VIEW, next="wait")
    found = bench.hold()
    assert (found.word, found.refusal, bench.calls) == ("refused", "refused:retired", [])
    assert HoldStore(lambda: bench.con).of_attempts(("a",)) == {}
    bench.fresh = None
    assert bench.hold().word == "held"  # held afresh once it stops again


def test_a_retired_hold_that_moved_the_labels_removes_held_first_and_waits_on_a_tracker_failure(bench: Bench) -> None:
    """The work went on since and passed (the view read now is at `land`, no hold cause): `held` is removed, then the
    row; the approval label is not added back (a claimed task advances without it)."""
    store = HoldStore(lambda: bench.con)
    row = store.insert(HoldInsert("a", "a", "failed:needs_owner", 5.0))
    store.labelled("a", row.rev, "moved", 6.0)
    bench.fresh = replace(VIEW, next="land")
    bench.tracker.cleared = "unavailable"
    assert (bench.hold().missing, bench.hold().refusal) == ("retire", "unavailable:tracker") and bench.row().labels == "moved"
    bench.tracker.cleared = "done"
    assert bench.hold().refusal == "refused:retired" and store.of_attempts(("a",)) == {}
    assert bench.calls == ["clear tl-1"] * 3  # never a label step, an abandon or a comment


@pytest.mark.parametrize(("fresh", "word"), [
    (replace(VIEW, next="stuck:entry_lost"), "held"),  # still a hold cause, maybe another word
    (replace(VIEW, next="stuck:hung"), "refused"),  # D7: not a cause
    (replace(VIEW, release=ReleaseRow(D, 9.0, "unclaiming"), next="start"), "held"),  # an abandon under way is finished
])
def test_the_cause_is_fenced_on_the_status_read_now(bench: Bench, fresh: AttemptView, word: str) -> None:
    bench.fresh = fresh
    assert bench.hold().word == word


def test_a_round_passed_cause_stands_while_the_view_still_waits_for_its_advance_or_publication(bench: Bench) -> None:
    HoldStore(lambda: bench.con).insert(HoldInsert("a", "a", "branch_moved", 5.0))
    bench.fresh = replace(VIEW, next="verify")
    assert bench.hold().refusal == "refused:retired"
    bench.fresh = replace(VIEW, next="publish")
    assert bench.hold(reason="branch_moved").word == "held"


def test_clear_lists_only_the_round_s_own_backlog(bench: Bench) -> None:
    bench.hold()
    attempt(bench.con, "b", seq=2)
    calls = len(bench.calls)
    assert clear_holds(HoldStore(lambda: bench.con), bench.tracker.holds(), lambda: 20.0, "other") == ()
    assert len(bench.calls) == calls and bench.row().cleared_at is None


def test_tl_step_next_prints_the_hold_guide_for_a_pending_hold_only() -> None:
    pending = Round("tasks", (Move("tl-1", "hold", "pending abandon held:slot_dirty", "a", step="plan"),))
    shown = human("next", pending, None)
    assert [line for line in shown if line.startswith("hold: ")] == [f"hold: {pending_guide('pending abandon held:slot_dirty')}"]
    transient = Round("tasks", (Move("tl-1", "hold", "pending abandon unavailable:slot_busy", "a", step="plan"),))
    assert "Another operation holds the slot lock" in "\n".join(human("next", transient, None))
    held = Round("tasks", (Move("tl-1", "hold", "held failed:needs_owner", "a", step="plan"),))
    assert not any(line.startswith("hold: ") for line in human("next", held, None))


def test_a_refusal_echoing_an_untrusted_id_prints_one_printable_line_per_detail_line() -> None:
    hostile = "tl\x1b[31m\u202e-1\nForged: yes" + "x" * 3000
    refused = Failed("refused", "absent", f"No attempt for {hostile} in backlog tasks")
    lines = human("show", refused, None)
    assert lines[0] == "show: refused:absent" and lines[2].startswith("Forged: yes") and len(lines) == 4  # the newline is a line break only
    assert all(each.isprintable() and len(each) <= 2000 for each in lines) and "tl [31m -1" in lines[1]
