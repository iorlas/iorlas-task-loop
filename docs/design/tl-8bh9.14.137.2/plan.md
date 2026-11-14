# Header
tl-8bh9.14.137.2 @ ddd02a30f27d46341168b567777fcb23529b6860
Depth: small; one durable successor behaviour.
Owner decision: none missing. Dependency: none unlanded.
Evidence budget: 6 calls.
Size: 15 changed files with tests/artifacts; 1 behaviour; 80 implement calls.

## Outcome and non-goals
Add durable repair admission. Typed failures and session continuation exist; successor admission is missing. Routing/holds: .137.3.

## Settled decisions
- Consume AnswerFailureData; name its rule in repair input.
- Retain session, slot, claim, settings and original deadline.
- Repair preserves verification-repeat numbering and caps.
- Reuse entry registration and recovery reconciliation.

## Open decisions
- None.

## Change map
- src/taskloop/answer_repair.py (new): AnswerRepair; custody/files/store.
- src/taskloop/answer_repair_models.py (new): typed requests, outcomes and context.
- src/taskloop/answer_repair_store.py (new): own repair links and admission.
- src/taskloop/attempt_store.py: AttemptStore; successor insertion/reservation transfer.
- src/taskloop/factory_schema.py: SCHEMA; unique links/version bump.
- src/taskloop/attempt_types.py: Admission; repair context.
- src/taskloop/attempt_loads.py: AttemptLoads; restore context.
- src/taskloop/attempt.py: Attempts._start/_launch; resume preserving work.
- src/taskloop/composition.py: compose AnswerRepair beside open_chain/open_continuation.
- tests/steps/test_answer_repair.py (new): durable admission.
- tests/steps/test_attempt_answers.py: repair launch/capture.
- tests/steps/test_factory_schema.py: constraints/version pin; update pin artifact if separate.
- docs/design/tl-8bh9.14.137.2/plan.md: plan.

## Read list
- src/taskloop/answer_failures.py:1-77 — failures.
- src/taskloop/admit_chain.py:58-183 — repeats.
- src/taskloop/admit_rows.py:1-120 — insertion.
- src/taskloop/attempt_store.py:68-236 — fences.
- src/taskloop/factory_schema.py:49-155 — DDL.
- src/taskloop/factory_schema.py:275-325 — successors.
- src/taskloop/attempt_types.py:110-205 — context.
- src/taskloop/attempt_loads.py:1-180 — loading.
- src/taskloop/attempt.py:161-301 — execution.
- src/taskloop/agents/launch.py:101-138 — resume.
- src/taskloop/composition.py:75-110 — continuation caller.
- src/taskloop/composition.py:265-285 — admission caller.
- src/taskloop/repeat.py:150-175 — repeat caller.
- src/taskloop/launch.py:150-245 — dispatch.
- src/taskloop/recovery/continue_attempt.py:24-115 — reconciliation.
- src/taskloop/recovery/native.py:25-83 — continuation.
- tests/steps/test_admit_chain.py:1-160 — admission fixtures.
- tests/steps/test_attempt_answers.py:1-150 — answer fixtures.
- tests/steps/test_factory_schema.py:1-90 — pin.
- tests/steps/test_continuation.py:1-130 — restart fixtures.

## Contract
Intent: save input before the transaction. Under custody recheck rejection, complete matching session, process liveness, reservation, deadline, drain and successors. Atomically insert one linked successor and transfer reservation, fencing its predecessor. Reject repair-of-repair; retries return the saved successor.
Effect: launch outside the transaction with saved session/settings and remaining time; preserve work/evidence. Reconcile ambiguous launches first; returned executions retry capture only.
Result: typed admitted/existing/refused/unavailable outcomes with explanations; validate saved context. Drain/discard for schema upgrade.

## Work packages
1. Models/schema/store: unique successor and frozen context.
2. Loading/launch/composition: resume through existing fences.
3. Tests: acceptance below; run just check and just test once each, last.

## Acceptance behaviours
- One repair retains the failed attempt's session, slot, claim, settings and deadline.
- Restart, races and lost acknowledgements converge on that successor without duplicate execution.
- Expired, conflicting or repaired work cannot launch another repair; capture retry preserves returned facts.
