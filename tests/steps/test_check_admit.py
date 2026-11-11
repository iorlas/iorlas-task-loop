"""The checks admission (S6d, tl-8bh9.14.6 section 5) over a factory.db file (the `done` implement attempt), the semantic Git
fake (the person's `main` with its profile, `task/tl-1` holding X), the real profile reader on the checkout and a tracker
double: the stored row and reservation, each refusal with nothing written (and no tracker read before step 6), a re-run,
and the races decided under the write lock."""

import json
from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from doubles import MAIN_PROFILE, ChecksBench, Done, FakeSlotFiles, PinnedViews
from git_porcelain import Sha
from git_porcelain.testing import FakeRemote, FakeRepo
from sqlite_store import begin_immediate

from taskloop.admit import AdmitRefused, Admitted
from taskloop.admit_chain import NextAdmission, NextStepRequest
from taskloop.attempt_types import AttemptKey
from taskloop.check_store import ChecksAdmitted, CheckStore, insert
from taskloop.checks import argv_digest
from taskloop.evidence_files import EvidenceFiles


@pytest.fixture
def bench(done: Done, repo: FakeRepo, checkouts: PinnedViews, slot_files: FakeSlotFiles) -> Generator[ChecksBench]:
    found = ChecksBench(done, repo, checkouts, slot_files)
    yield found
    found.con.close()


def required() -> str:
    return json.dumps([["check", argv_digest(["just", "check"])], ["test", argv_digest(["just", "test"])]], separators=(",", ":"))


def test_an_advance_stores_number_1_on_a_free_slot_at_d_with_the_target_and_its_required_digests(bench: ChecksBench) -> None:
    found = bench.admit()
    assert isinstance(found, Admitted) and found.slot == "s1" and bench.reads == ["tl-1"]
    rows, held = bench.stored()
    assert rows == [(1, "s1", bench.done.d, bench.done.target, required(), 100.0, "admitted", "implement")]
    assert held == [("s1", found.key.attempt_id, 1)] and found.key.reservation_generation == 1
    assert bench.con.execute("SELECT generation FROM slot WHERE name='s1'").fetchone() == (1,)
    current = CheckStore(lambda: bench.con).attempt_of("tasks", "tl-1")
    assert current is not None and current[0] == found.key and current[1] == "admitted"
    assert bench.con.execute("SELECT count(*) FROM attempt").fetchone() == (1,)  # no agent attempt, no input file
    assert not (bench.done.path.parent / "attempts").exists()


def refused_profile(bench: ChecksBench, **change: object) -> None:
    bench.main({**MAIN_PROFILE, **change})


def moved_branch(bench: ChecksBench) -> None:
    bench.repo.delete_branch("task/tl-1", expected=Sha(bench.done.x))
    bench.root.checkout_new("task/tl-1", bench.done.target)
    bench.root.checkout("main")


def missing_x(bench: ChecksBench) -> None:
    gone = "e" * 40
    bench.con.execute("UPDATE attempt SET end_commit=?", (gone,))
    bench.con.execute("UPDATE published_branch SET commit_sha=?", (gone,))


@pytest.mark.parametrize(("arrange", "word"), [
    (lambda b: setattr(b, "now", 100), "expired"),
    (lambda b: b.con.execute("UPDATE slot_release SET claim='unclaiming'"), "not_advanceable"),  # the abandon's flip went first
    (lambda b: b.con.execute("UPDATE verification SET verdict='rejected',reason='x'"), "not_advanceable"),
    (lambda b: b.con.execute("DELETE FROM published_branch"), "not_advanceable"),
    (lambda b: b.con.execute("UPDATE attempt SET step='plan',after_commit=NULL"), "not_advanceable"),  # an agent step follows
    (lambda b: b.repo.delete_branch("task/tl-1", expected=Sha(b.done.x)), "branch_moved"),
    (moved_branch, "branch_moved"),
    (missing_x, "commit_missing"),
    (lambda b: b.repo.rename_branch("main", "trunk"), "target"),
    (lambda b: refused_profile(b, target="release"), "target"),
    (lambda b: b.main(None), "target_profile"),
    (lambda b: refused_profile(b, required=["check", "smoke"]), "target_profile"),
    (lambda b: refused_profile(b, checks="many"), "target_profile"),
    (lambda b: refused_profile(b, required=[]), "no_required"),
    (lambda b: b.con.execute("INSERT INTO reservation VALUES ('s1',?,9,'another')", (b.repo.identity().key,)), "no_free_slot"),
], ids=["expired", "unclaiming", "rejected", "unpublished", "plan", "branch_gone", "branch_moved", "commit_missing", "no_main",
        "other_target", "no_profile", "required_undefined", "bad_profile", "no_required", "no_free_slot"])
def test_each_refusal_before_the_tracker_read_writes_nothing(
    bench: ChecksBench, arrange: Callable[[ChecksBench], object], word: str
) -> None:
    arrange(bench)
    before = bench.stored()
    found = bench.admit()
    assert isinstance(found, AdmitRefused) and found.reason == word
    assert bench.stored() == before and bench.reads == []


@pytest.mark.parametrize(("status", "assignee"), [("open", ""), ("in_progress", "someone"), ("closed", "taskloop")])
def test_a_claim_lost_since_the_implement_step_refuses_after_one_tracker_read(bench: ChecksBench, status: str, assignee: str) -> None:
    bench.status, bench.assignee = status, assignee
    found = bench.admit()
    assert isinstance(found, AdmitRefused) and found.reason == "claim_lost" and bench.reads == ["tl-1"]
    assert bench.stored() == ([], [])


def test_another_repository_s_checkout_is_refused(bench: ChecksBench, tmp_path: Path) -> None:
    other = FakeRepo.clone(FakeRemote("https://example.invalid/other.git"), tmp_path / "other")
    bench.views = PinnedViews(bench.repo, other)
    found = bench.admit(checkout=other.identity().root)
    assert isinstance(found, AdmitRefused) and found.reason == "checkout" and bench.stored() == ([], [])


def test_x_only_on_origin_s_task_branch_is_admitted(bench: ChecksBench) -> None:
    """The local `task/<id>` gone, the remote-tracking one still contains X: the checks run on X itself."""
    bench.root.checkout("task/tl-1")
    bench.root.push("task/tl-1")
    bench.root.checkout("main")
    bench.repo.fetch()
    bench.repo.delete_branch("task/tl-1", expected=Sha(bench.done.x))
    assert isinstance(bench.admit(), Admitted)


def test_a_failed_released_checks_attempt_is_re_run_as_number_2_and_the_first_is_kept(bench: ChecksBench) -> None:
    first = bench.admit()
    assert isinstance(first, Admitted)
    bench.concluded("failed", released=False)
    unreleased = bench.admit(2)
    assert isinstance(unreleased, AdmitRefused) and unreleased.reason == "task_attempted"  # released first
    bench.concluded("failed")
    target = bench.main({**MAIN_PROFILE, "required": ["test"]})  # the re-run reads `main` again
    again = bench.admit(2)
    assert isinstance(again, Admitted) and again.key != first.key and again.key.reservation_generation == 2
    rows, held = bench.stored()
    assert [row[0:4] for row in rows] == [(1, "s1", bench.done.d, bench.done.target), (2, "s1", bench.done.d, target)]
    assert json.loads(str(rows[1][4])) == [["test", argv_digest(["just", "test"])]] and held == [("s1", again.key.attempt_id, 2)]


@pytest.mark.parametrize(("conclusion", "abandoned", "word"), [
    ("passed", False, "task_attempted"), ("failed", True, "not_advanceable"),
], ids=["passed", "abandon_half_done"])
def test_a_passed_or_abandoned_latest_attempt_is_never_re_run(bench: ChecksBench, conclusion: str, abandoned: bool, word: str) -> None:
    assert isinstance(bench.admit(), Admitted)
    bench.concluded(conclusion, abandoned=abandoned)
    before = bench.stored()
    found = bench.admit(2)
    assert isinstance(found, AdmitRefused) and found.reason == word and bench.stored() == before


def test_a_number_other_than_the_store_s_is_task_attempted(bench: ChecksBench) -> None:
    """The caller read the task before another start admitted or concluded a checks attempt."""
    found = bench.admit(2)
    assert isinstance(found, AdmitRefused) and found.reason == "task_attempted" and bench.stored() == ([], []) and bench.reads == []


def racer(bench: ChecksBench) -> None:
    """Another start's admission of number 1, committed between this admission's reads and its write."""
    with begin_immediate(bench.con):
        bench.con.execute("INSERT INTO reservation VALUES ('s0',?,7,'winner')", (bench.repo.identity().key,))
        insert(bench.con, ChecksAdmitted(AttemptKey("winner", "w", 7), "implement", 1, "s0", bench.done.d, bench.done.target,
                                         (("check", "1" * 64),), 100.0))


def concluded_racer(bench: ChecksBench) -> None:
    """The racing admission's checks attempt has even concluded `failed` and been released since: the next is number 2."""
    racer(bench)
    bench.concluded("failed")


@pytest.mark.parametrize(("arrange", "word"), [
    (racer, "task_attempted"),
    (concluded_racer, "task_attempted"),
    (lambda b: b.con.execute("UPDATE slot_release SET claim='unclaiming'"), "not_advanceable"),  # the abandon's flip
    (lambda b: b.con.execute("INSERT INTO reservation VALUES ('s1',?,9,'another')", (b.repo.identity().key,)), "no_free_slot"),
], ids=["winner", "winner_failed", "abandon_flip", "slot_taken"])
def test_a_commit_between_the_reads_and_the_write_is_seen_under_the_lock(
    bench: ChecksBench, arrange: Callable[[ChecksBench], object], word: str
) -> None:
    bench.racing = lambda: arrange(bench)
    found = bench.admit()
    assert isinstance(found, AdmitRefused) and found.reason == word
    ids = [row[0] for row in bench.con.execute("SELECT attempt_id FROM checks_attempt")]
    assert ids in ([], ["winner"]) and {each[1] for each in bench.stored()[1]} <= {"winner", "another"}  # nothing of ours


def test_the_agent_advance_refuses_the_check_step_before_any_tracker_read_or_input(bench: ChecksBench) -> None:
    """`admit_chain` admits only agent steps: after implement it is `not_advanceable` (never `kind("check")`)."""
    advance = NextAdmission(lambda: bench.con, begin_immediate, EvidenceFiles(bench.done.path.parent), bench.inspect, bench.views,
                            lambda: 10, lambda _p: True, bench.files)
    found = advance.admit_next(NextStepRequest(bench.done.implement, bench.repo.path, "m", "high", "workspace-write", 100.0))
    assert isinstance(found, AdmitRefused) and found.reason == "not_advanceable" and bench.reads == []
