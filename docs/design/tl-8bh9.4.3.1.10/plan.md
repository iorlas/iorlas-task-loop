# Slot preparation under a custody lock: the task branch and the attempt-lifetime ProcessLock

Task: tl-8bh9.4.3.1.10 (proposed id). Design proposal, 2026-11-10, against HEAD ca9806ab7, revised after an independent
review. Its findings were checked in the committed source (`git show HEAD:`), and the owner's decision on Q1 is applied.
Nothing was implemented. The only commands run were read-only source reads, one `git ls-remote` and one
`uv lock --dry-run` on a scratch copy (section 8). The claim heartbeat is designed in [.9](../tl-8bh9.4.3.1.9/plan.md).

Read: CLAUDE.md, AGENTS.md, glossary; [.4.3.1](../tl-8bh9.4.3.1/plan.md) (custody), [delivery](../tl-8bh9.9/delivery-publication.md);
`bd show tl-8bh9.4.5`; slices .3 (slots), .4 (entry, O4), .5/.7/.8 (verify, factory commit, repeat). Source:
`attempt_entry, plan, plan_admit, plan_commit, plan_verify, plan_verifier, plan_repeat, plan_launch, plan_ops, slots,
composition, cli_composition, cli_plan`, `tests/plan`, `tests/cli`, `tests/rules`, `.importlinter`, `ruff.toml`.
Installed git_porcelain 0.13.0 (`take_branch`, `refs`, `is_ancestor`, `worktrees`, `FakeWorktree.take_branch`). The
shelf `process-lock-v0.2.1` `__init__.py` was read with `git show`.

## 1. What changes

Today an admitted attempt runs on the slot's detached HEAD and the factory commits there; nothing excludes a second
writer. This slice changes four things. No schema changes, no network, no release.

- **Lock.** The entry takes a per-slot `ProcessLock(reentrant=False, timeout=0)` after its identity check. That one
  handle wraps the entry's whole body: preparation, the agent run, the publish retries, the factory commit, the
  clean-tree check and the verdict.
- **Task branch.** Preparation moves the slot onto `task/<task-id>` (`take_branch(mode="resume")`) before B is read.
- **Branch pre-check at admission.** Admission runs a read-only check of the branch's name, holders and history before
  anything is held, so the common refusals happen before the slot and the claim are taken.
- **Other writers.** `tl plan verify`, and the verify inside a repeating `tl plan start`, take the same lock with
  `timeout=0` around their Git writes and report `slot_busy` instead of racing.

## 2. The lock (decided)

| Question | Decision and reason |
|---|---|
| Scope | One lock per managed slot, `(RepoId, slot name)`. The guarded resource is the worktree, not the task or the attempt. |
| Path | `lock_path(cwd) = Path(cwd).parent / ".locks" / f"{Path(cwd).name}.lock"`, i.e. `<slots_root>/<repo_id>/.locks/s1.lock`, from the stored `reservation.cwd` (.3: the adopted path is the fact; nothing re-derives it from config). It is outside the slot, where the agent's sandbox cannot write. `adopt` names only `s1..sN`, so `.locks` never collides with a slot. |
| Not the artifacts dir, not beside factory.db | `tl plan verify` gets only `--db`. Two factory.db files that adopted the same worktree must still exclude each other. |
| Never unlinked | No code deletes the file or folder; the library creates them (`mkdir(parents=True)`, file mode 0600). If a person deletes the file while it is held, exclusion is lost (new inode): documented, not detected. |
| Who takes it | `attempt_entry.enter`, after the identity check and one fenced `store.load(key)` (for `cwd`), before `execute`: before any Git read of the slot. In a repeat, the new attempt's own entry. The coordinator and the launcher never hold it; there is no handoff. |
| How long | `slot_lock.acquire` then `try/finally: release` around the entry's whole remaining body. The fd is non-inheritable (PEP 446), so the agent never holds it. |
| Wait | `timeout=0` for every taker. Each contender is a one-shot command or an entry that `tl plan start` relaunches; a bounded wait would add polling sleeps for no case that a rerun does not cover. |
| Busy | `LockHeldError` maps to `SlotBusy`. The entry logs `refused slot_busy`, exits 1, and the attempt stays `admitted` with nothing read or written. Verify returns `VerifyUnavailable("slot_busy")` (exit 3). If the lock file cannot be created (`OSError`): `refused lock` / `unavailable:lock`. |
| Holder record | `label="taskloop-slot"`, `meta={"attempt": <id>, "role": "entry" or "verify"}`; the library adds pid and time. No path, argv, env or secret. It is informational only: `tl plan verify` may print it as detail, and nothing decides on it. |

**Shape (smallest).** `src/taskloop/slot_lock.py` is the only importer of `process_lock` (about 50 lines): `lock_path`,
`SlotBusy`, `SlotLockUnavailable`, `acquire(cwd, attempt_id, role) -> ProcessLock`, and `hold(admission)`, a context
manager that acquires and releases. `PlanAttempts` is unchanged: the entry holds the lock around everything it calls.
`PlanVerifier` takes one new constructor argument, `hold: Callable[[Admission], AbstractContextManager[None]]`, used only
around `_settle` (the commit through the verdict). A stored verdict, the `applicable` refusals, `leftovers` and `staged`
take no lock, because they write no Git. The three builders:

- **Entry:** `contextlib.nullcontext` (the entry already holds the lock; the library's nonreentrant registry would refuse
  a second acquire).
- **`open_plan_verifier`** (`tl plan verify` and the repeat's verify of C): `slot_lock.hold`.
- **`cli_composition.py:81`** (the read-only verifier behind `plan show`'s leftovers): a `refused` hold that raises
  `SlotBusy`. That verifier never calls `verify`; if it ever did, it would fail closed.

**Not stop proof** (.4.3.1, tl-8bh9.4.5). When the entry dies the kernel frees the lock while its agent may still run.
`quiet()`'s `worker_gone` gate before each Git write and the repeat's stop proof stay as they are: a free lock plus a
live worker is still `unsettled:worker_alive`.

**Ordering.** Lock first, then DB transactions. Nobody waits on the lock while holding a write transaction, and
`timeout=0` cannot deadlock. A repeating start releases the lock when `verify(C)` returns, before `admit_repeat`.
That leaves the existing window (L5): another `verify(C)` can take the lock and commit X before the takeover. The window
is closed by what already exists: `admit_repeat` re-reads under its write lock and refuses `not_repeatable` once a
`plan_verification` row exists; after the takeover a verify of C is `superseded` by the fence; and N's dispatch requires
HEAD == E (.8).

**Free rule (O4 of .4.3.1.4): the lock probe is deferred (owner accepted).** Reservations are never released, and a
used slot sits on its task branch, which `slots._clean` already reports as `attached`. The probe joins the release slice.

**Hook for .9.** The claim keep-alive starts and stops inside the entry's lock `try/finally`, with the lock outermost.

## 3. Preparation

`task_branch(task_id) = f"task/{task_id}"` (the glossary's derivation; never stored). The old factory used the same
`task/<bead>` names, and this checkout has 5 local `task/*` branches, 25 `origin/task/*` refs, and `task/tl-wl9u`
checked out in another worktree. Those cases are why the checks exist.

**The one branch rule** (`plan_prepare.branch_refusal(repo, task_id, heads)`, pure plus read-only Git; used by both
admission and the entry). `heads` is the base or bases D the attempt could start from. The checks, in order:

1. **Name** (pure, no Git): the task id must match `[A-Za-z0-9._-]+`. That excludes control characters, space,
   `~^:?*[\` and `/`. Also no leading `.` or `-`, no `..`, no trailing `.`, no `.lock` suffix. Otherwise `branch_name`.
2. **Refs**, one `repo.refs(["refs/heads/task", "refs/remotes/origin/task/"])` read, with exact names filtered in our
   code: `refs/heads/task` exists, or any `refs/heads/task/<id>/...` exists (a directory/file conflict) ->
   `branch_name`. Another local `task/*` whose name casefolds equal to ours but differs (it collides on macOS) ->
   `branch_name`.
3. **Holders:** `repo.worktrees()` lists another worktree whose branch is `task/<id>` -> `branch_held`.
4. **History:** for each of the local `task/<id>` tip and a locally present `refs/remotes/origin/task/<id>` tip:
   `repo.is_ancestor(D, tip)` false -> `branch_diverged` (Q1 decided: refuse; resuming a branch that contains D is
   accepted). No fetch: local refs only. The refusal's detail tells the person to rename or delete the old branch
   (`git branch -m task/<id> old/task/<id>`) or move the remote-tracking ref aside. `MissingRevision`/`GitReadFailure`
   -> `GitUnavailable`, never "absent".

To keep `PLR0911` (6 returns) and C90 (12) satisfied, the rule is an ordered tuple of `(check, word)` steps folded by
one loop, and the entry's flow is three functions (`_state_refusal`, `branch_refusal`, `_take`), each with at most four
returns.

**At admission (H1).** In `plan_admit.admit`, after `_observe` and before `put_input`, the claim and the reservation:
read `repo.worktrees()` once for the observed free slots' HEADs, run `branch_refusal` with those heads, and keep only
the free names whose D passes. If none pass: `AdmitRefused` with the rule's word. Nothing is written and nothing is
claimed. `plan_admit.py` grows from 363 to about 375 lines; the rule itself lives in `plan_prepare.py`. Its refusal
words join `Refusal`: `branch_name`, `branch_held`, `branch_diverged`.

**At the entry (authoritative).** Inside `_start`, after the launch spec and before the base read; `plan_prepare.py`
also takes over `plan.py`'s `_base`/`_problem`, so `plan.py` shrinks from 375 to about 345 lines. Preparation runs only
for an `admitted` attempt:

1. `observe_slot`, with the pointer check first (no Git call on `redirected` -> `slot_redirected`). Unborn -> `slot_unborn`.
2. Already on `task/<id>` -> no Git write (a crash after step 4, or a repeat's slot). Go to the base check. L2: no
   history check here. Admission refuses a slot that a person switched onto a branch before admission (`attached` is
   not free). A switch made after admission erases D, which only a stored D (a schema change) could recover. A person
   who switches a reserved slot onto the task branch has chosen that base.
3. On any other branch -> `slot_branch`. Detached in a repeat -> `slot_detached`. Detached and dirty -> `slot_dirty`.
4. Detached and clean, attempt 1: `branch_refusal(..., heads=(D,))` again, then the pointer re-check, then
   `take_branch("task/<id>", base, mode="resume")` on the slot's own hardened view (no `post-checkout` hook).
   `base` is the remote-tracking tip when no local branch exists and the tip contains D (that is delivery's "fetch the
   task branch, read its plan"); otherwise D. An existing local branch is checked out as it is. `BranchHeld` ->
   `branch_held`.
5. Base check, as today but branch-aware: born; on `task/<id>`; clean for attempt 1, or at E with nothing staged for a
   repeat. B = HEAD, re-checked against the deadline and recorded by the dispatch write.

Every refusal leaves the attempt `admitted`, runs `harness.cleanup()`, and is one fixed word. `GitUnavailable` gives
`unavailable:git`.

**TOCTOU and the dead end.** Between admission and the entry, the branch can be created, moved or checked out
elsewhere. The entry still refuses. The attempt then stays `admitted`, with its slot reserved and the claim held, and
the entry's log line names the word. `plan show` says `start` until the deadline passes, then `stuck:expired_admitted`.
The person fixes the branch and reruns `tl plan start` before the deadline; after it, the only way out is the documented
factory.db discard. The window is small (seconds between admission and launch) but real (section 5).

**Parent plan, line 137** ("Preparation failure publishes a typed failed attempt with agent execution not started").
This slice does not do that. A preparation refusal is a pre-dispatch refusal like the existing credential and slot
checks since .4: nothing ran, so nothing is recorded and the attempt stays `admitted`. A typed terminal "failed, not
started" is only useful when it also releases the reservation and the claim. That needs the release slice (and a phase
or column, so a schema change), and it belongs there. Admission's pre-check removes the common cases until then.

**Detached-HEAD assumptions, after.**

| Where | After |
|---|---|
| `slots._clean` (adopt, free) | Unchanged: free means detached, a used slot is `attached`. |
| `SlotState.problem(at)` | `problem(at, branch)`: `branch` unless on exactly `task/<id>`. |
| `_base`, `settle`, `_unwritten`, `clean_at`, `leftovers` | On `task/<id>`, otherwise `branch`; `record` now advances the branch ref. |
| B, `_ours`, `judge` B..X, `head_moved`, `worker_gone`, pointer check | Unchanged: B is still the HEAD read just before dispatch. |
| .5's Q7 (no ref pins X) | Narrowed (L3): while the slot is on X, its HEAD already keeps X from garbage collection. The branch adds pinning only after a later park/detach (release slice). |
| `ATTEMPT_ONLY` help, adopt hint, live-smoke.md:71 | "no publication or release"; adopt hint adds "`git switch --detach` in a slot left on a task branch". Live-smoke `--acceptance` text "on the slot's HEAD" becomes "on task/<id>" (L4; edited by the implementer, not in this design-only change). |

**The agent's view.** Its cwd is the slot, on `task/<id>`, at B. It still cannot commit or move refs (the common dir is
outside its writable roots, .7). The pointer check is unchanged, and no prompt mentions HEAD state. While the slot holds
the branch, the person cannot check it out elsewhere or `git branch -f` it; `update-ref` still can, and settle then
reports `head_moved`. After a DB discard, `tl slot adopt` refuses a used slot (`attached`) until the person detaches it.
The branch and its commits stay, and the next attempt 1 resumes them when they contain D.

## 4. Facts, owners, schema

| Fact | Only writer |
|---|---|
| `refs/heads/task/<id>` created / checked out | `plan_prepare.py` (`take_branch`), inside the entry's lock |
| Branch advanced to X | `plan_commit.py` (`record`), inside the entry's lock or a verifier's `hold` |
| Slot custody | the kernel flock through `slot_lock.py`; the holder record is the library's and informational |
| B, X, verdict, reservation, phase | unchanged (`plan_store.py`, `plan_admit.py`) |

No column, table or version change: the branch name and the lock path are derived, and `WRITERS` is unchanged. A v5
attempt dispatched detached before this change verifies as `unsettled:branch`. That is truthful, and there is no compat
path. Rules:

- `.importlinter` gains a forbidden contract: source `taskloop` must not import `process_lock`, with
  `ignore_imports = taskloop.slot_lock -> process_lock`.
- `test_policy.GIT_WRITES` gains `take_branch`, and its expected set gains `("take_branch", "plan_prepare.py")`.

## 5. Failure and unknown table

| When | State left | Reported | Next |
|---|---|---|---|
| Admission: bad name, held or diverged branch | nothing: no input file, claim or row | `refused:branch_*` | person renames, deletes or frees the branch |
| Lock held elsewhere | nothing read or written | entry `refused slot_busy`; verify `unavailable:slot_busy` | rerun `tl plan start` / `verify` |
| Lock file not creatable | nothing | `refused lock` / `unavailable:lock` | fix the slots root permissions |
| Branch changed between admission and entry | `admitted`, slot and claim held | entry `refused branch_*`; `start`, then `stuck:expired_admitted` | fix the branch, `tl plan start` before the deadline; afterwards discard factory.db |
| Entry dies after the lock, before prepare | lock freed; `admitted` | `start` | relaunch |
| Entry dies inside `take_branch` | maybe `index.lock` or a half checkout | next entry `unavailable:git` / `slot_dirty` | owner inspects |
| Branch made, entry dies before dispatch | on `task/<id>` at base, `admitted` | `start` | relaunch: step 2, no write |
| Entry dies while the agent runs | lock free, agent may live | `unsettled:worker_alive` | stop the worker (`stuck:hung` guide) |
| Verify dies mid-commit | lock free, maybe a trailer commit | next verify adopts it (`_ours`) | rerun |
| Hung entry holds the lock | every verify `slot_busy` | | `stuck:hung` guide: worker, then entry |
| Lock file deleted while held | exclusion silently lost | nothing | documented residual |

## 6. Tests (contract, then consumer; caps 400/80/800)

The Git port's contract (`take_branch`, `refs`, `is_ancestor` against real and fake) is git_porcelain's own suite. The
factory tests consume `FakeRepo`, plus one real-Git wiring row.

- **Fixtures.** `prepared` in `tests/plan/conftest.py`: the slot moved with `slot.take_branch("task/tl-1", "HEAD",
  mode="resume")`. In both real fixtures: `git worktree add -b task/tl-1` instead of `--detach`.
- **`tests/plan/test_prepare.py`** (new, about 230 lines; parametrized tables):
  - name rule (each `branch_name` case, including `task` and `task/tl-1/x` conflicts and a case-fold twin);
  - created at D; created at a remote-tracking tip that contains D; already on the branch (spy: zero `take_branch`);
  - local or remote tip lacking D -> `branch_diverged`;
  - `branch_held`, `slot_branch`, `slot_detached`, `slot_unborn`, `slot_dirty`;
  - `slot_redirected` with zero Git calls; `GitUnavailable` -> `unavailable:git`;
  - every refusal: zero run calls, `cleanup` called, phase `admitted`;
  - admission: each `branch_*` refused before `put_input` and the claim (spies); a free slot whose D fails is skipped
    for one that passes.
- **`tests/plan/test_slot_lock.py`** (new, about 150 lines). Real kernel contention in one process: the test holds a
  raw second fd (`os.open` plus `fcntl.flock(LOCK_EX | LOCK_NB)`, released in `finally`). flock belongs to the open file
  description, so the library's own fd is refused by the kernel, not by its in-process registry. Cases:
  - entry -> `refused slot_busy` and zero `execute`;
  - `slot_lock.hold` verify -> `unavailable:slot_busy` with zero `stage`/`record`;
  - a stored verdict is returned while the lock is held;
  - repeat -> `unavailable:slot_busy` and `admit_repeat` never called;
  - the entry's own verify settles under `nullcontext`;
  - the lock is released after `enter` returns and after a raise inside it;
  - a free lock plus a live worker -> `worker_alive`;
  - the holder record has attempt and role only; an unwritable root -> `unavailable:lock`; `lock_path` is outside the slot.
- **Churn, checked in HEAD:**
  - the 11 `PlanVerifier(` test sites gain `hold` (the 11 `PlanAttempts(` sites are unchanged);
  - `tests/plan/real/test_commit_real.py`: its 8 direct `settle()` calls move to the branch fixture;
  - `tests/plan/real/test_repeat_real.py:80-85` and `tests/plan/test_repeat.py:168,312,450` (seeded attempts):
    prepared slot;
  - `tests/plan/test_ops.py:361` (leftovers): prepared slot;
  - `test_verify.py:211`, `test_dispatch_slot.py:93-116`, `test_repeat_run.py:191-201`: "attached" becomes "another
    branch", plus a detached row;
  - `tests/cli/test_cli.py:20,29`: the help text;
  - `test_entry.py`: the lock (raw-fd helper).
- **Budgets.** `test_verify.py` is 669 lines and `test_attempt.py` 774 (total lines; the gate counts SLOC). Neither
  takes new tests.
- **Real layer.** `tests/plan/real/test_prepare_real.py` (one row, about 80 lines): real repo, `--detach` slot, adopt,
  admit, execute with a `FakeRun` agent, verify -> `Verified`, `task/tl-1` tip == X.
- **Rules.** `test_isolation.SHARED` gains `"process-lock": "process-lock-v0.2.1"`; plus the `.importlinter` contract
  and the `GIT_WRITES` row from section 4.

Size estimates: `plan_prepare.py` about 170, `slot_lock.py` about 50, `plan.py` about 345, `plan_admit.py` about 375,
`plan_commit.py` about 210, `plan_verifier.py` about 150, `attempt_entry.py` about 185 (`enter` under 80).

## 7. Explicitly deferred

- Publication, fetch and any remote read beyond the local remote-tracking refs.
- Merging the target into the task branch.
- Release: the typed not-started failure with release, park/detach, generation reuse, and the free-rule lock probe.
- Force-unlock (never: the library never breaks a held lock).
- The heartbeat (.9) and descendant stop proof (.4.4).
- Created/resumed and the branch in `tl plan show`; the dashboard.

## 8. Dependency (checked)

- **Pin.** `pyproject.toml` gains `process-lock==0.2.1` and the source `{ git = ".../shelf.git", subdirectory =
  "packages/process-lock", tag = "process-lock-v0.2.1" }`.
- **Tag.** `git ls-remote` shows the tag object da9c83d peeling to d3d611ca15e0.
- **Lock file.** `uv lock --dry-run` (uv 0.13.0) on a scratch copy printed only `Add process-lock v0.2.1 (d3d611ca)`.
  The repo's `uv.lock` is untouched. The implementer runs `uv lock`, `uv sync` and `just test`.
- **Library.** stdlib only. It polls with `time.sleep` (never reached at `timeout=0`) and calls `os.kill(pid, 0)` only
  to word an error.

## 9. Owner questions

None open. Q1 is decided: refuse `branch_diverged` (local or local remote-tracking tip without D), and resume one that
contains D. The owner accepted the deferred free-rule probe. Decided here, open to veto: `timeout=0` everywhere; the
lock beside the slots; no fetch; repeats require the slot already on its branch; no schema bump; no typed not-started
failure before release.

## 10. Not verified

Nothing was run against Git. These were read from source, not exercised:

- real `take_branch` and its `BranchHeld` read;
- `FakeRepo.refs` prefix semantics against real `for-each-ref` (our code filters exact names either way) and whether a
  `FakeRepo.clone` carries `refs/remotes/origin/*`;
- macOS lock-path resolution and ref case-folding;
- whether `PLR0911`/C90 hold for the sketched split.

Line counts are estimates.
