"""The human rendering of every step, slot and config result: lines of fixed words around the operations' values. Nothing
here decides, reads or writes; `result_data.as_data` is the one JSON shape."""

from datetime import UTC, datetime
from pathlib import Path

from taskloop.attempt import succeeded
from taskloop.attempt_status import AttemptView, Listed, SetupShown, Shown
from taskloop.attempt_types import ATTEMPTS
from taskloop.machine_config import Loaded
from taskloop.operations import (
    UNCLAIMING,
    Adoption,
    Ended,
    Failed,
    PublishedTask,
    ReleasedTask,
    Round,
    Started,
    VerifiedTask,
)
from taskloop.publish import is_published, publish_word
from taskloop.result_data import Result
from taskloop.slot_release import Released, is_released, release_word
from taskloop.slots import Adopted
from taskloop.step_guide import GUIDE, HELD, PUBLISH, STEP_ONLY, discard
from taskloop.tracker import leaked_claim


def _show_lines(each: AttemptView) -> list[str]:
    entry = "" if each.entry_process is None else f" (pid {each.entry_process[0]}, started {each.entry_process[1]})"
    # the stored registration only: the agent may have exited long ago, so it is never shown as running
    worker = "none" if each.worker is None else f"last known pid {each.worker[0]}, process group {each.worker[1]} (not checked)"
    repeats = "" if each.previous_attempt_id is None else f"; repeats {each.previous_attempt_id}, {each.repeat_reason}"
    ended = each.release
    released = [] if ended is None else [
        f"Released: {datetime.fromtimestamp(ended.released_at, UTC):%Y-%m-%d %H:%M:%S} UTC, slot parked at {ended.head}; "
        f"claim {ended.claim}{'; abandoned' if ended.abandoned else ''}"
    ]
    found = each.published
    published = [] if found is None else [
        f"Published: task/{each.task_id} at {found.commit} on origin, {datetime.fromtimestamp(found.published_at, UTC):%Y-%m-%d %H:%M:%S}"
        " UTC"
    ]
    return [
        f"Task: {each.task_id} (backlog {each.backlog})", f"Step: {each.step}",
        f"Attempt: {each.attempt_id} ({each.number} of at most {ATTEMPTS}{repeats})",
        *(f"Earlier: {attempt_id} " + (why if why in ("abandoned", "advanced") else f"repeated ({why})")
          for attempt_id, why in each.earlier),
        f"Slot: {each.slot}", f"Phase: {each.phase}",
        f"Entry: {each.entry}{entry}", f"Worker: {worker}", f"Result: {each.result.status} {each.result.reason}".rstrip(),
        f"Succeeded: {'yes' if succeeded(each.result) else 'no'}", f"Deadline passed: {'yes' if each.deadline_passed else 'no'}",
        *released, *published,
    ]


def _setup_line(found: SetupShown | None) -> str:
    """The latest setup run's conclusion from factory.db (`unfinished` while it has none) and its log's path."""
    if found is None:
        return "Setup: none"
    row, whose = found.row, "" if found.attempt_id is None else f" (attempt {found.attempt_id}'s, which this repeat keeps)"
    return f"Setup: run {row.run} {row.conclusion or 'unfinished'} at {row.commit}{whose}; log {found.log}"


def human(command: str, result: Result, db: Path | None) -> list[str]:
    """`db` (the resolved factory.db) goes into the discard steps; None only when the config itself was refused."""
    stuck = [] if db is None else [discard(db)]
    match result:
        case Failed(kind=kind, reason=reason):
            lines = [f"{command}: {result.word}", *([result.detail] if result.detail else [])]
            lines += [f"  {view.name} {view.state} {view.reason or view.attempt_id or ''} {view.path}" for view in result.slots]
            lines += [GUIDE[each] for each in (kind, reason) if each in GUIDE]
            return lines + ([f"Admitted: {HELD} Re-run `tl step start` to retry the launch."] if result.admitted else [])
        case Started():
            entry = "" if result.entry is None else f"; entry pid {result.entry[0]}"
            lines = [f"{result.status}: attempt {result.attempt_id} for {result.task_id} (backlog {result.backlog}){entry}"]
            lines += [f"Result: {result.result}"] if result.result else []
            if result.number is not None:
                stand = f"attempt {result.number - 1}'s choices stand; deadline from --minutes"
                lines += [f"attempt {result.number} of at most {ATTEMPTS}; {stand}"]
            lines += ["existing attempt; its admitted choices stand"] if result.existing else [HELD]
            return [*lines, f"Step commands ({STEP_ONLY}). Follow it with `tl step show {result.task_id} --backlog {result.backlog}`."]
        case Shown(view=each):
            paths = [f"Directory: {result.directory}", f"Entry log: {result.entry_log}"]
            ended = each.release
            guide = GUIDE[each.next] if ended is None or not ended.abandoned else GUIDE["abandoned"] if each.next == "start" else UNCLAIMING
            steps = [guide, *(stuck if each.next.startswith("stuck:") else [])]
            left = [f"Unsettled: {each.leftovers[0]}", *(f"  {line}" for line in each.leftovers[1:])] if each.leftovers else []
            last = [] if each.last_entry is None else [f"Last entry result: {each.last_entry}"]
            return [*_show_lines(each), _setup_line(result.setup), *paths, *last, *left, f"Next: {each.next}", *steps]
        case Listed() | Round() | Ended():
            return _rows_lines(command, result, stuck)
        case VerifiedTask() | ReleasedTask() | PublishedTask():
            return _released_lines(result)
        case Adoption() | Loaded():
            return _setup_lines(result)


def _rows_lines(command: str, result: Listed | Round | Ended, stuck: list[str]) -> list[str]:
    """`tl step list`: one row per task. `tl step next`: one line per move as performed, `Stopped:` when admission ended
    early, then the guide of each distinct reported, skipped or stopping word once. `tl step rounds`: why it ended."""
    if isinstance(result, Ended):
        ended = {"interrupted": "Rounds stopped: interrupted. Launched steps keep running; `tl step rounds` again continues them.",
                 "abrupt": "Stopped at once."}
        if result.reason in ended:
            return [ended[result.reason]]
        return [f"{command}: {result.reason}", *([result.detail] if result.detail else []),
                *(GUIDE[each] for each in result.reason.split(":") if each in GUIDE)]
    if isinstance(result, Listed):
        attempts = result.attempts
        rows = [f"{a.task_id}\t{a.backlog}\t{a.step}\t{a.number}/{ATTEMPTS}\t{a.slot}\t{a.phase}\t{a.entry}\t"
                f"{a.result.status} {a.result.reason}\t{a.next}" for a in attempts]
        kinds = dict.fromkeys(a.next for a in attempts if a.next.startswith("stuck:"))
        steps = [f"{kind}: {GUIDE[kind]}" for kind in kinds] + (stuck if kinds else [])
        return ["task\tbacklog\tstep\tattempt\tslot\tphase\tentry\tresult\tnext", *rows, *steps]
    width = max((len(each.task_id) for each in result.moves), default=0)
    lines = [f"{each.task_id:<{width}}  {each.action:<8} {each.word} {each.attempt_id}".rstrip() for each in result.moves]
    lines += [f"Stopped: {result.stopped}"] if result.stopped else []
    lines += [] if result.moves or result.stopped else [f"Nothing to do in backlog {result.backlog}."]
    words = [("abandoned_skip" if each.word == "abandoned" else each.word) for each in result.moves
             if each.action in ("report", "skip", "advance")]
    keys = dict.fromkeys(key for word in [*words, result.stopped] for key in (word, word.split(":")[0]) if key in GUIDE)
    leaked = [f"claim_leaked: {leaked_claim(each.task_id)}" for each in result.moves if each.word == "claim_leaked"]
    return lines + [f"{key}: {GUIDE[key]}" for key in keys] + leaked


def _released_lines(result: VerifiedTask | ReleasedTask | PublishedTask) -> list[str]:
    """A verdict with the release and the publication that followed it; a release with each change on its own line; a
    publication."""
    if isinstance(result, PublishedTask):
        found = result.result
        done = publish_word(found)
        return [f"{done}: task/{result.task_id} at {found.commit} on origin (attempt {result.attempt_id}, backlog {result.backlog})",
                *(["Nothing changed: it was published before."] if done == "already_published" else [])]
    if isinstance(result, VerifiedTask):
        held = [f"Release: {result.release}"] + ([] if is_released(result.release) else [GUIDE["release"]])
        held += [f"Publish: {result.published}"] + ([] if is_published(result.published) else [PUBLISH])
        return [f"{result.status}: attempt {result.attempt_id} for {result.task_id} (backlog {result.backlog})", *held]
    found, task = result.result, result.task_id
    if not isinstance(found, Released):
        return [f"{release_word(found)}: attempt {result.attempt_id} for {task} (backlog {result.backlog}); nothing changed",
                f"Claim: {found.claim}{'; abandoned' if found.abandoned else ''}"]
    lines = [f"{release_word(found)}: attempt {result.attempt_id} for {task} (backlog {result.backlog})"]
    lines += [f"Slot {found.slot} parked at {found.parked}" if found.parked else f"Slot {found.slot}: no Git write"]
    lines += [f"Reservation of {found.slot} removed"] if found.reservation_removed else []
    claims = {"kept": "Claim kept", "unclaimed": "Claim returned to the tracker",
              "not_held": f"Claim not held by taskloop (reverted, or another actor's): check `bd show {task}`"}
    lines += [claims[found.claim]]
    return lines + ([f"Abandoned: `tl step start {task}` admits a fresh attempt"] if found.abandoned else [])


def _setup_lines(result: Adoption | Loaded) -> list[str]:
    if isinstance(result, Adoption):
        slots = result.slots
        lines = [f"{each.name} {'adopted' if isinstance(each, Adopted) else each.reason} {each.path or ''}".rstrip() for each in slots]
        missing = any(not isinstance(each, Adopted) and each.reason == "not_listed" for each in slots)
        attached = any(not isinstance(each, Adopted) and each.reason == "attached" for each in slots)
        hints = ["Make each not_listed slot with `git worktree add --detach <path>`, then adopt again."] if missing else []
        return lines + hints + (["Run `git switch --detach` in a slot left on a task branch, then adopt again."] if attached else [])
    lines = [f"Config file: {result.path} ({'exists' if result.exists else 'missing: built-in defaults'})"]
    return lines + [f"{key} = {each.value} ({each.source})" for key, each in result.settings.pairs()]
