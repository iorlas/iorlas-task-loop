"""A hold in the status (tl-8bh9.14.9 sections 3, 7.2 and 10): section 3's cause rule row by row (a hand-started task
never), the `hold` and `on_hold` words over every other word but `unknown`, the eligibility rule of a re-ingestion, the
hold looked up by the agent attempt (the swapped checks view's `after`), `tl step list --stuck`, the JSON's additive keys
and the `Hold` lines and guides of `tl step show` and `tl step list`."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import D, X
from sqlite_store import begin_immediate

from taskloop.answer_failures import AnswerFailureData, AnswerRule, encode
from taskloop.attempt_reads import ReleaseRow, StoreUnavailable
from taskloop.attempt_status import AttemptView, Listed, Shown, StatusPorts, agent_attempt, list_attempts, show_attempt, with_hold
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptResult, Unsettled
from taskloop.check_status import ChecksView
from taskloop.check_store import CheckStore
from taskloop.evidence_files import EvidenceFiles
from taskloop.hold_guide import HOLD, hold_guide
from taskloop.hold_status import cause, finished, reingests
from taskloop.hold_store import HoldInsert, HoldRow, HoldStore
from taskloop.operations import Failed
from taskloop.result_data import as_data
from taskloop.step_render import human

FAILED = AttemptResult("collected", "needs_owner")
VIEW = AttemptView("tasks", "tl-1", "plan", "a", "s1", "captured", "gone", FAILED, False, "done", label="auto")
RETURNED = ReleaseRow(D, 5.0, "unclaimed")
ROW = HoldRow("a", "a", "failed:needs_owner", 10.0, "moved", 11.0, 12.0, 13.0, None, 4, "tasks", "tl-1", "/tracker", "auto")


@pytest.mark.parametrize(("view", "expected"), [
    (VIEW, "failed:needs_owner"),
    (replace(VIEW, next="release", result=AttemptResult("collected", "run:timeout")), "failed:run:timeout"),
    (replace(VIEW, step="check", result=AttemptResult("collected", "failed:test:failed")), "failed:test:failed"),
    (replace(VIEW, result=AttemptResult("collected", "rejected:paths")), "failed:rejected:paths"),
    (replace(VIEW, result=AttemptResult("collected", "verified")), None),
    (replace(VIEW, result=AttemptResult("collected", "passed")), None),
    (replace(VIEW, result=AttemptResult("pending", "verification")), None),
    (replace(VIEW, next="repeats_exhausted", leftovers=("uncommitted", "a.py")), "repeats_exhausted:uncommitted"),
    *((replace(VIEW, next=word), word) for word in ("stuck:expired_admitted", "stuck:entry_lost", "stuck:uncollected",
                                                   "stuck:conflict", "stuck:setup_failed", "stuck:checks_refused")),
    *((replace(VIEW, next=word), None) for word in ("stuck:hung", "unknown", "wait", "start", "landed")),
    (replace(VIEW, label=None), None),  # started by hand
    (replace(VIEW, next="stuck:entry_lost", label=None), None),
    (replace(VIEW, next="release", release=ReleaseRow(D, 5.0, "unclaiming")), None),  # an abandon already started
    (replace(VIEW, release=ReleaseRow(D, 5.0, "kept", checks_abandoned=True)), None),
    (replace(VIEW, release=ReleaseRow(D, 5.0, "kept")), "failed:needs_owner"),  # released settled: still held
], ids=lambda each: each.next + ":" + each.result.reason + (":hand" if each.label is None else "") if isinstance(each, AttemptView) else "")
def test_the_cause_rule(view: AttemptView, expected: str | None) -> None:
    assert cause(view) == expected


@pytest.mark.parametrize(("row", "release", "done"), [
    (ROW, RETURNED, True), (ROW, ReleaseRow(D, 5.0, "not_held"), True), (ROW, ReleaseRow(D, 5.0, "unclaiming"), False),
    (ROW, ReleaseRow(D, 5.0, "kept"), False), (ROW, None, False), (replace(ROW, commented_at=None), RETURNED, False),
    (replace(ROW, labels=None, labelled_at=None), RETURNED, False),
    (replace(ROW, labels="closed", commenting_at=None, commented_at=None), ReleaseRow(D, 5.0, "not_held"), True),
    (replace(ROW, labels="missing", commenting_at=None, commented_at=None), ReleaseRow(D, 5.0, "not_held"), True),
    (replace(ROW, labels="not_ours", commented_at=None), ReleaseRow(D, 5.0, "not_held"), False),
])
def test_a_hold_is_finished_once_labelled_abandoned_and_commented(row: HoldRow, release: ReleaseRow | None, done: bool) -> None:
    assert finished(row, release) is done


@pytest.mark.parametrize(("view", "row", "word"), [
    (VIEW, None, "hold"),  # due
    (replace(VIEW, label=None), None, "done"),
    (replace(VIEW, release=RETURNED, next="start"), ROW, "on_hold"),
    (replace(VIEW, next="start"), ROW, "hold"),
    (replace(VIEW, next="stuck:hung"), ROW, "hold"),  # once recorded the row decides whatever the word
    (replace(VIEW, next="unknown"), ROW, "unknown"),
    (replace(VIEW, next="unknown"), None, "unknown"),
])
def test_the_hold_decides_the_word_after_every_rule_but_unknown(view: AttemptView, row: HoldRow | None, word: str) -> None:
    held = with_hold(view, row)
    assert (held.next, held.hold, held.hold_due) == (word, row, "failed:needs_owner" if word == "hold" and row is None else None)


@pytest.mark.parametrize(("word", "row", "label", "taken"), [
    ("on_hold", ROW, "auto", True), ("on_hold", replace(ROW, labels="absent"), "auto", True),
    ("on_hold", ROW, "auto2", False),
    *(("on_hold", replace(ROW, labels=each), "auto", False) for each in ("not_ours", "closed", "missing")),
    ("hold", ROW, "auto", False), ("start", None, "auto", False),
])
def test_only_a_hold_that_removed_the_round_s_own_label_is_taken_again(word: str, row: HoldRow | None, label: str, taken: bool) -> None:
    assert reingests(word, row, label) is taken


@pytest.mark.parametrize(("reason", "retry"), [
    ("land:conflict", False), ("merge:needs_owner", False), ("land:checks_failed", True),
    ("land:remote_rejected", True), ("land:branch_moved", True), ("land:claim_lost", True),
])
def test_terminal_decisions_resist_restored_approval_labels(reason: str, retry: bool) -> None:
    assert reingests("on_hold", replace(ROW, reason=reason), "auto") is retry


@pytest.mark.parametrize("pending", [True, False])
def test_terminal_land_guidance_preserves_work_without_restart_advice(pending: bool) -> None:
    row = replace(ROW, reason="land:conflict")
    view = replace(VIEW, next="hold" if pending else "on_hold", hold=None if pending else row,
                   hold_due=row.reason if pending else None)
    text = hold_guide(view)
    assert "retained task work" in text and "stays held" in text
    assert "do not restart" in text and "resolution limit" in text
    assert "To answer" not in text and "`bd" not in text and "`tl" not in text


def plan(con: sqlite3.Connection, *, label: str | None = "auto", released: str | None = None) -> None:
    """tl-1's admitted plan attempt `a` (no entry, deadline 100), maybe released with `released` as its claim."""
    with begin_immediate(con):
        con.execute(
            """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
            input_path,input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,label) VALUES
            ('a','a-token',1,'plan','beads','tasks','tl-1','/tracker','r','s1','i','d',1,'m','e','{"harness":"codex","sandbox":"workspace-write"}',100,1,1,?,?)""",
            (D, label))
        if released is not None:
            con.execute("INSERT INTO slot_release VALUES ('a','a-token',1,?,5,?)", (D, released))


def reads(con: sqlite3.Connection, now: float = 500) -> StatusPorts:
    return StatusPorts(AttemptStore(lambda: con), lambda _entry: "gone", lambda: now, lambda _key: None, lambda: "boot")


def recorded(con: sqlite3.Connection, attempt_id: str = "a", cause_id: str = "a", reason: str = "stuck:expired_admitted",
             comment: bool = True) -> HoldRow:
    store = HoldStore(lambda: con)
    row = store.insert(HoldInsert(attempt_id, cause_id, reason, 10.0))
    row = store.labelled(attempt_id, row.rev, "moved", 11.0)
    leased = store.commenting(attempt_id, row.rev, 12.0)
    assert leased is not None
    return store.commented(attempt_id, leased.rev, 13.0) if comment else leased


def listed(con: sqlite3.Connection, *, stuck: bool = False) -> tuple[AttemptView, ...]:
    found = list_attempts(reads(con), stuck=stuck)
    assert isinstance(found, Listed)
    return found.attempts


@pytest.mark.parametrize(("requested", "configured"), [("tasks", None), (None, "tasks"), ("tasks", "other")])
def test_show_reads_a_selected_backlog_without_enumerating_others(
    factory: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    requested: str | None, configured: str | None,
) -> None:
    plan(factory)
    ports = reads(factory)

    def unavailable() -> tuple[str, ...]:
        raise StoreUnavailable("Backlog enumeration unavailable")

    monkeypatch.setattr(ports.store, "backlogs", unavailable)
    shown = show_attempt(ports, tmp_path, requested, "tl-1", configured_backlog=configured)
    assert isinstance(shown, Shown) and shown.view.backlog == "tasks"
    failed = show_attempt(ports, tmp_path, None, "tl-1")
    assert isinstance(failed, Failed) and (failed.kind, failed.reason, failed.detail) == (
        "unavailable", "store", "Backlog enumeration unavailable")


def test_a_due_hold_is_listed_stuck_and_a_hand_started_one_keeps_its_word(factory: sqlite3.Connection) -> None:
    plan(factory)
    (view,) = listed(factory, stuck=True)
    assert (view.next, view.hold_due, view.hold, view.label) == ("hold", "stuck:expired_admitted", None, "auto")
    factory.execute("UPDATE attempt SET label=NULL")
    assert [each.next for each in listed(factory, stuck=True)] == ["stuck:expired_admitted"]


def test_a_finished_hold_is_on_hold_and_not_in_the_stuck_listing(factory: sqlite3.Connection) -> None:
    plan(factory)
    recorded(factory)
    assert [each.next for each in listed(factory, stuck=True)] == ["hold"]  # recorded, not abandoned yet
    factory.execute("INSERT INTO slot_release VALUES ('a','a-token',1,?,14,'unclaimed')", (D,))
    (view,) = listed(factory)
    assert (view.next, view.hold is not None and view.hold.labels) == ("on_hold", "moved")
    assert listed(factory, stuck=True) == ()


def test_a_task_taken_again_shows_its_new_attempt_without_the_old_hold(factory: sqlite3.Connection) -> None:
    plan(factory, released="unclaimed")
    recorded(factory)
    with begin_immediate(factory):
        factory.execute("""INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,
            repo_id,slot,input_path,input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,label) VALUES
            ('b','b-token',1,'plan','beads','tasks','tl-1','/tracker','r','s1','i','d',1,'m','e','{"harness":"codex","sandbox":"workspace-write"}',900,1,2,?,'auto')""",
            (D,))
    (view,) = listed(factory)
    assert (view.attempt_id, view.next, view.hold) == ("b", "start", None)


def test_the_swapped_checks_view_finds_the_hold_of_the_implement_attempt_it_follows(checking: sqlite3.Connection) -> None:
    """The view shows the checks attempt; the hold is the implement attempt's (`checks.row.after`), its cause the checks."""
    checking.execute("UPDATE attempt SET label='auto'")
    row = CheckStore(lambda: checking).of_attempt("implement")[0]
    view = AttemptView("tasks", "tl-1", "check", row.key.attempt_id, "s2", "concluded", "gone",
                       AttemptResult("collected", "failed:test:failed"), False, "done", label="auto", checks=ChecksView(row, ()))
    assert with_hold(view, None).hold_due == "failed:test:failed" and agent_attempt(view) == "implement"
    held = recorded(checking, "implement", row.key.attempt_id, "failed:test:failed", comment=False)
    assert HoldStore(lambda: checking).of_attempts((view.attempt_id,)) == {}  # never looked up by the checks attempt's id
    found = with_hold(view, HoldStore(lambda: checking).of_attempts(("implement",)).get("implement"))
    assert (found.next, found.attempt_id, found.hold) == ("hold", row.key.attempt_id, held)


def test_show_prints_the_hold_lines_and_the_answer_with_the_stored_label(factory: sqlite3.Connection, tmp_path: Path) -> None:
    plan(factory, released="unclaimed")
    recorded(factory, reason="branch_moved")
    shown = show_attempt(reads(factory), tmp_path, "tasks", "tl-1")
    assert isinstance(shown, Shown) and shown.view.next == "on_hold"
    text = "\n".join(human("show", shown, tmp_path / "factory.db"))
    assert "Hold: branch_moved at 1970-01-01 00:00:10 UTC (cause a)" in text
    assert "Hold tracker: `auto` removed, `held` added, commented" in text and "Hold claim: returned" in text
    assert "Next: on_hold\nHeld: the factory abandoned" in text and "`bd label add tl-1 auto`" in text
    assert "First restore task/tl-1 to contain the verified commit" in text and "--abandon` again" not in text
    data = as_data(shown)
    assert data["label"] == "auto" and data["hold_due"] is None
    assert data["hold"] == {"reason": "branch_moved", "cause": "a", "label": "auto", "held_at": 10.0, "labels": "moved",
                            "labelled_at": 11.0, "commented_at": 13.0, "cleared_at": None}


def test_the_on_hold_guide_gives_the_one_fix_of_the_cause(factory: sqlite3.Connection, tmp_path: Path) -> None:
    plan(factory, released="unclaimed")
    recorded(factory, reason="failed:run:timeout")
    shown = show_attempt(reads(factory), tmp_path, "tasks", "tl-1")
    assert isinstance(shown, Shown)
    text = "\n".join(human("show", shown, tmp_path / "factory.db"))
    assert "did not finish before its deadline" in text and "To fix it, raise `--minutes` for the next run, then add back" in text
    assert "`bd label add tl-1 auto`" in text
    assert "edit the task's description" not in text


def test_show_of_a_pending_hold_names_each_action_and_the_claim_kept(factory: sqlite3.Connection, tmp_path: Path) -> None:
    plan(factory)
    recorded(factory, comment=False)
    shown = show_attempt(reads(factory), tmp_path, "tasks", "tl-1")
    assert isinstance(shown, Shown)
    lines = human("show", shown, tmp_path / "factory.db")
    assert "Hold tracker: `auto` removed, `held` added, not commented yet" in lines
    assert "Hold claim: kept: the abandon has not finished" in lines
    assert lines[-1] == HOLD and "hold pending <step> <word>" in HOLD and "`tl " not in HOLD


def test_list_prints_the_hold_word_and_its_guide_once_and_json_says_due(factory: sqlite3.Connection) -> None:
    plan(factory)
    found = list_attempts(reads(factory), stuck=True)
    assert isinstance(found, Listed)
    lines = human("list", found, Path("/f/factory.db"))
    assert lines[1].endswith("\thold\tstuck:expired_admitted\t-") and lines[2] == f"hold: {HOLD}" and len(lines) == 3
    attempts = as_data(found)["attempts"]
    assert isinstance(attempts, list) and len(attempts) == 1 and isinstance(data := attempts[0], dict)
    assert (data["next"], data["hold_due"], data["hold"], data["label"]) == ("hold", "stuck:expired_admitted", None, "auto")


def test_an_unreadable_hold_table_is_unknown(factory: sqlite3.Connection) -> None:
    plan(factory)
    factory.execute("DROP TABLE task_hold")
    assert [each.next for each in listed(factory)] == ["unknown"]


def test_end_commit_and_label_are_read_with_the_attempt(factory: sqlite3.Connection) -> None:
    plan(factory)
    factory.execute("UPDATE attempt SET phase='captured',base_commit=?,end_commit=?", (D, X))
    row = AttemptStore(lambda: factory).attempts("tasks", "tl-1")[0]
    assert (row.label, row.end_commit) == ("auto", X)


def test_list_stuck_reads_the_leftovers_of_a_round_taken_attempt_so_a_due_repeats_exhausted_hold_shows(
    factory: sqlite3.Connection,
) -> None:
    """Attempt 3 of a step awaiting its verify whose slot has leftovers a repeat would hand back: `repeats_exhausted`, so
    a due hold; the leftovers are read for a labelled attempt only (a hand-started one never becomes a hold)."""
    with begin_immediate(factory):
        for number in (1, 2, 3):
            previous, why = (None, None) if number == 1 else (f"a{number - 1}", "uncommitted")
            factory.execute(
                """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
                input_path,input_digest,schema_version,model,effort,access_policy,deadline,phase,base_commit,number,seq,slot_head,
                previous_attempt_id,repeat_reason,label) VALUES (?,?,1,'plan','beads','tasks','tl-1','/tracker','r','s1','i','d',1,
                'm','e','{"harness":"codex","sandbox":"workspace-write"}',100,'captured',?,?,?,?,?,?,'auto')""",
                (f"a{number}", f"a{number}-token", D, number, number, D, previous, why))
        factory.execute("""INSERT INTO execution (attempt_id,dispatch_token,generation,rc,timed_out,work,stands,stdout_path,
            stdout_digest,stderr_path,stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,answer_kind,effect,
            session_state) VALUES ('a3','a3-token',1,0,0,1,1,'o','d','e','d','a','d','g','d','valid','commit','complete')""")
    probed: list[str] = []

    def leftovers(key: object) -> Unsettled:
        probed.append(str(key))
        return Unsettled("uncommitted", ("a.py",))

    ports = replace(reads(factory), leftovers=leftovers)
    found = list_attempts(ports, stuck=True)
    assert isinstance(found, Listed) and [(each.next, each.hold_due) for each in found.attempts] == [
        ("hold", "repeats_exhausted:uncommitted")]
    factory.execute("UPDATE attempt SET label=NULL")
    probed.clear()
    found = list_attempts(ports, stuck=True)
    assert isinstance(found, Listed) and found.attempts == () and probed == []


def test_a_moved_head_shows_the_refs_the_agent_made_but_stays_next_verify_not_a_repeat(factory: sqlite3.Connection) -> None:
    """`tl step show` prints `Unsettled:` from the attempt's leftovers: `head_moved` carries its listing there too, though
    it is no repeatable leftover (the next action stays `verify`)."""
    plan(factory)
    factory.execute("UPDATE attempt SET phase='captured',base_commit=?", (D,))
    factory.execute("""INSERT INTO execution (attempt_id,dispatch_token,generation,rc,timed_out,work,stands,stdout_path,
        stdout_digest,stderr_path,stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,answer_kind,effect,
        session_state) VALUES ('a','a-token',1,0,0,1,1,'o','d','e','d','a','d','g','d','valid','commit','complete')""")
    ports = replace(reads(factory), leftovers=lambda _key: Unsettled("head_moved", ("refs/tags/task/evil",)))
    found = list_attempts(ports)
    assert isinstance(found, Listed) and [(each.next, each.leftovers) for each in found.attempts] == [
        ("verify", ("head_moved", "refs/tags/task/evil"))]
    for reason in ("branch", "unborn"):  # no listing: the reason alone, which the `unsettled` guide's `branch` text answers
        found = list_attempts(replace(ports, leftovers=lambda _key, why=reason: Unsettled(why)))
        assert isinstance(found, Listed) and [(each.next, each.leftovers) for each in found.attempts] == [("verify", (reason,))]
    found = list_attempts(replace(ports, leftovers=lambda _key: Unsettled("dirty", ("a",))))  # not shown: only the three
    assert isinstance(found, Listed) and [each.leftovers for each in found.attempts] == [()]


def test_deadline_passed_of_a_captured_agent_attempt_is_whether_its_run_timed_out_not_whether_the_clock_passed(
    factory: sqlite3.Connection,
) -> None:
    plan(factory)
    factory.execute("UPDATE attempt SET phase='captured',base_commit=?", (D,))
    factory.execute("""INSERT INTO execution (attempt_id,dispatch_token,generation,rc,timed_out,work,stands,stdout_path,
        stdout_digest,stderr_path,stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,answer_kind,
        session_state,answer_failure)
        VALUES ('a','a-token',1,0,0,1,1,'o','d','e','d','a','d','g','d','json_invalid','complete',?)""",
        (encode(AnswerFailureData(rule=AnswerRule.JSON, explanation="Answer must be strict JSON")),))

    def seen(now: float) -> list[bool]:
        found = list_attempts(reads(factory, now))
        assert isinstance(found, Listed)
        return [each.deadline_passed for each in found.attempts]

    assert (seen(50), seen(500)) == ([False], [False])  # the run ended in time; the deadline (100) passing later changes nothing
    factory.execute("UPDATE execution SET timed_out=1,rc=124")
    assert (seen(50), seen(500)) == ([True], [True])


def test_show_of_a_task_held_for_failed_checks_names_each_failed_check_with_its_exit_and_log(checking: sqlite3.Connection,
                                                                                            tmp_path: Path) -> None:
    """After the hold's abandon the current attempt is the implement attempt, but the cause is the checks attempt: `show`
    prints that attempt's unpassed results from factory.db with their log paths (not the tracker comment, not a log)."""
    with begin_immediate(checking):
        checking.executemany(
            "INSERT INTO check_result VALUES ('checks',1,?,?,'checks-token',1,?,60,NULL,NULL,NULL,NULL,1,?,?,?)",
            [(0, "check", "1" * 64, 3, 1, "failed"), (1, "test", "2" * 64, 9, 0, "passed")])
        checking.execute("UPDATE slot_release SET claim='unclaimed' WHERE attempt_id='implement'")
        checking.execute("UPDATE attempt SET label='auto'")
    recorded(checking, "implement", "checks", "failed:check:failed")
    shown = show_attempt(reads(checking), tmp_path, "tasks", "tl-1")
    assert isinstance(shown, Shown) and shown.view.step == "implement" and shown.view.next == "on_hold"
    log = EvidenceFiles(tmp_path).check_path(CheckStore(lambda: checking).of_attempt("implement")[0].key, 1, "check")
    lines = human("show", shown, tmp_path / "factory.db")
    assert f"Failed check: check failed, exit 1, 2 s; log {log}" in lines
    assert not any(line.startswith("Failed check: test") for line in lines)
    failed = as_data(shown)["failed_checks"]
    assert isinstance(failed, dict) and [each["name"] for each in failed["results"]] == ["check"]
