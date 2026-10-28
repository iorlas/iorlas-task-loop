"""The reviewer's prompt."""
from taskloop.domain.prompts.common import DECIDED_RULE, OPTIONS_RULE

REVIEW_PROMPT = """You review one stage of a task, from another model family than the writer. Do not edit files.
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
Return:
- findings: bugs, broken contracts, risky changes (a public member, a test weakened or removed, a suppression, a file
  outside what the stage names, a break of this repo's own conventions: the rules in its AGENTS.md or CLAUDE.md, checked
  on the changed lines), each with file, line, severity and the fix. high and medium send the stage back; low
  is noted only. No style nits.
- unmet: what in {scope} the work does not do yet, each saying what is missing. A requirement shown met by a check or
  by the evidence is met; never list a remark that something is fine.
- question: empty, unless only the owner can decide something about the task itself (then explain it for a phone:
  what you found, the options, your recommendation).
- leftovers: real follow-up work you noticed outside this task, else empty.""" + "\n" + OPTIONS_RULE + "\n" + DECIDED_RULE

def review_prompt(fix: bool, last: bool, fix_scope: str, **fields: object) -> str:
    """REVIEW_PROMPT for one stage. The scope of the `unmet:` line is a fixed phrase (the template's line never takes text from
    the stage); in a fix round the fix's own scope is a line of its own (tl-7y6.6.11: it was spliced into the sentence)."""
    scope = ("the stage goal" if fix else
             "the stage goal and every requirement and acceptance criterion of the task" if last else
             "the stage goal (later stages cover the rest of the task)")
    return REVIEW_PROMPT.format(scope=scope, fix_line=f"Scope of this fix round: {fix_scope}\n" if fix else "", **fields)

NEW_FILES_TEXT = ("\nUnexplained new files: untracked, and no stage lists them nor the writer names them. They are NOT in the "
                  "commit unless you accept them, and they are moved out of the tree before the land gate. Decide EVERY one: "
                  "put its path in accept_files if the task needs it (it is staged), or in reject_files if it is a stray (a "
                  "test run's leftover). One you do not decide becomes a medium finding that sends the stage back. Each file "
                  "with its first 80 lines (or its size, if binary):\n")
