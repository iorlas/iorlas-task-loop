# Managed slots: the smallest slot state admission needs

Task: tl-8bh9.4.3.1.3 (proposed id). Design proposal, 2026-11-09, revised after independent review. Not delivered,
nothing run. Unblocks the [admission slice](../tl-8bh9.4.3.1.2/plan.md), which the owner held on "managed `s1`-style
slots, no operator-named path" (its Q2). Implements STORE 5 (tl-sqd3.26.5) only as far as admission needs:
reservations plus minimal managed-worktree provenance. SLOT-STATE (tl-8bh9.2.1) adoption of the old lifecycle,
PROCESS-BOUNDARY (tl-8bh9.4.4) and LOCK-BOUNDARY (tl-8bh9.4.5) stay where they are. "Q" = owner question.

Read: CLAUDE.md, AGENTS.md, glossary, .8.7, STORE tl-sqd3.26, .4.3.1.1 (and its known limits), .4.3.1.2, .4/plan and
shared-interfaces, .1/identity-store-contract, .2/plan and lifecycle, slot-grant.md, slots-carve.md; source
`plan_store.py`, `plan_types.py`, `repo.py`, `composition.py`, `tests/plan/test_attempt.py`; installed git_porcelain
0.13.0 and sqlite_store 0.1.0; shelf `process-lock-v0.2.1` header (read-only). Baseline slots (731b7c76:
`SlotsConfig.count/dir=".slots"`, tracker slot tasks, setup stamps) were read only so they are not repeated.

## 1. The contract this must meet

- Identity-store contract (.1, lines 38-39) and lifecycle (.2, lines 110-115): after a DB discard, unrecorded worktrees
  need inspection/adoption; ownership is never inferred from a naming convention or an empty DB.
- STORE 5: reservations **and managed-worktree provenance**; one winner per managed worktree; missing or unreadable
  state never proves free; a stale holder cannot release a newer one.

The first draft (slots derived from names alone, no provenance) broke the first rule: a clean worktree at a derived
path counted as a free slot after a discard. It is withdrawn. The design below adds a provenance row.

## 2. What a managed slot is

| Question | Answer |
|---|---|
| Identity | `(RepoId, name)`, name `s1`..`sN`. Not a path, not a tracker task. Two repos may each have `s1`. |
| Location | Derived: `<slots_root>/<repo_id>/<name>`, root resolved once. Outside the person's main checkout (author's choice: no write into their checkout or its `info/exclude`, no collision with old baseline `.slots/` worktrees). |
| Provenance | A `slot(repo_id, name, cwd)` row, written **only** by `adopt`. No row, no slot. After a DB discard there are zero slots until they are adopted again. |
| Root source | An explicit argument of `adopt` only (stop-gap, owner's Q8 rule of no config source). After adoption the stored `cwd` is the fact; admission and display never take a root or path. |
| How many | The number of adopted rows. `adopt(count)` adopts `s1..sN`. Where a default capacity later lives is deferred (Q2). |
| Creation | A person runs `git worktree add --detach <derived path>` (in contract: it is inspection-then-adoption). Whether the factory creates worktrees now is Q3. Preparation (task branch, repo setup) is deferred. |
| Held | A `reservation` row for `(repo_id, slot)`; written only by admission. |
| Free | `slot` row AND no `reservation` row AND Git lists a non-main worktree at `cwd` AND its status is clean. Anything else is `held` or `unknown`. Later the custody lock also gates free (section 7). |

## 3. Facts and where they live

| Fact | Owner |
|---|---|
| Slot exists as a managed slot, its path | factory.db `slot` (adopt is the only writer) |
| Worktree listed, is main, clean | Git via `git_porcelain`, observed per call, never stored |
| Slot held, by which attempt, generation | factory.db `reservation` (admission is the only writer) |
| Working directory given to the attempt | `reservation.cwd`, copied from `slot.cwd` by admission in the same transaction. This is a deliberate copy: the body (`PlanStore._load`) already reads it and the test seed writes it. Moving the join to `slot` would change the body and the seed; it is cheaper to keep the copy, which cannot drift because no code updates either row. |

## 4. Schema delta (all DDL in `plan_schema.py`, per .4.3.1.2)

```sql
CREATE TABLE slot (
 repo_id TEXT NOT NULL, name TEXT NOT NULL, cwd TEXT NOT NULL,
 PRIMARY KEY (repo_id, name)
);
CREATE TABLE reservation (
 slot TEXT NOT NULL, repo_id TEXT NOT NULL, cwd TEXT NOT NULL,
 generation INTEGER NOT NULL, attempt_id TEXT NOT NULL UNIQUE,
 PRIMARY KEY (repo_id, slot)
);
```

- Reservation column order is unchanged (`slot, repo_id, cwd, generation, attempt_id`); only the key moves to a
  table-level `(repo_id, slot)`, since `s1` of two repos must not collide. Production inserts name their columns;
  the positional seed at `tests/plan/test_attempt.py:53` stays valid.
- The earlier `cwd UNIQUE` is dropped: its stated reason was wrong. Paths embed `repo_id` and name, so two keys cannot
  share a path, and two roots for the same name are already stopped by the primary key.
- No foreign key from `reservation` to `slot` or from `plan_attempt`: the helper runs `PRAGMA foreign_keys=ON`, so a
  key would force the seed to add a `slot` row, and tests delete reservations to model a release (`:340`, `:533`).
  Admission checks the `slot` row under its write lock instead.
- `Schema(version=2)`, shared with admission's `UNIQUE(adapter, backlog, task_id)` since both land together (Q6 decided).
  Checked in sqlite_store 0.1.0: `_open` re-raises `SchemaError` ("missing upgrade step") for a v1 file; it is a
  `sqlite3.DatabaseError`, so `PlanStore._connection` reports `StoreUnavailable`. No migration (CLAUDE.md).
- `plan_store.py` reads change in two places: the `cwd` subquery and the fence `SELECT` gain `repo_id=p.repo_id` /
  `repo_id=?`. `_connection` checks `SCHEMA.version` instead of the hardcoded `(1,)`.

Release (deferred) needs a further schema change, recorded now: `attempt_id NOT NULL UNIQUE` cannot keep a row with
no holder, so release either makes the holder nullable or moves the generation counter onto `slot` and deletes the
reservation. Either way generation stays monotonic per slot; until then it is fixed at 1 (owner's Q5).

## 5. Module `src/taskloop/slots.py` (new, about 100 lines, functions under 30)

```python
@dataclass(frozen=True)
class SlotView:          # built only by observe(); callers cannot supply a path
    name: str
    path: Path           # from slot.cwd
    state: Literal["free", "held", "unknown"]
    reason: str | None   # unknown: not_listed | main | dirty | git_unavailable | store_unavailable
    attempt_id: str | None

def slot_names(count: int) -> tuple[str, ...]                                       # s1..sN; count < 1 refuses
def adopt(connect, begin, repo: Repo, root: Path, count: int) -> tuple[Adopted | Refused, ...]
def observe(con: sqlite3.Connection, repo: Repo, repo_id: RepoId) -> tuple[SlotView, ...]
```

- **adopt** (the only `slot` writer): for each name not yet adopted, derive `root.resolve()/repo_id/name`, require
  that `repo.worktrees()` lists it with `is_main=False` and that `repo.worktree(path).dirty().raw` is `False`; then,
  in one short `begin_immediate`, insert `(repo_id, name, str(path))` if absent. Git reads happen before the
  transaction. Idempotent; a name that fails is reported with its reason and not adopted. A slot is never
  re-adopted while a row exists, so `cwd` never changes under a reservation.
  As implemented: a stored row under another root is reported as `other_root` (never moved), a root inside the main
  checkout is refused as `inside_checkout`, and no write lock is taken when nothing is pending.
- **observe**: read `slot` and `reservation` rows for the repo (one read connection), then `repo.worktrees()` once
  (without `with_dirty`), then `repo.worktree(cwd).dirty().raw` only for adopted, unheld, listed, non-main slots.
  `with_dirty=True` is not used: it runs a status read on every worktree of the repo, including the person's main
  checkout and unrelated linked worktrees. A reservation row -> `held` (Git not consulted). `GitUnavailable` on
  the list or on one status read -> `unknown(git_unavailable)` for the affected unheld slots. DB unavailable ->
  every slot unknown, because then the slot rows themselves are unknown and nothing is shown as free.
- Reservation is **not** written here. Admission (`plan_admit.py`, .4.3.1.2) is the only inserter of `reservation`
  and `plan_attempt`. It uses `observe` before any effect, and re-checks inside its transaction (section 6).
- Display: `SlotView` is the typed result. Its first consumer is admission's `no_free_slot` refusal; a read-only
  `tl slot list` and the dashboard are deferred (Q6 decided).
- Locked worktrees: `WorktreeInfo` has no lock field (fields: path, head, branch, is_main, dirty) and
  `real_parse.parse_worktrees` drops the `locked` record, so this slice cannot show a locked slot as unknown. A
  `git worktree lock` only stops prune/move/remove, which this slice never does; provisioning/cleanup must
  revisit it.

## 6. Admission changes (applied to .4.3.1.2 in the same revision)

Inputs: the repo checkout (any checkout, for `identity()`) replaces the slot checkout path; no root, no count.
Before `put_input` and `Bd.claim`: `observe`; no `free` view -> `Refused("no_free_slot", views)` with no effect.
Inside its single `begin_immediate`: re-read `slot` and `reservation` for the observed-free names and insert the
reservation for the lowest name that still has a slot row and no reservation (Q5 decided), copying `slot.cwd`; none
left (a race) -> `Refused("no_free_slot")` and the claim compensation. No Git IO in the transaction: the clean status
is from `observe`, and between observe and commit only a factory holder may write to a managed slot; this window is
accepted and noted in .4.3.1.2.

## 7. Library calls (verified against installed source)

- `git_porcelain.RealRepo(path, memoize=False)`; `Repo.identity() -> RepoIdentity(root, common_dir, origin_url, key)`.
- `Repo.worktrees(*, with_dirty=False) -> tuple[WorktreeInfo, ...]`, main first. Real: git's literal
  `worktree list --porcelain -z` paths (not resolved by the library); malformed output raises `GitUnavailable`.
- `Repo.worktree(path) -> Worktree`; `Worktree.dirty(base=None, *, ignored_under=()) -> Dirty`; `Dirty.raw` =
  tracked or untracked changes. Real: one `status --porcelain=v2` in that worktree.
- `git_porcelain.testing.FakeRepo` implements `worktrees`, `worktree(path)`, `FakeWorktree.dirty`, `add_worktree`.
- `sqlite_store.Store(SCHEMA).shared_rw(path)`, `Store.begin_immediate(con)` (commit on success, rollback on any
  `BaseException`), `Schema(version, ddl, steps, name)`.
- Not used here: `add_worktree`/`drop_worktree` (Q3, cleanup), `any_lease` (resource permits, not slots; its source was
  not read). `process_lock.ProcessLock(reentrant=False)`: the tl-8bh9.4.5 note plans that the attempt entry holds it
  on the worktree from preparation to cleanup. When that lands, a held kernel lock will also make a slot not free,
  while a free lock still won't authorize reuse on its own (the same note; lifecycle step 4). The review cited glossary
  lines 20-21 for this; those lines define attempt and session, so the reference here is the bead note instead.

## 8. Explicitly deferred

Factory creation of worktrees (unless Q3 says now), preparation, release and generation reuse, cleanup/deletion and
un-adoption, the custody lock and surviving-worker reconciliation, a capacity default or config home (tl-bxk.14),
CLI (`tl slot adopt`, `tl slot list`) and dashboard, retiring old tracker slot tasks (tl-8bh9.2.1). Until a CLI exists,
`adopt` and admission are reachable only through `composition.py`, like the existing plan body. No subprocess, no
Git write, no new dependency.

## 9. Tests (successor `tests/plan`, pytest functions, no spawn)

`tests/plan/test_slots.py`, about 170 lines: `FakeRepo.clone` from a `FakeRemote` with one commit (as
`tests/cli/test_repo.py` does), `add_worktree` at derived paths, in-memory SQLite through `SCHEMA.ddl`. Parametrized:

1. `adopt`: listed clean linked worktree adopted; not listed, main, dirty, `GitUnavailable` refused with reasons;
   re-running is idempotent; a worktree at a non-derived path is never adopted.
2. `observe`: no `slot` row -> no view even for a clean worktree at the derived path (the discard rule); free;
   held wins over dirty or missing; dirty, not listed, `GitUnavailable` -> unknown; DB unavailable -> all unknown.
3. Admission side (in `test_admit.py` of .4.3.1.2): `no_free_slot` before any file write or claim (spies); a
   reservation inserted between observe and commit -> next free name or `no_free_slot`; two repos both get `s1`;
   the produced reservation passes `PlanStore.load`'s fence; another repo's `s1` does not.
4. v1 database -> `StoreUnavailable`.

Churn in `tests/plan/test_attempt.py` (601 lines): `:46` `user_version=1` -> `SCHEMA.version`; `:143` `user_version=2`
-> `SCHEMA.version + 1`; the import of `SCHEMA` follows its move to `plan_schema.py`. The seed `:53`, `UPDATE reservation`
at `:133`/`:330` and `DELETE FROM reservation` at `:340`/`:533` are unaffected (column order kept, no foreign key).
Sizes: `plan_schema.py` about 75 (adds `slot`), `plan_store.py` 310 -> about 262 after the split, `slots.py` about 100.
All under 400/80/800; these are estimates.

## 10. Acceptance

1. A slot exists only as a `slot` row written by `adopt` after Git lists a clean non-main worktree at the derived path;
   an empty DB has no slots.
2. No caller of admission or `observe` supplies a slot path; `SlotView` is produced only by `observe`.
3. `free` requires slot row, no reservation, listed non-main and `dirty().raw is False`; store or Git failure never
   yields `free`.
4. `plan_schema.py` owns all DDL and column lists; `adopt` is the only `slot` writer, admission the only `reservation`
   writer; reservation keyed `(repo_id, slot)` with the old column order; schema v2; v1 refused.
5. Body unchanged except the two `repo_id` conditions and the version check; existing body tests pass.
6. `just check` and `just test` pass (not run: design only).

## 11. Owner questions

- **Q3 Does the factory create slot worktrees now?** (a) No: a person runs `git worktree add --detach <derived path>`
  and then `adopt` (proposed; matches the deferral). (b) Yes: `adopt` creates a missing one with
  `Repo.add_worktree(path, rev)` at the integration target (about 20 lines, a Git write outside any transaction,
  no setup).
- **Q2 Capacity home (deferred, no change now):** machine config (lifecycle.md) or repo profile (glossary, old
  `slots.count`, tl-bxk.14)? The documents disagree; capacity today is the number of adopted slots.
- Still open from .4.3.1.2: its Q3 (`Bd.claim` versus tl-8bh9.3.5).

Decided by the coordinator's review (author or contract, open to owner veto): root outside the checkout as an adopt
argument (Q1); provenance required after discard (Q4, closed by the contract); lowest free name (Q5); land with
admission, no `tl slot list` yet (Q6).

## 12. Not verified

Nothing was run. Whether real git on macOS reports worktree paths as `realpath` (`/private/...`) was read from
source, not observed; `adopt` compares the resolved derived path with the listed path and refuses a mismatch as
`not_listed`. `FakeWorktree.dirty` was found by name, not exercised. Line counts are estimates.
