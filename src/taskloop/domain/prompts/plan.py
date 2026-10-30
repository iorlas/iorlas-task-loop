"""The planner's prompt, its visual-stage rules, and the texts a plan is sent back with."""
from typing import Final

from taskloop.domain.prompts.common import COMMON, DECIDED_RULE, OPTIONS_RULE

PLAN_BRIEF_KB: Final = 12            # the planner's whole brief should stay under this

ASSUME_TEXT = ("\nYou asked: %s\nNothing in that question cannot be undone, so the engine does not ask the owner: it records it as an "
               "Assumption. Plan the work on your best assumption now, with at least one stage.\n")

PLAN_DECIDED_TEXT: Final = "Plan the work that meets it; ask nothing it already answers.\n"

TRACKER_TEXT: Final = ("\n\nYour plan was sent back: these checks read the issue tracker (they run bd or read .beads/), which "
                "no writer can run and no code change can satisfy:\n%s\nRewrite them to prove the code and the tree only. "
                "Follow-up work the task wants filed goes in leftovers: the engine files it.")

UNANCHORED_TEXT: Final = ("\n\nYour plan was sent back: these stages change files that exist but name no anchor for them:\n%s\nGive each "
                   "such file an anchor in the stage's `anchors` (path, lines, symbol, why; at most 8 per stage) so the writer "
                   "starts where you already looked instead of searching the tree again.")

EMPTY_PLAN_TEXT = ("\n\nYour plan was sent back: it has no stages, no question and no leftovers, so there is nothing to do and nothing to "
                   "ask. A plan has at least one stage (goal, files, checks). If the work is already done in the tree, plan the "
                   "stage that checks it. If only follow-up work is left, list it in leftovers. If the task cannot be done without "
                   "an owner's decision, ask it in question.")

DRY_CHECK_TEXT: Final = ("\n\nYour plan was sent back: the engine dry-ran its checks and these cannot run:\n%s\nReturn the plan "
                  "with only these checks fixed.")

REFUSED_CHECKS_TEXT: Final = ("\n\nYour plan was sent back: these checks name a repo check that does not exist or run a repo check's "
                       "command again:\n%s\nReturn the plan with only these checks fixed.")

GATE_ONLY_ACCEPTANCE: Final = "plan-lint rule gate-only-acceptance"

GATE_ONLY_ACCEPTANCE_TEXT: Final = ("\n\nYour plan was sent back (%s): these acceptance cases or Done-when items are only the "
                             "gate command, and the engine runs the gate (`%s`) once at land on its own:\n%s\nReplace each with what "
                             "the task asks for that the gate does not show (a behaviour, a number, a file), or drop it.")

VISUAL_PLAN: Final = """This repo has visual work (screens). Give every case a class in `class`:
- test: a command proves it (the usual case with its check).
- look-objective: a picture can prove it: it shows, nothing is clipped or overlapped, no error text, magenta or missing
  texture, the state asked for is visible. Leave `check` empty: the engine renders the shots and a look judge reads them.
- taste: someone has to like it ("the owner approves", "reads well", "feels like ..."). Leave `check` empty: it goes to the
  owner after the land and never blocks it.
A number for a look item (a contrast ratio, a size) comes only from the task, the owner or a project standard file (design
tokens, a rule under config/). Never invent one as a check: if you think one is needed, ask it as your question (options with
your proposal first) and plan no check for it.
%s"""

VISUAL_STAGES: Final = """A stage whose files match this repo's visual paths (%s) changes how something looks. Its writer cannot \
render: it names the
pictures to render in `shots` (a method from the table below, its args, names) or gives a `logic_only` reason; an answer with
neither is sent back. Plan such stages knowing that, and never plan a check that needs a picture the writer is to make.
Shot methods:
%s"""

PLAN_PROMPT: Final = COMMON + """

The task (the bead, with its acceptance criteria and comments: review findings, the owner's answers):
<task>
{brief}
</task>
Explore cheaply: find code with `rg -n` and read line ranges (`sed -n 'a,bp'`), not whole files. Stop reading once
each stage has its files and its checks. Budget: about 12 tool calls. Then plan.

- Split the work into stages, each one coherent piece that its checks can judge (often one stage is enough).
- For each stage: goal, the files it changes, the exact commands that prove it (tests, linters), and hard=true only
  when it is risky or subtle. A check is {{"kind": "ref", "check": "<id>"}} (a repo check from the list below) or
  {{"kind": "adhoc", "argv": [...], "reads": [...]}}: the program and its arguments as separate strings, e.g.
  ["python3", "-m", "unittest", "tests.test_x"] or ["just", "check"]; `reads`: ids of repo checks whose log it reads.
  The engine execs the argv as given, with no shell: no `&&`,
  `;`, pipe, redirect, `$(...)`, `$VAR`, glob or quote means anything in it, and a string is sent back. It
  exits 0 when it proves the goal and non-zero when it does not: the engine reads only the exit code. Exit 86 means it could not
  run its proof (a tool or host it needs is missing): recorded unverified, never passed, and the land refuses on it; never
  exit 0 with a "skipped" line. A proof that needs a
  pipeline, a redirect, a loop or a count ("expect empty", `grep ... | wc -l`) goes into a recipe the repo has or you add (a just
  target or a script, listed in the stage's files), and the check calls it: ["just", "name"].
- An adhoc argv never starts with a repo check's command: use a ref. To assert on a repo check's output, list its id
  in `reads`: your check runs after it (skipped if it failed) with its log in `TL_CHECK_LOG_<ID>` (id upper-cased, other
  characters `_`; exit `TL_CHECK_RC_<ID>`). A script reads it; pass the name:
  {{"kind": "adhoc", "argv": ["python3", "tools/assert_log.py", "TL_CHECK_LOG_UNITY_TESTS", "Passed: 12"], "reads": ["unity-tests"]}}.
- The engine sets every time limit and runs checks one at a time; never write timeouts, "run alone" or similar notes
  into a check.
- cases: the acceptance cases. At least one per acceptance criterion of the task, each with the criterion it proves
  (quote it) and a check. They run on the last stage and again after any fix at land. A case about what users see uses
  the host's tools and a fact the tool reports (a scenario script, a screenshot saved under the evidence folder, a count
  the editor prints), never only "a screenshot exists".
- Before planning, check that every input the criteria need exists: a file or asset, an object in the content, a platform or
  machine the factory has, the engine or tool the project uses now, an input the task says someone provides. One you could not
  find is listed in unresolved (what, kind, path: the file it should be at, or empty). If the rest of the task can go on
  without it, defer the criteria that need it instead (a case with proved_by leftover, and a leftover) and do not list it.
  A listed input is never an ask: the engine records it as an Assumption and the plan goes on. Material outside the
  worktree (a study, a file under ~/ or Drop) is missing material: plan from the bead text and the repo.
- Each case says in proved_by how its criterion is proved, and via names what proves it: check (a command; the usual
  case), stage (its stage's own checks; via = the stage number), leftover (deferred to a follow-up bead the engine files:
  also list it in leftovers; via = that leftover's title; check empty) or engine_step (the engine does it itself: files the
  leftovers as beads, runs the gate, lands, closes the bead, copies screenshots; via = which; check empty). A criterion
  about filing beads, the gate, the land or closing is an engine_step; one the tracker holds is never a check. The review
  and the verifier are told this ledger and will not call a leftover or engine_step criterion unmet.
- A criterion only the owner can judge (it looks right, feels right, the owner approves) is never a pass/fail check on a
  number you chose: the check proves the evidence exists (the screenshot or sheet is saved, a count the tool reports), and
  the judgement goes in leftovers for the owner. A threshold you invent is a requirement nobody asked for, and the writer
  will tune the work to it.
- Verify (a read-only check of what the workers could not check) runs only on a visual bead: one whose stage files match the repo's
  visual paths or whose criteria ask for a picture. For any other bead a check you plan is the only proof there is, and what is
  left unchecked lands as one follow-up bead: plan a check for every criterion you can.
- Name the risks ahead of time: what could break something users or other code rely on (a saved format, a public
  member, shared files), each with the check that proves it safe. None is fine.
- A check proves the code and the tree only: it never reads the tracker (no `bd`, nothing under `.beads/`) nor
  anything outside the worktree; the writers cannot run bd, so such a check fails whatever they do. Follow-up work the
  task wants filed (a new bead, a later task) goes in leftovers, each a title and why: the engine files them itself,
  and no check or case asks for them.
- question: empty. Assume instead of asking: decide what you can, plan on it, and say it in the summary. Only a step
  that cannot be undone may ask: set irreversible to push_shared (a push to a shared branch), delete_outside (a
  deletion outside the worktree), close_epic (closing an epic) or spend_money, and write the question so it can be
  answered from a phone: what you found, the decision, 2-3 options with costs, your recommendation. A question
  without irreversible is dropped by the engine and recorded as an Assumption. Missing reference material, a missing
  file, an unclear scope, a product or architecture choice are all reversible: assume.
""" + OPTIONS_RULE + "\n" + DECIDED_RULE

REPLAN_CAP: Final = "stuck: the bead was re-planned "  # the cap's ask; an owner's answer to it allows one more
