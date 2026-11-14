# Header
Task: tl-8bh9.14.174.3; base: 63dd79089d87cb6346b11fffea52fb43360865e4
Depth: medium; three coupled resume behaviours.
Decision missing: none; unlanded dependency: none; evidence: 12 model calls.
Size: 16 changed files including tests/artifacts; 3 behaviours; 55 implement model calls.

## Outcome and non-goals
Connect digest and Git evidence to fresh admission after a hold. Select implementation before capturing input/settings. Preserve ordinary advances/repeats. No schema, dependency or scheduling-policy changes.

## Settled decisions
- A3 is the integration boundary; canonical digest persistence and the read-only Git evaluator are already implemented.
- Reuse requires matching task content, a successful recorded plan belonging to this repo/tracker task, and accepted committed Git evidence at the selected task-branch tip.
- Plan evidence lookup crosses later implement attempts; input context still uses the latest attempt.
- Missing or invalid reusable evidence selects planning; unavailable evidence stops admission with its explanation.
- Apply overrides once to the selected step's settings; persist those choices.
- Preserve explicit holds and existing claim, reservation and dispatch fences.

## Open decisions
- None.

## Change map
- `src/taskloop/resume_plan.py` (new): typed helper integrated by `AttemptAdmission.admit` and `Attempts._prepared`.
- `src/taskloop/admit.py`: `AdmitRequest`, `_Prepared`, `admit`, `_commit`; select step/input/settings and fence reuse evidence.
- `src/taskloop/attempt_loads.py`: `AttemptLoads`; scoped successful-plan lookup, also usable under admission lock.
- `src/taskloop/plan_reuse.py`: `evaluate`, `_evaluate`; validate/diff an explicit source commit; preserve HEAD default.
- `src/taskloop/operations.py`: `_admit`; production request producer passes settings and overrides for fresh selection.
- `src/taskloop/attempt.py`: `Attempts.__init__`, `_prepared`; validate reuse before setup/dispatch.
- `src/taskloop/composition.py`: `open_admission`, `open_attempts`; wire shared validation ports.
- `tests/steps/test_admit.py`: `request`, `admission`; adapt producers; cover settings and races.
- `tests/steps/test_operations.py`: `Admission`; adapt fake and verify override forwarding.
- `tests/steps/test_plan_reuse.py`: `planned`, evaluator callers; explicit-tip validation from a parked worktree.
- `tests/steps/test_resume_plan.py` (new): integrate helper/entry with existing `AttemptAdmission` and `Attempts` fixtures.
- `tests/steps/test_round_holds.py`: `factory`, `asks`, `ready`; repeated holds/content-change coverage.
- `src/taskloop/agents/settings.py`: consult `StepSettings.for_step`, `apply` for settings ownership.
- `src/taskloop/task_content_store.py`: consult `TaskContentStore.read` for immutable digest evidence.
- `src/taskloop/admit_rows.py`: consult `insert_attempt`; preserve plan-only digest writes.
- `src/taskloop/prepare.py`: consult `_take`, `_state_refusal` for existing branch checks.
- `src/taskloop/attempt_entry.py`: consult `_registered` for reconstruction through `open_attempts`.
- `src/taskloop/admit_chain.py`: consult `ChainAdmission`, `NextAdmission`; preserve repeat/advance callers.
- `docs/design/tl-8bh9.14.174.3/plan.md`: bounded implementation plan.
- `docs/design/tl-8bh9.14.174.3/plan-metadata.json`: source commit and consulted paths.

## Read list
- `src/taskloop/admit.py:55-112` — request and prepared evidence.
- `src/taskloop/admit.py:152-209` — input production and observation.
- `src/taskloop/admit.py:267-318` — authoritative admission write.
- `src/taskloop/operations.py:471-496` — production request caller.
- `src/taskloop/agents/settings.py:135-166` — settings selection and overrides.
- `src/taskloop/attempt_loads.py:100-123` — scoped earlier-attempt reads.
- `src/taskloop/task_content_store.py:10-24` — digest port.
- `src/taskloop/plan_reuse.py:41-126` — typed evaluator and scoped diff.
- `src/taskloop/attempt.py:61-85` — entry dependencies.
- `src/taskloop/attempt.py:155-228` — preparation-to-dispatch boundary.
- `src/taskloop/composition.py:112-136` — entry composition.
- `src/taskloop/composition.py:233-256` — discussion and admission composition.
- `src/taskloop/admit_rows.py:22-29` — atomic digest insertion.
- `src/taskloop/prepare.py:190-218` — taking the observed source.
- `src/taskloop/prepare.py:230-261` — branch/base validation.
- `src/taskloop/attempt_entry.py:153-180` — persisted entry reconstruction.
- `src/taskloop/admit_chain.py:71-105` — repeat boundary.
- `src/taskloop/earlier_attempt.py:8-19` — existing evidence identity.
- `src/taskloop/attempt_store.py:68-69` — inherited store reads.
- `tests/steps/test_admit.py:115-169` — direct request producers and execution fixture.
- `tests/steps/test_operations.py:76-88` — request fake and captured choices.
- `tests/steps/test_plan_reuse.py:26-65` — committed-plan semantic fixture.
- `tests/steps/test_round_holds.py:1-62` — integrated hold fixture and tracker changes.
- `src/taskloop/implement_step.py:115-148` — implementation input contract.
- `src/taskloop/attempt_types.py:49-61` — existing step/effect types.

## Contract
Intent: one collected discussion/digest and selected Git source produce typed plan/implement/unavailable selection, explanation, source commit and optional plan identity/digest. Reuse existing vocabularies; additional closed results use enums and database-facing evidence uses pydantic.

Effect: scoped captured/verified plan evidence must match the committed artifact at the selected source. Do not bypass a newer failed plan or saved work. Read digests through `TaskContentStore`; implementation creates none. Recheck plan identity/revision and latest-attempt fence under the admission lock; Git/tracker reads stay outside it.

Result: atomically store chosen step, input/settings, sequence and reservation. Existing `after_commit` carries the observed source, with fresh numbering and no fabricated advance via `previous_attempt_id`. Preserve earlier-answer context. Stale database evidence refuses admission.

Entry: after branch preparation, reconstruct eligibility from stored source/task identity and plan evidence, recollect content and validate the prepared tip before setup/dispatch. Changed tip/digest/eligibility refuses dispatch; read failure stays unavailable. A later fresh admission reevaluates to plan; never switch a stored implement prompt in place. Restart requires no coordinator memory or new stored fields.

## Work packages
1. Add `resume_plan.py`, scoped `attempt_loads.py` lookup and explicit-tip `plan_reuse.py` evaluation; focused coverage closes evidence selection in A1/A2.
2. Update `admit.py`, `operations.py`, composition and request producers/tests; close A1 and admission races in A2. Keep reuse orchestration in the new helper to respect admission's file cap.
3. Wire entry validation in `attempt.py`/composition and add helper/round tests, including database reopen; close A2/A3. Run final `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each with pipeline failure preserved.

## Acceptance behaviours
A1: A released held task with matching digest and valid committed plan starts implementation directly, with implementation prompt/settings and overrides; absent, invalid or changed evidence starts planning, while unavailable reads prevent dispatch with an explanation.
A2: Concurrent plan/attempt changes cannot commit stale selection; branch/content changes between admission and entry prevent implementation dispatch, and reopening the intact database enforces the same checks and stored choices.
A3: Two successive cleared implementation holds with unchanged task and cited paths add no plan attempt or plan-agent invocation; changing canonical task content before the next resume adds a new plan attempt, while hold bookkeeping alone leaves reuse eligible.
