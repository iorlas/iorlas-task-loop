# Depth
Large: the task requires a schema version change; its three scoped behaviours form one cohesive recovery operation. No owner decision is missing and no dependency is explicitly stated to be unlanded. Evidence-gathering budget: 20 model calls total. This assessment uses the supplied task text alone.

## Size
Estimate: 14 changed files, including this plan, five new source files, three new focused test files and five existing integration/test files. Estimate for one implement attempt: 55 model calls, including verification and repairs. Three independently testable behaviours:

1. Versioned durable recovery records. Acceptance: a compatible file database reopens with the exact saved attempt/session, owner and intent revision; an incompatible database is refused without modification.
2. Atomic intent ownership. Acceptance: two independent SQLite connections racing from the same snapshot produce one owner; stale snapshots and replaced owners cannot update that intent, including after reopening the database.
3. Typed eligibility reconciliation. Acceptance: known stopped eligible work obtains an explanatory authorization outcome; live/unknown processes, conflicting sessions, stale or held work, lost/unknown claims, drain and expired allowance obtain explanatory outcomes without changing execution ownership or starting an agent.

Concurrency and reopen scenarios verify these behaviours, rather than adding separate behaviours. The estimate stays within 60 files, three behaviours and 100 model calls.

## Scope and current evidence
Plan only task `tl-8bh9.14.128.2.1`, the first child of `tl-8bh9.14.128.2`. Use the supplied meanings of task, step, attempt, session, slot, harness, factory, plan and worktree. Recovery, ownership and reconciliation use their ordinary engineering meanings; introduce no glossary term.

Source: `6030aa95b581cde45dc72f6f7194a7c1c9fe11c7`. This managed task worktree began clean, with no existing child plan or task-specific WIP commit above the source commit. The parent plan was read from `task/tl-8bh9.14.128.2:docs/design/tl-8bh9.14.128.2/plan.md`; its execution work is outside this child's scope. Native continuation part `tl-8bh9.14.128.1` is already present at `81e5f3a1`.

The current schema is version 22. Attempts already own their pinned settings/input, reservation generation, revision, entry/worker identities and saved session. `AttemptStore.register_entry` only replaces an admitted entry, and `register` retains the first worker. Preserve those contracts here. `Attempts._resume` finishes captured results; it does not continue a conversation. Existing worker stop proof includes process identity and an empty process group; a free slot lock is insufficient. Claims' existing heartbeat renews a lease, so it must not be mistaken for a read-only ownership observation.

This child ends with a directly callable, tested recovery authorization operation. Fenced native continuation, registration barriers, callback fencing, execution adoption, round/entry activation and deadline renewal remain subsequent work. Authorization records are prerequisites for that work, not permission for an existing launch path to bypass its fences.

## Read list
- `src/taskloop/factory_schema.py:45-121` — version 22 and existing attempt/execution facts; add recovery DDL alongside them.
- `src/taskloop/factory_schema.py:280-340` — successor/currentness rules and incompatible-version preservation contract.
- `src/taskloop/attempt_store.py:64-191` — owning writes, revision checks and session/capture producers; add a transaction-local eligibility reader here.
- `src/taskloop/attempt_loads.py:87-181` — reservation-aware reconstruction and captured execution reads used by the owning eligibility helper.
- `src/taskloop/attempt_reads.py:182-266` — short transactions, schema checks, current-attempt and release reads; reuse without enlarging this nearly capped file.
- `src/taskloop/attempt_types.py:107-155` — existing attempt key, admission and identity/revision snapshot; preserve these types.
- `src/taskloop/hold_store.py:102-123` — owning hold reads; expose a transaction-local hold predicate for authorization.
- `src/taskloop/drain/store.py:16-128` — transaction-local drain boundary and conditional owner replacement pattern.
- `src/taskloop/owned_processes.py:14-54` — native worker/group, entry and boot observations for the new observation adapter.
- `src/taskloop/slot_lock.py:39-73` — nonreentrant custody contract; accept caller-held custody through injection.
- `src/taskloop/session.py:22-88` — saved-session producers and reconciliation that may invalidate a previously observed attempt revision.
- `src/taskloop/attempt.py:84-145` — current execute and captured-result completion callers; preserve their behaviour.
- `src/taskloop/attempt_entry.py:198-218` — future entry consumer and existing completion path; no wiring in this child.
- `src/taskloop/round.py:209-255` — future round consumer and current relaunch boundary; no scheduling changes here.
- `src/taskloop/agents/launch.py:84-122` — existing saved-session adapter boundary; do not launch or duplicate its backend validation here.
- `src/taskloop/ids.py:8-24` — injected identities for durable intent ownership.
- `src/taskloop/claim_lease.py:108-117` — renewing claim operation, distinct from the injected eligibility observation.
- `src/taskloop/tracker_client.py:186-196` — backend heartbeat producer; keep tracker commands/types inside its adapter.
- `tests/steps/conftest.py:26-36` — current-schema fixture, without importing the old application/bootstrap.
- `tests/steps/test_attempt_store.py:16-100` — real SQLite attempt/reservation seeding and replacement regressions.
- `tests/steps/test_restart.py:23-72` — compatible reopen preservation contract; keep existing scheduling results valid.
- `tests/steps/test_drain_fences.py:101-140` — authorization/drain race and refusal conventions.
- `tests/steps/test_schema_words.py:38-83` — unchanged incompatible databases and explanatory version refusal; extend coverage here.
- `tests/rules/test_policy.py:65-144` — SQL ownership registry; register only the new table's actual writers.

These 24 existing-file entries cover the implementation's integration points, producers, future callers and focused regressions. New files are identified below. Use additional targeted caller searches only if an existing signature must change.

## Implementation
Create new files `src/taskloop/recovery/__init__.py`, `models.py`, `store.py`, `recover.py` and `observe.py`. Keep the package initializer minimal. `recover.py` owns the application operation; `observe.py` adapts the existing native process observations; `store.py` hides recovery persistence. Public inputs/results and persisted records are typed, with pydantic v2 at record/observation boundaries. All new closed outcomes/reasons are stdlib enums or classes with one edge codec per vocabulary. Every result requires a nonempty explanation; backend-specific explanations come from the observation adapter. Do not leak tracker/harness error types or command names into public outcomes.

### Records and schema
Add one recovery-intent table and bump schema version 22 to 23, or the next version if the implementation base changes. Its current record is keyed by attempt identity and includes a monotonically increasing ownership generation/revision, unique owner token, complete owner process identity, expected attempt revision, saved session, and prior entry/worker identities needed for reconciliation. Retain the association with the pinned harness/settings through the attempt, rather than copying those settings into another authority. Validate loaded records; malformed data returns an explanatory unavailable outcome.

Persist only authorization and ownership facts used by this child. Do not add unused execution-registration/completion states or a second execution history. Retain revision/generation on replacement so an old token never becomes valid again. The recovery store alone reads/writes its table; extend the policy registry for its actual DDL and writes.

The normal version refusal remains unchanged: no migration, old-version reader, backup/restore, reconstruction or file fallback. Drain running attempts and entry processes under matching code before upgrading, then deliberately discard the incompatible database. Recovery itself must preserve an intact compatible database, including unfinished attempts created before any recovery row exists.

### Atomic authorization
Add narrow transaction-local eligibility functions in the owning `attempt_store.py` and `hold_store.py`. Reuse `drain.store.blocked`. The recovery store coordinates these store functions within one short immediate transaction; connections and SQL stay in store modules, with no nested writer transaction and no SQL copied into the operation.

Before inserting or replacing an intent, revalidate the exact attempt key/admission/revision, currentness including a live checks successor, reservation generation, phase, remaining deadline, saved-session consistency and exclusive current session ownership within the pinned harness. Check absence of execution/capture, release/abandon and an explicit hold, and require the drain boundary to remain open. Do not clear a hold or change attempt, reservation, entry, worker, session or execution facts as a side effect of authorization.

World observations occur outside writer transactions and identify the exact snapshot they observed. Commit only if all corresponding local facts still match. Same-owner re-entry with an unchanged snapshot returns the existing intent idempotently. A competitor cannot take ownership from a live or unknown owner. Replacement requires confirmed absence of the exact prior owner, renewed eligibility observations and a conditional write against the previous generation/revision. Elapsed time is never sufficient proof. A loser reloads and returns an explanatory typed outcome.

### Reconciliation operation
Inject clock, identities, owning stores, a typed claim-eligibility observation and slot custody. Accept an injected already-held custody scope for a future entry caller; never reacquire its nonreentrant lock. The standalone caller can supply the existing slot custody API. There is no CLI, dashboard or round composition in this child.

1. Read the attempt, any captured execution and existing intent. Captured work returns an explanatory outcome for existing collection; it does not authorize another agent. Missing, superseded, released, abandoned or held work is ineligible.
2. Require a saved, nonconflicting session owned by this attempt and pinned harness. A session also owned by another current attempt prevents authorization. Use durable structured facts, never transcript filenames or display text.
3. Observe prior entry, worker and any recovery owner through `observe.py` using the owning native APIs. Matching or unknown identity blocks replacement. A reused PID is insufficient while the old worker group remains; previous-boot handling follows the owning process API. Missing/incomplete registration without a proof of absence remains unresolved. Preserve the intent in that case.
4. Under injected custody, obtain current claim eligibility without reclaiming the task. This child accepts the typed observation port and tests it semantically; production tracker wiring belongs to the later consumer. Lost/unknown eligibility, unavailable custody, expired allowance or drain produces an explanation and no authorization. Do not invoke heartbeat as a read, renew the deadline, or perform tracker mutations here.
5. Run the atomic authorization described above and return its typed result. Reopening the same compatible database re-observes the world; it never treats a saved authorization as permanently fresh. Any changed attempt/session/result invalidates that snapshot. An intent owner confirmed gone can be replaced only through the same conditional operation.

There is no launch action in this part, so no external-action outbox is executed or marked complete. The durable intent is the authorization boundary the next part will consume. That execution consumer must revalidate ownership and eligibility and fence registration/callbacks before its body runs; this child does not claim to provide those execution guarantees. Preserve original attempt/task/step/slot identity, base commit, dirty work and native session throughout.

## Verification
Add new pytest files `tests/steps/test_recovery_store.py`, `test_recovery.py` and `test_recovery_observe.py`. Use local semantic fakes and real current-schema SQLite file databases; avoid round/CLI benches in the new slice tests. Existing integration points are the current-schema fixture, attempt seed pattern, policy registry and version-refusal tests above.

- Race two independent connections from the same observed attempt with deterministic barriers and separate connection ownership. Assert one committed owner, no second intent, explanatory losing outcomes and no attempt/execution mutation. Repeat with concurrent replacement of an observed-dead owner and reject the replaced token.
- Close all connections and reconstruct stores before authorization, after its commit, and after owner replacement. Assert rollback before commit, exact persisted data after commit, idempotent same-owner reconciliation, preserved reservation/session/pinned facts and revision fencing after replacement. No runtime object may supply missing recovery state.
- Change revision, session, captured result, successor, release, hold, reservation or drain between observation and commit. Each change prevents authorization in the same transaction. Seed a compatible unfinished attempt with no recovery record and prove it can enter the operation without DB discard.
- Cover alive/unknown entry, worker and owner, reused PID with a nonempty group, prior boot, missing registration proof, missing/conflicting/foreign session, lost/unknown claim, expired deadline, busy custody and unavailable/malformed storage. Every outcome has a nonempty explanation. Native adapters use semantic process fakes, with no source/test spawn, signal or wait escape hatch.
- Assert that all paths leave existing execution/registration state intact and invoke no agent, preparation, fresh-session allocation, tracker mutation or deadline renewal. Keep the ordinary registration and captured-result completion regression contracts.
- Extend incompatible-version assertions to the bumped version and verify the refused database's digest is unchanged. Update only the actual new SQL owners in the policy registry.

Run focused recovery tests and affected attempt-store, restart, drain, schema and policy contracts in the declared successor environment, then the required `just check` and `just test`. Do not run whole-suite/live tests, use baseline imports or introduce a bootstrap. If executing the installed CLI for a focused check, use `just install` followed by `uv run --frozen --no-sync python -I -m taskloop ...`. Enforce 400 source lines/file, 80/function and 800/test file; place new models in the new slice rather than expanding already oversized `attempt_types.py`. Add no Any, cast or ignore escapes.

This planning step runs no implementation gates. Completion means the three scoped acceptance criteria and focused concurrency/reopen checks pass, together with the two required gates. It does not mean session continuation or factory restart lifecycle integration is complete.
