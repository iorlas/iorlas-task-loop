"""The human rendering of every step, slot and config result: lines of fixed words around the operations' values. Nothing
here decides, reads or writes; `result_data.as_data` is the one JSON shape."""

from pathlib import Path

from taskloop.attempt_status import Listed, Shown
from taskloop.attempt_types import ATTEMPTS
from taskloop.hold_guide import hold_guide, pending_guide
from taskloop.land import Landed
from taskloop.land_guide import CANDIDATE_RELEASE, LAND_GUIDE
from taskloop.land_push import Withdrawn
from taskloop.land_render import COMMAND, land_lines
from taskloop.land_summary import LandSummary
from taskloop.machine_config import Loaded
from taskloop.operations import (
    UNCLAIMING,
    Adoption,
    Ended,
    Failed,
    Move,
    PublishedTask,
    ReleasedTask,
    Round,
    Started,
    VerifiedTask,
)
from taskloop.printable import block
from taskloop.publish import is_published, publish_word
from taskloop.result_data import Result, StepResult
from taskloop.show_render import last_command, show_lines
from taskloop.slot_release import Released, is_released, release_word
from taskloop.slots import Adopted
from taskloop.step_guide import GUIDE, HELD, PUBLISH, STEP_ONLY, discard, guide
from taskloop.tracker import leaked_claim


def human(command: str, result: Result, db: Path | None) -> list[str]:
    """`tl step land`'s answers and refusals are `land_render`'s; the rest (a land candidate's refused release too, with
    its own guide) `_step_lines`'."""
    if isinstance(result, Landed | Withdrawn | LandSummary) or (isinstance(result, Failed) and command == COMMAND):
        return land_lines(command, result)
    return _step_lines(command, result, db)


def _step_lines(command: str, result: StepResult, db: Path | None) -> list[str]:
    """`db` (the resolved factory.db) goes into the discard steps; None only when the config itself was refused."""
    stuck = [] if db is None else [discard(db)]
    match result:
        case Failed():
            lines = [f"{command}: {result.word}", *(block(result.detail).split("\n") if result.detail else [])]  # an echoed id is untrusted
            lines += [f"  {view.name} {view.state} {view.reason or view.attempt_id or ''} {view.path}" for view in result.slots]
            named = "`tl step release --abandon`" in result.detail  # the detail names the action (`HALF_DONE`, `UNCLAIMING`)
            lines += [] if named else _guides(result)
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
            abandoning = each.next == "release" and each.land is not None and each.land.row.superseded == "abandoned"
            told = guide(each.next, checks=each.checks is not None, land=each.land is not None)
            told = LAND_GUIDE["abandoning"] if abandoning else told
            told = told if ended is None or not ended.abandoned else GUIDE["abandoned"] if each.next == "start" else UNCLAIMING
            told = hold_guide(each) if each.next in ("hold", "on_hold") else told
            steps = [told, *(stuck if each.next.startswith("stuck:") else [])]
            left = [f"Unsettled: {each.leftovers[0]}", *(f"  {line}" for line in each.leftovers[1:])] if each.leftovers else []
            last = [] if each.last_entry is None else [f"Last entry result: {each.last_entry}"]
            return [*show_lines(result), *paths, *last, *left, f"Next: {each.next}", *steps]
        case Listed() | Round() | Ended():
            return _rows_lines(command, result, stuck)
        case VerifiedTask() | ReleasedTask() | PublishedTask():
            return _released_lines(result)
        case Adoption() | Loaded():
            return _setup_lines(result)


def _guides(result: Failed) -> list[str]:
    """The guide of the kind and the reason: a land candidate's release (`result.land`) has its own words first."""
    found = [CANDIDATE_RELEASE.get(each) if result.land else None for each in (result.kind, result.reason)]
    return [text or guide(each, checks=result.checks) for each, text in zip((result.kind, result.reason), found, strict=True)
            if text is not None or each in GUIDE]


def _path(move: Move) -> list[str]:
    """An `unusable` slot's path, under its line (the round log holds fixed words only)."""
    return [f"  {move.detail}"] if move.word.startswith("unusable:") and move.detail else []


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
        rows = [f"{a.task_id}\t{a.backlog}\t{a.step}\t{a.number}{'' if a.checks else f'/{ATTEMPTS}'}\t{a.slot}\t{a.phase}\t{a.entry}\t"
                f"{a.result.status} {a.result.reason}\t{a.next}\t{last_command(a) or '-'}" for a in attempts]
        kinds = dict.fromkeys((a.next, a.checks is not None) for a in attempts if a.next.startswith("stuck:") or a.next == "hold")
        steps = [f"{kind}: {guide(kind, checks=checks)}" for kind, checks in kinds]
        steps += stuck if any(kind.startswith("stuck:") for kind, _checks in kinds) else []
        return ["task\tbacklog\tstep\tattempt\tslot\tphase\tentry\tresult\tnext\tlast command", *rows, *steps]
    width = max((len(each.task_id) for each in result.moves), default=0)
    lines = [f"{each.task_id:<{width}}  {each.action:<8} {each.word} {each.attempt_id}".rstrip() for each in result.moves]
    lines = [line for each, text in zip(result.moves, lines, strict=True) for line in (text, *_path(each))]
    lines += [f"Stopped: {result.stopped}"] if result.stopped else []
    lines += [] if result.moves or result.stopped else [f"Nothing to do in backlog {result.backlog}."]
    words = [("abandoned_skip" if each.word == "abandoned" else each.word) for each in result.moves
             if each.action in ("report", "skip", "advance")]
    pending = dict.fromkeys(pending_guide(each.word) for each in result.moves if each.action == "hold" and each.word.startswith("pending "))
    keys = dict.fromkeys(key for word in [*words, result.stopped] for key in (word, word.split(":")[0]) if key in GUIDE)
    leaked = [f"claim_leaked: {leaked_claim(each.task_id)}" for each in result.moves if each.word == "claim_leaked"]
    return lines + [f"{key}: {GUIDE[key]}" for key in keys] + [f"hold: {each}" for each in pending] + leaked


def _released_lines(result: VerifiedTask | ReleasedTask | PublishedTask) -> list[str]:
    """A verdict with the release and the publication that followed it; a release with each change on its own line (an
    abandon's land candidate first, then its checks attempt); a publication."""
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
    first = [] if result.land is None else _released_lines(result.land)
    first += [] if result.checks is None else _released_lines(result.checks)
    what = f"{'land candidate' if result.candidate else 'attempt'} {result.attempt_id} for {task} (backlog {result.backlog})"
    if not isinstance(found, Released):
        claim = f"Claim: {found.claim}{'; abandoned' if found.abandoned else ''}"
        return [*first, f"{release_word(found)}: {what}; nothing changed", claim]
    lines = [*first, f"{release_word(found)}: {what}"]
    lines += [f"Slot {found.slot} parked at {found.parked}" if found.parked else f"Slot {found.slot}: no Git write"]
    lines += [f"Reservation of {found.slot} removed"] if found.reservation_removed else []
    claims = {"kept": "Claim kept", "unclaimed": "Claim returned to the tracker",
              "not_held": f"Claim not held by taskloop (reverted, or another actor's): check `bd show {task}`"}
    lines += [claims[found.claim]]
    fresh = found.abandoned and found.claim != "kept"  # a checks attempt's abandon keeps the claim: its implement attempt's follows
    return lines + ([f"Abandoned: `tl step start {task}` admits a fresh attempt"] if fresh else [])


SLOT_COUNT_NOTE = "slot_count only adds slots (`tl slot adopt`); lowering it retires none: rounds use every slot adopted in factory.db."


def _setup_lines(result: Adoption | Loaded) -> list[str]:
    if isinstance(result, Adoption):
        slots = result.slots
        lines = [f"{each.name} {'adopted' if isinstance(each, Adopted) else each.reason} {each.path or ''}".rstrip() for each in slots]
        missing = any(not isinstance(each, Adopted) and each.reason == "not_listed" for each in slots)
        attached = any(not isinstance(each, Adopted) and each.reason == "attached" for each in slots)
        hints = ["Make each not_listed slot with `git worktree add --detach <path>`, then adopt again."] if missing else []
        return lines + hints + (["Run `git switch --detach` in a slot left on a task branch, then adopt again."] if attached else [])
    lines = [f"Config file: {result.path} ({'exists' if result.exists else 'missing: built-in defaults'})"]
    lines += [f"{key} = {each.value} ({each.source})" for key, each in result.settings.pairs()]
    return [*lines, SLOT_COUNT_NOTE]
