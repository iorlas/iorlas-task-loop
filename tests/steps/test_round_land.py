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

from taskloop.attempt_loads import AttemptLoads
from taskloop.attempt_types import SlotFiles
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.hold_store import HoldRow, HoldStore
from taskloop.ids import NativeIds
from taskloop.land import How, LandRequest
from taskloop.land_conflict.admit import Ports, admit
from taskloop.land_conflict.handoff import request_for
from taskloop.land_conflict.store import ConflictStore
from taskloop.land_mode import known_mode, land_mode
from taskloop.merge.models import Phase, Reason, Work
from taskloop.merge.store import MergeStore
from taskloop.operations import Failed
from taskloop.profile import PROFILE_PATH, LandMode
from taskloop.round_land import Landing
from taskloop.slots import SlotGit


@pytest.fixture
def rig(tmp_path: Path, slot: FakeWorktree, checkouts: PinnedViews, slot_files: SlotFiles) -> Generator[Checking]:
    """The checks bench (`test_checks_round.Checking`): one adopted slot, tl-1 ready with `auto`, `main` requiring `check` and `test`."""
    root = slot.repo.worktree(slot.repo.identity().root)
    root.write_file(PROFILE_PATH, json.dumps(MAIN_PROFILE))
    assert isinstance(root.record("profile", paths="all"), Recorded)
    root.push("main")
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
@pytest.mark.parametrize("label", [None, "auto"])
def test_a_refusal_about_the_change_holds_the_task_once_with_the_cause_and_never_tries_it_again(
    rig: Checking, reason: str, label: str | None,
) -> None:
    passed(rig)
    rig.con.execute("UPDATE attempt SET label=?", (label,))
    if label is None:
        rig.tracker.beads["tl-1"] = replace(rig.tracker.beads["tl-1"], labels=())
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


def test_a_conflict_comment_preserves_retained_work_and_restored_labels_do_not_restart_it(rig: Checking) -> None:
    passed(rig)
    rig.landing = Lands(LandMode.AUTO, Failed("refused", "conflict")).landing()
    rig.round(rig.last.written)
    [(_, text)] = rig.tracker.comments
    assert "retained task work" in text and "stays held" in text and "resolution limit" in text
    assert "branch aside" not in text and "starts again" not in text and "restore the approval label" not in text
    rig.tracker.beads["tl-1"] = replace(rig.tracker.beads["tl-1"], labels=("auto",))
    for _ in range(2):
        assert rig.round(rig.last.written) == [("tl-1", "implement", "skip", "abandoned")]
    assert len(rig.tracker.comments) == 1 and rig.next_words()["tl-1"] == ("implement", "on_hold")


@pytest.mark.parametrize("evidence", ["valid", "identity", "active", "malformed"])
def test_terminal_notice_retries_an_interrupted_effect_and_reads_released_resolution_evidence(rig: Checking, evidence: str) -> None:
    passed(rig)
    [agent] = rig.store.current_attempts()
    checks = rig.checks.row(rig.key("tl-1"))
    assert checks is not None
    store = ConflictStore(lambda: rig.con)
    request = request_for(agent.key, checks, checks.commit, rig.now + 300)
    ports = Ports(store, AttemptLoads(lambda: rig.con), EvidenceFiles(rig.tmp), rig.slot.repo,
                  SlotGit(rig.checkouts, rig.files), lambda _p: True, lambda: rig.now, NativeIds())
    admitted = admit(ports, request)
    assert admitted.record is not None
    record = admitted.record
    work = Work(attempt_id=record.key.attempt_id, dispatch_token=record.key.dispatch_token,
                generation=record.key.reservation_generation, task_id=request.task_id, repo_id=request.repo_id,
                root=rig.root, slot=Path(record.slot_path), gitdir=rig.root / "gitdir", base=record.base,
                source=request.checked, target=request.target, branch=None, deadline=request.deadline,
                setting=record.inputs.setting, input_path=record.inputs.input_ref.path, input_digest=record.inputs.input_ref.digest,
                phase=Phase.TERMINAL, reason=Reason.OWNER, explanation="The retained resolution needs the owner's choice.")
    merges = MergeStore(lambda: rig.con)
    stored = work.model_copy(update={"dispatch_token": "another-operation"}) if evidence == "identity" else (
        work.model_copy(update={"phase": Phase.RESOLVE}) if evidence == "active" else work)
    merges.start(stored)
    if evidence == "malformed":
        rig.con.execute("UPDATE merge_operation SET data='{}' WHERE attempt_id=?", (record.key.attempt_id,))
    rig.con.execute("DELETE FROM reservation WHERE attempt_id=?", (record.key.attempt_id,))
    lands = Lands(LandMode.AUTO, Failed("refused", "conflict"))
    rig.landing = lands.landing()
    rig.tracker.down.add("comment")
    rig.round(rig.last.written)
    assert rig.tracker.comments == []
    rig.tracker.down.clear()
    if evidence == "malformed":
        rig.con.execute("UPDATE merge_operation SET data=? WHERE attempt_id=?", (work.model_dump_json(), record.key.attempt_id))
    elif evidence != "valid":
        merges.put(stored, work)
    rig.now += 121  # an interrupted notice's existing comment lease expires before another caller retries
    rig.round(rig.last.written)
    [(_, text)] = rig.tracker.comments
    assert f"> {work.explanation}" in text
    holds = list(rig.tracker.holds)
    rig.tracker.beads["tl-1"] = replace(rig.tracker.beads["tl-1"], labels=("auto",))
    for _ in range(2):
        assert rig.round(rig.last.written) == [("tl-1", "implement", "skip", "abandoned")]
    assert rig.tracker.holds == holds and len(lands.requests) == 1
    assert merges.get(record.key.attempt_id) == work


def test_a_crash_after_posting_a_terminal_notice_reconciles_without_posting_it_twice(
    rig: Checking, monkeypatch: pytest.MonkeyPatch,
) -> None:
    passed(rig)
    lands = Lands(LandMode.AUTO, Failed("refused", "conflict"))
    rig.landing = lands.landing()

    def interrupted(_store: HoldStore, _attempt_id: str, _rev: int, _now: float) -> HoldRow:
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(HoldStore, "commented", interrupted)
        with pytest.raises(KeyboardInterrupt):
            rig.round(rig.last.written)
    assert len(rig.tracker.comments) == 1
    rig.now += 121
    rig.round(rig.last.written)
    assert rig.next_words()["tl-1"] == ("implement", "on_hold")
    assert len(rig.tracker.comments) == 1 and len(lands.requests) == 1
    writes = list(rig.tracker.holds)
    assert rig.round(rig.last.written) == []
    assert rig.tracker.holds == writes


@pytest.mark.parametrize("reason", ["remote", "running", "unknown", "no_slot"])
def test_an_unknown_is_tried_again_next_round_and_never_holds(rig: Checking, reason: str) -> None:
    passed(rig)
    lands = Lands(LandMode.AUTO, Failed("unavailable", reason), Failed("unavailable", reason), "pushed")
    rig.landing = lands.landing()
    assert rig.round(rig.last.written) == [LAND_LINE, ("tl-1", "check", "land", f"unavailable:{reason}")]
    assert rig.round(rig.last.written) == [LAND_LINE, ("tl-1", "check", "land", f"unavailable:{reason}")]
    assert rig.round(rig.last.written) == [LAND_LINE, ("tl-1", "check", "land", "pushed")]
    assert len(lands.requests) == 3 and rig.tracker.holds == []


def test_a_refusal_only_a_person_decides_is_reported_and_leaves_the_task_waiting(rig: Checking) -> None:
    passed(rig)
    lands = Lands(LandMode.AUTO, Failed("refused", "gate_changed"))
    rig.landing = lands.landing()
    assert rig.round(rig.last.written) == [LAND_LINE, ("tl-1", "check", "land", "refused:gate_changed")]
    assert rig.next_words() == {"tl-1": ("check", "land")} and rig.tracker.holds == []


@pytest.mark.parametrize("label", [None, "auto"])
def test_one_land_per_round_the_oldest_passed_task_first(rig: Checking, label: str | None) -> None:
    passed(rig)
    rig.con.execute("UPDATE attempt SET label=?", (label,))
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
