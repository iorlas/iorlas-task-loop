"""The delivery rule (tl-8bh9.14.8 section 7) over `land_bench`: origin read as S (delivered, never pushed again), as O
(pushed), or elsewhere (fetched: containing S is delivered, else the candidate superseded `moved` and N+1 made once per
invocation, then `target_moved`); every push answer; the fetch failure; `--withdraw`; a closed task with a pushable
candidate; a delivery recorded by a concurrent land."""

from pathlib import Path

import pytest
from doubles import CHECKS
from git_porcelain import HookRejected, RemoteRejected, Transient
from land_bench import RUN, LandBench, bench

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_types import AttemptKey
from taskloop.check_store import CheckStore
from taskloop.land import Landed
from taskloop.land_push import Withdrawn
from taskloop.land_store import LandStore
from taskloop.operations import Failed


class Losing(LandStore):
    """The candidates' store whose next `lost` delivery records fail as a crash would lose them (S already pushed)."""

    lost = 1

    def record_delivery(self, key: AttemptKey, remote_head: str, now: float) -> None:
        if self.lost:
            self.lost -= 1
            raise StoreUnavailable("the push's answer was lost")
        super().record_delivery(key, remote_head, now)


@pytest.fixture
def b(tmp_path: Path) -> LandBench:
    return bench(tmp_path)


def word(found: Landed | Withdrawn | Failed) -> tuple[str, str]:
    assert isinstance(found, Failed), found
    return found.kind, found.reason


def pushable(b: LandBench) -> str:
    """A land whose push did not reach origin (`Transient`): its candidate is validated and pushable; returns S."""
    b.repo.answer = Transient("connection reset")
    assert word(b.land()) == ("unavailable", "remote")
    row = b.rows()[-1]
    assert row.pushable and b.origin_main() != row.commit
    return row.commit


def lost(b: LandBench) -> str:
    """A land whose push reached origin but whose answer was lost before the record; returns S."""
    b.lands = Losing(lambda: b.con, b.begin)
    assert word(b.land()) == ("unavailable", "store")
    s = b.rows()[-1].commit
    assert b.origin_main() == s and b.rows()[-1].pushable
    return s


def test_origin_at_s_is_delivered_without_a_second_push(b: LandBench) -> None:
    s = lost(b)
    found = b.land()
    assert isinstance(found, Landed) and found.how == "already_pushed" and found.row.remote_head == s
    assert b.repo.pushes == 1 and b.rows()[-1].delivery == "pushed" and len(b.rows()) == 1


def test_origin_built_on_s_is_delivered_with_its_later_tip(b: LandBench) -> None:
    s = lost(b)
    f = b.advance({"LATER": "another task on top\n"})
    found = b.land()
    assert isinstance(found, Landed) and found.how == "already_pushed" and found.row.remote_head == f
    assert b.repo.is_ancestor(s, f) and b.repo.pushes == 1


def test_a_pushable_candidate_onto_a_moved_main_is_superseded_and_candidate_two_lands(b: LandBench) -> None:
    s = pushable(b)
    o = b.advance({"OTHER": "another task\n"})
    found = b.land()
    assert isinstance(found, Landed) and found.how == "pushed" and found.row.number == 2 and found.row.origin == o
    first, second = b.rows()
    assert (first.commit, first.superseded, first.delivery) == (s, "moved", None)
    assert (second.validation, second.delivery, b.origin_main()) == ("passed", "pushed", second.commit) and b.execs() == RUN


def test_main_moving_after_the_candidate_is_made_is_target_moved_and_the_rerun_lands(b: LandBench) -> None:
    b.racing = lambda: b.advance({"OTHER": "another task\n"})  # right before the candidate's insert
    assert word(b.land()) == ("unavailable", "target_moved")
    assert b.repo.pushes == 0 and [(row.number, row.superseded) for row in b.rows()] == [(1, "moved")]
    found = b.land()
    assert isinstance(found, Landed) and found.row.number == 2 and b.origin_main() == found.row.commit


def test_a_push_rejected_after_the_read_reads_origin_again_and_answers_target_moved(b: LandBench) -> None:
    """The race between the delivery's `ls_remote` (R is O) and the push: Git's fast-forward rule refuses it."""
    b.repo.after_ls = [None, lambda: b.advance({"OTHER": "won the race\n"})]
    assert word(b.land()) == ("unavailable", "target_moved")
    assert b.repo.pushes == 1 and b.rows()[0].superseded == "moved" and b.rows()[0].delivery is None
    found = b.land()
    assert isinstance(found, Landed) and found.how == "pushed" and found.row.number == 2 and b.execs() == RUN


@pytest.mark.parametrize(("answer", "expected"), [
    (Transient("reset by peer"), ("unavailable", "remote")),
    (RemoteRejected("[remote rejected] main (protected branch hook declined)"), ("refused", "remote_rejected")),
    (HookRejected("pre-push hook declined"), ("unavailable", "git")),
])
def test_each_push_answer_records_nothing_and_leaves_the_candidate_pushable(
    b: LandBench, answer: Transient | RemoteRejected | HookRejected, expected: tuple[str, str]
) -> None:
    b.repo.answer = answer
    assert word(b.land()) == expected
    row = b.rows()[0]
    assert row.pushable and row.delivery is None and b.origin_main() == b.base
    assert isinstance(b.land(), Landed) and b.repo.pushes == 2  # the rerun pushes the same candidate


def test_a_failed_fetch_is_unavailable_remote_and_records_nothing(b: LandBench) -> None:
    b.repo.after_ls = [lambda: setattr(b.remote, "offline", True)]
    assert word(b.land()) == ("unavailable", "remote") and b.rows() == ()


def test_a_delivery_recorded_by_a_concurrent_land_is_the_same_answer(b: LandBench) -> None:
    def other() -> None:
        row = b.rows()[-1]
        LandStore(lambda: b.con).record_delivery(row.key, row.commit, 11)

    b.repo.after_ls = [None, other]
    found = b.land()
    assert isinstance(found, Landed) and found.how == "already_pushed" and found.row.delivered_at == 11


def test_withdraw_supersedes_a_pushable_candidate_and_the_abandon_proceeds(b: LandBench) -> None:
    pushable(b)
    store = CheckStore(lambda: b.con)
    assert store.abandon_released(CHECKS) == "landing"
    found = b.land("withdraw")
    assert isinstance(found, Withdrawn) and found.row.superseded == "withdrawn" and b.repo.pushes == 1  # the transient one
    assert store.abandon_released(CHECKS) == "abandoned"


def test_withdraw_of_a_candidate_already_on_origin_records_the_delivery(b: LandBench) -> None:
    s = lost(b)
    found = b.land("withdraw")
    assert isinstance(found, Landed) and found.how == "already_pushed" and found.row.remote_head == s
    assert CheckStore(lambda: b.con).abandon_released(CHECKS) == "landed"


def test_withdraw_with_nothing_pushable_is_refused(b: LandBench) -> None:
    assert word(b.land("withdraw")) == ("refused", "not_landing")
    assert word(b.land("withdraw", no_change=True)) == ("refused", "choices")


def test_a_closed_task_with_a_pushable_candidate_on_origin_records_the_delivery(b: LandBench) -> None:
    s = lost(b)
    b.status = "closed"
    found = b.land()
    assert isinstance(found, Landed) and found.how == "already_pushed" and found.row.remote_head == s and b.repo.pushes == 1


def test_a_closed_task_with_a_pushable_candidate_not_on_origin_is_refused_closed(b: LandBench) -> None:
    pushable(b)
    b.status = "closed"
    assert word(b.land()) == ("refused", "closed")
    assert b.rows()[0].pushable and b.repo.pushes == 1


def test_at_most_one_new_candidate_per_invocation(b: LandBench) -> None:
    """A resumed candidate superseded `moved` makes candidate 2 once; main moving again under it is `target_moved`."""
    pushable(b)
    b.advance({"OTHER": "another task\n"})
    def third() -> None:  # after candidate 1's supersede, right before candidate 2's insert
        b.racing = lambda: b.advance({"MORE": "a third task\n"})

    b.racing = third
    assert word(b.land()) == ("unavailable", "target_moved")
    assert [(row.number, row.superseded) for row in b.rows()] == [(1, "moved"), (2, "moved")] and b.repo.pushes == 1
    found = b.land()
    assert isinstance(found, Landed) and found.row.number == 3 and b.origin_main() == found.row.commit


def test_a_pruned_s_is_superseded_gone_and_candidate_two_lands(b: LandBench) -> None:
    s = pushable(b)
    b.repo.prune(s)
    found = b.land()
    assert isinstance(found, Landed) and found.row.number == 2 and b.origin_main() == found.row.commit
    assert (b.rows()[0].superseded, b.rows()[0].delivery) == ("gone", None)
