# tl-8bh9.14.6: the checks step (block B4, milestone M2)

Design, 2026-11-11, against HEAD f5ef43664 (M1 built, M1 smoke passed); revised the same day after an independent review
(section 20) against 4f1d14c2c (composition split). Docs only: nothing built or run. Read: CLAUDE.md,
[glossary](../../glossary.md), [roadmap](../self-hosting-roadmap.md) (B3, B4, B6, B7, D1-D14, O1-O6),
[candidate checks](../tl-8bh9.5.1/candidate-checks.md), [.15](../tl-8bh9.4.3.1.15/plan.md) section 5,
[.16](../tl-8bh9.4.3.1.16/plan.md) sections 12-15, [S5e](../tl-8bh9.4.3.1.16.2/plan.md) and the
[M1 smoke findings](../tl-8bh9.4.3.1.16.2/m1-smoke-findings.md), [profile reader](../tl-8bh9.14.1/plan.md), and
`steps`, `environment`, `setup_store`, `slot_env`, `factory_schema` (v11), `attempt`, `attempt_status`, `round`,
`operations`, `slot_release`, `publish`, `launch`, `attempt_entry`, `claim_lease`, `prepare`, `admit`, `admit_chain`,
`agent_credentials`, `composition`, `step_render`, `tests/rules/test_policy.py`, and the installed `stream_proc` and
`git_porcelain`.

The owner is away and asked for autonomous decisions. Every decision below is marked **decided here** (recommendation,
open to veto); owner decisions D1-D14 are cited by number. Section 13 lists blocking owner questions: none.

## 1. What changes for the owner

After an implement attempt is verified and published at X, the next round advances the task to a **check** step: it
reserves a free slot, checks X out detached, resets the slot to exactly X and runs the profile's `setup` at X, then runs
every check of `.task-loop.json` at X on the host (normal networking, the agent's scrubbed environment and push bar,
D9/D10), one after another, each with its timeout. Each check's output is an evidence file; each result is a row in
factory.db. The step concludes `passed` only when every check named in `required` by the profile at `main` passed on X;
otherwise `failed` with a reason. Every way a checks attempt can end is a conclusion with its slot released, never an
attempt left relaunching. `tl step show` prints one `Check:` line per check (conclusion, exit, duration, output path) and
the step's result; `tl step list` shows the step `check`. A failed check leaves the task `done` with a visible failed
result and its claim kept (M2; holds are B7); `tl step start` on it re-runs the checks on the same X without a new plan
or implement. Nothing is merged, landed, pushed or committed by this step.

## 2. Decisions this design respects

D1 (any plain file, so a task may change its own profile, `justfile` and `setup`), D2 (bare static analysis always
runs: here `check` is required at `main`), D3 (no label check on an advance), D4 (an abandon restarts at plan), D6, D9
(normal host networking for checks; one mandatory check set, no pass cache), D10 (checks on the host, before any
review, scrubbed environment and push bar, no scratch HOME), D11 (commands from the profile at X, required names from
the target), D12 (`setup` from the same ref as the checks, run by the factory with network), D14 (factory folders
beside the slots). Candidate checks: a failure is a result, never a pass; no reuse across candidates; an interrupted
block repeats after a stop proof, a completed one is not run again; a check that changes tracked files invalidates the
candidate.

## 3. A step with its own tables, not a step kind (decided here)

The checks step has no agent, input, answer, session, commit, verifier or publication, so it is not a `StepKind`
(`steps.STEPS` stays `(PLAN, IMPLEMENT)`; `kind("check")` stays an error) and its attempt is not an `attempt` row: six
NOT NULL `attempt` columns are agent facts (input path and digest, schema version, model, effort, sandbox) and the
`execution`/`verification`/`published_branch` chain hangs off it; making them nullable would put `step == "check"`
branches into admission, the entry, capture, verify, repeat, publish and release (.15 section 5). Instead:

- **Own tables** `checks_attempt` (the step's attempt) and `check_result` (one check's result in one block), section 4.
- **Shared by reuse, not by copy:** the `reservation` and `slot` rows (`admit.reserve`), slot custody
  (`slot_lock.custody`), the launcher (generalized over its target table), the boot-aware stop proof
  (`slot_release.entry_stopped`, `setup_store.SetupSeen`), the park (`slot_release` extracts its slot read and park as a
  function), the environment preparation (`environment.Preparation`, sandbox probe off), the capped evidence log, the
  registered start (`stream_proc.run_registered` through the `SetupProcess` port), the claim keep-alive (`claim_lease`),
  and the `Next`, `rounds.log` and `tl step` words.
- **Sequencing:** a module constant `steps.ORDER = ("plan", "implement", "check")`; `following(step)` reads it (no longer
  through `kind`), so `following("implement") == "check"`. `next_step` returns `"check"` after a done implement attempt;
  `NextAdmission._previous` refuses `not_advanceable` unless the next step is a `StepKind` step (`steps.is_agent`), so
  `admit_next` never reaches `task_text` and `kind("check")`. `Next: advance` keeps its one meaning;
  `operations._admit` sends an advance whose next step is `check` to the checks admission.
- **Words:** the step is `check` (`Step: check`, `rounds.log` `<task> check advance started`). The attempt is a
  **checks attempt** (`checks_attempt`). The glossary's "attempt of an individual check" is a `check_result` row,
  identified by (checks attempt, block, name); no extra noun.
- **B6 reuse:** `checks.Block` takes a `BlockTarget` (slot, its pinned view, commit, required list, deadline,
  environment) and a `ResultSink` port (`start`, `registered`, `conclude`, `undefined`); `CheckStore` is the sink for
  checks attempts. Land (B6) validates a new merge candidate with the same `Block` and its own record, so the shared
  validation operation is not tied to `checks_attempt` rows (candidate checks: one shared validation operation).

## 4. Schema v12 (no migration; v11 is refused `schema`)

```sql
CREATE TABLE checks_attempt (
 attempt_id TEXT PRIMARY KEY, dispatch_token TEXT NOT NULL UNIQUE, generation INTEGER NOT NULL,
 after_attempt_id TEXT NOT NULL REFERENCES attempt(attempt_id),  -- the done implement attempt
 number INTEGER NOT NULL CHECK(number >= 1),                     -- 1 for the advance, +1 for each re-run of the same X
 slot TEXT NOT NULL,
 slot_head TEXT NOT NULL CHECK(length(slot_head) IN (40,64)),           -- D: the free slot's HEAD; the release parks here
 target_commit TEXT NOT NULL CHECK(length(target_commit) IN (40,64)),   -- the target: `main` when the required names were read
 target_seen TEXT CHECK(target_seen IS NULL OR length(target_seen) IN (40,64)),  -- `main` when found moved (main_moved)
 required TEXT NOT NULL,              -- JSON [[name, argv digest of that name at the target], ...] in the target's `required` order, 1..32
 profile_digest TEXT CHECK(profile_digest IS NULL OR length(profile_digest)=64),  -- sha256 of `.task-loop.json` at X; set once
 deadline REAL NOT NULL, entry_pid INTEGER, entry_start TEXT, entry_boot TEXT,
 phase TEXT NOT NULL DEFAULT 'admitted' CHECK(phase IN ('admitted','concluded')),
 rev INTEGER NOT NULL DEFAULT 0,
 refusal TEXT, refusals INTEGER NOT NULL DEFAULT 0 CHECK(refusals >= 0),  -- the last relaunchable refusal, how often in a row
 conclusion TEXT CHECK(conclusion IN ('passed','failed')), reason TEXT, concluded_at REAL,
 released_at REAL, parked TEXT CHECK(parked IS NULL OR length(parked) IN (40,64)),
 abandoned INTEGER NOT NULL DEFAULT 0 CHECK(abandoned IN (0,1)),
 CHECK((phase='concluded') = (conclusion IS NOT NULL)), CHECK((conclusion IS NULL) = (concluded_at IS NULL)),
 CHECK((conclusion='failed') = (reason IS NOT NULL)), CHECK((released_at IS NULL) = (parked IS NULL)),
 CHECK(abandoned=0 OR released_at IS NOT NULL), CHECK(abandoned=1 OR released_at IS NULL OR phase='concluded'),
 CHECK((refusal IS NULL) = (refusals = 0)),
 CHECK((entry_pid IS NULL) = (entry_start IS NULL) AND (entry_pid IS NULL) = (entry_boot IS NULL)),  -- S6a repair
 UNIQUE (after_attempt_id, number)
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
 CHECK((pid IS NULL) = (pgid IS NULL) AND (pid IS NULL) = (proc_start IS NULL) AND (pid IS NULL) = (boot IS NULL)),  -- S6a repair
 CHECK(conclusion IS NOT 'undefined' OR (pid IS NULL AND rc IS NULL)), CHECK(rc IS NULL OR conclusion IS NOT NULL),
 PRIMARY KEY (attempt_id, block, position), UNIQUE (attempt_id, block, name)
);
```

`setup_run` loses `REFERENCES attempt(attempt_id)`: its `attempt_id` names an `attempt` or a `checks_attempt` (both
uuid4 hex). `setup_store.HELD` becomes the union of today's fence and the same fence on `checks_attempt`
(`phase='admitted'`, the reservation held at the key's generation). Nothing else in v11 changes.

**No copied columns (decided here).** The task (`adapter`, `backlog`, `task_id`), `tracker_root`, `repo_id` and X are
the implement attempt's: every read joins `attempt a ON a.attempt_id = c.after_attempt_id` (X is `a.end_commit`; the
reservation fence matches `r.repo_id = a.repo_id AND r.slot = c.slot AND r.attempt_id = c.attempt_id AND r.generation =
c.generation`). A checks attempt's slot and D are its own. `profile_digest` is written once by the first block and never
compared (X is immutable, so a second digest cannot differ; no refusal word for it).

**What the rows mean.** The phase is only `admitted` (setup and blocks run; there is no once-only agent, so no
`dispatching`/`registered`) and `concluded`. "Current" is the highest `number` of one implement attempt; "latest block"
the highest `block` of one checks attempt; the conclusion reads only that block. X, the target, the required list and the profile
digest are facts of the attempt, never copied into each result: a result always travels joined with them and carries
its own argv digest. `timed_out` is the conclusion `timed_out`; the exit is `rc`; the duration is `ended_at -
started_at`. The output is a file (section 7), never a column. `check_store.LIVE_AFTER = ("lingering", "timed_out",
"interrupted")`: a row unfinished or so concluded names a command whose group must be proven empty before the slot is
reset, set up, relaunched or released.

**The not-current rule (review finding 1).** `factory_schema.SUCCESSOR` replaces `LATER` in `slot_release`'s `ROW`
(`successor`), `FENCE` and `FLIP`: an attempt `p` is not current when `LATER` holds or its latest checks attempt is
not abandoned:

```sql
(<LATER> OR EXISTS (SELECT 1 FROM checks_attempt c WHERE c.after_attempt_id=p.attempt_id AND c.abandoned=0
 AND c.number=(SELECT max(d.number) FROM checks_attempt d WHERE d.after_attempt_id=p.attempt_id)))
```

So an abandon of the implement attempt after a checks attempt was admitted refuses `changed`, and the task's abandon
goes checks first (section 10). `publish`'s fence keeps `LATER`: publication precedes any checks attempt (admission
requires the published row) and pushes nothing afterwards. `admit_chain` keeps `LATER` (no agent step follows checks).

**Writers** (`test_policy.WRITERS`): `CREATE TABLE checks_attempt`, `check_result` by `factory_schema.py`; `INSERT` and
`UPDATE` of `checks_attempt` and of `check_result` by the new `check_store.py` (the admission's insert is a
`check_store` function called inside the admission's transaction; `INSERT reservation` and `UPDATE slot` stay `admit.py`'s
through `admit.reserve`; `DELETE FROM reservation` stays `slot_release.py`'s through an extracted `free(con, ...)`).
`GIT_WRITES` gains `reset`, owned by `environment.py` (section 8).

**What else batches into v12 (decided here): nothing.** B6 (land record and actions) and B7 (holds) have no design yet;
guessed tables now would be unused speculative schema (CLAUDE.md). If either design is settled before S6a is built, its
DDL joins v12 so the owner discards once; otherwise each brings its own discard. B7 as roadmapped (a tracker comment,
the label removed, the claim returned through the existing abandon) may need no table at all.

## 5. Admission: like an advance, or a re-run (`check_admit.py`, new)

`ChecksAdmission.admit_checks(ChecksRequest(previous: AttemptKey, checkout, deadline))`, called by `operations._admit`
for an advance whose next step is `check`, and for a re-run (`tl step start` on a done, failed checks attempt; the
round never re-runs). Order, every read before any effect:

1. Choices and the deadline (`admit.deadline_refusal`).
2. The implement attempt (`admit_chain`'s `_task_of` and done-ness reads, shared): not superseded by `LATER`, step
   `implement`, verified, released `kept`, published at its `end_commit` (else `not_advanceable`). Its checks attempts:
   none (an advance, `number` 1), or the latest concluded `failed`, released and not abandoned (a re-run, `number` + 1);
   a latest one abandoned (the task's abandon is half done) is `not_advanceable`; any other latest one is
   `task_attempted`. The checkout's repository is the attempt's (`checkout`).
3. X still on the task's branch: the local `task/<id>`, else the remote-tracking one, contains X (`prepare.lacks`), else
   `branch_moved`; X readable, else `commit_missing`. The checks run on X itself, not the tip.
4. **The required names (O1, decided here):** `refs/heads/main` of the repository resolves to the target (else `refused target`);
   `profile.read_profile(files, target)` through the checkout's view (`Refused`: `refused target_profile` with B3's reason in
   the detail; `Unavailable`: `unavailable git`); its `target` must be `main` (another land branch is B6's, `refused
   target`); its `required` must be non-empty (`refused no_required`: nothing required would conclude `passed`
   vacuously). The list stored is each required name with the argv digest of that name's check at the target.
5. Free slots (`admit.free_slots`). No branch rule: the slot takes X detached, never `task/<id>`.
6. One tracker read (`admit.read_task`): `claim_lost` unless `in_progress` for `taskloop`; no label (D3).
7. One write transaction re-reading 2 and an unheld slot: `admit.reserve`, then `check_store.insert` (D = the slot's
   HEAD, the target, required, deadline, the number). A lost race on `(after_attempt_id, number)` is `task_attempted`; the caller
   then reads the winner through `check_store.attempt_of` and launches it with the checks launcher (never the agent's
   `attempt_of`). No claim call, no input file.

In the round, a refusal is a skip of the done implement attempt except `no_free_slot` and the existing `ADVANCE_STOPS`.
`target`, `target_profile` and `no_required` are about `main`: every done task skips with the same word until the person
fixes `main`; `quiet` writes each line once.

**The wait for a slot.** Between the implement release and the checks admission nothing renews the claim's lease (bd's
300 s TTL, `claim_lease`). Admission confirms `in_progress` for `taskloop`; the entry renews before the block (section
6, step 3). A claim another actor took meanwhile ends the checks attempt `failed claim_lost`.

## 6. The checks entry (`check_entry.py`, new)

`python -I -m taskloop.check_entry DB ARTIFACTS BACKLOG TASK`, launched through `launch.Launcher` (generalized: an
`EntryTargets` port with `attempt_of` and `register_entry`, implemented by `AttemptStore` and `CheckStore`, and the
entry module name). `CheckStore.register_entry` is `AttemptStore`'s rule (one winner while `admitted`, the renewal once
per reboot) with one difference (decided here): it does not refuse a passed deadline, because a checks entry past its
deadline runs nothing and only concludes `failed expired` and releases; otherwise an expired checks attempt could never
be launched to end itself. Its stdout and stderr are the checks attempt's `entry.log`.

**Process facts (verified from the installed code).** `stream_proc.run_registered` calls `popen_registered`, whose
`start_new_session` defaults to True and is not overridden: each check command is its own session and process group
(pgid = its pid), so it outlives a killed entry and the reconcile must prove it gone. `run_registered` returns
`survivors` (pids of the tree alive after its own stop); `slot_env.setup_process` drops them today. Git:
`git_porcelain` parses `worktree list --porcelain`, giving `WorktreeInfo.branch = None` for a `detached` record (and
the fake reports `(detached)` as None too), so "HEAD X, detached" is `(head, branch) == (X, None)`.

Order (each "concludes" below writes the conclusion and goes to step 13):

1. factory.db exists (never created); the task's current checks attempt; this process is its registered entry
   (`refused identity` otherwise), as `attempt_entry._registered`.
2. Slot custody, never waiting (`refused slot_busy`), held to the end.
3. The claim keep-alive (`claim_lease.keeping` at the implement attempt's tracker root) starts, and one renewal now
   (`attempt_entry.renewal`): `lost` concludes `claim_lost`, after step 4's reconcile (no slot access) has marked the
   gone unfinished results `interrupted` (S6c review). The keep-alive thread renews every 100 s while setup and
   the block run, between checks included; a claim lost later is recorded (`claim=`) and the results stand.
4. **Reconcile, before any slot read or write**: the latest setup run's unsettled command (`setup_store.running`) and
   every unsettled row of the latest block (`check_store.unsettled`: no conclusion, or `LIVE_AFTER`), each through
   `setup_seen` (another boot is gone): alive is `unavailable checks:running`, unknown `unavailable checks:unknown`,
   never signalled; gone (or never registered) rows with no conclusion become `interrupted`. A live orphan that dirtied
   the slot therefore says `checks:running`, never `slot_dirty`.
5. Past the deadline: concludes `expired` (step 4 proved nothing of the attempt still runs).
6. **The profile at X** (`read_profile` through `slot_profiles` on the slot's pinned view): `Refused` concludes
   `profile:<reason>` (X's own profile is the candidate's); `Unavailable` is `unavailable git`. The first block writes
   the profile digest.
7. **`main` still the target**: `refs/heads/main` read now on the slot's pinned view; another commit concludes
   `main_moved` (and stores it as `target_seen`). Read before step 8 (S6c review): a candidate that moved `main` and then
   killed its entry must not pass on the relaunch.
8. **A completed latest block is not run again** (candidate checks: "if the whole checks block completed, continue"):
   when the latest block has a terminal row (`passed`, `failed`, `timed_out`, `undefined`) for every check at X and
   every undefined required name, or a row that stops a block (`lingering`, `dirty`), the conclusion is computed from it
   (step 12) and nothing runs. An `interrupted` row or a missing name means the block repeats whole.
9. **Take X** (`prepare.detach_at`, new in `prepare.py`): through `observe_slot` and the pinned view, a clean slot
   detached at D is parked at X (`Worktree.park(X)`) and re-read (`(head, branch) == (X, None)`); a slot already detached
   at X passes in any state (step 10's reset makes it exactly X). On a branch concludes `slot:branch`; a redirected
   pointer concludes `slot:redirected`; X gone concludes `commit_missing`; a slot at another detached commit with
   changes is `refused slot_dirty` (relaunchable: a free slot is clean at admission).
10. **The environment**: `Preparation.prepare_for(SetupFor(key, slot, commit=X, branch=None, deadline, first=True),
    prepared, renew, env=scrubbed, probe=None)` (section 8): reset to exactly X, then `setup` at X. Its words map by
    section 6.1's table.
11. **The block** (`checks.Block.run`, section 7), then `main` read again: moved concludes `main_moved`.
12. **The conclusion**: `passed` when, in the latest block, every stored required name has a result `passed`; else
    `failed` with the reason of the first required name (the target's order) that did not pass: `<name>:<conclusion>`, or
    `<name>:not_run` when the block stopped before it; a stopping `dirty` or `lingering` row of a non-required check is
    the reason itself. Written once, fenced (`check_store.conclude`, which also clears `refusal`).
13. **Release** of its own slot under the lock it holds (`ChecksRelease.release(key, abandon=False, me)`, section 10),
    then the scratch `.t/<slot>` emptied. A release held (`lingering`, `slot_redirected`) leaves `Next: release`.
14. One log line of fixed words: `collected passed|failed:<reason>` or the refusal, then `claim=`, `release=`. Exit 0
    only for `passed`.

### 6.1 Refusals: conclude, or relaunch and count (review finding 3; decided here)

A condition the candidate caused, or one that a relaunch cannot clear, **concludes** the checks attempt `failed` with a
reason and releases its slot; a transient or unknown one leaves it `admitted` for a relaunch and is **counted**:
`check_store.refused(key, word)` adds one for every relaunch whatever its word and keeps the word in `refusal` for display
only (S6c review: two words alternating, such as `environment:uncertain` then `checks:running`, must not relaunch forever);
only the conclusion clears it, so a block that repeats after a refusal inside it keeps counting.
Two in a row make `Next` `stuck:checks_refused`: rounds stop relaunching it, as `stuck:setup_failed` does; `tl step start` relaunches it by hand.

| Concludes `failed` with reason | Relaunch, counted |
|---|---|
| `claim_lost`; `expired` (before the block) and `expired:<check>` (mid-block); `main_moved`; `commit_missing`; `slot:branch`; `slot:redirected`; `profile:<reason>`; `setup:<conclusion>` (two failed setup runs, `SETUP_RUNS`); `environment:<word>` for `platform`, `path_long`, `roots`, `remove_unsafe`, `reset`, `profile`, `moved`, `dirty`; `<name>:lingering`, `<name>:dirty`, `<name>:<conclusion>` from the block | `unavailable` `store`, `git`, `checks:running`, `checks:unknown`, `checks:uncertain`, `environment:files`, `environment:exit` (one failed setup run), `environment:lingering`, `environment:running`, `environment:unknown`, `environment:uncertain`; `refused slot_busy`, `slot_dirty`; any other fault
once the attempt is the entry's own, `unavailable fault:<type>` (S6c review) |

A concluded checks attempt is re-run with `tl step start` (section 5): cheap, no new plan or implement, the earlier
attempt kept as history (`Earlier:`).

## 7. The block (`checks.py`, new)

One block runs every check of the profile at X in profile order, each once, required or not (decided here: D9's one
mandatory set; a non-required result is shown and never decides; a task adding a check runs no code `setup` could not
already run). Before the first command, each stored required name the profile at X does not define gets a result
`undefined` (no process, no argv digest): a required check that never reports blocks, as on GitHub. The M2 smoke's
`failed:offline-only:undefined` (a name `main` required that X's profile lacked) is this rule as designed; its cause, X
cut from a stale slot instead of `main`, is fixed by [.15 section 17](../tl-8bh9.4.3.1.15/plan.md).

Per check, `name`, `argv`, `timeout` from the profile at X:

1. `sink.start(block, position, name, argv_digest, timeout)` (argv digest: sha256 of the argv as compact JSON,
   `environment.setup_digest`'s rule on one argv).
2. The log `attempts/<hash>/check-<block>-<name>.log` (0600, append, 32 MiB then one `[truncated]` line: S5e's
   `SetupLog`, renamed `CappedLog`), framed by the factory's lines `$ <shlex.join(argv)>` and the ending (`exit <rc>`,
   `timed out`, `stopped at the deadline`, `not started`, `ended by a signal`, `start uncertain`, `lingering`, `dirty`,
   and `untracked: <path>` lines, at most 50, then a count). Check names are B3's `[A-Za-z0-9._-]` not starting with
   `.` or `-`, so the file name needs no escaping.
3. The registered start (`SetupProcess`, real `run_registered`): the `registered` callback commits the identity
   (`sink.registered`, the bounded registration connection) before the command executes; cwd the slot; stdin empty,
   stderr merged; environment `environment.setup_env(scrubbed, folders(slot))`: the scrubbed environment and push bar,
   `TMPDIR` = `.t/<slot>`, `UV_CACHE_DIR`, `UV_TOOL_DIR`, no `UV_OFFLINE`, the person's `HOME` (D10); wall timeout
   `min(timeout, deadline - now)`. `SetupEnded` gains `survivors: bool` (`bool(Result.survivors)`), for setup too.
4. **After every end, whatever it was** (exit, its own timeout, the deadline): the group check (`lingering(pgid)`) or
   `survivors` means a process is left: the result is `lingering`, the block stops, the attempt concludes `failed
   <name>:lingering`, and the release waits for the group (`held:check_running`).
5. **Then the slot, after every check that ran** (exit 0, non-zero, own timeout or deadline), through the pinned view:
   `(head, branch)` must be `(X, None)` and no tracked file changed (staged or unstaged; decided here, review finding 4:
   untracked non-ignored files are not `dirty`; they are listed in the log and the next block's reset removes them).
   Otherwise the result is `dirty`, the block stops, the attempt concludes `failed <name>:dirty`.
6. Else, in this order: start uncertain is `unavailable checks:uncertain` (the identity is stored; the next entry
   reconciles it); stopped by the attempt's deadline is `interrupted` and concludes `expired:<name>`; stopped by its
   own timeout is `timed_out` (the block continues); exec failed or exit not 0 is `failed` (continues); exit 0 is
   `passed`.

A **pass** (glossary) is exactly: a `check_result` row concluded `passed` in its checks attempt's latest block, whose
attempt names X (through its implement attempt), the profile digest at X and the argv digest. It is never looked up for
another X, another checks attempt or another task: nothing reads results except the status of their own attempt (and
later land, for the same X).

## 8. Environment: S5e's machinery, reused

`Preparation.prepare(record, ...)` stays the implement path; both paths call one `prepare_for(target: SetupFor, slot:
Prepared, renew, env, *, probe: Launch | None)` where `SetupFor(key, slot_path, commit: str | None, branch: str | None,
deadline, first: bool)`; `probe` is the agent's Codex and environment for the sandbox probe, None for no probe. For
checks: `branch=None` (S5e section 4 step 8 then expects `(X, None)`), `probe=None` (no sandbox; the platform,
`path_long`, roots and removal checks stay, so checks inherit `environment:platform` off Linux, where implement never ran
anyway), and **no reuse** of a passed setup (decided here): a block that ran task code on the host may have left anything
in ignored files or the uv folders.

**Reset to exactly X (decided here, review finding 4).** A checks slot never holds work, so with `commit` set the reset
is `Worktree.reset(X, mode="hard")` (tracked files back to X, so a check killed mid-rewrite cannot poison the next
block), then S5e's `clean(ignored=True, nested=True)` (untracked and ignored files, nested repositories), an empty
ignored listing and `.env/<slot>` emptied. `reset` joins `test_policy.GIT_WRITES`, owned by `environment.py` like
`clean`. The implement path (`commit=None`) is unchanged: it never resets tracked files, because its slot holds the
task branch.

**The scrubbed environment without Codex**: `agent_credentials.codex_machine_credentials` is split into
`scrubbed(environ)` (the scrub, the venv drop, the push bar) and the Codex lookup; the checks entry uses `scrubbed` only,
so a checks attempt needs no `codex` on `PATH`. It does not hide Codex's login: section 12.

## 9. Status, `Next`, the round and `rounds.log`

`attempt_status`: for a task whose current agent attempt is a done implement attempt with its release claim `kept`,
`check_store.of_attempt` reads its latest checks attempt into `ChecksView`, and `AttemptView` gains `checks:
ChecksView | None`. When it is set, these view fields are the checks attempt's (review finding 7): `step` (`check`),
`attempt_id`, `slot`, `phase`, `entry`, `entry_process`, `worker` (None), `deadline_passed`, `next`, `number`,
`last_entry`, `result` (`collected passed`, `collected failed:<reason>`, or `pending admitted`), and `release` (a
`ReleaseRow` of its `released_at`, `parked`, the implement attempt's claim, and `abandoned`); `leftovers`,
`previous_attempt_id` and `repeat_reason` are empty. Kept from the implement attempt: `backlog`, `task_id`, `seq`,
`published` (X on origin); `earlier` gains `(<implement id>, advanced)` and each earlier checks attempt of the same
implement attempt (`re-run`). `attempt.succeeded` also accepts `collected passed`, so `round._settle`'s `done if
succeeded(...)` stays silent for a passed check and reports a failed one; `each.release.abandoned` reads the checks
attempt's flag. Once the implement attempt's abandon has finished (claim not `kept`) the view is the implement
attempt's again (`start`, abandoned: skipped by the round, a fresh plan by `tl step start`).

| Latest checks attempt | `Next` |
|---|---|
| none (implement done) | `advance` (`following("implement")` is `check`) |
| `admitted`, entry running | `wait`; past the deadline `stuck:hung` |
| `admitted`, entry none, gone or another process, `refusals` >= 2 | `stuck:checks_refused` |
| `admitted`, entry none, gone or another process | `start` (a relaunch; past the deadline the entry concludes `expired`) |
| entry unknown, or a store read fails | `unknown` |
| `concluded`, not released | `release` |
| released by an abandon (implement claim still `kept` or `unclaiming`) | `release` (rerun `tl step release --abandon`) |
| released, `passed` or `failed` | `done` |

`operations`: `_current` reads the latest checks attempt of a done implement attempt first: `admitted` is launched with
the checks launcher; `done` and `passed` is `already_dispatched` with its result; `done` and `failed` is a re-run
(section 5); released by an abandon is `refused release` (the abandon's rerun), never a launch of that attempt or of a
racing winner. `start` sets `Started.step` itself for a checks attempt (`reader.step_of` reads `attempt` and would give
None for a checks id). The round needs no new phase: the advance phase admits and launches checks attempts (claimed work
first, FIFO by the implement release time); settle relaunches `start`, reports `wait`, `release`, `stuck:*`; `_resume`
sends a checks attempt to the checks launcher; it never re-runs a failed one. `rounds.log` lines, fixed words:

```
<time> <backlog> tl-1 check advance started <checks attempt>
<time> <backlog> tl-1 implement skip no_required <implement attempt>
<time> <backlog> tl-1 check report running <checks attempt>
<time> <backlog> tl-1 check relaunch relaunched <checks attempt>
<time> <backlog> tl-1 check report failed:test:failed <checks attempt>
<time> <backlog> tl-1 check report stuck:checks_refused <checks attempt>
```

`check report running` appears while a block runs (settle reports `wait`, as for an agent); `done` and `passed` writes
nothing; `done` and `failed` is reported once (`quiet`).

**`tl step show`** for a checks attempt (human; JSON key `checks` with the same facts, `results` a list):

```
Task: tl-1 (backlog m2)
Step: check
Attempt: <id> (run 1)
Earlier: <implement id> advanced
Slot: s1
Phase: concluded
Entry: gone (pid 4242, started ...)
Commit: <X>
Required: check, test (main at <target>)
Profile: <digest> at X
Setup: run 1 passed at <X>; log <dir>/setup-1.log
Check: check passed, exit 0, 41 s; log <dir>/check-1-check.log
Check: test failed, exit 1, 312 s; log <dir>/check-1-test.log (argv differs from main)
Check: smoke undefined (required by main, not defined at X)
Result: collected failed:test:failed
Succeeded: no
Released: 2026-11-12 10:00:00 UTC, slot parked at <D>; claim kept
Next: done
```

A moved `main` adds `Main: moved from <target> to <target_seen>`; a counted refusal adds `Refused: <word> (<n> in a row)`.
`(argv differs from main)` marks a required check whose argv digest at X differs from the one stored from the target (decided
here: the cheapest visible signal of a task changing a required command); `(not required)` marks the others.
`tl step list`: step `check`, the checks attempt's slot, phase, entry, result and `Next`; `--stuck` includes its
`stuck:*` and `unknown`. `tl step verify` and `tl step publish` act on the agent attempt only. `STEP_ONLY` names `plan,
implement, check`. GUIDE gains `no_required`, `target`, `target_profile`, `commit_missing`, `main_moved`, `checks`
(for `checks:running|unknown|uncertain`), `checks_refused` and `check_running`, each one sentence on what the person does.

## 10. Release, abandon, re-run, publish, D4

`check_release.py` (new), `ChecksRelease.release(key, abandon, me)`, the same shape as `SlotRelease`:

- **Settled** (`tl step release TASK`, and the entry itself): the attempt `concluded` (else `refused not_terminal`).
- **Stop proof, both modes**: the registered entry (`entry_stopped`, `me` passes), the latest setup run's unsettled
  command (`setup_store.running`) and every unsettled row of the latest block (`check_store.unsettled`), each through
  `setup_seen`: alive `held:setup_running` / `held:check_running`, unknown `unavailable setup_unknown` /
  `check_unknown`. Never signalled; the guide lists the group's members and their cwd for the person.
- **Reset before the park (review of S6b, decided here):** after the stop proof and under the lock, a slot listed
  detached at X through its pinned view is reset to exactly X (`reset --hard X`, then `clean -ffdx`, one `environment`
  function, so `reset` and `clean` keep their one owner, `environment.py`, in `test_policy.GIT_WRITES`). Otherwise the
  untracked leftovers of a passed block (`coverage.xml`, `junit.xml`, `build/` not ignored by the repository) would make
  `park_slot` refuse `held:slot_dirty` and wedge the slot after every block. A slot not detached at X is not reset (an
  attached HEAD would carry its branch): the park's own refusal stands.
- Then the lock, the slot read and the park at D (the extracted `slot_release.park_slot`: detached at X and clean is
  parked at D; `held:slot_dirty` when not clean), one transaction fenced on `rev`, `phase`, the held reservation and no
  release (`check_store.record_release` with `abandoned`, `slot_release.free`), then the scratch emptied, best effort.
- **Abandon of an already released checks attempt** flips `abandoned` 0 to 1 in one fenced update (the latest checks
  attempt, not abandoned).

**The task's abandon** (`tl step release --abandon TASK` while its current step is check), in this order:
`ChecksRelease.release(latest checks key, abandon=True)`, then the existing `SlotRelease.release(implement key,
abandon=True)`, whose `FLIP` now passes because `SUCCESSOR` no longer sees an unabandoned latest checks attempt. A
failure between the two shows `Next: release`; rerunning `--abandon` finishes (the first part answers
`already_released`). **The race with a checks admission** (both orders, each tested): the admission commits first, so
the implement attempt's abandon (the person called it on a stale view, or `release_task` read before the admission)
meets `SUCCESSOR` in `ROW`, `FENCE` or `FLIP` and refuses `changed`, and the person reruns `--abandon`, now checks first;
or the abandon's `FLIP` commits first, so the admission's re-read sees the release `unclaiming` and refuses
`not_advanceable`. In the half-done state (latest checks attempt abandoned, implement claim `kept`), `tl step start` and
the round refuse `release`, admission refuses `not_advanceable`, and nothing launches.

**D4 and re-runs.** An abandon gives the claim back and the next start is a fresh plan (D4); the old checks attempts hang
off an abandoned implement attempt and are never current again. A re-run is not an abandon: same claim, same implement
attempt and X, a new checks attempt (`number` + 1) with a new target. **Publish**: the checks step pushes and commits nothing;
it requires the implement attempt published at X and runs on X itself. **Across candidates**: a new implement attempt
has its own X and its own checks attempts; nothing is carried. The same X checked in a new workflow runs again (D9).

## 11. The failed-checks route (O2; decided here for M2)

M2 holds nothing: a failed checks attempt is `done` with `Result: collected failed:<reason>`, `Succeeded: no`, the claim
kept (`in_progress` for `taskloop`), the slot released, and one `check report failed:<reason>` line. The person reads the
`Check:` lines and logs, then re-runs (`tl step start`, for a flaky or environment failure), fixes by hand on `task/<id>`
and lands by hand (M2 is still hand land), or abandons (D4: plan, then implement on the current branch, then checks on
the new X). **Recommendation for B7 (M4):** a failed checks attempt, and `stuck:checks_refused`, are hold reasons:
comment the reason and the failing log paths on the task, remove `auto`, return the claim (O5). Automatic repair (back to
implement with the output, tl-7i9k.56.1) stays later (O2's recommendation unchanged).

## 12. Security (D10 accepted) and what land must show later

The candidate's code runs on the host before anyone reads it, twice per block (`setup`, then every check), with network
and the person's `HOME`. Accepted residuals (D10, S5e Q3), stated precisely: SSH keys, `~/.netrc`, Git credential
helpers **and Codex's own login** (`~/.codex/auth.json`, or `$CODEX_HOME/auth.json`: `CODEX_HOME` is not scrubbed) are
readable; the push bar is only an environment entry the code can unset. Splitting out `scrubbed` keeps Codex's
executable path out of the checks' setup; it hides no file. Kept: the scrub of credential variables, the push bar, the
factory folders outside the slot, the slot's lock, the pinned Git views, the stop proof before any reset and release.

**O1 (decided here).** Required names are read from the local `refs/heads/main` (the person's; the factory never writes
it). This protects only against non-hostile task edits: task code already runs on the host and could rewrite that ref.
Therefore: `main` is read before and after each block, and before a completed block is concluded on a relaunch; a
move concludes `failed main_moved` and is shown (`Main:` line); and B6 must re-read the required names from the remote target at land time and compare them with the stored target.

**The B6 land summary must list** (recorded here so B6's design starts from it):

1. The checks attempt for exactly the land candidate X (else the checks run again), its conclusion, the target, and each
   required name with its result.
2. The required names re-read from the remote target at land time, compared with the target's; any difference, or a new required
   name, reruns the checks (O1).
3. Each required check whose argv at X differs from the target's (stored digests), with both argv shown.
4. Checks the task added, removed or changed at X (non-required ones ran on the host too) and every changed `setup`.
5. Every changed check-configuration file between the target and X: `.task-loop.json`, `justfile`, `pyproject.toml`,
   `uv.lock`, `mise.toml`, `.importlinter`, `tests/rules/`, any `conftest.py`, and any file a check's argv names.

## 13. Owner questions

**Blocking: none.** Non-blocking, each built as decided unless vetoed:

1. **O1**: the local `main`, with the before/after read and B6's re-read from the remote (section 12).
2. **Empty `required` at `main`** refuses `no_required` rather than passing vacuously.
3. **Every check at X runs**, required or not; only required ones decide.
4. **Every terminal condition concludes `failed` with a reason**; transient refusals count to `stuck:checks_refused`
   after two in a row (section 6.1).
5. **Re-run by `tl step start`** of a failed checks attempt on the same X; the round never re-runs.
6. **`dirty` is tracked changes or a moved HEAD only**; each block resets the checks slot hard to X.
7. **O2 for M2**: failed is a visible `done`, no hold (section 11).

## 14. Slices (caps: 400 code lines per file, 80 per function, 800 per test file)

Code lines by the policy counter at 4f1d14c2c; current counts in brackets.

| Order | Slice | What | Source | Tests |
|---|---|---|---|---|
| 1 | **S6a schema, store, not-current rule** | v12 DDL and column lists; `check_store.py` (rows, `insert`, `of_attempt`, `attempt_of`, `register_entry` without the deadline refusal, `refused`, `profiled`, `block`, the sink writes, `undefined`, `conclude`, `record_release`, `abandon_released`, `results`, `unsettled`, `LIVE_AFTER`); `factory_schema.SUCCESSOR` and its use in `slot_release` `ROW`/`FENCE`/`FLIP`; `setup_store.HELD` union; `WRITERS` | `factory_schema` [109] +40, `check_store` new ~240, `setup_store` [97] +4, `slot_release` [263] +3 | `test_check_store.py` ~340; `test_setup_store` +30; `test_slot_release` +50 (implement abandon refused `changed` with an unabandoned checks attempt, passes once it is abandoned) |
| 2 | **S6b block and environment** | `checks.py` (`BlockTarget`, `ResultSink`, `Block.run`: undefined rows, each check, the after-end group check, the tracked-only clean read, the completed-block reading, the conclusion); `environment.prepare_for`, `SetupFor`, `commit` reset, `probe` None, no reuse [229] +30; `SetupEnded.survivors` in `slot_env` [96] +2 and setup's judgment; `prepare.detach_at` [125] +28; `evidence_files.check_log`, `CappedLog` [107] +10; `agent_credentials.scrubbed` [65] +6; `GIT_WRITES` `reset` | `checks` new ~230 | `test_checks.py` ~480; `test_environment` +80; `test_prepare` +60; `real/test_checks_real.py` ~100 |
| 3 | **S6c entry, launcher, release** | `check_entry.py` (section 6 with 6.1's table); `launch.EntryTargets` [150] +14; `slot_release.park_slot`, `free` +8; `check_release.py` (the reset to X before the park, section 10, through `environment`'s reset function: `reset`/`clean` stay `environment.py`'s in `GIT_WRITES`); composition wiring of the entry, release and launcher [100] +35; import contracts (`check_entry`, `checks`, `check_release` join the entry's closure; `check_entry` joins `cli-never-imports`) | `check_entry` new ~210, `check_release` new ~135 | `test_check_entry.py` ~420; `test_check_release.py` ~280; `test_launch` +40 |
| 4 | **S6d admission and `tl step`** | `check_admit.py` (section 5, advance and re-run); `steps.ORDER`, `following`, `is_agent` [46] +8; `admit_chain._previous` refusal [261] +3; `attempt.succeeded` +1; `operations` routing (`_current`, re-run, `Started.step`, the `task_attempted` winner through the checks launcher, release and abandon order) [276] +55; `attempt_status` `ChecksView`, the field swap and the `Next` table [154] +70; `step_render` [138] +45, `result_data` [108] +22, `step_guide` [133] +18; `cli_composition` [208] +25 | `check_admit` new ~140 | `test_check_admit.py` ~360; `test_operations` +120 (both race orders, the half-done abandon, re-run); `test_step_cli` +150 |
| 5 | **S6e round and words** | `round._settle`/`_resume` routing for checks attempts [240] +20; glossary (section 15); roadmap B4 row; the live smoke file | +20 | `test_checks_round.py` ~380; `test_round` +40 |

Total about +1,480 source and +3,000 test lines (S5e-1 alone was +408/+567). Largest new functions: `Block.run` split
into undefined rows, one check, the judgment and the conclusion (each under 45); the entry's `enter` about 60 (split
before 80). After the slices the largest touched files are `operations` (~331), `slot_release` (~274), `admit_chain`
(~264) and `round` (~260); `composition` stays near 135 after tl-8bh9.14.20.

Dependencies: S6a, then S6b, S6c, S6d, S6e in order (each needs the previous one's types; S6d's admission writes rows
only S6c's entry runs). Each slice lands green with `just check` and `just test`, independently reviewed. The live smoke
(section 17) follows S6e; M2 is reached when it passes.

## 15. Glossary changes (S6e)

| Term | Meaning |
|---|---|
| check (as built) | A named entry of the profile's `checks` at X that the checks step runs on the host. |
| checks attempt | The check step's attempt (`checks_attempt`): numbered per done implement attempt (a re-run adds one); a slot, an entry process (`taskloop.check_entry`), a deadline; the target and the required names; concluded `passed` or `failed` with a reason. Not an `attempt` row. |
| block | One pass over the profile's checks at X within a checks attempt, after a reset to X and `setup` at X; an interrupted block repeats whole after its stop proof; a completed one is never run again. |
| check result | One check's result in one block (`check_result`): `passed`, `failed`, `timed_out`, `lingering`, `dirty` (a tracked change or a moved HEAD), `undefined` (required at `main`, not defined at X), `interrupted` (not a result of the check: the block stopped). Its output is `check-<block>-<name>.log`. |
| pass (as built) | A check result `passed` in its checks attempt's latest block, for that attempt's X, profile digest and argv digest; never looked up for any other X or attempt. |
| result (checks) | The checks attempt's conclusion and reason: `<name>:<conclusion>`, `<name>:not_run`, `setup:<conclusion>`, `profile:<reason>`, `environment:<word>`, `slot:<word>`, `expired[:<name>]`, `main_moved`, `commit_missing`, `claim_lost`. |
| re-run | `tl step start` on a done, failed checks attempt: a new checks attempt of the same implement attempt and X. Not a repeat (an agent step's retry) and not an abandon. |

Also: the `profile` row loses "the factory does not run the checks yet"; `stuck` gains `stuck:checks_refused`; `held`
gains `held:check_running`; `step kind` says the check step is not one; `evidence files` gains
`check-<block>-<name>.log`.

## 16. Tests (pytest functions, fakes through ports, no process in factory tests)

- **Store and the not-current rule** (S6a): every v12 CHECK; writes fenced by token, generation and the held reservation
  of an `admitted` attempt; a concluded attempt refuses new results; the reboot renewal and no deadline refusal;
  `UNIQUE(after_attempt_id, number)`; latest block only; `unsettled` returns every unsettled row (unfinished,
  `lingering`, `timed_out`, `interrupted`); the refusal counter (same word, another word, kept across a block,
  cleared by a conclusion); `SUCCESSOR` in `ROW`, `FENCE` and `FLIP`; a checks attempt's setup run fenced through `HELD`.
- **Block** (S6b), as observed events over fakes: the identity committed before the fake executes; env (push bar,
  folders, no `UV_OFFLINE`, no Codex variables), cwd, the `min` timeout; every row of section 7 steps 4-6, including
  `timed_out` with survivors and the deadline with survivors (`lingering`), the deadline without (`interrupted`,
  `expired:<name>`), a tracked change after a timed-out check (`dirty`), untracked files only (listed, not `dirty`), a
  moved HEAD; a non-required failure still `passed`; an undefined required name `failed`; a completed block concluded
  without running; the log framing and cap; the hard reset of a checks slot and not of an implement slot. Real: a slot
  detached at X with real `sh -c` checks that pass, rewrite a tracked file (`dirty`), and leave an untracked file.
- **Entry and release** (S6c): section 6's order as events, the reconcile before any slot read (an orphan alive and a
  dirty slot give `checks:running`); every row of 6.1's table (concluded and released, or counted); the renewal before
  the block; `main_moved` before and after; take X fresh and on relaunch; the release's stop proof for setup and check
  rows in both modes; abandon of a released checks attempt.
- **Admission and status** (S6d): the stored row; each refusal of section 5 with nothing written; a racing admission
  launching the winner through the checks launcher; a re-run; the abandon race in both orders and the half-done state;
  `_previous` refusing `not_advanceable` for `check`; every row of the `Next` table and the field swap; show lines and
  JSON; list and `--stuck`; release, abandon and their rerun.
- **Round** (S6e), end to end over real SQLite and fakes: plan, implement, `check advance`, block, `passed`, `done`
  (silent); the failed path reported once and never re-run by the round; a block interrupted (entry gone, command gone)
  relaunched and repeated as block 2; a relaunch after a completed block concluding without running; two counted
  refusals then `stuck:checks_refused` and no further relaunch; a checks advance waits for a slot and goes before a new
  task; an abandon during checks restarts at plan.

## 17. Live smoke (owner, or an agent the owner authorizes, after S6e)

The runbook as built is [live-smoke.md](live-smoke.md) (section 25); the steps below are the design's. Since the S6e
repairs (section 25.1): in step 5 a check outliving its stopped entry makes the rounds report `check report running`
(they wait without relaunching or counting) and relaunch once it ends; in step 7 the rounds retry the held release each
round (`check release held:check_running`, logged once) and release the slot (`check release released`) once the person
stopped the survivor, so `T step release` is no longer needed there.

Base: the M1 runbook ([live-smoke.md](../tl-8bh9.4.3.1.16.2/live-smoke.md) "M1 end-to-end smoke") with a new scratch
folder `$M2`, the runner at the S6e commit, the scratch remote's `main` at that commit, and factory.db new (v12). Before
any task is cut, commit to the scratch `main`'s `.task-loop.json` one non-required check `slow`, `["sh", "-c", "sleep
90"]`, timeout 300, so every block has an interrupt window.

1. `T profile show --at HEAD` in the scratch checkout: setup `just bootstrap`; checks `check`, `test`, `slow`; required
   `check`, `test`.
2. A small `auto` task (as M1's); `T step rounds ... --minutes 120`. Expect in `rounds.log`: `plan start`, `implement
   advance`, `check advance started <id>`, `check report running` while the block runs, then nothing once it passed.
3. While the block runs: `T step show` says `Step: check`, `Entry: running`, a `Check:` line `unfinished`; the recorded
   check pid's group runs with cwd the slot (`ps -o pid,pgid,sid,cmd`; its sid is its own pid, not the entry's).
4. After: `Result: collected passed`; `Check:` lines `check passed, exit 0` and `test passed, exit 0` with logs ending
   `exit 0` and containing `All checks passed!` and `N passed`, and `slow passed ... (not required)`; `Released: ...
   claim kept`; `Next: done`. `bd show`: `in_progress`, `taskloop`. The slot detached at D and clean; `.t/<slot>` empty.
5. **Interrupted block**: a second task; while `slow` runs, stop rounds (Ctrl-C), then stop the checks entry by the pid
   `T step show` records (the person verifies it). Its check keeps running in its own session: restart rounds and expect
   `check relaunch relaunched` with the entry log `unavailable checks:running` until `slow` ends, then a relaunch that
   marks block 1's `slow` `interrupted` and runs block 2; the result is block 2's.
6. **Undefined required**: a third task; after its `implement advance` line, commit to the scratch checkout's `main` a
   profile adding a check `smoke` (`["true"]`) to `checks` and `required`. Expect `Check: smoke undefined`, `Result:
   collected failed:smoke:undefined`, one `check report failed:smoke:undefined` line, claim kept. Then `T step start`
   re-runs it (`Attempt: ... (run 2)`): still `smoke:undefined` (X lacks it), proving the re-run reads `main` again.
   Revert the `smoke` commit.
7. **Timeout with survivors**: on a scratch task branch's profile (commit it to `main` before cutting the task), a
   non-required check `orphan`, `["sh", "-c", "sleep 600 & sleep 600"]`, timeout 5: expect `orphan timed_out` (the stop
   took its group) and the block going on. Then `["sh", "-c", "setsid sleep 600 & sleep 600"]`, timeout 5: expect
   `orphan lingering`, `Result: collected failed:orphan:lingering`, `Released:` absent and `Next: release`
   (`held:check_running`) until the person stops the recorded survivor, then `T step release` frees the slot.
8. **Dirty and untracked**: a check `["sh", "-c", "touch untracked-file"]`: `passed`, the log lists `untracked:
   untracked-file`, the next block's reset removes it. A check `["sh", "-c", "echo x >> README.md"]`: `dirty`,
   `Result: collected failed:<name>:dirty`, the slot parked clean afterwards by the next block's reset or by hand.
9. **Abandon during checks** (optional): `T step release --abandon` while a block runs refuses `entry_running`; after it
   ends, the abandon releases the checks slot and returns the claim; `T step start` begins at plan.
10. Record findings in `docs/design/tl-8bh9.14.6/m2-smoke-findings.md` as for M1.

The abandon race and the relaunch after a completed block are covered by tests only (a live window is too narrow).

## 18. Risks

- **Host execution before review** (D10): accepted; residuals and mitigations in section 12.
- **One `--minutes` for every step**: setup plus all checks must fit one deadline; a deadline mid-block concludes
  `expired:<name>`, re-run with a larger `--minutes` (cheap since the re-run). Per-step minutes stay deferred.
- **Setup per block** (no reuse): minutes and downloads per block (S5e Q1's cost again).
- **A lingering check holds the slot** (`held:check_running`) until the person stops the group; with one slot the loop
  stops taking work. A redirected or branch-held slot likewise. B7 makes them visible in the tracker; nothing frees them
  automatically.
- **Two transient refusals stop relaunches** (`stuck:checks_refused`), including a store busy twice; the person relaunches
  with `tl step start`.
- **Detached descendants** (`setsid`) of a check are seen only as `survivors` of a stop; one that escapes before the
  library's process-table note is unobservable (.4.4).
- **Unbounded line buffer** in `stream_proc` (tl-8bh9.14.25) applies to check output too; it should land before M4.
- **`main` as the source of the required names** (O1, section 12): a moved `main` fails the block; a person committing
  to `main` during a block costs a re-run.
- **Flaky checks** fail the step; the person re-runs by hand until repair exists.
- **A checks attempt holds a slot** for its whole block: with one slot, agents wait behind checks (claimed work first).
- **Schema discard** at the upgrade to v12: finish or abandon attempts first (the existing runbook).

## 19. Not verified

- `run_registered`'s stop of a real `just test` tree on its own timeout, and its `survivors` for a `setsid` child (smoke
  step 7).
- That `just check` and `just test` pass from a slot set up by `just bootstrap` with network and the scrubbed
  environment outside any sandbox (M1 ran them inside the sandbox, offline, and by hand outside it).
- That `bd`'s heartbeat after a lapsed lease (a long wait for a slot) answers `held` while the task is still
  `in_progress` for `taskloop` (to be pinned by S6c's tracker-double test and the smoke's step 2).
- Line estimates, from the counts at 4f1d14c2c.

## 20. Review repairs (2026-11-11)

An independent review of 7ae3b0ec6 found nine points; all are taken.

| # | Finding | Repair |
|---|---|---|
| 1 | An implement abandon racing a checks admission could return the claim under a running checks attempt (`LATER` sees only `attempt`) | `SUCCESSOR` in `ROW`, `FENCE`, `FLIP`; abandon checks first; the half-done state refuses `release`/`not_advanceable`; both orders tested (sections 4, 10) |
| 2 | A timeout or deadline stop did not prove the tree gone | `SetupEnded.survivors`; the group check after every end; `lingering` stops the block; `LIVE_AFTER` includes `interrupted`; `unsettled` returns every live row; the clean read after timed-out checks; smoke step 7 (section 7) |
| 3 | Refusals that never clear relaunched forever with the slot held | Section 6.1: terminal conditions conclude `failed` and release; transient ones count to `stuck:checks_refused`; re-runs by `tl step start` (`number`, `UNIQUE(after_attempt_id, number)`) |
| 4 | Untracked files counted as `dirty` | Tracked changes and HEAD moves only; untracked listed; each block resets the checks slot hard to X (`reset` owned by `environment.py`) |
| 5 | A completed block ran again on relaunch | Section 6 step 7 |
| 6 | Task code can rewrite the local `main` | O1 decided with the before/after read, `main_moved`, B6's remote re-read; the Codex-login residual corrected (section 12) |
| 7 | View swap, `step_of`, the `task_attempted` winner, `_previous`, the reconcile order | Sections 3, 5, 6, 9 |
| 8 | Copied columns, the `profile_changed` machinery, a missing CHECK, B6 reuse | Section 4; `checks.Block` with a `ResultSink` (section 3) |
| 9 | Sizes after the composition split, the lease, the smoke | Section 14 sizes; section 6 step 3 and the slot wait (section 5); section 17 |

## 21. As built: S6a (tl-8bh9.14.6.1)

Schema v12, `check_store.py`, `factory_schema.SUCCESSOR`, the `setup_store.HELD` union and the policy entries; nothing of
S6b-S6e (no block, entry, launcher, release operation, admission, status or round routing). Code lines by the policy
counter: `check_store` 258 (new), `factory_schema` 153 (+44), `setup_store` 99 (+2), `slot_release` 264 (+1);
`test_check_store` 341 (new), `test_setup_store` 114 (+24), `test_slot_release` 385 (+61).

- **DDL** exactly as section 4. v11 (and every other version) is refused `schema`; `tests/steps/test_operations`'s
  foreign-version list now holds 11. The column lists `CHECKS_ADMITTED`, `CHECKS_LOADED`, `CHECK_RESULT` live in
  `factory_schema` with the others.
- **`SUCCESSOR`** replaces `LATER` in `slot_release`'s `ROW`, `FENCE` and `FLIP`; `publish` and `admit_chain` keep
  `LATER`. The `_pending` refusal now says "A later attempt or a checks attempt of the task is current".
- **`setup_store.HELD`** is today's fence `UNION ALL check_store.HELD` (bound with the key twice); `setup_run` has no
  foreign key.
- **`check_store`**: `ChecksAdmitted`, `ChecksRow` (joined with the implement attempt: task, repository, tracker root,
  X), `ResultRow` (`unsettled`); module functions `insert(con, admitted)` (in the admission's transaction; an existing
  `(after_attempt_id, number)` is `StoreRefused("task_attempted")`, read before the write), `record_release(con, key,
  (rev, phase), parked, now, abandoned)` (in the release's transaction; False off the fence: key, the proof's rev and
  phase, the held reservation, no earlier release, settled only once concluded; it does not remove the reservation:
  S6c's `slot_release.free` does), `latest_results`, `unsettled`; `CheckStore` with `attempt_of`, `row`, `of_attempt`,
  `results`, `register_entry`, `refused`, `profiled`, `block`, `start`, `undefined`, `registered`, `finish`, `conclude`,
  `abandon_released`; `LIVE_AFTER = ("lingering", "timed_out", "interrupted")`.
- **Policy**: `WRITERS` gains the two `CREATE TABLE` rows (`factory_schema.py`) and `INSERT`/`UPDATE` of both tables
  (`check_store.py`). `GIT_WRITES` gains `reset` now, with no owner yet: S6b adds `("reset", "environment.py")` to the
  expected writers when it builds the hard reset.

**Deviations (decided here, open to veto).**

1. A result's conclusion is `CheckStore.finish`, not `conclude`: one class cannot carry both the attempt's and the
   result's `conclude`. S6b's `ResultSink` is a small adapter binding the key, its `conclude` calling `finish`.
2. "rows" is built as the dataclasses plus `row(key)`; `of_attempt(after)` returns every checks attempt of the implement
   attempt by number (the last is the latest), so S6d's `Earlier:` lines need no second read.
3. `attempt_of` overrides `AttemptReads.attempt_of` with the same signature (the latest checks attempt of the task's
   current agent attempt), ready for S6c's `EntryTargets`.
4. There is no block column on the attempt: `block(key)` returns the latest result block plus one; called again before any result is written it returns the same number. Result writes are accepted only in
   the latest block, or to start the next one (`check_changed` otherwise); a command registers once.
5. `register_entry` ignores a non-finite renewal rather than refusing (it has no deadline refusal at all); `now` is
   unused and kept for the launcher's port.
6. The `required` list is validated on insert (1 to 32 distinct names, each with a 64-character digest: `ValueError`) and
   on every read (`StoreUnavailable`); the DDL itself has no JSON CHECK.

**Tests**: every CHECK of both tables rejecting its bad row (and the valid rows accepted), the two UNIQUEs and both
foreign keys; v11 not current; the insert's lost race and its validation; every write under another key, without the
held reservation (removed, another generation, another slot) or once concluded is `stale_reservation` and writes
nothing; blocks, the latest-block reads, results started outside the latest or next block or on a taken position or
name, registration once, a result concluded once; the registration connection used only for the identity; `unsettled`
for every conclusion; the refusal counter; the profile digest once; `conclude`'s CHECK on the reason, `target_seen`, the
cleared counter; the entry registration (a passed deadline accepted, same-boot and other-boot renewal, off the fence);
`attempt_of` after a fresh plan; `record_release` and `abandon_released` fences; a checks attempt's setup runs fenced by
the union. `SUCCESSOR`: `ROW` with the latest checks attempt admitted or abandoned (and an earlier one of each kind),
`FLIP` with a checks row committed between the abandon's read and its flip, `FENCE` with one committed under the
release's lock, and the other order: the abandon's flip committed first, then a checks row written anyway, and the
abandon's rerun still returns the claim. The admission's own refusal in that order (`not_advanceable` on `unclaiming`)
is S6d's.

**Not verified**: nothing runs a checks attempt yet; the store's shape is exercised only by these tests.

### 21.1 Review repairs to S6a (2026-11-11)

An independent review of 3ce982650 found no defect in the DDL or `SUCCESSOR`; six repairs, each with a test that fails
without it:

1. **The refusal counter survives a block** (section 6.1 changed): `block()` no longer clears it, only `conclude` does.
   Otherwise a refusal inside a block (start uncertain, store or Git unavailable mid-block) was cleared when the
   relaunch repeated the block, and the attempt relaunched forever.
2. **New CHECKs** (section 4 DDL): an entry identity (`entry_pid`, `entry_start`, `entry_boot`) and a command identity
   (`pid`, `pgid`, `proc_start`, `boot`) are all set or none; an `undefined` result has no `pid` and no `rc`; `rc` only
   with a conclusion. A partial stored identity (only past the CHECKs) reads as `StoreUnavailable`, never as no process.
3. **`attempt_of` says `released`** for a released checks attempt, whatever its phase (an abandon releases an `admitted`
   one without a conclusion). **S6c**: the launcher launches only `admitted`, so an abandoned checks attempt is never
   relaunched; the round's and `tl step start`'s routing (S6d, S6e) must read the same word.
4. **`CheckStore` has no agent attempt read**: `attempt_reads.StoreConnection` is the shared connection base;
   `AttemptReads` (the `attempt` table's reads) extends it, and `CheckStore` extends only `StoreConnection`, so a checks
   key can never be passed to `state`, `tracker_root`, `release_of`, `step_of`, `attempts`, `chain` or `slot_use`.
   `attempt_of` is now `CheckStore`'s own method, not an override (deviation 3 above).
5. **The Git write matcher** in `test_policy` (`git_names`) counts an attribute (call or reference), a bare call, or a
   string argument of `getattr`, `methodcaller` or `attrgetter`; any other string (the refusal word `reset` in S6b's word
   tables) is not a use. It stays closed for real calls.
6. **The letter T**: the glossary's T is the remote tip after a push; `main`'s commit at a checks admission is now "the
   target" everywhere in this plan, the code comments and the test constants (`TARGET`). The glossary says factory.db
   v12 since S6a.

## 22. As built: S6b (tl-8bh9.14.6.2)

The block, the checks slot's setup and its take of X; nothing of S6c-S6e (no entry, launcher, release operation,
admission, status or round routing; nothing runs a block yet). Code lines by the policy counter: `checks` 159 (new),
`environment` 245 (+16), `prepare` 154 (+29), `evidence_files` 113 (+6), `agent_credentials` 67 (+2), `slot_env` 97
(+1); `test_checks` 236 (new), `real/test_checks_real` 63 (new), `test_environment` 381 (+62), `test_prepare` 326
(+49), `test_credentials` 179 (+7), `doubles` 220 (+1).

- **`checks.py`**: `Block(BlockPorts(process, lingering, clock)).run(BlockTarget(slot, view, commit, required, deadline,
  env), sink, block, checks)` as section 7; returns None when the block ended (ran through, or stopped by `lingering` or
  `dirty`: the results decide) or the attempt's word: `refused expired:<name>`, `unavailable checks:uncertain`, `git`,
  `environment:files`. The readings `completed(results, checks, required)` (section 6 step 7) and `conclusion(results,
  required)` (step 12), `differs(required, row)` (the `(argv differs from main)` marker), `argv_digest`, `main_seen(view)`
  (`refs/heads/main` now, None when gone: the entry's before/after comparison), `check_env(scrubbed, slot)`
  (`environment.setup_env`). `CheckSink(store, key, files, clock)` is the checks attempt's `ResultSink`; its `conclude`
  is `CheckStore.finish` (S6a deviation 1).
- **`environment.prepare_for(SetupFor(key, slot, commit, branch, deadline, first), prepared, renew, env, *, probe)`**:
  `prepare` builds the implement `SetupFor` (commit None, `task/<id>`, `first` = attempt 1) and passes its launch as the
  probe. A checks slot (`commit` X, `branch` None, `probe=None`): no probe, no reuse of a passed run, `reset(X,
  mode="hard")` before the existing `clean`, `(X, None)` expected after setup.
- **`SetupEnded.survivors`** (`bool(Result.survivors)` in `slot_env.setup_process`). Setup's judgment now checks for a
  process left first, for every end: a timed-out setup command whose stop left survivors (or whose group is alive) is
  `lingering` (`environment:lingering`), no longer `timed_out`/`expired`.
- **`prepare.detach_at(checkouts, files, slot_path, repo_id, X)`**: section 6 step 9 through `observe_slot` and the
  pinned view; `Prepared(X, gitdir, root)`.
- **`evidence_files`**: `SetupLog` renamed `CappedLog` (`LOG_CAP`), `check_log(key, block, name)`, `open_check_log`.
- **`agent_credentials.scrubbed(environ)`**: the scrub, the venv drop and the push bar; `codex_machine_credentials`
  calls it after its Codex lookups.
- **Policy**: `test_policy` expects `("reset", "environment.py")`; `taskloop.checks` joins the entry's import closure
  contract (`entry-never-imports-the-command-surface`) now rather than in S6c.

**Deviations and decisions (decided here, open to veto).**

1. `ResultSink` has a fifth method, `log(block, name)`: the log belongs to the record's owner (land keeps its own), so
   the block knows no key. The log is opened before `start`: a log that cannot be opened is `unavailable
   environment:files` with no result written (section 7 put `start` first).
2. A deadline reached between checks is `refused expired:<next name>` with no result for that check (nothing started);
   section 7 only named the deadline's stop of a running check (`interrupted`).
3. A command that never ran (exec failed, or the start failed before registration) is `failed` with no group check and
   no slot read (section 7 step 5 says "every check that ran"); the block goes on.
4. A supervision failure after registration is judged like setup's: `ended uncertainly`, the group check, then the slot,
   then `failed`.
5. The slot unreadable after a check (`GitUnavailable`) is `unavailable git` and leaves that result unfinished with its
   identity, so the next entry's reconcile makes it `interrupted` and the block repeats.
6. `conclusion`: a stopping result always gives the reason (`<name>:lingering|dirty`, required or not), even when every
   required check passed before it (section 7 steps 4-5: the attempt concludes `failed <name>:...`).
7. `detach_at`'s words: `slot:redirected`, `slot:branch`, `commit_missing` (checked before `slot_dirty`, so a gone X is
   never a counted relaunch), `slot_dirty`, `slot_unborn`, `unavailable` `repo`, `not_listed`, `git`, and a new
   **`slot:moved`** when the re-read after the park is not `(X, detached)`. S6c's 6.1 table: `slot:moved` and
   `slot_unborn` conclude; `repo`, `not_listed` relaunch counted.
8. Setup's `lingering` now takes precedence over `timed_out` (above); the existing implement-path tests are unchanged.

**Tests**: `test_checks.py` (block over real SQLite through `CheckSink`, the Git fake's slot at X and the scripted
registered start): order and identity before execution, cwd, the scrubbed environment (push bar, folders, no
`UV_OFFLINE`, no credential, Codex-companion or venv variable), the nearer wall limit; undefined required names first;
own timeout (`timed_out`, the block goes on); `lingering` after an exit, a failed exit, a timeout with survivors or an
alive group, and the deadline with survivors; the deadline without survivors (`interrupted`, `expired:<name>`); a
deadline between checks; `dirty` for a tracked change, a staged file, a branch and a new commit after exit 0, exit 1 and
a timeout; untracked files listed (50 and a count, ignored files not), not `dirty`; never-ran commands; supervision
failure; uncertain start; an unreadable slot; an unopenable log; an interrupted block repeated whole with only the
latest block concluding; `completed`, `conclusion`, `differs`, `argv_digest`, `main_seen`, `CappedLog`'s cap.
`test_environment`: the checks slot reset hard (a rewritten tracked file, untracked and ignored files gone before
setup), no probe, setup at X; no reuse; an implement slot never reset hard; `moved` off X; failed checks setups counted
to `environment:failed`; renewal and deadline; survivors `lingering` on the implement path. `test_prepare`: `detach_at`
on the fake. `test_credentials`: `scrubbed`. Real (`real/test_checks_real.py`): a `--detach` slot at D parked at X, then
real `sh -c` checks pass, leave an untracked file, time out, rewrite a tracked file (`dirty`, block stops); a check
with a background child is `lingering`.

**Not verified**: a real `setsid` survivor of a stop (smoke step 7); a real deadline stop mid-check; anything of the
entry around the block (S6c).

### 22.1 Review repairs to S6b (2026-11-11)

An independent review of 89a4a0608 found no defect in the block; three repairs:

1. **The hard reset only of a slot detached at X** (defence in depth): `Preparation._reset` reads the worktree listing
   through the pinned view first and refuses `environment:moved` (nothing reset, cleaned or run) unless the slot is
   `(X, detached)`. A straggler that checked out a branch between `detach_at` and the reset would otherwise have had that
   branch moved to X. Test: a branch and another detached commit, each refused with the branch ref, tracked and ignored
   files untouched (fails without the check).
2. **Words**: the S5e plan's run-result table and step 7 say a stop that left survivors is `lingering`; the
   `environment` guide covers checks blocks, says `lingering` waits for the process (then a relaunch, or `expired` past
   the deadline) and no longer promises a relaunch runs setup again after the deadline.
3. **The checks release resets the slot to X before the park** (a design gap of S6c, recorded, not built): section 10
   and the S6c slice row; also in the S6c tracker issue's notes.

## 23. As built: S6c (tl-8bh9.14.6.3)

The checks entry, the launcher port and the checks release; nothing of S6d-S6e (no admission, `steps.ORDER`, operations
routing, status `Next` table, `tl step` show/list/release/start for checks, round routing or `rounds.log` words: nothing
admits or launches a checks attempt yet). Code lines by the policy counter: `check_entry` 209 (new), `check_release` 129
(new), `composition` 136 (+36), `launch` 162 (+12), `environment` 255 (+10), `check_store` 273 (+7), `slot_release` 266
(+2), `prepare` 154 and `attempt_entry` 230 (renames only); `test_check_entry` 263 (new), `test_check_release` 194 (new),
`real/test_check_release_real` 66 (new), `test_launch` 252 (+35), `conftest` 129 (+22).

- **`check_entry.py`**: section 6's order and 6.1's table. `enter(args, opened, inspect, log, heartbeat_for, stop)`; the
  collaborators are `composition.Checking` (`open_checking`: the stores, evidence, Git views, slot file port, profile port,
  `Preparation`, `Block`, the command and entry observations, the scratch, the clock and the scrubbed environment). Exit 0
  only for `collected passed`.
- **The 6.1 rule as built** (`check_entry.concluded`): every `unavailable` word relaunches and counts; every `refused`
  word concludes `failed` with that word, except `RELAUNCHED` (`slot_busy`, `lock`, `slot_dirty`, and the store fences
  `stale_reservation`, `check_changed`, `setup_changed`). So S6b's `slot:moved` and `slot_unborn` conclude, `unavailable
  repo`, `not_listed`, `environment:files` count; `refused environment:profile` concludes and `unavailable
  environment:profile` (a Git read) counts; `refused environment:failed` concludes `setup:<the latest run's conclusion>`.
- **`launch.EntryTargets`** (`attempt_of`, `register_entry`) and `Targets` (the store over one connection): `Launcher(...,
  targets=AttemptStore, module=ENTRY_MODULE)` by default; `composition.open_checks_launcher` passes `CheckStore` and
  `CHECK_ENTRY_MODULE`. A concluded or released checks attempt is `refused dispatched`.
- **`check_release.ChecksRelease`**: section 10. The stop proof (`entry_stopped`, `slot_release.setup_stopped`, and
  `checks_stopped` over `check_store.unsettled`), then under the lock `environment.reset_to(view, slot, X)` only for a slot
  listed `(X, detached)`, then `slot_release.park_slot(..., branch=None)`, then `check_store.record_release` and
  `slot_release.free` in one transaction, then the scratch. Abandon of a released attempt: `abandon_released`.
- **Shared, extracted**: `slot_release.park_slot(checkouts, files, path, repo_id, D, branch)`, `free(con, ...)` (the one
  `DELETE FROM reservation`) and `setup_stopped(seen, setup)` are module functions used by both releases;
  `environment.reset_to` is the one owner of `reset` and `clean` (the checks setup's reset uses it too);
  `check_store.held_slot` / `CheckStore.slot_path` read the held reservation's slot path.
- **Policy**: `WRITERS` and `GIT_WRITES` unchanged (the owners did not move). `.importlinter`: `check_entry`,
  `check_release`, `check_store` join the entry closure contract; `check_entry` joins the command surface's forbidden list.

**Deviations and decisions (decided here, open to veto).**

1. `slot_unborn` concludes with the reason `slot:unborn` (the `slot:<word>` family of section 15).
2. `RELAUNCHED` adds `lock` (the slot's lock file cannot be opened) and the three store fences to the table's relaunch
   column. `stale_reservation` cannot be counted (the attempt no longer holds its reservation) and the launcher will not
   launch it again either.
3. Before the attempt is its own the entry refuses without counting: `refused database|absent|identity`, `refused
   concluded|released` (the task's latest checks attempt is not admitted), `refused stale_reservation` (its reservation is
   not held), `unavailable store`.
4. The log line of a counted relaunch is `<status> <reason> claim=<word>` (no count: it is factory.db's); `refused
   slot_busy` and `refused lock` have no `claim=` (the claim was not read). A conclusion the store refuses is logged
   `refused <fence>` or counted `unavailable store`, and nothing is released.
5. The entry reads the slot's pinned Git directory before X is taken through `prepare.slot_listed` (S6b's `_listed`, made
   public), so the profile at X and `main` are read on the pinned view; its words are `detach_at`'s.
6. The scrubbed environment is computed once by `open_checking`: a malformed `GIT_CONFIG_COUNT` is `failed
   CredentialsUnavailable` from `main`, not a counted refusal (it would relaunch until the person fixes the environment;
   S6e's round should treat a `failed` entry log like any lost entry).
7. A claim lost at the renewal after setup (`environment`'s) concludes `claim_lost` before the block; lost later by the
   keep-alive thread it is only `claim=lost`, and a passed block still exits 0.
8. `main` gone (no `refs/heads/main`) is `main_moved` with `target_seen` NULL.
9. A checks release never touches the tracker claim; its `Released`/`AlreadyReleased` say `kept` (the claim is the
   implement attempt's; the implement abandon that follows returns it).
10. `attempt_entry._exists` is now `database_exists`; the checks entry imports `EntryArgs`, `arguments`,
    `database_exists` and `renewal` from it (one argv shape and one renewal rule for both entries).
11. No `open_checks_releaser` yet: `tl step release` for a checks attempt is S6d's.

**Tests**: `test_check_entry.py` (a factory.db file with the entry registered as this process's real identity, the Git
fake's slot, `doubles`' environment and scripted start, the real slot lock, a scripted claim): the passing order (renewal,
X taken, reset and setup at X, renewal, block, release parked at D), a failed required check, the claim lost before the
block, at the setup's renewal and later (recorded, results stand); the reconcile before any slot read (a live or unknown
orphan with a dirty slot: `checks:running|unknown`, counted twice; a live setup command); an interrupted block repeated
whole; a completed block concluded without running or taking X; expired only after the proof, with no X and no setup run;
`main_moved` before and after the block; the profile at X refused; a dirty slot counted, then a branch concluded (the count
cleared); the environment's refusals concluded and its unavailable words counted; two failed setups concluding
`setup:lingering`; a lingering check holding the release (`held:check_running`); the deadline mid-block (`expired:check`);
an uncertain start counted and reconciled; identity, concluded and missing-database refusals; a busy lock counted; the
6.1 table. `test_check_release.py`: the reset to X then park at D (untracked, ignored and tracked leftovers), no Git write
at D, `not_terminal`, every stop-proof refusal in both modes with nothing changed, the passing proofs (`me`, settled, never
registered, gone), a slot on a branch not reset, a busy lock and a changed rev, absent and closed store, the task's abandon
in both orders (implement first refused `changed`, then checks, then implement returns the claim; and the implement flip
first, a checks row anyway, both finished by the reruns), the abandon of a released attempt once and only of the latest.
`test_launch`: a checks attempt past its deadline still launched with `taskloop.check_entry`, concluded and released ones
refused `dispatched`, the composition. Real (`real/test_check_release_real.py`): a real `--detach` slot at X with an
untracked report, an ignored `build/` and a rewritten tracked file, released to a clean D. Mutation-checked: removing the
reset, the checks stop proof, the setup stop proof, the settled check, the free, the reconcile, the expiry, the
interrupted marking, the completed-block reading, either `main` read, a `RELAUNCHED` word, the counter, the identity
state check or the exit code each fails a test.

**Not verified**: a real launched `taskloop.check_entry` process (only the body runs in tests; the launcher's start is the
fake); a real block run by the entry end to end (S6b's real test runs the block alone); `bd`'s heartbeat after a lapsed
lease (section 19); everything S6d-S6e route.

### 23.1 Review repairs to S6c (2026-11-11)

An independent review of f28337f41 found the refactor sound and five defects; each is repaired with a test that fails
without it:

1. **The counter counts every relaunch** (`CheckStore.refused`: `refusals+1` whatever the word; `refusal` is for display).
   Two words alternating (an uncertain setup or check start, then `checks:running` because it is not waited for) relaunched
   forever and reran the candidate's setup each cycle. Consequence: two failed setup runs (`environment:exit`, then
   `environment:lingering`) are now two counted relaunches, so `stuck:checks_refused` stops the rounds before the third
   entry concludes `setup:<conclusion>`; a relaunch by hand concludes it. Tests: setup and block alternation, the store.
2. **`main` before a completed block**: section 6 steps 7 and 8 swapped; the completed path reads `main` on the pinned
   view first (`main_moved`). Test: a completed passing block with `main` moved concludes `main_moved`.
3. **The entry-log grammar** (`round_log.WORD`, the one owner, also `rounds.log`): a part is the profile's name alphabet
   and length, `[A-Za-z0-9_][A-Za-z0-9._-]{0,63}`, so `collected failed:type-check:failed` and `failed:expired:a.b-c` are
   read by `last_entry`. Tests in `test_operations` (a 65-character part and a leading `-` still refused).
4. **Faults are counted**: any exception under the lock once the attempt is the entry's own is `unavailable
   fault:<type>`, counted. The scrubbed environment is read when the slot is set up (`Checking.environ` is now a
   callable), so `CredentialsUnavailable` is such a fault (supersedes deviation 6 of section 23). Test: two faults reach
   two.
5. **A lost claim reconciles first**: before concluding `claim_lost` the entry runs the reconcile (no slot access) and
   ignores its word, so gone unfinished results become `interrupted` (a live one holds the release). Test.

## 24. As built: S6d (tl-8bh9.14.6.4)

The checks admission, `steps.ORDER` and the `tl step` routing and status of a task in its check step; nothing of S6e (the
round's settle and `_resume` routing and its `rounds.log` words). Code lines by the policy counter: `check_admit` 201
(new), `check_status` 45 (new), `show_render` 67 (new: the `tl step show` lines, moved out of `step_render`), `operations`
324 (+48), `attempt_status` 194 (+40), `step_render` 110 (-28), `step_guide` 161 (+25), `result_data` 122 (+14),
`cli_composition` 213 (+5), `composition` 146 (+10), `steps` 51 (+5), `attempt_reads` 196 (+1), `admit` 281 (+1),
`cli_step` 164 (+2); `test_check_admit` 138, `test_check_operations` 176, `test_check_status` 119, `tests/cli/test_check_cli`
119 (all new), `conftest` 164 (+35, the `done` fixture), `doubles` 294 (+74, `ChecksBench`, `NoChecks`, `MAIN_PROFILE`).

- **`check_admit.ChecksAdmission.admit_checks(ChecksRequest(previous, checkout, deadline, number))`**: section 5's order.
  `next_number` (shared by the reads and the write transaction) is the implement attempt still current and done
  (`admit_chain.CURRENT`, `task_of`, made public) and the number its checks attempts give. The required names come from
  the profile at the local `refs/heads/main` through `git_views.GitProfileFiles` on the checkout (`composition`'s
  `Profiles` port). No input file, no claim.
- **`steps.ORDER = ("plan", "implement", "check")`**, `CHECK`, `is_agent`; `following` and `next_step` read `ORDER`
  (`kind("check")` stays an error); `admit_chain._previous` refuses `not_advanceable` when the next step is no agent's.
- **`check_status`**: `latest`, `route` (`advance`, `launch`, `rerun`, `answer`, `abandoned`), `checks_result`,
  `checks_release`, `checks_next` (section 9's table, `REFUSED_STUCK = 2`), `ChecksView`, `HALF_DONE`.
- **`operations`**: `StartPorts.checks` (`ChecksPorts`: the admission and the launcher of `taskloop.check_entry`);
  `_current` sends a done implement attempt to `_checked`; an admitted checks attempt (`_Relaunch`), the advance, the
  re-run and a racing winner (read through `CheckStore.attempt_of`) are launched with the checks launcher; `Started.step`
  is set to `check` by the route (no `step_of` read). `release_task(reader, releaser, checks, ...)`: the latest checks
  attempt first; settled stops there; the abandon then abandons the implement attempt (`ReleasedTask.checks` carries the
  first half). `verify_task` and `publish_task` are unchanged: they follow the agent attempt (tested).
- **Status**: `AttemptView.checks`; `attempt_status._show` swaps the fields once the implement attempt's `Next` is
  `advance` and a checks attempt exists (a failed read of it is `unknown`); `show_attempt` names the checks attempt's
  directory, entry log, latest setup run and each latest-block result's log (computed, never made). `Next` gains
  `stuck:checks_refused`. `attempt.succeeded` accepts `passed`.
- **Words**: `STEP_ONLY` names `check`; GUIDE adds `stuck:checks_refused`, `check_running`, `check_unknown`, `checks`,
  `no_required`, `target`, `target_profile`, `commit_missing`, `main_moved`, and the `done`, `advance` and
  `not_advanceable` texts name the check step; `start`, `verify` and `release` help.
- **Composition**: `open_checks_admission(database)`, `open_checks_releaser(database, store)`; `open_start` and
  `open_next` wire `ChecksPorts`; `open_release` yields the checks releaser too. `.importlinter`: `check_admit` and
  `check_status` join the entry closure contract (composition imports them), `show_render` the command surface's.

**Deviations and decisions (decided here, open to veto).**

1. `ChecksRequest.number`: the caller's reading of the next number (1, or the failed latest + 1); the store deciding another
   number, before or under the write lock, is `task_attempted`. So the round's advance (`advancing`) only admits number 1
   (a re-run is never the round's) and a concurrent conclusion between the reads and the write cannot slip in a re-run.
2. X readable (`commit_missing`) is checked before its containment by the task branch (`branch_moved`), so both words
   are reachable; a superseded implement attempt is `not_advanceable` (section 5), not `admit_chain`'s `task_attempted`.
3. A required name the profile at `main` does not define among its own checks is `refused target_profile` with
   `required_undefined: <names> at main` (B3's `resolve` rule for the target side).
4. A concluded checks attempt not yet released is answered (`already_dispatched` with its result), never re-run; a passed
   one likewise. The half-done abandon is `refused release` with `HALF_DONE` (rerun `--abandon`), never a launch.
5. `ReleaseRow.checks_abandoned` (additive): a checks attempt's own abandon flag, so `abandoned` holds while its claim is
   still the implement attempt's `kept`; `tl step release --abandon` prints the checks attempt's lines first and its
   JSON gains `checks` (the first half's release data, null otherwise). The "Abandoned: `tl step start` admits a fresh
   attempt" line is printed only for a release that returned the claim.
6. `tl step show` of a checks attempt prints section 9's lines (no `Worker:`, `Deadline passed:` or `Published:`; the
   JSON keeps every key), `Check: none yet` before a block, `unfinished` for a running check, the exit only when known and
   whole seconds; `tl step list`'s attempt column is the run number alone. JSON: `checks` (commit, target, target_seen,
   required names, profile_digest, refusal, refusals, results with name, required, conclusion, rc, block, times,
   argv_differs and log, the log null in `tl step list`) on every view, null for an agent attempt.
7. The round is not changed (S6e). Its advance phase already admits and launches checks attempts (`<task> check advance
   started <id>`; `no_required`, `target`, `target_profile`, `commit_missing` are skips). Until S6e its settle phase
   reports, for a checks attempt: a relaunch `refused:changed` (`_resume` reads the agent attempt), a failed one as
   `failed:failed:<reason>`, and the other `Next` words as they are.
8. `tests/steps/test_advance.py` now ends at `Next: advance` for the implement step (its checks admission is a double
   refusing `no_required`).

**Tests**: `test_check_admit.py` (the `done` factory.db, the Git fake's `main` and `task/tl-1`, the real profile reader,
a tracker double): the stored row and reservation (D, target, required digests, generation), each refusal with nothing
written and no tracker read (`expired`, `unclaiming`, rejected, unpublished, a plan, branch gone or moved, `commit_missing`,
no `main`, another target, no or a broken profile, `required_undefined`, `no_required`, `no_free_slot`), `claim_lost`
after one read, another repository's checkout, X only on origin's task branch, a re-run (number 2, the target read again,
the first kept; refused before the release), a passed or half-abandoned latest one, a number the store does not give,
and commits between the reads and the write (a winner, a winner already failed and released, the abandon's flip, a taken
slot); the agent advance refusing the check step. `test_check_operations.py`: start's advance, relaunch, answers, re-run
(never by the round), the round's advance, the half-done refusal, a racing winner and a failed launch through the checks
launcher; release settled (checks only), the abandon's order, a half-way stop and its rerun, no checks attempt; verify on
the implement attempt. `test_check_status.py`: the field swap, `advance` without a checks attempt, every `Next` row
(including `stuck:checks_refused`, `stuck:hung`, `unknown` and an unreadable row), result and release, `--stuck`, show's
directory, setup, logs and earlier attempts (creating nothing) and its last entry line. `tests/cli/test_check_cli.py`: the
show lines in order, `Main:`, `Refused:`, an unread profile, no block, an unfinished check, show and list JSON, the list
row, a checks start, the abandon's text and JSON. Mutation-checked: removing either number fence, the commit read, the
remote-tracking fallback, the abandon, `no_required`, target, checkout or `required_undefined` refusal, the round's
number 1, the winner's checks read, the settled stop, the `check` step on a start, the `abandoned` route, the abandoned
`release`, the refusal threshold, `unknown`, `stuck:hung`, `passed` in `succeeded`, `checks_abandoned`, `is_agent` in
`_previous`, the argv marker, the swap or the claim-returning `Abandoned:` line each fails a test.

**Not verified**: a real `tl step start` launching a real `taskloop.check_entry` and its block end to end (the launcher is
a semantic fake here); the profile read of a real `main` through `GitProfileFiles` in the admission (only the Git fake);
the round's settle of checks attempts (S6e).

### 24.1 Review repairs to S6d (2026-11-11)

An independent review of a7dc16784 found the admission, routing and fences sound and five wording or reporting defects;
each is repaired with a test that fails without it:

1. **A checks view's own guide** (`step_guide.CHECKS_GUIDE`, chosen by `guide(word, checks=...)` in `tl step show` and
   in `tl step list`'s stuck lines): `start` says only `tl step start` relaunches a checks attempt (S6e changes this
   sentence once the round routes it); `stuck:hung` names `taskloop.check_entry` and the check process groups and stops
   only verified pids; `release` names `held:check_running` and `held:slot_dirty`. The agent texts (`Worker`,
   `taskloop.attempt_entry`, "each round relaunches it") are never shown for a checks attempt. A `Check:` line of a
   command not proven gone names its process group (`, process group <pgid>`), which the hung guide verifies.
2. **A concluded checks entry still running is `wait`** (it is releasing its slot), never `stuck:hung` past the deadline
   and not `release`; `stuck:hung` is only an `admitted` attempt's (section 9's table, `checks_next`).
3. **After a finished abandon** (the implement attempt's claim no longer `kept`, its latest checks attempt released),
   `tl step release` and the `--abandon` rerun answer with the implement attempt's release and its claim (`unclaimed`),
   not the checks half's `kept`. A checks attempt still holding its slot (admitted after the implement flip, the other race
   order) is still released first.
4. **A refusal whose detail names its action** (`HALF_DONE`, `UNCLAIMING`: rerun `tl step release --abandon`) prints no
   further guide; `GUIDE["release"]` ("slot still held ... `tl step release`") contradicted it.
5. **Logs through their owner**: `EvidenceFiles.check_path` (no directory made; `check_log` makes it) gives `tl step
   show`'s log paths; an `undefined` result has none (`logs` entry and JSON `results[].log` null).

## 25. As built: S6e (tl-8bh9.14.6.5)

The round's settle routing for checks attempts, its `rounds.log` words, the guide, the glossary and roadmap rows and the
[M2 live-smoke runbook](live-smoke.md). No schema, exit code or JSON key change. Code lines by the policy counter: `round`
244 (+4), `operations` 344 (+18), `step_guide` 178 (+2); tests: `round_bench` 150 (new: the rounds bench moved out of
`test_advance`, now 112), `test_checks_round` 215 (new), `test_check_operations` 222 (+30), `test_check_cli` 143 (+1).

- **`_resume` of a checks view** (`each.checks` set) calls `operations.relaunch_checks`: fenced on
  `CheckStore.attempt_of` (the checks launcher's own read): the snapshot's checks attempt is still the task's latest,
  `admitted` and not released, else `refused:changed`, `concluded`, `released` or `abandoned` (the last a `skip
  abandoned`); then the checks launcher, never the agent's; `Started.step` is `check`. A checks attempt whose advance
  launch failed (`implement advance unavailable:start`), whose entry refused or died, or that passed its deadline is
  relaunched (`check relaunch relaunched`). The round never admits, claims or re-runs: a failed checks attempt is `done`.
- **Words** (section 9): `check advance started`, `check report running`, `check relaunch relaunched`, `check report
  failed:<reason>` (the checks result's reason is already `failed:<reason>`; it was `failed:failed:<reason>`, four parts,
  logged `invalid`), `check report stuck:checks_refused`, `check report release`. A failed or stuck checks task is one
  task's move: it never stops other advances or ingestion (S5c's stop set is unchanged).
- **Admission's skip of a half-done abandon**: `_admit`'s attempts map reads "abandoned" as the claim no longer `kept`,
  so a ready task whose checks half is abandoned (claim kept, then lapsed) is skipped `attempted`, not `abandoned`.
- **Guide**: `CHECKS_GUIDE["start"]` says each round relaunches the checks entry, and `tl step start` does; it and
  `stuck:checks_refused` name the count past the deadline.

**Decided here (open to veto): the bound on relaunches the entry never counts.** S6c's counter is the entry's: a launch
that fails or is uncertain, an entry refusing before the attempt is its own (`identity`, `stale_reservation`, `absent`,
`unavailable store`) or one crashing before it counts (`failed <Type>` from `main`) leave `refusals` unchanged, so a
round relaunching them would do so forever, past the deadline too (a checks attempt past its deadline is still `start`:
its entry concludes `expired`). The plan has no mechanism for these; the smallest, with no new column: **past its
deadline each round's relaunch is counted before the launch** (`CheckStore.refused(key, LATE)`, `LATE = "late_relaunch"`,
the existing counter and threshold), so at most two such relaunches follow the deadline before `stuck:checks_refused`
(fewer when the entry counted refusals already; one that concludes clears the count). Before the deadline such
relaunches repeat once per round, as an agent attempt's do until its deadline (`stuck:expired_admitted`). Not chosen:
counting every failed launch (a transient fork failure would stop the rounds after two), counting every round relaunch
(double counts the entry's own refusals: stuck after one), or counting at registration (changes S6c's meaning of the
counter). Consequences: a reservation no longer held makes the count refuse, so past the deadline nothing launches
(`relaunch refused:stale_reservation`, reported each round, logged once); the relaunch after a reboot past the deadline
is counted although the entry's registration renews the deadline (once; cleared by its conclusion); with a live
orphan check past the deadline the round and the entry both count, so one late relaunch reaches the threshold.
`tl step start` by hand is not counted.

**Tests** (`test_checks_round.py`, over a factory.db file, the rounds bench, the real checks admission at a `main`
requiring `check` and `test`, and the real `launch.Launcher` over `CheckStore` whose registered start runs a scripted
entry body at once): plan, implement and checks to `Next: done` with one claim and nothing logged for the pass; a failed
check reported once (`quiet`), never relaunched or re-run, the claim kept and a new task started; relaunch with the checks
launcher only after a failed launch, a crashed entry and a counted refusal (the agent launcher never called again); two
counted refusals stopping the rounds (reported once) while new work starts in a second slot, then `tl step start` by hand;
past the deadline a failed launch and a crash each stopping after two counted relaunches, uncounted before it; a late
relaunch concluding `expired` clearing the count; the half-done abandon `attempted`, the finished one `skip abandoned`,
never re-advanced; two done tasks on one slot checked in release order while new work waits. `test_check_operations`:
`relaunch_checks` launching the admitted attempt uncounted before the deadline, its fences (`changed`, `concluded`,
`released`, `abandoned`, `stale_reservation`) launching nothing, and the late count written before a failed launch.
Mutation-checked: the checks route in `_resume`, the agent launcher in its place, the `failed:` word, the attempts map, the
late count (removed or always), the `admitted` fence, the id fence and the `abandoned` word each fail a test.

**Not verified**: a real `tl step rounds` with real checks entries (the [M2 live smoke](live-smoke.md)); the `lingering`
outcome of a timed-out `sh -c 'sleep 600 & sleep 600'` on the host (the smoke records it); a real launch failure.

### 25.1 Review repairs to S6e (2026-11-11)

An independent review of eba237919 and 4e004864c found the routing, fences, stop sets and words sound and three defects;
each is repaired with a test that fails without it:

1. **A check outliving its dead entry no longer ends `stuck:checks_refused`** (medium). The status counted only the entry:
   an admitted checks attempt whose entry died while a slow check ran was `start`, each round relaunched it and each
   entry's reconcile counted `checks:running`, so within two rounds it was stuck before its deadline, and nothing resumed
   it once the check ended. Now `attempt_status` observes, for an admitted, unreleased checks attempt whose entry does not
   run, the latest setup run's unsettled command and every unsettled result of the latest block through a new
   `StatusPorts.commands` port (the CLI wires `owned_processes.setup_seen`, the entry's reconcile rule: another boot is
   gone; the default for reads that never meet one is gone), aggregated by `check_status.commands_seen`. `checks_next`:
   alive is `wait` (the round reports `check report running`, never relaunches or counts), past the deadline
   `stuck:hung` (nothing enforces a check's timeout once its entry died), unknown is `unknown`; gone relaunches as before.
   `stuck:checks_refused` still takes precedence. Tests: a check (alive, unknown) and a setup command outliving the entry
   across three rounds never counted or relaunched, logged once, `stuck:hung` past the deadline, then relaunched once
   gone; `commands_seen` over setup and settled/unsettled rows.
2. **The round releases a concluded checks attempt left holding its slot** (low-medium; decided by the reviewer). With
   `Next: release` (concluded, not released, the entry not running: `checks_next` gives `wait` while it runs) the round
   calls the settled `ChecksRelease.release(key, abandon=False)` through a new `ChecksPorts.release` (composition's
   `open_checks_releaser`): the full stop proof, never a signal, held while a command of it runs. Words `check release
   released <id>` or `check release held:<why>` / `unavailable:<why>` (the `release` action, new in `Action`), one per
   round, the unchanged line logged once (`quiet`). Agent attempts keep their behavior (a `release` reported). Tests: an
   entry that died after concluding, one still running (reported `running`, released once gone), and a `lingering` check
   held each round, logged once, released once its group ended, then `check report failed:check:lingering`.
3. **The `start` guide** no longer says every unfinished relaunch counts: every refusal the entry counts, while
   uncounted relaunches (a failed or uncertain launch, an entry refusing `identity`, `stale_reservation`, `absent` or
   `unavailable store`, a crash before it counts) repeat each round until the deadline like an agent's, then count
   (`late_relaunch`). `CHECKS_GUIDE` gains `wait` (a check's or setup's group from a dead entry), and its `stuck:hung` and
   `release` texts name the outliving group and the rounds' release retry.

Code lines by the policy counter after the repairs: `round` 252, `operations` 345, `attempt_status` 202, `check_status`
57, `step_guide` 182, `cli_composition` 214; `test_checks_round` 288, `test_check_status` 136, `doubles` 297.
Mutation-checked: `checks_next` ignoring the commands, alive without the deadline, unknown dropped, the setup command not
observed, and the round's release case removed each fail a test.

**Not verified**: the real `setup_seen` against a real check group outliving a killed `taskloop.check_entry` (M2 smoke
section 3's harder variant).
