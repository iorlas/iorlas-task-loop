"""The ask each stop of the engine puts to the owner: built from facts the raise site holds (numbers, lists, the worker's own words),
never from the text of a message. Each returns an AskSpec that passes lint."""
from collections.abc import Sequence
from typing import Any

from taskloop.contracts.ask import AskDetail, AskOption, BudgetLine, ReplanLine
from taskloop.contracts.dash import OwnerCause
from taskloop.contracts.enums import AskClass
from taskloop.domain.asks.lint import DECISION_MAX, LABEL_MAX, TRIED_MAX
from taskloop.domain.asks.spec import AskSpec
from taskloop.domain.asks.text import SPLIT_WORDS, clip

RAW_CAP = 4000
ONE_BULLET = 160
DROPPED = str.maketrans({"{": "(", "}": ")", "\n": " "})
SPLIT = AskOption(label="Split the bead", consequence="The bead is cut down from your answer, then the work goes on from where it stopped.",
                  action="split", text=SPLIT_WORDS, cost="One planning run")


MARKS = (". ", "? ", "! ")


def question(text: str, how: str = "What should the engine do about this?") -> str:
    """One sentence ending in '?' from a worker's free text: its last question, cut at a word; `how` when it asked none."""
    flat = " ".join(text.translate(DROPPED).split())
    if not flat.endswith("?"):
        return how
    head = flat[:-1]
    start = max([head.rfind(m) + len(m) for m in MARKS if m in head] or [0])
    last = head[start:].strip() or head
    return clip(last, DECISION_MAX - 1).rstrip("…") + ("…?" if len(last) > DECISION_MAX - 1 else "?")


def bullets(lines: Sequence[str]) -> list[str]:
    return [clip(x, ONE_BULLET) for x in lines if x.strip()][:TRIED_MAX]


def worker_options(given: Sequence[dict[str, Any]] | None) -> list[AskOption]:
    """The worker's own answers as options: its label, its answer text, its cost line; the recommended one first."""
    out = []
    for o in given or []:
        label, answer = str(o.get("label") or "").strip(), str(o.get("answer") or "").strip()
        if not label or not answer:
            continue
        out.append(AskOption(label=clip(label.translate(DROPPED), LABEL_MAX), action="text", text=answer[:1000],
                             consequence="The bead runs again with this as its instruction.", cost=clip(str(o.get("cost") or ""), 120),
                             recommended=bool(o.get("recommended"))))
    out = out[:4]
    return sorted(out, key=lambda o: not o.recommended)


def declared(cause: object) -> OwnerCause:
    """The cause an agent declared with its question; anything but a value of the list is '?'."""
    try:
        return OwnerCause(str(cause or "unknown"))
    except ValueError:
        return OwnerCause.UNKNOWN


def open_question(text: str, given: Sequence[dict[str, Any]] | None, cause: object = "unknown", default: str = "") -> AskSpec:
    """A planner, writer or reviewer asked the owner something. Fewer than two usable options are made up to two. A `default` makes it a
    soft ask: the run went on with that and the question stays open for the owner."""
    opts = worker_options(given)
    if len(opts) < 2:
        opts += [SPLIT] if opts else [AskOption(label="Answer in words",
        consequence="The bead runs again with your answer as its instruction.",
                                               action="text", edit=True), SPLIT]
    opts = [_recommend(o, k == 0) for k, o in enumerate(opts)]
    return AskSpec(AskClass.OPEN_QUESTION, question(text), [], opts, AskDetail(text=text[:RAW_CAP]), declared(cause),
                   blocking=not default.strip(), default=default.strip()[:300])


def _recommend(o: AskOption, first: bool) -> AskOption:
    return AskOption(label=o.label, consequence=o.consequence, action=o.action, text=o.text, cost=o.cost, recommended=first, edit=o.edit)


def external_fact(items: Sequence[str]) -> AskSpec:
    """The workers could not check these and no command can: only the owner knows."""
    first = clip(items[0], 60) if items else "this"
    more = f" and {len(items) - 1} more" if len(items) > 1 else ""
    return AskSpec(AskClass.EXTERNAL_FACT, f"Can this land without checking: {first}{more}?",
                   bullets(["The workers could not check it, and no command here can", *items]),
                   [AskOption(label="Right, land it", consequence="The bead lands as it is; the unchecked items are noted on it.",
                              action="confirm", text="right", recommended=True),
                    AskOption(label="Wrong: say what", consequence="The engine plans a fix from your words and keeps the accepted stages.",
                              action="text", edit=True, cost="One more run")],
                   AskDetail(text="; ".join(items)[:RAW_CAP]))


def unproven(items: Sequence[str], fix_rounds: int) -> AskSpec:
    first = clip(items[0], 60) if items else "a claim"
    return AskSpec(AskClass.UNPROVEN, f"How can the engine prove {first}?",
                   bullets([f"{fix_rounds} fix rounds did not prove it", *items]),
                   [AskOption(label="Say how to prove it", consequence="The engine plans the proof you describe, then lands.",
                              action="text", edit=True, recommended=True, cost="One more run"), SPLIT],
                   AskDetail(text="; ".join(items)[:RAW_CAP]))


def no_progress(what: str, limit: int, tail: str) -> AskSpec:
    last = tail.strip().splitlines()[-1] if tail.strip() else ""
    return AskSpec(AskClass.NO_PROGRESS, f"How should it go on after {limit} fix rounds of {clip(what, 50)}?",
                   bullets([f"{limit} fix rounds ran", what, clip(last, 120)]),
                   [AskOption(label="Run again", consequence="The bead goes on from where it stopped, with a fresh set of fix rounds.",
                              action="rerun", text="run again", recommended=True, cost="Up to one more run"),
                    AskOption(label="Give direction", consequence="The engine follows your words on the next run.",
                    action="text", edit=True), SPLIT],
                   AskDetail(text=tail[-RAW_CAP:]))


def check_timeout(check: str, minutes: float) -> AskSpec:
    """A check hit its wall limit: the writer was not asked to fix it and nothing was retried."""
    return AskSpec(AskClass.NO_PROGRESS, f"Check {clip(check, 40)} ran out of time at {minutes:g} min; how should it go on?",
                   bullets([f"check {check} timed out after {minutes:g} min (wall_min={minutes:g})", "the writer was not asked"]),
                   [AskOption(label="Run again", consequence="It goes on from where it stopped; raise wall_min first if needed.",
                              action="rerun", text="run again", recommended=True, cost="One more check run"),
                    AskOption(label="Give direction", consequence="The engine follows your words on the next run.",
                              action="text", edit=True), SPLIT],
                   AskDetail(text=f"check {check}: stopped at its wall limit of {minutes:g} min"))


def cap_reached(planned: int, plans: Sequence[tuple[str, str]]) -> AskSpec:
    """The plan was redone `planned` times; `plans` is (mode, why) per planner run."""
    return AskSpec(AskClass.CAP_REACHED, f"The plan was redone {planned} times; how should the bead go on?",
                   bullets([f"{m}: {w}" for m, w in plans[-TRIED_MAX:]]),
                   [AskOption(label="Allow one more try", consequence="The engine plans once more and goes on from there.",
                              action="rerun", text="allow one more", recommended=True, cost="One planning run"), SPLIT],
                   AskDetail(replans=[ReplanLine(n=k + 1, why=clip(w, ONE_BULLET)) for k, (_m, w) in enumerate(plans[-6:])]))


def over_budget(over: Sequence[str], steps: Sequence[BudgetLine], waited_min: int) -> AskSpec:
    tried = ["Over its limit: {}".format(", ".join(over))] + [f"{b.step} took {round(b.minutes)} min" for b in steps[:2]]
    if waited_min >= 1:
        tried = [*tried[:TRIED_MAX - 1], f"{waited_min} min waiting for shared resources are not counted"]
    return AskSpec(AskClass.OVER_BUDGET, "Run it again with a fresh budget, or split the bead?", bullets(tried),
                   [AskOption(label="Run again", consequence="The bead goes on from where it stopped; the budget counts per run.",
                              action="rerun", text="run again", recommended=True, cost="Up to one more full budget"), SPLIT],
                   AskDetail(budget=list(steps)))


def missing_criteria() -> AskSpec:
    return AskSpec(AskClass.MISSING_CRITERIA, "What proves this bead done?", ["The bead has no acceptance criteria"],
                   [AskOption(label="I added them", consequence="The bead runs again and reads the criteria you added.", action="rerun",
                              text="run again", recommended=True),
                    AskOption(label="Write them here", consequence="Your words are the acceptance criteria for the next run.",
                    action="text",
                              edit=True)])


def too_big(goals: Sequence[str], big: int) -> AskSpec:
    return AskSpec(AskClass.TOO_BIG, f"The plan has {len(goals)} stages; keep this as one bead?",
                   bullets([f"{k + 1}. {g}" for k, g in enumerate(goals)] + [f"more than the {big} a single task takes"]),
                   [AskOption(label="Keep it as one bead", consequence="The engine goes ahead with every stage in this task.",
                              action="confirm", text="keep", recommended=True),
                    AskOption(label="I will split it", consequence="The bead stays stopped until you cut it into smaller beads.",
                    action="split",
                              text="split")],
                   AskDetail(text="\n".join(f"{k + 1}. {g}" for k, g in enumerate(goals))[:RAW_CAP]))


def repeated_fault(n: int, first_line: str) -> AskSpec:
    return AskSpec(AskClass.NO_PROGRESS, f"The engine failed the same way {n} times; how should it go on?", bullets([first_line]),
                   [AskOption(label="Run again", consequence="The bead runs again, after you fixed the cause.", action="rerun",
                              text="run again", recommended=True),
                    AskOption(label="Say how to go on", consequence="The engine follows your words on the next run.",
                    action="text", edit=True)])
