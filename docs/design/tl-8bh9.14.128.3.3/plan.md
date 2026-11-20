# Header
Task: tl-8bh9.14.128.3.3; base: 947165975e0dea1ee7fb723a7b82fd888677f35a
Depth: medium; three completion behaviours.
Owner decisions: none; dependency landed.
Evidence budget: 12 model calls.
Size: 3 changed files, 3 independent behaviours, 45 implement model calls.

## Outcome and non-goals
Exercise recovery and completion through production round operations over a closed and reopened file database. Use semantic fakes at process, harness, tracker and Git boundaries. Exclude live termination, real remote publication, schema changes and new recovery policy.

## Settled decisions
- The predecessor is landed; no dependency blocks this verification task.
- Existing tests cover recovery launch, entry, status and release separately; the gap is completion together after database reopen.
- Verification, release and publication are the three independently asserted behaviours, labelled A1–A3 below.
- Reuse `round_bench.Factory` with `adopted=True` when reopening; rebuild its database-bound ports and preserve external fake state separately.
- Use `Recovery`, `Continuation`, `NativeContinuation` and `CapturedCompletion` rather than faking successful recovery or verification results.
- Keep publication scoped to the verified task branch. Landing and task closure are outside this task.
- Count logical effects and calls; idempotent retries must not create another commit or remote change.

## Open decisions
- None.

## Change map
- `tests/steps/killed_rounds_bench.py` (new): compose `round_bench.Factory`, recovery-aware `StatusPorts`, continuation dispatch and `CapturedCompletion`; add close/reopen, interruption hooks and effect observations.
- `tests/steps/test_killed_rounds.py` (new): parametrized restart scenarios exercise A1–A3 through `run_round`, including repeated reopen after completed effects and conservative liveness gates.
- `docs/design/tl-8bh9.14.128.3.3/plan.md`: this bounded implementation and verification plan.
- Consult `src/taskloop/round.py`: `run_round`, `_run_round`, `_settle`, `_verified` and completion callback; retain their real dispatch and completion decisions.
- Consult `src/taskloop/cli_composition.py`: `_starting` produces launcher ports; `open_next` composes round ports; `one_round.once` calls `open_next` and `run_round`; `open_rounds` reconciles restart before rounds.
- Consult `src/taskloop/composition.py`: `open_launcher`, `open_verifier`, `open_releaser`, `open_publisher` produce the operations under test.
- Consult `tests/steps/round_bench.py`: `Factory.round` calls `run_round`; adapt `ports`, `launch`, `releaser` and `starting` for recovery in the new fixture.

## Read list
- `tests/steps/round_bench.py:145-257` — adoption, launch, port construction and round caller.
- `tests/steps/test_attempt.py:1-90` — semantic attempt surroundings and valid plan answer shape.
- `tests/steps/test_native_continuation.py:30-107` — harness resume fake, hooks and pending result production.
- `tests/steps/test_recovery_entry.py:35-110` — entry composition, custody and capture assertions.
- `tests/steps/test_recovery_launch.py:30-100` — recovery dispatch authorization and permit fence.
- `tests/steps/test_recovery_store.py:20-52` — file database setup and durable identity facts; avoid its synthetic Git identities in the integrated fixture.
- `tests/steps/test_recovery_callbacks.py:30-65` — registered callbacks and valid continuation result producer.
- `tests/steps/test_recovery_status.py:25-65` — recovery-aware status port and liveness cases.
- `tests/steps/test_recovery_release.py:25-95` — retained recovery identities and release blocking.
- `tests/steps/test_claim_restart.py:30-112` — close/reopen and external-effect interruption pattern.
- `src/taskloop/round.py:110-135` — `RoundPorts` completion and recovery integration fields.
- `src/taskloop/round.py:155-297` — settle, relaunch, release and publish dispatch.
- `src/taskloop/round.py:337-395` — verification/completion consumer and its downstream effects.
- `src/taskloop/cli_composition.py:142-195` — launcher producer and production round composition.
- `src/taskloop/cli_composition.py:205-219` — round consumer used by rounds.
- `src/taskloop/cli_composition.py:270-302` — intact-database startup reconciliation.
- `src/taskloop/composition.py:95-149` — continuation, captured completion and attempt producers.
- `src/taskloop/composition.py:195-227` — completion operations and recovery launcher producer.
- `src/taskloop/recovery/complete_attempt.py:13-59` — captured completion under custody without execution authorization.
- `src/taskloop/recovery/status.py:21-53` — conservative recovery process gate.
- `src/taskloop/verifier.py:58-145` — captured-answer preconditions and idempotent verification.
- `src/taskloop/publish.py:137-175` — publication operation and stored-result fast path.
- `src/taskloop/slot_release.py:110-143` — reservation deletion and release identity facts.

## Contract
No new production types, states, stored fields or vocabulary. New fixture classes are test support only and use existing typed ports and outcomes.

Intent: interrupt an admitted task with a saved session. Effect: close owned database handles, retain worktree, artifacts and external fake state, then compose fresh ports. Result: retain `AttemptKey`, dispatch generation, claim and session reference without inserting another attempt or slot.

Intent: finish after process stop proof and claim confirmation. Effect: dispatch saved-session continuation with real hooks and capture, then complete through `CapturedCompletion` and `Verifier`. Result: one continuation before capture; no harness invocation after capture. The real verifier determines commit and verdict.

Intent: release and publish that verified result. Effect: the real releaser checks recovery liveness and parks the slot; the real publisher sends the pinned commit through a fake remote. Result: one release record, reservation removal and publication record for the original attempt, with retained evidence and branch content. No release or publish success is supplied by a stub.

Retain fake Git and tracker state across reopen; rebuild database-bound objects. Instrument boundary effects, not logs. Suppress unrelated advancement through tracker inputs after the target step.

## Work packages
1. Add `killed_rounds_bench.py`: reuse admission and fake Git setup; wire recovery reads, continuation and captured completion; add interruption hooks and reopen without seeding. Enables A1–A3.
2. Add `test_killed_rounds.py`: interrupt before capture and after capture, resume through rounds, and assert stable identities, one verified commit and no extra harness execution. Close A1.
3. In that test file, reopen before/after release and publication. Repeat rounds and idempotent operations; count commit, park, claim and remote effects and preserve artifact bytes. Include live/unknown recovery observations. Close A2–A3.
4. Run a focused file check if needed using `uv run --frozen --no-sync python -I -m pytest -q tests/steps/test_killed_rounds.py --tb=short | tail -40` after installation. Finish the implement attempt with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, last. Gates must pass.

## Acceptance behaviours
A1: Reopening an interrupted saved session completes verification on the original attempt and session, produces the expected selected-path commit once, and never executes the harness again after capture.
A2: Recovery liveness that is alive or unknown prevents release; once stopped, reopened completion releases the original reservation once while preserving branch work, claim ownership and evidence through repeated completion.
A3: Reopened completion publishes exactly the verified commit to the task branch; subsequent rounds and reopen preserve the recorded result without duplicate execution, another logical delivery or changed evidence.
