"""Deterministic execution facts for public JSON contract examples; no runtime IO."""

from dataclasses import replace
from pathlib import Path

from git_porcelain import Change
from hold_fixtures import event

from taskloop.agents.stop_models import AgentStop, Identity, StopCause, StopPhase, StopProof, Survivor
from taskloop.attempt_reads import PublishedRow, ReleaseRow
from taskloop.attempt_result import CommittedStatus
from taskloop.attempt_status import AttemptView, Listed, SetupShown, Shown
from taskloop.attempt_types import AttemptKey, AttemptResult
from taskloop.check_status import ChecksView
from taskloop.check_store import ChecksRow, ResultRow
from taskloop.command_conclusion import CommandConclusion
from taskloop.hold_store import HoldRow
from taskloop.land import Landed
from taskloop.land_gate import Changed, Gate, Weakened
from taskloop.land_push import Withdrawn
from taskloop.land_status import LandView
from taskloop.land_store import LandRow
from taskloop.land_summary import LandSummary
from taskloop.machine_config import Loaded, defaults
from taskloop.operations import Adoption, CommittedTask, Ended, Failed, Move, PublishedTask, ReleasedTask, Round, Started
from taskloop.profile import Check
from taskloop.publish import BranchPublished
from taskloop.result_data import Result
from taskloop.setup_store import SetupRow, SetupSample
from taskloop.setup_timing import SetupTimingReport
from taskloop.slot_release import AlreadyReleased, Released
from taskloop.slots import Adopted, NotAdopted, SlotView
from taskloop.task_event_cause import ChecksCause, FailedCheck

PATH = Path("/snapshot")
KEY = AttemptKey("attempt", "private-token", 1)
ENTRY = (7, "process-start", "boot")
CHECK = Check("test", ("just", "test"), 60)
LOADED = Loaded(PATH / "config.toml", False, defaults(PATH))
START_FLAGS = ["--tracker-root", "/tracker", "--checkout", str(PATH), "--minutes", "30"]
ROUND_FLAGS = [*START_FLAGS, "--label", "approved"]


def land_row() -> LandRow:
    return LandRow(
        KEY, "checks", 1, "origin", "commit", False, (("test", "argv-digest"),), "s1", "head", 100.0, "digest", ENTRY,
        "passed", None, 10.0, 11.0, "parked", None, None, "pushed", 12.0, "remote", "closed", 13.0, 1,
        "tasks", "tl-1", "repo", "/tracker", "checked", False, 8.0, None, 9.0, 10.0, 11.0, 12.0,
    )


def shown_cases() -> tuple[Shown, Shown]:
    view = AttemptView("tasks", "tl-1", "implement", "attempt", "s1", "captured", "gone",
                       AttemptResult("pending", "commit"), False, "commit")
    checks = ChecksView(
        ChecksRow(KEY, "agent", 1, "s1", "head", "main", "origin", (("test", "argv-digest"),), "digest", 100.0,
                  ENTRY, "concluded", 1, None, 0, "passed", None, 11.0, 12.0, "parked", False,
                  "tasks", "tl-1", "repo", "/tracker", "commit"),
        (ResultRow(1, 1, "test", "digest", 60, None, 10.0, 11.0, 0, CommandConclusion.PASSED),),
        (PATH / "check.log",),
    )
    stop = AgentStop(attempt_id="attempt", dispatch_token="private-token", generation=1,
                     entry=Identity(pid=7, pgid=7, start="process-start", boot="boot"),
                     agent=Identity(pid=8, pgid=8, start="agent-start", boot="boot"),
                     cause=StopCause.DEADLINE, requested_signal=15, requested_at=10.0, trigger_signal=2,
                     phase=StopPhase.OBSERVED_GONE, reported_at=11.0, observed_gone_at=12.0,
                     proof=StopProof(term_attempted=True, term_delivered=True, kill_attempted=True, kill_delivered=True,
                                     survivors=(Survivor(pid=9, start="survivor-start"),), error=False))
    populated = replace(
        view, entry_process=ENTRY, worker=(8, 8), leftovers=("uncommitted",), number=2, previous_attempt_id="previous",
        repeat_reason="uncommitted", earlier=(("previous", "uncommitted"),), last_entry="gone", seq=2,
        release=ReleaseRow("head", 12.0, "unclaimed"), published=PublishedRow("commit", "remote", 13.0), checks=checks,
        land=LandView(land_row(), checks.results, "gone", checks.logs), label="approved",
        hold=HoldRow(event=event(ChecksCause(check=FailedCheck(name="test", conclusion=CommandConclusion.FAILED)),
                                 attempt_id="attempt", cause_id="checks"),
                     held_at=14.0, labels="moved", labelled_at=15.0, commenting_at=16.0, commented_at=17.0,
                     cleared_at=None, rev=1, backlog="tasks", task_id="tl-1", tracker_root="/tracker", label="approved"),
        last_command=0, source_checks_id="checks", hold_due="checks", stop=stop,
        result=AttemptResult("refused", "checks", explanation="A check failed"),
    )
    return (
        Shown(view, PATH, PATH / "entry.log", PATH / "events.jsonl"),
        Shown(populated, PATH, PATH / "entry.log", PATH / "events.jsonl",
              SetupShown(SetupRow(1, "commit", "digest", 0, None, CommandConclusion.PASSED, 10.0, 11.0),
                         PATH / "setup.log", "setup"), checks),
    )


def step_cases() -> dict[str, tuple[list[str], Result]]:
    empty, full = shown_cases()
    cases: dict[str, tuple[list[str], Result]] = {
        "config": (["config", "show"], LOADED),
        "slots": (["slot", "adopt", str(PATH)], Adoption((Adopted("s1", PATH), NotAdopted("s2", "inside_checkout", PATH)))),
        "show.empty": (["attempt", "show", "tl-1", "--backlog", "tasks"], empty),
        "show.full": (["attempt", "show", "tl-1", "--backlog", "tasks"], full),
        "list.empty": (["attempt", "list"], Listed(())),
        "list.full": (["attempt", "list"], Listed((full.view,))),
        "round.empty": (["rounds", "once", "--backlog", "tasks", *ROUND_FLAGS], Round("tasks", ())),
        "round.full": (["rounds", "once", "--backlog", "tasks", *ROUND_FLAGS],
                       Round("tasks", (Move("tl-1", "start", "started", "attempt", "detail"),), "capacity", False)),
        "committed": (["step", "commit", "tl-1", "--backlog", "tasks"],
                     CommittedTask(
                         CommittedStatus.COMMITTED, "tasks", "tl-1", "attempt", "released", "published")),
        "published": (["step", "publish", "tl-1", "--backlog", "tasks"],
                      PublishedTask("tasks", "tl-1", "attempt", BranchPublished("commit", "remote"))),
        "setup-times": (["attempt", "setup-times", "--backlog", "tasks"],
                        SetupTimingReport(backlog="tasks", rows=(), sample_count=0)),
        "setup-times.full": (["attempt", "setup-times", "--backlog", "tasks"],
                             SetupTimingReport(backlog="tasks", rows=(SetupSample(
                                 attempt_id="attempt", task_id="tl-1", repo_id="repo", run=1,
                                 started_at=10.0, ended_at=11.0, conclusion=CommandConclusion.PASSED),), sample_count=1)),
        "start.empty": (["step", "start", "tl-1", "--backlog", "tasks", *START_FLAGS],
                        Started("started", "tasks", "tl-1", "attempt", False)),
    }
    for status in ("started", "relaunched", "already_running", "already_dispatched", "repeated"):
        cases[f"start.{status}"] = (["step", "start", "tl-1", "--backlog", "tasks", *START_FLAGS],
                                   Started(status, "tasks", "tl-1", "attempt", False, ENTRY, 2, "result", "implement"))
    for kind in ("refused", "unavailable"):
        for operation in ("start", "show"):
            cases[f"{operation}.{kind}"] = (
                [("attempt" if operation == "show" else "step"), operation, "tl-1", "--backlog", "tasks",
                 *(START_FLAGS if operation == "start" else [])],
                Failed(kind, "choices", "Operation refused", True, (SlotView("s1", PATH, "held", attempt_id="attempt"),), True),
            )
    for reason in ("interrupted", "drained", "unavailable"):
        cases[f"rounds.{reason}"] = (["rounds", "start", "--backlog", "tasks", *ROUND_FLAGS], Ended("tasks", reason, "Rounds ended"))
    released = ReleasedTask("tasks", "tl-1", "attempt", Released("s1", "parked", True, "unclaimed", False))
    for name, result in {"released": released, "released.nested": replace(released, checks=released, land=released, candidate=True),
                         "released.already": replace(released, result=AlreadyReleased("s1", "kept", True))}.items():
        cases[name] = (["step", "release", "tl-1", "--backlog", "tasks"], result)
    for name, result in land_cases().items():
        cases[name] = (["land", "run", "tl-1", "--backlog", "tasks", "--checkout", str(PATH)], result)
    return cases


def land_cases() -> dict[str, Result]:
    row = land_row()
    changed = Changed("test", CHECK, None)
    gate = Gate((Change("pyproject.toml", "M", 1, 1),), (changed,), ((("just", "install"),), ()), (("test",), ()),
                ("pyproject.toml",), (Weakened("tests/test.py", "removed test"),))
    return {
        "land.empty": Landed(row, "pushed"),
        "land.full": Landed(row, "already_pushed", "released", gate),
        "land.withdrawn": Withdrawn(row),
        "land.summary": LandSummary("checks", "passed", "main", "commit", (("test", CommandConclusion.PASSED),),
                                    "origin", ("added",), ("removed",), (changed,), gate, "base", "same_tree", (), "Ready"),
    }
