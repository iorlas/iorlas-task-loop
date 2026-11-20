# Header
Task: tl-8bh9.14.171.1.1
Base: ea06b229f3c7761ec7769a1bc12a907c3bd4df36
Depth: medium; two vocabulary owners plus codec
Decision/dependency: none missing/unlanded.
Evidence budget: 12 model calls.
Size: 13 files incl tests/artifacts; 2 behaviours; ~40 implement model calls.

## Outcome and non-goals
Give plan/implement one enum owner and text codec. Preserve stored spellings, strict earlier-attempt validation and visible behaviour. Broader factory and presentation migrations belong to sibling consumer tasks. Check retains separate non-agent handling. No schema change or shelf work.

## Settled decisions
- `taskloop.step` owns `Step`, a stdlib `StrEnum` with `PLAN` and `IMPLEMENT`: exactly the values currently shared by the Literal and AgentStep.
- Remove both previous definitions and update direct imports; leave no compatibility alias or re-export in attempt_types.
- Keep this module independent of settings, attempts and step implementations to avoid their existing import cycle.
- Retain the current string-facing `StepSettings.for_step` boundary while its callers migrate separately; it delegates validation to the shared codec and selects by enum member.
- The supplied discussion assigns the remaining factory and presentation migrations to tl-8bh9.14.171.1.2 and tl-8bh9.14.171.1.3. Neither is a prerequisite here.
- Sequencing, settings selection and earlier-attempt storage already exist; vocabulary integration remains.

## Open decisions
- None.

## Change map
- `src/taskloop/step.py` (new): `Step`, `decode_step`, `encode_step`; shared vocabulary integrated by settings, steps, resume_plan, earlier_attempt and attempt_loads.
- `src/taskloop/attempt_types.py`: remove the `Step` Literal; other attempt fields remain for the factory consumer task.
- `src/taskloop/agents/settings.py`: remove `AgentStep`; `StepSettings.for_step` uses the codec and shared members.
- `src/taskloop/steps.py`: import shared `Step`; construct `PLAN` and `IMPLEMENT` with members; preserve sequencing signatures and CHECK.
- `src/taskloop/resume_plan.py`: `Selection.step` imports and returns shared members for both outcomes.
- `src/taskloop/earlier_attempt.py`: `EarlierAttempt.step` imports the shared enum and retains strict model validation.
- `src/taskloop/attempt_loads.py`: `AttemptLoads.earlier` decodes row text before constructing EarlierAttempt.
- `tests/steps/test_step.py` (new): codec and strict model contracts, integrated with Step and EarlierAttempt.
- `tests/steps/test_agent_settings.py`: exercise `StepSettings.for_step` for strings, members and invalid input.
- `tests/steps/test_steps.py`: assert StepKind member identity and Selection's two producer outcomes; retain order/check coverage.
- `tests/steps/test_attempt_loads.py`: assert earlier evidence returns the enum member without changing stored text or scope.
- `src/taskloop/agents/config.py`: consult `display`, the string-producing settings caller; preserve output.
- `src/taskloop/admit.py`: consult `_input`'s Selection/settings integration; preserve settings and input.
- `src/taskloop/operations.py`: consult `_admit`, the advancement/settings caller; check stays on its separate branch.
- `src/taskloop/attempt_store.py`: consult `_earlier_row`, the row producer; SQL stays unchanged.
- `src/taskloop/earlier_input.py`: consult `EarlierInput.attach`, the earlier-step consumer; preserve answer lookup and rendering.
- `src/taskloop/attempt_reads.py`: consult `AttemptRow` and boundary helpers; broader row conversion is deferred.
- `src/taskloop/harness_choice.py`: consult existing lightweight enum ownership pattern; no edit.
- `tests/steps/test_earlier_input.py`: consult existing earlier-evidence integration coverage; no edit.
- `docs/design/tl-8bh9.14.171.1.1/plan.md`: implementation contract.
- `docs/design/tl-8bh9.14.171.1.1/plan-metadata.json`: preparation evidence.

## Read list
- `src/taskloop/attempt_types.py:1-66` — old vocabulary and imports to remove.
- `src/taskloop/agents/settings.py:1-12` — imports to replace.
- `src/taskloop/agents/settings.py:125-160` — AgentStep and settings selector.
- `src/taskloop/steps.py:14-96` — sole StepKind producers and existing order/check contract.
- `src/taskloop/resume_plan.py:8-45` — Step import, Selection producer and its consumers.
- `src/taskloop/earlier_attempt.py:1-19` — strict Pydantic edge accepting Step.
- `src/taskloop/attempt_loads.py:126-146` — stored earlier-attempt conversion.
- `src/taskloop/attempt_store.py:58-64` — earlier-row producer and column order.
- `src/taskloop/agents/config.py:104-120` — settings caller and text presentation.
- `src/taskloop/admit.py:160-185` — Selection consumer and settings caller.
- `src/taskloop/operations.py:470-492` — advancement settings caller and separate check branch.
- `src/taskloop/earlier_input.py:55-82` — EarlierAttempt consumer and error translation.
- `src/taskloop/attempt_reads.py:35-75` — existing row types and current text fields.
- `src/taskloop/harness_choice.py:1-22` — dependency-light enum precedent.
- `tests/steps/test_steps.py:1-58` — existing sequencing/check tests and immediate producer assertions.
- `tests/steps/test_agent_settings.py:20-118` — defaults, selection and invalid configuration coverage.
- `tests/steps/test_attempt_loads.py:61-83` — released earlier-evidence fixture and assertions.
- `tests/steps/test_earlier_input.py:28-64` — repeated earlier-input behaviour exercised by enum propagation.

## Contract
Intent: `Step` represents the two agent-step values already accepted by Step and AgentStep. `decode_step(text: str) -> Step` accepts only their exact persisted spellings; no case folding, alias or fallback. `encode_step(step: Step) -> str` returns that spelling. Invalid text raises ValueError through the one codec.

Effect: enum members flow through StepKind.step, Selection.step and EarlierAttempt.step. StepSettings.for_step validates at its retained text boundary, then selects the same immutable AgentSetting by member. AttemptLoads.earlier converts the stored step through decode_step before invoking strict Pydantic validation. EarlierAttempt's direct in-process construction requires a member; do not weaken its strict configuration or add an independent string validator.

Result: encode/decode preserves member identity and text. Earlier-attempt reads retain scope and identity fences. CHECK stays outside this agent vocabulary, rejected by settings as before. No IO, state transition or stored field is added.

## Work packages
1. Add `step.py`, remove the definitions in `attempt_types.py` and `agents/settings.py`, update direct imports and StepKind/Selection producers in `steps.py`, `resume_plan.py`, `earlier_attempt.py`. Add focused codec and strict-model tests in new `test_step.py`. Closes A1.
2. Route `StepSettings.for_step` and `AttemptLoads.earlier` through the codec. Update `test_agent_settings.py`, `test_steps.py` and `test_attempt_loads.py` for member identity, both selection outcomes and preserved boundary behaviour. Consult every caller listed above. Closes A2.
3. After edits and focused validation, run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last; resolve any failure within this scope before completion. No live tests.

## Acceptance behaviours
A1: One Step enum replaces both definitions; plan and implement round-trip through one codec with member identity preserved, while unknown, empty, case-altered and check text are rejected.
A2: StepKind and Selection produce members, strict earlier-attempt reads return members, and string/member settings requests select the same settings; stored/displayed spellings, sequencing and check's non-agent behaviour remain unchanged.
