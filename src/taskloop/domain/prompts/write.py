"""The writer's prompts: the first one of a stage, the delta of a resumed writer, and what a fresh writer is told of its predecessor."""
from taskloop.domain.prompts.common import DECIDED_RULE, OPTIONS_RULE

REPEAT_RED = ("\nThese checks failed in the last round too:\n%s\nIf one measures a threshold the task does not ask for (the task "
              "says the owner judges it, or the number is the plan's own), do not keep tuning the work to it: list it in "
              "bad_checks, with why, and the plan is changed instead.\n")

SHOTS_FIX = ("\nYour answer named no shots and gave no logic_only reason, but this stage touches visual paths. You cannot render here: the "
             "engine does. Name the pictures to render in `shots` (a method from the table, its args, names), or say in logic_only why "
             "nothing on screen differs. Change nothing else; do not redo the work.\n%s\n")

LOOK_WRITE_TABLE = ("\nThis stage changes how something looks (it touches visual paths). You cannot render it here: the engine does, "
                    "right after this write, and a look judge reads the pictures. Say what to render in `shots`: one entry per "
                    "set of pictures, with a method from the table below, its args (name, value) and names (the screens or "
                    "states you changed, in words). At most %d entries. Do not save screenshots yourself.\n%s\nIf nothing on "
                    "screen differs, leave `shots` empty and put a one-line reason in logic_only.")

LOOK_FEEDBACK = ("\nThe engine rendered your shots and the look judge found these defects:\n%s\nThe pictures are at (open one only "
                 "if you need to):\n%s\nFix what the judge saw, and list the shots to render again in `shots`.\n")

WRITE_PROMPT = """You are the writer for one stage of a task, in an unattended engine. Nobody is watching.

<task>
{brief}
</task>
<plan>
{plan}
</plan>
Your stage: {n}: {goal}{rules}
Files: {files}
{anchors}The stage's checks (the engine runs all of them after you; the split says which you may run):
{checks}
{where}
A check that mentions $TL_CHECK_LOG_<ID> or $TL_CHECK_RC_<ID> reads the log and the exit code of a configured check the engine ran just
before it. Those variables exist only while the engine runs the checks, never in your session: do not ask for them, do not export them,
and do not call it a blocker that they are unset. Make what the check asserts true and run the checks you may run.
Never run the gate{gate} or the issue tracker (bd): the engine runs the gate, and its run is the one that counts.
Repo instructions that say a change is done only when the full gate passes are for people working by hand; here the
engine does that part.
{feedback}
flakes: a test that failed for a reason outside your change (it passed or failed differently on a rerun, or fails on the
untouched base): its name and one line; else empty. The engine tells later tasks of this repo.
bad_checks: a stage check that fails for a reason no code change can fix (wrong arguments, a guard that rejects the
uncommitted work this stage must leave, a pattern that matches harmless text), each with why (cmd: the check's \
command exactly as listed, never shortened); else empty. \
The engine
then asks for a new plan instead of retrying.
A check that times out or fails only where you run it is not yours to retry; note it once and move on.
Proof the engine cannot rerun (a test seen failing after a planted fault, then passing once restored; a manual
measurement): save the exact commands and their output as files in {evidence}/ and name those files in the summary.
Only that proof goes there, never your own runs of the checks.
Screenshots, PDFs or other files the owner should see: save them in {artifacts}/ ($TL_ARTIFACTS in checks and tools); the engine keeps them.
Rules: no suppressions; do not weaken, skip or delete tests; stay inside the
stage. question: empty unless only the owner can decide something about the task itself (then explain it for a
phone); never a question about tools or access.""" + "\n" + OPTIONS_RULE + "\n" + DECIDED_RULE

WRITE_RULES = """
This repo's rules for work in your sandbox (what runs there, what does not):
<worker_rules>
%s
</worker_rules>"""

def write_prompt(rules: str, **fields: object) -> str:
    """WRITE_PROMPT with the repo's worker rules inlined (a resumed writer's delta never repeats them)."""
    return WRITE_PROMPT.format(rules=WRITE_RULES % rules if rules else "", **fields)

WRITE_RESUME_PROMPT = """You are still the writer of this task, in an unattended engine. Nobody is watching. This session has the
task, the plan and your rules from before; only what changed is below.
The brief is unchanged; it is in {brief}; re-read it if unsure.
{plan}
Your stage: {n}: {goal}
Files: {files}
{anchors}The stage's checks (the engine runs all of them after you; the split says which you may run):
{checks}
{where}
{feedback}"""

STAGES_DONE = """
Earlier stages of this task are accepted and their work is in this tree; you are a fresh session for the next one (the last
session had grown large). Do not redo them.
Accepted stages:
%sDone so far (git diff --stat from the task's base):
%s
The last rounds (the writer's summary, then what was sent back):
%s"""

DONE_SO_FAR = """
You take over from an earlier writer of this task, whose session grew too large to go on. Its work is in this tree, committed
on this branch or not: do not start over.
Done so far (git diff --stat from where this stage started):
%s
Its last summary: %s
The last rounds (the writer's summary, then what was sent back):
%s"""
