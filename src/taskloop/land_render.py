"""The human rendering of `tl step land`'s answers (tl-8bh9.14.8 sections 7, 8, 10, 16): a land delivered and closed
(`Landed`), a candidate given up (`Withdrawn`), the land summary (`LandSummary`), and a refusal or unknown with its land
guide (`land_guide`, then `step_guide.GUIDE`). Fixed words around the operation's values; every stored or outside text is
one printable line (`land_summary.one_line`). Nothing here decides, reads or writes; `land_data` is the one JSON shape."""

from typing import Final

from taskloop.land import Landed
from taskloop.land_close import NOT_SYNCED
from taskloop.land_guide import LAND_GUIDE
from taskloop.land_push import Withdrawn
from taskloop.land_store import LandRow
from taskloop.land_summary import LandSummary, gate_lines, lines, one_line
from taskloop.operations import Failed
from taskloop.step_guide import GUIDE

COMMAND: Final = "tl step land"
HOW: Final = {
    "pushed": "S pushed to origin's main by this land",
    "already_pushed": "origin's main was found to hold S: recorded, not pushed again",
    "no_change": "origin's main already held X's changes: recorded with no push",
    "delivered": "S was on origin's main before this call: only the close was left",
    "already_landed": "landed before this call: nothing called",
}


def _candidate(row: LandRow) -> str:
    validated = {"same_tree": "same tree as X, no checks", "no_change": "no change, no checks", "passed": "checks passed on S"}
    return (f"Candidate {row.number} ({row.key.attempt_id}): S {row.commit} onto origin main at {row.origin}; "
            f"{validated.get(row.validation or '', row.validation or 'pending')}")


def landed_lines(found: Landed) -> list[str]:
    """The land's end: what this call did, the candidate, origin's main, the close and the release it retried."""
    row = found.row
    lines_ = [f"{found.how}: {row.task_id} (backlog {row.backlog}) on origin main; {HOW[found.how]}", _candidate(row)]
    lines_ += [f"Pushed: origin main at {row.remote_head}"] if row.delivery == "pushed" else []
    lines_ += [] if found.gate is None else ["Gate changes accepted:", *gate_lines(found.gate)[:-1]]
    lines_ += [] if found.release is None else [f"Release: {one_line(found.release, 200)}"]
    if row.close is None:
        return [*lines_, "Closed: not yet: rerun `tl step land` to close the task (the code is on main)."]
    return [*lines_, f"Closed: {row.close}", NOT_SYNCED, "Next: `git pull --ff-only` in your checkout."]


def land_lines(command: str, found: Landed | Withdrawn | LandSummary | Failed) -> list[str]:
    """`tl step land`'s answer, or a refusal of it."""
    if isinstance(found, Landed):
        return landed_lines(found)
    if isinstance(found, Failed):
        return failed_lines(command, found)
    return withdrawn_lines(found) if isinstance(found, Withdrawn) else summary_lines(found)


def withdrawn_lines(found: Withdrawn) -> list[str]:
    row = found.row
    return [f"withdrawn: {row.task_id} (backlog {row.backlog}); candidate {row.number} ({row.key.attempt_id}) superseded, S "
            f"{row.commit} was not on origin's main", "`tl step release --abandon` may now abandon the task; `tl step land` makes "
            "a new candidate."]


def summary_lines(found: LandSummary) -> list[str]:
    return [*lines(found), "Nothing was recorded, reserved, pushed or closed: `tl step land TASK` lands it."]


def failed_lines(command: str, found: Failed) -> list[str]:
    """A refusal (exit 1) or unknown (exit 3) of `tl step land`: its word, its detail as printable lines, then each guide
    once: the reason, its first word and the kind, each from the land's table before the step commands'."""
    detail = [one_line(line, 2000) for line in found.detail.split("\n") if one_line(line, 2000)]
    keys = dict.fromkeys((found.reason, found.reason.split(":")[0], found.kind))
    guides = dict.fromkeys(text for key in keys if (text := LAND_GUIDE.get(key) or GUIDE.get(key)) is not None)
    return [f"{command}: {found.word}", *detail, *guides]
