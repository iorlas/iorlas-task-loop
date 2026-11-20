# Header
Task: tl-8bh9.14.128.3.2.2.1
Base: e752ae5d6944787089e270cceaa50faf7207d55e
Depth: medium; two behaviours
Owner decision missing: no. Unlanded dependency: none identified.
Evidence budget: 12 model calls.
Size: 7 changed files, 2 independent behaviours, 45 implement model calls.

## Outcome and non-goals
Give status and round consumers shared recovery process facts, including worker groups and recovery owners. Prevent actionable status when absence is unproved. Launch authorization, entry continuation, claim renewal and scheduling convergence belong to later split tasks; no schema change is needed.

## Settled decisions
- Reuse the delivered recovery models, native identity observations and snapshot comparisons.
- Status observes without authorization, custody acquisition, claim mutation or allowance renewal.
- A status observation conveys no execution authority; execution retains its own committing fences.
- Keep the existing public next-action vocabulary and existing StatusPorts constructor callers compatible.
- An unavailable observation must have an explanation and must never imply confirmed absence.

## Open decisions
- None.

## Change map
- `src/taskloop/recovery/store.py` — `RecoveryStore.snapshot`, `compare`: support consistent SELECT-only observation on the existing read-only connection; preserve authorization's write transaction and exact comparison.
- `src/taskloop/recovery/recover.py` — `Recovery.observe`, `_observations`, `_observe`: share fact gathering with a new `Recovery.status` read operation, without custody or tracker calls; retain the existing execution observation contract.
- `src/taskloop/attempt_status.py` — `StatusPorts`, `_agent`: inject the recovery status reader and apply a conservative process gate before leftovers or actionable next-word selection; `show_attempt`, `list_attempts`, `current_view` share it. Keep old constructors valid through a conservative unavailable default for relevant unfinished registrations.
- `src/taskloop/cli_composition.py` — `open_reads`, `open_next`: compose the same read-only recovery reader for both StatusPorts producers. CLI `_show`/`_list`, dashboard `_ports` callbacks `board`/`task`/`body`/`feed`, `build_task`, the hold reader's `partial(current_view, reads)` and `run_round` receive it through existing ports and require no new workflow.
- `tests/steps/test_recovery_contract.py` — observation contracts: cover status on a reopened read-only database, exact snapshot drift and absence of authority effects.
- `tests/steps/test_recovery_status.py` (new) — integrate `StatusPorts`, `show_attempt`, `list_attempts`, `current_view` and the existing round bench; cover the process gate and zero execution effects in successive reads/rounds.
- `tests/cli/test_step_status_cli.py` — command-level status coverage through `open_reads`, with unchanged database and artifact files.

## Read list
- `src/taskloop/recovery/store.py:27-141` — stop proof, snapshot reads/comparison and authorization fence.
- `src/taskloop/recovery/recover.py:48-166` — classification and shared observation paths.
- `src/taskloop/recovery/models.py:12-110` — typed observations, explanations and outcomes.
- `src/taskloop/recovery/observe.py:1-19` — native identity and process-group semantics.
- `src/taskloop/attempt_store.py:93-135` — eligibility, captured precedence and session restrictions.
- `src/taskloop/attempt_reads.py:184-212` — read versus write connection ownership.
- `src/taskloop/attempt_status.py:55-104` — ports and view fields.
- `src/taskloop/attempt_status.py:135-244` — next-word decisions and agent/check separation.
- `src/taskloop/attempt_status.py:278-317` — single-attempt reader.
- `src/taskloop/attempt_status.py:364-399` — listing, current view and hold application.
- `src/taskloop/cli_composition.py:94-121` — read-only connection and status composition.
- `src/taskloop/cli_composition.py:154-186` — round reader and hold callback composition.
- `src/taskloop/cli_step.py:229-240` — CLI show/list callers.
- `src/taskloop/dash_composition.py:37-65` — dashboard status-reader consumers.
- `src/taskloop/dash_task.py:270-282` — current-view consumer.
- `src/taskloop/round.py:173-205` — status snapshot producer/consumer and admission accounting.
- `src/taskloop/round.py:226-264` — next-word dispatch and no-action reports.
- `tests/steps/test_recovery_contract.py:1-85` — shared observation fixtures and race checks.
- `tests/steps/test_recovery_reconcile.py:1-65` — existing process classification cases.
- `tests/steps/test_recovery_observe.py:1-50` — native observation tests already delivered.
- `tests/steps/round_bench.py:206-244` — semantic round ports for the new integration tests.
- `tests/steps/test_operations.py:344-396` — existing status and no-write expectations.
- `tests/cli/test_step_status_cli.py:1-90` — CLI database/config fixtures.
- `tests/cli/test_step_status_cli.py:178-223` — read-only list and missing-database coverage.

## Contract
Intent: `Recovery.status(AttemptKey)` reads an unfinished registered attempt's recovery facts. Effect: short consistent read transactions around snapshot collection/comparison, native process observations outside those transactions, no slot lock acquisition, tracker access or writes. Result: existing `Observations | Result`; the claim is explicitly `ClaimState.UNKNOWN` with an explanation that status has not checked authority. Never manufacture an owned claim. Reuse native process collection; avoid duplicating eligibility SQL in status.

Keep `Recovery.observe` under custody for execution consumers. Preserve exact comparisons and the `authorize` committing fence. Read-only snapshots retain coherence and drift detection.

Intent: an injected `StatusPorts` reader informs `_agent` for unreleased, unfinished registered agent attempts. Effect: read-only calls only. Result: a live entry, worker/group or recorded recovery owner produces `wait` (or the existing expired-running report); an unknown identity, failed read or changed snapshot produces `unknown`. A missing owner record needs no owner probe. Unknown dominates a simultaneous live observation. Only confirmed absence may leave the existing stopped-attempt decision actionable. No new recovery next word is introduced in this task.

Apply this gate before setup/merge decisions or leftover probing can overwrite it. Incomplete recovery identity/session facts fail closed. Admitted attempts, checks attempts, captured completion, releases and explicit holds retain their existing owning paths; observation never reopens them. Existing constructor callers without a recovery reader remain valid, with relevant unfinished registrations conservatively unknown. No stored fields change.

## Work packages
1. Read-only recovery observation: update recovery store/read orchestration and contract tests. Close acceptance 1 with a real read-only reopened connection and fakes that reject custody, claim and execution effects.
2. Status integration: update attempt status and both composition producers; add the focused status/round test file and CLI coverage. Close acceptance 2, then run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last. Use no live processes or harnesses in tests.

## Acceptance behaviours
1. Reopened status reads use shared, snapshot-checked recovery observations and leave database rows, reservations, deadlines, recovery ownership and artifact files unchanged; observation drift/unavailability remains explained and conservative.
2. Live or unknown entry, worker/group or recovery-owner facts prevent actionable status and execution effects through show, list, current-view and round consumers, including expired entries; confirmed absence permits existing stopped decisions, while captured and explicitly held work retains its owning path.
