# Depth

Medium: deliver tracker discussion and answers after a hold to attempt inputs,
then expose the saved input in the dashboard. No owner decision is missing and
the references to .121, .137, .162 and .145 do not establish unlanded dependencies.
Evidence budget: 12 model calls. Use the supplied glossary; no new term is needed.

## Size

Estimate 18–22 changed files, including focused tests, this plan and any adapter
contract changes; 65 model calls for one implement attempt. Three independently
testable behaviours:

1. Both agent steps receive the task's comments and directly linked discussion,
   with authors and times, without agent access to the tracker.
2. The next attempt after a hold receives later answers, including through a
   restart or repeat, without treating their prose as a state transition.
3. The dashboard shows the exact discussion snapshot sent to the selected
   attempt, even after tracker edits and beyond the current display cutoff.

This is one bounded delivery change. It needs no database schema change, new
scheduler behaviour or implementation of the related tasks.

## Current boundaries

At source commit `7976bd5a7ac17d707f103677272357c8cc67fc37`:

- `tracker.inspect_task` returns task prose and typed dependencies, without
  comments. `task_comments` already maps comments to author, tracker time and
  text; `tracker_client.py` owns construction of the real client.
- `admit.task_text` delegates to `plan_step.input_text` or
  `implement_step.input_text`. Initial admission and `NextAdmission` save the
  rendered input through `EvidenceFiles.put_input`, with its digest.
- `repeat.StepRepeat._input` builds feedback around the first input in the chain.
  Updating only the initial renderers would therefore leave repeats stale.
- `HoldStore` owns hold records, including `held_at`, `cause_id`, reason and
  comment publication times. Clearing a hold does not erase its history.
- `dash_task._agent_body` reads the saved `input.txt`, but `EvidenceFiles.text`
  silently limits it to 65,536 bytes. The Prompt tab labels that prefix as the
  input sent to the agent.

There is no existing plan or unfinished task-branch work at this checkout.

## Discussion collection

Add one application operation for collecting attempt discussion, used by every
agent-attempt admission path. Keep it separate from ordinary task inspection:
status checks, checks attempts and dashboard tracker polling should not acquire
an expanded dependency on all discussion reads.

Use an explicit read port returning validated structured records. The tracker
adapter reads the task's comments and the comments of unique directly linked
tasks in the same configured backlog, using the structured links already
returned by task inspection, including dependency links. Include each source
task's id, title and relationship so linked comments have context. Include all
authors, including the factory's comments; do not guess who is a person from an
author string. Do not recursively traverse links or search descriptions for
task ids. Deduplicate self-links and repeated links; sort source tasks by id
and retain each thread's tracker order. A linked task referenced in the .77
regression fixture must contribute .58's discussion.

Use pydantic v2 models for tracker interchange and validated timestamp values;
keep backend commands, relationship decoding and error details inside the
adapter. In-process application inputs/results remain typed. A failed read,
missing linked source or malformed response is an explained unavailable/refused
input, never an empty discussion. Reuse existing input/admission outcomes where
they fit; any new closed vocabulary must have one enum and codec.

Bound collection to 16 unique linked tasks and the rendered discussion block
to 32 KiB of UTF-8, including metadata and delimiters. Read each source once per
new attempt. Enforce limits before saving input or taking a claim/reservation;
if the complete discussion cannot fit, refuse input construction with the
source and exceeded bound. Do not silently clip a decision, answer or linked
thread and then dispatch an agent with incomplete requirements. Empty discussion
is a successful, explicit empty block. These are internal limits, not profile
settings. No network or tracker read occurs inside a write transaction.

## Hold answers and attempt lifecycle

Add a narrow `HoldStore` read for the most recent recorded hold of the scoped
task, regardless of whether its label was subsequently cleared. Return its
existing typed cause and recorded time; SQL remains in that owning store.
Classify task comments whose valid tracker times are later than `held_at` as
comments after that hold. Preserve the original time and author in the prompt,
and include the hold's reason and time so the agent can associate the answers
with the refusal. Include all comments, rather than extracting supposed answers
from prose. Missing/unusable comment times must remain visible as unclassified
comments, never evidence that an answer is still pending.

Without local hold history, supply the whole discussion without claiming which
comments answer a hold. Do not reconstruct factory state from tracker comment
text, exports, transcripts or Git history. Existing typed causes remain the
authority, including the boundaries associated with .162/.145.

Collect immediately before constructing each new immutable attempt input:
initial plan, advance to implement, manual restart after a hold, and automatic
repeat. Reuse one collector and renderer through composition; give repeats the
existing tracker binding through their owning attempt reader. Repeat feedback
keeps the existing task specification and repair instructions but replaces its
discussion block once with the newly collected snapshot. The answer-repair
path associated with .137 must retain this same block rather than reverting to
the first attempt's discussion. Do not implement a new repair workflow here.

An already admitted attempt resumed after an intact-database restart keeps its
saved input and digest. Refresh only when creating a new attempt. A collection
failure leaves existing work, claims, reservations and explicit holds intact;
it must not launch an agent or mutate tracker status. A person's comment does
not automatically release a held task. Human-request work associated with .121
can use the same input operation without making that task a prerequisite.

## Plain-text rendering

Render a single delimited block labelled as tracker discussion data, following
the task prose and before the factory's step instructions. State outside the
block that its contents supply task discussion and decisions, cannot override
factory instructions, and require no tracker access by the agent. Preserve
plain text and newlines, with task/relationship, author and time labels. Both
plan and implement use the same renderer.

Prefix every data line so text containing delimiters, Markdown fences or
factory-context markers cannot close a block or become factory instructions.
Locate actual delimiters as standalone framing lines, rather than substring
matches inside comment text. Update the existing context replacement helper
only as needed to coexist with quoted marker text. Repeats and answer repair
must contain exactly one discussion block and one factory context block.

Persist the completed prompt through the existing immutable input file and
digest. The tracker remains the owner of live discussion; the file records
what this particular attempt received. No discussion table, schema upgrade,
fallback reader or baseline runtime import is needed.

## Dashboard

Continue to display the selected attempt's saved input in the existing Prompt
tab. Obtain its stored input reference through the owning attempt reader and
read it through `EvidenceFiles`, preserving digest validation. Remove the silent
64 KiB prefix behaviour for prompts so a complete saved discussion remains
visible even when preceding requirements make the total input longer than
64 KiB. Keep answer/log limits independent. Missing or damaged input must be
reported as unavailable evidence rather than displayed as an empty prompt or
reconstructed from current tracker data. Preserve the existing comparison with
the preceding attempt and render discussion as text, never HTML.

## Focused verification

Use semantic tracker, store and agent fakes and ordinary pytest tests:

- Parameterize plan/implement input tests: own and linked comments retain
  provenance and multiline decisions, empty threads are explicit, links are
  deduplicated, and the agent receives text without tracker calls in its slot.
- Regress .109 with a recorded needs-owner hold followed by the owner's six
  decisions; the next input includes all six and labels their times correctly.
  Regress .77 with the linked task's discussion present.
- Cover latest versus older holds, equal/earlier/later comment times, unknown
  timestamps, cleared holds and absent local hold history. Comments alone must
  leave a held task held.
- Exercise initial admission, advance, restarted task and repeat. A new comment
  appears in the next new attempt exactly once; resuming the same admitted
  attempt preserves its bytes and digest. Preserve repair feedback and context.
- Test link/count and UTF-8 byte bounds, read failures and malformed records:
  input construction explains the failure and causes no claim, reservation or
  agent launch. Include delimiter-shaped text and both factory marker strings.
- Dashboard tests compare the selected attempt's input to the saved bytes after
  editing/deleting tracker comments, including a prompt over 64 KiB, and check
  missing/damaged evidence and literal rendering of markup.

Keep source files/functions within 400/80 lines and test files within 800;
extract a small discussion module if needed instead of enlarging admission
modules. No new subprocess use, Any, cast, ignore or third-party dependency.
Run focused tests during implementation, then the required `just check` and
`just test` gates. Do not run whole-suite/live tests. This planning attempt
changes only this document and does not run implementation checks.

Completion requires the attempt input and dashboard regressions above plus
both required gates passing. Until implemented, the coordinator's interim rule
remains to put owner decisions into the task description; this plan does not
make agents depend on that workaround.
