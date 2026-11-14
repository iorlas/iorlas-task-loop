"""A hold's one tracker comment (tl-8bh9.14.9 section 6): a pure function of the hold, its cause and the abandon's outcome.

Fixed English. Every quoted part (the reason, the label, the agent's explanation, check names, paths) has its control,
format, surrogate, private-use and unassigned characters removed; every part is one line, except the explanation,
whose every line is quoted (`> `) under its own header, so no quoted text can forge a line of the comment. Caps: the
explanation 2000 characters, 10 failed checks, 20 left paths, each other part `PART` characters, the whole comment
`TOTAL`: the details are shortened first, so the claim line and the answer always stay. The claim line states only
what the abandon recorded: "returned" only when the claim is `unclaimed`.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal

from taskloop.evidence_files import TERMINATED
from taskloop.hold_cause import cause, next_step
from taskloop.printable import one_line

EXPLANATION: Final = 2000
CHECKS: Final = 10
PATHS: Final = 20
PART: Final = 300
TOTAL: Final = 6000
CUT: Final = "[shortened]"
QUOTE: Final = "> "  # each line of the agent's explanation
type LabelsWord = Literal["moved", "absent", "not_ours"]  # the label step's words after which a comment is written
type KeptWord = Literal["slot_dirty", "slot_branch", "slot_redirected", "slot_unborn", "worker_alive", "setup_running",
                    "check_running", "landing", "landed"]  # an abandon refusal only the person clears (section 12)


@dataclass(frozen=True)
class FailedCheck:
    name: str
    conclusion: str
    log: str


@dataclass(frozen=True)
class Leftovers:
    """What a `repeats_exhausted` hold leaves in the slot: the repeat reason and the paths."""

    reason: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class Returned:
    """The abandon is recorded: the claim `unclaimed` (returned by this abandon) or `not_held` (it was not the factory's)."""

    claim: Literal["unclaimed", "not_held"]


@dataclass(frozen=True)
class Kept:
    """The abandon was refused by `word`; the factory still holds the claim. `slot` names the slot path, `pid` and
    `pgid` the process that still runs. `claim`: whether the task's claim is the factory's as the label step read it
    (`ours`), not (`not_ours`: another actor's, or none: the claim had lapsed), or not known (`unknown`: read in an earlier
    call); only `ours` says the factory still holds the claim and returns it."""

    word: KeptWord
    slot: str = ""
    pid: int | None = None
    pgid: int | None = None
    claim: Literal["ours", "not_ours", "unknown"] = "ours"


@dataclass(frozen=True)
class HoldFacts:
    """Everything the comment says, as the hold read it."""

    task_id: str
    label: str | None  # None for a hand-started task held during preparation
    labels: LabelsWord
    reason: str
    step: str
    number: int
    attempt_id: str
    held_at: float
    published: str | None  # the task branch's published commit, None when not published
    end_commit: str | None  # X
    explanation: str | None
    checks: tuple[FailedCheck, ...]
    leftovers: Leftovers | None
    evidence: str  # the attempt's evidence directory
    entry: str | None = None  # the entry log's last line of fixed words (`Last entry result`), None when there is none
    deadline: float | None = None  # the attempt's deadline, epoch seconds
    saved: tuple[str, ...] = ()  # the full ids of the commits the hold saved the slot's unfinished work in, in order


def explained(text: str) -> str:
    """The agent's explanation: its printable lines (at most `EXPLANATION` characters in all), each quoted `> `."""
    lines = (one_line(line, EXPLANATION) for line in text.split("\n"))
    capped = "\n".join(line for line in lines if line)[:EXPLANATION].rstrip()
    return "\n".join(QUOTE + line for line in capped.split("\n")) if capped else ""


def _listed[T](items: tuple[T, ...], cap: int) -> tuple[tuple[T, ...], str]:
    more = len(items) - cap
    return items[:cap], (f" and {more} more" if more > 0 else "")


def _details(facts: HoldFacts) -> list[str]:
    when = f"{datetime.fromtimestamp(facts.held_at, UTC):%Y-%m-%d %H:%M:%S} UTC"
    branch = f"task branch task/{one_line(facts.task_id)}"
    at = f"{branch} at {one_line(facts.published)}" if facts.published else f"{branch} is not published"
    lines = [f"taskloop hold: {one_line(facts.reason)}",
             f"Step {one_line(facts.step)}, attempt {facts.number} ({one_line(facts.attempt_id)}), {when}; {at}."]
    if facts.entry is not None and facts.entry.endswith(TERMINATED):
        lines.append("The attempt's entry was terminated by a signal; its agent was stopped with it and its session was not "
                     "continued.")
    if facts.explanation and (text := explained(facts.explanation)):
        lines.extend(["The agent explained:", text])
    shown, more = _listed(facts.checks, CHECKS)
    lines.extend(f"Failed checks: {one_line(each.name, 100)} {one_line(each.conclusion, 40)} {one_line(each.log)}" for each in shown)
    if more:
        lines.append(f"Failed checks:{more}")
    if facts.leftovers is not None:
        paths, more = _listed(facts.leftovers.paths, PATHS)
        lines.append(f"Left in the slot: {one_line(facts.leftovers.reason, 40)} {', '.join(one_line(path) for path in paths)}{more}")
    if facts.saved:
        ids = ", ".join(one_line(sha, 64) for sha in facts.saved)
        lines.append(f"The slot's unfinished work was saved as commit {ids} on {branch}. The implementation is still incomplete: "
                     "the saved work is not a result and no check ran on it. The slot was released.")
    lines.append(f"Evidence: {one_line(facts.evidence)}")
    return lines


def _labelled(facts: HoldFacts) -> str:
    if facts.label is None and facts.labels in ("moved", "absent"):
        return "The factory added `held` without removing an approval label"
    label = one_line(facts.label or "", 200)
    return {"moved": f"The factory removed `{label}` and added `held`",
            "absent": f"The factory added `held` (`{label}` is no longer on the task)",
            "not_ours": "The factory changed no label (another actor holds this task)"}[facts.labels]


def claim_line(facts: HoldFacts, outcome: Returned | Kept) -> str:
    """What the factory did to the labels and the claim, by the abandon's outcome."""
    done = _labelled(facts)
    if isinstance(outcome, Returned):
        return done + (" and returned its claim." if outcome.claim == "unclaimed" else "; the claim was no longer the factory's.")
    claim = "not_ours" if facts.labels == "not_ours" else outcome.claim
    kept = f"{done}, but still holds the claim: " if claim == "ours" else f"{done}, but keeps the attempt's slot: "
    back = {"ours": "the next round returns the claim", "not_ours": "the next round frees the slot (the claim is not the factory's)",
            "unknown": "the next round frees the slot and returns the claim if it is still the factory's"}[claim]
    slot = f"slot {one_line(outcome.slot)}" if one_line(outcome.slot) else "its slot"
    match outcome.word:
        case "slot_dirty":
            return (kept + f"{slot} has files left by this attempt. Save what you need, remove or restore them "
                    f"after inspecting their status, and {back}. The factory never removes work.")
        case "worker_alive" | "setup_running" | "check_running":
            group = "" if outcome.pgid is None else f", group {outcome.pgid}"
            pid = f"pid {outcome.pid}{group}" if outcome.pid is not None else "pid unknown: wait for verified process identity"
            return (kept + f"a process of this attempt still runs ({pid}). When it has ended (or after you "
                    f"stop it by its verified identity), {back}.")
        case "landing" | "landed":
            return (kept + f"a land of this task holds its slot or may be on origin ({outcome.word}). Finish or withdraw it "
                    f"after resolving its delivery state, and {back}.")
        case _:
            return (kept + f"{slot} is not where the factory left it ({outcome.word}). "
                    f"Restore its recorded location and state, and {back}.")


def _answer(facts: HoldFacts, outcome: Returned | Kept) -> list[str]:
    """The cause's own line, then its one next step: an owner's answer only for a cause an answer fixes."""
    task, found = one_line(facts.task_id), cause(facts.reason, facts.deadline)
    if facts.reason.startswith("merge:"):
        return ["Main's merge stopped for a decision. The retained task work and resolution evidence remain available. "
                "The task stays held; approval labels do not restart its plan or reset the resolution limit."]
    if facts.labels == "not_ours":
        retry = "resolve its ownership with the current actor: rounds do not take it again"
    else:
        retry = (f"restore the approval label `{one_line(facts.label or '', 200)}`: "
                 f"the next round starts it again at plan on task/{task} as it is")
    edit = "edit this task's description or acceptance criteria (the agent reads those, not comments)"
    lines = [] if found is None else [found.what]
    lines.append(next_step(found, retry, edit))
    if isinstance(outcome, Kept):
        lines.append("Do that once the slot or process above is cleared: until then the task is not taken again.")
    if facts.reason == "branch_moved":
        lines.append(f"Restore task/{task} to contain {one_line(facts.end_commit or '')}, or rename it aside (`old/{task}-` and the "
                     "first 12 characters of its tip), "
                     "before adding the label.")
    if facts.reason == "claim_lost":
        lines.append("Someone else changed this task's claim while the factory worked on it.")
    return lines


def comment(facts: HoldFacts, outcome: Returned | Kept) -> str:
    """The comment, at most `TOTAL` characters: the details shortened (marked `CUT`) before the claim line and answer."""
    tail = "\n".join([claim_line(facts, outcome), *_answer(facts, outcome)])
    head = "\n".join(_details(facts))
    room = TOTAL - len(tail) - 1
    if len(head) > room:
        head = head[:room - len(CUT) - 1].rstrip() + "\n" + CUT
    return head + "\n" + tail
