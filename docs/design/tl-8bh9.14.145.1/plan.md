# Header
tl-8bh9.14.145.1 @ c8906e46b26e0dc092047e0e681f075e8f89fe46
Depth: large
Schema change; cohesive. No missing owner decision or explicitly unlanded dependency.
Evidence ceiling: 20 model calls.
Size: about 24 changed files, 3 behaviours, 75 implement model calls.

## Outcome and non-goals
Replace a hold's opaque persisted reason with a validated TaskEvent snapshot recorded when the hold is decided. Existing hold reads obtain their reason from that snapshot; later event consumers can read the typed cause without reconstructing it from changing attempt state. Preserve the existing fenced hold lifecycle, saved commits and release behaviour. Dashboard event rows and their detail panel, unrelated lifecycle instrumentation, and the downstream .162 work are outside this storage link.

## Settled decisions
- The schema bundle lands as code before activation; its single matching-runtime drain and restart follow the chain. Do not drain the running factory during an implementation attempt.
- Use the existing drain command before discarding the old database and activating the new schema; the current compatibility gate already refuses incompatible databases.
- TaskEvent is the authoritative stored cause. A HoldRow reason remains a display projection, rather than a second persisted fact.
- The hold decision records agent/check failures, stuck conditions, exhausted repeats, terminal merge causes and explicit advance, publication and land refusals through the same store path.
- Preserve the distinction between the held agent attempt and the attempt supplying the cause, including a latest checks attempt.
- A retired hold releases its active lifecycle record, while its event remains available as evidence of the decision.

## Open decisions
- None.

## Change map
- `src/taskloop/task_event.py` (new): TaskEvent, closed cause variants and their codec; integrated by hold_task and HoldStore.
- `src/taskloop/events/__init__.py` (new): package marker for the event persistence feature; integrated through events.api.
- `src/taskloop/events/api.py` (new): public event-store operations consumed by HoldStore.insert and its row loaders.
- `src/taskloop/events/store.py` (new): transaction-local append and typed batch reads behind events.api; owns event SQL.
- `src/taskloop/factory_schema.py`: SCHEMA and HOLD; add the event table and hold reference, replace persisted reason ownership, increment 31 to 32 once.
- `src/taskloop/hold_store.py`: HoldInsert, insert, _row and row loaders; accept a typed cause, atomically persist its event and hold, and project existing HoldRow fields from the event.
- `src/taskloop/hold.py`: hold_task; construct the typed cause from decision inputs before insertion; reuse the recorded cause on retries.
- `src/taskloop/hold_status.py`: cause; consult the complete existing cause classification when defining typed variants; preserve hold eligibility.
- `src/taskloop/hold_cause.py`: cause and terminal_cause; consult reason spellings and diagnostic context for the single projection codec.
- `src/taskloop/attempt_status.py`: AttemptView and hold_due; consult agent/check identity and status classification inputs.
- `src/taskloop/round.py`: _held, _advance and _publish; consult the production caller and explicit refusal producers; preserve their shared hold_task path.
- `src/taskloop/round_land.py`: land_passed; consult land refusal production and the callback into the shared hold path.
- `src/taskloop/admit_chain.py`: advance claim and branch checks; consult refusal producers before mapping closed causes.
- `src/taskloop/publish.py`: publication branch fence; consult the branch_moved producer.
- `tests/steps/test_task_event_store.py` (new): typed persistence, invalid payloads, rollback, stable snapshots and retained events; integrates existing factory fixtures.
- `tests/steps/test_hold_store.py`: held, put and hold fences; migrate typed inserts and direct SQL fixtures, assert event/hold atomicity.
- `tests/steps/test_hold.py`: Bench and HoldInsert producers; migrate typed fixtures and verify all decision families retain their cause across retries.
- `tests/steps/test_hold_status.py`: recorded; migrate the typed insert while preserving eligibility and terminal-hold expectations.
- `tests/steps/test_attempt_stop.py`: stop-related hold inserts; preserve stop attribution with typed causes.
- `tests/steps/test_discussion.py`: held restart setup; migrate its HoldInsert without changing linked-answer behaviour.
- `tests/steps/test_round.py`: held fixture; migrate its HoldInsert while retaining round skip behaviour.
- `tests/steps/test_wip_merge.py`: log fixture; migrate its HoldInsert while retaining saved-work behaviour.
- `tests/steps/test_merge_release.py`: terminal merge hold inserts; retain preservation and release fences.
- `tests/steps/test_dash_read.py`: hold producers; migrate known causes and replace the unknown-cause insertion case with validation rejection.
- `tests/steps/test_lost_entry.py`: protect callback; migrate the typed cause while retaining recovery custody checks.
- `tests/cli/test_step_status_cli.py`: hold helper; migrate its insert and preserve text/JSON status projections.
- `tests/steps/test_factory_schema.py`: DDL_DIGESTS and compatibility checks; append the v32 pin and cover the event table and old-schema refusal.
- `.importlinter`: regenerate module coverage and event-store privacy without adding SQLite exceptions.
- `ruff.toml`: the exact event-store SQLite import permission.
- `tools/generate_import_contracts.py`: generate; consult the existing regeneration interface, with no generator behaviour change.
- `docs/design/tl-8bh9.14.145.1/plan.md`: implementation boundaries and acceptance contract.
- `docs/design/tl-8bh9.14.145.1/plan-metadata.json`: preparation commit and consulted paths.

## Read list
- `src/taskloop/factory_schema.py:257-312` — hold DDL and column lists; also target SCHEMA.version when editing.
- `src/taskloop/hold_store.py:20-230` — insert fences, every row loader, retirement and saved-work ownership.
- `src/taskloop/hold.py:93-155` — hold decision, retry and retirement boundaries.
- `src/taskloop/hold_status.py:19-88` — eligible causes, main-moved threshold and permanent holds.
- `src/taskloop/hold_cause.py:18-171` — existing closed cause families, terminal semantics and diagnostics.
- `src/taskloop/attempt_status.py:73-110` — view identity, checks linkage and pending cause.
- `src/taskloop/round.py:309-484` — caller plus advance/publication cause producers.
- `src/taskloop/round_land.py:30-69` — land cause producer and hold callback.
- `src/taskloop/admit_chain.py:245-341` — claim and branch refusal producers.
- `src/taskloop/publish.py:150-180` — publication branch refusal producer.
- `tests/steps/test_hold_store.py:24-169` — typed constructor migration, direct SQL fixtures and fence assertions.
- `tests/steps/test_hold.py:115-595` — Bench and all existing HoldInsert callers, including races.
- `tests/steps/test_hold_status.py:126-137` — recorded hold producer.
- `tests/steps/test_attempt_stop.py:43-112` — both stop-related insert producers.
- `tests/steps/test_discussion.py:183-200` — held restart producer.
- `tests/steps/test_round.py:212-222` — round hold producer.
- `tests/steps/test_wip_merge.py:38-44` — saved-work hold producer.
- `tests/steps/test_merge_release.py:54-103` — all terminal merge insert producers.
- `tests/steps/test_dash_read.py:88-208` — board/detail producers and unknown-reason assumption.
- `tests/steps/test_lost_entry.py:96-117` — recovery-race hold producer.
- `tests/cli/test_step_status_cli.py:204-215` — CLI hold producer.
- `tests/steps/test_factory_schema.py:15-150` — schema pins and read-only incompatibility assertions.
- `.importlinter:598-867` — generated coverage and exact SQLite exceptions.
- `ruff.toml:15-61` — banned APIs and exact store permissions.
- `tools/generate_import_contracts.py:49-90` — contract regeneration interface.

## Contract
TaskEvent is a pydantic model with attempt_id (held agent), cause_id (causal agent/checks attempt), occurred_at and a typed cause. Its stored event_id identifies the snapshot referenced by the hold. Closed variants distinguish agent/check failure, stuck state, exhausted repeat, terminal merge, advance/publication refusal and land refusal; use enums for their reason vocabularies. Structured context retains explanatory values such as deadline or repeat detail. Unknown variants fail validation. One codec projects existing reason spellings; arbitrary explanation text cannot select a cause.

Intent: hold_task chooses a typed cause from its explicit refusal input or the current attempt/check decision facts. Existing semantic reason codes may be decoded at this boundary by the one validated codec; never parse rendered messages or logs. The store receives the typed value, not an unvalidated reason string.

Effect: HoldStore.insert applies the existing label/current-attempt/current-checks/no-existing-hold fences inside its short transaction. Only after they pass, the event store records the validated snapshot and HoldStore records its reference in that same transaction. An exception rolls both back. Event SQL stays inside the event store; transaction-local methods let HoldStore share the transaction without owning event SQL.

Result: HoldRow retains its current consumer-facing identity, time and reason projections, loaded from the referenced event through the owning reader. Keep its constructor shape so presentation consumers and direct HoldRow fixtures need no migration. The hold table owns only hold lifecycle state and its event association. Repeated calls reuse the existing event, stale/concurrent losers append nothing, and retirement never deletes the event. No read reconstructs a recorded cause from later status, execution files or the former reason column.

## Work packages
1. Add TaskEvent models/codec and the event store; change factory_schema.py and hold_store.py together. Remove the old persisted cause representation, retain store fences, refresh import coverage/permissions and append the schema pin. Closes acceptance B and the storage portion of C.
2. Integrate typed cause creation in hold.py and migrate every HoldInsert producer listed above. Exercise agent, checks, repeat, merge, advance/publication and land inputs through the shared decision boundary. Preserve display projections and permanent-hold behaviour. Closes acceptance A.
3. Complete focused snapshot, race, rollback, retirement and incompatible-open tests. Confirm activation retains the existing matching-runtime drain prerequisite; no live drain or database discard belongs to this attempt. Closes C. Run focused tests as needed, then run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
A. Every supported hold decision persists its typed cause and causal attempt/context once; reopening or changing later attempt state cannot change that recorded cause or its displayed reason.
B. A valid hold and its event commit together; stale decisions, losing concurrent inserts and failed writes leave no orphan event, retries reuse the event, and clearing/retirement preserve the recorded cause and existing saved-work/release behaviour.
C. Fresh v32 databases enforce the event/hold association and payload contract; v31 or incomplete databases are refused without alteration, and activation uses the existing drain-before-discard boundary after the schema chain.
