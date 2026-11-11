"""The land's close (tl-8bh9.14.8 section 8, slice L4) over `land_bench`'s semantic tracker double: the push first, then the
close as `taskloop`; a rerun after a crash between them, or after a lost close record, goes straight to the close; a task
closed by hand is recorded `already_closed`; a refused close leaves the task open and claimed and the rerun closes it; a
closed land answers `already_landed` with no Git or tracker call; the no-change close; `--withdraw` never closes. Then
the real port (`tracker_client`) over beads_client's scripted runner: the read, the fenced close, and bd's answers."""

import json
from pathlib import Path

import pytest
from beads_client import Bd
from beads_client.testing import Script
from doubles import Command
from land_bench import LandBench, bench

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_types import AttemptKey
from taskloop.claim_lease import BD_TIMEOUT_S
from taskloop.land import Landed, LandResult
from taskloop.land_close import NOT_SYNCED
from taskloop.land_store import Close, LandStore
from taskloop.operations import Failed
from taskloop.tracker_client import CloseAnswer, Closed, tracker_claims


class Died(BaseException):
    """The `tl step land` process died (a crash, `kill -9`) right before the tracker's close."""


class LosingDelivery(LandStore):
    """The candidates' store whose first delivery record is lost (S already on origin)."""

    lost = 1

    def record_delivery(self, key: AttemptKey, remote_head: str, now: float) -> None:
        if self.lost:
            self.lost -= 1
            raise StoreUnavailable("the push's answer was lost")
        super().record_delivery(key, remote_head, now)


class Losing(LandStore):
    """The candidates' store whose next close record is lost (the close made in the tracker), or, with `other`, recorded by
    a concurrent land right before this one's."""

    lost = 1
    other = False

    def record_close(self, key: AttemptKey, close: Close, now: float) -> None:
        if self.other:
            self.other = False
            LandStore(self.connect).record_close(key, "closed", 7.0)
        elif self.lost:
            self.lost -= 1
            raise StoreUnavailable("the close's record was lost")
        super().record_close(key, close, now)


@pytest.fixture
def b(tmp_path: Path) -> LandBench:
    return bench(tmp_path)


def word(found: LandResult) -> tuple[str, str]:
    assert isinstance(found, Failed), found
    return found.kind, found.reason


def delivered_open(b: LandBench) -> str:
    """The candidate delivered and not closed, the task still in progress and claimed; returns S."""
    row = b.rows()[-1]
    assert row.delivery == "pushed" and row.close is None and (b.status, b.assignee) == ("in_progress", "taskloop")
    return row.commit


def test_the_land_pushes_then_closes_as_taskloop_and_records_the_close(b: LandBench) -> None:
    found = b.land()
    assert isinstance(found, Landed) and found.how == "pushed" and found.row.close == "closed" and found.row.closed_at == 10.0
    s = found.row.commit
    assert b.tracker == [("tl-1", s)]  # one close, made once S was on origin's main
    assert (b.status, b.reason) == ("closed", f"Landed {s} on main (task/tl-1 at {b.x})")
    assert NOT_SYNCED == "Tracker: closed locally, not synced (bd dolt push shares it)"


def test_a_crash_between_the_push_and_the_close_is_finished_by_the_rerun_without_git(b: LandBench) -> None:
    def died() -> None:
        b.on_close = lambda: None
        raise Died

    b.on_close = died
    with pytest.raises(Died):
        b.land()
    s = delivered_open(b)
    b.remote.offline = True  # the rerun neither fetches, reads origin nor pushes
    found = b.land()
    assert isinstance(found, Landed) and found.how == "delivered" and found.row.close == "closed"
    assert b.repo.pushes == 1 and b.status == "closed" and b.tracker == [("tl-1", s)] and b.execs() == []


def test_a_lost_close_record_is_recorded_already_closed_by_the_rerun(b: LandBench) -> None:
    b.lands = Losing(lambda: b.con, b.begin)
    found = b.land()
    assert word(found) == ("unavailable", "store") and isinstance(found, Failed) and "is on origin's main" in found.detail
    row = b.rows()[0]
    assert (row.delivery, row.close, b.status) == ("pushed", None, "closed")
    reason = b.reason
    again = b.land()
    assert isinstance(again, Landed) and again.how == "delivered" and again.row.close == "already_closed"
    assert b.reason == reason and len(b.tracker) == 2 and b.repo.pushes == 1  # the second close only read it closed


def test_a_close_recorded_by_a_concurrent_land_is_the_same_answer(b: LandBench) -> None:
    store = Losing(lambda: b.con, b.begin)
    store.other = True
    b.lands = store
    found = b.land()
    assert isinstance(found, Landed) and found.how == "pushed" and found.row.closed_at == 7.0


def test_a_claim_taken_during_the_push_leaves_the_task_open_until_closed_by_hand(b: LandBench) -> None:
    b.repo.after_ls = [None, lambda: setattr(b, "assignee", "someone")]  # after the delivery's read, before the push
    found = b.land()
    assert word(found) == ("refused", "claim_lost") and isinstance(found, Failed)
    assert "assigned to someone: close it by hand with `bd close tl-1 --force`" in found.detail
    s = b.rows()[0].commit
    assert b.origin_main() == s and b.rows()[0].close is None and b.status == "in_progress"
    assert word(b.land()) == ("refused", "claim_lost")  # the rerun goes straight to the close again
    b.status = "closed"  # the person closes it by hand
    again = b.land()
    assert isinstance(again, Landed) and again.how == "delivered" and again.row.close == "already_closed"
    assert b.repo.pushes == 1 and b.reason is None


@pytest.mark.parametrize(("answer", "expected"), [
    ("unavailable", ("unavailable", "tracker")), ("claim_lost", ("refused", "claim_lost")), ("missing", ("refused", "task")),
    ("blocked", ("refused", "blocked")),
])
def test_a_refused_close_leaves_the_task_open_and_claimed_and_the_rerun_closes_it(
    b: LandBench, answer: Closed, expected: tuple[str, str]
) -> None:
    b.closing = [CloseAnswer(answer)]
    assert word(b.land()) == expected
    delivered_open(b)
    found = b.land()
    assert isinstance(found, Landed) and found.how == "delivered" and found.row.close == "closed" and b.status == "closed"
    assert b.repo.pushes == 1 and len(b.tracker) == 2


def test_a_closed_land_is_already_landed_with_no_git_or_tracker_call(b: LandBench) -> None:
    first = b.land()
    assert isinstance(first, Landed)
    b.remote.offline = True
    b.closing = [CloseAnswer("unavailable")]
    found = b.land()
    assert isinstance(found, Landed) and found.how == "already_landed" and found.row == b.rows()[0]
    assert len(b.tracker) == 1 and b.repo.pushes == 1


def test_no_change_closes_with_the_disposition_s_reason(b: LandBench) -> None:
    main = b.advance({"src/x.py": "X = 1\n"}, "a hand land")
    found = b.land(no_change=True)
    assert isinstance(found, Landed) and found.how == "no_change" and found.row.close == "closed"
    assert b.reason == f"Already on main at {main}" and b.repo.pushes == 0 and b.tracker == [("tl-1", main)]


def test_a_closed_task_whose_candidate_is_on_origin_records_already_closed(b: LandBench) -> None:
    b.closing = [CloseAnswer("unavailable")]
    assert word(b.land()) == ("unavailable", "tracker")
    b.con.execute("UPDATE land_candidate SET delivery=NULL,delivered_at=NULL,remote_head=NULL")  # the delivery record lost too
    b.status = "closed"
    found = b.land()
    assert isinstance(found, Landed) and found.how == "already_pushed" and found.row.close == "already_closed"


def test_withdraw_of_a_delivered_unclosed_candidate_never_closes(b: LandBench) -> None:
    b.closing = [CloseAnswer("unavailable")]
    assert word(b.land()) == ("unavailable", "tracker")
    found = b.land("withdraw")
    assert isinstance(found, Landed) and found.how == "delivered" and found.row.close is None
    assert len(b.tracker) == 1 and b.status == "in_progress"


def test_withdraw_finding_the_candidate_on_origin_never_closes(b: LandBench) -> None:
    b.closing = [CloseAnswer("unavailable")]
    assert word(b.land()) == ("unavailable", "tracker")
    b.con.execute("UPDATE land_candidate SET delivery=NULL,delivered_at=NULL,remote_head=NULL")
    found = b.land("withdraw")
    assert isinstance(found, Landed) and found.how == "already_pushed" and found.row.close is None and len(b.tracker) == 1
    again = b.land()
    assert isinstance(again, Landed) and again.how == "delivered" and again.row.close == "closed"


SHOW = json.dumps([{"id": "tl-1", "title": "Widget", "status": "in_progress", "assignee": "taskloop"}])
REASON = "Landed abc on main (task/tl-1 at def)"


def show(status: str = "in_progress", assignee: str = "taskloop") -> str:
    return json.dumps([{"id": "tl-1", "title": "Widget", "status": status, "assignee": assignee}])


def test_the_port_closes_as_taskloop_fenced_on_the_assignee_and_never_unclaims(tmp_path: Path) -> None:
    script = Script().say(SHOW)
    assert tracker_claims(script).close(str(tmp_path), "tl-1", REASON) == CloseAnswer("closed")
    assert [argv[1:] for argv in script.calls] == [
        ["--actor", "taskloop", "show", "tl-1", "--json"],
        ["--actor", "taskloop", "update", "tl-1", "--if-assignee", "taskloop", "--assignee", "taskloop", "--json"],
        ["--actor", "taskloop", "close", "tl-1", "--reason", REASON, "--json"],
    ]


DELETED = '{"error": "resolving tl-1: no issue found matching \\"tl-1\\"", "schema_version": 1}'
# bd 1.3.1's refusals of a close (stderr, exit 1), measured in a scratch tracker on 2026-11-12.
CHILDREN = "cannot close tl-1: 1 open child issue(s); close children first or use --force to override"
BLOCKERS = "cannot close blocked issue: tl-1 is blocked by [tl-2] (use --force to override)"


@pytest.mark.parametrize(("replies", "expected", "calls"), [
    ([(show("closed"), "", 0)], "already_closed", 1),
    ([(show(assignee="someone"), "", 0)], "claim_lost", 1),
    ([("", "Error: Issue tl-1 not found", 1)], "missing", 1),
    ([("", "bd: no answer in 30.0s", 124)], "unavailable", 1),
    ([(SHOW, "", 0), ("", "", 13)], "claim_lost", 2),
    ([(SHOW, "", 0), (DELETED, "", 1)], "missing", 2),
    ([(SHOW, "", 0), ("", "", 0), ('{"error": "database is down"}', "", 1)], "unavailable", 3),
    ([(SHOW, "", 0), ("", "", 0), ("", CHILDREN, 1)], "blocked", 3),
    ([(SHOW, "", 0), ("", "", 0), ("", BLOCKERS, 1)], "blocked", 3),
], ids=["closed", "other_assignee", "not_found", "timeout", "fence_refused", "deleted", "close_failed", "children", "blockers"])
def test_the_port_maps_bd_s_answers(tmp_path: Path, replies: list[tuple[str, str, int]], expected: str, calls: int) -> None:
    script = Script()
    for out, err, code in replies:
        script.say(out, err, code)
    found = tracker_claims(script).close(str(tmp_path), "tl-1", REASON)
    assert found.word == expected and len(script.calls) == calls and all("unclaim" not in argv for argv in script.calls)
    assert found.assignee == ("someone" if expected == "claim_lost" and calls == 1 else None)
    assert expected != "blocked" or found.detail == replies[-1][1]


def test_the_port_s_bd_calls_are_capped_at_bd_timeout(tmp_path: Path) -> None:
    """A hung bd answers within BD_TIMEOUT_S per call (bd's runner then gives `timeout`: `unavailable tracker`)."""
    built: list[dict[str, object]] = []

    class Recorded(Bd):
        def __init__(self, actor: str, cwd: str | None = None, **options: object) -> None:
            built.append({"actor": actor, "cwd": cwd} | {key: value for key, value in options.items() if key != "run"})
            super().__init__(actor, cwd, run=Script().say("", "bd: no answer in 30.0s", 124))

    found = tracker_claims(Script(), client=Recorded).close(str(tmp_path / "x" / ".."), "tl-1", REASON)
    assert found == CloseAnswer("unavailable", detail="timeout")
    assert built == [{"actor": "taskloop", "cwd": str(tmp_path.resolve()), "timeout": BD_TIMEOUT_S}]


@pytest.mark.parametrize(("holder", "advice"), [
    ("", "it is unassigned (its claim lapsed): close it by hand with `bd close tl-1`;"),
    ("someone", "it is assigned to someone: close it by hand with `bd close tl-1 --force`"),
    (None, "another actor took it meanwhile: inspect it (`bd show tl-1`)"),
], ids=["unassigned", "another_actor", "fence"])
def test_a_lost_claim_names_the_close_by_hand_that_works(b: LandBench, holder: str | None, advice: str) -> None:
    b.closing = [CloseAnswer("claim_lost", holder)]
    found = b.land()
    assert word(found) == ("refused", "claim_lost") and isinstance(found, Failed) and advice in found.detail


def test_a_blocked_close_names_bd_s_words_and_is_no_plain_rerun(b: LandBench) -> None:
    b.closing = [CloseAnswer("blocked", detail=f"{BLOCKERS}\x1b[2J")]
    found = b.land()
    assert word(found) == ("refused", "blocked") and isinstance(found, Failed) and found.detail.isprintable()
    assert "is blocked by [tl-2]" in found.detail and "`bd close tl-1 --force`" in found.detail


@pytest.mark.parametrize("closed_by_hand", [True, False], ids=["closed_task", "no_change"])
def test_a_delivery_found_on_origin_carries_the_held_release_word(b: LandBench, closed_by_hand: bool) -> None:
    """Section 4 step 5's release ran first (held: the block rewrote the slot's `.git` pointer); a candidate found on
    origin by the closed task's read, or by `--no-change`'s, answers with that word as every other `Landed` does."""
    b.advance({"OTHER": "another task\n"})
    pointer = b.slot.path / ".git"
    b.environment.process.script = [Command(), Command(), Command(effect=lambda: b.files.contents.update({pointer: b"gitdir: /x\n"}))]
    b.lands = LosingDelivery(lambda: b.con, b.begin)
    assert word(b.land()) == ("unavailable", "store")
    assert b.rows()[0].pushable and b.rows()[0].holds_slot and b.origin_main() == b.rows()[0].commit
    b.status = "closed" if closed_by_hand else b.status
    found = b.land(no_change=not closed_by_hand)
    assert isinstance(found, Landed) and (found.how, found.release) == ("already_pushed", "held:slot_redirected")
    assert found.row.close == ("already_closed" if closed_by_hand else "closed")
