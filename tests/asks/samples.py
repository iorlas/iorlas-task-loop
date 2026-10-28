"""The 8 asks of tl-7y6.2.16 as the old engine put them to the owner (the quoted text, cut with `[...]` where the original was long) and
the 3 rewrites of 68-design-asks section 5. Lint must refuse the first and pass the second."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401
from taskloop.contracts.ask import Ask, AskOption
from taskloop.contracts.enums import AskClass, AskKind, AskStatus


def ask(bead: str, kind: AskKind, cls: AskClass, decision: str, options: list[AskOption], tried: list[str] | None = None) -> Ask:
    return Ask(id=bead + "-1", n=1, bead=bead, kind=kind, ask_class=cls, decision=decision, run=bead + "-20261026-101010", t=1.0,
               status=AskStatus.OPEN, tried=tried or [], options=options)


def opt(label: str, consequence: str = "", rec: bool = False) -> AskOption:
    return AskOption(label=label, consequence=consequence, recommended=rec)


RAW = "needs a human: delegate stopped the write step (bad_request): codex rejected the request: {\"type\":\"error\",\"error\":{\"message\":\"Invalid schema [...]"
BAD = {
    "lifesim-sz3-1": ask("lifesim-sz3-1", AskKind.DECISION, AskClass.BAD_REQUEST, RAW, [opt("Right"), opt("Wrong")]),
    "lifesim-6dq0-1": ask("lifesim-6dq0-1", AskKind.DECISION, AskClass.SANDBOX_DENIAL,
                          "needs a human: the write step was denied `{'command': '/bin/zsh -lc \"head -45 client/Assets/Tests/Editor/LiveViewTests.cs [...]", []),
    "lifesim-fld.27.3-1": ask("lifesim-fld.27.3-1", AskKind.DECISION, AskClass.EXTERNAL_FACT,
                              "Check these yourself, then comment on the bead (right, or wrong and why): The 'just check green' acceptance case runs a "
                              "hand-picked set of recipes [...]", []),
    "lifesim-o67g-8": ask("lifesim-o67g-8", AskKind.STUCK, AskClass.CAP_REACHED,
                          "**Re-planned 4 times; the engine stopped**\n\n**What I need from you:** Split the bead, say what the plan keeps missing, "
                          "or allow one more run.", [opt("Allow one more planner run", "The planner runs once more on the next pass of its loop.", True)]),
    "lifesim-22b3-4": ask("lifesim-22b3-4", AskKind.BUDGET, AskClass.OVER_BUDGET,
                          "**Over its time limit: 189 of 180 min**\n\n**What I need from you:** Pick an option, or say what to change.",
                          [opt("Run again", "", True), opt("Split the bead", "")]),
    "lifesim-d5f.39-4": ask("lifesim-d5f.39-4", AskKind.DECISION, AskClass.OPEN_QUESTION,
                            "**PoseShots requires every declared slot, but the toaster lacks a model and usable action**\n\n**What I need from you:** "
                            "Should that content be completed as a prerequisite or added to this task's scope?",
                            [opt("Complete prerequisite first", "The bead runs again with this as its instruction.", True), opt("Expand this task", "")]),
    "lifesim-5ban.30-3": ask("lifesim-5ban.30-3", AskKind.DECISION, AskClass.OPEN_QUESTION,
                             "**Existing order reasons and notices have one line**\n\n**What happened**\n- Strict variant validation will fail the required "
                             "green gate, while writing variants is explicitly out of scope\n\n**What I need from you:** Should the writing follow-up "
                             "supply them before this task proceeds, or should this task's scope include writing them?", [opt("A", "x", True)]),
    "lifesim-d5f.58-2": ask("lifesim-d5f.58-2", AskKind.DECISION, AskClass.OPEN_QUESTION,
                            "Lifesim-d5f.58 (front approach): the fix works. Shower and toilet are now used from the front, and a blocked front falls "
                            "back to another side. One older test stays red, and I need your call on it. What I found: in the two-lifer evening test "
                            "(seed 23), lifer 2 eats a snack [...] Options: A) The test allows a repeat only when it was the only choice offered [...]", []),
}
MOCKS = {
    "lifesim-d5f.39": ask(
        "lifesim-d5f.39", AskKind.DECISION, AskClass.OPEN_QUESTION, "How should the screenshot tool treat objects that do not exist yet?",
        [opt("Add an object filter", 'The tool renders only the objects this bead changes and records others as "not requested".', True),
         opt("Wait for the toaster", "This bead stays parked until someone makes the toaster model and action."),
         opt("Make the toaster here", "The bead grows to include the 3D model and gameplay content."),
         opt("Drop the toaster check", "The tool stops requiring it; no one is told the toaster is missing.")],
        ["Checked the base branch: the toaster is still missing"]),
    "lifesim-d5f.58": ask(
        "lifesim-d5f.58", AskKind.DECISION, AskClass.OPEN_QUESTION, "Should the test allow a repeat when it was the only choice?",
        [opt("Change the test", "Allows a repeat only if one candidate existed; real circling still fails.", True),
         opt("Raise minimum score", "0.01 becomes 0.012, so a nearly full need no longer counts; every golden changes."),
         opt("Change the scenario", "A different seed or starting needs so the moment never happens.")],
        ["Reran with the fixed tuning and seed: same result"]),
    "lifesim-22b3": ask(
        "lifesim-22b3", AskKind.STUCK, AskClass.NO_PROGRESS, "Run again with a named fix, or give different direction?",
        [opt("Run again, pick hair without sway bones", "Tests use a recipe and hair with no sway bones; run only these tests first.", True),
         opt("Ignore that one log message", "LogAssert.Ignore for the sway-bone error, only if main also shows it."),
         opt("Split the bead", "The tint logic lands now; the render tests become a follow-up bead.")],
        ["21 check rounds ran for 124 min", "12 of 21 rounds failed on the same test"]),
}
