# Header
Task: tl-8bh9.14.155.3.4
Base: 203c7244352988d08a908a176567d166f78bf001
Depth: medium; three behaviours
Owner decision: none missing. Dependency .155.3.3: landed.
Evidence budget: 12 model calls.
Size: 10 changed files including plan; 3 behaviours; 45 implement model calls.

## Outcome and non-goals
Active conflict execution already returns retryable unavailable outcomes. Terminal conflicts already enter the durable hold operation. Summaries already bypass execution. Remaining gaps: land conflict holds permit approval-label reingestion, offer branch replacement/replanning advice, and omit retained resolution explanations from checks-caused notices.
Exclude resolution execution, delivery reconciliation, summary content changes, schema changes and new owner recovery commands.

## Settled decisions
- Active work retains its admission, deadline and execution count.
- Terminal land conflicts remain held when approval labels return.
- Reuse existing land causes and holding; other refusals retain their policy.
- Summary and dashboard reads perform no conflict or delivery transition.

## Open decisions
- None.

## Change map
- `src/taskloop/hold_cause.py`: classify `land:conflict`; replace branch-replacement advice with retained-work wording.
- `src/taskloop/hold_status.py`: `reingests` excludes terminal land conflicts as well as terminal merges; leave retryable land outcomes outside holding.
- `src/taskloop/hold_text.py`: `_answer` uses the terminal classification to explain the hold without label/replan instructions or CLI commands.
- `src/taskloop/hold_guide.py`: `hold_guide` uses the same classification for pending and completed terminal land holds.
- `src/taskloop/hold_facts.py`: `facts` obtains the exact admission's stored terminal explanation for `HoldFacts`.
- `tests/steps/test_hold_status.py`: cover terminal land holds resisting reingestion and ordinary land holds retaining their policy.
- `tests/steps/test_round_land.py`: cover retries, interrupted hold completion, one terminal notice, retained explanation and approval-label resistance.
- `tests/steps/test_land_conflict_handoff.py`: cover running, unknown and unavailable results without resetting work.
- `tests/steps/test_land_summary.py`: cover active, terminal and accepted retained work, including dashboard reads.
- `docs/design/tl-8bh9.14.155.3.4/plan.md`: this implementation contract.
- Consult under `src/taskloop/`: `land_conflict/handoff.py` (`stopped`, `resume`), `land_conflict/store.py` (`find`, `completed`), `merge/store.py` (`get`): outcome and evidence producers.
- Consult `land.py` (`_made`, `_summary`), `round_land.py` (`land_passed`), `round.py` (caller), `dash_land.py` (`build_land`): execution/read boundaries, under `src/taskloop/`.
- Consult `hold.py` (`_caused`, `_abandoned`), `task_status.py` (`restartable`, `waiting_for_land`), `attempt_status.py` (`_show`, `_swapped`): hold/status callers, under `src/taskloop/`.
- Consult `show_render.py` (`hold_lines`), `step_render.py` (`hold_guide`), `round_guide.py`, `dash_board.py` (`cause`), `step_guide.py`, `operations.py` (constant imports), under `src/taskloop/`.

## Read list
- `src/taskloop/hold_cause.py:95-150` — land causes and explanation codec.
- `src/taskloop/hold_status.py:48-87` — cause and reingestion rules.
- `src/taskloop/hold_text.py:165-200` — terminal answer and comment assembly.
- `src/taskloop/hold_guide.py:42-90` — status guidance consumers.
- `src/taskloop/hold_facts.py:77-107` — checks versus agent evidence selection.
- `tests/steps/test_hold_status.py:65-145` — completed holds and label answers.
- `tests/steps/test_round_land.py:44-187` — automatic land port, holds and retries.
- `tests/steps/test_land_conflict_handoff.py:120-216` — retained completion and running execution.
- `tests/steps/test_land_summary.py:116-156` — summary invariants and retained work.
- `src/taskloop/dash_land.py:29-50` — dashboard summary integration.
- `src/taskloop/land_conflict/store.py:118-130` — existing admission lookup.
- `src/taskloop/land_conflict/handoff.py:20-90` — result conversion, resume and admission identities.
- `src/taskloop/merge/store.py:1-19` — typed stored decision reader.
- `src/taskloop/land.py:210-239` — retained resolution producer integration.
- `src/taskloop/land.py:348-391` — summary separation and public operation.
- `src/taskloop/round_land.py:27-69` — retry versus terminal hold dispatch.
- `src/taskloop/round.py:190-202` — land caller and slot reservation.
- `src/taskloop/hold.py:127-140` — hold-cause fence.
- `src/taskloop/hold.py:193-220` — facts and notice effect boundary.
- `src/taskloop/task_status.py:80-112` — retry eligibility and held status.
- `src/taskloop/attempt_status.py:162-202` — checks and land status production.
- `src/taskloop/show_render.py:150-160` — held status renderer.
- `src/taskloop/step_render.py:65-82` — hold guidance caller.
- `src/taskloop/round_guide.py:1-45` — cause rendering caller.
- `src/taskloop/dash_board.py:1-75` — dashboard cause consumer.

## Contract
Classify the existing terminal land conflict cause through one enum-backed vocabulary in `hold_cause`. No new phase or stored field. Unavailable `Failed` results never create a hold; refused conflicts retain their existing durable cause.

In `facts`, build `ConflictStore.find`'s request from the checks row and original agent key; its target placeholder grants no execution authority. Read `MergeStore.get(record.key.attempt_id)` and validate operation identity and terminal phase before using its explanation. Missing evidence uses generic retained-work wording; malformed or unavailable evidence remains retryable. Evidence reads must work after reservation release.

Intent: the existing hold row records the cause. Effect: the existing hold operation changes labels, settles custody/claim and writes its notice outside store transactions. Result: its durable completion fields prevent repeats after restart. Approval-label changes do not retire or reingest terminal holds; retries retain the original resolution limit.

Summary intent remains observation, allowing existing Git fetch/object construction. No conflict admission, execution, preservation, release, checks, push, tracker writes or hold creation. Summary readers must not call `Handoff.resume`; status reads perform no transition.

## Work packages
1. Update `hold_cause`, `hold_status`, `hold_text`, `hold_guide` and `test_hold_status`: close A2's terminal policy and guidance.
2. Update `hold_facts`; extend `test_round_land` through the real hold boundary, including interruption and changed labels: close A2's retained explanation and exactly-once effects.
3. Extend `test_land_conflict_handoff` and `test_land_summary`, including dashboard reads: close A1 and A3. Targeted implementation reads cover constant imports in `step_guide.py` and `operations.py`.
4. Run the final focused gates once each, last: `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, preserving pipeline exit status. No live tests.

## Acceptance behaviours
A1. Running, unobservable or temporarily unavailable conflict work stays retryable across rounds and restart, creates no hold, and retains the same admission, deadline and resolution execution count.
A2. A terminal conflict decision produces one durable hold and one notice carrying its verified retained explanation; interrupted effects reconcile, later rounds and restored approval labels leave it held, unrelated land causes retain their policy, and guidance states the decision without CLI or replanning instructions.
A3. CLI summaries, dashboard delivery summaries and status reads for active, terminal and accepted retained conflict work leave resolution, reservations, holds, checks, delivery and tracker state unchanged across repeated reads.
