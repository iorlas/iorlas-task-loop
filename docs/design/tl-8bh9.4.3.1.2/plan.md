# Admit one plan attempt (admission only)

Status: **built** for this bounded successor slice. The dated proposal and preparation statements below
are historical; they do not describe current availability. Use the current [README](../../../README.md)
and CLI help for command syntax.

Task: tl-8bh9.4.3.1.2 (proposed id; slice after [.4.3.1.1](../tl-8bh9.4.3.1.1/plan.md)). Design proposal, 2026-11-09,
revised after independent review and owner answers. Not delivered. "Q" = owner decision left open.
Read: CLAUDE.md/AGENTS.md, glossary, .8.7, .4.3.1, .3.2.1, STORE tl-sqd3.26, .9, handoff roadmap, plan*.py, and the
installed any_agent 0.4.0, sqlite_store 0.1.0, git_porcelain 0.13.0, beads_client 0.1.0. Nothing was run.

## 1. The cut

**This slice builds the one producer of admission authority and nothing that runs it.** It writes the held `reservation`
and the `admitted` `plan_attempt` that the existing body (`PlanAttempts.execute/publish/collect`) only consumes. Owner
decision: admission only. The launcher, the entry process, lock custody and credentials are the next slice (section 8).

Consequence, stated plainly: an admitted attempt cannot run. `PlanStore.load` refuses it with `unregistered_entry`
because `entry_pid/start/boot` stay NULL until a registered launcher exists, which is not built here. Nothing reaches the
body from this slice, no CLI command is registered, and no "usable plan" is claimed.

## 2. What is built

| File | Owns | Approx. lines |
|---|---|---|
| `plan_schema.py` (new, split out of `plan_store.py`) | `SCHEMA` (version 2), DDL, and the ONLY column lists for `slot`/`reservation`/`plan_attempt`/`plan_execution` | 75 |
| `slots.py` (new, [.4.3.1.3](../tl-8bh9.4.3.1.3/plan.md)) | `adopt` (only `slot` writer) and `observe` (typed free/held/unknown views) | 100 |
| `plan_admit.py` (new) | `PlanAdmission.admit(...) -> AdmitResult`: the only writer of `reservation` and the `plan_attempt` insert | 120 |
| `plan_store.py` (edit) | imports the column constants instead of its own string lists; version check uses `SCHEMA.version` | -50 |
| `plan_files.py` (edit) | `put_input(key, text) -> FileRef` on the existing `_write` | +6 |
| `composition.py` (edit) | wires `PlanAdmission` with `Bd.claim`/`Bd.unclaim`, the clock and the store | +20 |

`plan_store.py` is 310 lines and `SCHEMA` plus the constants move out of it, so one module (`plan_schema.py`) owns every
column list and neither store module repeats them. Existing imports of `SCHEMA` from `plan_store` are updated (no compat).
No new Protocol: `claim`, `unclaim`, `clock` are plain `Callable` aliases like `Execution`/`Credentials`.
Reused unchanged: the body, `PlanFiles` read/capture/directory, `AttemptKey`, `Admission`, `inspect_task`, `TaskReference`.

## 3. Inputs and who decides them

Explicit: task id, backlog, tracker root, repo checkout (any checkout, for identity), model, effort, sandbox, budget.
Nothing is discovered. The slot is chosen by admission among adopted managed slots ([.4.3.1.3](../tl-8bh9.4.3.1.3/plan.md)); no slot path is an input. The task text is read with `inspect_task` and stored verbatim as the
input file (no prompt template: a prompt contract is the next slice's, with the runner that consumes it).

## 4. Admission sequence

1. `inspect_task` (existing) and the checkout inspection (existing `inspect_repo`, extended per b). Any failure refuses.
2. **Refuse when no slot is free**, before any file write or claim: `slots.observe` ([.4.3.1.3](../tl-8bh9.4.3.1.3/plan.md)) returns typed views; no
   `free` view -> `Refused("no_free_slot", views)`. Free means adopted `slot` row, no reservation, listed non-main
   worktree and `dirty().raw is False`. `RepoInspection` and `tl repo inspect` stay unchanged (owner's Q9).
3. Ids: `attempt_id = uuid4().hex`, `dispatch_token = secrets.token_hex(16)`, `generation = 1`. The key is
   `AttemptKey(attempt_id, token, 1)`.
4. **(a) `put_input(key, text)` first**, under `PlanFiles.directory(key)`; this is the only path scheme (e): the input,
   schema, evidence all hang off the one key-derived directory. Write failure refuses before any external effect. A file
   left behind by a later failure is an inert immutable artifact, never deleted automatically.
5. `claim(task_id)` is `Bd.claim(bead) -> bool` (verified: atomic, idempotent for its own holder, `False` when another
   holds it, other failures raise). `False` -> `Refused("claimed_elsewhere")`, no compensation, nothing to undo.
   `BdError` -> `Unavailable("tracker")`: the claim outcome is unknown, so a compensating `unclaim` is attempted (below).
6. **One `begin_immediate` block** (verified: commits on success, rolls back on any `BaseException`). Inside it:
   re-read `slot`/`reservation` for the observed-free names and take the lowest that still has a slot row and no
   reservation (none left, a race -> `no_free_slot`); `SELECT` for the task in `plan_attempt` -> `task_attempted`; then
   the two INSERTs, the reservation copying `slot.cwd` and naming its columns. Under `BEGIN IMMEDIATE` the reads are authoritative, so the reason is decided by reads, not by
   parsing an error string. **(c)** `sqlite3.IntegrityError` is caught in this block by the admission module itself and
   returned as `Refused("constraint")` after the rollback (it should be unreachable; it proves a schema mismatch). Other
   `sqlite3.Error` -> `Unavailable("store")`. `PlanStore._connection` is not reused: it wraps every `sqlite3.Error` as
   `StoreUnavailable`, which would hide the constraint cases. Admission opens its own connection via the same
   `connect/begin` callables and checks `PRAGMA user_version == SCHEMA.version`.
7. Return `Admitted(key)`. No agent, tracker, Git or file IO inside the transaction.

**Compensation (a).** After step 5 succeeds and before the commit in step 6 completes, every failure (`no_free_slot`,
`task_attempted`, `constraint`, DB unavailable, a store exception) calls
`Bd.unclaim(task_id, if_assignee="taskloop")` (verified signature: `unclaim(bead, *, force=False, if_assignee=None) -> bool`;
the actor string `"taskloop"` is the one `composition.inspect_tracker_task` already builds `Bd` with). `if_assignee` fences it so
it never clears another actor's claim; `force` is never used. `unclaim` returning `False` or raising is reported in the
result (`claim_leaked`) and not retried: the owner sees an explicit leaked claim.

**What leaks if the process dies between claim and commit:** the task stays claimed by `taskloop` with no attempt row, no
reservation, and an orphan input file. Because `Bd.claim` is idempotent for its own holder, a later admission for the same
task re-claims harmlessly; nothing else is stranded. Dying *after* the commit leaves a valid admitted row and the claim
correctly held. The tracker claim and the SQL commit are not atomic, and this slice does not pretend otherwise.

## 5. Schema delta

No new table here (the `slot` table and the `reservation` key `(repo_id, slot)` come from [.4.3.1.3](../tl-8bh9.4.3.1.3/plan.md), same version). In
`plan_attempt` add `UNIQUE(adapter, backlog, task_id)`. **(d) `Schema(version=2)`**, so a factory.db
created by the earlier v1 DDL (which lacks the constraint) is refused loudly by `sqlite_store`, not silently accepted;
no `steps`, no quarantine, no migration (nothing real is stored; CLAUDE.md discards old data). `PlanStore._connection`
currently hardcodes `user_version == (1,)` and must read `SCHEMA.version`; the existing `tests/plan` helper that sets
`user_version=1` is updated the same way.

**One attempt per task, permanently for now (Q4 = yes, owner-decided).** Consequences, not softened:
- A refused, crashed or stuck attempt keeps its `plan_attempt` row and its held `reservation` and **stays unresolved**.
- **Nothing in this slice or the next can resume, retry, release, replace or delete it.** No second admission for that task
  is possible (`task_attempted`), and the slot stays held, until a later *release slice* exists. That slice does not exist
  yet and is not designed here. (Later, [.4.3.1.8](../tl-8bh9.4.3.1.8/plan.md): a captured attempt whose slot has Git
  leftovers is repeated by the step's next attempt, which takes the held reservation over; nothing is released.)
- Only a person editing `factory.db` by hand could free it; that is outside this design and not offered as a path.
- **The tracker claim's lease (found by live smoke 5, checked 2026-11-10 against bd 1.3.1).** `bd update --claim` also
  takes a lease with a 5-minute TTL, kept alive only by `bd heartbeat` (`Bd.heartbeat`); at the time of this note the
  factory never heartbeated, so `bd show` reported `Lease: expires in ...` and then a lapsed lease. Measured in a scratch tracker: after the lease
  lapsed the bead stayed `in_progress`, assigned to the holder, out of `bd ready`; another actor's plain `--claim` was
  still refused ("issue already claimed"), and the holder's `heartbeat` on the lapsed lease succeeded. So the claim is
  NOT freed by expiry alone; it is freed only by `bd reclaim` (a reaper: reverts in_progress beads whose lease lapsed to
  open, clears the assignee) or `bd update --force`, both run by someone else. Wherever a supervisor runs `bd reclaim`
  on the tracker, a taskloop claim whose lease lapsed is reverted while its attempt still holds the slot; the `HELD`
  banner says so. Decided in [.4.3.1.9](../tl-8bh9.4.3.1.9/plan.md): the entry renews the lease every 100 s while a step
  runs; nothing renews it between steps.
Generation is fixed at 1 (Q5 decided: acceptable because the body also fences on `attempt_id` and `dispatch_token`, and
no release exists to reuse a slot). The release slice must introduce monotonic generations before it deletes any reservation.

## 6. What stays out

Launcher, entry process, registration (`register_entry`), `ProcessLock`, credentials, `popen_registered`, self-identity
check, prompt template, worktree preparation (`take_branch`), Git verification and publication, cleanup, reservation
release, scheduler/readiness/hold/dependency policy (tl-8bh9.3.5), CLI registration, claim-uncertainty ledger, retry policy,
task close, slot provisioning. No `process-lock` dependency is added. No subprocess or spawn exists in source or tests.

## 7. Tests, caps, acceptance

New files `tests/plan/test_admit.py` (~180 lines) and a few cases in the existing `test_repo*.py`; `tests/plan/test_attempt.py`
(601 lines) loses its private DDL and gains one import change. Caps 400/80/800 hold. Real SQLite through the same
`SCHEMA.ddl` (existing in-memory helper), real tmp files, injected `claim`, `unclaim`, `clock`. For worktree facts use the
owning `git_porcelain.testing.FakeRepo` (`worktrees`, `worktree(path).dirty()` and `add_worktree` exist; see .4.3.1.3).

**What the tests can and cannot reach.** Admission is not an execution-ready state: it leaves `entry_*` NULL and the body
refuses with `unregistered_entry`. So production admission cannot replace the seeded SQL in `tests/plan/test_attempt.py`
end to end. The honest replacement is partial:
- Test 1 asserts that `admit` produces rows with exactly the columns the body's `load` expects, shows that `PlanStore.load`
  and `PlanAttempts.execute` refuse with `unregistered_entry`/`refused` on them (the intended state), and `collect` reports
  pending `admitted`.
- Test 2 then applies a **test-only** `UPDATE plan_attempt SET entry_pid=?,entry_start=?,entry_boot=?` to the admitted row and
  runs `execute` with released `FakeRun`, proving the produced row is body-compatible. This test-only registration is
  explicitly retained and must be deleted when the next slice supplies the real `register_entry`; it is not a production path
  and is the only seeded-SQL remnant. The other body tests keep their direct seeding until then.

Acceptance:
1. `admit` is the only code that INSERTs `reservation`/`plan_attempt` (`adopt` is the only `slot` writer, [.4.3.1.3](../tl-8bh9.4.3.1.3/plan.md));
   rows match section 5's schema; v1 DB refused; no slot path is an admission input.
2. `put_input` precedes `claim`; `claim` is outside any transaction (a spy asserts no open transaction on the connection).
3. Every failure after a successful claim and before commit calls `unclaim(..., if_assignee="taskloop")` once; a failed
   `unclaim` yields `claim_leaked`, never a retry or `force`.
4. `no_free_slot` is returned before any effect when `observe` finds none, and again under the write lock on a race;
   `task_attempted` is decided under the write lock and distinguished; `IntegrityError` is caught in the
   block; neither failure leaves a partial row.
5. A slot that is not adopted, is held, main, not listed, dirty or unobservable is never reserved.
6. One column-list owner (`plan_schema.py`, including `slot`), grep-checkable; no Git write, no spawn, no CLI command.
7. `just check`, `just test` pass (not run by me: design only).

## 8. Next slice: registered entry (input from the review, not decided here)

Scope for the following design: launcher, `register_entry`, the attempt-entry module, nonreentrant `ProcessLock`, credential
source, and the first real CLI-free run. Recorded review findings as inputs:
- **F1/F2:** admission leaves the row unregistered, so the next slice owns the first path to `execute`; its design must say
  exactly how the test-only registration above is replaced.
- **F4:** `popen_registered(registration_timeout=5.0)` brackets the `registered` callback, and `sqlite_store` busy handling has
  its own 5 s window; the callback's DB write must be bounded below the registration timeout or raise `unavailable`,
  never hang the gate. Decide the relation explicitly.
- **F8/F9/F10/F13:** carried as the reviewer's open findings on entry/lock/credential custody; the reviewer's text is
  authoritative, I only have the identifiers from the coordinator's message and cannot restate them.
- **Q1 (kept):** the entry must check its own identity (`inspect_process(os.getpid())` against the registered row), because the
  dispatch token is in argv and visible to any local process; the registered identity is then what authorizes `execute`.
- Also open there: spawn through `stream_proc.popen_registered` directly versus a thin adapter and its dependency declaration
  (stream-proc is currently only inherited via any-agent); `process-lock` pin; the real `Credentials` source (none exists today);
  entry stderr and survival-proof strategy under the no-spawn rule; the `process-lock` and `popen_registered` fakes.

## 9. Open owner questions

- **Q2.** Answered by the slot-state design [.4.3.1.3](../tl-8bh9.4.3.1.3/plan.md): adopted `s1`-style managed slots, derived paths, provenance row.
- **Q3.** Does `Bd.claim` satisfy tl-8bh9.3.5's atomic initial claim, or must this slice wait for it? (The actor part is answered:
  `"taskloop"`.)
- **Q8.** Source of model, effort, sandbox and budget; required explicit parameters are the proposal, and `deadline` is
  wall-clock, not the handoff's "active minutes".
- **Q9.** Is adding `is_main`/`dirty` to `RepoInspection` (and so to `tl repo inspect` output) acceptable, or should admission
  call `worktrees(with_dirty=True)` itself and leave `repo inspect` untouched?
- Decided here, for owner veto: Q5 (generation 1), Q11 (order: admission, then registered entry, then Git prep/verify/publish,
  then release/cleanup/CLI).

## 10. Not verified

No test, lint or gate ran. The exact bd `claim`/`unclaim`
behavior against a real tracker, and whether `unclaim(if_assignee="taskloop")` matches how `claim` records the assignee were
read from signatures and docstrings only. Line counts are estimates. The reviewer's F8/F9/F10/F13 contents were not available to me.

## Owner decisions recorded (this session)

- Cut: admission only. Q4: one attempt per task; a refused or crashed attempt stays unresolved until a release slice.
- Q2: **implementation is blocked on the slot-state design** (managed `s1`-style slots). No operator-named path as slot identity.
- Q8: admission takes model, effort, sandbox and deadline as explicit required caller arguments; no defaults or config source.
- Q9: admission calls `worktrees(with_dirty=True)` itself; `RepoInspection` and `tl repo inspect --json` stay unchanged.
  (Applied through .4.3.1.3's `observe`: `worktrees()` plus a status read of the managed slot paths only, so the
  person's checkout is not read; `RepoInspection` stays unchanged as decided.)
- Q3 (does `Bd.claim` satisfy tl-8bh9.3.5) remains open.

## As implemented (2026-11-09, after independent review)

These records replace the corresponding rules in sections 4 and 7 where they differ.

- **Read-only order before any effect:** first non-blank model, effort and sandbox (`choices`), then a finite deadline
  (`deadline`: NaN or infinity is refused), then deadline after `clock()` (`expired`). Next the task read (`task`, or
  tracker unavailable) and the checkout (`checkout`, or Git unavailable). Then the store version, then `task_attempted`
  (checked before slots, so re-admitting an attempted task says so even when every slot is held), then `observe`. A
  reservation table that cannot be read is `Unavailable("store")`, never `no_free_slot`. Last comes `no_free_slot`.
- **Input:** `put_input` writes `<directory(key)>/input.txt` with the text `"{title}\n\n{requirements}\n\n{acceptance}\n"`
  from `inspect_task`. This is the task's own prose with no template. A write or encoding failure (`EvidenceError`,
  `UnicodeError`, `OSError`) is `Refused("input")` before the claim.
- **Claim callables:** `Claim` and `Unclaim` are `Callable[[tracker_root, task_id], bool]`, because `Bd` is bound to a
  tracker-root working directory. `composition.tracker_claims` binds `Bd("taskloop").claim` and
  `Bd("taskloop").unclaim(task, if_assignee="taskloop")`, never `force`.
- **Inside the single `begin_immediate`:** `task_attempted` comes first, then the lowest observed-free slot that still
  has a row and no reservation, then both INSERTs. The values are bound by column name to the `plan_schema` lists.
- **Compensation, which replaces "every failure calls unclaim":** `Bd.claim` is idempotent for the actor, so a claim
  may belong to an attempt another admission already committed. After any failure that follows a claim
  (`no_free_slot`, `constraint`, store error, any other exception, or an unknown claim outcome), admission first runs a
  fresh read for a `plan_attempt` of the task:
  - An attempt exists: no unclaim, `claim_leaked=False`. The claim is that attempt's.
  - The read fails: no unclaim, `claim_leaked=True`.
  - No attempt: one fenced `unclaim`. If it returns `False` or raises, the result has `claim_leaked=True`.
  - `task_attempted` never unclaims.
  - A claim `BdError` of kind `missing_binary`, `version`, `not_found` or `lint` means the claim certainly did not
    happen: no unclaim and no leak. Other kinds are an unknown outcome and get the guarded compensation.
  - Any other exception (including `BaseException`) is compensated the same way and then propagates.
- **`IntegrityError`** is caught after the rollback as `Refused("constraint")`. Every constraint is pre-checked under
  the write lock, so reaching it means a schema or check mismatch.
- **Result details** carry `"<ExceptionType>: <message>"`, bounded to 300 characters.
