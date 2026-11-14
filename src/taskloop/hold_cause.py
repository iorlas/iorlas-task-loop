"""What a hold's cause is and the one right next step for it (tl-8bh9.14.56), by the reason word the hold stored. Fixed
English; the deadline is the only value filled in. `fix` None means an owner's answer fixes the cause (edit the task, then
add its label back); "" means the same attempt is worth a retry as it is; a text is an imperative clause naming the step that
fixes it (lower case, no final stop), after which the label is added back. Text only; the comment
(`hold_text`) and the answer guide (`hold_guide`) place it."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from taskloop.agents.stop_models import AgentStop
from taskloop.agents.stop_text import stop_text
from taskloop.attempt_types import MiB, StepRules

CHECK_GIT = "look at the task branch and the retained slot evidence"
EVIDENCE = "its `stdout.txt`, `stderr.txt` and `diagnostics.txt` in the evidence directory"
RULES = {  # the verdict rule words (`attempt_types.Rule`): what broke, and the fix ("" = retry as it is)
    "plan_missing": ("`plan.md` is absent from the commit (an `unchanged` answer needs an existing plan)", ""),
    "plan_encoding": ("`plan.md` is not valid UTF-8 text", ""),
    "plan_empty": ("`plan.md` is empty or only whitespace", ""),
    "plan_size": (f"`plan.md` is over the {StepRules('').file_cap // MiB} MiB limit", ""),
    "paths": ("a listed path is not allowed (outside the step's folder, a Git file, or too many paths)", ""),
    "mode": ("a listed file is not a plain, non-executable file", ""),
    "file_size": ("a listed file is over the size limit", ""),
    "commit_absent": ("the step's commit is not in the slot's repository", CHECK_GIT),
    "not_descendant": ("the step's commit does not descend from the commit the step started from", CHECK_GIT),
    "chain_length": ("the step's commit is more than one commit past the commit the step started from", CHECK_GIT),
    "nothing_written": ("the agent reported work but wrote no file, so there is nothing to commit", None),
}
RUN = {  # the run's classified end words the shelf names: what happened, and the fix
    "vendor_blip": ("The agent CLI failed with an error the factory cannot tell from a blip; often `--model` or `--effort` is "
                    f"not offered to the account. The vendor's message is in {EVIDENCE}.",
                    "correct `--model` or `--effort` if the message says so"),
    "bad_request": (f"The vendor rejected the request, often because of `--model` or `--effort`; its message is in {EVIDENCE}.",
                    "correct `--model` or `--effort`"),
    "hung": ("The agent printed nothing for too long and was stopped.", ""),
    "crash": ("The agent process crashed.", ""),
    "killed": ("The agent process was killed by a signal. The factory has no recorded sender or stop cause.", ""),
    "secrets": ("A command of the agent exposed a secret, so the run was stopped.",
                f"find what printed it in {EVIDENCE} and remove that source"),
    "exit": (f"The agent exited with an error and no answer; see {EVIDENCE}.", "read it and fix what it names"),
    "worker_failed": (f"The agent failed after starting work; see {EVIDENCE}.", "read it and fix what it names"),
    "logged_out": ("The agent's vendor refused the login.", "sign in again"),
    "rate_limited": ("The agent's vendor refused for a limit.", "wait for the limit to clear"),
    "credit_exhausted": ("The agent's vendor refused: credit is exhausted.", "restore the credit"),
    "network": ("The agent could not reach its vendor.", "restore the network"),
    "setup": ("The slot's setup failed before the agent started.", "fix the setup or environment named in the setup log"),
}
STUCK = {
    "expired_admitted": ("The attempt's deadline passed before its entry started.", "raise `--minutes` for the next run"),
    "entry_lost": ("The attempt's entry process ended without recording a result.", ""),
    "uncollected": ("The attempt's result could not be read back in full.", ""),
    "conflict": ("The attempt's stored session facts conflict.", ""),
    "setup_failed": ("The slot's setup command failed.", "fix the setup or environment first (the setup log is beside the attempt's "
                     "entry log)"),
}


@dataclass(frozen=True)
class Cause:
    what: str
    fix: str | None = None


def _at(deadline: float | None) -> str:
    return "" if deadline is None else f" ({datetime.fromtimestamp(deadline, UTC):%Y-%m-%d %H:%M:%S} UTC)"


def _known(table: Mapping[str, tuple[str, str | None]], word: str, fallback: Cause) -> Cause:
    found = table.get(word)
    return fallback if found is None else Cause(*found)


def _run(rest: str) -> Cause:
    return _known(RUN, rest, Cause(f"The agent run failed ({rest}); see {EVIDENCE}.", "read it and fix what it names"))


def _rejected(rest: str) -> Cause:
    what, fix = RULES.get(rest, (f"the step broke the commit rule `{rest}`", ""))
    return Cause(f"The factory rejected the agent's work: {what}. The agent's own claim of success was not what was checked.", fix)


def _stuck(rest: str) -> Cause:
    return _known(STUCK, rest, Cause(f"The attempt is stuck ({rest}).", ""))


def _answer(_rest: str) -> Cause:
    return Cause("The agent's answer did not fit the answer contract; `diagnostics.txt` in the evidence directory says how.", "")


def _repeats(_rest: str) -> Cause:
    return Cause("The agent was asked to repeat its step until its files were settled and did not manage it "
                 "(`Left in the slot` names them).")


LAND_CAUSE = "land:"  # the prefix of a land refusal's hold reason (`round_land`)
ASIDE = ("set the task's old branch aside (rename it to `old/<id>-` and the first 12 characters of its tip, saved work "
         "included: nothing is deleted) so the work starts again on the current "
         "`main`")
LAND = {  # a land refusal about the task's own change: what happened and the fix ("" = the same work may be tried again)
    "conflict": ("The checked change no longer merges onto `main`: newer changes on `main` conflict with it.", ASIDE),
    "checks_failed": ("The checks failed on the change as squashed onto the current `main`, though they passed on the task's own "
                      "commit (the land's check logs say which).", ASIDE),
    "remote_rejected": ("Origin refused the push to `main` by its own policy (for example a protected branch), not because `main` "
                        "moved.", "lift what blocks the push to `main`, or land the change by hand"),
    "branch_moved": ("The task branch no longer holds exactly the commit that was checked.", None),
    "claim_lost": ("Someone else changed this task's claim while it waited to land.", None),
}


def _land(rest: str) -> Cause:
    what, fix = LAND.get(rest, (f"The factory could not land the change ({rest}).", None))
    return Cause(f"The factory tried to land this task by itself and was refused: {what}", fix)


OWNER = {
    "needs_owner": Cause("The agent needs a decision only the owner can give (its explanation is quoted above)."),
    "main_moved": Cause("`main` moved while each of the last checks runs ran (more landing or pushing than the checks take), so "
                        "none of them could conclude.", ""),
    "incomplete": Cause("The agent stopped without finishing (its explanation is quoted above)."),
}
BY_PREFIX: tuple[tuple[str, Callable[[str], Cause]], ...] = (  # the first prefix of the word that fits builds the cause
    ("land:", _land), ("run:", _run), ("answer:", _answer), ("rejected:", _rejected), ("repeats_exhausted", _repeats), ("stuck:", _stuck),
)


def cause(reason: str, deadline: float | None = None, stop: AgentStop | None = None, rc: int | None = None) -> Cause | None:
    """The cause line and fix of a hold's `reason`, None for a reason without one of its own (the owner's answer then)."""
    word = reason.removeprefix("failed:")
    if word == "run:timeout":
        found = Cause(f"The agent did not finish before its deadline{_at(deadline)}.", "raise `--minutes` for the next run")
    else:
        found = OWNER.get(word) or next((build(word.removeprefix(prefix)) for prefix, build in BY_PREFIX if word.startswith(prefix)), None)
    attribution = stop_text(stop, rc) if word.startswith("run:") or word == "stuck:entry_lost" else None
    if attribution is not None:
        return Cause(attribution, found.fix if found is not None else "")
    return found


def next_step(found: Cause | None, back: str, owner: str) -> str:
    """The one sentence of what to do: the fix then `back` (how the task is taken again); `owner` is the owner's answer."""
    if found is None or found.fix is None:
        return f"To answer, {owner}, then {back}."
    return f"To try again, {back}." if found.fix == "" else f"To fix it, {found.fix}, then {back}."
