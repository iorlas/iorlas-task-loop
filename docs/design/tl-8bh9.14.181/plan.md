# Carry earlier attempt answers and saved work into fresh attempts

## Decision and scope

Every agent attempt after an earlier agent attempt of the same task receives the earlier attempt's stored disposition and explanation, its retained work commit and that commit's changed file names. Paste at most 1,500 characters of the explanation and include the exact instruction: “Start from the work in that commit; do not re-read what the explanation already tells you.” Launch a fresh session; never resume the earlier agent session to obtain this context.

This is one bounded change to attempt input construction and its focused contracts. It covers repeats, a task restarted after a hold or abandon, and advancement from plan to implementation. It does not change task eligibility, hold decisions, WIP publication, or the meaning of a completed result. Existing source preparation still decides how retained task work is checked out and reconciled with the current source.

## Current code and sources of truth

At source commit `7976bd5a7ac17d707f103677272357c8cc67fc37`, `repeat.StepRepeat._input` renders refusal feedback over attempt 1's original input. It does not include the preceding answer or a saved-work file list. `admit.AttemptAdmission` builds a new plan input, and `admit_chain.NextAdmission` builds the next step's input independently. `previous_attempt_id` links only repeats; task `seq` also orders advancement and restarts, so following only the repeat chain misses later attempts of the same task.

`AttemptStore` owns execution records and digest-bearing answer references. `hold_facts.explanation` already demonstrates decoding the stored answer through the owning step's decoder. That evidence is the source of disposition and explanation; do not ask the agent to summarize itself or infer either from transcripts, task comments, or refusal text.

`HoldStore.saved` owns factory-created WIP commit identities (`wip.SavedCommit`); Git owns each commit's changed paths. WIP identities cannot come from agent-declared `paths` or `message`: the factory saves unfinished work after the answer. Combine these existing owners when composing the next input, without modifying the original answer evidence or adding agent answer fields. `agents.launch.AgentLaunch.build` already constructs a new session through `ids.session()`; preserve and test that behavior. `Attempts._resume` reconciles captured execution, rather than resuming an agent conversation, and must retain that restart safety.

## Implementation

1. Add a small typed read/composition path for the latest earlier agent attempt of the same registered repo and tracker task identity, ordered by task `seq`. Repeats select their immediate predecessor; other admissions select the latest earlier agent attempt, excluding checks attempts and other tasks. Read through owning stores, retaining their identity and generation fences. Decode the original stored answer using its step's existing schema and decoder, sharing the existing explanation-reading behavior without making the input path import hold comment rendering. No SQL or database connection escapes a store.

2. Read the predecessor's factory-recorded saved commit for its slot from `HoldStore`. Use the latest applicable save if reconciliation recorded more than one. Read that exact immutable commit's changed file names through the owning Git API, including added, modified, deleted and renamed paths; use names only, with deterministic ordering and safe escaping. Do not enumerate the whole repository, read source file contents, scan Git history for the task id, or use the answer's declared commit paths as a substitute for the actual commit's paths.

   Some predecessors have no WIP commit: a successful earlier step has its recorded result commit, while an unsafe repeat can retain uncommitted work in the same reserved slot before any hold saves it. Include the recorded result commit and its names when available, identifying it accurately; otherwise state explicitly that no retained commit was recorded and that existing slot work remains to be assessed. Do not fabricate a SHA, treat a WIP commit as a finished result, or introduce a new save/reset operation merely to render the input. When a WIP save exists, its full SHA and complete changed-name list are mandatory.

3. Render one factory-authored block containing earlier attempt identity, disposition, explanation truncated to 1,500 characters, commit identity and kind, and changed file names. Clearly delimit answer text and filenames as data with escaping consistent with existing prompt data boundaries. Preserve the exact start-from-commit instruction when a commit is supplied; use accurate guidance when no commit exists. An invalid or absent prior answer is reported as unavailable, never invented. Distinguish a legitimately absent save from failure to read a recorded save or its Git object; an unreadable recorded fact uses the existing typed input failure with an explanation instead of silently dropping it.

4. Attach this block in all three input paths: new plan admissions for previously attempted tasks, next-step admissions, and repeats. Keep the original task text and required step warnings intact. A repeat replaces any older handoff block with its immediate predecessor's facts; it must not nest summaries or repeatedly paste earlier explanations through attempt 1's input. A first-ever task attempt has no earlier-attempt block. Capture the selected predecessor before admission and recheck that it is still current in the existing short admission transaction, so a concurrent attempt cannot attach another predecessor's facts. File and Git reads occur outside write transactions.

5. Store the complete composed input through the existing digest-bearing evidence writer before admission. Dispatch-time `input_context.refresh` must preserve the block in the actual launched input. Redispatch/reconciliation of an admitted attempt retains the same selected facts rather than fetching a newer answer. Wire dependencies through the existing composition roots and semantic ports. No new database schema, state reconstruction, transcript parser, subprocess wrapper, session replay, or speculative scheduler behavior is needed.

## Focused verification

Extend the behavior fixtures in `tests/steps/test_repeat.py`, `tests/steps/test_admit_chain.py` and `tests/steps/test_round_holds.py` and their semantic Git/agent fakes, using a separate focused test module if needed to retain file limits. Add only tests that exercise observable contracts:

- An unsafe repeat receives its predecessor's stored disposition and explanation, although its refusal differs. A second repeat receives the immediately preceding answer once, without nested blocks or mutation of earlier input evidence.
- Explanations below, at and above 1,500 characters, including Unicode, preserve the intended character limit. Rendered names and explanation data cannot terminate their surrounding data block or masquerade as instructions.
- A held task restarted into a free slot receives the factory-recorded WIP SHA and the actual changed names, including files omitted from the agent's answer, deletions and renames. Unrelated repository files and file contents are absent. Advancement into implementation also receives the prior plan answer and recorded commit.
- A different task and a first attempt receive no earlier facts. A predecessor without a valid answer or without a saved commit is represented accurately. An unreadable digest-checked answer or recorded Git object is distinguished from legitimate absence; existing typed refusal/unavailable behavior remains reviewable.
- Admission races do not store stale predecessor facts. Restart/reconciliation and launch context refresh preserve the admitted block. Every newly admitted successor starts a fresh harness session and never passes the predecessor's session identity as a resume input; replaying captured results does not launch an agent again.

Keep production files within 400 lines, functions within 80 lines and test files within 800 lines; extract the shared input behavior instead of expanding already large orchestration modules. Use existing typed decoders and pydantic v2 edge models, with no new escape types.

Run `just check` and `just test` as the required focused gates during implementation, using the declared successor environment and the existing focused test contracts. Do not run whole-suite/live agent tests. This documentation-only planning step does not run implementation gates.

## Acceptance and observation

Automated acceptance is the saved-input and actual-launch-input contract: a later attempt carries the stored earlier answer (explanation capped at 1,500 characters), recorded retained commit and its names, plus the required instruction, while starting a fresh session.

For the next real repeats with editable work, inspect their existing execution artifacts through the owning readers and count model calls through the first repository edit. The target is a first edit within eight calls. Record attempt identity, call count and whether the supplied commit was used in implementation evidence. This is an observed agent outcome, not something a fake harness proves; do not claim the saving before observing it or add a new control-state owner for measurement. If the target is missed, inspect the supplied block and the observed extra reads before proposing further changes. Attempts legitimately refusing without an edit are recorded separately and do not establish the first-edit target.

## As built

`answer_read` shares the owning step's stored-answer decoder with hold presentation. `AttemptStore.earlier` selects
the latest agent attempt for the registered repo and tracker task identity; admission rechecks its fenced identity
and revision in the existing transaction. `earlier_input` composes the escaped answer and retained commit names
outside that transaction, using `HoldStore` saves before a recorded result commit. Repeats strip the older block
before composing the immediate predecessor's facts. Dispatch refresh and captured-result reconciliation retain
the admitted evidence, and agent launches remain fresh sessions.

Focused contracts cover unsafe repeats, successive repeats, Unicode explanation limits, escaped answer and filename
data, actual saved changes across slots, plan advancement, absent/invalid/unreadable evidence, missing recorded
Git objects, admission races, input refresh and captured-result replay. No live repeats were launched during this
implementation. The eight-call first-edit target and token saving remain to be measured on the next real repeats
through their existing execution readers, as described above.
