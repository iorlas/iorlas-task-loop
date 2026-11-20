# Header
Task: tl-8bh9.14.155.3.2; base: e752ae5d6944787089e270cceaa50faf7207d55e
Depth: medium; three behaviours
Decisions: none missing; prerequisite .3.1 landed. Evidence budget: 12 model calls.
Size: 7 changed files including tests and plan; 3 behaviours; 45 implement model calls.

## Outcome and non-goals
Land validates retained resolution bytes with original implement/checks attribution. Exclude rebasing after target movement, push/close reconciliation, terminal holds, dashboard and schema changes.

## Settled decisions
- Accepted saves already retain commit, inputs and release independently of slot custody; preserve this protocol.
- Reuse `merge.models.Completed`; require durable accepted release before promotion.
- Fetch origin main for required checks and gate inputs; always validate resolved candidates, including equal trees.
- A different target stops promotion and preserves the resolution; rebasing belongs to delivery reconciliation.
- Candidate rows own interrupted validation and resume without another resolution invocation.

## Open decisions
- None.

## Change map
- `src/taskloop/land_conflict/handoff.py` — `Handoff.resume/start/conflicted`, `stopped`: expose verified durable completion.
- `src/taskloop/land.py` — `_made`, `_delivered`, `_pending`: consume completion, force fresh validation and resume candidates first.
- `src/taskloop/land_target.py` — `made_s`, `squashed_onto`: allow resolved source while retaining original attribution.
- `tests/steps/land_bench.py` — `LandBench.conflicts`: support durable completion fixtures.
- `tests/steps/test_land_conflict_handoff.py` — `executing`, land assertions: replace accepted-stop expectations; retain other outcomes and read-only coverage.
- `tests/steps/test_land_resolved_validation.py` (new) — integrate `LandBench`, `ExecutionCase`, `land`, `ConflictStore.completed` for A1–A3.
- `docs/design/tl-8bh9.14.155.3.2/plan.md` (new) — implementation contract.
- `src/taskloop/land_conflict/composition.py` — consult `conflict_handoff`, production constructor and execution producer.
- `src/taskloop/land_conflict/execute.py` — consult `execute`, completed-result producer/replay.
- `src/taskloop/land_conflict/store.py` — consult `find`, `completed`, `release`, identity and completion readers.
- `src/taskloop/land_conflict/preserve.py` — consult `Preservation._intent`, retained evidence producer.
- `src/taskloop/land_conflict/models.py` — consult `Request`, `Record`, `Save` contracts.
- `src/taskloop/merge/models.py` — consult `Completed` contract.
- `src/taskloop/land_check.py` — consult `inserted`, `checked`, `validated`, candidate consumers.
- `src/taskloop/land_store.py` — consult `LandRow`, `require_checked`, `insert` fences.
- `src/taskloop/land_summary.py` — consult `message_at`, attribution producer.
- `tests/steps/test_land_conflict_accepted_release.py` — consult accepted-release and slot-reuse assertions.
- `tests/steps/test_land_resume.py` — consult interruption and liveness assertions.

## Read list
- `src/taskloop/land.py:210-239` — candidate creation and validation shortcut.
- `src/taskloop/land.py:267-304` — pending validation and conflict-resume precedence.
- `src/taskloop/land_conflict/handoff.py:19-69` — all result adapters and their callers.
- `src/taskloop/land_target.py:26-101` — target checks, squash construction, tree comparison and gate.
- `src/taskloop/land_check.py:83-139` — validation result, release and atomic reservation.
- `src/taskloop/land_check.py:225-244` — validation custody and process observation.
- `src/taskloop/land_store.py:78-112` — candidate source, target and validation fields.
- `src/taskloop/land_store.py:164-193` — original eligibility and candidate admission fences.
- `src/taskloop/land_conflict/store.py:24-59` — immutable identity lookup and historical completion.
- `src/taskloop/land_conflict/store.py:96-129` — release result and find/load boundaries.
- `src/taskloop/land_conflict/models.py:21-114` — retained inputs and save fields.
- `src/taskloop/land_conflict/execute.py:48-65` — completed-result producer and replay.
- `src/taskloop/land_conflict/preserve.py:90-104` — retained commit/ref input production.
- `src/taskloop/land_conflict/composition.py:33-62` — production constructor and credential boundary.
- `src/taskloop/merge/models.py:117-136` — completion and noncompletion result types.
- `src/taskloop/land_summary.py:69-73` — original checks provenance in commit message.
- `tests/steps/land_bench.py:194-239` — ports, conflict execution and observable effects.
- `tests/steps/test_land_conflict_handoff.py:41-90` — fixtures and ordinary conflict refusals.
- `tests/steps/test_land_conflict_handoff.py:145-234` — accepted, interrupted and production-wiring integration assertions.
- `tests/steps/test_land_conflict_accepted_release.py:51-74` — retained commit after independent base release.
- `tests/steps/test_land_conflict_accepted_release.py:244-271` — completion reads after slot reuse.
- `tests/steps/test_land_resume.py:25-92` — interruption, deadline renewal and liveness.

## Contract
Handoff: `Completed | Failed`, also `None` for absent work in `resume`. Require `ConflictStore.completed(record.key)` to prove accepted release with matching result/source/target/commit. Verify retained ref/object. Pending release, missing objects or inconsistent evidence stop promotion with an explanation. Read historical completion before execution or credential acquisition.

Intent: match original implement/checks identities; fetch O and required checks after resolution. Require O equal the resolution target. Squash accepted content onto O using original task/checks attribution. Compare S with original X and O; inspect the gate. Preserve `ChecksRow.commit` and checked input. Always validate resolved S; `same_tree` grants no shortcut.

Effect/result: construct Git objects outside write transactions. Existing `inserted` atomically reserves a slot and records S/O/required checks. Existing validation records results and releases custody. Only passed validation reaches delivery. No schema change or new stored fields.

Resume: before insertion, reread accepted completion; after insertion, use persisted S/O/checks through pending/delivery paths. Renew deadlines and reconcile liveness. Never replay completed resolution, plan or implementation. Preserve the retained ref. Target movement must stop safely rather than reverting to conflicting X; rebasing is outside scope.

## Work packages
1. `handoff.py`, `land_bench.py`, handoff tests: expose durable completion; close A1.
2. `land.py`, `land_target.py`, new validation tests: construct and validate S at fresh O; close A2.
3. `land.py`, handoff and new validation tests: resume pending candidates across interruptions; close A3. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
A1. An accepted, durably released resolution supplies its exact retained bytes after restart or slot reuse without another agent invocation; incomplete release or mismatched/missing retained evidence creates no candidate and preserves saved work.
A2. With unchanged current target, resolved bytes pass the fresh target gate and required checks before delivery, even for equal trees; stale target, missing validation deadline, rejected gate or failed checks cannot push or close and retain the resolution.
A3. Interruption before insertion reuses accepted completion; interruption after insertion resumes the same candidate with renewed deadline and existing process reconciliation, without plan, implementation or resolution replay; only successful validation resumes delivery.
