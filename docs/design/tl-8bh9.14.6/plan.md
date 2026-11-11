# tl-8bh9.14.6: the checks step (block B4, milestone M2)

Design, 2026-11-11, against HEAD f5ef43664 (M1 built, M1 smoke passed). Docs only: nothing built or run. Read:
CLAUDE.md, [glossary](../../glossary.md), [roadmap](../self-hosting-roadmap.md) (B3, B4, B6, B7, D1-D14, O1-O6),
[candidate checks](../tl-8bh9.5.1/candidate-checks.md), [.15](../tl-8bh9.4.3.1.15/plan.md) section 5,
[.16](../tl-8bh9.4.3.1.16/plan.md) sections 12-15, [S5e](../tl-8bh9.4.3.1.16.2/plan.md) and the
[M1 smoke findings](../tl-8bh9.4.3.1.16.2/m1-smoke-findings.md), [profile reader](../tl-8bh9.14.1/plan.md), and
`steps`, `environment`, `setup_store`, `factory_schema` (v11), `attempt_status`, `round`, `operations`, `slot_release`,
`launch`, `attempt_entry`, `prepare`, `admit`, `admit_chain`, `composition`, `step_render`, `tests/rules/test_policy.py`.

The owner is away and asked for autonomous decisions. Every decision below is marked **decided here** (recommendation,
open to veto); owner decisions D1-D14 are cited by number. Section 13 lists blocking owner questions: none.

## 1. What changes for the owner

After an implement attempt is verified and published at X, the next round advances the task to a **check** step: it
reserves a free slot, checks X out detached, resets the slot and runs the profile's `setup` at X, then runs every check
of `.task-loop.json` at X on the host (normal networking, the agent's scrubbed environment and push bar, D9/D10), one
after another, each with its timeout. Each check's output is an evidence file; each result is a row in factory.db. The
step concludes `passed` only when every check named in `required` by the profile at `main` passed on X; otherwise
`failed` with a reason. `tl step show` prints one `Check:` line per check (conclusion, exit, duration, output path) and
the step's result; `tl step list` shows the step `check`. A failed check leaves the task `done` with a visible failed
result and its claim kept (M2; holds are B7). Nothing is merged, landed, pushed or committed by this step.

## 2. Decisions this design respects

D1 (any plain file, so a task may change its own profile, `justfile` and `setup`), D2 (bare static analysis always
runs: here `check` is required at `main`), D3 (no label check on an advance), D4 (an abandon restarts at plan), D6, D9
(normal host networking for checks; one mandatory check set, no pass cache), D10 (checks on the host, before any
review, scrubbed environment and push bar, no scratch HOME), D11 (commands from the profile at X, required names from
the target), D12 (`setup` from the same ref as the checks, run by the factory with network), D14 (factory folders
beside the slots). Candidate checks: a failure is a result, never a pass; no reuse across candidates; an interrupted
block repeats after a stop proof; a check that changes tracked files invalidates the candidate.

## 3. A step with its own tables, not a step kind (decided here)

The checks step has no agent, input, answer, session, commit, verifier or publication, so it is not a `StepKind`
(`steps.STEPS` stays `(PLAN, IMPLEMENT)`; `kind("check")` stays an error) and its attempt is not an `attempt` row: six
NOT NULL `attempt` columns are agent facts (input path and digest, schema version, model, effort, sandbox) and the `execution`/
`verification`/`published_branch` chain hangs off it; making them nullable would put `step == "check"` branches into
admission, the entry, capture, verify, repeat, publish and release (.15 section 5: "attempt rows are not made nullable
for them"). Instead:

- **Own tables** `checks_attempt` (the step's attempt) and `check_result` (one check's result in one block), section 4.
- **Shared by reuse, not by copy:** the `reservation` and `slot` rows (a checks attempt reserves a slot exactly as an
  advance does: `admit.reserve`), slot custody (`slot_lock.custody`), the launcher (generalized over its target table),
  the boot-aware stop proof (`slot_release.entry_stopped`, `setup_store.SetupSeen`), the park (`slot_release` extracts
  its slot read and park as a function), the whole environment preparation (`environment.Preparation`, with the sandbox
  probe off), the capped evidence log, the registered start (`stream_proc.run_registered` through the existing
  `SetupProcess` port), the claim keep-alive (`claim_lease`), and `Next`, `rounds.log` and `tl step` words.
- **Sequencing:** `steps.following("implement")` becomes `"check"` (a module constant `ORDER = ("plan", "implement",
  "check")`; `following` no longer goes through `kind`). `Next: advance` keeps its one meaning (admit attempt 1 of the
  next step of a done attempt); `operations._admit` sends an advance whose next step is `check` to the checks
  admission instead of `NextAdmission.admit_next`. `next_step`'s table is unchanged for agent steps.
- **Words:** the step is `check` (glossary's step list; `Step: check`, `rounds.log` `<task> check advance started`). The
  attempt is a **checks attempt** (`checks_attempt`). The glossary's "attempt of an individual check" is a `check_result`
  row identified by (checks attempt, block, name); no extra noun.

## 4. Schema v12 (no migration; v11 is refused `schema`)

```sql
CREATE TABLE checks_attempt (
 attempt_id TEXT PRIMARY KEY, dispatch_token TEXT NOT NULL UNIQUE, generation INTEGER NOT NULL,
 after_attempt_id TEXT NOT NULL UNIQUE REFERENCES attempt(attempt_id),  -- the done implement attempt; one checks attempt each
 adapter TEXT NOT NULL CHECK(adapter='beads'), backlog TEXT NOT NULL, task_id TEXT NOT NULL,
 tracker_root TEXT NOT NULL CHECK(substr(tracker_root,1,1)='/'),       -- copied: the claim keep-alive and the abandon
 repo_id TEXT NOT NULL, slot TEXT NOT NULL,
 slot_head TEXT NOT NULL CHECK(length(slot_head) IN (40,64)),           -- D: the free slot's HEAD; the release parks here
 commit_sha TEXT NOT NULL CHECK(length(commit_sha) IN (40,64)),         -- X: the implement attempt's end commit
 target_commit TEXT NOT NULL CHECK(length(target_commit) IN (40,64)),   -- T: `main` when the required names were read
 required TEXT NOT NULL,              -- JSON [[name, argv digest of that name at T], ...] in T's `required` order, 1..32
 profile_digest TEXT CHECK(profile_digest IS NULL OR length(profile_digest)=64),  -- sha256 of `.task-loop.json` at X; set once
 deadline REAL NOT NULL, entry_pid INTEGER, entry_start TEXT, entry_boot TEXT,
 phase TEXT NOT NULL DEFAULT 'admitted' CHECK(phase IN ('admitted','concluded')),
 rev INTEGER NOT NULL DEFAULT 0,
 conclusion TEXT CHECK(conclusion IN ('passed','failed')), reason TEXT, concluded_at REAL,
 released_at REAL, parked TEXT CHECK(parked IS NULL OR length(parked) IN (40,64)),
 abandoned INTEGER NOT NULL DEFAULT 0 CHECK(abandoned IN (0,1)),
 CHECK((phase='concluded') = (conclusion IS NOT NULL)), CHECK((conclusion IS NULL) = (concluded_at IS NULL)),
 CHECK((conclusion='failed') = (reason IS NOT NULL)), CHECK((released_at IS NULL) = (parked IS NULL)),
 CHECK(abandoned=0 OR released_at IS NOT NULL)
);
CREATE TABLE check_result (
 attempt_id TEXT NOT NULL REFERENCES checks_attempt(attempt_id), block INTEGER NOT NULL CHECK(block >= 1),
 position INTEGER NOT NULL CHECK(position >= 0),   -- the check's index at X; an undefined required name follows them
 name TEXT NOT NULL, dispatch_token TEXT NOT NULL, generation INTEGER NOT NULL,
 argv_digest TEXT CHECK(argv_digest IS NULL OR length(argv_digest)=64), timeout INTEGER CHECK(timeout IS NULL OR timeout >= 1),
 pid INTEGER, pgid INTEGER, proc_start TEXT, boot TEXT,   -- the command's registered identity, committed before it executes
 started_at REAL NOT NULL, ended_at REAL, rc INTEGER,
 conclusion TEXT CHECK(conclusion IN ('passed','failed','timed_out','lingering','dirty','undefined','interrupted')),
 CHECK((ended_at IS NULL) = (conclusion IS NULL)), CHECK((argv_digest IS NULL) = (conclusion IS 'undefined')),
 CHECK((timeout IS NULL) = (argv_digest IS NULL)),
 PRIMARY KEY (attempt_id, block, position), UNIQUE (attempt_id, block, name)
);
```

`setup_run` loses `REFERENCES attempt(attempt_id)`: its `attempt_id` names an `attempt` or a `checks_attempt` (both
uuid4 hex, never equal). `setup_store.HELD` becomes the union of today's fence and the same fence on `checks_attempt`
(`phase='admitted'`, the reservation held at the key's generation). Nothing else in v11 changes.

**What the rows mean.** The phase is only `admitted` (setup and blocks run; the agent attempt's `dispatching` and
`registered` exist because an agent runs at most once, which does not hold for checks) and `concluded`. "Latest block"
is the highest `block`; the conclusion reads only that block. One fact, one owner (decided here): X, T, the required
list and the profile digest are on the checks attempt, never copied into each result; every result is read joined with
its attempt, so a result always travels with its X, its profile digest and its argv digest. `timed_out` is the
conclusion `timed_out`; the exit is `rc`; the duration is `ended_at - started_at`. The output is a file (section 7),
never a column.

**Writers** (`test_policy.WRITERS`): `CREATE TABLE checks_attempt`, `check_result` by `factory_schema.py`; `INSERT` and
`UPDATE` of `checks_attempt` and of `check_result` by the new `check_store.py` (the admission's insert is a
`check_store` function called inside the admission's transaction; `INSERT reservation` and `UPDATE slot` stay `admit.py`'s
through `admit.reserve`; `DELETE FROM reservation` stays `slot_release.py`'s through an extracted `free(con, ...)`).

**What else batches into v12 (decided here): nothing.** B6 (land record and actions) and B7 (holds) have no design yet;
adding guessed tables now would be unused speculative schema (CLAUDE.md). If either design is settled before S6a is
built, its DDL joins v12 so the owner discards once; otherwise each brings its own discard. B7 as roadmapped (a tracker
comment, the label removed, the claim returned through the existing abandon) may need no table at all.

## 5. Admission: like an advance (`check_admit.py`, new)

`ChecksAdmission.admit_checks(ChecksRequest(previous: AttemptKey, checkout, deadline))`, called by `operations._admit`
for an advance whose next step is `check` (by `tl step start` and the round alike). Order, every read before any effect:

1. Choices and the deadline (`admit.deadline_refusal`).
2. The previous attempt (`admit_chain`'s `_task_of` and done-ness reads, shared): current (no `LATER`), step
   `implement`, verified, released `kept`, published at its `end_commit` (else `not_advanceable`); no checks attempt for
   it (else `task_attempted`). The checkout's repository is the attempt's (`checkout`).
3. X still on the task's branch: the local `task/<id>`, else the remote-tracking one, contains X (`prepare.lacks`), else
   `branch_moved`; X readable in the repository, else `commit_missing`. The checks run on X itself, not the tip.
4. **The required names (O1 as B3 built it; decided here):** `refs/heads/main` of the repository resolves to T (else
   `refused target`); `profile.read_profile(files, T)` through `GitProfileFiles` on the checkout's view (`Refused`:
   `refused target_profile` with B3's reason in the detail; `Unavailable`: `unavailable git`); its `target` must be
   `main` (another land branch is B6's, `refused target`); its `required` must be non-empty (`refused no_required`: a
   checks step with nothing required would conclude `passed` vacuously and land would trust it). The list stored is each
   required name with the argv digest of that name's check at T (B3 guarantees T defines it).
5. Free slots (`admit.free_slots`). No branch rule: the slot takes X detached, never `task/<id>`.
6. One tracker read (`admit.read_task`): `claim_lost` unless `in_progress` for `taskloop`; no label (D3).
7. One write transaction re-reading 2 and an unheld slot: `admit.reserve`, then `check_store.insert` (D = the slot's
   HEAD, X, T, required, `tracker_root` copied, deadline, `phase='admitted'`). A lost race on `after_attempt_id` is
   `task_attempted` (the caller launches the winner, as the advance does). No claim call, no input file.

Refusal words are a skip of the done implement attempt in the round (section 9) except `no_free_slot` and the existing
`ADVANCE_STOPS`, which stop the phase. `target`, `target_profile` and `no_required` are about `main`, so every done task
skips with the same word until the person fixes `main`; the round's `quiet` set writes each line once.

## 6. The checks entry (`check_entry.py`, new)

`python -I -m taskloop.check_entry DB ARTIFACTS BACKLOG TASK`, launched through `launch.Launcher` (generalized: an
`EntryTargets` port with `attempt_of` and `register_entry`, implemented by `AttemptStore` and `CheckStore`, and the
entry module name; the deadline renewal once per reboot is the same rule in `CheckStore.register_entry`). Its stdout and
stderr are the checks attempt's `entry.log`. Order:

1. factory.db exists (never created); the current checks attempt of the task; this process is its registered entry
   (`refused identity` otherwise), exactly as `attempt_entry._registered`.
2. Slot custody, never waiting (`refused slot_busy`), held to the end.
3. The claim keep-alive (`claim_lease.keeping`, the stored tracker root): a claim found lost before the block refuses
   `claim_lost`; one lost later is only recorded (`claim=` word), the results stand (they are about X, not the claim).
4. `refused expired` past the deadline.
5. **Take X** (`prepare.detach_at`, new in `prepare.py`, so no new Git writer module): through `observe_slot` and the
   pinned view, a clean slot detached at D is parked at X (`Worktree.park(X)`), then re-read: HEAD X, detached, clean;
   a slot already detached at X and clean passes (a relaunch); dirty `refused slot_dirty`, on a branch `refused
   slot_branch`, X gone `refused commit_missing`, pointer `refused slot_redirected`.
6. **Reconcile the latest block**: each result row with no conclusion, or concluded `lingering` or `timed_out`, whose
   registered command is alive (`setup_seen`'s rule: another boot is gone) gives `unavailable checks:running`, unknown
   `unavailable checks:unknown`, never signalled; gone (or never registered) rows with no conclusion become
   `interrupted`. Then the block repeats whole (candidate checks: "repeating a completed prefix is acceptable").
7. **The profile at X** (`read_profile` through `slot_profiles`, pinned): `Refused` concludes the attempt `failed`,
   reason `profile:<reason>` (X's own profile is the candidate's); `Unavailable` is `unavailable git`. The blob's sha256
   is the profile digest, set once (`check_store.profiled`; a different digest on a relaunch is `refused
   profile_changed`, which cannot happen for one X and is checked anyway).
8. **The environment**: `Preparation.prepare_for(SetupFor(key, slot, branch=None, deadline, first=True), prepared,
   renew, env=scrubbed, probe=None)` (section 8). Two failed setup runs (`setup_store.failures >= SETUP_RUNS`) conclude the
   attempt `failed`, reason `setup:<latest conclusion>`, in the entry that sees the count reached (decided here: setup
   at X is the candidate's command, and two runs absorb one network failure). Any other preparation refusal leaves the
   attempt `admitted` with S5e's words (`environment:*`, `expired`, `claim_lost`).
9. **The block** (`checks.Block.run`, section 7).
10. **The conclusion**: `passed` when, in the latest block, every stored required name has a result `passed`; else
    `failed` with the reason of the first required name (T's order) that did not pass: `<name>:<conclusion>`, or
    `<name>:not_run` when the block stopped before it. A stopping `dirty` or `lingering` of a non-required check is the
    reason itself (it invalidated the slot). Written once, fenced (`check_store.conclude`).
11. **Release** of its own slot under the lock it holds (`ChecksRelease.release(key, abandon=False, me)`, section 10),
    then the scratch `.t/<slot>` emptied.
12. One log line of fixed words: `collected passed|failed:<reason>` or the refusal, then `claim=`, `release=`. Exit 0
    only for `passed`.

Nothing here is retried; every `unavailable` leaves the attempt `admitted`, and the next round relaunches it.

## 7. The block (`checks.py`, new)

One block runs every check of the profile at X in profile order, each once, required or not (decided here: D9's one
mandatory set; a non-required result is shown and never decides; the task adding a check runs no code that `setup` could
not already run). Before the first command, each stored required name the profile at X does not define gets a result
`undefined` (no process, no argv digest): a required check that never reports blocks, as on GitHub.

Per check, `name`, `argv`, `timeout` from the profile at X:

1. `check_store.start(key, block, position, name, argv_digest, timeout)` (argv digest: sha256 of the argv as compact
   JSON, `environment.setup_digest`'s rule on one argv).
2. The log `attempts/<hash>/check-<block>-<name>.log` (0600, append, 32 MiB then one `[truncated]` line: S5e's
   `SetupLog`, renamed `CappedLog`, three references), framed by the factory's own lines `$ <shlex.join(argv)>` and the
   ending (`exit <rc>`, `timed out`, `not started`, `ended by a signal`, `start uncertain`, `lingering`, `dirty`). Check
   names are B3's `[A-Za-z0-9._-]` not starting with `.` or `-`, so the file name needs no escaping.
3. The registered start (`SetupProcess`, real `stream_proc.run_registered`): the `registered` callback commits the
   identity (`check_store.registered`, the bounded registration connection) before the command executes; cwd the slot;
   stdin empty, stderr merged; environment `environment.setup_env(scrubbed, folders(slot))`: the scrubbed environment
   and push bar, `TMPDIR` = `.t/<slot>`, `UV_CACHE_DIR`, `UV_TOOL_DIR`, no `UV_OFFLINE`, the person's `HOME` (D10);
   wall timeout `min(timeout, deadline - now)`.
4. The judgment, in this order:

| Ended | Result | The block |
|---|---|---|
| Start uncertain | none (identity stored) | stops: `unavailable checks:uncertain`; the next entry reconciles |
| Stopped by its own timeout | `timed_out` | continues (the library stopped and proved its tree) |
| Stopped by the attempt's deadline | `interrupted` | stops: `refused expired` (not a result of the check) |
| Its group still has a member | `lingering` | stops: the attempt concludes `failed`; the release waits for the group |
| Exec failed, or exit not 0 | `failed` | continues |
| Exit 0 | judged by step 5 | |

5. The slot after every check that exited (any exit), through the pinned view: HEAD X, detached, and no tracked or
   untracked change (`--ignored=no`; ignored files such as `.venv` and caches are allowed). Otherwise the result is
   `dirty` (whatever the exit) and the block stops: the candidate no longer stands for X (candidate checks); the attempt
   concludes `failed`; the slot stays as the check left it and the release refuses `slot_dirty` until the person
   removes the listed files.
6. Exit 0 and a clean slot: `passed`.

A pass (glossary) is therefore exactly: a `check_result` row concluded `passed` in its checks attempt's latest block,
whose attempt names X, the profile digest at X and the argv digest. It is never looked up for another X, another
checks attempt or another task: nothing reads results except the status of their own attempt (and later land, for the
same X).

## 8. Environment: S5e's machinery, reused

`Preparation.prepare(record, ...)` stays the implement path; both paths call one `prepare_for(target: SetupFor, slot:
Prepared, renew, env, *, probe: Launch | None)` where `SetupFor(key, slot_path, branch: str | None, deadline, first:
bool)`; `probe` is the agent's Codex and environment for the sandbox probe, None for no probe.
For checks: `branch=None` (step 8 of S5e section 4 expects HEAD = X detached), `probe=None` (no sandbox; the platform,
`path_long`, roots and removal checks stay, so checks inherit `environment:platform` off Linux, where implement never ran
anyway), and **no reuse** of a passed setup (decided here): every block starts with S5e's reset (`git clean -ffdx` on the
pinned view, an empty ignored listing, `.env/<slot>` emptied) and a fresh `setup` at X. A block that ran task code on the
host may have left anything in ignored files or the uv folders; repeating setup is the price of a block that starts
from X alone. The scratch is emptied before and after setup, as for an agent.

The scrubbed environment without Codex: `composition.codex_machine_credentials` is split into `scrubbed(environ)` (the
scrub, the venv drop, the push bar) and the Codex lookup; the checks entry uses `scrubbed` only, so a checks attempt
needs no `codex` on `PATH` and no `auth.json`.

## 9. Status, `Next`, the round and `rounds.log`

`attempt_status`: for a task whose current agent attempt is a done implement attempt, `check_store.of_attempt` reads its
checks attempt; `AttemptView` gains `checks: ChecksView | None`, and when it is set the view's `step`, `attempt_id`,
`slot`, `phase`, `entry`, `deadline_passed` and `next` are the checks attempt's (its `earlier` gains `(<implement id>,
advanced)`).

| Checks attempt | `Next` |
|---|---|
| none (implement done) | `advance` (as today; `following("implement")` is now `check`) |
| `admitted`, entry running | `wait`; past the deadline `stuck:hung` |
| `admitted`, entry none, gone or another process | `start` (a relaunch: safe, section 6.6; no `stuck:entry_lost` for checks) |
| the same, past the deadline (not rebooted) | `stuck:expired_admitted` |
| entry unknown, or a store read fails | `unknown` |
| `concluded`, not released | `release` |
| released by an abandon whose implement claim is still `kept` or `unclaiming` | `release` (rerun `--abandon`) |
| released, `passed` or `failed` | `done` |

The round (`round.py`) needs no new phase: the advance phase admits and launches checks attempts (claimed work first,
FIFO by the implement release time); settle relaunches `start`, reports `wait`, `release`, `stuck:*`; `_resume` sends a
checks attempt to the checks launcher. `rounds.log` lines, fixed words:

```
<time> <backlog> tl-1 check advance started <checks attempt>
<time> <backlog> tl-1 implement skip no_required <implement attempt>
<time> <backlog> tl-1 check relaunch relaunched <checks attempt>
<time> <backlog> tl-1 check report running <checks attempt>
<time> <backlog> tl-1 check report failed:test:failed <checks attempt>
```

`done` and `passed` write nothing (as a succeeded `done` today); `done` and `failed` is reported `failed:<reason>`, kept
to one line by `quiet` (as a failed `done` today).

**`tl step show`** for a checks attempt (human; JSON key `checks` with the same facts, `results` a list):

```
Task: tl-1 (backlog m2)
Step: check
Attempt: <id>
Earlier: <implement id> advanced
Slot: s1
Phase: concluded
Entry: gone (pid 4242, started ...)
Commit: <X>
Required: check, test (main at <T>)
Profile: <digest> at X
Setup: run 1 passed at <X>; log <dir>/setup-1.log
Check: check passed, exit 0, 41 s; log <dir>/check-1-check.log
Check: test failed, exit 1, 312 s; log <dir>/check-1-test.log (argv differs from main)
Check: smoke undefined (required by main, not defined at X)
Result: failed test:failed
Succeeded: no
Released: 2026-11-12 10:00:00 UTC, slot parked at <D>; claim kept
Next: done
```

`(argv differs from main)` marks a required check whose argv digest at X differs from the one stored from T (decided
here: the cheapest visible signal of a task changing a required command, D1/D11; land repeats it, section 12). A
non-required check is marked `(not required)`. `tl step list`: step `check`, the checks attempt's slot, phase, entry,
`collected passed|failed:<reason>` or `pending`, and `Next`; `--stuck` includes its `stuck:*` and `unknown`.
`tl step verify` and `tl step publish` act on the agent attempt only (unchanged). `STEP_ONLY` names `plan, implement,
check`. GUIDE gains `no_required`, `target`, `target_profile`, `commit_missing`, `profile_changed`, `checks` (for
`checks:running|unknown|uncertain`) and `check_running`, each one sentence on what the person does.

## 10. Release, abandon, publish, D4

`check_release.py` (new), `ChecksRelease.release(key, abandon, me)`, the same shape as `SlotRelease`:

- **Settled** (`tl step release TASK`, and the entry itself): the attempt `concluded` (else `refused not_terminal`).
- **Stop proof, both modes**: the registered entry (`entry_stopped`, `me` passes), the latest setup run's unsettled
  command (`setup_store.running`) and the latest block's unsettled check command (`check_store.unsettled`), both through
  `setup_seen`: alive `held:setup_running` / `held:check_running`, unknown `unavailable setup_unknown` /
  `check_unknown`. Never signalled; the guide lists the group's members and their cwd for the person.
- Then the lock, the slot read and the park at D (the extracted `slot_release.park_slot`: detached at X and clean is
  parked at D; dirty `held:slot_dirty`), one transaction fenced on `rev`, `phase`, the held reservation and no release
  (`check_store.record_release` with `abandoned`, `slot_release.free`), then the scratch emptied, best effort.

**Abandon** (`tl step release --abandon TASK` while the task's current step is check), in this order:
`ChecksRelease.release(checks key, abandon=True)` (skipped when already released), then the existing
`SlotRelease.release(implement key, abandon=True)`, which flips the implement attempt's `kept` release to `unclaiming`
and returns the claim. A failure between the two shows `Next: release`; rerunning `--abandon` finishes. By D4 the next
start is a fresh plan; the old checks attempt hangs off an abandoned implement attempt and is never current again.

**Publish**: the checks step pushes nothing and commits nothing. It requires the implement attempt published at X
(section 5.2) and runs on X itself; X stays on origin's `task/<id>` for land.

**Results across candidates**: a new implement attempt (after an abandon) has its own X and its own checks attempt;
nothing is carried. The same X checked again (an implement answering `unchanged` after an abandon) runs again: a new
workflow, no pass cache (D9).

## 11. The failed-checks route (O2; decided here for M2)

M2 holds nothing: a failed checks attempt is `done` with `Result: failed <reason>`, `Succeeded: no`, the claim kept
(`in_progress` for `taskloop`), the slot released, and one `check report failed:<reason>` line in `rounds.log`. The
person reads the `Check:` lines and logs, then either fixes by hand on `task/<id>` and lands by hand (M2 is still hand
land), or abandons (D4: plan, then implement on the current branch, then checks on the new X). **Recommendation for
B7 (M4):** a failed checks attempt is one more hold reason: comment `<reason>` and the failing log paths on the task,
remove `auto`, return the claim (O5). Automatic repair (back to implement with the output, tl-7i9k.56.1) stays later,
after smokes show how often it would help (O2's recommendation unchanged).

## 12. Security (D10 accepted) and what land must show later

The candidate's code runs on the host before anyone reads it, twice per block (`setup`, then every check), with
network, the person's `HOME` (SSH keys, `~/.netrc`, Git credential helpers reachable), and a push bar that is only an
environment entry the code can unset. That is D10 and S5e Q3, accepted; nothing here widens it beyond what setup already
runs. Kept: no Codex credentials (`scrubbed`), the scrub of credential variables, the push bar, the factory folders
outside the slot, the slot's lock, the pinned Git views, the stop proof before reset and release.

**The B6 land summary must list** (recorded here so B6's design starts from it):

1. The checks attempt for exactly the land candidate X (else the checks run again), its conclusion, T, and each
   required name with its result.
2. Whether `main` moved since T, and the required names at the new target tip (a newly required name reruns checks).
3. Each required check whose argv at X differs from the target's (stored digests), with both argv shown.
4. Checks the task added, removed or changed at X (non-required ones ran on the host too) and every changed `setup`.
5. Every changed check-configuration file between the target and X: `.task-loop.json`, `justfile`, `pyproject.toml`,
   `uv.lock`, `mise.toml`, `.importlinter`, `tests/rules/`, any `conftest.py`, and any file a check's argv names.

## 13. Owner questions

**Blocking: none.** Non-blocking, each built as decided unless vetoed:

1. **O1** (required names from `main`): built as B3 built it, reading the local `refs/heads/main` (the person's, which
   the factory never writes), not `origin/main`.
2. **Empty `required` at `main`** refuses `no_required` rather than passing vacuously.
3. **Every check at X runs**, required or not; only required ones decide.
4. **Two failed setups conclude `failed setup:<conclusion>`** rather than `stuck:setup_failed`.
5. **O2 for M2**: failed is a visible `done`, no hold (section 11).

## 14. Slices (caps: 400 code lines per file, 80 per function, 800 per test file)

Code lines by the policy counter; current counts in brackets.

| Order | Slice | What | Source | Tests |
|---|---|---|---|---|
| 1 | **S6a schema and store** | v12 DDL and column lists; `check_store.py` (rows and conclusion types, `insert`, `of_attempt`, `attempt_of`, `register_entry` with the reboot renewal, `profiled`, `block`, `start`, `registered`, `conclude_result`, `undefined`, `conclude`, `record_release`, `results`, `unsettled`); `setup_store.HELD` union; `WRITERS` | `factory_schema` [109] +32, `check_store` new ~210, `setup_store` [97] +4 | `test_check_store.py` ~300; `test_setup_store` +30 |
| 2 | **S6b block and environment** | `checks.py` (`ChecksPorts`, `Block.run`: reconcile, undefined rows, each check, judgment, clean read, conclusion); `environment.prepare_for`, `SetupFor`, `probe` flag, no reuse for checks [229] +20; `prepare.detach_at` [125] +28; `evidence_files.check_log`, `CappedLog` [107] +10; `composition.scrubbed` [317] +6 | `checks` new ~190 | `test_checks.py` ~420; `test_environment` +60; `test_prepare` +60; `real/test_checks_real.py` ~70 |
| 3 | **S6c entry, launcher, release** | `check_entry.py` (section 6); `launch.EntryTargets` [150] +14; `slot_release.park_slot`, `free` [263] +8; `check_release.py`; composition wiring of the entry, release and launcher [~323] +35; import contracts (`check_entry`, `checks`, `check_release` join the entry's closure; `check_entry` joins `cli-never-imports`) | `check_entry` new ~175, `check_release` new ~125 | `test_check_entry.py` ~330; `test_check_release.py` ~260; `test_launch` +40 |
| 4 | **S6d admission and `tl step`** | `check_admit.py` (section 5); `steps.ORDER`, `following` [46] +6; `operations` routing: `_current` reads the checks attempt, `_admit` dispatch, check launcher, release and abandon order [276] +40; `attempt_status` `ChecksView` and the `Next` table [154] +55; `step_render` [138] +40, `result_data` [108] +20, `step_guide` [133] +15; `cli_composition` [210] +25 | `check_admit` new ~125 | `test_check_admit.py` ~300; `test_operations` +80; `test_step_cli` +140 |
| 5 | **S6e round and words** | `round._settle`/`_resume` routing for checks attempts [240] +20; glossary (section 15); roadmap B4 row; the live smoke file | +20 | `test_checks_round.py` ~320; `test_round` +40 |

Total about +1,230 source and +2,500 test lines (S5e-1 alone was +408/+567). Largest new functions: `Block.run` split
into reconcile, one check and conclusion (each under 45); the entry's `enter` about 50. `composition` ends near 365
code lines: tl-8bh9.14.20 (composition split) should land before S6c if it is ready, else after M2.

Dependencies: S6a, then S6b, S6c, S6d, S6e in order (each needs the previous one's types; S6d's admission writes rows
only S6c's entry runs). Each slice lands green with `just check` and `just test`, independently reviewed. The live smoke
(section 17) follows S6e; M2 is reached when it passes.

## 15. Glossary changes (S6e)

| Term | Meaning |
|---|---|
| check (as built) | A named entry of the profile's `checks` at X that the checks step runs on the host. |
| checks attempt | The check step's attempt (`checks_attempt`): one per done implement attempt; a slot, an entry process (`taskloop.check_entry`), a deadline; X, T, the required names; concluded `passed` or `failed` with a reason. Not an `attempt` row. |
| block | One pass over the profile's checks at X within a checks attempt, after a reset and `setup` at X; an interrupted block repeats whole after its stop proof. |
| check result | One check's result in one block (`check_result`): `passed`, `failed`, `timed_out`, `lingering`, `dirty`, `undefined` (required at `main`, not defined at X), `interrupted` (not a result of the check: the block stopped). Its output is `check-<block>-<name>.log`. |
| pass (as built) | A check result `passed` in its checks attempt's latest block, for that attempt's X, profile digest and argv digest; never looked up for any other X or attempt. |
| result (checks) | The checks attempt's conclusion and reason, `<name>:<conclusion>`, `<name>:not_run`, `setup:<conclusion>` or `profile:<reason>`. |

Also: the `profile` row loses "the factory does not run the checks yet"; `stuck`/`Next` and `reserved / locked / held`
gain `held:check_running`; `step kind` says the check step is not one; `evidence files` gains `check-<block>-<name>.log`.

## 16. Tests (pytest functions, fakes through ports, no process in factory tests)

- **Store** (S6a): every v12 CHECK (phase/conclusion, reason, release pair, abandoned, undefined/argv/timeout, unique
  name per block); writes fenced by token, generation and the held reservation of an `admitted` attempt; a concluded
  attempt refuses new results; the reboot renewal; latest block only; `unsettled`; a checks attempt's setup run fenced
  through the new `HELD`, an agent attempt's unchanged.
- **Block** (S6b), as observed events over fakes: the identity committed before the fake executes; env (push bar,
  folders, no `UV_OFFLINE`, no Codex variables), cwd, timeout `min`; each judgment row of section 7 including deadline
  versus own timeout; `lingering` and `dirty` stop the block; a non-required failure still `passed`; an undefined
  required name `failed`; the profile at X refused concludes `profile:<reason>`; reconcile alive, unknown, gone,
  unregistered; the log framing and cap. Mutations of the judgment order, the clean read, the required-only verdict and
  the `min` timeout each fail a test (run by hand, not kept). Real: a slot detached at X with a real `sh -c` check that
  passes and one that writes a tracked file (`dirty`).
- **Entry and release** (S6c): the order of section 6 as events; `slot_busy`, `identity`, `claim_lost`, `expired`;
  take X fresh and on relaunch; two failed setups conclude `setup:failed`; the release's stop proof for setup and check
  commands in both modes; the park and the fence; abandon then the implement's flip.
- **Admission and status** (S6d): the stored row; each refusal of section 5 with nothing written; a racing admission;
  every row of the `Next` table; show lines and JSON; list and `--stuck`; release and abandon order and its rerun.
- **Round** (S6e), end to end over real SQLite and fakes: plan, implement, `check advance`, block, `passed`, `done`; the
  failed path reported once; a block interrupted (entry gone, command gone) relaunched and repeated as block 2; a
  checks advance waits for a slot and goes before a new task; an abandon during checks restarts at plan.

## 17. Live smoke (owner, or an agent the owner authorizes, after S6e)

Base: the M1 runbook ([live-smoke.md](../tl-8bh9.4.3.1.16.2/live-smoke.md) "M1 end-to-end smoke") with a new scratch
folder `$M2`, the runner at the S6e commit, the scratch remote's `main` at that commit, and factory.db new (v12).

1. `T profile show --at HEAD` in the scratch checkout: setup `just bootstrap`; checks `check`, `test`; required both.
2. A small `auto` task (as M1's); `T step rounds ... --minutes 120`. Expect in `rounds.log`: `plan start`, `implement
   advance`, `check advance started <id>`; then quiet until `done`.
3. While the block runs: `T step show` says `Step: check`, `Entry: running`, one `Check:` line `unfinished`; the entry's
   pid is the recorded one; `ps -o pid,pgid,cmd` shows `just test` in the recorded group, cwd the slot.
4. After: `Result: collected passed`, two `Check:` lines `passed, exit 0` with logs that end `exit 0` and contain
   `All checks passed!` and `N passed`; `Released: ... claim kept`; `Next: done`. `bd show`: `in_progress`, `taskloop`.
   The slot detached at D, `status --porcelain` empty; `.t/<slot>` empty.
5. **Interrupted block**: a second task; while its `test` check runs, stop rounds (Ctrl-C), then stop the checks entry by
   its recorded pid and wait until the recorded check group is empty (the person verifies the pid is the entry shown
   by `T step show`). Restart rounds: `check relaunch relaunched`; `T step show` shows block 2; block 1's row
   `interrupted`; the final result is block 2's.
6. **Undefined required**: a third task; after its `implement advance` line, commit to the scratch checkout's `main` a
   profile adding a check `smoke` (`["true"]`) to `checks` and `required`. Expect `Check: smoke undefined`, `Result:
   failed smoke:undefined`, one `check report failed:smoke:undefined` line, claim kept.
7. **Abandon during checks** (optional): `T step release --abandon` while a block runs refuses `entry_running`; after
   it ends, the abandon releases the checks slot and returns the claim; `T step start` begins at plan.
8. Record findings in `docs/design/tl-8bh9.14.6/m2-smoke-findings.md` as for M1.

## 18. Risks

- **Host execution before review** (D10): accepted; mitigations in section 12.
- **One `--minutes` for every step**: setup plus all checks must fit one deadline (this repository: about 1 minute of
  setup plus `just check` and `just test`); a deadline mid-block is `stuck:expired_admitted` and costs an abandon (plan
  again). Per-step minutes stay deferred; the guide says to raise `--minutes`.
- **Setup per block** (no reuse): minutes and downloads per checks attempt and per relaunch (S5e Q1's cost again).
- **A dirty or lingering check holds the slot** until the person cleans or stops the group; with one slot, the loop
  stops taking work. B7 and the git timeout (M4) do not change that; a reset of a checks slot's tracked files is a
  possible later change (the slot holds no work), not taken now because "release never resets work" is one rule.
- **Detached descendants** (`setsid`) of a check are unobservable (.4.4), as for setup.
- **Unbounded line buffer** in `stream_proc` (tl-8bh9.14.25) applies to check output too; it should land before M4.
- **Local `main` lag**: required names come from the person's local `main`; a person who has not pulled checks
  against older required names. Land (B6) re-reads them at the land base.
- **Flaky checks** fail the step with no rerun; only abandon (a new plan and implement) reruns them until repair exists.
- **A checks attempt holds a slot** for its whole block: with one slot, agents wait behind checks (claimed work first).
- **Schema discard** at the upgrade to v12: finish or abandon attempts first (the existing runbook).
- **`composition.py` near its cap** (section 14).

## 19. Not verified

- `run_registered`'s stop of a check's tree on its own timeout for a real `just test` (setup's real test covers a small
  command only).
- That `just check` and `just test` pass from a slot set up by `just bootstrap` with network and the scrubbed
  environment outside any sandbox (M1 ran them inside the sandbox, offline, and by hand outside it).
- That a check's `uv sync` inside `just test` with `UV_CACHE_DIR` in `.env/<slot>` and network leaves the slot clean
  (`.venv` is ignored; expected).
- Line estimates, from the counts at this tree.
