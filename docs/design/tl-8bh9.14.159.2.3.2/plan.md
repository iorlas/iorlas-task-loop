# Header
Task: tl-8bh9.14.159.2.3.2
Base: 4b6f7bda6044f5284c0f928b0afd7449740e3bbb
Depth: medium; collection, guards, dashboard.
Decisions: settled. Unlanded dependencies: none.
Evidence budget: 12 calls.
Size: 50 changed files including tests/artifacts; 3 behaviours; 65 implement calls.

## Outcome and non-goals
One pending encoding across collection, guards and dashboard. Storage is delivered. Exclude terminal results, publication projections, command identities, help and prose.

## Settled decisions
- Use the naming map's Result vocabulary row pending:verification → pending:commit and its matching pending/page row.
- No aliases; scheduling remains equivalent.
- Dashboard summary codes change; verification step identities and the page-only pending result retain their roles.
- Preserve displayed sentences for the separate wording task.

## Open decisions
- None.

## Change map
- src/taskloop/attempt_types.py — new PendingReason.COMMIT string-enum member; existing AttemptResult transport.
- src/taskloop/attempt_result.py — _report emits the selector; report/collect remain the result boundary.
- src/taskloop/attempt_status.py — _stopped compares the selector; next_action keeps its choices.
- src/taskloop/round.py — _committed updates both completion guards.
- src/taskloop/dash/static/rail.js — row compares summary commit; navigation identities stay intact.
- src/taskloop/dash/static/words.js — WORDS changes the summary key, preserving its sentence.
- src/taskloop/attempt.py — consult collect/execute/capture/_capture report callers.
- src/taskloop/attempt_entry.py — consult _step/resumed; commit pending stays outside UNFINISHED.
- src/taskloop/dash_task.py — consult _agent/build_body/history collection and summary projection.
- src/taskloop/dash_verify.py — consult applies/verification; preserve page pending and terminal inference.
- src/taskloop/result_data.py — consult _show_data; transported reason becomes commit.
- tests/steps/test_pending_commit.py — new next_action regression functions, integrated through report and AttemptResult.
- tests/steps/test_answer_contract.py — pending/terminal verdict matrix.
- tests/steps/test_check_repeat.py — pending assertion and equivalent next-round actions.
- tests/cli/test_step_cli.py — pending fixture and unchanged next action.
- tests/cli/test_dash_words.py — summary key expectation.
- tests/dash/rail.test.js — pending summary fixtures and attachment coverage regression.
- tests/rules/public_surfaces.json — pending reason fixture only.
- tests/steps/public_surface_fixtures.py — pending rename.
- tests/steps/real/test_prepare_real.py — pending rename.
- tests/steps/real/test_repeat_real.py — pending rename.
- tests/steps/test_admit.py — pending rename.
- tests/steps/test_admit_chain.py — pending rename.
- tests/steps/test_agent_completion.py — pending rename.
- tests/steps/test_attempt.py — pending rename.
- tests/steps/test_attempt_entry.py — resumed fixture/expectation only.
- tests/steps/test_attempt_runtime.py — pending rename.
- tests/steps/test_attempt_usage.py — pending rename.
- tests/steps/test_compaction.py — pending rename.
- tests/steps/test_continuation.py — pending rename.
- tests/steps/test_continuation_composition.py — pending rename.
- tests/steps/test_decision_boundaries.py — pending rename.
- tests/steps/test_dispatch_slot.py — pending rename.
- tests/steps/test_drain_fences.py — pending rename.
- tests/steps/test_execution_turns.py — pending rename.
- tests/steps/test_hold_status.py — pending rename.
- tests/steps/test_input_context.py — pending rename.
- tests/steps/test_lost_entry.py — pending rename.
- tests/steps/test_operations.py — pending fixtures/expectations only.
- tests/steps/test_prepare.py — pending rename.
- tests/steps/test_publish.py — upstream pending rename.
- tests/steps/test_repeat.py — pending rename.
- tests/steps/test_restart.py — pending rename.
- tests/steps/test_slot_lock.py — pending rename.
- tests/steps/test_slot_release.py — pending rename.
- tests/steps/test_verifier.py — pending rename.
- docs/design/tl-8bh9.14.159.2.3.2/plan.md — new plan.
- docs/design/tl-8bh9.14.159.2.3.2/plan-metadata.json — new evidence metadata.

## Read list
- docs/design/tl-8bh9.14.159.1/naming-map.md:58-66 — single-target pending mapping; matching page row at 218.
- docs/glossary.md:191-198 — verdict/effect meanings alongside supplied definitions.
- src/taskloop/attempt_types.py:326-352 — enum/transport integration.
- src/taskloop/attempt_result.py:47-110 — pending producer and terminal boundary.
- src/taskloop/attempt_status.py:135-155 — stopped guards; new regression integration.
- src/taskloop/round.py:347-359 — completion guards.
- src/taskloop/attempt.py:92-132 — collection/capture callers; _capture also delegates to report.
- src/taskloop/attempt_entry.py:215-265 — entry and resumed callers.
- src/taskloop/dash_task.py:148-166 — summary projection; history also collects through the same owner.
- src/taskloop/dash_verify.py:24-66 — page pending and terminal inference.
- src/taskloop/result_data.py:50-73 — result transport.
- src/taskloop/dash/static/rail.js:118-155 — summary coverage.
- src/taskloop/dash/static/words.js:25-44 — summary selector and sentences.
- tests/steps/test_answer_contract.py:212-230 — verdict matrix.
- tests/steps/test_check_repeat.py:150-185 — scheduling integration.
- tests/cli/test_step_cli.py:54-64 — pending next-action fixture.
- tests/cli/test_dash_words.py:10-46 — key/word coverage.
- tests/dash/rail.test.js:64-80 — attachment regression integration.
- Rename-only files are exempt under the map's pending:verification → pending:commit rows. Replace only pending reasons. Require no matches from `rg -nw -e 'pending:verification' -e '"pending", "verification"' src/taskloop tests`. Search for changed/omitted callers as needed.

## Contract
Intent: a complete clean commit/keep execution lacks a verdict.
Effect: _report emits pending with PendingReason.COMMIT, encoded as commit through existing string transport. No stored-field change.
Result: pending never succeeds. Stopped attempts and rounds reach the same commit action. Validation/session waits still resume; commit pending never reruns the agent. Dashboard summary commit retains attachment coverage; page-only pending retains unknown checks.

## Work packages
1. Collection: attempt_types.py, attempt_result.py, verdict matrix and rename-only fixtures. Close A1 and A4 through one typed selector and updated result expectations.
2. Scheduling: attempt_status.py, round.py and scheduling tests above. Close A2; cover stopped attempts with/without execution and session-wait completion.
3. Dashboard: rail.js, words.js, test_dash_words.py and rail.test.js. Close A3; preserve navigation, terminal projections and sentences.
4. Audit the pending mapping. Run focused function-based tests and dashboard regression checks without live processes. Last, run once each `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, preserving exit status.

## Acceptance behaviours
A1: Commit/keep answers lacking a verdict expose pending/commit through collection and JSON and never succeed; validation, session and terminal outcomes keep their meanings.
A2: Entry resume, stopped attempts and rounds preserve waits, commit, release and publication ordering without extra agent invocation or premature advancement.
A3: Dashboard pending summaries use commit, retain attached results and readable words, and assert no successful conclusion without evidence.
A4: `rg -nw -e 'pending:verification' -e '"pending", "verification"' src/taskloop tests` returns no matches.
