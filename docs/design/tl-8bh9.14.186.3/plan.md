# Header
Task: tl-8bh9.14.186.3; base: 48bb8b6a19e941e360bc62ae2894300aa6eb4322
Depth: medium; 3 behaviours.
Owner decision: none missing. Dependency: none explicitly unlanded.
Evidence budget: 12 model calls. Size: 7 changed files including tests/plan; 3 behaviours; 48 implement model calls.

## Outcome and non-goals
Attempts receive a validated committed shelf digest and guidance. Extraction, bounded generation and the artifact exist; input consumption remains. Generation and later observation are outside scope.

## Settled decisions
- Use the existing compact artifact and deterministic byte bound; no tokenizer dependency.
- Put validation and rendering behind input_context.read/render/refresh, shared by both step producers and retry routes.
- Require the artifact when committed configuration declares shelf dependencies; unrelated repositories retain current context.
- Match all six identities to selected manifests. source_commit records generation attribution; unrelated HEAD changes do not invalidate it.
- Reuse the existing InputError refusal path; validation never repairs or regenerates the artifact during dispatch.

## Open decisions
- None.

## Change map
- src/taskloop/shelf_digest/artifact.py (new): DigestArtifact/read_artifact; codec/validation for render_digest and input_context.read.
- src/taskloop/shelf_digest/render.py: _Digest/render_digest; share schema, preserve canonical bytes and bound.
- src/taskloop/input_context.py: InputContext/read/refresh; validated digest/guidance and InputError.
- tests/steps/test_shelf_digest_artifact.py: artifact contracts; consumer validation and stale identities.
- tests/steps/test_input_context.py: Files/admission/dispatch/repeat cases; committed blobs and failure boundaries.
- tests/steps/test_check_repeat.py: rig/repair_agent; repair freshness and rejection.
- src/taskloop/admit.py: task_text/AttemptAdmission._input (consult); initial admission.
- src/taskloop/admit_chain.py: NextAdmission.admit_next (consult); chained admission.
- src/taskloop/attempt.py: Attempts._context (consult); actual-head refresh.
- src/taskloop/check_repeat/repair.py: CheckRepeat.repair (consult); checked-head refresh.
- src/taskloop/plan_step.py: input_text (consult); plan renderer.
- src/taskloop/implement_step.py: input_text (consult); implement renderer.
- src/taskloop/steps.py: StepKind.input_text (consult); producer signature.
- src/taskloop/repeat.py: InputError handling (consult); ordinary repeat framing.
- src/taskloop/resume_plan.py: InputError handling (consult); plan reuse.
- src/taskloop/earlier_input.py: InputError production (consult); earlier-attempt frame.
- src/taskloop/discussion.py: InputError production (consult); discussion frame.
- docs/design/tl-8bh9.14.186.3/plan.md: implementation handoff.

## Read list
- src/taskloop/input_context.py:28-126 — context ports, renderer, committed reads and replacement.
- src/taskloop/shelf_digest/render.py:1-49 — compact schema, canonical encoding and bound.
- src/taskloop/shelf_digest/identities.py:14-42 — package vocabulary and identity results.
- src/taskloop/shelf_digest/identities.py:150-227 — six-package manifest reconciliation without shelf IO.
- src/taskloop/shelf_digest/source.py:23-65 — explained read failures and immutable SourceSnapshot for manifest reconciliation.
- src/taskloop/shelf_digest/facts.py:12-128 — required facts, exact text and package/module attribution.
- src/taskloop/shelf_digest/generate.py:17-51 — existing producer and generation provenance.
- docs/shelf-digest.json:1-1 — committed interchange artifact.
- src/taskloop/git_views.py:105-145 — committed blob/path adapter used by input readers.
- src/taskloop/admit.py:111-195 — producer, context reader and admission refusal boundary.
- src/taskloop/admit_chain.py:241-262 — chained admission reader and failure handling.
- src/taskloop/attempt.py:210-220 — actual-head refresh before launch evidence is written.
- src/taskloop/check_repeat/repair.py:50-77 — failed-check refresh and failure boundary.
- src/taskloop/plan_step.py:160-164 — plan rendering integration.
- src/taskloop/implement_step.py:114-118 — implement rendering integration.
- src/taskloop/steps.py:28-42 — shared producer contract.
- src/taskloop/repeat.py:117-140 — ordinary repeat framing and input errors.
- src/taskloop/resume_plan.py:65-84 — retained-plan input error handling.
- src/taskloop/earlier_input.py:23-81 — earlier-attempt frame protection and errors.
- src/taskloop/discussion.py:113-130 — discussion frame protection and errors.
- tests/steps/test_shelf_digest_artifact.py:1-63 — artifact identities, attribution and canonical bound.
- tests/steps/test_input_context.py:37-92 — fake committed reader and both producer assertions.
- tests/steps/test_input_context.py:147-264 — initial admission, moved-head dispatch and ordinary repeat scenarios.
- tests/steps/test_check_repeat.py:48-119 — repair fixture and captured launch inputs.
- pyproject.toml:8-27 — declared shelf identities for test fixture setup; obtain matching lock blobs through the existing committed-file port.

## Contract
Intent: context for one commit. Effect: read artifact, pyproject.toml and uv.lock through InputFiles.blob at that commit; feed manifests to existing reconciliation. Result: validated text or InputError before admission/launch. No stored fields or external actions change.

DigestArtifact replaces _Digest as the shared pydantic edge codec. Reject malformed/oversized JSON, duplicate/extra fields or packages, invalid indices, unsafe paths/ranges/hashes and changed fact text/attribution. Compare every expanded identity field, including stream-proc's own version/shared commit. Check references against CONTRACTS; retain source hashes as generation evidence without reopening shelf. Preserve artifact encoding and generation API.

InputContext carries validated shelf content. Pure rendering emits: "Shelf is read-only for agents. Use this validated digest first. If the task requires a shelf change, stop with needs_owner and describe the proposed shelf change." Keep digest/guidance inside the factory frame; refresh replaces both while preserving surrounding input.

Missing/nonregular/unavailable/stale required artifacts raise an explained InputError naming the artifact/mismatch. Never skip a malformed present artifact. Shelf declarations determine when absence is an error.

## Work packages
1. Consumer validation: artifact.py, render.py, test_shelf_digest_artifact.py. Shared codec, committed identity/fact checks, canonical output; closes acceptance 1.
2. Input integration: input_context.py, test_input_context.py. Shared block/guidance through existing callers; closes acceptance 2.
3. Refresh coverage: test_input_context.py, test_check_repeat.py. Moved-head and both repeat routes; closes acceptance 3. Last, run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, retaining exit status.

## Acceptance behaviours
1. A valid bounded artifact matches all six selected manifest identities and required fact attribution; missing, malformed, altered or stale required input is rejected with a concrete explanation. Unrelated commits can reuse it; repositories without shelf inputs still work.
2. Initial plan and implement inputs, including chained admission, contain the validated digest and read-only/needs_owner guidance exactly once, drawn from committed blobs despite dirty checkout files; invalid required input prevents claim/reservation or agent launch at the existing boundary.
3. Moved-head dispatch, ordinary repeats and failed-check repeats replace prior digest/guidance with one current block, preserve task and feedback text, retain the actual launched input, and refuse stale artifacts before an agent runs.
