# Depth
Large: the supplied code map names more than 60 files; the task specifies one cohesive behavior, generated answer rules. No owner decision is missing and no dependency is explicitly unlanded. Evidence budget: 20 model calls. The code map is orientation evidence, not an implementation change list; there are no independent parts requiring an early split.

## Size
Estimated changed files: 3, including this new plan artifact, one existing source file and one existing test file. Independent behaviors: 1. Estimated model calls for one implement attempt: 25. Acceptance: every dispatched plan and implement input carries its own response schema and applicable disposition requirements, including retry routes, with focused contract coverage. These estimates fit the limits of 60 files, 3 behaviors and 100 calls.

## Outcome
Protect the existing answer rules in generated step inputs with focused tests using the actual step definitions through the launch boundary. The complete dispatched input is the step prose plus the schema appended by `AgentLaunch.build`; the admitted input alone deliberately does not contain that appended schema.

## Existing implementation and scope
`plan_step` and `implement_step` already own their answer schemas, decoders and disposition guidance. `steps` exposes those definitions; `admit.task_text` generates task prose, `EvidenceFiles.prepare` serializes the selected schema, and `Attempt._launch` passes both to `AgentLaunch.build`. The adapter appends the JSON-only instruction and serialized schema for all three supported harnesses. Repeat feedback retains the original step input; failed-check feedback retains implement guidance. Existing launch tests primarily use a generic object schema, while existing step tests check selected guidance and decoder tests check answer shapes separately. The missing coverage is their composition using real plan and implement schemas.

Retain this implementation rather than adding a second schema renderer or changing schema ownership. The plan schema already permits incomplete, but the plan's closing prose does not explain when to use it; add that missing instruction. Do not move the launch-time appendix: merge resolution also uses this adapter with its own answer schema. No dependency, schema version, vocabulary or AGENTS.md change is needed.

The owner's split makes tl-8bh9.14.185.1.2 (early-stop instructions), .1.3 (Read list generation), and .1.4 (code map generation) independent siblings. This task covers answer rules only. Existing Header/Change map plan-template work is outside scope; avoid assertions that freeze those unrelated sections. The supplied glossary definitions suffice; no glossary read is needed.

## Implementation
In `plan_step._closing_words`, add a concise instruction to answer incomplete and explain why when the planning work cannot be finished. Preserve needs_owner for the existing decision, infeasibility and scope-refusal conditions, and preserve the existing no-commit shape for both unfinished outcomes. This is instruction text only; do not change the decoder, schema or effect mapping.

Extend `tests/steps/test_agent_launch.py` using its existing `setting`, `EvidenceFiles`, `FixedIds`, launch-spec construction and cleanup conventions. Construct a minimal task and `InputContext` locally, obtaining step definitions through `steps.kind`, never by directly importing the owning step modules.

Generate plan and implement inputs through their public step interface. Exercise initial inputs, both recorded/unrecorded leftover retry forms through `feedback`, and the implement failed-check route through `failed_check_feedback`. Cross these applicable routes with the supported harness choices. Use semantic test data and inspect launch specifications; execute no external agent.

For each case, prepare the actual step schema with `EvidenceFiles.prepare` and build the launch specification. Inspect `spec.stdin` and parse only the terminal schema appendix using its fixed factory delimiter. Assert the appendix is present exactly once in these controlled inputs and is structurally equal to both the prepared schema file and `StepKind.answer_schema`. Assert the original generated input is preserved ahead of the appendix. Verify plan inputs advertise the five required keys and planned/unchanged/incomplete/needs_owner; implement inputs advertise four keys, omit plan_path, and use implemented in place of planned. Existing strict-schema tests remain the authority for detailed schema restrictions.

In those same generated inputs, assert the applicable disposition requirements: success lists the files and one-line commit message for the factory; unchanged applies when the requested result already exists and requires no edits; incomplete reports unfinished work; needs_owner explains an infeasible plan or required decision; only success requests a commit, while other outcomes use empty paths and a null message. Plan guidance names the expected plan path; implement guidance forbids listing plan.md and requires command results in explanation. Retain existing saved-work guidance across retries. Use focused semantic assertions rather than copying whole prompt snapshots or retesting every private renderer and decoder bound.

No new runtime or test modules are proposed. This plan.md is new; its implementation integration points are the existing test module and producers/callers listed below.

## Read list
- `src/taskloop/plan_step.py:99-115` — authoritative plan response keys and schema.
- `src/taskloop/plan_step.py:129-156` — decoder requirements and initial input producer.
- `src/taskloop/plan_step.py:188-200` — success, unchanged and refusal disposition guidance.
- `src/taskloop/plan_step.py:204-231` — plan retry input composition.
- `src/taskloop/implement_step.py:28-45` — authoritative implement response keys and schema.
- `src/taskloop/implement_step.py:95-124` — implement decoder and initial input producer.
- `src/taskloop/implement_step.py:147-162` — implement disposition, path and explanation requirements.
- `src/taskloop/implement_step.py:166-208` — leftover and failed-check retry producers.
- `src/taskloop/steps.py:28-74` — public step interface, schema wiring and failed-check caller.
- `src/taskloop/step_text.py:23-46` — shared retry frame and saved-work instructions.
- `src/taskloop/admit.py:119-124` — admitted step-input caller and discussion composition.
- `src/taskloop/attempt.py:218-228` — schema preparation and adapter launch caller.
- `src/taskloop/evidence_files.py:281-286` — serialization of the authoritative step schema.
- `src/taskloop/agents/launch.py:84-121` — shared schema appendix and harness launch-spec production.
- `src/taskloop/merge/resolve.py:51-62` — another adapter caller whose answer schema must be preserved.
- `tests/steps/test_agent_launch.py:1-105` — existing test integration point to extend; launch choices, schema assertions and cleanup.
- `tests/steps/test_steps.py:42-61` — existing implement disposition and explanation guidance coverage.
- `tests/steps/test_steps.py:254-277` — existing retry and failed-check guidance coverage.
- `tests/steps/test_answer_contract.py:53-106` — existing strict-schema and plan answer coverage.
- `tests/steps/test_answer_contract.py:224-270` — existing implement schema and disposition decoding coverage.
- `tests/steps/test_input_context.py:183-201` — existing complete dispatched-input evidence integration coverage.

## Acceptance and verification
The single behavior passes when the generated-input contract test covers both real step schemas, every applicable retry route and every supported harness, and detects a wrong or missing schema, wrong disposition vocabulary, lost disposition instructions or lost original input. Existing decoder and input-evidence tests continue to pass. The tests inspect generated specifications only; there are no live agent tests.

During implementation, run the changed test file using `uv run --frozen --no-sync python -I -m pytest -q tests/steps/test_agent_launch.py --tb=short | tail -40` in the prepared project environment. After all edits and focused verification, run `just check 2>&1 | tail -60` and then `just test 2>&1 | tail -40`, once each as the final gates, with pipefail so the underlying exit status is retained. Report their results. This planning attempt does not run implementation gates.
