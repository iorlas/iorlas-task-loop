# STORE: reconciled retained scope

Status: **design**. Accepted retained STORE scope and exclusions, not a delivery receipt for all listed slices.
Current implemented slices are identified in the [index](../INDEX.md); commands are in the [README](../../../README.md).

Task: tl-sqd3.26. Owner approved the consolidated identity/lifecycle contract and released its design hold for corrected scope on 2026-11-09. The existing parent and ten open children were rewritten; the previously closed cold-singleton child was left unchanged. This is a scope/ownership record, not a second tracker: current status, assignees and dependencies live in tasks.

## Approved authority and exclusions

One local repository binding per canonical Git common directory, with a configured task-backlog scope and one enabled execution binding per backlog within the shared local factory authority. Linked slots provide parallel work. Factory state belongs in the existing per-user factory.db; tasks own work intent and portable discussion, Git owns plans/code, readers own logs/transcripts/artifact bytes. Local slot reservations and repeatable repository setup are settled. Completed checks survive clean slot handoff; interrupted execution requires liveness reconciliation.

Only corrected successor tasks are released. The old sqlite-store-plan.md migration/strangler/import/export/compatibility scope is superseded. No FILEVERB, speculative merge queue, parked review modes or other explicit hold is changed. No automatic lane start, code implementation or release occurred during reconciliation.

## Existing slices and their retained responsibility

| Existing task | Corrected responsibility |
|---|---|
| tl-sqd3.26.1 | STORE 1: authoritative coordinator state and loop controls |
| tl-sqd3.26.2 | STORE 2: explicit waits and cumulative retry progress |
| tl-sqd3.26.3 | STORE 3: revisioned step, actual-attempt and session state |
| tl-sqd3.26.4 | STORE 4: pending execution, publication and land actions |
| tl-sqd3.26.5 | STORE 5: local slot reservations and managed-worktree provenance |
| tl-sqd3.26.6 | STORE 6: current validation and local task-control state |
| tl-sqd3.26.8 | STORE 8: remove superseded state authorities in one hard cut |
| tl-sqd3.26.9 | Git-owned decisions: retire local ADR authority and import paths |
| tl-sqd3.26.10 | STORE asks: remove obsolete ledger after portable discussion adoption |
| tl-sqd3.26.11 | STORE progress: direct typed execution, timing and usage readers |

REPOID tl-sqd3.18 now has acceptance for the same binding contract. Application integration remains in the existing SLOT-STATE, STEP-ATTEMPTS, CHECK-EXECUTION, PORTABLE-ASKS and DASH-STATE tasks; STORE storage slices must not duplicate their workflow implementations.

## Prerequisite boundaries

- Identity precedes local coordinator/reservation storage. Reservation state precedes actual-attempt state; wait/current-validation/read models build on those owners.
- Pending external actions require shared agent admission/recovery and truthful task-service conditional outcomes. The new verified task-port gap is tl-8bh9.6.2; upstream generation/conditional capability remains tl-r2g4.
- Slot lifecycle adoption additionally requires typed liveness and process/permit lifetime verification. Independent Git/SQLite work is not blocked on unrelated agent API changes.
- Portable asks owns question/response behavior; adapter/storage adoption follows, and obsolete ask-ledger deletion comes last. No reciprocal dependency.
- Direct progress writers/readers and dashboard field replacement precede deletion of log-derived/state fallback authority. No retained field disappears merely because its old reader is removed.
- Factory state tests use owning-library fakes and in-memory SQLite for local transitions; actual external mechanisms are verified by library contracts. Existing just check / just test remain source gates.

The explicit prerequisite graph was checked with tl task dep cycles: no cycles were reported. Verification also confirmed all ten open children have corrected acceptance, no obsolete hold/proposed labels remain on them, and the closed child remains closed. No source tests were run because source did not change.

## Definition of unblocked

The owner-decision hold is lifted for the descriptions and acceptance now recorded. A slice with an unsatisfied dependency is still blocked by that dependency. This is intentional, not a continuing blanket STORE hold. Unsupported backend guarantees must be resolved or reported precisely; no silent weakening of the accepted contract.

Table names, opaque key encoding and module layout are implementation decisions within these boundaries. Reuse already implemented SQLite owners after checking current callers; do not perform a second migration of facts already in their correct owner.
