# Header
Task: tl-8bh9.14.145.1.2
Base: 3f0f48292becc35d10f14f67ff6a915b75307a18
Depth: large; schema bump
Decisions: settled. Dependency: part 1 landed.
Evidence budget: 20 model calls.
Size: 34 changed files including tests/artifacts; 3 independent behaviours; 55 implement model calls.

## Outcome and non-goals
A recorded hold owns an immutable cause snapshot. Recording is atomic with the currentness fence; retries and comments use that snapshot after evidence changes. Preserve reason projections and lifecycle. Scheduling, retry eligibility, tracker protocols, recovery ownership and shelf are outside scope. Deployment drains old entries and discards the old database; no live drain/restart here.

## Settled decisions
- The existing TaskEvent, cause models and codec already provide validation, causal identity and reason projection; reuse them.
- Store the event inside task_hold, whose owning store already provides atomic insertion and retirement. Do not add an independently mutable cause record.
- Replace stored cause_id and reason with the event payload; retain their read-facing values as projections. attempt_id remains the relational key and must match the payload.
- Construct causes from structured execution, answer, verification, checks, stop and refusal inputs at the hold decision. Do not parse display reasons back into events.
- Round and land refusals pass typed causes with their available explanation/context, rather than only a formatted reason.
- Increment the current schema version once, 31 to 32, with a new DDL digest pin. No migration or old-row fallback.

## Open decisions
- None.

## Change map
- src/taskloop/factory_schema.py — SCHEMA, HOLD: required event JSON, remove redundant cause columns, bump once.
- src/taskloop/hold_store.py — HoldInsert, HoldRow, _row, insert, uncleared: typed event input/output, projections and atomic fenced storage; correct positional row decoding.
- src/taskloop/hold_event.py (new) — event construction integrated by hold_task: select existing cause classes from structured inputs and capture deciding context before effects.
- src/taskloop/hold.py — hold_task, _caused: create an event only for a new hold, accept typed override causes, retain stored events on retries and use typed families for special fences.
- src/taskloop/hold_facts.py — facts, explanation, land_explanation: capture causal facts before insertion; render recorded cause context without re-deciding it from later evidence.
- src/taskloop/round.py — _held, _advance, _publish, round's land_passed callback: propagate typed round/land causes and refusal detail.
- src/taskloop/round_land.py — land_passed: construct LandCause at the refused land decision and pass it through the callback.
- .importlinter — generated module lists: include the new module through the existing contract generation workflow.
- tests/steps/test_hold_event.py (new) — exercise hold_event through hold_task inputs for each cause family and causal step.
- tests/steps/test_hold_store.py — held, put, HELD and store cases: typed payloads, atomic rejection, corrupt data and unchanged lifecycle fences.
- tests/steps/test_factory_schema.py — DDL_DIGESTS: pin version 32 and retain incompatible-version refusal coverage.
- tests/steps/test_hold.py — Bench.hold, direct HoldInsert calls, restart/retirement cases: explicit events and stable snapshot evidence.
- tests/steps/test_hold_status.py — ROW, recorded: valid events with correct agent/check identities.
- tests/steps/test_guide_words.py — ROW: typed row construction with the same projected guidance.
- tests/steps/test_task_status.py — HOLD: typed row construction preserving status assertions.
- tests/steps/test_attempt_stop.py — both HoldInsert producers: capture run/entry-loss stop context before storing.
- tests/steps/test_lost_entry.py — protect: construct the explicit stuck event without weakening recovery fences.
- tests/steps/test_merge_release.py — all three HoldInsert producers: explicit MergeCause including retained explanation.
- tests/steps/test_wip_merge.py — log: explicit stuck event; retain saved-commit assertions.
- tests/steps/test_dash_read.py — three HoldInsert producers: valid typed events; replace impossible synthetic causes with supported causes and preserve question isolation.
- tests/cli/test_step_status_cli.py — hold: explicit event fixtures and unchanged projected CLI fields.
- tests/steps/test_discussion.py — restart hold producer: explicit disposition event; retain unchanged-hold assertions during discussion collection.
- tests/steps/test_round.py — held: typed fixture preserving round reingestion behaviour.
- tests/steps/test_recovery_launch.py — changed-work fixture: valid event JSON in raw hold insert.
- tests/steps/test_recovery_status.py — held-work fixture: valid stuck event JSON.
- tests/steps/test_recovery_store.py — ineligibility fixture: valid event JSON in raw hold insert.
- tests/steps/test_continuation.py — held-work fixture: valid event JSON in raw hold insert.
- tests/steps/test_answer_repair.py — held-work fixture: valid event JSON in raw hold insert.
- tests/steps/test_check_repeat.py — held-source fixture: valid implement/check event with the same exclusion fence.
- tests/steps/test_attempt_listing.py — finished/unfinished hold fixture: valid payload and canonical projected reason.
- docs/design/tl-8bh9.14.145.1.2/plan.md — implementation contract and bounded read list.
- docs/design/tl-8bh9.14.145.1.2/plan-metadata.json — preparation commit and consulted paths.

## Read list
- src/taskloop/factory_schema.py:44-55,257-273,310-318 — version/DDL/columns.
- src/taskloop/hold_store.py:24-230 — fences, decoding and lifecycle.
- src/taskloop/hold.py:93-157,195-268 — decision and effects.
- src/taskloop/hold_status.py:18-88 — eligibility/reingestion.
- src/taskloop/hold_facts.py:75-139 — causal evidence capture.
- src/taskloop/attempt_status.py:66-104,368-400 — identity/projection.
- src/taskloop/attempt_types.py:291-330; src/taskloop/attempt_result.py:10-84 — structured results/precedence.
- src/taskloop/check_status.py:25-79 — checks identity/status.
- src/taskloop/round.py:193-202,309-323,386-408,467-484 — production hold callers.
- src/taskloop/round_land.py:29-69 — refusal callback.
- src/taskloop/task_event.py:25-56; src/taskloop/task_event_cause.py:145-298; src/taskloop/task_event_codec.py:18-62 — validation/codecs.
- src/taskloop/result_data.py:46-78 — output projections.
- src/taskloop/slot_release_store.py:23-31; src/taskloop/answer_repair_store.py:75-85 — existence fences.
- .importlinter:687-825 — generated lists.
- tests/steps/test_hold.py:122-140,190-245,300-358,510-611; tests/steps/test_hold_store.py:25-309 — producers/lifecycle/constraints.
- tests/steps/test_factory_schema.py:15-38,113-150 — DDL/version guard.
- tests/steps/test_hold_status.py:26-35,127-138; tests/steps/test_guide_words.py:19-23; tests/steps/test_task_status.py:25-30 — row fixtures.
- tests/steps/test_attempt_stop.py:37-68,91-113; tests/steps/test_lost_entry.py:99-115 — stop producers.
- tests/steps/test_merge_release.py:54-100; tests/steps/test_wip_merge.py:38-44 — preservation producers.
- tests/steps/test_dash_read.py:90-101,183-212; tests/cli/test_step_status_cli.py:204-214 — presentation producers.
- tests/steps/test_discussion.py:179-202; tests/steps/test_round.py:211-222; tests/steps/test_round_land.py:114-132; tests/steps/test_round_holds.py:415-431 — producers and refusal integration.
- tests/steps/test_recovery_launch.py:103-109; tests/steps/test_recovery_status.py:109-118; tests/steps/test_recovery_store.py:174-184 — recovery SQL fixtures.
- tests/steps/test_continuation.py:85-95; tests/steps/test_answer_repair.py:165-175 — exclusion SQL fixtures.
- tests/steps/test_check_repeat.py:225-237; tests/steps/test_attempt_listing.py:245-258 — checks/listing SQL fixtures.
- tests/rules/test_policy.py:99-105 — SQL ownership.

## Contract
Intent: hold_task first loads an existing hold. Only when absent does the deciding operation build TaskEvent using the held agent identity, causal attempt identity/step and an existing discriminated cause. HoldInsert carries that event and recording time, with no independently supplied cause ID or reason. Use validated pydantic models for the changed persistence boundary.

Effect: HoldStore.insert validates payload/key consistency and applies the existing current-agent/latest-checks/no-existing-hold fence in the same short transaction as insertion. Required JSON is stored as task_hold.event; malformed or inconsistent persisted events fail through the store's unavailable boundary. A failed fence or validation stores nothing and performs no tracker/release action. Hand-started exceptions use MergeCause/LandCause, preserving their current scope.

Result: HoldRow exposes the event and projects attempt_id, cause_id and reason, checking the relational key. Joined facts and lifecycle fields keep their meanings. Retirement deletes the embedded event. Saved commits, revision fencing and comment leasing retain their owner.

Capture the available explanation, answer failure, run deadline/timeout/rc/stop, failed check conclusions, repeat leftovers and merge/land source/target/conflicts at the decision. Mandatory model context must be supplied before effects; unavailable evidence is not replaced with a fabricated cause. Use structured stored facts and closed enum values; do not split formatted reason strings to infer a cause. Checks use the causal checks ID and owning implement ID.

Retries render causal context from the stored event. Current claim/process/slot observations still decide whether abandon is possible; current status still decides retirement. Evidence/log locations may be resolved through their owning readers, but cannot replace the event's explanation, failures, stop or leftovers. No new scheduler state or external effect enters the storage transaction.

## Work packages
1. Establish atomic storage (A): change factory_schema and hold_store together; update schema/store tests and every direct SQL/row fixture in the change map. Retain existing codecs, saved work and relational attempt fences.
2. Connect typed decisions (B): add hold_event and its focused tests; wire hold_task, round._held/_advance/_publish and round_land.land_passed. Update every HoldInsert producer found above. Use existing eligibility policy and structured context; cover all ten existing cause families without duplicating codec validation tests.
3. Preserve lifecycle snapshots (C): adapt hold_facts and retry/comment paths; exercise evidence mutation, latest-check races, restart, lost comment responses, retirement and re-hold. Verify CLI/dashboard projections and recovery exclusions. Place event construction in the new module to respect size caps. Refresh generated import contracts. Last, run just check 2>&1 | tail -60 and just test 2>&1 | tail -40 once each, retaining and reporting actual exit status; no live tests.

## Acceptance behaviours
- A: a valid event round-trips with its hold; invalid/corrupt data cannot become a usable hold, and stale/currentness/duplicate races leave no partial record. Version 32 is pinned and older databases are refused.
- B: every eligible cause family and round/land refusal records the correct agent/check causal identity and available context; all producers use typed events, existing valid reason projections remain exact, and ineligible transient conditions still create no hold.
- C: after recording, source evidence changes and restart cannot change the cause snapshot; revision/lease races, lost comment responses, release refusals, clearing, saved work and retirement retain their behaviour, including a fresh event on a later valid hold.
