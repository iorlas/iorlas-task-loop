# Header
Task: tl-8bh9.14.171.1.3
Base: c0d83f93d95f67487e6e3a8f70ee28da226ee324
Depth: medium; one enum across three consumer families.
Owner decisions: none missing. Dependency: landed.
Evidence budget: 12 model calls.
Size: 10 changed files; 3 behaviours; about 40 implement model calls.

## Outcome and non-goals
Replace remaining consumer literals using the existing Step, codec and settings selector. Preserve external text and routes; verify enum-valued task-status inputs. Exclude factory sequencing, admission, persistence, schema and frontend vocabulary.

## Settled decisions
- Step contains PLAN and IMPLEMENT; checks remain separate.
- Column, verification and Next vocabulary retain their own text.
- StepSettings.for_step retains member/text acceptance and check rejection.
- AttemptRow.step and AttemptView.step expose str: use member equality, without migrating producers.
- task_status._moving already accepts enum values; verify both members without changing its check rule.
- Body/feed inputs remain strings; unknown names retain missing-attempt results.

## Open decisions
- None.

## Change map
- src/taskloop/agents/config.py — resolve_agents/display: Step iteration/maps, encoded external keys.
- src/taskloop/cli_step.py — _configuration: Step iteration for flag provenance.
- src/taskloop/dash_board.py — STEP_COLUMN/column_of/_repeat/duration_of: enum keys/comparisons; retain check and fallback.
- src/taskloop/dash_task.py — _agent/_chain: enum comparisons; retain build_feed/build_body/build_task contracts.
- src/taskloop/step.py — Step/decode_step/encode_step: reuse unchanged.
- src/taskloop/agents/settings.py — StepSettings.for_step: consult unchanged selector.
- src/taskloop/attempt_reads.py — AttemptRow: consult str producer.
- src/taskloop/attempt_status.py — AttemptView: consult str producer.
- src/taskloop/steps.py — STEPS/CHECK/ORDER: consult separate factory vocabulary.
- src/taskloop/task_status.py — _moving/task_status/in_flight: consult unchanged status rule.
- src/taskloop/machine_config.py — resolve: retain resolve_agents caller.
- src/taskloop/result_data.py — _show_data/config JSON: retain task_status/display callers.
- src/taskloop/step_render.py — human: retain task_status/display callers.
- src/taskloop/admit.py — admission: retain for_step caller.
- src/taskloop/operations.py — start: retain for_step caller.
- src/taskloop/round.py — task_status/in_flight callers: retain scheduling results.
- src/taskloop/dash_model.py — Column/Verification/FeedEvent/AttemptDetail: retain display types.
- src/taskloop/dash_composition.py — _ports: retain build_board/build_task/build_body/build_feed callers.
- src/taskloop/dash_server.py — _json/_feed/body routing: retain serialization and text inputs.
- tests/steps/test_agent_settings.py — extend resolution/display cases.
- tests/cli/test_config.py — extend human/JSON flag provenance cases.
- tests/steps/test_dash_read.py — extend enum board/history cases.
- tests/steps/test_task_status.py — extend both member inputs with check controls.
- tests/cli/test_dash_server.py — consult endpoint assertions.
- docs/design/tl-8bh9.14.171.1.3/plan.md — new plan.
- docs/design/tl-8bh9.14.171.1.3/plan-metadata.json — new preparation metadata.

## Read list
- src/taskloop/step.py:1-18 — vocabulary and codec.
- src/taskloop/agents/settings.py:137-157 — selector and overrides.
- src/taskloop/agents/config.py:35-121 — inputs, resolution and display.
- src/taskloop/cli_step.py:302-320 — flag provenance and dispatch integration.
- src/taskloop/dash_board.py:20-177 — column, restart, duration and board projection.
- src/taskloop/dash_task.py:89-326 — feed/body callers and agent/check history projections.
- src/taskloop/attempt_reads.py:48-80 — agent row producer shape.
- src/taskloop/attempt_status.py:66-90 — status view producer shape.
- src/taskloop/steps.py:47-94 — factory step order and non-agent checks.
- src/taskloop/task_status.py:104-137 — moving states, status precedence and in-flight results.
- src/taskloop/machine_config.py:159-175 — configuration resolver caller.
- src/taskloop/result_data.py:43-209 — status and configuration JSON callers.
- src/taskloop/step_render.py:186-195 — human configuration display caller.
- src/taskloop/admit.py:169-180 — initial settings selection caller.
- src/taskloop/operations.py:477-488 — subsequent settings selection caller.
- src/taskloop/round.py:430-439 — scheduling status caller.
- src/taskloop/dash_model.py:100-180 — separate display and agent fields.
- src/taskloop/dash_composition.py:39-67 — board, task, body and feed callbacks.
- src/taskloop/dash_server.py:164-210 — JSON encoding and body/feed routes.
- tests/steps/test_agent_settings.py:25-58 — selector coverage and configuration fixture pattern.
- tests/cli/test_config.py:128-274 — human/JSON output and agent provenance cases.
- tests/steps/test_dash_read.py:226-335 — board, body and feed cases; search existing restart/repeat/check cases before extending.
- tests/steps/test_task_status.py:25-80 — status matrix and in-flight coverage.
- tests/cli/test_dash_server.py:206-218 — external JSON assertion pattern.

## Contract
Intent: Step owns agent-step decisions. No new public types, states, stored fields or effect boundaries. Configuration maps use Step keys; external plan/implement fields remain unchanged.

Effect: pair each configuration input/default with its member; iterate Step in display/CLI provenance and encode external keys. Board lookup uses Step keys: handle check first, then decode agent text, retaining the implement fallback on invalid text. Compare row/view values with members for restart, duration and implement-check history. Retain column values and body/feed route matching.

Result: str producers and enum inputs yield identical projections and statuses. Unknown body/feed names still miss. No new IO or external actions.

## Work packages
1. Update agents/config.py and cli_step.py; extend test_agent_settings.py and test_config.py for A1, including distinct file choices and flag overrides.
2. Update dash_board.py and dash_task.py; extend test_dash_read.py for A2, consulting existing model/composition/server integration.
3. Extend test_task_status.py for A3 with both members and check controls; retain the generic status rule.
4. Run focused affected-file tests with the permitted isolated pytest command. Last, run just check 2>&1 | tail -60 and just test 2>&1 | tail -40 once each, preserving pipeline failure detection. Both must pass. No live services.

## Acceptance behaviours
A1. Both agents resolve their own settings through Step members; default/file/flag precedence and all human/JSON configuration keys, values, sources and refusal results stay unchanged.
A2. Enum and canonical-text inputs produce equivalent dashboard columns, restart/repeat details, durations and implement-check history; checks/verification routes, JSON spellings, unknown-column fallback and missing body/feed results stay unchanged.
A3. Both agent members remain running while check remains checking; status reasons, held/queued precedence and in-flight membership agree across shared CLI, dashboard and scheduling reads.
