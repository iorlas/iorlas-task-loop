# Header
Task: tl-8bh9.14.199
Base: db42514ca3d9064800666febae11560fa216a62b
Depth: medium; two behaviours in one slice.
Decision/dependency: none missing/unlanded.
Evidence budget: 12 model calls.
Size: 8 changed files including tests/artifacts; 2 behaviours; about 60 implement model calls.

## Outcome and non-goals
Implement attempts can adopt shelf releases and return typed capability requests through the existing needs_owner hold. Excludes shelf changes, dependency upgrades in this task, release discovery, scheduling and database changes.

## Settled decisions
- Permit adding or upgrading only shelf packages, to their most recent released version; retain the prohibition for every other dependency.
- Resolve release versions when implementing the task that needs them; task identifiers and task text do not pin versions.
- Shelf remains read-only. A missing capability ends the attempt through needs_owner, with no commit request.
- Keep the existing implement answer keys. Allow a structured explanation for a shelf request; ordinary explanations remain strings.
- The supplied predecessor decision is settled: shared Step enum integration is delivered. No vocabulary migration remains here.

## Open decisions
- None.

## Change map
- `src/taskloop/implement_step.py`: ENVIRONMENT, ANSWER_SCHEMA, decode, _closing_words — replace the blanket ban with the shelf-only exception; document and validate the structured refusal; reconcile offline-cache guidance with authorized shelf acquisition.
- `src/taskloop/shelf_request.py` (new): ShelfRequest — strict pydantic package/capability payload and human explanation; integrated by implement_step.decode and attempt_types.Answer.
- `src/taskloop/attempt_types.py`: Answer — carry an optional shelf_request, absent for ordinary answers.
- `src/taskloop/answer_failures.py`: AnswerRule — identify invalid shelf requests through the existing failure codec.
- `tests/steps/test_steps.py`: implement input and repeat coverage — assert the exception, remaining ban and stop instructions in generated prompts.
- `tests/steps/test_answer_contract.py`: schema, implement decoder and evidence coverage — exercise structured refusals, invalid payloads and reconstruction through answer_read.read.
- `src/taskloop/steps.py`: IMPLEMENT, failed_check_feedback — consult the schema/decoder binding and feedback delegation.
- `src/taskloop/attempt.py`: Attempts._launch, Attempts._validate — consult initial schema production and answer collection; use existing disposition/effect persistence.
- `src/taskloop/recovery/native.py`: NativeContinuation.__call__ — consult continuation schema production.
- `src/taskloop/answer_read.py`: read — consult reconstruction through the owning decoder.
- `src/taskloop/hold_facts.py`: explanation — consult decoded explanation delivery.
- `src/taskloop/hold_text.py`: _details — consult hold rendering.
- `tests/steps/test_agent_launch.py`: schema/prompt forwarding — consult harness coverage.
- `tests/steps/test_input_context.py`: repeated implement input — consult repeat coverage.
- `tests/steps/test_commit_paths.py`: step contract consumers — consult shared coverage.
- `docs/design/tl-8bh9.14.199/plan.md`: planning artifact.
- `docs/design/tl-8bh9.14.199/plan-metadata.json`: preparation evidence.

## Read list
- `src/taskloop/implement_step.py:27-113` — answer schema, environment guidance and decoder.
- `src/taskloop/implement_step.py:123-209` — prompt and both feedback paths.
- `src/taskloop/attempt_types.py:330-342` — decoded Answer integration point.
- `src/taskloop/answer_failures.py:8-49` — failure vocabulary and typed diagnostic.
- `src/taskloop/answer_decode.py:1-51` — shared field and explanation validation.
- `src/taskloop/steps.py:24-64` — kind binding and feedback caller.
- `src/taskloop/attempt.py:245-255` — initial schema producer.
- `src/taskloop/attempt.py:338-367` — answer decoder caller and persisted state.
- `src/taskloop/recovery/native.py:25-39` — continuation schema producer.
- `src/taskloop/answer_read.py:1-16` — evidence reader and decoder caller.
- `src/taskloop/hold_facts.py:72-80` — explanation consumer.
- `src/taskloop/hold_text.py:105-116` — human hold rendering.
- `tests/steps/test_steps.py:45-148` — implement prompt and working/final verification contracts.
- `tests/steps/test_steps.py:148-165` — repeat preservation integration.
- `tests/steps/test_answer_contract.py:28-69` — harness schema constraints.
- `tests/steps/test_answer_contract.py:227-292` — implement fixture and unfinished answer validation.
- `tests/steps/test_agent_launch.py:118-145` — harness forwarding of prompts and schemas.
- `tests/steps/test_input_context.py:246-264` — repeated implement input consumer.
- `tests/steps/test_commit_paths.py:104-116` — contract consumer for both step kinds.

## Contract
Intent: adopt shelf's latest release. Effect: authorize shelf dependency addition/upgrade, including acquisition when absent from the prepared cache. Result: ordinary answer shapes remain valid. Other dependencies remain forbidden. No general manifest auditing service is added.

Intent: report a missing shelf capability. Effect: answer with disposition needs_owner, paths [], message null, and explanation {"package": "<distribution name>", "capability": "<missing capability>"}. Result: decode into frozen pydantic ShelfRequest, attach it as Answer.shelf_request, and produce a bounded human explanation naming both fields and saying shelf work is required before this task can continue. No owner CLI instruction is generated.

The request object has exactly two strict string fields. Package is a nonblank distribution name, at most 200 characters; capability is nonblank text, at most 1000 characters. Reject missing/extra fields, wrong types, blank values, excessive lengths and structured explanations on any disposition except needs_owner. Report these through AnswerRule.SHELF_REQUEST and AnswerFailure. Ordinary string explanations still use the existing validator, including non-shelf needs_owner causes; the plan step's schema is untouched.

Use an object/string explanation schema under the existing strict harness contract: all object properties required, extra properties forbidden. Evidence owns the structured interchange; AnswerState retains its fields. Evidence reads reconstruct the request and formatted explanation through the same decoder. The existing no-effect needs_owner path holds the task.

## Work packages
1. In implement_step.py and test_steps.py, replace the dependency ban, resolve conflicting cache-only wording and describe the request shape in initial, repeat and failed-check inputs. Closes A1.
2. Add shelf_request.py; extend Answer, AnswerRule and implement_step's schema/decoder. In test_answer_contract.py verify accepted and rejected requests, schema forwarding compatibility, evidence reconstruction and the no-commit effect. Closes A2.
3. Run focused tests for the changed contracts. Finish with pipeline failure propagation and `just check 2>&1 | tail -60`, then `just test 2>&1 | tail -40`, once each as the final validation; report their outcomes.

## Acceptance behaviours
A1: Generated implement instructions permit adding/upgrading shelf packages only to the latest release, retain the ban on other dependencies, and preserve this policy in repeated and failed-check attempts.
A2: A missing capability produces a validated package/capability request under needs_owner; it survives evidence reconstruction, yields a human explanation naming both, requests no commit and holds rather than advances. Malformed requests and requests on other dispositions are rejected; ordinary answers and plan answers retain their contracts.
