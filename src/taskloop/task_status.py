"""The one task status (tl-8bh9.14.143): what a task is doing, computed once from the stored facts of its current view (the attempt,
its release, hold and land) and, when the reader knows it, the admission facts (which tasks the tracker lists ready under the round's
label, and what keeps a round from starting one). `tl step list`, the dashboard's board and drawer and the round's admission all call
`task_status`, so they cannot disagree. Pure: values in, values out.

A task whose attempt a person abandoned (`tl step release --abandon`, the claim returned, no hold) is `abandoned` until the tracker
lists it ready under the round's approval label; then the round restarts it fresh (`QUEUED`, one restart route, no `tl step start`
by hand). A task a hold abandoned is `held` and is taken again only by the person's answer (`hold_status.reingests`)."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from taskloop.attempt_result import succeeded
from taskloop.attempt_status import AttemptView
from taskloop.hold_status import RETURNED, reingests
from taskloop.land_policy import LandPolicy, LandState, decision
from taskloop.land_policy import words as land_words
from taskloop.land_status import LandView
from taskloop.profile import LandMode


class Status(StrEnum):
    RUNNING = "running"  # an agent step runs (plan, implement)
    CHECKING = "checking"  # the check step runs
    SETTLING = "settling"  # the factory moves it: starting, verifying, repeating, releasing, publishing, advancing
    WAITING_FOR_LAND = "waiting_for_land"  # checked and passed: the landing decision says who delivers
    LANDING = "landing"  # a land is observed running
    LANDED = "landed"
    HELD = "held"  # a hold, due or recorded: waits for a person (its reason is the hold's)
    STUCK = "stuck"  # failed, `stuck:*`, `repeats_exhausted` or unknown, not (yet) held: needs a person
    FINISHED = "finished"  # done and nothing follows
    ABANDONED = "abandoned"  # a person gave the attempt up; nothing starts it until the approval label is on the task
    QUEUED = "queued"  # waits to be (re)started by a round; `Wait` says why not yet


class Wait(StrEnum):
    READY = "ready"  # the next round starts it
    NO_FREE_SLOT = "no_free_slot"
    SLOT_FOR_LAND = "slot_for_land"  # the last free slot is the person's land's
    MAX_RUNNING = "max_running"  # the in-flight bound is reached
    SKIPPED = "skipped"  # a selection rule (its word is `TaskStatus.skip`)


IN_FLIGHT: Final = frozenset({Status.RUNNING, Status.CHECKING, Status.SETTLING, Status.WAITING_FOR_LAND, Status.LANDING})
SETTLING: Final = frozenset({"start", "verify", "repeat", "release", "publish", "advance"})
FRESH: Final = frozenset({Status.ABANDONED, Status.QUEUED})  # no current work: a new attempt is what comes next


@dataclass(frozen=True)
class Admission:
    """What a reader knows of ingestion: `approved`, the tasks the tracker lists ready under `label` (the round's), and `wait`, what
    keeps a round from starting a task now (`READY`: nothing)."""

    approved: frozenset[str]
    label: str
    wait: Wait = Wait.READY


@dataclass(frozen=True)
class TaskStatus:
    status: Status
    reason: str | None = None  # the stored typed reason: a hold's, a failed result's, a `stuck:*` word, a setting's `Next` word
    wait: Wait | None = None  # QUEUED only
    skip: str | None = None  # QUEUED with `Wait.SKIPPED`: the selection rule's word
    landing: LandState | None = None
    policy_commit: str | None = None


def blocker(free: int, reserve: int, running: int, bound: int) -> Wait:
    """What keeps a round from starting a task: no slot is free, the last ones are reserved for a land, or the bound is reached."""
    if free == 0:
        return Wait.NO_FREE_SLOT
    if free <= reserve:
        return Wait.SLOT_FOR_LAND
    return Wait.MAX_RUNNING if running >= bound else Wait.READY


def skipped(rule: str) -> TaskStatus:
    return TaskStatus(Status.QUEUED, rule, Wait.SKIPPED, rule)


def waiting_for_land(view: AttemptView) -> bool:
    """Released passing checks eligible for land, independently of the admission label."""
    checks = view.checks
    return (view.next == "land" and checks is not None and checks.row.conclusion == "passed"
            and checks.row.released_at is not None and not checks.row.abandoned
            and view.hold is None and not (view.release is not None and view.release.abandoned))


def landing(land: LandView | None) -> bool:
    """A land is observed running (every other task at its land waits for the person)."""
    return land is not None and land.row.pending and land.process == "running"


def restartable(view: AttemptView, admission: Admission | None) -> bool:
    """The restart rule: the person abandoned the attempt (claim returned, no hold) and the tracker lists the task ready under the
    round's approval label, or a hold's answer (`hold_status.reingests`) did."""
    if admission is None or view.task_id not in admission.approved:
        return False
    if view.hold is not None:
        return reingests(view.next, view.hold, admission.label)
    return view.release is not None and view.release.claim in RETURNED


def _stopped(view: AttemptView) -> TaskStatus | None:
    """A hold, landed, or abandoned: the statuses that no other rule overrides."""
    if view.next in ("hold", "on_hold"):
        return TaskStatus(Status.HELD, view.hold.reason if view.hold is not None else view.hold_due)
    if view.next == "landed":
        return TaskStatus(Status.LANDED)
    return TaskStatus(Status.ABANDONED, view.next) if view.release is not None and view.release.abandoned else None


def _moving(view: AttemptView, policy: LandPolicy) -> TaskStatus | None:
    if view.next == "land":
        known = policy if policy.mode is not LandMode.AUTO or waiting_for_land(view) else LandPolicy(commit=policy.commit)
        state = decision(known, running=landing(view.land),
                         delivered=view.land is not None and view.land.row.delivery is not None)
        return TaskStatus(Status.LANDING if landing(view.land) else Status.WAITING_FOR_LAND,
                          landing=state, policy_commit=policy.commit)
    if view.next == "wait":
        return TaskStatus(Status.CHECKING if view.step == "check" else Status.RUNNING)
    return TaskStatus(Status.SETTLING, view.next) if view.next in SETTLING else None


def task_status(view: AttemptView, admission: Admission | None = None, policy: LandPolicy | None = None) -> TaskStatus:
    """The status of the task whose current view this is. Without `admission` a task that waits for a new attempt is `ABANDONED`
    (or held): the reader does not know the approval label."""
    if admission is not None and restartable(view, admission):
        return TaskStatus(Status.QUEUED, view.next, admission.wait)
    found = _stopped(view) or _moving(view, view.policy if policy is None else policy)
    if found is not None:
        return found
    if view.next == "done" and succeeded(view.result):
        return TaskStatus(Status.FINISHED)
    reason = view.result.reason if view.next == "done" else view.next
    return TaskStatus(Status.STUCK, f"failed:{reason}" if view.next == "done" and not reason.startswith("failed:") else reason)


def in_flight(views: tuple[AttemptView, ...]) -> frozenset[str]:
    """The tasks with work that goes on without the person (`IN_FLIGHT` statuses)."""
    return frozenset(each.task_id for each in views if task_status(each).status in IN_FLIGHT)


def words(found: TaskStatus) -> str:
    """The status in plain words, for a list row, a card and a round's skip line."""
    if found.landing is not None:
        return land_words(found.landing)
    reason = "" if found.reason is None else f" ({found.reason})"
    waits: Mapping[Wait, str] = {
        Wait.READY: "queued to start: the next round starts it", Wait.NO_FREE_SLOT: "queued to start: no free slot",
        Wait.SLOT_FOR_LAND: "queued to start: the last free slot is kept for a land",
        Wait.MAX_RUNNING: "queued to start: the in-flight bound is reached",
        Wait.SKIPPED: f"queued to start: skipped by rule {found.skip}",
    }
    if found.status is Status.QUEUED and found.wait is not None:
        return waits[found.wait]
    fixed = {
        Status.RUNNING: "running", Status.CHECKING: "checking", Status.SETTLING: "settling", Status.LANDED: "landed",
        Status.WAITING_FOR_LAND: "waiting for land", Status.LANDING: "landing", Status.FINISHED: "finished",
        Status.ABANDONED: "abandoned: a person gave the attempt up; a round restarts it once the task carries the approval label",
        Status.HELD: f"held{reason}: waits for a person", Status.STUCK: f"needs a person{reason}",
    }
    return fixed[found.status]
