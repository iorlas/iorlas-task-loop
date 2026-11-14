# Depth
Medium: the supplied task requests two coupled behaviours, durable fenced recovery intent and process/session ownership reconciliation that prevents duplicate execution. No owner decision is missing; part 1 is a dependency but is not explicitly described as unlanded. Evidence budget: 12 model calls total. The schema-version requirement in the task is conditional, so it does not itself trigger large depth. This assessment uses the task text alone.

## Size
Estimated changed files: 20, including this plan, five new recovery slice modules, three new focused test files, nine existing source/test integration files and up to two existing regression test files. Estimated model calls for one implement attempt: 80, including focused verification and repairs. These estimates are within 60 files, three independent behaviours and 100 calls.

Independent behaviours and acceptance:

1. Durable recovery authorization and completion. A current unfinished attempt with an exclusively owned saved session and confirmed stopped prior execution records one recovery intent and continues that session through the existing agent adapter. Acceptance: reopen the same compatible database at each transaction boundary; the same attempt/session is retained, competing callers authorize at most one execution, and a stale recovery callback cannot register or capture over the winner.
2. Reconciliation and explanatory ineligibility. Recovery observes entry and worker identity, reservation, session and task eligibility before acting. Acceptance: matching or unknown processes, missing/conflicting sessions, superseded/released/held work, lost claims and expired execution allowance produce typed outcomes with nonempty explanations and no continuation; a matching already-started recovery is adopted without another launch.

Crash, concurrency, schema and adapter checks below validate these behaviours. They are not separate user behaviours. Part 3 owns scheduling and entry lifecycle integration, deadline renewal policy and the killed-rounds end-to-end scenario.

## Scope and evidence
Use the supplied glossary definitions for task, step, attempt, session, slot, harness, factory and worktree. Recovery and fencing are plain English here; add no glossary terms.

Source commit: `6030aa95b581cde45dc72f6f7194a7c1c9fe11c7`. The slot initially has no changes and no task-specific plan. Recent history includes landed part 1 at `81e5f3a1`; there is no task-specific saved work in the inspected plan history. The parent plan was read from `task/tl-8bh9.14.128` as design context, not as approval for its larger implementation.

Relevant current constraints:

- `AgentLaunch.build(..., resume=...)` now constructs native continuation while ordinary calls allocate a fresh session. Keep harness-specific details there.
- `AttemptStore.dispatch` changes only admitted work. `register_entry` refuses replacement after admission; `register` accepts the first worker only. Recovery cannot work by calling these unchanged against a registered dead worker.
- Attempt records already retain session reference/conflict, full worker identity, entry identity, revision, reservation generation and pinned inputs/settings. Reuse those facts rather than copying their ownership into a second execution history.
- `Attempts._resume` completes an already captured result. Preserve it; it is distinct from continuing an interrupted conversation. `Attempts._call` already owns execution hooks and result capture.
- `worker_gone` requires process identity and an empty group; uncertain observations prevent continuation. A free slot lock alone proves nothing about a worker.
- `factory_schema.py` is version 22 and also versions incompatible interpretation changes. The recovery intent needs durable ownership and registration state that the current columns do not express safely.

## Read list
- `src/taskloop/factory_schema.py:45-121` — schema version, existing attempt/execution fields and placement of recovery DDL.
- `src/taskloop/factory_schema.py:283-340` — current-attempt fences and incompatible-schema refusal contract.
- `src/taskloop/attempt_store.py:64-191` — owning entry, dispatch, worker, session and capture writes to extend with recovery fences.
- `src/taskloop/attempt_loads.py:87-133` — admission reconstruction and reservation/identity validation.
- `src/taskloop/attempt_reads.py:182-222` — connection and short transaction lifetime for owning stores.
- `src/taskloop/attempt_types.py:108-155` — attempt key, admission, replacement proof and current record.
- `src/taskloop/attempt.py:84-145` — ordinary execute and captured-result completion paths to preserve.
- `src/taskloop/attempt.py:175-259` — dispatch, native launch, execution and capture integration to share narrowly.
- `src/taskloop/session.py:14-88` — worker registration and session producers; stale callbacks must be fenced.
- `src/taskloop/agents/launch.py:79-122` — part 1 native continuation adapter and explanatory launch failures.
- `src/taskloop/owned_processes.py:14-54` — identity/group observations and current process identity.
- `src/taskloop/slot_lock.py:39-73` — custody acquisition and nonreentrant lock handling.
- `src/taskloop/drain/store.py:16-104` — drain boundary and durable action authorization pattern.
- `src/taskloop/hold_store.py:105-123` — authoritative hold reads; recovery never clears a hold.
- `src/taskloop/claim_lease.py:20-90` — typed claim renewal/ownership boundary to inject into recovery eligibility.
- `src/taskloop/attempt_entry.py:198-235` — future caller and captured-result handling; no lifecycle wiring in part 2.
- `src/taskloop/round.py:207-255` — future scheduling caller and existing relaunch boundary; wiring remains part 3.
- `src/taskloop/ids.py:1-24` — injected identity generation for recovery fencing.
- `tests/steps/conftest.py:1-65` — installed successor test fixtures and current-schema database setup.
- `tests/steps/test_attempt_store.py:16-100` — real SQLite seed and identity replacement regression conventions.
- `tests/steps/test_restart.py:20-72` — compatible reopen and preservation assertions; existing scheduler behaviour remains valid.
- `tests/steps/test_agent_launch.py:100-206` — native continuation contracts and invalid session handling from part 1.
- `tests/steps/test_drain_fences.py:101-140` — authorization/registration ordering against drain.
- `tests/steps/test_schema_words.py:38-83` — incompatible-version refusal without database modification.
- `tests/rules/test_policy.py:65-144` — explicit SQL ownership registry to extend for the recovery table.

These 25 entries cover existing producers, write owners, future callers and test integration. Locate missed direct callers with targeted searches if implementation changes a signature; do not reopen broad orientation material. New files are described below rather than listed as existing reads.

## Implementation
Create a new `src/taskloop/recovery/` slice: `__init__.py`, `models.py`, `store.py`, `recover.py` and `execution.py`. `recover.py` exposes one application operation; `execution.py` implements its narrow execution port using the existing attempt execution/capture machinery and part 1 adapter. It is a helper, not a second scheduler or a separate policy owner. The operation is directly constructible and testable in part 2; part 3 will compose it into round and entry consumers.

Use pydantic v2 for persisted recovery records and external request/observation models. Use stdlib enums/classes for all new closed vocabularies and one codec per vocabulary. Every outcome includes an explanation; adapters supply backend-specific detail without leaking backend types or commands into the operation's public outcome. Inject clock, identities, claim eligibility, process observation, custody and execution ports. Use no new library, subprocess, signal, log parsing or file-based control state.

### Durable records and ownership
Add one recovery-intent table in `factory_schema.py`; `recovery/store.py` is its only SQL writer. Key the current intent by attempt identity with a monotonically fenced recovery generation and revision. Persist the expected attempt revision, saved session, previous entry/worker identities, recovery owner identity, and authorization/registration/completion state. Preserve prior identities in the intent while handing current execution ownership forward, so a crash cannot erase the evidence needed to reconcile. These are recovery facts, not a second owner for task requirements or the attempt's pinned settings.

Extend `AttemptStore` with recovery-specific conditional writes. Keep attempt/execution SQL there. Atomic authorization must validate currentness, reservation, expected revision, session consistency, absence of captured execution, holds and drain boundary in the same short write transaction that records intent. Store-to-store functions may cooperate within that transaction; SQL and connections remain inside store modules. External tracker/process checks happen outside transactions and their relevant local snapshot is revalidated before committing. Do not implement a read-then-unconditional-write recovery path.

Add the new table and bump the schema version from 22 to 23 (or the next version if the base changes). Follow the existing drain-before-upgrade and discard policy; add no migration, compatibility reader, backup or reconstruction. The recovered records are existing admitted/registered records in a database compatible with the running version, including records created before its first recovery intent. Do not require discarding that compatible database during recovery. A version-22 database remains untouched and receives the normal incompatible-version refusal; deployment must drain old attempts before installing this schema change.

### Operation and execution boundary
1. Read the current attempt and any captured result through owning ports. Captured/terminal work returns an explanatory outcome directing the caller to existing collection, without another agent execution. Reject superseded, released, abandoned or explicitly held work. Validate that the saved session belongs to this attempt and pinned harness/settings; reject conflicting ownership by another current attempt. Do not infer ownership from filenames or transcript text.
2. Observe the previous entry and worker using complete process identities, including boot/start identity and worker group emptiness. Matching or unknown execution prevents a second launch. A changed PID identity is not by itself proof that the old worker group is empty. If registration was incomplete and the world cannot prove absence, retain the unresolved intent and return an explanatory pending outcome.
3. Under slot custody, obtain current typed claim eligibility without reclaiming a task. Re-read/fence all local eligibility and write the intent before any external action. Keep custody through dispatch and completion or explicitly transfer it through an acknowledged ownership boundary. Never reacquire the existing nonreentrant lock from inside an entry that already holds it: the operation accepts an injected custody scope for that future caller.
4. Invoke the execution port outside the write transaction. Prepare native continuation with the saved session, pinned inputs/settings and remaining allowed time. Share existing result capture; expose a narrow public attempt helper if needed instead of calling private methods across slices. Do not repeat worktree preparation, setup, resets or fresh-session allocation. Expired allowance returns an explanation; renewal belongs to part 3.
5. Before the continuation body can run, durably register its owned process against the exact intent generation and recovery owner. Extend the existing registration-hook path rather than adding direct spawn logic. A registration refusal prevents the target body from running. Fence subsequent session and capture callbacks too; an old entry, worker or recovery generation cannot write over the new execution. Preserve attempt/task/step/slot identity, reservation generation, base commit and session reference.
6. Record the observed launch/result in a second short transaction. If the response is lost, re-enter the same operation and ask the process port about the registered identity. Adopt a matching execution, retain unknown ownership, or allow a later fenced continuation only after confirmed absence and no captured result. Do not blindly clear dispatch state or replay a launch because its acknowledgement is missing. A claimant cannot be replaced merely because time elapsed: its owned process must be confirmed gone, and a stale claimant must fail registration after replacement.

The spawn-before-registration interval needs explicit proof in the execution adapter: a child waiting for registration cannot execute the continuation if its owner dies or its registration is rejected. Reuse the owning library's existing registration barrier. If it cannot provide that guarantee for this path, leave the intent unresolved and refuse execution with an explanation; never claim crash safety from an in-memory flag. No new process lifecycle wrapper is authorized without a concrete demonstrated gap.

## Verification and acceptance evidence
Add new focused pytest files `tests/steps/test_recovery.py`, `test_recovery_store.py` and `test_recovery_crashes.py`, with local semantic fakes and current-schema file databases. Avoid importing round/CLI test benches into the new slice's tests. Existing integration points are the database fixture, attempt-store seed pattern, adapter contracts and SQL ownership registry in the Read list.

- Seed unfinished existing attempts without recovery rows. Confirm same session, attempt, slot, pinned settings, base and dirty work survive successful continuation; assert no fresh-session or preparation call occurs.
- Use two independent SQLite connections and a deterministic race barrier. Both callers observe the same dead execution; only one intent generation can register a runnable continuation. Stale callbacks cannot write, and all losers explain why.
- Simulate process death by reconstructing application/store instances after each boundary: before intent commit, after commit before launch, before registration, after registration before acknowledgement, after execution before result acknowledgement, and after result commit. The semantic process port tracks runnable executions, not merely launch-call counts. Assert at most one live execution of the saved session, adoption after lost acknowledgement, and safe continuation only after proven death.
- Exercise alive/unknown entry and worker, reused PID with remaining group, previous boot, competing recovery owner, missing/conflicting or foreign session, stale reservation/revision, successor, hold, release, claim loss, expired allowance, drain and unavailable store. Each outcome has a nonempty explanation and no unauthorized body starts.
- Verify the continued harness reports the same session through callbacks/result capture. A differing reference produces conflict rather than silently replacing the recorded conversation. Preserve ordinary fresh retries and captured-result completion contracts.
- Update `tests/rules/test_policy.py` only for the new table's declared owner. Preserve source/function/test caps of 400/80/800, and no Any/cast/ignore escape. Add schema refusal regression coverage without mutating the incompatible database.

Run the focused recovery and affected contract tests through the declared successor environment, then the required `just check` and `just test` gates. Do not invoke whole-suite/live scenarios or baseline imports. Report actual checks and failures. This planning attempt runs no implementation gates.

## Completion boundary
Part 2 is complete when the application operation, durable intent, process reconciliation, fenced native execution boundary and focused crash/concurrency tests work together with explanatory outcomes. Round/entry activation, execution-allowance renewal and the killed-rounds restart scenario remain acceptance work for part 3, dependent on this operation. Do not claim that this plan or part 2 completes restart lifecycle integration or the task factory.
