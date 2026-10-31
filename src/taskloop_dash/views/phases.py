"""The tables that turn engine facts into the page's words: step -> phase, step -> board column, a run's Close and a Transition's cause
-> how a pass ended. Typed enums in, typed enums out; no text is read for a fact."""

from typing import Final

from taskloop.contracts.dash import Column, PassEnd, Phase
from taskloop.contracts.enums import Cause, Outcome, Step, WhyCode
from taskloop.contracts.log import Close

ORDER: Final = {p: i for i, p in enumerate(Phase)}
STEP_PHASE: Final = {
    Step.PLAN: Phase.PLAN,
    Step.REPLAN: Phase.PLAN,
    Step.WRITE: Phase.WRITE,
    Step.CHECKS: Phase.TEST,
    Step.REVIEW: Phase.REVIEW,
    Step.VERIFY: Phase.REVIEW,
    Step.LOOK: Phase.LOOK,
    Step.GATE: Phase.LAND,
    Step.LAND: Phase.LAND,
}  # reset, close and reflect are not drawn
PHASE_COLUMN: Final = {
    Phase.PLAN: Column.WORKING,
    Phase.WRITE: Column.WORKING,
    Phase.TEST: Column.WORKING,
    Phase.REVIEW: Column.REVIEW,
    Phase.LOOK: Column.LOOK,
    Phase.LAND: Column.LANDING,
}
# A Close whose run was stuck (WhyCode.STUCK), hung or failed names no PassEnd here: passes.last_end makes it "stuck" when the run's
# Stuck episode is open at its end; "exited" is a run recorded lost (runlife).
CODE_END: Final[dict[WhyCode, PassEnd]] = {
    WhyCode.NEEDS_HUMAN: "asked",
    WhyCode.OWNER_DECISION: "asked",
    WhyCode.OVER_BUDGET: "asked",
    WhyCode.TICKET: "asked",
    WhyCode.LANE_OUT: "lane_out",
    WhyCode.PAUSED: "parked",
    WhyCode.NETWORK: "parked",
    WhyCode.STOPPED_BY_COORDINATOR: "parked",
    WhyCode.VERIFY: "sent_back",
    WhyCode.GATE_RED: "test_failed",
}
CAUSE_END: Final[dict[str, PassEnd]] = {
    Cause.BAD_CHECKS: "test_failed",
    Cause.GATE_RED: "test_failed",
    Cause.CONFLICT: "test_failed",
    Cause.PUSH_RACE: "test_failed",
    Cause.VERIFY_WRONG: "sent_back",
    Cause.PLAN_SENT_BACK: "replan",
}
END_TEXT: Final[dict[PassEnd, str]] = {
    "": "",
    "test_failed": "test failed: back to write",
    "replan": "re-plan",
    "asked": "asked, waiting for an answer",
    "parked": "parked",
    "lane_out": "lane ran out, parked",
    "sent_back": "sent back",
    "stuck": "stuck",
    "exited": "worker exited",
    "done": "landed",
}
LOOPED: Final = frozenset({"test_failed", "replan", "sent_back"})  # a pass that ended by going back (the card's ↻N)


def step_of(name: str) -> Step | None:
    try:
        return Step(name)
    except ValueError:
        return None


def phase_of(name: str) -> Phase | None:
    step = step_of(name)
    return STEP_PHASE.get(step) if step else None


def end_of_cause(cause: str) -> PassEnd:
    return CAUSE_END.get(cause, "")


def end_of_close(close: Close) -> PassEnd:
    """How a run's Close ended its last pass, from the typed outcome and why_code."""
    if close.outcome in (Outcome.LANDED, Outcome.DONE):
        return "done"
    if close.why_code is None:
        return "parked" if close.outcome in (Outcome.PARKED, Outcome.BLOCKED) else ""
    return CODE_END.get(close.why_code, "")


def end_text(end: PassEnd, why: str = "") -> str:
    """The pass's closing line: the engine's own one-liner when it gave one, else the table's."""
    line = why.strip().splitlines()[0][:160] if why.strip() else ""
    return line or END_TEXT[end]
