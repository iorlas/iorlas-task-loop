"""A round lands a passed task by itself under the profile's `land: auto` (tl-8bh9.14.136), through the one land operation
(here a recording port: `land.land` has its own tests) over the checks bench (`test_checks_round`): auto lands and manual
does not, a refusal about the task's change holds it once and a held task is never tried again, an unknown is tried again
next round, a refusal only a person decides is reported and leaves the task waiting, one land per round, the oldest first."""

import json
from collections.abc import Generator
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import MAIN_PROFILE, PinnedViews
from git_porcelain import Recorded, Repo
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from round_bench import Tracker, scripts, task
from sqlite_store import Store
from test_checks_round import LAND_LINE, Checking, implemented

from taskloop.attempt_types import SlotFiles
from taskloop.factory_schema import SCHEMA
from taskloop.land import How, LandRequest
from taskloop.land_mode import cached_mode, known_mode, land_mode
from taskloop.operations import Failed
from taskloop.profile import PROFILE_PATH, LandMode
from taskloop.round_land import Landing


@pytest.fixture
def rig(tmp_path: Path, slot: FakeWorktree, checkouts: PinnedViews, slot_files: SlotFiles) -> Generator[Checking]:
    """The checks bench (`test_checks_round.Checking`): one adopted slot, tl-1 ready with `auto`, `main` requiring `check` and `test`."""
    root = slot.repo.worktree(slot.repo.identity().root)
    root.write_file(PROFILE_PATH, json.dumps(MAIN_PROFILE))
    assert isinstance(root.record("profile", paths="all"), Recorded)
    path = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    built = Checking(path, con, tmp_path, slot, checkouts, slot_files, Tracker(task("tl-1")))
    scripts(built, slot, "tl-1", "tl-2", "tl-3")
    yield built
    con.close()


class Lands:
    """The land port: the profile's `land` as read now, and each land's answer in turn (the last one repeats)."""

    def __init__(self, mode: LandMode | Failed, *answers: How | Failed) -> None:
        self.mode, self.answers = mode, list(answers)
        self.requests = list[LandRequest]()
        self.reads = 0

    def landing(self) -> Landing:
        return Landing(self.read, self.land)

    def read(self, _checkout: Path) -> LandMode | Failed:
        self.reads += 1
        return self.mode

    def land(self, request: LandRequest) -> How | Failed:
        self.requests.append(request)
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def passed(rig: Checking, *others: str) -> None:
    """tl-1 (and any `others`, each ready first) has passed its checks and waits at `Next: land`."""
    implemented(rig)
    rig.bodies = ["passed"]
    assert rig.round() == [("tl-1", "check", "advance", "started")]
    assert rig.round() == [LAND_LINE]


def moves_of(rig: Checking) -> list[tuple[str, str, str, str]]:
    return [(each.task_id, each.step, each.action, each.word) for each in rig.last.moves]


def test_auto_lands_the_passed_task_it_took_through_the_one_land_with_the_rounds_choices(rig: Checking) -> None:
    passed(rig)
    lands = Lands(LandMode.AUTO, "pushed")
    rig.landing = lands.landing()
    assert rig.round(rig.last.written) == [LAND_LINE, ("tl-1", "check", "land", "pushed")]
    assert lands.requests == [LandRequest("tasks", "tl-1", rig.slot.repo.path, 30)]  # the validation's deadline is the round's --minutes
    assert rig.tracker.holds == [] and rig.logged("tl-1", "check", "land", "pushed", rig.key("tl-1").attempt_id) == 1


def test_manual_and_no_port_land_nothing_and_manual_reads_the_profile_once_a_round(rig: Checking) -> None:
    passed(rig)
    lands = Lands(LandMode.MANUAL, "pushed")
    rig.landing = lands.landing()
    assert rig.round(rig.last.written) == [LAND_LINE] and rig.round(rig.last.written) == [LAND_LINE]
    assert lands.requests == [] and lands.reads == 2 and rig.next_words() == {"tl-1": ("check", "land")}


def test_an_unreadable_profile_lands_nothing_and_says_why_once(rig: Checking) -> None:
    passed(rig)
    lands = Lands(Failed("unavailable", "remote"))
    rig.landing = lands.landing()
    assert rig.round(rig.last.written) == [LAND_LINE, ("tl-1", "check", "land", "unavailable:remote")]
    assert rig.round(rig.last.written) == [LAND_LINE, ("tl-1", "check", "land", "unavailable:remote")]
    assert lands.requests == [] and rig.logged("tl-1", "check", "land", "unavailable:remote", rig.key("tl-1").attempt_id) == 1


@pytest.mark.parametrize("reason", ["conflict", "checks_failed", "remote_rejected", "branch_moved", "claim_lost"])
def test_a_refusal_about_the_change_holds_the_task_once_with_the_cause_and_never_tries_it_again(rig: Checking, reason: str) -> None:
    passed(rig)
    lands = Lands(LandMode.AUTO, Failed("refused", reason))
    rig.landing = lands.landing()
    assert rig.round(rig.last.written) == [LAND_LINE, ("tl-1", "check", "hold", f"held land:{reason}")]
    assert rig.round(rig.last.written) == [] and rig.round(rig.last.written) == []  # on_hold: no land, no tracker call, no line
    assert len(lands.requests) == 1 and rig.next_words()["tl-1"] == ("implement", "on_hold")
    bead = rig.tracker.beads["tl-1"]
    assert (bead.status, bead.assignee, bead.labels) == ("open", "", ("held",))  # the claim returned, `auto` moved
    [(_, text)] = rig.tracker.comments
    assert f"taskloop hold: land:{reason}" in text and "tried to land this task by itself and was refused" in text
    assert "tl step" not in text  # a person is told what to decide in words, not which command to run


def test_a_conflict_comment_says_what_to_do_with_the_old_branch(rig: Checking) -> None:
    passed(rig)
    rig.landing = Lands(LandMode.AUTO, Failed("refused", "conflict")).landing()
    rig.round(rig.last.written)
    [(_, text)] = rig.tracker.comments
    assert "conflict with it" in text and "set the task's old branch aside" in text and "starts again on the current `main`" in text


def test_an_unknown_is_tried_again_next_round_and_never_holds(rig: Checking) -> None:
    passed(rig)
    lands = Lands(LandMode.AUTO, Failed("unavailable", "remote"), Failed("unavailable", "remote"), "pushed")
    rig.landing = lands.landing()
    assert rig.round(rig.last.written) == [LAND_LINE, ("tl-1", "check", "land", "unavailable:remote")]
    assert rig.round(rig.last.written) == [LAND_LINE, ("tl-1", "check", "land", "unavailable:remote")]
    assert rig.round(rig.last.written) == [LAND_LINE, ("tl-1", "check", "land", "pushed")]
    assert len(lands.requests) == 3 and rig.tracker.holds == []


def test_a_refusal_only_a_person_decides_is_reported_and_leaves_the_task_waiting(rig: Checking) -> None:
    passed(rig)
    lands = Lands(LandMode.AUTO, Failed("refused", "gate_changed"))
    rig.landing = lands.landing()
    assert rig.round(rig.last.written) == [LAND_LINE, ("tl-1", "check", "land", "refused:gate_changed")]
    assert rig.next_words() == {"tl-1": ("check", "land")} and rig.tracker.holds == []


def test_one_land_per_round_the_oldest_passed_task_first(rig: Checking) -> None:
    passed(rig)
    rig.adopt("s2")
    rig.tracker.beads["tl-2"] = task("tl-2")
    rig.bodies = ["passed"]
    for _ in range(5):  # tl-2: plan, verify, advance, verify, checks, then it waits at land too
        rig.round(rig.last.written)
    assert rig.next_words() == {"tl-1": ("check", "land"), "tl-2": ("check", "land")}
    lands = Lands(LandMode.AUTO, "pushed")
    rig.landing = lands.landing()
    rig.round(rig.last.written)
    assert [each.task_id for each in lands.requests] == ["tl-1"]  # one land, the oldest passed task
    rig.round(rig.last.written)
    assert [each.task_id for each in lands.requests] == ["tl-1", "tl-1"]  # the fake lands nothing: tl-1 is still the oldest


def profile(land: str | None) -> str:
    return json.dumps({"checks": [], "required": [], **({} if land is None else {"land": land})})


def test_the_mode_is_the_land_key_at_origin_main_fetched_now_and_manual_without_the_key(tmp_path: Path) -> None:
    remote = FakeRemote("https://example.invalid/repo.git")
    remote.advance("main", {"README": "one"})
    repo = FakeRepo.clone(remote, tmp_path / "main")

    def views(_path: Path, /, *, git_dir: Path | None = None) -> Repo:
        return repo

    read = land_mode(views)
    missing = read(repo.path)
    assert isinstance(missing, Failed) and missing.word == "refused:target_profile"
    remote.advance("main", {PROFILE_PATH: profile(None)})
    assert read(repo.path) is LandMode.MANUAL
    remote.advance("main", {PROFILE_PATH: profile("auto")})
    assert read(repo.path) is LandMode.AUTO  # a fetch each time: a landed change of the profile counts at once
    assert known_mode(views)(repo.path) is LandMode.AUTO  # the dashboard's local read of the same tracking ref


def test_the_dashboard_asks_the_profile_again_only_after_the_cache_runs_out() -> None:
    now, asked = [0.0], list[str]()

    def read(_checkout: Path) -> LandMode | None:
        asked.append("read")
        return LandMode.AUTO

    mode = cached_mode(read, Path("/checkout"), lambda: now[0], 30.0)
    assert [mode(), mode()] == [LandMode.AUTO, LandMode.AUTO] and len(asked) == 1
    now[0] = 31.0
    assert mode() is LandMode.AUTO and len(asked) == 2


@pytest.mark.parametrize("reason", ["conflict", "checks_failed", "remote_rejected", "branch_moved", "claim_lost"])
def test_an_unlabelled_land_refusal_is_held_once_and_preserves_other_labels(rig: Checking, reason: str) -> None:
    passed(rig)
    rig.con.execute("UPDATE attempt SET label=NULL")
    rig.tracker.beads["tl-1"] = replace(rig.tracker.beads["tl-1"], labels=("other",))
    lands = Lands(LandMode.AUTO, Failed("refused", reason))
    rig.landing = lands.landing()
    rig.round(rig.last.written)
    assert rig.next_words()["tl-1"] == ("implement", "on_hold")
    rig.round(rig.last.written)
    assert len(lands.requests) == 1 and len(rig.tracker.comments) == 1
    assert rig.tracker.beads["tl-1"].labels == ("other", "held")
    [(_, text)] = rig.tracker.comments
    assert "The factory added `held`" in text and "removed" not in text and "`None`" not in text
    assert "tl step" not in text


def test_round_ignores_another_repository_in_the_same_backlog(rig: Checking) -> None:
    passed(rig)
    rig.con.execute("UPDATE attempt SET repo_id='another-repository'")
    lands = Lands(LandMode.AUTO, "pushed")
    rig.landing = lands.landing()
    rig.round(rig.last.written)
    assert lands.requests == [] and lands.reads == 0


def test_newly_released_checks_can_land_in_the_same_round(rig: Checking) -> None:
    implemented(rig)
    rig.bodies = ["unreleased"]
    rig.round()
    lands = Lands(LandMode.AUTO, "pushed")
    rig.landing = lands.landing()
    rig.round(rig.last.written)
    assert [request.task_id for request in lands.requests] == ["tl-1"]
