# Header
Task: tl-8bh9.14.107.3
Base: 16ef79887d13fb5465b0a39c240195e3d159f720
Depth: small; one claim behaviour
Owner decision missing: no; dependency unlanded: none stated.
Evidence budget: 6 model calls.
Size: 1 changed file (plan); 1 behaviour; 20 implement calls.

## Outcome and non-goals
Claim-only reconciliation and restart tests exist; remaining work is verification. No source gap was found. Exclude attempt/session recovery, discarded databases and unrelated claims.

## Settled decisions
- Release an unfinished admission's claim before scheduling; ordinary admission may then claim it.
- Retain durable CLAIM intent, fenced adoption and tracker observation.
- Preserve live/unknown owners and claims adopted by attempts.
- No schema or shelf changes.

## Open decisions
- None.

## Change map
- `src/taskloop/drain/drain.py`: retain `reconcile_claims`, `_inspect` filtering.
- `src/taskloop/cli_composition.py`: retain `open_rounds` startup integration.
- `src/taskloop/admit.py`: consult `_claimed`, `_claim_then_admit` producer.
- `src/taskloop/drain/composition.py`: consult `open_drain`, `_return_claim`, Reconcile construction.
- `src/taskloop/drain/reconcile.py`: consult `Reconcile.__call__` adoption.
- `src/taskloop/drain/store.py`: consult `authorize`, `adopt`, `finish`, `uncertain`, `pending`.
- `src/taskloop/drain/observe.py`: consult `observe` liveness.
- `src/taskloop/cli_step.py`: consult `_rounds` caller.
- `tests/steps/test_claim_restart.py`: retain `ports` Reconcile construction and reconcile_claims cases.
- `tests/cli/test_factory_restart.py`: retain `open_rounds` restart cases.
- `tests/cli/test_open_rounds.py`: consult `open_rounds` callers.
- `tests/cli/test_cli_flags.py`: consult `open_rounds` double.
- `tests/steps/test_drain.py`: consult `Reconcile` caller.
- `tests/steps/test_drain_fences.py`: consult `Reconcile` caller.
- `docs/design/tl-8bh9.14.107.3/plan.md`: refresh assessment and verification.

## Read list
- `src/taskloop/drain/drain.py:26-80` — claim-only operation.
- `src/taskloop/cli_composition.py:268-308` — startup ordering.
- `src/taskloop/admit.py:212-253` — intent and claim boundary.
- `src/taskloop/drain/composition.py:39-83` — observation/release.
- `src/taskloop/drain/reconcile.py:19-39` — adoption versus release.
- `src/taskloop/drain/store.py:66-134` — action ownership.
- `src/taskloop/drain/observe.py:18-32` — liveness.
- `src/taskloop/cli_step.py:198-208` — CLI caller.
- `tests/steps/test_claim_restart.py:34-162` — crash, ownership and retry cases.
- `tests/cli/test_factory_restart.py:124-191` — production startup cases.
- `tests/cli/test_open_rounds.py:55-100` — startup callers.
- `tests/cli/test_cli_flags.py:46-46` — composition double.
- `tests/steps/test_drain.py:303-303` — Reconcile integration.
- `tests/steps/test_drain_fences.py:231-231` — Reconcile integration.
- `docs/design/tl-8bh9.14.107.3/plan.md:1-7` — assessment.

## Contract
Intent: persisted ActionKind.CLAIM identifies unfinished admission. Effect: only after Seen.GONE, adopt with its revision fence; call Reconcile outside the write transaction. Result: finish after an attempt adopts the claim or tracker observation confirms release/nonownership. Uncertainty stays durable and blocks scheduling. Restart observes again after a crash during release. Preserve non-CLAIM actions. No new typed names or stored fields.

## Work packages
1. Confirm retained source and coverage satisfy A1; no additions are currently identified.
2. Validate A1: run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last. This plan attempt has not run gates.

## Acceptance behaviours
A1: Intact-DB restart releases a dead admission owner's pending claim and permits ordinary admission with retake disabled; crash retries converge, uncertainty blocks scheduling, and attempts, live/unknown owners and unrelated claims remain protected.
