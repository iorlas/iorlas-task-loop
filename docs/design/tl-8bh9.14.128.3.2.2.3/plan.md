# Header
Task: tl-8bh9.14.128.3.2.2.3
Base: 7026a24582699dd01e8eb8d0078a8189c8348eda
Depth: medium
Reason: 3 behaviours. Owner decision: none missing. Dependency: landed.
Evidence budget: 12 model calls.
Size: 4 changed files incl. plan/tests; 3 independent behaviours; 45 implement model calls.

## Outcome and non-goals
Make stopped execution actionable through recovery and retain its identity across reopened connections. Use existing launch authorization, saved-session continuation and captured completion. Exclude schema, harness protocol, claim reconciliation and admission policy changes.

## Settled decisions
- Direct `start` already reaches recovery through `Launcher._target` without admission.
- `process_gate` falls through after all processes stop, leaving dispatched work at `release`; fix this gap.
- `_verified` already calls captured completion before verification; strengthen restart coverage.

## Open decisions
- None.

## Change map
- `src/taskloop/recovery/status.py` — `process_gate`: project successful stopped-process observations to the existing `start` action for recoverable dispatched work; retain conservative blocked outcomes.
- `tests/steps/test_recovery_status.py` — `test_shared_gate_covers_all_status_consumers_without_writes`: expect actionable recovery after all processes stop, including expired saved work; retain no-write assertions and blocked-process coverage.
- `tests/steps/test_restart.py` — add direct-start and freshly reopened-round convergence scenarios; extend captured-completion retry coverage with fresh ports/connections and ordering assertions.
- `docs/design/tl-8bh9.14.128.3.2.2.3/plan.md` — this implementation contract.
- `src/taskloop/attempt_status.py` — consult `_agent`, gate consumer; `next_action`/`_stopped`, fallback producers; `show_attempt`/`list_attempts`/`current_view`, shared readers.
- `src/taskloop/operations.py` — consult `start`/`_start`/`_current`; callers also in `tests/steps/test_operations.py` and `tests/steps/round_bench.py`.
- `src/taskloop/round.py` — consult `run_round` → `_settle` → `_resume`/`_verified`; `_advance`/`_start_each` call `start`.
- `src/taskloop/cli_step.py` — consult command callers of `open_start`/`start` and `open_next`/`run_round`.
- `src/taskloop/cli_composition.py` — consult `open_start`/`open_next` → `_starting`; `one_round` → `open_next`/`run_round`; completion wiring.
- `src/taskloop/composition.py` — consult `open_launcher`, `open_continuation`, `open_completion`, port producers.
- `src/taskloop/launch.py` — consult `_target`/`_register`, recovery dispatch.
- `src/taskloop/recovery/launch.py` — consult `RecoveryLaunch`, authorization caller.
- `src/taskloop/recovery/recover.py` — consult `Recovery.authorize`, authority owner.
- `src/taskloop/recovery/complete_attempt.py` — consult `CapturedCompletion`, `Attempts.execute` caller.
- `tests/steps/test_continuation_composition.py` — consult production launch/entry and completion setup.
- `tests/steps/test_recovery_launch.py` — consult `launcher`, authorization fake.
- `tests/steps/test_recovery_entry.py` — consult `entry_apps`/`run_entry`, entry setup.

## Read list
- `src/taskloop/recovery/status.py:19-41` — read-only observation producer and scheduling gate to edit.
- `src/taskloop/attempt_status.py:133-154` — fallback action for stopped execution.
- `src/taskloop/attempt_status.py:208-237` — projection consumer and repeat/verification boundaries.
- `src/taskloop/operations.py:325-402` — direct-start dispatch and current-attempt fences.
- `src/taskloop/round.py:226-297` — settlement and same-attempt relaunch.
- `src/taskloop/round.py:337-349` — completion-before-verification boundary.
- `src/taskloop/round.py:368-451` — advance and ready-task admission callers.
- `src/taskloop/cli_step.py:160-188` — command entry callers.
- `src/taskloop/cli_composition.py:128-191` — shared start/round composition.
- `src/taskloop/cli_composition.py:205-219` — repeated rounds reopen ports.
- `src/taskloop/composition.py:95-121` — continuation and completion producers.
- `src/taskloop/composition.py:219-226` — recovery-aware launcher producer.
- `src/taskloop/launch.py:191-239` — target selection and authorization callback.
- `src/taskloop/recovery/launch.py:9-15` — shared authorization adapter.
- `src/taskloop/recovery/recover.py:81-153` — observation, authorization and reconciliation ownership.
- `src/taskloop/recovery/complete_attempt.py:20-49` — captured execution completion fences.
- `tests/steps/test_restart.py:1-135` — existing restart setup and completion assertions to extend.
- `tests/steps/test_recovery_status.py:27-95` — projection expectations and unavailable-observation coverage to update.
- `tests/steps/test_continuation_composition.py:31-68` — production launch/entry composition pattern.
- `tests/steps/test_continuation_composition.py:115-145` — reopened completion pattern.
- `tests/steps/test_recovery_launch.py:26-108` — launch fake and authorization/refusal scenarios.
- `tests/steps/test_recovery_entry.py:36-58` — existing continuation and entry setup integration points.
- `tests/steps/round_bench.py:203-271` — port producers and `run_round`/`start` callers.
- `tests/steps/test_operations.py:175-281` — direct-start callers and existing-admission assertions.
- `tests/steps/test_operations.py:650-696` — existing-start and release fences.

## Contract
No new stored fields or schema version. Reuse `Observations`, `Result`, `Seen`, `AttemptKey`, `Intent` and existing scheduling actions.

Intent: status reads dispatched work without capture or release. Effect: observe entry, worker and recovery owner without writes. Result: all stopped yields existing `start`; live/unknown processes block it. Extend the gate's typed return; `_agent` already accepts the projection. Held, incomplete, changed and unavailable observations retain their protected paths.

Intent: either scheduler selects that attempt. Effect: launcher registers and authorizes recovery; entry continues the saved session. Result: preserve attempt key, dispatch token, attempt generation, session and reservation. Recovery revisions and execution registration change only under their existing owner.

Intent: captured execution awaits answer/session completion. Effect: complete under custody before verification. Result: only `pending:verification` permits verification; unavailable/unfinished completion remains retryable without a harness invocation.

## Work packages
1. Update `recovery/status.py` and its status contract tests so stopped recoverable execution reaches recovery, including expired saved work. Close the scheduling part of acceptance 2; preserve live/unknown and held fences.
2. Extend `test_restart.py` with production composition and semantic fakes. Exercise direct `start`, then independent rounds with fresh connections/ports; assert saved-session execution, one attempt/reservation and no admission/repeat calls. Close acceptance 1 and remaining acceptance 2.
3. Extend captured-completion retries in `test_restart.py` with reopened state, ordering and zero-harness assertions. Close acceptance 3. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
1. A direct start after restart continues the saved attempt and session through recovery, with no fresh admission, repeat attempt or extra reservation.
2. Successive rounds with reopened connections recover stopped execution once and retain the same attempt/session; live or unknown entry, worker or owner observations prevent execution, and an existing recovery owner prevents duplicate launch.
3. Captured answer/session completion survives unavailable storage and reopening, finishes before verification, and retries without another harness invocation.
