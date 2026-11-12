"""The one JSON shape of every step command result (`as_data`): what the CLI prints with `--json` and a dashboard renders.
It never holds a dispatch token, a remote URL or Git output."""

from taskloop.attempt_reads import PublishedRow, ReleaseRow
from taskloop.attempt_result import succeeded
from taskloop.attempt_status import AttemptView, Listed, Shown
from taskloop.attempt_types import EntryIdentity
from taskloop.check_status import ChecksView
from taskloop.checks import differs
from taskloop.hold_store import HoldRow
from taskloop.land import Landed
from taskloop.land_data import land_data, view_data
from taskloop.land_push import Withdrawn
from taskloop.land_summary import LandSummary
from taskloop.machine_config import Loaded
from taskloop.operations import (
    Adoption,
    Ended,
    Failed,
    PublishedTask,
    ReleasedTask,
    Round,
    Started,
    VerifiedTask,
)
from taskloop.publish import publish_word
from taskloop.slot_release import Released, release_word
from taskloop.slots import Adopted, NotAdopted, SlotView

# every command result of the config, slot and step commands: rendered by `step_render.human`, shaped here, exit-coded by
# `exit_codes`
type StepResult = Started | Shown | Listed | VerifiedTask | ReleasedTask | PublishedTask | Adoption | Loaded | Round | Ended | Failed
type Result = StepResult | Landed | Withdrawn | LandSummary


def _entry_data(entry: EntryIdentity | None) -> dict[str, object] | None:
    return None if entry is None else {"pid": entry[0], "start": entry[1], "boot": entry[2]}


def _show_data(each: AttemptView) -> dict[str, object]:
    return {
        "backlog": each.backlog, "task": each.task_id, "step": each.step, "attempt_id": each.attempt_id, "slot": each.slot,
        "phase": each.phase,
        "entry": each.entry, "result": {"status": each.result.status, "reason": each.result.reason},
        "succeeded": succeeded(each.result), "deadline_passed": each.deadline_passed, "next": each.next,
        "entry_process": _entry_data(each.entry_process),
        "worker": None if each.worker is None else {"pid": each.worker[0], "pgid": each.worker[1]},
        "leftovers": list(each.leftovers), "number": each.number, "previous_attempt_id": each.previous_attempt_id,
        "repeat_reason": each.repeat_reason, "earlier": [attempt_id for attempt_id, _reason in each.earlier],
        "last_entry": each.last_entry, "seq": each.seq, "release": _release_data(each.release),
        "published": _published_data(each.published), "checks": _checks_data(each.checks), "land": view_data(each.land),
        "label": each.label, "hold": _hold_data(each.hold), "hold_due": each.hold_due,
        "last_command": each.last_command,
    }


def _hold_data(row: HoldRow | None) -> dict[str, object] | None:
    """A hold's record (tl-8bh9.14.9 section 10): its reason, cause, the label it removes, when, and its phases."""
    if row is None:
        return None
    return {"reason": row.reason, "cause": row.cause_id, "label": row.label, "held_at": row.held_at, "labels": row.labels,
            "labelled_at": row.labelled_at, "commented_at": row.commented_at, "cleared_at": row.cleared_at}


def _checks_data(checks: ChecksView | None) -> dict[str, object] | None:
    """A checks attempt's own facts (tl-8bh9.14.6 section 9): X, the target and the required names, the profile digest,
    the counted refusals and its latest block's results (`log`: `tl step show` only)."""
    if checks is None:
        return None
    row, required = checks.row, dict(checks.row.required)
    logs = checks.logs or (None,) * len(checks.results)
    results = [{"name": each.name, "required": each.name in required, "conclusion": each.conclusion, "rc": each.rc,
                "block": each.block, "started_at": each.started_at, "ended_at": each.ended_at,
                "argv_differs": differs(row.required, each), "log": None if log is None else str(log)}
               for each, log in zip(checks.results, logs, strict=True)]
    return {"commit": row.commit, "target": row.target, "target_seen": row.target_seen, "required": list(required),
            "profile_digest": row.profile_digest, "refusal": row.refusal, "refusals": row.refusals, "results": results}


def _release_data(release: ReleaseRow | None) -> dict[str, object] | None:
    if release is None:
        return None
    return {"head": release.head, "released_at": release.released_at, "abandoned": release.abandoned, "claim": release.claim}


def _published_data(published: PublishedRow | None) -> dict[str, object] | None:
    if published is None:
        return None
    return {"commit": published.commit, "remote_head": published.remote_head, "published_at": published.published_at}


def _released_data(result: VerifiedTask | ReleasedTask | PublishedTask) -> dict[str, object]:
    if isinstance(result, PublishedTask):
        return _publish_data(result)
    if isinstance(result, VerifiedTask):
        return {"status": result.status, "backlog": result.backlog, "task": result.task_id, "attempt_id": result.attempt_id,
                "release": result.release, "published": result.published}
    found = result.result
    changed = (found.parked, found.reservation_removed) if isinstance(found, Released) else (None, False)
    status = release_word(found)
    return {"status": status, "backlog": result.backlog, "task": result.task_id, "attempt_id": result.attempt_id, "slot": found.slot,
            "parked": changed[0], "reservation_removed": changed[1], "claim": found.claim, "abandoned": found.abandoned,
            "checks": None if result.checks is None else _released_data(result.checks),
            "land": None if result.land is None else _released_data(result.land), "candidate": result.candidate}


def _publish_data(result: PublishedTask) -> dict[str, object]:
    found = result.result
    status = publish_word(found)
    return {"status": status, "backlog": result.backlog, "task": result.task_id, "attempt_id": result.attempt_id,
            "commit": found.commit, "remote_head": found.remote_head}


def _slot_data(each: SlotView | Adopted | NotAdopted) -> dict[str, object]:
    match each:
        case SlotView():
            return {"name": each.name, "path": str(each.path), "state": each.state, "reason": each.reason, "attempt_id": each.attempt_id}
        case Adopted():
            return {"name": each.name, "adopted": True, "reason": None, "path": str(each.path)}
        case NotAdopted():
            return {"name": each.name, "adopted": False, "reason": each.reason, "path": None if each.path is None else str(each.path)}


def as_data(result: Result, *, admission: bool = False) -> dict[str, object]:
    """`_step_data`'s shapes, and `tl step land`'s answers (`land_data`)."""
    if isinstance(result, Landed | Withdrawn | LandSummary):
        return land_data(result)
    return _step_data(result, admission=admission)


def _step_data(result: StepResult, *, admission: bool) -> dict[str, object]:
    """The one JSON shape per result (a refusal or unknown is `{"error": {kind, reason, message}}`, plus `claim_leaked`,
    `admitted` and `slots` for an admission's, `tl step start`); no dispatch token, no version field. An empty diagnostic
    or result text is null, as every other absent field."""
    match result:
        case Failed():
            error: dict[str, object] = {"kind": result.kind, "reason": result.reason, "message": result.detail or None}
            if admission:
                slots = [_slot_data(each) for each in result.slots]
                error |= {"claim_leaked": result.claim_leaked, "admitted": result.admitted, "slots": slots}
            return {"error": error}
        case Started():
            return {"status": result.status, "backlog": result.backlog, "task": result.task_id, "step": result.step,
                    "attempt_id": result.attempt_id,
                    "existing": result.existing, "entry_process": _entry_data(result.entry), "number": result.number,
                    "result": result.result or None}
        case Shown():
            setup = None if result.setup is None else {"run": result.setup.row.run, "conclusion": result.setup.row.conclusion,
                                                        "commit": result.setup.row.commit, "log": str(result.setup.log),
                                                        "attempt_id": result.setup.attempt_id}
            return _show_data(result.view) | {"directory": str(result.directory), "entry_log": str(result.entry_log), "setup": setup,
                                                   "failed_checks": _checks_data(result.failed)}
        case Listed() | Round() | Ended():
            return _rows_data(result)
        case VerifiedTask() | ReleasedTask() | PublishedTask():
            return _released_data(result)
        case Adoption() | Loaded():
            return _setup_data(result)


def rounds_data(backlog: str, every: int, log: str) -> dict[str, object]:
    """`tl step rounds`'s start, printed before the first round; its end is `as_data(Ended)`."""
    return {"status": "rounds", "backlog": backlog, "every": every, "log": log}


def _rows_data(result: Listed | Round | Ended) -> dict[str, object]:
    """`tl step list`: every current attempt; `tl step next`: each move in the order performed and `stopped`, the word that
    ended admission early, or null; `tl step rounds`: why the rounds ended."""
    if isinstance(result, Listed):
        return {"attempts": [_show_data(each) for each in result.attempts]}
    if isinstance(result, Ended):
        return {"status": "ended", "backlog": result.backlog, "reason": result.reason, "detail": result.detail or None}
    moves = [{"task": each.task_id, "action": each.action, "word": each.word, "attempt_id": each.attempt_id or None,
              "detail": each.detail or None} for each in result.moves]
    return {"status": "round", "backlog": result.backlog, "moves": moves, "stopped": result.stopped or None, "logged": result.logged}


def _setup_data(result: Adoption | Loaded) -> dict[str, object]:
    if isinstance(result, Adoption):
        return {"slots": [_slot_data(each) for each in result.slots]}
    settings = {
        key: {"value": each.value if isinstance(each.value, int) else str(each.value), "source": each.source}
        for key, each in result.settings.pairs()
    }
    return {"file": {"path": str(result.path), "exists": result.exists}, "settings": settings}
