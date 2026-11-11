"""A task's land in its status and its release (tl-8bh9.14.8 sections 13 and 14, slice L5) over `land_bench`: every row of
the `Next` table (`land`, `landed`, a land's `release`; a failed checks attempt with no candidate stays `done`), `tl step
show`'s `Land` lines and JSON `land` key, the list's word, printable stored words, and `tl step release` going land
candidate first, then the checks attempt, then the implement attempt (settled, abandoned, refused `landing`/`landed`,
held by a live land process, and its rerun)."""

import dataclasses
import json
from pathlib import Path

import pytest
from doubles import Command
from git_porcelain import Transient
from land_bench import ME, RUN, LandBench, bench

from taskloop.attempt_status import AttemptView, Listed, Shown, StatusPorts, list_attempts, show_attempt
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, EntryIdentity, Seen
from taskloop.check_release import ChecksRelease
from taskloop.land import Landed
from taskloop.land_close import NOT_SYNCED
from taskloop.land_guide import CANDIDATE_RELEASE, LAND_GUIDE, LAND_NEXT
from taskloop.operations import Failed, ReleasedTask, release_task
from taskloop.result_data import as_data
from taskloop.slot_release import AlreadyReleased, NotReleased, Released, ReleaseResult
from taskloop.step_render import human
from taskloop.tracker_client import CloseAnswer


@pytest.fixture
def b(tmp_path: Path) -> LandBench:
    return bench(tmp_path)


def _observe(b: LandBench, alive: set[EntryIdentity]) -> StatusPorts:
    def seen(entry: EntryIdentity) -> Seen:
        return "matching" if entry in alive else "gone"

    return StatusPorts(AttemptStore(lambda: b.con), seen, lambda: b.now, lambda _key: None, lambda: "boot")


def shown(b: LandBench, alive: set[EntryIdentity] | None = None) -> Shown:
    found = show_attempt(_observe(b, alive or set()), b.environment.artifacts, "tasks", "tl-1")
    assert isinstance(found, Shown), found
    return found


def view(b: LandBench) -> AttemptView:
    listed = list_attempts(_observe(b, set()))
    assert isinstance(listed, Listed) and len(listed.attempts) == 1
    return listed.attempts[0]


def lines(b: LandBench, alive: set[EntryIdentity] | None = None) -> list[str]:
    return human("tl step show", shown(b, alive), b.root / "factory.db")


def land_lines(found: list[str]) -> list[str]:
    return [line for line in found if line.startswith(("Land", "Pushed:", "Delivered:", "Closed:", "Tracker:"))]


def interrupt() -> None:
    raise KeyboardInterrupt


def interrupted(b: LandBench) -> None:
    """Ctrl-C while S's second check runs: the candidate pending, its land process `ME` stored, the check unfinished."""
    b.advance({"OTHER": "another task\n"})
    b.environment.process.script = [Command(), Command(), Command(effect=interrupt)]
    with pytest.raises(KeyboardInterrupt):
        b.land()


def test_passed_checks_with_no_candidate_are_next_land_with_the_land_guide(b: LandBench) -> None:
    found = shown(b)
    assert (found.view.next, found.view.land) == ("land", None) and as_data(found)["land"] is None
    assert lines(b)[-2:] == ["Next: land", LAND_NEXT["land"]] and land_lines(lines(b)) == []


def test_failed_checks_with_no_candidate_stay_done(b: LandBench) -> None:
    b.con.execute("UPDATE checks_attempt SET conclusion='failed',reason='test:failed'")
    assert view(b).next == "done"


def test_a_same_tree_land_is_landed_with_its_lines_and_no_slot_or_check(b: LandBench) -> None:
    found = b.land()
    assert isinstance(found, Landed)
    row = found.row
    assert land_lines(lines(b)) == [
        f"Land: candidate 1 ({row.key.attempt_id}) onto origin main at {b.base}: {row.commit}; same tree as X, no checks",
        f"Land required: check, test (origin main at {b.base}; same as the checks)",
        "Land result: same_tree",
        f"Pushed: origin main at {row.commit}, 1970-01-01 00:00:10 UTC",
        "Closed: 1970-01-01 00:00:10 UTC (closed)", NOT_SYNCED,
    ]
    assert lines(b)[-2:] == ["Next: landed", LAND_NEXT["landed"]] and view(b).next == "landed"
    data = as_data(shown(b))["land"]
    assert isinstance(data, dict) and (data["commit"], data["delivery"], data["close"], data["results"]) == (row.commit, "pushed",
                                                                                                             "closed", [])


def test_a_close_refused_after_the_push_is_still_next_land_and_shows_pushed(b: LandBench) -> None:
    b.closing = [CloseAnswer("unavailable", detail="bd timed out")]
    assert isinstance(b.land(), Failed)
    shown_lines = land_lines(lines(b))
    assert view(b).next == "land" and shown_lines[-1].startswith("Pushed: origin main at ")
    assert not any(line.startswith(("Closed:", "Tracker:")) for line in shown_lines)


def test_a_validated_land_shows_its_slot_and_land_check_lines_with_their_logs(b: LandBench) -> None:
    b.advance({"OTHER": "another task\n"})
    b.environment.process.script = [Command(), Command(), Command(rc=1)]
    assert isinstance(b.land(), Failed)
    found = shown(b)
    land = found.view.land
    assert land is not None and found.view.next == "land"
    directory = b.environment.artifacts / "attempts"
    shown_lines = land_lines(lines(b))
    assert shown_lines[0].endswith("merged onto a moved main, checks run again")
    assert shown_lines[2] == f"Land slot: s1, released 1970-01-01 00:00:10 UTC, parked at {b.d}"
    assert shown_lines[3].startswith("Land check: check passed, exit 0, 0 s; log ") and shown_lines[3].endswith("/check-1-check.log")
    assert shown_lines[4].startswith("Land check: test failed, exit 1") and shown_lines[5:] == ["Land result: failed test:failed"]
    assert all(each is not None and each.is_relative_to(directory) for each in land.logs)
    data = as_data(found)["land"]
    assert isinstance(data, dict) and [each["conclusion"] for each in data["results"]] == ["passed", "failed"]  # type-checked shape


def test_a_pending_candidate_whose_land_process_runs_is_next_land_and_names_the_process(b: LandBench) -> None:
    interrupted(b)
    shown_lines = land_lines(lines(b, {ME}))
    assert "Land slot: s1, held" in shown_lines and "Land process: running (pid 4242, started land-start)" in shown_lines
    assert "Land result: pending" in shown_lines and any(line.startswith("Land check: test unfinished, process group") for line in
                                                          shown_lines)
    assert shown(b, {ME}).view.next == "land" and "Land process: gone (pid 4242, started land-start)" in land_lines(lines(b))


def test_a_held_release_after_the_push_is_next_release_with_the_land_s_release_guide(b: LandBench) -> None:
    b.advance({"OTHER": "another task\n"})
    pointer = b.slot.path / ".git"
    b.environment.process.script = [Command(), Command(), Command(effect=lambda: b.files.contents.update({pointer: b"gitdir: /x\n"}))]
    found = b.land()
    assert isinstance(found, Landed) and found.row.holds_slot and found.row.close == "closed"
    assert lines(b)[-2:] == ["Next: release", LAND_NEXT["release"]] and view(b).next == "release"
    assert "Land slot: s1, held" in land_lines(lines(b))


def test_a_withdrawn_candidate_says_superseded_and_is_next_land(b: LandBench) -> None:
    b.repo.answer = Transient("connection reset")
    assert isinstance(b.land(), Failed)
    b.land("withdraw")
    assert "Land superseded: withdrawn" in land_lines(lines(b)) and view(b).next == "land"


def test_a_no_change_land_on_failed_checks_is_landed(b: LandBench) -> None:
    b.con.execute("UPDATE checks_attempt SET conclusion='failed',reason='test:failed'")
    b.advance({"src/x.py": "X = 1\n"})  # main already holds X's change
    assert isinstance(b.land(no_change=True), Landed)
    assert view(b).next == "landed" and any(line.startswith("Delivered: no change, origin main at") for line in lines(b))


def test_stored_words_are_shown_as_one_printable_line(b: LandBench) -> None:
    b.advance({"OTHER": "another task\n"})
    b.environment.process.script = [Command(), Command(), Command(rc=1)]
    assert isinstance(b.land(), Failed)
    b.con.execute("UPDATE land_candidate SET reason=?", ("test:failed\n\x1b[31mClosed: forged\u2028x",))
    shown_lines = land_lines(lines(b))
    assert "Land result: failed test:failed [31mClosed: forged x" in shown_lines
    assert all(line.isprintable() for line in shown_lines) and not any(line.startswith("Closed:") for line in shown_lines)


@dataclasses.dataclass
class Implement:
    """The implement attempt's release port: records each call, answers `result`."""

    calls: list[tuple[str, bool]] = dataclasses.field(default_factory=list)
    result: ReleaseResult = dataclasses.field(default_factory=lambda: Released("s0", None, False, "unclaimed", True))

    def release(self, key: AttemptKey, abandon: bool, me: EntryIdentity | None = None) -> ReleaseResult:
        del me
        self.calls.append((key.attempt_id, abandon))
        return self.result


@dataclasses.dataclass(frozen=True)
class HalfWay:
    """The real candidate release, then a checks attempt's release that fails (`unavailable store`): an abandon stopping
    half way."""

    real: ChecksRelease

    def release_candidate(self, key: AttemptKey, abandon: bool, me: EntryIdentity | None = None) -> ReleaseResult:
        return self.real.release_candidate(key, abandon, me)

    def release(self, key: AttemptKey, abandon: bool, me: EntryIdentity | None = None) -> ReleaseResult:
        del key, abandon, me
        return NotReleased("unavailable", "store", "OperationalError. Nothing changed.")


def release(b: LandBench, abandon: bool, implement: Implement, alive: set[EntryIdentity] | None = None, *,
            halfway: bool = False) -> ReleasedTask | Failed:
    work = b.checking()

    def seen(entry: EntryIdentity) -> Seen:
        return "matching" if entry in (alive or set()) else "gone"

    checks = ChecksRelease(work.store, work.checkouts, work.slot_files, seen, b.ports().custody, work.clock, work.seen, work.scratch)
    ports = HalfWay(checks) if halfway else checks
    return release_task(AttemptStore(lambda: b.con), implement, ports, "tasks", "tl-1", abandon=abandon)


def test_a_settled_release_frees_a_held_land_slot_alone(b: LandBench) -> None:
    test_a_held_release_after_the_push_is_next_release_with_the_land_s_release_guide(b)
    del b.files.contents[b.slot.path / ".git"]
    implement = Implement()
    found = release(b, False, implement)
    candidate = b.rows()[0]
    assert isinstance(found, ReleasedTask) and found.candidate and found.attempt_id == candidate.key.attempt_id
    assert isinstance(found.result, Released) and (found.checks, found.land, implement.calls) == (None, None, [])
    assert candidate.released_at is not None and b.reservations() == [] and view(b).next == "landed"
    assert human("tl step release", found, None)[0] == f"released: land candidate {candidate.key.attempt_id} for tl-1 (backlog tasks)"
    assert json.loads(json.dumps(as_data(found)))["candidate"] is True


def test_the_abandon_goes_land_candidate_first_then_checks_then_the_implement_attempt(b: LandBench) -> None:
    interrupted(b)
    implement = Implement()
    found = release(b, True, implement)
    candidate = b.rows()[0]
    assert isinstance(found, ReleasedTask) and found.attempt_id == "implement" and implement.calls == [("implement", True)]
    assert found.land is not None and found.land.candidate and found.land.attempt_id == candidate.key.attempt_id
    assert found.checks is not None and found.checks.attempt_id == "checks" and found.checks.result.abandoned
    assert (candidate.superseded, b.reservations()) == ("abandoned", []) and b.slot_head() == b.d
    assert "Land superseded: abandoned" in land_lines(lines(b)) and view(b).next == "release"  # the claim is still to be returned
    rendered = human("tl step release", found, None)
    assert [line.split(":")[0] for line in rendered if line.startswith(("released", "abandoned"))] == ["released"] * 3
    assert rendered.index(f"released: land candidate {candidate.key.attempt_id} for tl-1 (backlog tasks)") < rendered.index(
        "released: attempt checks for tl-1 (backlog tasks)")
    data = as_data(found)
    assert isinstance(data["land"], dict) and data["land"]["candidate"] is True and data["candidate"] is False


def test_the_abandon_of_a_live_land_is_held_and_guided_as_a_land(b: LandBench) -> None:
    interrupted(b)
    implement = Implement()
    found = release(b, True, implement, {ME})
    assert isinstance(found, Failed) and found.land and found.word == "refused:entry_running" and implement.calls == []
    assert b.rows()[0].pending and "land process" in found.detail
    rendered = human("tl step release", found, None)
    assert rendered[0] == "tl step release: refused:entry_running" and CANDIDATE_RELEASE["entry_running"] in rendered
    assert LAND_GUIDE["unavailable"] not in rendered and LAND_GUIDE["entry_running"] not in rendered


def test_a_release_unknown_of_a_candidate_says_rerun_the_release_never_the_land() -> None:
    failed = Failed("unavailable", "changed", "The land candidate no longer holds its reservation.", land=True)
    rendered = human("tl step release", failed, None)
    assert CANDIDATE_RELEASE["unavailable"] in rendered and CANDIDATE_RELEASE["changed"] in rendered
    assert LAND_GUIDE["unavailable"] not in rendered and LAND_GUIDE["changed"] not in rendered


def test_an_abandon_stopping_after_the_candidate_is_next_release_and_the_land_refuses_until_it_finished(b: LandBench) -> None:
    interrupted(b)
    implement = Implement()
    found = release(b, True, implement, halfway=True)
    assert isinstance(found, Failed) and found.word == "unavailable:store" and found.checks and implement.calls == []
    assert found.detail.endswith("The land candidate was released first.") and b.rows()[0].superseded == "abandoned"
    assert lines(b)[-2:] == ["Next: release", LAND_GUIDE["abandoning"]] and view(b).next == "release"
    pushes, main = b.repo.pushes, b.origin_main()
    refused = b.land()
    assert isinstance(refused, Failed) and refused.word == "refused:abandoning" and len(b.rows()) == 1
    assert (b.repo.pushes, b.origin_main(), b.execs()) == (pushes, main, RUN)
    assert isinstance(b.land("withdraw"), Failed) and isinstance(b.land(no_change=True), Failed)
    done = release(b, True, implement)
    assert isinstance(done, ReleasedTask) and done.land is None and implement.calls == [("implement", True)]


def test_a_pending_candidate_whose_land_process_cannot_be_observed_is_unknown_and_listed_stuck(b: LandBench) -> None:
    interrupted(b)
    reads = dataclasses.replace(_observe(b, set()), observe=lambda _entry: "unknown")
    listed = list_attempts(reads, stuck=True)
    assert isinstance(listed, Listed) and [each.next for each in listed.attempts] == ["unknown"]


@pytest.mark.parametrize(("arrange", "word"), [
    (lambda b: setattr(b.repo, "answer", Transient("connection reset")) or b.land(), "landing"),
    (lambda b: b.land(), "landed"),
], ids=["pushable", "delivered"])
def test_the_abandon_of_a_pushable_or_delivered_candidate_is_refused_and_nothing_changes(
    b: LandBench, arrange: object, word: str
) -> None:
    assert callable(arrange)
    arrange(b)
    before = b.rows()
    implement = Implement()
    found = release(b, True, implement)
    assert isinstance(found, Failed) and found.word == f"refused:{word}" and implement.calls == [] and b.rows() == before
    assert LAND_GUIDE[word] in human("tl step release", found, None)
    assert b.con.execute("SELECT abandoned FROM checks_attempt").fetchone() == (0,)


def test_a_rerun_of_the_abandon_never_releases_the_candidate_again(b: LandBench) -> None:
    interrupted(b)
    first = release(b, True, Implement(result=AlreadyReleased("s0", "unclaiming", True)))
    assert isinstance(first, ReleasedTask) and first.land is not None
    again = release(b, True, Implement(result=AlreadyReleased("s0", "unclaimed", True)))
    assert isinstance(again, ReleasedTask) and again.land is None and again.checks is not None
    assert isinstance(again.checks.result, AlreadyReleased) and b.rows()[0].superseded == "abandoned"
