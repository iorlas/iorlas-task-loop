"""What a hold's cause is and the one right next step for it (tl-8bh9.14.56), by the reason word the hold stored. Fixed
English; the deadline is the only value filled in. `fix` None means an owner's answer fixes the cause (edit the task, then
add its label back); a text names the step that does, after which the label is added back. Text only; the comment
(`hold_text`) and the answer guide (`hold_guide`) place it."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from taskloop.attempt_types import MiB, StepRules

EVIDENCE = "its `stdout.txt`, `stderr.txt` and `diagnostics.txt` in the evidence directory"
PLAN_RULES = {
    "plan_missing": "`plan.md` is absent from the commit (an `unchanged` answer needs an existing plan)",
    "plan_encoding": "`plan.md` is not valid UTF-8 text",
    "plan_empty": "`plan.md` is empty or only whitespace",
    "plan_size": f"`plan.md` is over the {StepRules('').file_cap // MiB} MiB limit",
}
STUCK = {
    "expired_admitted": "The attempt's deadline passed before its entry started",
    "entry_lost": "The attempt's entry process ended without recording a result",
    "uncollected": "The attempt's result could not be read back in full",
    "conflict": "The attempt's stored session facts conflict",
    "setup_failed": "The slot's setup command failed",
}


@dataclass(frozen=True)
class Cause:
    what: str
    fix: str | None = None


def _at(deadline: float | None) -> str:
    return "" if deadline is None else f" ({datetime.fromtimestamp(deadline, UTC):%Y-%m-%d %H:%M:%S} UTC)"


NO_EDIT = "Nothing in the task needs editing"
EXACT = {
    "run:vendor_blip": Cause(
        "The agent CLI failed with an error the factory cannot tell from a blip; often `--model` or `--effort` is not offered to "
        f"the account. The vendor's message is in {EVIDENCE}.",
        "Correct `--model` or `--effort` of the rounds if it says so (editing the task does not help)"),
    "needs_owner": Cause("The agent needs a decision only the owner can give (its explanation is quoted above)."),
    "incomplete": Cause("The agent stopped without finishing (its explanation is quoted above)."),
}


def _run(rest: str) -> Cause:
    return Cause(f"The agent run failed ({rest}); the vendor's message is in {EVIDENCE}.",
                 "Clear what it names (login, limit, setup), not the task")


def _answer(_rest: str) -> Cause:
    return Cause("The agent's answer did not fit the answer contract; `diagnostics.txt` in the evidence directory says how.", NO_EDIT)


def _rejected(rest: str) -> Cause:
    found = PLAN_RULES.get(rest, f"a listed file broke the commit rule `{rest}`")
    return Cause(f"The factory rejected the agent's work: {found}. The agent's own claim of success was not what was checked.",
                 NO_EDIT + ": the next attempt writes it again")


def _repeats(_rest: str) -> Cause:
    return Cause("The agent was asked to repeat its step until its files were settled and did not manage it "
                 "(`Left in the slot` names them).")


def _stuck(rest: str) -> Cause:
    if rest not in STUCK:
        return Cause(f"The attempt is stuck ({rest}).")
    return Cause(f"{STUCK[rest]}; the entry log in the evidence directory says more.", NO_EDIT)


BY_PREFIX: tuple[tuple[str, Callable[[str], Cause]], ...] = (  # the first prefix of the word that fits builds the cause from the rest
    ("run:", _run), ("answer:", _answer), ("rejected:", _rejected), ("repeats_exhausted", _repeats), ("stuck:", _stuck),
)


def cause(reason: str, deadline: float | None = None) -> Cause | None:
    """The cause line and fix of a hold's `reason`, None for a reason without one of its own (the owner's answer then)."""
    word = reason.removeprefix("failed:")
    if word == "run:timeout":
        return Cause(f"The agent did not finish before its deadline{_at(deadline)}.",
                     "Raise `--minutes` of the rounds that take it (editing the task does not help)")
    found = EXACT.get(word)
    return found or next((build(word.removeprefix(prefix)) for prefix, build in BY_PREFIX if word.startswith(prefix)), None)
