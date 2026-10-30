"""The reviewer's prompt."""
from typing import Final

from taskloop.domain.prompts.common import DECIDED_RULE, OPTIONS_RULE, READ_RULE

REVIEW_PROMPT: Final = """You review one stage of a task, from another model family than the writer. Do not edit files.
<task>
{brief}
</task>
<plan>
{plan}
</plan>
Stage {n}: {goal}
{fix_line}{work}
The engine ran the checks outside any sandbox, one at a time, and they all pass; these results are facts:
{checks}
The engine runs the gate{gate} once, at land, on the tree rebased onto the latest base, before anything merges; a red
gate (coverage included) goes to a fix round. The gate, the checks above and what they prove are never an unchecked item.
The writer says: {summary}
Proof the engine cannot rerun (a test seen failing after a planted fault) is in {evidence}/: a requirement shown
there is met. The engine counted tests in the task's diff: {added} added, {removed} removed.
{host_rule}
{round_rule}{acceptance}Return:
- findings: bugs, broken contracts, risky changes (a public member, a test weakened or removed, a suppression, a file
  outside what the stage names), each with file, line, severity, axis, category, fix and scenario. axis: spec (a
  requirement of the task is not met, or behaviour nobody asked for) or standards (a break of this repo's own
  conventions: the rules in its AGENTS.md or CLAUDE.md, checked on the changed lines; name the rule). category: one word
  (logic, contract, test, docs, security, convention). scenario: the inputs and the wrong output, concretely. Only a high
  finding with a scenario sends the stage back; every other finding is noted. A finding whose scenario you cannot state
  is not high. No style nits.
- criteria: one entry per acceptance item listed above (empty when none is listed): item (its id), status (met, unmet,
  or engine when the engine proves it), evidence (what shows it: a check, a file and line, the evidence folder).
- unmet: what in {scope} the work does not do yet, each saying what is missing. A requirement shown met by a check or
  by the evidence is met; never list a remark that something is fine.
- question: empty, unless only the owner can decide something about the task itself (then explain it for a phone:
  what you found, the options, your recommendation).
- leftovers: real follow-up work you noticed outside this task, else empty.""" + "\n" + OPTIONS_RULE + "\n" + DECIDED_RULE \
    + "\n" + READ_RULE

HOST_RULE = ("The host is macOS, and the engine runs the gate there. Only the coordinator can run bd: the engine files follow-up beads\n"
             "itself, so never ask for a bead to be filed, closed or commented, nor for a check on another operating system; put\n"
             "such work in leftovers.")
FIRST_ROUND: Final = ("This is the first review of this stage: return the complete list of its blocking findings now; later rounds only\n"
               "check that they were fixed.\n")
LATER_ROUND: Final = ("This is review round {n} of this stage. Verify that each earlier finding below is fixed; report a new finding only\n"
               "for code changed since your last review or for a regression, and no low findings.\n{prior}")


def round_rule(round_no: int, prior: str) -> str:
    return FIRST_ROUND if round_no <= 1 else LATER_ROUND.format(n=round_no, prior=prior)


def acceptance_text(items: list[tuple[str, str]]) -> str:
    """The acceptance items of the task with their ids, for the last stage's review to map to evidence."""
    if not items:
        return ""
    return "Acceptance items (answer each in criteria):\n" + "".join(f"{i}. {t}\n" for i, t in items)


def review_prompt(fix: bool, last: bool, fix_scope: str, round_no: int = 1, prior: str = "", acceptance: str = "", **fields: object) -> str:
    """REVIEW_PROMPT for one stage. The scope of the `unmet:` line is a fixed phrase (the template's line never takes text from
    the stage); in a fix round the fix's own scope is a line of its own (tl-7y6.6.11: it was spliced into the sentence)."""
    scope = ("the stage goal" if fix else
             "the stage goal and every requirement and acceptance criterion of the task" if last else
             "the stage goal (later stages cover the rest of the task)")
    return REVIEW_PROMPT.format(scope=scope, fix_line=f"Scope of this fix round: {fix_scope}\n" if fix else "", host_rule=HOST_RULE,
                                round_rule=round_rule(round_no, prior), acceptance=acceptance, **fields)

NEW_FILES_TEXT: Final = ("\nUnexplained new files: untracked, and no stage lists them nor the writer names them. They are NOT in the "
                  "commit unless you accept them, and they are moved out of the tree before the land gate. Decide EVERY one: "
                  "put its path in accept_files if the task needs it (it is staged), or in reject_files if it is a stray (a "
                  "test run's leftover). One you do not decide becomes a medium finding that sends the stage back. Each file "
                  "with its first 80 lines (or its size, if binary):\n")
