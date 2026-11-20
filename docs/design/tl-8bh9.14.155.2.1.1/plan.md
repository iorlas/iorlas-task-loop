# Depth
Large: durable admission requires a schema version change; retained inputs, atomic reservation and reciprocal candidate exclusion belong to this cohesive admission operation. No owner decision is missing and no dependency is explicitly unlanded. Evidence-gathering budget: 20 model calls total.

## Size
Estimate: 12 changed files, including seven source files, four test/support files and this plan; three independently testable behaviours; 50 model calls for one implement attempt. This fits the limits of 60 files, three behaviours and 100 calls, and stays below the approximately 60-call attempt limit reported in the supplied discussion.

1. Schema compatibility. Acceptance: fresh databases support the durable admission record and its identity constraints; schema 22 is refused before work starts, preserving database bytes, reservations and evidence.
2. Retained inputs. Acceptance: admission reads the exact implement attempt's requirements artifact and captured agent settings after its reservation is released; wrong identities, missing/corrupt artifacts and malformed settings admit no work.
3. Atomic admission and reciprocal exclusion. Acceptance: competing requests for the same checked source retain one operation and one reservation, immutable inputs survive reopening, failed transactions leave neither partial record nor reservation, and candidate/conflict admission cannot both win in either ordering.

## Read list
- `src/taskloop/factory_schema.py:45-88` — compatibility version, operation-table pattern, slot and reservation constraints; add the admission table.
- `src/taskloop/factory_schema.py:295-312` — existing reservation and cross-checks candidate predicates; keep the new exclusion scoped to admission.
- `src/taskloop/attempt_loads.py:78-124` — identity lookup and reservation-dependent loader; add the independent retained-input read here.
- `src/taskloop/attempt_types.py:107-155` — existing key, file reference and admission types; consult without enlarging this already oversized file.
- `src/taskloop/agents/settings.py:103-129` — validated captured harness, model, effort and access settings.
- `src/taskloop/attempt_reads.py:182-206` — short transactions, schema fences and database error boundary.
- `src/taskloop/evidence_files.py:64-81` — owning artifact reader, root containment and digest verification.
- `src/taskloop/admit_rows.py:12-50` — owning reservation write and generation allocation helpers.
- `src/taskloop/admit.py:360-401` — existing free-slot observation and conditional generation/reservation selection; reuse without adding SQL to a use case.
- `src/taskloop/slots.py:19-54` — typed slot observations, probe and Git/file ports.
- `src/taskloop/slots.py:209-243` — reservation-aware free-slot observation, including the post-probe reread.
- `src/taskloop/slot_lock.py:87-96` — existing nonblocking lock probe; availability is not custody or process liveness.
- `src/taskloop/check_admit.py:272-279` — observed free-slot HEAD producer, with no task-branch rule.
- `src/taskloop/land_store.py:49-170` — checked-source fence, candidate producer and atomic insert; expose source eligibility and enforce reciprocal exclusion.
- `src/taskloop/land_check.py:92-146` — both candidate admission callers, with and without a reservation, and existing failure translation.
- `src/taskloop/land_target.py:45-78` — current conflict producer and checked source/target meaning; later execution wiring remains outside this part.
- `src/taskloop/land.py:218-242` — application caller that currently stops on conflict; preserve its dispatch boundary in this part.
- `src/taskloop/merge/models.py:78-114` — later detached execution's pinned inputs and existing execution accounting; avoid duplicating these facts.
- `tests/steps/conftest.py:26-59` — declared database schema and semantic Git/slot fixture setup.
- `tests/steps/conftest.py:121-176` — implement/checks/candidate row producers and file-backed Git fixture integration.
- `tests/steps/doubles.py:92-200` — semantic slot-files and checkout-view ports to compose in the new fixture.
- `tests/steps/test_land_store.py:194-243` — candidate eligibility and exclusion regressions; extend for the new reciprocal fence.
- `tests/steps/test_attempt_store.py:44-51` — ordinary reservation-fenced loading regression to preserve.
- `tests/cli/test_factory_restart.py:20-94` — preceding-version refusal, byte preservation and no scheduling on incompatibility.
- `docs/glossary.md:100-123` — reservation, slot custody, claim, checks and delivery vocabulary; use the supplied definitions for task, attempt, step, session and land.

## Change map
The assigned managed worktree is clean at source commit `6030aa95b581cde45dc72f6f7194a7c1c9fe11c7`. This task has no existing plan or task-specific unfinished commit after that source. The parent plan was read from `task/tl-8bh9.14.155.2.1:docs/design/tl-8bh9.14.155.2.1/plan.md`; this document carries only its durable-admission behaviour. The supplied split explicitly gives this part no dependencies. Part 2 depends on this part, not conversely. The supplied glossary and one targeted glossary read suffice; propose no terminology change.

New source files: `src/taskloop/land_conflict/__init__.py`, `models.py`, `store.py` and `admit.py`. They hold validated admission inputs/results, the owning persistence boundary and the admission use case. Existing source edits are `factory_schema.py`, `attempt_loads.py` and `land_store.py`. Put the retained-input result model beside its owning reader, avoiding growth in `attempt_types.py`. Do not grow the already full `admit.py`; reuse its existing APIs.

New test files: `tests/steps/land_conflict_bench.py`, `test_land_conflict_admit.py` and `test_land_conflict_inputs.py`. Extend `test_land_store.py` for candidate-side exclusion. Existing incompatible-schema tests select `SCHEMA.version - 1` dynamically, so they should cover version 22 without an edit. The plan is the twelfth changed file. Additional reads must be targeted to missed callers or changed source; reassess scope if a new integration proves necessary.

## Implementation
1. Add frozen pydantic v2 models for admission requests, stored records, retained source inputs and typed outcomes. Use existing identity and settings types. Closed outcomes/reasons use stdlib enums with one edge codec and a nonempty explanation for each result. Do not add a step name, scheduler or glossary term.

   Retain the implement attempt's full identity, checked checks identity, repo and tracker task identity, immutable checked commit X and target O, operation key/dispatch token, reserved slot name/path/generation and observed base D, deadline, and original input file reference/digest and captured agent settings. These are admission facts needed by part 2. Keep execution numbers, worker/session facts, merge phases and results in the existing merge slice when that part connects it. Do not invent lifecycle fields or a second execution history in this part.

2. Add a dedicated admission table with referential/uniqueness constraints. Enforce one operation per checked implement source in its repo, so concurrent callers or a rerun of checks for that same source cannot allocate a fresh operation identity. Retain the actual checks identity that authorized its admission. Bump schema 22 to 23 at this source; use the next version if the source has advanced when implementation starts.

   Keep the existing incompatible-runtime refusal. A schema upgrade requires running attempts and old entry processes to drain under matching code before the owner deliberately discards the old database. This task adds no migration, compatibility reader, automatic discard, backup/reconstruction or user-data deletion. Verify the preceding version remains untouched on refusal.

3. Add a narrow retained-input method on `AttemptLoads`, selected by the full implement key and independent of its released reservation. Return only validated identity, source input reference and captured settings, rather than fabricating a live `Admission` or weakening `_load`'s reservation fence. Use the owning artifact reader to validate containment, UTF-8 and digest before admission. Retain the same reference and immutable settings; do not reread the tracker or current machine settings, regenerate requirements, or use an empty fallback. A missing artifact is an explained refusal/unavailability with no new reservation.

4. Implement admission through explicit slot/Git observation, artifact, clock and ID ports. First look up an existing operation for the exact source; return its unchanged record rather than recomputing target, deadline or settings, even if no free slot remains. Reopening the intact database must return that same admission; this is persistence verification, not part 2's process reconciliation.

   For new work, obtain retained inputs and observe free, clean, detached slots and their HEADs outside a write transaction. In one short write transaction, recheck for an existing operation, source identity and eligibility, candidate exclusion, slot identity/path and unreserved generation. The checks must be latest, released, passed and not abandoned; the implement attempt must be current, at X, with its released claim kept. Use owning-store functions for eligibility and reservation writes, with SQL and connections confined to store modules. Insert the operation and reserve the chosen slot atomically. A changed generation or competing reservation cannot be overwritten; a database failure cannot be treated as availability.

   Use the existing reservation/generation helpers, adding no Git, artifact, tracker or process effects inside the write transaction. The operation is the durable intent for later detached execution; this part executes no external write requiring a second acknowledgement transaction. Concurrent requests return the winner if it has the same immutable source identity. Any supplied different target/deadline on repetition leaves the original record unchanged. Different sources cannot share one reservation.

5. Enforce exclusion in both directions within the respective insert transactions. Conflict admission refuses candidates of any checks attempt of the same implement attempt that are delivered, pushable or still hold a reservation. `land_store.insert` must consult the new feature's owning reservation predicate and reject candidate insertion while that source's conflict operation holds its reservation. Cover both reserved and slotless candidate insertion, including no-change delivery; do not rely on a preflight read in `land.py`.

   Expose narrow owning-store helpers for the shared transaction and arrange the dependencies without a circular store import. Preserve existing candidate rules and their explained failure translation. Do not broaden `LANDING` globally to change checks rerun/abandon policy in this part; apply the new exclusion at the admission boundary. Predicate reads must use database records and the actual reservation key/generation, never logs or artifact contents. A failed candidate insert rolls back any reservation it tentatively took.

6. Finish this part with a callable, typed admission operation and durable record ready for part 2. It reserves and retains inputs but starts no setup, merge or agent. Foreground owner acquisition, setup fences, detached execution, matching-effect adoption, execution bounds and drain inventory belong to part 2. Retained refs, saving/releasing conflict work and ordinary land dispatch remain in the subsequent parent work. This part needs no CLI, dashboard, composition-root or task-tracker changes and performs no task-branch update, validation, push or completion.

Keep source files within 400 lines, functions within 80 and tests within 800. Add no `Any`, casts, ignores, subprocess or signal escape, backend display parsing, baseline imports or speculative adapters. Preserve unrelated work and existing claims.

## Validation
Use pytest functions and real SQLite transactions with semantic Git/file ports. Compose a small feature fixture from the current fixture contracts; do not copy an old bootstrap. Test observable admission contracts rather than private helpers.

- Repeated requests, requests with changed target/deadline/settings and file-backed database reopening return one original admission and reservation. Keep distinct-source/task/repo identity cases separate.
- Released source reservations do not prevent exact retained-input reads. Preserve harness/model/effort/access values; reject wrong token/generation/source identity, changed artifact bytes, missing/out-of-root artifacts and malformed settings before allocating a slot. Ordinary live attempt loading keeps its existing fence.
- Use two connections to one file-backed database to exercise competing admissions. Inject a competitor after observation, a generation/path change, no usable slot, and a failure between reservation and record writes. Assert either one complete winner or no changes, including rollback of the generation counter and no orphan reservation. Instrument ports to reject external effects during write transactions.
- Exercise stale/unreleased/failed/abandoned checks, later implement attempts, a lost kept claim, source mismatch and delivered/pushable/reserved candidates, including candidates from earlier checks of the same implement attempt. All return typed outcomes with explanations and no admission side effects.
- Exercise both race orderings with candidate admission, including slotless same-tree/no-change candidates and reserved candidates. Only one side commits; a candidate refusal leaves no extra reservation. A different task remains eligible.
- Run existing incompatible-schema restart contracts: the preceding version is now 22; repeated startup refusal preserves database bytes and evidence and reaches no scheduling port. Fresh-schema operation constraints and current-schema reopening pass the focused admission tests.

After `just install`, run the new admission/input tests and affected land-store, attempt-store and incompatible-restart contracts through the declared successor environment. Any CLI probe uses `uv run --frozen --no-sync python -I -m taskloop ...`. Run the supplied required gates `just check` and `just test`; add no whole-suite/live run beyond these supplied gates. Review the diff, caps and import policies. This planning step changes only this plan and runs no implementation gates.
