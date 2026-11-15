# Header
Task: tl-8bh9.14.171.1.2
Base: c0d83f93d95f67487e6e3a8f70ee28da226ee324
Depth: medium; one migration across consumers.
Decision missing: no. Dependency: landed.
Evidence budget: 12 model calls.
Size: 14 changed files including tests/artifacts; 1 independent behaviour; 40 implement model calls.

## Outcome and non-goals
Step.PLAN, Step.IMPLEMENT, their codec, StepKind.step and earlier-attempt decoding already exist. Replace remaining literal dispatch, untyped admission facts and step comparisons in factory consumers. Preserve sequencing, repeats, verification and land results. Presentation/configuration belongs to the sibling task. Keep CHECK separate; no enum expansion or schema change.

## Settled decisions
- Reuse taskloop.step.Step and its encode_step/decode_step codec; no second vocabulary.
- PLAN and IMPLEMENT remain the only agent kinds; CHECK keeps its separate attempts and execution path.
- Decode agent text before enum dispatch; retain current text-taking boundaries.
- Admission facts passed to agent execution carry Step; stored spellings remain identical.
- Preserve eligibility, evidence, fencing and effect ordering.

## Open decisions
- None.

## Change map
- `src/taskloop/step.py` — Step, decode_step, encode_step: reuse unchanged.
- `src/taskloop/steps.py` — kind, ORDER, following, next_step, is_agent: enum dispatch and agent results; retain CHECK and rejection semantics.
- `src/taskloop/admit.py` — task_text, AttemptAdmission: carry the selected enum into input generation and insertion.
- `src/taskloop/admit_chain.py` — _Ready, NextAdmission._previous/_admit, ChainAdmission._takeover_open: carry Step and compare enum members.
- `src/taskloop/admit_rows.py` — Task, Previous, Current: declare validated Step fields.
- `src/taskloop/admit_store.py` — _decode, insert_attempt: decode/encode at the owning boundary and use Step.PLAN for evidence requirements.
- `src/taskloop/attempt_types.py` — Admission.step: declare Step.
- `src/taskloop/attempt_loads.py` — AttemptLoads._load: decode Admission.step; retain existing earlier decoding.
- `src/taskloop/repeat.py` — input preparation: compare Step.PLAN; preserve discussion collection.
- `src/taskloop/check_repeat/store.py` — CheckRepeatStore.state/admit: compare Step.IMPLEMENT and encode the inserted step.
- `src/taskloop/answer_read.py` — read: normalize agent text before kind dispatch; preserve absent/non-agent answers.
- `src/taskloop/verifier.py` — Verifier._settle: audit kind dispatch, preserving verification.
- `src/taskloop/land.py` — following/CHECK caller: audit eligibility unchanged.
- `src/taskloop/check_admit.py` — next_number: audit following/CHECK eligibility.
- `src/taskloop/operations.py` — following caller: audit advance routing.
- `src/taskloop/attempt.py` — kind callers: audit launch and completion dispatch.
- `src/taskloop/factory_commit.py` — _review: audit kind dispatch.
- `src/taskloop/recovery/native.py` — kind callers: audit recovery dispatch.
- `src/taskloop/attempt_status.py` — following callers: audit status boundaries.
- `src/taskloop/hold_facts.py` — CHECK: retain hold facts.
- `src/taskloop/verdict.py` — judge: retain StepKind input.
- `src/taskloop/plan_reuse.py` — evaluate/_evaluate: retain PLAN calls.
- `src/taskloop/check_repeat/repair.py` — failed_check_feedback: retain dispatch.
- `tests/steps/test_steps.py` — sequencing and kind cases: assert enum identity and existing boundary behaviour.
- `tests/steps/test_admit_chain.py` — advance/repeat cases: assert decoded enum facts alongside unchanged persisted text and transitions.
- `docs/design/tl-8bh9.14.171.1.2/plan.md` — new implementation handoff.
- `docs/design/tl-8bh9.14.171.1.2/plan-metadata.json` — new preparation metadata consumed by plan reuse.

## Read list
- `src/taskloop/step.py:1-17` — existing enum and codec.
- `src/taskloop/steps.py:29-97` — kinds, sequence and dispatch.
- `src/taskloop/admit.py:113-118` — input producer; follow insertion when editing.
- `src/taskloop/admit_chain.py:118-310` — repeat and advance inputs, fences and inserts.
- `src/taskloop/admit_rows.py:20-78` — admission row models.
- `src/taskloop/admit_store.py:57-144` — insertion and row decoding.
- `src/taskloop/attempt_types.py:121-136` — Admission contract.
- `src/taskloop/attempt_loads.py:137-195` — earlier and Admission producers.
- `src/taskloop/repeat.py:119-143` — repeat discussion and kind selection.
- `src/taskloop/check_repeat/store.py:32-110` — failed-check eligibility and insertion.
- `src/taskloop/answer_read.py:1-16` — text-taking answer reader.
- `src/taskloop/verifier.py:170-195` — verification dispatch.
- `src/taskloop/land.py:108-132` — done implement/check gate.
- `src/taskloop/check_admit.py:91-111` — predecessor eligibility.
- `src/taskloop/operations.py:383-421` — following consumer and advance routing.
- `src/taskloop/attempt.py:238-260` — launch dispatch; follow completion caller if affected.
- `src/taskloop/factory_commit.py:170-190` — rules dispatch from Admission.
- `src/taskloop/recovery/native.py:22-44` — recovery dispatch from Admission.
- `src/taskloop/attempt_status.py:157-205` — CHECK status boundary; consult completion following caller if affected.
- `src/taskloop/hold_facts.py:112-132` — CHECK hold facts.
- `src/taskloop/verdict.py:14-25` — StepKind integration.
- `src/taskloop/plan_reuse.py:75-110` — PLAN rules/artifact consumers.
- `src/taskloop/check_repeat/repair.py:55-75` — feedback integration.
- `tests/steps/test_steps.py:42-60` — sequencing and non-agent checks contract.
- `tests/steps/test_admit_chain.py:138-312` — admission, advancement and repeat examples.

## Contract
Intent: route eligible tasks using Step. Effect: decode admission row fields before strict model construction; encode inserted values in the owning store, preserving malformed-row error translation. Result: enum-bearing Admission and admission facts, unchanged SQL values and columns.

Intent: select the current/next kind. Effect: use enum members in agent dispatch and return enum members for agent successors; keep the existing CHECK boundary and terminal None. The text-taking functions retain their current valid-input, unknown-input and not-done behaviour, including is_agent returning false for CHECK and unknown text. Result: fresh tasks start at PLAN; completed PLAN advances to IMPLEMENT; completed IMPLEMENT routes to checks; completed CHECK terminates.

Intent: repeat or finish work. Effect: retain evidence requirements, caps, failed-check repair and published/released eligibility. Result: unchanged actions, transactions and land decisions. Listing/presentation models retain text contracts; normalize their agent spellings at consumption.

## Work packages
1. Update steps.py, admission models/stores, Admission and its loader. Preserve text-taking integration points listed above. Close A1 through enum identity, boundary decoding and unchanged sequence assertions in test_steps.py and test_admit_chain.py.
2. Update repeat.py and check_repeat/store.py; audit verifier.py, land.py, check_admit.py and all listed kind/following callers. Extend existing chain tests only where enum identity or storage decoding lacks coverage. Close the remaining A1 cases for repeats, verification and land.
3. Run focused existing sequencing/admission/repeat/check/verification/land tests as needed. Finally run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, retain failure status, and fix any relevant failure before handoff.

## Acceptance behaviours
- A1: Factory dispatch uses shared Step members and enum-bearing admission facts while preserving fresh start, done-only advancement, plan repeat evidence, implement repeats, failed-check repair, verification and land eligibility; CHECK never acquires an agent kind, and persisted spellings and unknown-input outcomes stay unchanged.
