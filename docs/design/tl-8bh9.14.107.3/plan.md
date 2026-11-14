# Header
Task: tl-8bh9.14.107.3; base: f720ecce0ae276391994b7ec58b3cc562e442116
Depth: small; one claim behaviour
Decision missing: no; dependency unlanded: none stated.
Evidence: 6 model calls.
Size: 5 files including tests/plan; 1 behaviour; 45 implement calls.

## Outcome and non-goals
Normal restart releases an unfinished admission's claim through the existing fenced adapter before ordinary admission. Excludes attempt/session recovery, database-discard retaking and unrelated claims.

## Settled decisions
- Admission already records ActionKind.CLAIM before calling the tracker; retain that durable intent.
- Reconcile already adopts an attempt's claim or returns a claim without an attempt; reuse it.
- Captured-session and lost-entry recovery are delivered; do not repeat their implementations.
- Use existing action storage and liveness observations; no schema change or tracker-wide scan.

## Open decisions
- None.

## Change map
- `src/taskloop/drain/drain.py`: add claim-only reconciliation sharing ownership/observation handling with `inspect`; preserve drain semantics.
- `src/taskloop/cli_composition.py`: `open_rounds` reconciles claims through `open_drain` before scheduling, including an open drain boundary.
- `tests/steps/test_claim_restart.py` (new): exercise claim crash boundaries using `DrainStore`, `Reconcile` and admission helpers.
- `tests/cli/test_factory_restart.py`: cover normal restart composition without retake enabled.
- `docs/design/tl-8bh9.14.107.3/plan.md`: retain this implementation contract.
- Consult producers/callers: admission's `_claim_then_admit`; `open_drain`, `_return_claim`, `Reconcile.__call__`, `run_round`, `_run_round`, `round_bench.Factory`; drain-fence callers of `Reconcile`/`inspect`.

## Read list
- `src/taskloop/admit.py:211-260` — claim intent producer and admission commit boundary.
- `src/taskloop/drain/drain.py:15-90` — ports, observation and action reconciliation loop.
- `src/taskloop/drain/store.py:65-170` — authorize, adopt, finish, uncertain and pending storage.
- `src/taskloop/drain/observe.py:10-33` — boot-aware owner liveness.
- `src/taskloop/drain/reconcile.py:19-39` — attempt adoption versus claim return.
- `src/taskloop/drain/composition.py:39-84` — fenced tracker return and production ports.
- `src/taskloop/cli_composition.py:250-310` — rounds lock and restart integration.
- `src/taskloop/round.py:155-210` — scheduling consumer.
- `src/taskloop/tracker.py:91-111` — existing discard-only retake boundary.
- `tests/steps/test_drain_fences.py:48-125` — admission/action fixtures and drain regression cases.
- `tests/steps/round_bench.py:210-245` — scheduling test integration.
- `tests/cli/test_factory_restart.py:55-109` — restart composition and refusal coverage.

## Contract
Intent: reconcile persisted CLAIM actions in this database. Observe owners before adoption; live/unknown owners remain untouched. Effect: after fenced adoption, invoke Reconcile outside a write transaction. Result: finish after observed release/nonownership or adoption by an attempt; tracker uncertainty stays retryable. Observe the tracker again after a crash between release and finish. No new fields or outcome vocabulary. Surface unresolved reconciliation without admitting that task or requiring retake.

## Work packages
1. Add the shared claim-only operation and wire normal startup in the two source files; close A1.
2. Add crash/reopen, ownership, retry and production-composition coverage in the two test files; close A1. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
A1: Reopening an intact database after claim acquisition but before attempt creation returns that claim and permits ordinary admission without retake; retries converge across crashes before acquisition and after release, while existing attempts, live/unknown owners and unrelated claims remain protected and tracker failures retain a retryable intent.
