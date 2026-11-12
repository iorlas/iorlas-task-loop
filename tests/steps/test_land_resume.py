"""A rerun does only what is missing (tl-8bh9.14.8 section 12, the close aside) over `land_bench`: a crash after the
validation before the push, a Ctrl-C during the block, a `kill -9` of the land with its check still running, a slot
release left held and retried first, concurrent lands (the insert fence, the slot's custody), the abandon racing the
land, a lost claim, and no free slot."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

import pytest
from doubles import CHECKS, Command
from git_porcelain import Transient
from land_bench import ME, RUN, LandBench, bench

from taskloop.check_store import CheckStore
from taskloop.land import Landed, LandResult
from taskloop.operations import Failed
from taskloop.slot_lock import lock_path

RESULTS = "SELECT block,name,conclusion FROM check_result ORDER BY block,position"


@pytest.fixture
def b(tmp_path: Path) -> LandBench:
    found = bench(tmp_path)
    found.advance({"OTHER": "another task\n"})  # every land here validates
    return found


def word(found: LandResult) -> tuple[str, str]:
    assert isinstance(found, Failed), found
    return found.kind, found.reason


def interrupt() -> None:
    raise KeyboardInterrupt


def interrupted(b: LandBench) -> None:
    """Ctrl-C while the second check runs: the registered command's result is left unfinished."""
    b.environment.process.script = [Command(), Command(), Command(effect=interrupt)]
    with pytest.raises(KeyboardInterrupt):
        b.land()
    row = b.rows()[0]
    assert row.pending and row.entry == ME and b.reservations() == [("s1", row.key.attempt_id)]
    assert b.con.execute(RESULTS).fetchall() == [(1, "check", "passed"), (1, "test", None)]


def test_a_crash_after_the_validation_before_the_push_pushes_on_the_rerun_without_checking_again(b: LandBench) -> None:
    b.repo.answer = Transient("connection reset")
    assert word(b.land()) == ("unavailable", "remote")
    assert b.rows()[0].pushable and b.rows()[0].released_at is not None
    found = b.land()
    assert isinstance(found, Landed) and found.how == "pushed" and b.execs() == RUN and len(b.rows()) == 1


def test_ctrl_c_during_the_block_is_repeated_whole_by_the_rerun_with_a_renewed_deadline(b: LandBench) -> None:
    interrupted(b)
    b.now = 1000.0  # past the first deadline: the person's rerun is new consent
    b.environment.process.script = []
    found = b.land()
    assert isinstance(found, Landed) and found.how == "pushed"
    assert b.con.execute(RESULTS).fetchall() == [(1, "check", "passed"), (1, "test", "interrupted"), (2, "check", "passed"),
                                                 (2, "test", "passed")]
    assert b.rows()[0].deadline == 1000.0 + 5 * 60 and b.rows()[0].validation == "passed"


def test_a_pending_candidate_is_not_resumed_without_minutes(b: LandBench) -> None:
    interrupted(b)
    pending = b.rows()[0]
    assert word(b.land(minutes=None)) == ("refused", "minutes")
    assert b.rows() == (pending,) and b.reservations() == [("s1", pending.key.attempt_id)]


def test_a_killed_land_s_running_check_holds_the_rerun_until_it_ended(b: LandBench) -> None:
    """`kill -9` of `tl step land`: its check may still run in its own session; nothing is reset or run until it is gone,
    and the next land process replaces the dead one's identity under the slot's custody."""
    interrupted(b)
    pid = b.con.execute("SELECT pid FROM check_result WHERE conclusion IS NULL").fetchone()[0]
    b.environment.seen[pid] = "alive"
    b.me = (5555, "next-start", "boot")
    assert word(b.land()) == ("unavailable", "checks:running")
    assert b.rows()[0].pending and b.slot_head() != b.d
    b.environment.seen[pid] = "gone"
    found = b.land()
    assert isinstance(found, Landed) and found.row.entry == b.me and found.row.validation == "passed"


def test_a_stored_land_process_still_running_is_never_replaced(b: LandBench) -> None:
    interrupted(b)
    b.me, b.seen[ME] = (5555, "next-start", "boot"), "matching"
    assert word(b.land()) == ("unavailable", "land_running") and b.rows()[0].entry == ME


def test_a_second_land_while_the_first_holds_the_slot_is_slot_busy(
    b: LandBench, occupy: Callable[[Path], AbstractContextManager[None]]
) -> None:
    interrupted(b)
    with occupy(lock_path(str(b.slot.path))):
        assert word(b.land()) == ("unavailable", "slot_busy")
    assert b.rows()[0].pending and b.con.execute(RESULTS).fetchall()[-1] == (1, "test", None)


@pytest.mark.parametrize("moved", [False, True], ids=["same_tree", "validated"])
def test_a_concurrent_land_winning_the_insert_refuses_the_other_landing(tmp_path: Path, moved: bool) -> None:
    """Another `tl step land` of the task runs to its end right before this one's insert: the insert's fence, or, when S
    validates, the slot taken at the winner's generation read again as the winner's candidate: `landing` either way."""
    b = bench(tmp_path)
    if moved:
        b.advance({"OTHER": "another task\n"})
    winner: list[LandResult] = []
    b.racing = lambda: winner.append(b.land())
    assert word(b.land()) == ("refused", "landing")
    assert isinstance(winner[0], Landed) and len(b.rows()) == 1
    found = b.land()
    assert isinstance(found, Landed) and found.how == "already_landed" and found.row.key == winner[0].row.key


def test_a_held_release_is_retried_first_by_every_rerun_and_the_land_still_pushes(b: LandBench) -> None:
    """The block's code rewrote the slot's `.git` pointer: the release refuses to park it; S is still pushed."""
    pointer = b.slot.path / ".git"
    b.environment.process.script = [Command(), Command(), Command(effect=lambda: b.files.contents.update({pointer: b"gitdir: /x\n"}))]
    found = b.land()
    assert isinstance(found, Landed) and found.how == "pushed" and found.row.holds_slot
    again = b.land()
    assert isinstance(again, Landed) and again.how == "already_landed" and again.release == "held:slot_redirected"
    del b.files.contents[pointer]
    done = b.land()
    assert isinstance(done, Landed) and (done.how, done.release) == ("already_landed", "released") and b.reservations() == []
    assert b.slot_head() == b.d and b.repo.pushes == 1


def test_an_abandoned_checks_attempt_is_not_landed(b: LandBench) -> None:
    assert CheckStore(lambda: b.con).abandon_released(CHECKS) == "abandoned"
    assert word(b.land()) == ("refused", "not_checked") and b.rows() == ()


def test_a_claim_lost_at_the_first_renewal_concludes_the_candidate_failed_and_releases_it(b: LandBench) -> None:
    b.beats = ["lost"]
    assert word(b.land()) == ("refused", "checks_failed")
    row = b.rows()[0]
    assert (row.validation, row.reason) == ("failed", "claim_lost") and b.execs() == [] and b.reservations() == []


def test_no_free_slot_is_unavailable_and_writes_nothing(b: LandBench) -> None:
    b.con.execute("INSERT INTO reservation (slot,repo_id,generation,attempt_id) SELECT 's1',repo_id,9,'other' FROM slot "
                  "WHERE name='s1'")
    assert word(b.land()) == ("unavailable", "no_free_slot") and b.rows() == ()


def test_no_change_while_a_candidate_validates_is_landing(b: LandBench) -> None:
    interrupted(b)
    b.advance({"src/x.py": "X = 1\n"}, "a hand land")
    assert word(b.land(no_change=True)) == ("refused", "landing") and b.rows()[0].pending and len(b.rows()) == 1


def test_a_held_pushable_candidate_onto_a_moved_main_says_its_slot_is_held(b: LandBench) -> None:
    """Its release was held and origin's `main` moved: the new candidate is refused for the held slot, `Next: release`."""
    pointer = b.slot.path / ".git"
    b.environment.process.script = [Command(), Command(), Command(effect=lambda: b.files.contents.update({pointer: b"gitdir: /x\n"}))]
    b.repo.answer = Transient("connection reset")
    assert word(b.land()) == ("unavailable", "remote") and b.rows()[0].holds_slot and b.rows()[0].pushable
    b.advance({"MORE": "a third task\n"})
    found = b.land()
    assert isinstance(found, Failed) and (found.kind, found.reason) == ("refused", "landing") and "still holds its slot" in found.detail
