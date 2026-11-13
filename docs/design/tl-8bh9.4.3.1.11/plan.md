# Release a slot reservation, and abandon an attempt

Status: **built** for this bounded successor slice. See [the as-built record](#14-as-built-2026-11-10-on-7a66d0dff). The dated proposal and preparation statements below
are historical; they do not describe current availability. Historical `tl plan` commands were superseded by
`tl step`; use the current [README](../../../README.md) and CLI help for command syntax.

Task: tl-8bh9.4.3.1.11 (proposed id). Design proposal, 2026-11-10, against HEAD 7a66d0dff; revision 2 applies the
owner's answers (section 11). Nothing here is built or run; the only commands run were source reads and the policy line
counter (`tests/rules/test_policy.code_lines`) over HEAD. Read: CLAUDE.md, glossary, [.4.3.1](../tl-8bh9.4.3.1/plan.md)
(custody), slices [.2](../tl-8bh9.4.3.1.2/plan.md) to [.10](../tl-8bh9.4.3.1.10/plan.md) (especially .6 section 8, .8
section 8, .9 sections 4-5, .10 sections 2, 3 and 7); source `plan_admit, plan_ops, plan_repeat, plan_store, plan_reads,
plan_schema, plan_prepare, plan_verify, plan_verifier, slots, slot_lock, attempt_entry, plan_launch, composition,
cli_composition, cli_plan`, `.importlinter`, `tests/rules/test_policy.py`; installed process_lock 0.2.1, git_porcelain
0.13.0 (`park`), stream_proc 0.5.0 (`observe_owned`, `group_alive`), beads_client 0.1.0 (`unclaim`).

Words. **Release** here always means releasing a slot reservation (a lease, in the glossary's standard sense), never a
software release. **Abandon** throws an attempt away and gives the task back to the task tracker. The tracker **claim**
is bd's assignment of the task to the actor `taskloop`, kept alive by .9's heartbeat (unchanged). The agent's process is
`worker` in code. Publication, push and merge are out of scope throughout (section 10).

## 1. The dead ends this closes

Today nothing deletes a `reservation` row, and no code unclaims after a committed admission (.2, .6 section 8, .8
section 8). Each of these keeps the slot reserved and the claim held until the whole factory.db is discarded:

| Dead end | After this slice |
|---|---|
| Terminal result (`verified`, `reused`, `rejected:*`, `run:*`, `answer:*`, `incomplete`, `needs_owner`) | released by the step itself when the slot is clean; otherwise `Next: release` once the person tidies |
| `repeats_exhausted` | tidy, then `tl plan verify` (which now releases), or `tl plan release --abandon` |
| `stuck:expired_admitted`, `stuck:unpublished`, `stuck:conflict`, `stuck:entry_lost` | `tl plan release --abandon` when the stop proof holds (section 4) |
| `stuck:hung` (entry alive past its deadline) | the entry holds the slot's lock: `slot_busy` until a person stops it by verified pid; then abandon |
| A used slot left `attached` on its task branch | the release parks it detached at its admission base D |
| A task whose attempt failed or was abandoned | after abandon, `tl plan start` admits a fresh attempt (section 5) |

The whole-DB discard stays documented as the last resort, no longer "the only release".

## 2. When a reservation may be released

Two modes of one operation (owner Q1: decided):

- **settled**: the attempt's result is collected (`plan.collect` says `collected`; for `planned`/`unchanged` that means
  a stored verdict). The slot is parked, the claim **kept**: a verified plan is not task completion (land is), and a
  failed step stays the factory's until someone abandons it.
- **abandon**: any phase, collected or not. The slot is parked, the claim **returned** (fenced unclaim, never forced),
  and the attempt is thrown away: the task can be started again.

Preconditions, all read before anything changes, in this order:

1. The task's current attempt still holds its reservation, or is already released (then the call only finishes what
   is pending: section 6).
2. settled only: collected, else `refused:not_terminal`. A captured attempt with repeatable leftovers is not terminal:
   it is repeated or tidied (`Next: repeat` / `repeats_exhausted` unchanged).
3. **Stop proof** (section 4).
4. **Custody**: the slot's lock taken now (`slot_lock`, `timeout=0`), held to the end of the transaction.
5. **Slot state**, under the lock (section 3). Dirty, on another branch, redirected or unborn: refused and the
   reservation stays (.6 section 8 point 5: release never resets work).

Callers: the attempt entry, after its verify, when the result it read back is collected (it holds the lock already);
`tl plan verify`, after it returns a verdict (new or stored); and the person, `tl plan release`.

## 3. What release does to the slot, the claim and the attempt

**Slot.** Under the lock, on the slot's own hardened view (`composition.checkouts`, no hook), the read is
`plan_verify.observe_slot` (pointer first: `redirected` makes no Git call), then:

| Slot found | Release does |
|---|---|
| on exactly `task/<id>`, clean, nothing staged | `worktree.park(D)`: detached at D; the branch keeps its tip (X, or B for `unchanged`) |
| detached, clean | nothing (never prepared, or parked by an earlier call that died before its transaction) |
| dirty or staged | `refused:slot_dirty` with the `bounded` listing; nothing changed |
| other branch / redirected / unborn / Git unreadable | `refused:slot_branch` / `slot_redirected` / `slot_unborn` / `unavailable:git` |

**Why D, not X.** The next admission of any task uses a free slot's detached HEAD as its D. Parking at X would start an
unrelated task from another task's unmerged plan commit. D is the HEAD admission observed and checked with the branch
rule; it is stored now (`plan_attempt.slot_head`, section 7) because .10 noted that a later switch erases it; a repeat
copies it. A freed slot returns to where it was; moving free slots to the integration target is a later concern.

**Reservation.** Deleted in one write transaction with the release record (section 7), fenced on the attempt id, its
dispatch token, its reservation generation and the `rev` and phase read at proof time. The existing fences do the rest:
`_load` refuses `stale_reservation`, `register_entry`'s join refuses, `admit_repeat` says `not_repeatable`, a stored
verdict is still returned with no Git read, `collect` and the evidence readers still work.

**Generation, monotonic per slot** (required by .2 and .3 before any delete). `slot.generation` is the last generation
issued for that slot. A fresh admission takes `max(generation of the observed-free slots) + 1` before it writes the input
(the key names the evidence directory); in its transaction it takes the lowest still-unheld candidate whose counter is
below that value and sets the counter to it, else `no_free_slot` (claim compensated as today). `admit_repeat` sets the
counter to the new reservation generation in the same transaction.

**Claim.** settled: untouched (`kept`). abandon: after the transaction commits, `unclaim(tracker_root, task_id)` with the
stored root (`plan_attempt.tracker_root`) through `composition.tracker_claims().unclaim` (`if_assignee="taskloop"`, never
`force`): `True` -> `unclaimed`; `False` -> `not_held` (reverted by a reaper, or another actor's), reported, never
forced; `BdError` -> stays `unclaiming`, result `unavailable:tracker` (exit 3), retried by the next `tl plan release`.
This is .6's decided order: durable intent and reservation delete first, unclaim outside the transaction.

**Attempt row.** `plan_attempt` is not updated: phase, result and evidence stay as they were. The ending is the new
`plan_release` row (one owner, `plan_release.py`); it stays as history when the task is started again.

## 4. Stop proof (one rule, shared with repeat)

`plan_release.stop_proof(observe, gone, me, row) -> None | refusal`; `PlanRepeat._stopped` calls it instead of its own
copy. It is exactly two observations (owner Q2):

1. **Entry.** A registered entry, observed by its boot-aware identity (`entry_seen` over `observe_owned`: a native
   process-table read, no spawn or signal, never by name). `matching` -> `refused:entry_running` with its pid, unless it
   is `me` (the entry releasing itself after its own verify). `unknown` -> `unavailable:observe`. `gone` or
   `different_process`, or no registered entry, passes.
2. **Agent.** A registered worker must satisfy `composition.worker_gone` (identity gone or different, and no process left
   in its group; unknown counts as alive), else `unsettled:worker_alive`.

Where this cannot be shown, abandon refuses. That includes phase `dispatching` with no worker registered: the dispatch
write precedes the spawn, so an agent may run with no recorded identity -> `unsettled:worker_unknown`. That one case keeps
the whole-DB discard as its only way out (section 9). `admitted` never started an agent and passes on the entry alone.

The lock is never part of the proof (.4.3.1: a free lock, a dead leader, a result and a clean tree are separate
observations); it is taken after the proof only to exclude every other Git writer while the slot is parked.

**A hung entry** holds the lock: release, verify and repeat all get `slot_busy` (or `entry_running`). The factory does not
stop it and has no stuck detection or supervisor (owner Q4). A person stops it by verified pid, using the existing
`stuck:hung` guide, then abandons.

## 5. Starting a task again after abandon (owner Q3)

Any task can be started again once its current attempt is abandoned. The old attempts and their `plan_release` rows stay
as history; the fresh attempt is admitted by the existing `admit` path, unchanged except for which rows count:

- **Admission.** `_attempted` (before the slots and again under the write lock) refuses `task_attempted` only when the
  task's current attempt is not abandoned. After an abandon, `tl plan start` therefore runs the ordinary first-attempt
  path: task read, slots, branch rule, input, claim (bd's claim is idempotent, so a claim found not held is simply taken
  again), then the rows. A settled release is still the task's answer: `start` returns `already_dispatched`.
- **Numbering.** `number` keeps its meaning, the attempt's position in its step (1..`ATTEMPTS`): the fresh attempt is
  number 1 again with no `previous_attempt_id`, so it gets the full repeat budget, its own chain for the verdict (B1 is
  its own base) and the attempt-1 preparation path (`record.start is None`). The task-wide order moves to a new
  column `seq` (1, 2, 3, ... per task; a repeat takes its previous attempt's `seq + 1`). `UNIQUE(adapter, backlog,
  task_id, number)` becomes `UNIQUE(adapter, backlog, task_id, seq)`; `attempt_of` and `attempts()` order by `seq DESC`.
  `UNIQUE(previous_attempt_id)` and the fenced reservation update still make each chain linear.
- **Display.** `tl plan show` lists earlier attempts newest first as `repeated (<reason>)` or `abandoned`; `tl plan list`
  shows one row per task (its highest `seq`), not one per chain end.
- **Task branch and X: the slice .10 branch rule, unchanged.** Release leaves `task/<id>` at the abandoned attempt's tip
  (X if it committed, otherwise D) and the slot detached. The fresh admission runs `branch_refusal` against the free
  slots' D: the branch is held by no worktree now, and its tip contains D for the slot it was made from, so that slot
  passes and the entry resumes the branch as it is (`take_branch(mode="resume")`). The fresh agent is told to read an
  existing plan first and answer `unchanged` if it still holds, so a plan the abandoned attempt committed is reused or
  rewritten, not lost. **Plain consequence:** "thrown away" applies to the attempt, not to commits already on
  `task/<id>`. To discard those too, the person renames or deletes the branch before starting (the rule's existing
  `branch_diverged` detail says how).
- **Where it meets `branch_diverged`.** Only when no free slot's D is contained in the branch tip (for example, the
  slots were adopted at different commits and the branch's own slot is held), admission refuses `branch_diverged`, as
  it does today for any old branch. That is the existing rule working as designed, not a new conflict; nothing new is
  added for it.

## 6. The operation and its surfaces

`src/taskloop/plan_release.py`, `PlanRelease` (frozen dataclass of ports: a read connection, `connect`/`begin` for the
writer, `checkouts`, `slot_files`, `observe`, `gone`, `hold: Callable[[str, str], AbstractContextManager[None]]`
(cwd, attempt id), `unclaim`, `clock`), one method:

```python
def release(self, key: AttemptKey, abandon: bool, me: Entry | None = None) -> Released | ReleaseRefused | ReleaseUnavailable
@dataclass(frozen=True) class Released:   # exactly what this call changed, nothing else
    slot: str; parked: str | None         # the commit it parked at in this call; None: no Git write
    reservation_removed: bool; claim: Literal["kept", "unclaimed", "not_held"]; abandoned: bool
```

It imports neither `plan_ops` nor `plan_repeat` (`.importlinter`: the entry's closure may not reach `plan_ops`); `plan_ops`
maps its results to `Failed` and `as_data`.

**Flow**: own fenced read (not `PlanStore._load`, which refuses an admitted attempt with no registered entry) -> an
existing release row: finish what is pending (an `unclaiming` claim; or abandon of a settled release: flip `abandoned`,
then unclaim; no Git, no lock) and return -> terminal check -> stop proof -> `hold(cwd)` -> slot read and `park` ->
transaction (re-read: no successor, reservation held at the key's generation, same `rev` and phase, no release row;
insert `plan_release`; delete the reservation; else `changed`) -> lock released -> unclaim when abandoning -> the row's
`claim` updated.

**Consumers, one operation:**

- **Entry** (`attempt_entry._claimed`): after `keeping(alive)` ends, still inside the lock, when the read-back result is
  collected: `release(key, False, me)` with `hold = nullcontext` (as its verifier). The log line gains
  `release=<released|held:<word>|unavailable:<word>|refused:<word>>` last; `plan_ops.ENTRY_WORDS` becomes 7 (`WORD`
  already matches).
- **`tl plan verify`** (`plan_ops.verify_task`): after `Verified`/`Rejected`, settled release with `slot_lock.hold`;
  `Checked` gains `release` (`released`, `held:<word>`, `unavailable:<word>`). A held release does not change verify's
  exit code; the word and `Next: release` tell the person.
- **`tl plan release TASK --backlog B [--abandon]`** (`plan_ops.release_task`): the person's verb, and the one a
  dashboard would call and render through `as_data`.
- **Hard cut:** the placeholders `tl slot release` and `tl plan abandon` are removed with `deferred()` (no aliases).
- **`tl plan start`**: settled release -> `already_dispatched` with its result; abandoned -> admit a fresh attempt
  (section 5). Without this check a released `admitted` attempt would be relaunched into `registration_refused`, and a
  released captured one would reach the repeat's stale read.

**Status and next words** (`plan_ops.next_step`; `AttemptRow` gains `seq`, `held` and the release row through the
`attempts()` query: one `LEFT JOIN`, one `EXISTS`):

| State | `next` | GUIDE |
|---|---|---|
| collected, reservation still held | `release` (new) | "The step ended; its slot is still held. Remove the listed files if any, then `tl plan release`; `--abandon` also gives the task back." |
| released, settled | `done` | unchanged |
| released, abandoned | `start` | "Abandoned: the slot is free and the claim was returned (`Claim:` says if not). `tl plan start` admits a fresh attempt." |
| `stuck:*` | unchanged kinds | each guide ends with `tl plan release --abandon` instead of "discard"; `hung` keeps "stop it by verified pid" first |

`tl plan show` adds `Released: <time>, slot parked at <D>; claim <kept|unclaiming|unclaimed|not_held>[; abandoned]`.
`HELD` and `ATTEMPT_ONLY` drop "nothing here releases them" (`ATTEMPT_ONLY`: "attempt only: no publication").
`discard()` is retitled "Last resort".

## 7. factory.db schema v7 (direct; v6 refused, discarded, no migration)

```sql
CREATE TABLE slot (... , generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0));   -- last issued
-- plan_attempt (ATTEMPT_ADMITTED gains both; a repeat copies slot_head and takes its previous attempt's seq + 1):
 seq INTEGER NOT NULL CHECK(seq >= 1),                              -- the attempt's order among its task's attempts
 slot_head TEXT NOT NULL CHECK(length(slot_head) IN (40,64)),      -- D: the slot's detached HEAD admission chose
 UNIQUE(adapter, backlog, task_id, seq)                             -- replaces UNIQUE(adapter, backlog, task_id, number)
CREATE TABLE plan_release (
 attempt_id TEXT PRIMARY KEY REFERENCES plan_attempt(attempt_id), dispatch_token TEXT NOT NULL, generation INTEGER NOT NULL,
 head TEXT NOT NULL CHECK(length(head) IN (40,64)),                -- where the slot was left (D)
 released_at REAL NOT NULL,
 abandoned INTEGER NOT NULL DEFAULT 0 CHECK(abandoned IN (0,1)),
 claim TEXT NOT NULL CHECK(claim IN ('kept','unclaiming','unclaimed','not_held')),
 CHECK((abandoned = 0) = (claim = 'kept'))
);
```

Writers (`tests/rules/test_policy.WRITERS` gains): `("CREATE TABLE", "plan_release")`: plan_schema.py;
`("INSERT", "plan_release")`, `("UPDATE", "plan_release")`, `("DELETE", "reservation")`: plan_release.py;
`("UPDATE", "slot")`: plan_admit.py. `GIT_WRITES` expected gains `("park", "plan_release.py")`. `RELEASE` joins the
column lists in `plan_schema.py`. Slots left `attached` by v6 attempts are detached by hand before `tl slot adopt`.

**Free rule, lock probe** (deferred by .10 to here). `slot_lock.probe(cwd) -> bool | None` (acquire with `timeout=0`,
role `probe`, release at once; `None` on `OSError`). `slots.observe` takes it as a port: an unreserved, clean, detached
slot whose lock is held is `unknown(locked)`, an unknown probe `unknown(lock_unavailable)`. Admission never reserves a
slot a releaser is still parking. Held slots are never probed, so no entry is refused by a probe.

## 8. Failure and refusal words

Nothing changes on a refusal except where the row says so. Exit codes as `plan_ops.exit_code`: refused 1, unknown 3.

| When | Changed | Result | Next |
|---|---|---|---|
| no attempt | nothing | `refused:absent` | |
| settled, not collected | nothing | `refused:not_terminal` | finish, repeat, or `--abandon` |
| already released, nothing pending | nothing | `already_released` (0) | |
| entry observed running | nothing | `refused:entry_running` + pid | wait, or stop it by verified pid |
| entry observation unknown | nothing | `unavailable:observe` | rerun |
| agent or its group alive, or unknown | nothing | `unsettled:worker_alive` | stop it by verified pid |
| `dispatching`, no worker recorded | nothing | `unsettled:worker_unknown` | whole-DB discard (section 9) |
| lock held / not creatable | nothing | `unavailable:slot_busy` / `unavailable:lock` | rerun / fix `.locks` permissions |
| slot dirty or staged / other branch / redirected / unborn | nothing (stays held) | `refused:slot_dirty` + listing / `slot_branch` / `slot_redirected` / `slot_unborn` | tidy or inspect, rerun |
| Git read or `park` fails | maybe a half checkout | `unavailable:git` | owner inspects, rerun |
| attempt changed after the proof (relaunch, takeover) | possibly parked at D, nothing recorded | `unavailable:changed`, detail says whether it parked | rerun |
| crash after park, before the transaction | detached at D, still reserved | the next call finds it detached and clean: no Git write | rerun |
| store write fails | possibly parked | `unavailable:store` | rerun |
| unclaim raises / says not ours | released; claim `unclaiming` / `not_held` | `unavailable:tracker` / `released` with "check `bd show`" | rerun / owner looks |
| `tl plan start` while an abandon's claim is `unclaiming` | nothing | `refused:release` (show: `Next: release`) | rerun `tl plan release --abandon` |
| repeat's takeover while a release holds the slot (or the reverse) | nothing | repeat `unavailable:slot_busy`; release `slot_busy` | rerun |

An `unavailable:changed` that parked is safe: an admitted attempt's next entry re-takes its branch (`resume`); any other
change refuses at the fence before a Git write.

## 9. Residuals, stated plainly

- `dispatching` with no worker recorded cannot be proven stopped, so it cannot be abandoned; the discard remains its exit.
- A hung entry is a person's to stop; nothing detects it beyond today's `stuck:hung` (deadline passed, entry running).
- Commits an abandoned attempt made stay on `task/<id>` and are resumed by the next start unless the person moves the
  branch (section 5).
- Future idea only, not designed: the dashboard shows the humanized time since the last command started and ended. A
  supervisor is built only after a real stuck case shows the need.
- Since [.4.3.1.13](../tl-8bh9.4.3.1.13/plan.md): an `admitted` attempt whose entry exited before the agent ran (none,
  gone or a different process) is relaunched by each `tl plan next` round until its deadline; `tl plan start` remains
  the manual equivalent. Past the deadline (`stuck:expired_admitted`) rounds only report it; every `stuck:*` and a
  failed result stay a person's.

## 10. Out of scope

Publication, push, fetch, merge, landing and task completion; any tracker write but the fenced `unclaim`; stopping
processes; repeating on `rejected`, `run:*`, `answer:*`; moving free slots to the integration target; slot creation,
deletion or un-adoption; a dashboard; breaking a held kernel lock (process_lock never does).

**Publication delivered by [.4.3.1.12](../tl-8bh9.4.3.1.12/plan.md).** Release stays independent of it: the entry releases first (inside the lock),
then publishes (outside it); a held release does not stop publication, and `tl plan release` never publishes. `Next:
publish` follows a settled release of a verified plan that is not yet on `origin`.

## 11. Owner decisions (2026-11-10)

1. Automatic release when a step's result is final: **yes**, a clean slot is parked, the claim kept; only abandon unclaims.
2. **No descendant concept**: the stop proof is the registered entry identity plus `worker_gone` (unknown counts as
   alive); where that cannot be shown, abandon refuses. The agent library is expected to own its child processes.
3. **Any task can be started again**: an abandoned attempt is thrown away and a fresh attempt is admitted (section 5).
4. **The factory does not stop hung entries or agents** and has no stuck detection or supervisor; the heartbeat stays.

Decided here, open to veto: one verb `tl plan release` with `--abandon` replacing both placeholders; park at the stored
admission base D; dirty slots stay held; the `slot.generation` counter; the `seq` column; the lock probe; `tl plan
verify` releases after a verdict. No owner question is open.

## 12. Code, caps and tests

SLOC by the policy counter today -> estimate; caps 400 file, 80 function, 800 test file.

| Module | Change | SLOC |
|---|---|---|
| `plan_release.py` (new) | `PlanRelease`, `stop_proof`, its reads, park, transaction, unclaim | ~190 |
| `plan_schema.py` | v7: `slot.generation`, `seq`, `slot_head`, `plan_release`, `RELEASE` | 79 -> ~95 |
| `plan_admit.py` | generation counter, `seq`, `slot_head`; `_attempted` ignores an abandoned current attempt | 310 -> ~335 |
| `plan_reads.py` | order by `seq`; `attempts()` gains `seq`, `held`, the release row; `release_of(key)` | 128 -> ~150 |
| `plan_repeat.py` | uses `stop_proof` | 158 -> ~150 |
| `plan_ops.py` | `release_task`, start's release check, `next` words, verify releases, one row per task in `list` | 312 -> ~345 |
| `slot_lock.py`, `slots.py` | roles `release`/`probe`, `probe`; the `locked` reasons | 32 -> ~45, 123 -> ~130 |
| `attempt_entry.py` | release after the step, `release=` word | 189 -> ~205 |
| `composition.py`, `cli_composition.py` | release wiring; release ports for start, verify, release | 233 -> ~250, 101 -> ~120 |
| `cli_plan.py` | `plan release` verb and rendering; placeholders and `deferred` removed | 203 -> ~200 |

No subprocess, no signal, no `Any`/`cast`/ignore. The only new Git write is `park`, in `plan_release.py`, under the lock.

Tests (pytest functions; the port contracts stay their owners'). Factory tests use `FakeRepo`/`FakeWorktree`,
`FakeSlotFiles`, the in-memory SQLite `factory` fixture, scripted `observe`/`gone`, a recording `unclaim`, the `occupy`
lock fixture (a real second flock) and a fake clock.

- **`tests/plan/test_release.py`** (new, ~350 lines, parametrized tables):
  - settled verified on `task/tl-1` at X: parked at D, `task/tl-1` tip still X, reservation gone, `claim=kept`, no
    unclaim; a second call `already_released` with zero Git writes and no lock taken;
  - settled on each non-collected phase -> `not_terminal`, nothing changed (rows, Git spy, lock spy);
  - entry `matching` (not me) / `unknown`, worker or group alive / unknown, `dispatching` without a worker -> the
    section 8 words with zero lock acquisitions and zero Git calls; `matching` equal to `me` passes;
  - abandon `admitted` never registered on a detached slot (no `park`) and on a prepared slot (parked); unclaim once
    with the stored root;
  - `occupy` -> `slot_busy`; dirty, staged, other branch, redirected (zero Git calls), unborn -> refused, still held;
  - a hold that registers a new entry inside (rev bump) -> `changed` with `parked` in the detail, nothing recorded;
  - unclaim `False` -> `not_held`; raises -> `unavailable:tracker`, `unclaiming`; rerun retries once, then no bd call;
  - abandon of a settled release: the flip and one unclaim only;
  - after release: `load` refuses `stale_reservation`, `register_entry` refuses, `admit_repeat` `not_repeatable`, verify
    returns the stored verdict; a new admission takes the freed slot with a higher generation; `occupy` on a
    free-looking slot -> `unknown(locked)`, not admitted.
- **`test_admit.py`**: after an abandon the task is admitted again (number 1, `seq` 2, no previous attempt) and takes
  the existing branch through the rule; a settled release still refuses `task_attempted`; the generation counter rows.
- **`test_entry.py`**: a collected step ends `release=released`, the slot parked; a failed run with leftovers ends
  `release=held:slot_dirty`; `last_entry` accepts seven words.
- **`test_ops.py`**: the new `next` rows; `start` on settled-released (`already_dispatched`, no launch, no repeat) and on
  abandoned (admitted fresh); `list` one row per task; `verify_task` releases after a verdict and reports a held release.
- **`test_plan_cli.py`**: `plan release` result -> exit, human lines (each change on its own line; "nothing changed" on a
  refusal), exact JSON keys; `slot release`/`plan abandon` now exit 2; help text.
- **`test_repeat.py`, `test_slots.py`**: seeds gain `seq`, `slot_head` and the counter (churn, not new cases).
- **Real layer, `tests/plan/real/test_release_real.py`** (new, ~100 lines): real repo, `--detach` slot, adopt, admit,
  `execute` with a `FakeRun` agent, verify and release: the slot is detached at D and clean, `task/tl-1` at X, `observe`
  says free. Second row: abandon, then a fresh admission of the same task resumes `task/tl-1` at X through the real
  branch rule and `take_branch`. Both under a real flock.
- **Rules**: the `WRITERS` and `GIT_WRITES` rows of section 7.

Docs to change with the code: .4.3.1.6 section 8, .4.3.1.10 section 7, .4.3.1.8 section 2 (`number` is per step; task
order is `seq`), the live-smoke runbook (a release and abandon-then-start run, owner-run), the help texts of section 6.

## 13. Not verified

Read, not run: `park` on a real slot from X back to D (an ignored file colliding with a tracked path at D would fail the
checkout: `unavailable:git`); every line count above (estimates).

## 14. As built (2026-11-10, on 7a66d0dff)

Implemented as designed; uncommitted at the time of writing. Gates: `just check` (ruff, pyrefly, import-linter: 5
contracts kept) and `just test` (956 passed; 961 after the review repairs below). Line counts (policy counter, before the repairs): `plan_release.py` 235, `plan_admit.py` 337,
`plan_ops.py` 370, `cli_plan.py` 236, `plan_reads.py` 153, `attempt_entry.py` 202, `composition.py` 240,
`slot_lock.py` 44, `slots.py` 133; `tests/plan/test_release.py` 259. Differences from the sketch above:

- **Result types.** `Released` and `AlreadyReleased` (its own type: nothing changed, exit 0) as sketched; every refusal
  and unknown is one `NotReleased(kind, reason, detail)` with `kind` `refused`, `unavailable` or `unsettled` (the
  `worker_*` words exit 3, as section 8 says), instead of `ReleaseRefused | ReleaseUnavailable`. `detail` says what
  changed ("Nothing changed.", "The slot was parked at <D>; nothing was recorded.", the `bounded` listing). `word(result)`
  is the one word for a log line and a status: `released`, `held:<reason>` (a refused `slot_*` or an `unsettled`
  reason), `refused:<reason>`, `unavailable:<reason>`.
- **Ports.** `PlanRelease(store, checkouts, slot_files, observe, gone, hold, unclaim, clock)`: one `PlanStore` serves
  both the release's own fenced read (its `connect`, no transaction) and the writer (`connect`/`begin`), instead of a
  separate read connection. `hold` is `slot_lock.custody` (role `release`) for the CLI, `nullcontext` for the entry.
- **Stop proof.** `stop_proof` is `entry_stopped` then `worker_stopped`; `PlanRepeat._stopped` calls the two halves
  around its fenced load, so a running entry is still `already_running` and a stale reservation still the winner's
  launch. With no agent recorded only `admitted` passes; a captured attempt always has one.
- **Slot read.** `observe_slot`'s `repo` and `not_listed` give `unavailable:repo` / `unavailable:not_listed` (not in
  section 8's table). The release row's `head` is where the slot was left, always D (see the review repairs).
- **Pending work.** A release row with claim `unclaiming` is retried by any later call, settled or not (and blocks a fresh admission: review repairs below); finishing it
  returns `Released(parked=None, reservation_removed=False, ...)`. A store failure after a successful unclaim leaves
  `unclaiming`; the retry's fenced unclaim then answers `not_held` (reported, never forced).
- **Admission.** The generation is `max(slot.generation of the free names passing the branch rule) + 1`, read before
  the input is written; `_unheld` in the transaction requires `generation < key generation`. `PlanAdmission` takes the
  probe as a required port (composition passes `slot_lock.probe`; repeat-only tests pass a failing stub). `slots`
  splits `Unclean` (the Git words) from `Unknown` (adds `store_unavailable`, `locked`, `lock_unavailable`) and
  `Unadoptable` (adds `store_unavailable`, `other_root`, `inside_checkout`): adoption never says `locked`.
- **Entry.** `enter` gains an `unclaim` port (a settled release never calls it). `release=` is logged only when the
  read-back result is collected; a pending step's line stays as before. `entry_seen` moved from `cli_composition` to
  `composition` (the entry's release observes with it); `Seen` and `Observe` moved from `plan_ops` to `plan_types`.
- **Start, verify, list, show.** `plan_ops._current` answers a settled release with `already_dispatched` and its
  collected reason before any launch or repeat, and treats an abandoned current attempt as none; `tl plan start`
  needs no release port. `verify_task(reader, verifier, releaser, ...)` releases after `Verified` or `Rejected` only;
  a rejection's failure carries `Release: <word>` as its detail. `Next` gains `release`; the abandoned case keeps
  `start` with its own guide (`GUIDE["abandoned"]`). `tl plan show` prints `Released: <epoch seconds>, slot parked at
  <head>; claim <state>[; abandoned]`; JSON gains `seq` and `release` (status) and `release` (verify), and
  `tl plan release` has its own shape (`status`, `slot`, `parked`, `reservation_removed`, `claim`, `abandoned`).
  Guides were added for `not_terminal`, `entry_running`, `worker_unknown`, `slot_dirty`; `tracker` and `changed` are
  not guide keys (`unavailable:tracker` is also an admission word); their detail explains them.
- **Tests.** New: `tests/plan/test_release.py` (22 cases: settled park at D with the branch at X and a second call with
  no Git and no lock; `not_terminal` per phase; the stop-proof table with no lock and no Git; `me`; abandon on a
  detached and on a prepared slot; dirty, staged, other branch, redirected with no Git call, unborn; `slot_busy`; a
  relaunch inside the hold gives `changed` with the park named; unclaim failing, retried, then `already_released`, and
  `not_held`; abandoning a settled release; the fences afterwards and the probe on a freed slot) and
  `tests/plan/real/test_release_real.py` (two rows on real Git under real flock). Additions: `test_admit.py`
  (re-admission after an abandon: number 1, seq 2, generation 2 on the existing branch; a settled release still
  answers; a slot whose counter moved up is skipped), `test_entry.py` (`release=released` and the park on every
  collected line, `release=held:slot_dirty` for a failed run's leftovers), `test_ops.py` (release/done/start, start
  on settled and abandoned, one row per task, verify releasing), `test_slots.py` (`locked`, `lock_unavailable`, held
  slots never probed), `tests/cli` (release rendering, JSON keys, the removed placeholders exit 2, `--abandon` reaches
  the operation). Rules: the `WRITERS` rows (the DELETE key is `DELETE FROM`) and `("park", "plan_release.py")`.
- **Docs.** .4.3.1.6 section 8, .4.3.1.8 section 2 and .4.3.1.10 section 7 carry a note pointing here; the live-smoke
  runbook gains Run E (section 6d, owner-run, not yet run) and the release words in its entry.log row and section 8.

**Review repairs (same day).**

- **An abandon still returning its claim counts as attempted.** Admission's `_attempted` lets a fresh attempt in only
  when the current attempt is abandoned and its claim is `unclaimed` or `not_held`; while it is `unclaiming` (during
  the unclaim, or after a failed one) admission refuses `task_attempted` before any claim, so the abandon's own unclaim
  (or its retry) can never take back a fresh attempt's claim. `tl plan start` refuses `release` with "run
  `tl plan release --abandon` again", and `tl plan show` says `Next: release` with the same guide.
- **Probe race.** `slots.observe` reads the reservation again after a successful probe: a slot reserved meanwhile is
  `held`, never `free`. Accepted residual: a probe that holds the lock in the instant a just-reserved attempt's entry
  takes it makes that entry refuse `slot_busy` (nothing read or written; `tl plan start` relaunches it). The probe
  writes the lock file's holder record only when nobody holds the lock (process_lock 0.2.1 writes after a successful
  `flock`), so a live holder's record is never overwritten; a stale `probe` record stays until the next taker.
- **Repeat versus abandon.** `PlanRepeat` takes the slot's lock (`slot_lock.repeating`, role `repeat`) around
  `admit_repeat` only, released before the launch (the new attempt's entry takes it): a release can no longer park the
  slot under a takeover, and a held lock refuses the repeat `unavailable:slot_busy` with nothing admitted.
- **Detached slot off D.** A clean detached slot whose HEAD is not the stored D (a person moved it while reserved) is
  parked back at D; the release row's `head` is therefore always D.
- **Display.** `Released:` prints a UTC time (`2026-11-10 12:00:00 UTC`). An abandon whose unclaim fails names what
  was already done ("The reservation was removed, the slot parked at <D>." or "no Git write").
- Tests: admission refused during and after a failed unclaim, then admitted once the claim is returned
  (`test_admit.py`); the probe raced by a reservation (`test_slots.py`); a slot moved off D (`test_release.py`);
  `Next: release` and `start` refusing while `unclaiming` (`test_ops.py`); a held lock refusing the takeover
  (`test_repeat.py`). Gates after the repairs: `just check` clean (5 contracts kept), `just test` 961 passed.

**Residuals.** Ignored files survive a release: `park` is a plain `checkout --detach`, never a clean, and the slot read
counts only what `git status` lists, so ignored files (an ignored build output, a `.gitignore`d scratch file) stay in
the freed slot and are visible to the next task's agent. No mechanism is added for it; a person who wants them gone
cleans the slot by hand. An ignored file that collides with a tracked path at D makes `park` fail
(`unavailable:git`).

**Not verified.** Run E (live). `park` on a slot whose ignored file collides with a tracked path at D (would be
`unavailable:git`). macOS lock paths. Two concurrent abandons of one settled release (the flip's `rowcount` refuses the
second as `changed`; not exercised).
