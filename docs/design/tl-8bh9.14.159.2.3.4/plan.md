# Header
Task: tl-8bh9.14.159.2.3.4
Base: c32ab3b265ece637f97019a09117b6b1e70e3536
Depth: medium; terminal encoding and publication projections.
Decisions: settled; none unlanded.
Evidence budget: 12 model calls.
Size: ~46 files including artifacts, 2 behaviours, ~65 implement calls.

## Outcome and non-goals
Terminal success reaches command, entry, repeat, round and dashboard consumers as committed or reused; publication refuses an absent or rejected verdict as not_committed. Preserve explanations, rejection payloads, exit codes and delivery order. Pending encoding and committed storage are delivered. Leave schema, help, guidance text, dashboard operation names and documentation unchanged; guidance dictionary keys and the terminal display key must follow the encoding.

## Settled decisions
- Apply the committed naming map's VerifiedTask → CommittedTask, verified terminal word → committed, and not_verified → not_committed rows, without aliases.
- Keep reused and rejected:<rule> meanings and payloads.
- Factory commit success remains independent of release and publication success.
- The naming map's local verified → committed row applies to result variables; ordinary identity verification and deferred wording remain outside scope.

## Open decisions
- None.

## Change map
- src/taskloop/attempt_result.py: judged, succeeded — own typed success words and encoding.
- src/taskloop/operations.py: CommittedTask, commit_task — typed success; retain delivery order.
- src/taskloop/publish.py: BranchPublish._refusal — typed not_committed; retain detail.
- src/taskloop/result_data.py: StepResult, _released_data, _step_data, _show_data, _publish_data — consume renamed results/codecs.
- src/taskloop/step_render.py: render, _released_lines — consume CommittedTask.
- src/taskloop/round.py: _committed, _move, _publish — consume renamed result/codecs.
- src/taskloop/attempt_entry.py: shown, _step, _publish — consult codecs; rename local result.
- src/taskloop/dash_verify.py: verification — use judged for terminal encoding.
- src/taskloop/dash/static/rail.js: verdict — recognize committed.
- src/taskloop/dash/static/words.js: WORDS — rename terminal key only.
- src/taskloop/step_guide.py: GUIDE — rename refusal key only.
- src/taskloop/round_guide.py: refusal lookup — rename refusal key only.
- src/taskloop/repeat.py: _word — consult judged consumer.
- src/taskloop/attempt_status.py: _view — consult succeeded consumer.
- src/taskloop/hold_status.py: cause — consult succeeded consumer.
- src/taskloop/check_repeat/store.py: admission guard — consult succeeded consumer.
- src/taskloop/dash_task.py: agent projection — consult succeeded consumer.
- src/taskloop/cli_step.py: dispatch — consult commit_task caller.
- src/taskloop/show_render.py: rendering — consult succeeded consumer.
- src/taskloop/task_status.py: projection — consult succeeded consumer.
- tests/steps/test_answer_contract.py: verdict matrix — terminal success/non-success.
- tests/steps/test_operations.py: verdict/replay/delivery — typed results and ordering.
- tests/steps/test_publish.py: refusals — codes, no Git/push, rejection explanation.
- tests/steps/test_admit_chain.py: finish — rename result signature.
- tests/cli/test_step_cli.py: cases — typed fixtures and text/JSON assertions.
- Mapped fixtures in tests/steps, tests/cli, tests/dash and tests/rules/public_surfaces.json: one-to-one substitutions.
- docs/design/tl-8bh9.14.159.2.3.4/: plan.md and plan-metadata.json retain this contract.

## Read list
- docs/glossary.md:145-169 — factory commit verdict and delivery distinction.
- docs/design/tl-8bh9.14.159.1/naming-map.md:22-71 — fixed type and terminal vocabulary rows.
- src/taskloop/attempt_result.py:8-98 — pending separation, report and success codec.
- src/taskloop/operations.py:196-206 — result signature.
- src/taskloop/operations.py:511-530 — verdict, release and publication sequence.
- src/taskloop/publish.py:53-156 — publication result boundary and refusal guard.
- src/taskloop/result_data.py:40-173 — result union, signatures, dispatch and fields.
- src/taskloop/step_render.py:147-162 — result signature and delivery rendering.
- src/taskloop/round.py:348-359 — result producer call and round projection.
- src/taskloop/attempt_entry.py:138-151 — entry terminal encoder.
- src/taskloop/attempt_entry.py:219-249 — factory commit and collected-success decision.
- src/taskloop/dash_verify.py:40-60 — terminal dashboard projection.
- src/taskloop/repeat.py:49-61 — judged consumer.
- src/taskloop/attempt_status.py:208-215 — succeeded consumer.
- src/taskloop/hold_status.py:60-66 — succeeded consumer.
- src/taskloop/check_repeat/store.py:40-48 — succeeded admission guard.
- src/taskloop/dash_task.py:150-155 — succeeded projection consumer.
- src/taskloop/cli_step.py:266-271 — command integration.
- src/taskloop/show_render.py:70-77 — succeeded display consumer.
- src/taskloop/task_status.py:120-128 — succeeded task-status consumer.
- tests/steps/test_answer_contract.py:213-231 — terminal verdict matrix.
- tests/steps/test_operations.py:404-465 — typed result, sequencing and stored replay.
- tests/steps/test_publish.py:245-290 — pre-Git refusals and explanations.
- tests/steps/test_admit_chain.py:81-90 — helper result signature.
- tests/cli/test_step_cli.py:205-231 — CLI success and refusal projections.

Read-list exemptions: the map's VerifiedTask → CommittedTask, verified terminal/local result → committed and not_verified → not_committed rows, only for mechanical substitutions outside signatures. Includes fixtures, page success/key and guidance keys; no prose edits. Absence command: `rg -nw 'VerifiedTask|not_verified|["\x27]verified["\x27]|verified:|collected[ :]verified|verify=verified' src/taskloop tests`.

## Contract
Intent: encode Committed or Rejected. Effect: judged/report returns committed, reused or rejected:<rule>; enum-backed success words serve CommittedTask.status and serializers. Dashboard shares judged. Result: retain identity, artifact, reuse, explanation and rejection payloads; pending:commit stays nonterminal.

Intent: publish. Effect: existing fenced read and pre-Git checks; type the renamed refusal at its boundary. Result: not_committed for missing acceptance/rejection, existing detail, no push. Retain release/publication fields even on delivery failure. No stored-field/schema change.

## Work packages
1. Terminal owners and consumers above: introduce typed encoding, wire callers and update verdict/replay/CLI/dashboard cases. Closes 1–3.
2. publish.py, refusal keys and mapped fixtures: rename code and update publication/CLI assertions. Closes 4–5.
3. After installation, run focused existing tests via `uv run --frozen --no-sync python -I -m pytest -q <file> --tb=short | tail -40`; check absence and scope. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last. Closes 6.

## Acceptance behaviours
1. Fresh stored success encodes committed; unchanged success encodes reused; rejection retains rejected:<rule>; pending:commit never succeeds.
2. Replaying a stored verdict performs no fresh Git observation; identity, artifact, reuse and explanation survive encoding.
3. CLI text/JSON, entry, repeat, round and dashboard agree on terminal success; release follows either verdict and publication follows only success; delivery failure preserves successful factory commit and exit status.
4. Missing acceptance and rejected verdicts refuse publication as not_committed before Git or push; rejection detail remains available through the command path.
5. Help, guidance text, docs, action labels and pending scheduling retain their existing behaviour and wording.
6. The Read list's rg -nw command returns no matches for obsolete terminal encodings; separate identity-verification prose remains valid.
