# tl-8bh9.14.8: land and close (block B6, milestone M3)

Design, 2026-11-11, against 08784fe34 (M2 built, M2 smoke passed and its findings fixed); revised the same day after an
independent review of 365743d89 (section 24). Docs only: nothing built or run. Read: CLAUDE.md, [glossary](../../glossary.md), [roadmap](../self-hosting-roadmap.md) (B4, B6, B7, D1-D14, O1-O6),
[delivery and publication](../tl-8bh9.9/delivery-publication.md), [operations](../tl-8bh9.8/operations.md),
[candidate checks](../tl-8bh9.5.1/candidate-checks.md), [the checks step](../tl-8bh9.14.6/plan.md) (sections 3, 4, 6, 10,
12, 21-25) and its [M2 findings](../tl-8bh9.14.6/m2-smoke-findings.md), and `steps`, `publish`, `check_store`,
`check_entry`, `check_release`, `checks`, `slot_release`, `setup_store`, `operations`, `attempt_status`, `check_status`,
`round`, `composition`, `git_views`, `agent_credentials`, `tracker_client`, `profile`, `factory_schema` (v12),
`tests/rules/test_policy.py`, and the installed `git_porcelain` 0.15.0 and `beads_client` 0.2.0.

The owner is away and asked for autonomous decisions. Each one below is marked **decided here** (a recommendation, open
to veto); owner decisions D1-D14 are cited by number. Section 18 lists blocking owner questions: none.

## 1. What changes for the owner

After `tl step show TASK` says `Result: collected passed` for the check step, the person reads the diff, the `Check:`
lines and the land summary (`tl step land TASK --summary`), then runs **`tl step land TASK`**. The factory fetches
origin's `main`, makes one squash commit S of the checked commit X onto origin's tip O (a commit object only, no
checkout written), and:

- when S's tree is X's tree and `main` requires the same check names as when the checks ran, pushes S at once;
- otherwise (origin's `main` moved past the task's base, or its required names changed) runs every check of the
  profile at S in a free slot, in the foreground, with the checks step's own block, and pushes only if they pass;

then pushes S to origin's `main`, never forced, from the person's checkout with the person's Git credentials, and closes
the task in the tracker. A rerun of the same command does only what is still missing. Nothing lands without this
command: rounds never land. The person's main checkout and local `main` are never written; afterwards the person runs
`git pull --ff-only` in it and, if the tracker is shared, `bd dolt push` (O4).

## 2. Decisions this design respects

D1 (a task may change its own profile and check configuration: the summary lists it), D4 (an abandon restarts at plan),
D5, D6 (rounds never land), D9 (merge plus final squash, one resumable land; one mandatory check set, no pass cache),
D10 (checks on the host with the scrubbed environment and push bar), D11 and O1 as decided in the checks plan (required
names from the target; land re-reads them from the remote target), and the delivery contract: published, landed and
completed are three facts; append-only task branches, never forced; an uncertain push is observed before it is retried;
landed then close failed is "code delivered, task completion pending", retried without re-integration. Candidate checks:
the same candidate does not rerun because delivery starts; a changed integration result is validated before delivery.

## 3. One operation, explicit only (decided here)

`land.land(ports: LandPorts, request: LandRequest) -> Landed | Failed`, one application operation in a new module
`land.py`: the CLI's `tl step land` calls it; a later dashboard calls the same function from its own worker (it may run
for minutes when checks run); nothing else does. It is **never automatic**. Import contracts (slice L3):

- `rounds-never-land` (new, forbidden): `round`, `rounds`, `operations`, `attempt_entry`, `check_entry`, `composition`
  and every module of the entries' closure never import `land`, `land_push` or `land_summary`. So the land's wiring,
  `open_land`, lives in `cli_composition` (which the entries never import), never in `composition` (which `check_entry`
  imports); `open_land` builds on `composition.open_checking`. Status reads `land_store`, which only records.
- `cli-never-imports-the-attempt-entry` gains `land`, `land_push`, `land_summary` and `validate` as sources. The
  land needs the claim renewal that `check_entry` imports from `attempt_entry` today: `attempt_entry.renewal` moves to
  `claim_lease.renewal` (slice L2), imported by both entries and by `land`.

Rounds keep running beside a land; they see its slot reserved and nothing else.

`LandRequest(backlog, task_id, checkout, minutes, mode: Literal["land", "summary", "withdraw"], no_change: bool)`. CLI:

```
tl step land TASK --backlog KEY --checkout PATH --minutes N [--summary | --withdraw] [--no-change] [--db] [--artifacts] [--json]
```

The tracker root is the implement attempt's stored one (as the checks entry renews the claim there), so no
`--tracker-root` flag (decided here: one tracker per task, never a second binding). `--minutes` is the deadline of a
validation block if one runs (required, as for `tl step start`; unused otherwise). `--summary` prints the land summary
(section 10) and changes nothing in factory.db, the slots, the remote or the tracker (it fetches, see section 5).
`--withdraw` gives up a validated, undelivered candidate so the task can be abandoned (section 13). `--no-change`
accepts the no-change disposition (section 5, step 6). Exit codes as every step command: 0 landed (or already), 1
refused, 3 unknown (rerun is safe).

**Foreground, not an entry process (decided here).** Validation runs inside the `tl step land` process, not through a
launched entry: the land is the person's command and waits for its result; rounds must not relaunch it. Restart safety
comes from the same records the checks entry uses (every command's identity committed before it runs, the reconcile
before any slot access), plus the land process's own identity stored on the candidate when it takes the slot's custody
(`entry_pid`, `entry_start`, `entry_boot`, section 11), which every stop proof checks (`slot_release.entry_stopped`) as
it checks a checks entry. No land lock: the factory.db fences of section 11, the slot's custody lock during validation,
and idempotent Git and tracker actions make two concurrent `tl step land TASK` safe (the second refuses `landing` or
finds the work done).

**Interrupts (verified from the installed `stream_proc` 0.6.0).** `run_registered` supervises a command in
`runner._supervise`, which on any unwinding (`except BaseException`) stops the command's tree (`stop_tree`) before it
re-raises. So a Ctrl-C (Python's default `KeyboardInterrupt`; no signal handler, `one-signal-owner` stays true) stops
the running check's tree and ends the land with that result unconcluded; the rerun's reconcile finds it gone, marks it
`interrupted`, and repeats the block. Only a hard kill of the `tl` process (`kill -9`, a crash of the interpreter, a
reboot) leaves a check running in its own session: the rerun then answers `unavailable checks:running` until it ends
(section 12).

## 4. Preconditions, in order, every read before any effect

Refusal words are `refused <word>` (exit 1) unless written `unavailable` (exit 3).

1. `--minutes` valid (`deadline`); this process's environment does not carry the agent's push bar
   (`url.delegate-push-refused://.pushInsteadOf` among `GIT_CONFIG_*`): **`push_barred`** ("land runs from the person's
   own shell"). This only catches an accident (an agent's environment reaching `tl`); it is no security boundary: any
   process can unset the variable.
2. factory.db current (v13), else `unavailable store` / `refused schema`.
3. The task's current agent attempt is a done implement attempt: implement, verified, released `kept`, published at X
   (`admit_chain`'s done-ness reads, shared with `check_admit`), else **`not_done`** naming its `Next`. The plan step is
   implied: an implement attempt 1 exists only as the advance from a verified, published plan (`after_commit`), so land
   does not re-read the plan attempt (decided here).
4. Its latest checks attempt: concluded `passed`, released, not abandoned, else **`not_checked`** with that attempt's
   `Next` and result (a failed one: re-run with `tl step start`, or abandon). With `--no-change` any concluded, released,
   not abandoned checks attempt serves (section 5 step 6).
5. **The latest land candidate** of this checks attempt (section 11), if any, decides where to resume (section 12). A
   candidate still holding its slot is released first (the rerun retries a held release before anything else, closing or
   answering `already_landed` included). A closed one then answers `already_landed` with no Git or tracker call; a
   delivered one goes straight to the close (section 8), whose own `bd show` is its tracker read (no step 6-8 read).
6. The checkout's repository is the attempt's (`checkout`); `origin` exists (`no_remote`). Its fetch and push URLs
   are trusted as the person configured them: no URL comparison (decided 2026-11-12, section 29.3).
7. **X is still the task's work** (skipped with `--no-change`): the local `task/<id>` (else the remote-tracking one) is
   exactly X, and origin's `task/<id>` is exactly X (one `ls_remote` with the two patterns `refs/heads/main` and
   `refs/heads/task/<id>`). Ahead of X or elsewhere is **`branch_moved`** ("commits after the checked X: abandon and
   restart, or reset the branch"): land lands exactly what was checked. X unreadable is `commit_missing`.
8. One tracker read (`admit.read_task`): `in_progress` assigned `taskloop`, else **`claim_lost`**. `closed`: when a
   pushable candidate exists (section 11: validated, not delivered, not superseded) origin is read first by section 7's
   delivery rule: delivered is recorded, then `already_closed`; otherwise, and with no candidate, **`closed`** ("closed in
   the tracker without a land").

The checks attempt's claim is kept by the implement attempt's release; land neither claims nor unclaims (a `bd unclaim`
would reopen the task). Its close ends the claim.

## 5. The candidate S (one squash commit, no checkout)

Letters (glossary additions): **O** is origin's target tip as the land fetched it; **S** is the land candidate, one
commit whose parent is O and whose tree is X merged onto O. T keeps its meaning (the remote tip after a push: after the
land's push T is S).

1. **Fetch** `+refs/heads/main:refs/remotes/origin/main` through the `remotes` view of the person's checkout, with
   `timeout=PUSH_TIMEOUT` passed explicitly (git-porcelain's `fetch` takes its own timeout; the view's `remote_timeout`
   bounds pushes and `ls_remote`). Hooks off, the person's config and credentials: a remote-tracking ref, as the person's
   own `git fetch` writes it; never a local branch, index, HEAD or worktree. A failed fetch raises `GitUnavailable`
   (never a `Transient` value): `unavailable remote`. O is the fetched remote-tracking ref; origin without `main` is
   `refused target`.
2. **The target profile at O** (`profile.read_profile` on the checkout's `GitProfileFiles` at O): `Refused` is
   `target_profile`; its `target` must be `main` (another land branch is not built: `target`); `required` non-empty
   (`no_required`). The required list at O is stored with each name's argv digest at O (`check_store.required_json`).
3. **Squash** through a new git-porcelain operation (slice L0): `Repo.squash(onto=O, head=X, message) -> Squashed(sha,
   tree) | Conflicted(paths)`, object writes only (real: `git merge-tree --write-tree` then `git commit-tree -p O`; the
   person's `user.name`/`user.email` as author and committer; no hook, no signing). `Conflicted` is **`conflict`** with
   the first 20 paths and a count; nothing is recorded. The commit message is section 9's.
4. **Same tree?** S's tree listing equals X's: `Repo.tree(S).files == Repo.tree(X).files` (path to mode and blob, on the
   real and the fake alike; no new Git API, section 24 finding 12). True exactly when O is an ancestor of X, or main's
   changes were already in X.
5. **Required names changed?** The set of names required at O differs from the checks attempt's stored names.
6. **No change**: S's tree listing equals O's (main already holds X's changes, for example a hand land) is
   **`no_change`** unless `--no-change` is given. With it, whatever the task branch's state (step 7 of section 4 is
   skipped) and whatever the checks attempt concluded, the candidate is recorded with `validation` and `delivery`
   `no_change` (no slot, no push) and section 8 closes the task with the reason "Already on main at O" (the delivery
   contract's explicit no-change disposition). `--no-change` when S's tree is not O's is refused `changes` (there is
   something to land).

**When the checks run again (decided here): exactly when (4) is false or (5) is true**, the whole block (every check of
the profile at S, required or not) in a slot, with the checks step's machinery. Not when S's tree is X's and the names
are unchanged: that is the same candidate whose pass the checks attempt recorded (candidate checks: entering land does
not rerun an unchanged candidate), and S differs from X only in its parent. The rule is a tree comparison, never a pass
lookup across candidates (D9). **What it costs:** one setup plus one block per land whose target moved, in the
foreground (about 90 s in the M2 smoke: setup 10 s, `test` 20 s, a 60 s `slow` check); with several slots, every land
after the first of a batch moves `main` for the others, so each later land of the batch pays one block. A free slot is
needed for its duration (`no_free_slot`, unavailable: rerun, or stop rounds to free one).

## 6. Validation of S in a slot

Only when section 5 says so. In order:

1. **Insert the candidate** (one write transaction, section 11's fences): `admit.reserve` of a free slot
   (`admit.free_slots`, D its HEAD) and `land_store.insert` (O, S, `tree_same`, the required list, the deadline `now +
   --minutes`, the slot). Without validation: no slot, no reservation, `validation='same_tree'` at insert.
2. **Custody** of the slot (`slot_lock`, never waiting: `unavailable slot_busy`, which is also what a second concurrent
   land of the task meets), held to the release; under it, the land process's identity is written on the candidate
   (`land_store.hold(key, identity)`, fenced like `register_entry`: replaced only when the stored one is gone).
3. **Claim keep-alive**: one renewal (`claim_lease.renewal`; `lost` concludes `failed claim_lost` after the
   reconcile), then `claim_lease.keeping` for the setup and the block, as the checks entry.
4. **The shared validation flow** (slice L2 extracts it from `check_entry` into `validate.py`, unchanged in behavior for
   checks): the reconcile of the latest setup run and the latest block's unsettled results (alive `unavailable
   checks:running`, unknown `checks:unknown`, gone `interrupted`); the deadline (`expired`); the profile at S on the slot's
   pinned view (`profile:<reason>`), its digest stored once (`land_store.profiled`); a completed latest block concluded
   as it stands; S taken detached (`prepare.detach_at`); reset to exactly S and `setup` at S (`environment.prepare_for`,
   no probe, no reuse); the block (`checks.Block.run` with `BlockTarget(slot, view, S, required at O, deadline,
   check_env(scrubbed))` and `CheckSink(store, candidate key, files, clock)`); the conclusion from the latest block
   (`checks.conclusion`). The one difference from checks: no local `main` watch (`moved` is None for land). The required
   names were read from the remote target's immutable objects at O, and the push itself verifies O (section 7), so a
   rewritten local ref cannot make a land pass.
5. Section 6.1 of the checks plan maps the words: a terminal one concludes the candidate `failed <reason>`
   (`land_store.conclude`); a relaunchable one leaves it pending and the land answers `unavailable <word>` (no counter:
   nothing relaunches a land but the person).
6. **Release** of the slot under the lock it holds (`check_release`'s release, generalized over its target in L2, `me`
   the land's own identity): the stop proof, the reset to S, the park at D, the record, `slot_release.free`, the scratch
   emptied. A held release (`held:check_running`, `held:slot_dirty`) leaves `Next: release` (section 14); a passed land
   still pushes, and every rerun retries the release first.
7. Passed goes on to section 7. Failed answers **`checks_failed`** with the reason (`<name>:<conclusion>`, `setup:...`,
   `expired[:<name>]`, `claim_lost`, ...) and the log paths; nothing is pushed.

A rerun of `tl step land` with a pending candidate renews its deadline to `now + --minutes` (one fenced update: the
person's new command is new consent) and resumes at step 2. Its results go to `check_result` and its setup runs to
`setup_run` under the candidate's key (section 11); its logs are `check-<block>-<name>.log` and `setup-<run>.log` in the
candidate's evidence directory.

## 7. The push and the delivery rule (non-forced, resumable)

Through `land_push.py` (new; it shares `publish._relation` and the `remotes` view).

**The delivery rule (decided here, one rule for the first try and every resume).** Delivery is recorded only from (a) a
`Pushed` answer for S, or (b) origin's `main` as read by `ls_remote` or by the bounded fetch. Never from the local
remote-tracking ref without that fetch, never from a log. `origin` is trusted as configured (section 29.3): the reads
and the push go where the person's Git configuration sends them, and a person who points them at different
repositories owns that choice. With R the `ls_remote` answer for `refs/heads/main`:

1. **R is S**: delivered; record `pushed` with `remote_head` S (the answer says `already_pushed`).
2. **R is O**: push (step 4 below).
3. **Anything else**: fetch (section 5 step 1, bounded, `GitUnavailable` is `unavailable remote`), then ancestry on the
   fetched tip F: S an ancestor of F is delivered (someone built on it): record `pushed` with `remote_head` F, which
   contains S. Otherwise the candidate is **superseded** (`superseded='moved'`, section 11): O is no longer origin's tip
   and S is not in it. If this invocation has not yet made a candidate, it makes candidate N+1 onto F (section 5, then
   section 6 when its tree differs) and returns to step 1 for it; if it already made one, it answers **`target_moved`**
   ("main moved during the land; rerun"). At most one new candidate per invocation (decided here), so a busy `main` costs
   a rerun, never an unbounded loop.
4. **Push** S with the existing push port, exactly as `publish` pushes `task/<id>`:
   `repo.worktree(checkout).push("main", remote="origin", head=Sha(S))` from the person's checkout, never forced, no
   force-with-lease, no refspec with `+`, hooks off. Git's fast-forward rule is the condition (section 24 finding 10):
   the update is accepted only while origin's `main` is an ancestor of S. `Pushed` records `pushed` (`remote_head` S) in
   one fenced transaction (section 11). `RefRejected`: back to step 1 with a new `ls_remote` (another lander won: step 3).
   `Transient` is `unavailable remote`; `RemoteRejected` is **`remote_rejected`** ("origin refused by its own policy, for
   example a protected `main` that requires a pull request; PR mode is held: push by hand to see why"); `HookRejected` is
   `unavailable git`.
5. **Uncertain acknowledgment** (the process died, `Transient` after the remote updated): nothing recorded; the rerun's
   step 1 or 3 observes origin and records it. A second push of S to a remote at S changes nothing.

**Accepted race (decided here):** the push names no expected old tip (no lease: a lease is a force option, and every
factory push stays non-forced). The fast-forward rule refuses any `main` that is not an ancestor of S; the one case it
accepts that a lease would refuse is an origin `main` rewound by a force push to an ancestor of O between the
`ls_remote` and the push (seconds), where landing S puts O's commits back. The roadmap's "naming the expected old tip" is
met by step 2's read immediately before the push plus that rule.

The factory's push to origin's `main` (O3, decided here as the roadmap recommends): only from `tl step land`, with the
person's credentials through their Git configuration (SSH agent, credential helper, `insteadOf` rules apply as in their
shell); never from rounds or an entry (section 3).

**`--withdraw`** reads origin by the same rule and never pushes: delivered is recorded (and the answer is `landed`:
nothing to withdraw); otherwise the latest validated candidate is marked `superseded='withdrawn'` and the abandon of the
task is possible again (section 13).

## 8. Close the task (tracker port), and tracker sync (O4)

`TrackerClaims` gains `close(tracker_root, task_id, reason) -> Closed | ClosedBefore | CloseLost | CloseUnavailable`
(`tracker_client`: one tracker read, `Bd.show`; `closed` is `already_closed`; else `Bd.close(task, reason,
if_assignee="taskloop")`, its fence a same-value update; `BdError` of kind `precondition`/`not_claimable` is `claim_lost`,
any other `unavailable tracker`). Reason: `Landed <S> on main (task/<id> at <X>)`, or `Already on main at <O>` for a
no-change land. Recorded once (`closed_at`, `close`), fenced on the delivered candidate.

**`bd close` on a closed task (measured, bd 1.3.1, a scratch tracker under `~/tl-smoke`, removed afterwards):** closing
an already closed bead as its assignee exits 0 and changes nothing (the first reason and `closed_at` stay), and the
same-value assignee update that `beads_client` uses as the fence also exits 0 on a closed bead. So two concurrent lands
that both reach the close both succeed, the second as a no-op; the read first makes the second record `already_closed`
in the usual case. Also measured: `bd close` refuses an actor other than the assignee ("cannot close ...: assignee is
\"taskloop\", actor is ...; reclaim or use --force"), which is why the close runs as the `taskloop` actor (`Bd(ACTOR)`).

After a push, a failed close leaves the candidate delivered and the task open: `tl step show` says `Pushed:` and `Next:
land`; the land answers `unavailable tracker` (rerun) or `refused claim_lost` ("the code is on main; close the task by
hand with `bd close`; a rerun then records it `already_closed`"). A rerun goes straight to the close: no fetch, squash,
check or push.

**Tracker sync (O4, decided here): never automatic.** Land closes the task in the person's local tracker only. Its
answer always ends with `Tracker: closed locally, not synced (bd dolt push shares it)`; the factory never runs `bd dolt
push`, `bd sync` or any remote tracker operation (a remote operation needs its own authority, as Git pushes do; one
machine needs none). Land is complete for the factory once the close is recorded.

## 9. The commit message

Built by `land_summary.message` from typed values, never from logs:

```
<title> (<task-id>)

Squashed from task/<task-id> at <X>:
- <subject of each commit of merge-base(O, X)..X, oldest first> (<12-char sha>)

Task: <task-id>
Plan: docs/design/<task-id>/plan.md
Checked: <checks attempt id> passed at <X>
```

The title is the tracker's (`TaskInspection.title`, read in section 4 step 8): one line, control characters dropped,
cut to 72 characters. The commit list comes from `Repo.history([X], not_on=[merge-base])`, at most 50 lines then
`- ... and <n> more`. `Plan:` is present when the file exists at X. A validation of S cannot be named in S's own message (S is made before
its block); factory.db links them (`land_candidate`). Author and committer are the person (their Git identity); no co-author trailer (decided here: the factory does not
attribute agents in landed commits; the task branch keeps the agent's commits).

## 10. The land summary (`--summary`, and printed before every land)

`land_summary.summary(...)` from the profiles at O and X, the checks attempt's rows, and one diff
(`Worktree.diff(merge-base(O, X), X)` on the person's checkout: the task's own changes, not main's):

1. The checks attempt for exactly X: its id, conclusion, its target, and each required name with its result.
2. The required names at O against the checks attempt's: `same`, or each added and removed name (then the checks run
   again).
3. Each required check whose argv at X differs from its argv at O, both argv shown (`shlex.join`).
4. *(Superseded by section 30.1: the gate facts, S against O.)* Checks added, removed or changed at X against O (they ran
   on the host too), and a changed `setup` (both shown).
5. *(Superseded by section 30.1: the shape rule and weakened tests.)* Every changed check-configuration file between
   merge-base(O, X) and X: `.task-loop.json`, `justfile`,
   `pyproject.toml`, `uv.lock`, `mise.toml`, `.importlinter`, anything under `tests/rules/`, any `conftest.py`, and any
   tracked file a check's argv at X names (an argv element that is a path in X's tree).
6. O, whether S's tree is X's (`same tree as X`, or `merged onto a moved main: checks run again`), a conflict's paths, or
   `no change`.
7. The commit message (section 9), and the diff command for the person: `git diff <merge-base>..<X>`.

`--summary` makes the squash tree (objects only, to report a conflict and the same-tree answer) but no candidate, no
reservation, no push and no close. Facts only: no judgment of whether a change is safe.

## 11. Schema v13 (no migration; v12 is refused `schema`)

```sql
CREATE TABLE land_candidate (
 candidate_id TEXT PRIMARY KEY, dispatch_token TEXT NOT NULL UNIQUE, generation INTEGER NOT NULL,
 checks_attempt_id TEXT NOT NULL REFERENCES checks_attempt(attempt_id),  -- the checks attempt of X it lands
 number INTEGER NOT NULL CHECK(number >= 1),                             -- 1, then + 1 per new candidate
 origin_commit TEXT NOT NULL CHECK(length(origin_commit) IN (40,64)),    -- O: origin's main as fetched
 commit_sha TEXT NOT NULL CHECK(length(commit_sha) IN (40,64)),          -- S
 tree_same INTEGER NOT NULL CHECK(tree_same IN (0,1)),                   -- S's tree is X's
 required TEXT NOT NULL,                                                 -- JSON [[name, argv digest at O], ...], 1..32
 slot TEXT, slot_head TEXT CHECK(slot_head IS NULL OR length(slot_head) IN (40,64)),  -- the validation slot and its D
 deadline REAL, profile_digest TEXT CHECK(profile_digest IS NULL OR length(profile_digest)=64),
 entry_pid INTEGER, entry_start TEXT, entry_boot TEXT,                   -- the land process holding the slot's custody
 validation TEXT CHECK(validation IS NULL OR validation IN ('same_tree','no_change','passed','failed')),
 reason TEXT, validated_at REAL,
 released_at REAL, parked TEXT CHECK(parked IS NULL OR length(parked) IN (40,64)),
 superseded TEXT CHECK(superseded IS NULL OR superseded IN ('moved','withdrawn','gone','abandoned')), superseded_at REAL,
 delivery TEXT CHECK(delivery IS NULL OR delivery IN ('pushed','no_change')), delivered_at REAL,
 remote_head TEXT CHECK(remote_head IS NULL OR length(remote_head) IN (40,64)),
 close TEXT CHECK(close IS NULL OR close IN ('closed','already_closed')), closed_at REAL,
 rev INTEGER NOT NULL DEFAULT 0,
 CHECK((slot IS NULL) = (slot_head IS NULL) AND (slot IS NULL) = (deadline IS NULL)),
 CHECK((slot IS NULL) = (validation IS NOT NULL AND validation IN ('same_tree','no_change'))),
 CHECK((validation IS 'no_change') = (delivery IS 'no_change')),
 CHECK((validation IS NULL) = (validated_at IS NULL)), CHECK((validation IS 'failed') = (reason IS NOT NULL)),
 CHECK((entry_pid IS NULL) = (entry_start IS NULL) AND (entry_pid IS NULL) = (entry_boot IS NULL)),
 CHECK(entry_pid IS NULL OR slot IS NOT NULL),
 CHECK((released_at IS NULL) = (parked IS NULL)), CHECK(released_at IS NULL OR slot IS NOT NULL),
 CHECK((superseded IS NULL) = (superseded_at IS NULL)), CHECK(superseded IS NULL OR delivery IS NULL),
 CHECK((delivery IS NULL) = (delivered_at IS NULL)), CHECK((delivery IS 'pushed') = (remote_head IS NOT NULL)),
 CHECK(delivery IS NULL OR (validation IS NOT NULL AND validation IN ('same_tree','no_change','passed'))),
 CHECK((close IS NULL) = (closed_at IS NULL)), CHECK(close IS NULL OR delivery IS NOT NULL),
 UNIQUE (checks_attempt_id, number)
);
CREATE UNIQUE INDEX land_delivered ON land_candidate(checks_attempt_id) WHERE delivery IS NOT NULL;
```

Every CHECK is written so that a NULL operand cannot make it pass vacuously (SQLite accepts a CHECK that evaluates to
NULL): comparisons with a nullable column use `IS`, `IS NULL`, or `IS NOT NULL AND ... IN (...)`; L1 tests each CHECK
with the NULL case.

`check_result` loses `REFERENCES checks_attempt(attempt_id)`: its `attempt_id` names a checks attempt or a land
candidate (both uuid4 hex), as `setup_run`'s already names an attempt or a checks attempt. Nothing else in v12 changes.
**What else batches into v13 (decided here): nothing**; B7 has no design yet (if its DDL is settled before L1 is built,
it joins v13 so the owner discards once).

**What the rows mean.** One row per candidate; "latest" is the highest `number` of one checks attempt. A no-change
candidate has no slot and is inserted with `validation` and `delivery` both `no_change`. A candidate is:

- **pending** while it holds a slot with `validation` NULL;
- **pushable** when `validation` is `same_tree` or `passed`, `delivery` NULL and `superseded` NULL;
- **superseded** with a reason: `moved` (a land read origin: O is not its tip and S is not in it), `withdrawn`
  (`--withdraw`), `gone` (S unreadable, pruned), `abandoned` (a pending candidate released by an abandon). A superseded
  candidate is history; the next land makes a new one;
- **delivered** with `delivery`; at most one per checks attempt (the partial unique index), never superseded.

No task fact is copied: every read joins `checks_attempt` and `attempt` for the task, repository, tracker root and X,
as `check_store` does.

**Fences** (`land_store`, the one writer of `land_candidate`):

- `insert`, in the transaction that reserves the slot: the checks attempt is the latest of its implement attempt,
  released, not abandoned, and `passed` (any conclusion for `no_change`); the implement attempt is current
  (`factory_schema.SUCCESSOR`'s `LATER` part) and its claim `kept`; no candidate of it is delivered; the latest
  candidate is neither pending, nor pushable, nor holding a slot; `number` is the latest + 1 (a lost race is `landing`).
- `hold` (the land's identity, under the slot's custody), `renew`, `profiled`, `conclude`: `land_store.HELD`, the
  candidate pending and its reservation held at its generation.
- **Results and setup runs of a candidate**: `check_store.HELD` stays the checks fence for the checks attempt's own
  writes (`refused`, `profiled`, `conclude`, `record_release`, `abandon_released`). A second constant,
  `check_store.RESULT_HELD` = the checks fence `UNION ALL land_store.HELD` (key bound twice), fences only the result and
  block writes (`_new`, `_changed`, `block`, `registered`; and through them `start`, `undefined`, `finish`), so
  `CheckSink` serves a candidate key unchanged while no checks-attempt update can match a candidate's key.
  `setup_store.HELD` becomes the three-way union (key three times).
- `record_release` (in `check_release`'s transaction), `supersede` (fenced: not delivered, not already superseded),
  `record_delivery` (fenced: not superseded, the checks attempt not abandoned; a refusal after a `Pushed` answer is
  `refused abandoned` with "S is on origin main; inspect": by `LANDING` below it cannot happen, and is tested to
  refuse), `record_close` (fenced: delivered).
- **The abandon fence** `factory_schema.LANDING`: a checks attempt cannot be abandoned while a candidate of it is
  delivered (`landed`), or holds a slot, or is pushable (`landing`). `check_store.record_release(..., abandoned=True)`
  and `abandon_released` add `NOT LANDING` and return a word instead of a bool: `abandoned`, `landed`, `landing` or
  `changed`; `check_release` maps `landed` and `landing` to `refused` with their guide (rerun `tl step land`, or `tl
  step land --withdraw`). Both race orders are fenced: an insert or a delivery requires the checks attempt not
  abandoned; an abandon requires no pushable, slot-holding or delivered candidate. A delivery can therefore only follow a
  pushable candidate, and a pushable candidate blocks the abandon until a land records the delivery or supersedes it.

**Writers** (`test_policy.WRITERS`): `CREATE TABLE land_candidate` and `CREATE INDEX land_candidate` by
`factory_schema.py`; `INSERT`/`UPDATE` of `land_candidate` by `land_store.py`. The policy's `WRITE` pattern does not see
`CREATE UNIQUE INDEX` today: L1 extends it to `CREATE (UNIQUE )?INDEX <name> ON <table>` (kind `CREATE INDEX`, the
table after `ON`) with a spelling test. `GIT_WRITES` gains `squash` (owner `land.py`); `fetch` and `push` gain the owner
`land_push.py` (`push` keeps `publish.py`).

## 12. Restart and recovery: a rerun does only what is missing

| Interrupted after | factory.db | The rerun |
|---|---|---|
| nothing written (fetch, squash, a refusal) | no candidate | starts over |
| any point, the slot still held | the latest holds its slot | the release first (stop proof with the stored land identity: a live land process is `held`; a dead one passes), then the row below |
| a same-tree insert, or a passed validation | pushable | section 7's delivery rule: R = S records; R = O pushes; else fetch and ancestry: delivered, or superseded and candidate N+1 in the same invocation |
| part of a block: Ctrl-C | pending, the check's result unfinished (its tree stopped by `stream_proc`) | deadline renewed; the reconcile finds it gone, `interrupted`; the block repeats whole |
| part of a block: `kill -9`, crash, reboot | pending, slot reserved, a check may still run | deadline renewed; custody taken (the dead process's lock is gone), identity replaced; reconcile: still running is `unavailable checks:running` (nothing changed) until it ends, then the block repeats; a completed block concludes as it stands |
| the push sent, its answer lost | pushable | the delivery rule: S on origin is recorded `already_pushed`, never pushed again |
| the push recorded | delivered | straight to the close |
| `bd close` done, its record lost | delivered, not closed | tracker read: `closed` is recorded `already_closed` |
| the close recorded | delivered and closed | `already_landed` (after a held release is retried), nothing else called |
| S pruned by `git gc` (a candidate left unpushed for weeks) | pushable | S unreadable: superseded `gone`, candidate N+1 |
| factory.db discarded after the push | nothing | `refused not_done` (no done attempt): the person closes the task by hand; origin's `main` has S, its subject names the task. No reconstruction (CLAUDE.md) |

There is no exactly-once across Git and the tracker: each external effect is observed before it is repeated, and the
record follows the observation.

## 13. Abandon, release and D4

- **Before a delivery**: `tl step release --abandon TASK` goes land candidate first, then the checks attempt, then the
  implement attempt (`operations.release_task` gains the first half). A candidate holding its slot that is not pushable
  (pending, or `failed`) is released in abandon mode (the generalized checks release: stop proof including the stored
  land identity, reset to S, park at D) and marked `superseded='abandoned'` in the same transaction; then the existing
  order. A failure between halves shows `Next: release`; rerunning `--abandon` finishes. D4 applies: the next start is
  a fresh plan.
- **A pushable candidate** (validated, not delivered, not superseded) refuses the abandon **`landing`**: S may already be
  on origin. The person runs `tl step land` (which delivers and closes) or `tl step land --withdraw` (which reads origin:
  delivered is recorded, else the candidate is superseded `withdrawn`); then the abandon proceeds. `--withdraw` pushes
  nothing, so it skips the branch rule (section 4 step 7): a moved `task/<id>` never blocks the way out (L3 review).
- **After a delivery**: the abandon refuses **`landed`**: the code is on `main`; `tl step land` finishes the close.
- **Scope (L1 review repair)**: `LANDING` and `LANDED` look at every candidate of the checks attempt's implement attempt
  (of any of its checks attempts), and the checks admission refuses a re-run (`landed`, `landing`) while one is
  delivered, holds its slot or is pushable. Otherwise a no-change land delivered on a failed checks attempt whose close
  failed, followed by a checks re-run, would let the re-run's abandon return the claim with the code on `main`, and a
  candidate of the re-run could be delivered a second time. `--no-change` stays allowed on a failed checks attempt.
- **A superseded candidate** is always validated first (`supersede` is fenced on a validation): a pending candidate is
  superseded only `abandoned`, by its abandon release. A superseded candidate still holding its slot is released by
  either release mode (`tl step release`, or the abandon, which keeps its reason).
- **`tl step release TASK`** (settled) with a concluded candidate still holding its slot releases it, so a person can
  free a slot a land left held without landing (a candidate whose land process still runs is `held` by its identity).
- **A failed land validation** leaves the task `Next: land`: rerun (flaky: a new candidate runs the block again), or
  abandon (D4: plan, implement on the current branch, checks, land). **A conflict (decision tl-8bh9.14.30, trial 2 F1):
  one path, a new chain on the current `main`.**
  The task branch is the chain's memory (an existing local, else remote-tracking, `task/<id>` is resumed as it is) and a
  new branch starts at the person's local `main`, so a hand merge or an abandon alone reuses X's stale base and
  conflicts again. The conflict refusal prints the commands with the real id and X (`land_guide.restart`): `git switch
  main && git pull --ff-only` (if it cannot fast-forward, local `main` holds commits origin lacks: push or move them
  first); `git branch -m task/<id> old/<id>-<first 12 of X>` (a name per X, so a second recovery never meets the first's);
  `git push origin --delete task/<id>` (drops the remote-tracking ref; the old commits then stay only in the checkout);
  `tl step release <id> --abandon`; `tl step start <id>`. Plan and implement run again on the new `main` (two agent runs),
  the checks run on the new X, and the land squashes it clean unless `main` moved again. No typed re-base step is built.
  `test_conflict_recovery` runs the abandon (the real
  `release_task` over a passed checks attempt), the land of the restarted chain and a second conflict's recovery.
- **A hand land** (the M2 way) is reported by the next `tl step land` as `no_change`; `--no-change` records it and
  closes the task, whatever the task branch holds. `--no-change` never validates or pushes (L3 review): a pending
  candidate refuses it `landing`; a pushable one is read by section 7's rule without a push (on origin: delivered is
  recorded; origin's `main` still its O: `changes`, S is what to land; moved past it: superseded `moved`), then the
  no-change candidate is made (`changes` when S's tree is not O's).

## 14. Status: `tl step show`, `list`, `Next`; rounds untouched

`attempt_status`: when the view is a released checks attempt, `land_store.latest(checks attempt)` and its latest
block's results fill `AttemptView.land: LandView | None`. `Next` (the checks view's `done` when passed):

| State | `Next` |
|---|---|
| the latest candidate still holds its slot, delivered or closed or not | `release` (`tl step land` retries it, or `tl step release TASK`) |
| passed checks: no candidate, the latest superseded, pending, pushable, failed, or delivered and not closed | `land` |
| delivered and closed, slot released | `landed` |
| superseded `abandoned`, the checks attempt not abandoned (an abandon stopped half way; section 29.1) | `release` |
| failed checks attempt, no candidate | `done` (unchanged) |

`round._settle` treats `land` and `landed` as silent (`case "land" | "landed": return`). A land's `release` reaches the
existing default case, a `report release` move logged once (`quiet`); the round's checks-release case is guarded by the
checks attempt being unreleased, so the round never releases a land's slot (tested). `tl step show` adds, after the check
step's lines (JSON key `land`, null without a candidate):

```
Land: candidate 2 (<id>) onto origin main at <O>: <S>; merged onto a moved main, checks run again
Land required: check, test (origin main at <O>; same as the checks)
Land slot: s2, released 2026-11-12 10:03:10 UTC, parked at <D>
Land check: check passed, exit 0, 1 s; log <dir>/check-1-check.log
Land check: test passed, exit 0, 20 s; log <dir>/check-1-test.log
Land result: passed
Pushed: origin main at <S>, 2026-11-12 10:03:12 UTC
Closed: 2026-11-12 10:03:13 UTC (closed)
Next: landed
```

A same-tree candidate prints `...: <S>; same tree as X, no checks` and no slot or check lines; a superseded one adds
`Land superseded: moved|withdrawn|gone|abandoned`; while its land process runs, `Land process: running (pid ...)`. After
`already_pushed` by observation, `Pushed:` shows the recorded remote head (which contains S). `tl step list`: the `Next`
word only. GUIDE gains `land` ("read the diff and `tl step land TASK --summary`, then `tl step land TASK`"), `landed`
("nothing left; `git pull --ff-only` in your checkout"), a land's `release`, and one sentence for each new refusal word.
`STEP_ONLY` names `land`.

## 15. Security

- **Who pushes**: the `tl step land` process, from the person's checkout, with the person's environment, Git
  configuration and credentials (`remotes` view: no push bar, hooks off, bounded transport, no prompt). Only the existing
  push port, never forced, pinned to S. Rounds and entries cannot import land (section 3). An agent session in the
  person's shell can run `tl step land` as a person can: by CLAUDE.md that needs the person's explicit authority for
  remote publication; the factory cannot tell who typed the command, and the `push_barred` refusal only catches an
  agent's environment by accident.
- **What runs before the push**: a validation block runs the candidate's `setup` and checks on the host (D10, accepted),
  as the checks step did; S combines only code the person read (X's diff) with code already on `main`.
- **Accepted residual (D10)**: code run by a block shares the repository's Git directory with the person's checkout
  and could edit `.git/config` (a `pushurl`, `pushInsteadOf`, `insteadOf`, `core.sshCommand`) before the land pushes
  with the person's credentials. Land trusts `origin` as configured and compares no URLs (decided 2026-11-12, section
  29.3, which removed the earlier `push_url` refusal); a later review of the change set for suspicious code (roadmap
  section 6, deferred) is the place for it.
- **Remote truth, not local refs**: O and every delivery decision come from `ls_remote` and the bounded fetch of
  `origin`; the required names from O's objects; a block rewriting a local ref changes nothing land relies on.
- Unsigned commits only (`hardened` views): a target that requires signed commits answers `remote_rejected`.

## 16. Failing-land routes

| Answer | What the person does |
|---|---|
| `not_done`, `not_checked` | Finish the steps (`tl step show`), re-run failed checks with `tl step start`, or abandon |
| `branch_moved` | Reset `task/<id>` (local and origin) to X, or abandon and restart (D4) to check the new commits |
| `conflict` | A new chain on the current `main`: pull `main`, set `task/<id>` aside locally and on origin, abandon, start (section 13) |
| `checks_failed` | Read the `Land check:` logs; rerun `tl step land` (flaky), or restart as for a conflict |
| `target_moved` | Rerun: a new candidate onto the new `main` (validated if its tree differs) |
| `no_change` | Confirm `main` holds the work, then `tl step land --no-change` |
| `changes` (from `--no-change`) | There is something to land: drop `--no-change` |
| `remote_rejected` | Origin's policy (protected `main`, signed commits): land by hand or change the policy; PR mode is held |
| `claim_lost`, `closed` | Another actor owns the task: inspect it in the tracker; a pushed land needs only `bd close` |
| `push_barred` | Run land from your own shell |
| `target`, `target_profile`, `no_required` | Fix `main`'s `.task-loop.json` |
| `unavailable remote`, `tracker`, `store`, `git`, `slot_busy`, `no_free_slot`, `checks:running`, `checks:unknown` | Rerun later (a free slot: wait for one or stop rounds) |
| `landed` (from `--abandon`) | Rerun `tl step land` to finish the close |
| `landing` (from `--abandon`) | `tl step land` to land it, or `tl step land --withdraw`, then abandon |

## 17. Glossary changes (slice L5)

| Term | Meaning |
|---|---|
| land (as built) | `tl step land TASK`: the person's command that squashes the checked X onto origin's `main` as one commit S, validates S when its tree is not X's or `main`'s required names changed, pushes it never forced, and closes the task; a rerun does only what is missing. Never run by rounds. |
| landed | The land's end: S (or the no-change disposition) delivered to origin's `main` and the task closed in the local tracker. `Next: landed`. Tracker sync stays the person's (O4). |
| land candidate | One squash S of X onto one O, with its validation (`land_candidate`): `same_tree`, `no_change`, or a block's `passed`/`failed`; pending, pushable, superseded or delivered; numbered per checks attempt; at most one delivered. |
| land summary | The facts printed before a land (`--summary`): the checks, the required names at O, changed argv, checks and `setup`, changed check-configuration files, the commit message. Facts, no judgment. |
| O, S (commit letters) | O: origin's target tip as the land fetched it (`land_candidate.origin_commit`). S: the land candidate (`commit_sha`). |

Also: `Next` gains `land` and `landed` (and a land's `release`); `land` replaces the roadmap's "not built" row; `check
result` and `block` say a land candidate's block uses the same rows; `result sink` names `CheckSink` for both; the `T`
row says after a land T is S; STEP_ONLY and the CLI flags table (`--summary`, `--withdraw`, `--no-change`).

## 18. Owner questions

**Blocking: none.** Decided here, each built so unless vetoed:

1. **O3**: the factory pushes to origin's `main` only from the person's `tl step land`, a direct squash push, no PR.
2. **O4**: land never syncs the tracker; it says so and names `bd dolt push`.
3. **Validation on a changed result only**: the whole block on S when S's tree differs from X's or the required names
   changed; none otherwise (no pass lookup: the same tree). Cost in section 5.
4. **Foreground validation**, no entry process, no relaunch, no land lock; the land process's identity on the candidate.
5. **At most one new candidate per invocation** (`target_moved`: rerun).
6. **`branch_moved` when `task/<id>` holds commits after X**, locally or on origin: land lands exactly X.
7. **`--no-change`** for a target that already holds X's changes, whatever the branch; refused without it.
8. **Squash in Git objects** through a new git-porcelain operation (slice L0), never in a slot or the person's checkout.
   Not chosen: `Worktree.record(mode="squash_to")` and `rebase_onto` in a slot (a slot for every land, and a rebase's
   squash rule unverified on a detached HEAD); `history.merge` (an unpinned module function on a path).
9. **Commit message** from the tracker title and the branch's commit subjects; author the person; no co-author trailer.
10. **Branches kept**: land deletes neither `task/<id>` nor anything else.
11. **One delivery rule** (section 7), recorded only from `Pushed` or from origin read by `ls_remote` or the bounded
    fetch; `origin` trusted as configured (section 29.3).
12. **No lease on the push**: the fast-forward rule and the read right before it; the force-push rewind race accepted.
13. **A pushable candidate blocks the abandon** (`landing`) until a land delivers it or `--withdraw` supersedes it.

## 19. Slices (caps: 400 code lines per file, 80 per function, 800 per test file)

Code lines by the policy counter at 08784fe34 in brackets.

| Order | Slice | What | Source | Tests |
|---|---|---|---|---|
| 0 | **L0 shelf: git-porcelain squash and push URL** | git-porcelain 0.16.0: `Repo.squash(onto, head, message) -> Squashed(sha, tree) \| Conflicted(paths)` (real: `merge-tree --write-tree`, `commit-tree`; fake over `fake_merge.merge_trees`; one contract suite) and `Repo.remote_url(remote, *, push=False)` (`remote get-url --push`); the pin bump here. No `tree_id` (section 24 finding 12) | shelf ~+130; here `pyproject`/`uv.lock` | shelf ~+250 (clean, conflict, already merged, same tree, identity, no hook; push URL with `pushurl`, `pushInsteadOf`, `insteadOf`) |
| 1 | **L1 schema v13 and the land store** | DDL (section 11) and column lists; `land_store.py` (`LandRow` joined, `insert`, `latest`, `of_checks`, `hold`, `renew`, `profiled`, `conclude`, `record_release`, `supersede`, `record_delivery`, `record_close`, `HELD`); `check_store.RESULT_HELD` for result and block writes only, `LANDING` in its abandon fences with the word results; `setup_store.HELD` three-way; `WRITERS` and the policy's index pattern | `factory_schema` [153] +50, `land_store` new ~250, `check_store` [~280] +20, `setup_store` [99] +3 | `test_land_store.py` ~460 (each CHECK with its NULL case); `test_check_store` +70 (a candidate key through `RESULT_HELD` only, checks updates never matching it, abandon `landed`/`landing`/`changed`); `test_setup_store` +20; `test_policy` +10 |
| 2 | **L2 shared validation and release** | `validate.py` extracted from `check_entry` (reconcile, profile, completed block, take, environment, block, conclusion; `moved` and `profiled` parameters; `concluded` moved with it): checks behavior unchanged; `attempt_entry.renewal` moved to `claim_lease.renewal`; `check_release.ChecksRelease` over a `ReleaseTarget` port (row read with the entry identity, and record) with the checks target and `land_store`'s (the abandon mode marks `abandoned`) | `validate` new ~175, `check_entry` [~215] -110, `claim_lease` +12, `attempt_entry` -12, `check_release` [~135] +30, `land_store` +25 | `test_check_entry` unchanged and green (the guard); `test_validate.py` ~200; `test_check_release` +110 (a candidate released settled and abandoned, reset to S, park at D, a live land identity held) |
| 3 | **L3 the land operation: candidate, validation, delivery** | `land.py` (section 4's reads, the fetch, the target profile, the squash, the candidate insert with its reservation, the identity hold, the validation driver with the keep-alive and release, the resume table of section 12 without the close); `land_push.py` (section 7: the push URL check (removed, section 29.3), the delivery rule, the push, `--withdraw`); `cli_composition.open_land` (over `composition.open_checking`); `GIT_WRITES` owners; contracts `rounds-never-land` and the extended `cli-never-imports-the-attempt-entry` | `land` new ~270, `land_push` new ~150, `cli_composition` [214] +40, `publish` +2 | `test_land.py` ~450 (section 4's refusals with nothing written; same tree pushes; moved target validates; required changed validates; conflict; `push_url`); `test_land_resume.py` ~420 (each row of section 12 but the close, concurrent lands, the abandon race both orders, `--withdraw`); `test_land_push.py` ~380 (the delivery rule's three cases, every push result, the fetch failure, the push URL recheck); `real/test_land_real.py` ~200 (a bare origin: same tree, moved main validated with `sh -c` checks, `RefRejected` after a racing push, a `pushurl` refused) |
| 4 | **L4 close, message, summary** | `tracker_client` close port (+18); `land.py` close and record (+45); `land_summary.py` (section 9 message, section 10 summary); `--summary`; `--no-change` | `land_summary` new ~150, `land` +45, `tracker_client` [~70] +18 | `test_land_summary.py` ~300 (each summary item, message bounds and sanitizing); `test_land_close.py` ~260 (close, already closed, two closes, `claim_lost` after push, record lost, `closed` with a pushable candidate, no-change on a moved branch); tracker double +30 |
| 5 | **L5 surface and words** | `cli_step` `land` subcommand and flags (+30), `cli_composition` (+25), `result_data` `Landed` (+30), `show_render` land lines (+50), `attempt_status`/`check_status` `LandView` and `Next` incl. `release` (+45), `round._settle` silent (+2), `operations.release_task` land first (+30), `step_guide` (+35); glossary (section 17), roadmap B6 row, INDEX status; the M3 runbook `live-smoke.md` | about +250 | `tests/cli/test_land_cli.py` ~320; `test_check_status` +80; `test_check_operations` +100 (release and abandon order with a candidate, `landing` and `landed`); `test_checks_round` +50 (rounds silent on `land`/`landed`, report a land's `release`, never release its slot) |
| 6 | **M3 live smoke** | Section 21's runbook, owner-run or by an authorized agent; findings file | none | none |

Total about +1,400 source here (+130 in the shelf) and +3,300 test lines. Largest new functions: the land driver split
into reads, candidate, validation, delivery and close (each under 60); `validate`'s flow keeps `check_entry`'s split.
After the slices: `operations` ~375, `check_store` ~300, `land` ~315, `cli_composition` ~280, `composition` ~146.

Tracker: L0 tl-8bh9.14.8.1, L1 .2, L2 .3, L3 .4, L4 .5, L5 .6, the M3 smoke .7 (children of tl-8bh9.14.8, with the
dependency edges below).

Dependencies: L0 and L1 independent; L2 after L1; L3 after L0 and L2; L4 after L3; L5 after L4; the smoke after L5. Each
slice lands green with `just check` and `just test`, independently reviewed. M3 is reached when the smoke passes.

## 20. Tests (pytest functions, fakes through ports, no process in factory tests)

- **Store** (L1): every CHECK of `land_candidate` with a valid row and its violating rows, the NULL case included (a
  NULL `validation` with a slot, a NULL `validation` with a delivery); the unique delivered index,
  `UNIQUE(checks_attempt_id, number)`; `insert`'s fences one by one (a failed, unreleased or abandoned checks attempt; a
  later implement attempt; claim not kept; a delivered, pending or pushable candidate); `hold` replaced only when gone;
  validation writes off `HELD`; a candidate key's results and setup runs through `RESULT_HELD` and the setup union, and
  `refused`/`profiled`/`conclude` of `check_store` never matching it; `LANDING` refusing both abandon paths with
  `landed` and `landing`; `record_delivery` refused for a superseded candidate and an abandoned checks attempt.
- **Validation and release** (L2): `test_check_entry` passes unchanged after the extraction (mutation: drop the reconcile,
  the completed reading, the deadline from `validate`, each fails a checks test); a candidate validated with `moved` None;
  its release resets to S and parks at D; a live stored land identity holds it; abandon mode marks `abandoned`.
- **Land** (L3, L4), over a factory.db file, the Git fake (origin, `main`, `task/<id>`), the real profile reader, the
  scripted registered start and a tracker double: section 4's refusals in order with nothing written and no remote call
  before the fetch; same tree pushes S (parent O, X's tree, the message) with no slot; a moved `main` reserves a slot,
  runs the block on S, releases, pushes; a changed required set validates although the tree is the same; a failed block
  pushes nothing and leaves `Next: land`; the delivery rule (R = S; R = O; R elsewhere containing S; R elsewhere not
  containing S, making N+1 once and then `target_moved`); a `KeyboardInterrupt` raised by the scripted start (the
  result left unfinished, the rerun marks it `interrupted`); each row of section 12 by stopping the operation at that
  point (a port that raises) and rerunning; `RefRejected`; a racing second land (`landing`, then `slot_busy`); the close
  paths; `--summary` writes nothing (factory.db, slots, remote, tracker unchanged); `--withdraw`; `--no-change` with a
  moved branch; `push_barred`.
- **Real** (L3): a temporary bare origin, a checkout and one slot: the same-tree land (origin `main` at S, its parent O,
  its tree X's), a moved `main` with a passing and a failing `sh -c` check, a conflict, a racing push, a `pushurl`.
- **Surface** (L5): show lines and JSON, `Next` rows (the slot still held after a delivery is `release`), list, the
  abandon order and its rerun, rounds silent.

## 21. M3 live smoke (outline; the runbook is written in L5)

Base: the M2 runbook ([live-smoke.md](../tl-8bh9.14.6/live-smoke.md)) with a new scratch folder `$M3`: runner at the L5
commit, a scratch bare remote whose `main` is that commit, scratch tracker, factory.db new (v13), two slots.

1. Two `auto` tasks A and B through rounds to `Next: land` (both cut from the same `main`). Stop rounds.
2. `TL step land A --summary`: required names `same`, `same tree as X`, the message; nothing changed (factory.db
   `land_candidate` empty; remote `main` unchanged; `bd show`: in progress).
3. `TL step land A`: no slot used; remote `main` at S (`git log -1`: parent the old `main`, subject `<title> (A)`, tree
   X's); `bd show A`: closed with the reason; `TL step show A`: `Pushed:`, `Closed:`, `Next: landed`. The person's
   checkout untouched: `git rev-parse HEAD refs/heads/main` and `sha256sum` of its index file (`git rev-parse
   --git-path index`) equal before and after (not `git status`, which reports the checkout behind the fetched origin).
4. `TL step land B`: `merged onto a moved main, checks run again`; `Land check:` lines while it runs (second shell);
   pushed after `Land result: passed`; slot parked at D and clean.
5. **Interrupt and resume**: task C (cut before A landed, so its land validates).
   - Ctrl-C during its block: the land ends; `ps -g <recorded pgid>` empty (the library stopped the check's tree); the
     rerun marks it `interrupted` and repeats the block.
   - Again with `kill -9` of the `tl step land` pid the person verified (`TL step show`: `Land process: running (pid
     ...)`, matched with `ps`): the check keeps running in its session; the rerun answers `unavailable checks:running`
     until it ends, then repeats the block and lands.
   - Rerun `TL step land A`: `already_landed`, no fetch, push or tracker write (remote `main` and `bd show A` unchanged).
     The window between push and close has no live trigger: tests cover it (section 20).
6. **Moved target during the land**: task D; while its block runs, push a commit to the scratch remote's `main` by hand:
   `target_moved` (the invocation already made its candidate), nothing pushed; the rerun supersedes it (`moved`), makes
   candidate 2 and lands.
7. **Conflict**: task E editing the same line as a hand commit on `main`: `conflict` with the path, nothing recorded.
8. **Refusals**: `--abandon` after A is landed refuses `landed`; a task with a validated, unpushed candidate (stop with
   `kill -9` after `Land result: passed`) refuses the abandon `landing` until `--withdraw`; land from a shell carrying the
   push bar refuses `push_barred`; `remote_rejected` by a scratch `pre-receive` hook on the bare remote refusing `main`.
9. Record findings in `docs/design/tl-8bh9.14.8/m3-smoke-findings.md`.

## 22. Risks

- **A busy `main`** costs one block per moved land and one rerun per race (`target_moved`); with one slot and rounds
  running, a land may wait for a free slot (`no_free_slot`).
- **Foreground minutes**: a land with a validation block holds the person's shell; Ctrl-C is safe (section 3).
- **Agent cost of a conflict or `branch_moved`**: the abandon route re-runs the plan and implement agents.
- **Task code edits the shared Git config before a land's push** (section 15): `pushurl`/`pushInsteadOf` refused,
  `insteadOf` and `core.sshCommand` accepted under D10.
- **A rewound origin `main`** within seconds of the push (section 7): the push puts O's commits back; accepted.
- **Local `main` stale after a land** until the person pulls: new task branches are cut from the local `main` (.15
  section 17), so tasks admitted before the pull start behind and their lands validate on a moved `main`.
- **Branch protection** on a real forge (GitHub requiring PRs or signed commits) makes every land `remote_rejected`; PR
  mode stays held.
- **A pushable candidate blocks the abandon** until the person lands or withdraws it: one more command.
- **Schema discard** at v13: finish or abandon attempts first (the existing runbook).
- **A shelf dependency** (L0) on `merge-tree --write-tree` (Git 2.38 or later; this machine has 2.54).

## 23. Not verified

- That `commit-tree` through the `hardened` view takes the person's identity from their configuration as expected.
- `bd close` with `if_assignee` against a claim whose lease lapsed during a long block (the keep-alive renews it; a lapse
  between commands is pinned by a tracker-double test and the smoke). **Answered by the M3 smoke (2026-11-12, bd 1.3.1):**
  once rounds stopped, `bd show` of a task at `Next: land` read `Lease: expires expired (heartbeat ... ago)`, and every
  land's `bd close` fenced on `if_assignee taskloop` still succeeded (six tasks): the fence is the assignee, not the
  lease ([m3-smoke-findings.md](m3-smoke-findings.md) finding 5). A later bd that expires the assignee with the lease
  would turn this into `refused claim_lost` with its close by hand.
- `git remote get-url --push` on every remote form (SSH aliases, `file://`): L0's contract suite covers the forms it
  tests; the smoke covers a local bare remote only.
- Line estimates, from the counts at 08784fe34.

Verified for this revision: `stream_proc` 0.6.0 stops a command's tree on any unwinding of its supervision
(`runner._supervise`, `except BaseException: stop_tree(...)`); `bd` 1.3.1's `close` of a closed bead (section 8);
git-porcelain 0.15.0's `fetch` raising `GitUnavailable` on failure and taking its own `timeout`; `Repo.tree` of
`<X>^{tree}` giving the tree id on the real repository (`rev-parse <rev>^{commit}`, then `^{tree}`) but `None` on the
fake (which resolves only commit names and stored tree ids).

## 24. Review repairs (2026-11-11)

An independent review of 365743d89 found sixteen points; all are taken, none refuted (the code confirmed each one that
names code).

| # | Finding | Repair |
|---|---|---|
| 1 (high) | An abandon could reopen a task whose S is already on origin: `LANDING` saw only delivered or slot-holding candidates | `LANDING` also covers a pushable candidate; a `superseded` state (`moved`, `withdrawn`, `gone`, `abandoned`); `--withdraw`; `abandon_released` and the abandon release return `abandoned`/`landed`/`landing`/`changed`; `record_delivery` fenced against an abandoned checks attempt and tested (sections 7, 11, 13) |
| 2 (high) | Delivered-versus-moved needed a fetch, and sections 7 and 12 disagreed | One delivery rule (section 7): R = S delivered, R = O push, else the bounded fetch (`timeout=PUSH_TIMEOUT`, `GitUnavailable`) and ancestry; an undelivered candidate whose O is gone and whose S is not contained is superseded and the same invocation makes N+1; `closed` with a pushable candidate reads origin first (section 4 step 8) |
| 3 | Delivery was recorded from fetch-side reads, which `publish` deliberately avoids | `push_url` refusal when the push URL differs from the fetch URL, checked before the reads and again before the push (L0 adds `remote_url(push=True)`); the recording rule written down (section 7). Removed 2026-11-12: `origin` is trusted as configured (section 29.3) |
| 4 | Import contracts: `land` would import `attempt_entry`, and `open_land` in `composition` would enter `check_entry`'s closure | `renewal` moves to `claim_lease`; `open_land` lives in `cli_composition`; `rounds-never-land` covers `composition`; the land modules join `cli-never-imports-the-attempt-entry`'s sources (section 3) |
| 5 | Ctrl-C does stop the check tree (`_supervise` stops it on `BaseException`) | Sections 3, 12, 21, 23 corrected; the smoke uses `kill -9` of the verified `tl` pid for `checks:running` |
| 6 | The land process was not registered, so a release could run under a live land | `entry_pid`/`entry_start`/`entry_boot` on the candidate, written under custody (`hold`); every stop proof uses `entry_stopped` with it; the `kill -9` with a surviving check row in section 12 |
| 7 | The `check_store.HELD` union would let checks-attempt updates match a candidate key | `RESULT_HELD` only for result and block writes; `refused`, `profiled`, `conclude` keep the checks-only fence (section 11) |
| 8 | CHECK NULL holes | `IS NOT NULL AND ... IN (...)` forms, `IS NULL OR` on every enumerated column; each CHECK tested with its NULL case |
| 9 | A slot still held after a land had no `Next` | `Next: release` whenever the latest candidate holds its slot; every rerun retries the release first, before closing or answering `already_landed` |
| 10 (low) | The push names no expected old tip | Decided: no lease (a force option); the fast-forward rule and the read right before; the rewind race accepted and stated (section 7) |
| 11 | `--no-change` should not depend on the branch | Allowed whenever S's tree equals O's, the branch check skipped, any concluded checks attempt (sections 4, 5, 11) |
| 12 | `Repo.tree_id` is not needed | Dropped from L0; the same-tree test compares tree listings, which works on the real and the fake (`<X>^{tree}` works on the real only: verified) |
| 13 | (covered by 2) | |
| 14 | `test_land.py` over 800 lines; the policy misses `CREATE UNIQUE INDEX` | Tests split (`test_land`, `test_land_resume`, `test_land_push`, `test_land_close`); L1 extends the policy's DDL pattern |
| 15 | Smoke step 3 compared `git status` | `HEAD`, `refs/heads/main` and the index file's digest |
| 16 | Wording | `remote_head` after an observed delivery contains S; `target_commit` renamed `origin_commit` (the glossary's "the target" is the checks admission's `main`); `push_barred` only catches accidents |

The review also asked how `bd` answers a close of a closed task: measured (section 8), idempotent.

## 25. As built: L1 (tl-8bh9.14.8.2)

Schema v13, `land_store.py`, the candidate fences, `check_store.RESULT_HELD`, the three-way `setup_store.HELD`, the
abandon fence `LANDING` with its words, and the policy entries; nothing of L0 or L2-L5 (no squash, `validate`, land
operation, push, close, CLI or status: nothing creates a candidate yet). Code lines by the policy counter: `land_store`
199 (new), `factory_schema` 207 (+51), `check_store` 290 (+18), `check_release` 142 (+13), `setup_store` 99 (+0);
`test_land_store` 337 (new), `test_check_store` 456 (+88), `test_setup_store` 136 (+22), `test_check_release` 209 (+15),
`test_policy` 185 (+9), `conftest` 174 (+10, the `landing` fixture), `doubles` 304 (+2).

- **DDL** exactly as section 11 (its inline SQL comments left out). `check_result.attempt_id` has no foreign key. v12
  and every other version are refused `schema` (`test_operations`' foreign list now holds 12 and 14). Column lists
  `LAND_ADMITTED` and `LAND_LOADED` in `factory_schema`.
- **`land_store`**: `LandAdmitted`, `LandRow` (joined: task, repository, tracker root, X as `checked`, the checks
  attempt's `checks_abandoned`; properties `holds_slot`, `pending`, `pushable`); module functions `insert(con, admitted)`,
  `record_release(con, key, (rev, validation), parked, now, abandoned) -> bool` and `of_checks_on`; `LandStore` with
  `latest`, `of_checks`, `hold`, `renew`, `profiled`, `conclude`, `supersede`, `record_delivery`, `record_close`; `HELD`.
- **`check_store`**: `RESULT_HELD` (the checks fence `UNION ALL` the candidate's, key bound twice) for `block`, `_new`
  and `_changed` only; `refused`, `profiled`, `conclude`, `register_entry` keep the checks-only fence.
  `record_release` and `abandon_released` return a `Recorded` word. `setup_store.HELD` is the agent fence `UNION ALL
  check_store.RESULT_HELD` (key three times).
- **`check_release`** maps `landed` and `landing` to `refused` with a one-sentence guide in the detail (`tl step land`,
  or `tl step land --withdraw`); `changed` stays `unavailable changed`.
- **Policy**: `WRITERS` gains `CREATE TABLE`/`CREATE INDEX land_candidate` (`factory_schema.py`) and `INSERT`/`UPDATE
  land_candidate` (`land_store.py`); `WRITE` also sees `CREATE [UNIQUE] INDEX [IF NOT EXISTS] <name> ON <table>` (kind
  `CREATE INDEX`, the table after `ON`), with a spelling test that checks the kind and table each match yields.

**Deviations (decided here, open to veto).**

1. The candidate fence's SQL lives in `factory_schema` (`CANDIDATE_RESERVED`, `CANDIDATE_HELD`) and `land_store.HELD`
   is that constant: `land_store` imports `check_store` (the required list and the stored-value readers), so
   `check_store.RESULT_HELD` cannot import `land_store` without a cycle. `factory_schema.LANDED` (a delivered candidate)
   sits beside `LANDING` so one fenced read gives the word.
2. `check_store`'s stored-value readers are public (`stored_required`, `stored_entry`, `stored_word`, `stored_real`,
   `stored_nullable_real`) and shared with `land_store`.
3. `check_store.record_release` returns `released` for a settled release (the section names only the abandon's words);
   the abandon's `landed`/`landing` comes from the fenced read inside the release transaction, before the write.
4. `land_store.insert` refusal words: `not_checked` (the checks attempt not the latest, unreleased, abandoned, or not
   `passed` without `no_change`), `not_done` (a later attempt of the task, or the claim not `kept`), `landing` (a
   delivered candidate, the latest holding its slot or pushable, or `number` not the latest plus one).
5. `record_delivery` and `record_close` off their fence raise `StoreRefused("land_changed")` (also a second delivered
   candidate, from the `land_delivered` index); a delivery for an abandoned checks attempt `StoreRefused("abandoned")`.
6. The candidate `HELD` also requires `superseded IS NULL`. `hold` bumps `rev` (as an entry registration does); `renew`
   refuses a non-finite deadline (`ValueError`) and leaves `rev`. `supersede` takes `moved`, `withdrawn` or `gone`
   (`abandoned` is only the release's) and is fenced exactly as section 11 says: not delivered, not superseded.
7. `land_store.record_release` (consumed by L2's generalized release): settled only once validated; an abandon only
   for a pending or failed candidate (never pushable, delivered or superseded), marking it `superseded='abandoned'`.
8. The checks abandon's `LANDING` refusal is in the record, after the stop proof, reset and park of an unreleased
   checks attempt. It cannot arise there in practice (a candidate needs a released checks attempt); L2 may read it
   before the slot work if the release is generalized anyway.

**Tests**: every `land_candidate` CHECK rejecting its bad row matched by the exact failing expression SQLite reports
(each nullable operand's NULL case: a slot-less unvalidated row, a NULL validation with a no-change delivery, with a
reason, with a pushed delivery), the valid rows, `UNIQUE(checks_attempt_id, number)`, the token, the foreign key and
`land_delivered` (a second `pushed` or `no_change` delivery refused, undelivered rows beside it accepted); v13 current,
v12 unavailable; the insert's fences one by one with nothing written; every validation write off `HELD` (another key,
the checks key, no reservation, another slot, concluded, superseded); `hold` replaced only naming the stored identity;
renew, profile once, conclude; the release record both modes; supersede, delivery and close fences; malformed stored
rows unavailable. In `test_check_store`: a pending candidate's block and results under its own key; `refused`,
`profiled`, `conclude` and the entry registration never matching it; its result writes stale once released, concluded or
superseded; the abandon of a released checks attempt for nine candidate states (`landing`, `landed` or `abandoned`), the
abandon release of an unreleased one refused by a candidate put past the fences, and the other race order (abandon first:
insert `not_checked`, delivery `abandoned`). `test_setup_store`: a candidate's setup runs through the third part of
`HELD`. `test_check_release`: the abandon refused `landing` and `landed` with its guide, nothing recorded. Fourteen
hand mutations (the NULL-safe CHECK forms, each `LANDING` disjunct, `HELD`'s superseded clause, `RESULT_HELD` on
`conclude`, the two-way setup fence, the insert's slot and conclusion fences, the abandon release's pushable fence, the
delivery's abandoned and delivered fences) each fail a test.

**Not verified**: nothing creates, validates or delivers a candidate yet (L3); `land_store.record_release` has no
caller until L2.

### 25.1 Review repairs to L1 (2026-11-11)

An independent review of 9d70fc375 found the DDL identical to section 11 and NULL-safe, and two defects; both repaired,
each with tests that fail without it (seven hand mutations, each failing a test):

1. **(medium) A delivered land stopped blocking the abandon after a checks re-run.** `LANDING` and `LANDED` were scoped
   to one checks attempt, `insert` accepts `no_change` on a failed checks attempt (kept: sections 5 and 24), and
   `check_admit` re-ran a failed checks attempt without looking at candidates. Now `factory_schema.OF_TASK` scopes
   `LANDED` and `LANDING` to every checks attempt of the implement attempt; `land_store.insert` refuses `landing` by
   that `LANDING`; `record_delivery` refuses `land_changed` while any candidate of the implement attempt is delivered
   (the partial unique index covers only one checks attempt); `check_admit.next_number` refuses the re-run `landed` or
   `landing` with a guide (`admit.Refusal` gains both words; `step_guide` entries stay L5). Tests: the re-run's abandon
   (both release paths) refuses `landed`; the re-run is refused for a delivered no-change and a pushable candidate and
   admitted after a withdrawal; a candidate of the re-run is neither inserted nor delivered.
2. **(medium-low) A pending candidate could be superseded and then never released.** `supersede` is fenced on
   `validation IS NOT NULL`; `land_store.record_release`'s abandon mode now releases any candidate that is neither
   pushable nor delivered, keeping an existing superseded reason (`coalesce`), so a superseded validated candidate that
   still holds its slot is released by both modes. Tests: no `moved`/`withdrawn`/`gone` for a pending candidate, its
   abandon release; a superseded `passed` or `failed` candidate released settled and abandoned with its reason kept; a
   pending one superseded past the fences still released by the abandon.

Code lines after the repairs: `land_store` 200, `factory_schema` 208, `check_admit` 209 (+8), `admit` 283 (+1);
`test_land_store` 373, `test_check_store` 470, `test_check_admit` 159 (+21).

## 26. As built: L2 (tl-8bh9.14.8.3)

The shared validation, the renewal move and the generalized release; nothing of L3-L5 (no land operation, CLI, push,
close or status: nothing creates or validates a candidate outside tests). A refactor for checks and agent attempts:
every existing test passes unchanged, `test_check_entry` included (not one line of it changed). Code lines by the policy
counter: `validate` 104 (new), `check_entry` 131 (-83), `check_release` 203 (+61), `claim_lease` 69 (+7),
`attempt_entry` 224 (-6), `land_store` 208 (+8); `test_validate` 105 (new), `test_check_release` 291 (+82),
`test_claim_lease` 97 (+5), `conftest` 190 (+16, the `candidate_on_slot` fixture). Largest function: `enter` (29).

- **`claim_lease.renewal`**: moved verbatim from `attempt_entry`; both entries import it from `claim_lease`, and so will
  `land`. The `Renewal`/`Renew` types stay in `environment` (their owner; `claim_lease` imports them), so no import of
  them moves.
- **`validate.py`**: `check_entry`'s steps 4-12 moved verbatim, each function taking `(work: Checking, target: Target)`
  where it took the registered entry: `validate` (the old `_checked`, with its exception mapping), `reconcile` (public:
  the claim-lost path calls it alone), `_expired`, `_profiled`, `_at`, `_environment`, `_block`; `Verdict`, `Ended`,
  `RELAUNCHED` and `concluded` moved with them. `Target(key, repo_id, slot_path, commit, required, deadline, main,
  profiled)`: the plan's `moved` parameter is `main: str | None` (the commit `main` was at when the names were read;
  None watches nothing) and `profiled` writes the digest to the owner's row. `check_entry` builds the checks target
  (`_target`: X, `row.target` as `main`, `CheckStore.profiled`) and keeps the registration, lock, keep-alive, counting,
  conclusion and release. A candidate's target is S, `main` None, `LandStore.profiled`; `CheckSink` and the setup runs
  take its key unchanged (`RESULT_HELD`, the three-way `setup_store.HELD`).
- **Old and new flows compared step by step** (checks): the reconcile, deadline, profile read, `main` read (the view is
  built only when `main` is set; for a checks target always, as before), completed-block conclusion, detach, setup,
  block number, digest write, block, `main` reread and conclusion run in the same order with the same arguments
  (`row.key`, `found.slot_path`, `row.repo_id`, `row.commit`, `row.required`, `row.deadline`, `row.target`), and the same
  three exception types map to the same words. The release: the same reads (`CheckStore.row`, then `held_slot`,
  `running`, `unsettled` on one connection), the same order of answers (`absent`; an earlier release and the
  abandon's flip; `changed` without the reservation; `not_terminal`; entry, setup, checks stop proof; lock; reset; park;
  the fenced record and `free` in one transaction; scratch) and the same detail texts.
- **`check_release`**: `ReleaseTarget[R]` (a protocol: `store`, `read` to a `Holding[R]` or `refused absent`,
  `released` for an earlier release, `refusal` before the stop proof, `record_release` in the transaction) with
  `ChecksTarget` (the old checks behavior) and `CandidateTarget` (over `LandStore`). `ChecksRelease.release(key,
  abandon, me)` keeps its signature (the checks target); `ChecksRelease.release_of(target, key, abandon, me)` serves
  either. The candidate's stop proof is `entry_stopped` with the land process stored on the candidate (`me` passing:
  the land releasing its own slot), its setup run and its block's unsettled results, boot-aware; its reset is to S, its
  park at D; its record is `land_store.record_release` (`True` read as `released`/`abandoned`, `False` as `changed`).
  `land_store` gains reads only: `LandStore.row(key)` and `held_slot(con, key)`.
- **Contracts**: `validate` joins the sources of `cli-never-imports-the-attempt-entry` and of
  `entry-never-imports-the-command-surface`. `rounds-never-land` and the land modules as sources wait for L3, which
  creates the modules.

**Deviations (decided here, open to veto).**

1. The candidate target lives in `check_release`, not `land_store` (the plan's "`land_store`'s" target): its refusals
   and words are the release's; `land_store` stays the writer and reader of its table.
2. A candidate's abandon is refused before anything changes: delivered `refused landed`, pushable `refused landing`
   (with the L1 guides), read from the row before the stop proof, not only by the record's fence (section 25 deviation
   8 for candidates). A checks attempt's abandon keeps its `LANDING` refusal in the record (unchanged behavior).
3. A settled release of a candidate needs a validation (`refused not_terminal` while pending); a pushable or delivered
   candidate still holding its slot is released settled (the land's own release after a pass).
4. A candidate validated with no slot (`same_tree`, `no_change`) reads as `refused absent` ("No such land candidate
   holding a slot"). A released candidate answers `AlreadyReleased` to a settled release (`abandoned` when superseded
   `abandoned`); its abandon refuses `landed` when delivered and `landing` when pushable (section 26.1, repair 4), else
   `AlreadyReleased`.
5. The protocol's record method is `record_release`: the policy's Git-write matcher counts any `.record` attribute as a
   Git write (`record` is `Worktree.record`).

**Tests**: `test_validate.py` (a candidate's target over `candidate_on_slot`: a passing block at S with results and
setup runs under the candidate key, the digest on the candidate, the checks attempt untouched, `main` moved during the
block not watched; a failed required check; a surviving check of a killed land process `checks:running`/`checks:unknown`
before any read; an interrupted block repeated whole; a completed block concluded as it stands, then `expired`; the
reconcile alone). `test_check_release` (five new test functions): a candidate refused `not_terminal` while pending, then reset to S, parked
at D, recorded once, the checks attempt untouched; the abandon of a pending or failed candidate superseded `abandoned`;
the stop proof in both modes (the stored land process running or unknown, its check, its setup) and the land's own
identity passing; the abandon of a pushable or delivered candidate refused with nothing changed and its settled release
allowed; absent and store unavailable. `test_claim_lease` (+1): `renewal` from its new owner, a faulted beat
`unrenewed`. Ten hand mutations each fail a test: in `validate` drop the reconcile, the completed-block reading, the
deadline, the digest write (`test_check_entry`), and watch `main` when None (`test_validate`); in `check_release` drop the
entry stop proof, the candidate's `landing` and `landed` refusals, its `not_terminal`, and the reset to S.

**Not verified**: no real-Git or real-process run of a candidate's validation or release (`test_check_release_real`
covers the checks target only); `validate` and `CandidateTarget` have no production caller until L3; whether
import-linter accepts a forbidden contract naming modules that do not exist yet (not tried: L3 adds them with the
modules).

### 26.1 Review repairs to L2 (2026-11-11)

An independent review of d7e972a6a and 205347ba1 found the checks path equivalent and four low defects; all repaired,
each with a test that fails without it (five hand mutations, each failing a test):

1. **The stop proof was not re-read under the custody lock** (as in the checks release before L2, now also for
   candidates): a land process (or entry) could take the custody, start a check and die between the proof and the lock,
   and the release would reset the slot under the live check. Now, under the lock and before any Git write, the release
   reads its target again and runs the target's refusals and the stop proof again (`ChecksRelease._again`), for both
   targets; any other change since the first read is `unavailable changed` before the reset (the checks test whose rev
   moves after the proof now answers `changed` before any Git write instead of after the park: same word, nothing
   recorded). This is the one behavior change for checks attempts in L2, asked for by the review. Test: a check started
   and alive between the proof and the lock holds the slot (`held:check_running`) with nothing reset, for each target; a
   rev change there is `changed` with nothing reset.
2. **`land_store.record_release` answered a bool**: a delivery between the refusal and the record would read
   `unavailable changed` after the park. It now returns the checks record's words: `released`, `abandoned`, `landed`
   (delivered), `landing` (pushable), `changed`; the release maps `landed` and `landing` to their refusals. Tests:
   `test_land_store`'s abandon of a pushable, delivered or unreserved candidate records `landing`, `landed`,
   `changed` (its helper `released` keeps the bool for the other tests).
3. **The stop proof worded a land refusal as an attempt's entry**: `slot_release.entry_stopped` takes `process` (None:
   the old texts), `Holding.process` is `land process` for a candidate. Test: the running and unknown details name the
   land process for a candidate and the entry for a checks attempt.
4. **The abandon of a released pushable or delivered candidate looked like success** (`AlreadyReleased`): it now refuses
   `landing` or `landed` with the guide; settled still answers `already_released`. Test: a released `passed`
   candidate's abandon is `landing`, after its delivery `landed`, its settled release `AlreadyReleased`.

Code lines after the repairs: `check_release` 217, `land_store` 211, `slot_release` 269 (+4); `test_check_release` 336,
`test_land_store` 377.

## 27. As built: L3 (tl-8bh9.14.8.4)

The land operation up to and including the delivery: section 4's reads, section 5's candidate, section 6's validation,
section 7's delivery rule and push, `--withdraw`, the resume rows of section 12 but the close, `open_land`, the policy
tables and the contracts. Nothing of L4 (tracker close and its record, the commit message, the summary) or L5 (the `tl
step land` subcommand, status lines, `Next` words, guide, runbook): no command calls the operation yet. Code lines by the
policy counter: `land` 222 (new), `land_check` 138 (new), `land_push` 138 (new), `cli_composition` 229 (+15),
`land_store` 214 (+3), `slot_lock` 48 (+2), `owned_processes` 25 (+4), `check_admit` 209 (+0); `land_bench` 176 (new),
`test_land` 131, `test_land_resume` 100, `test_land_push` 132, `real/test_land_real` 137 (all new), `test_policy` 186
(+1), `test_operations` 601 (+2). Largest function: `land._made` (23).

- **`land.land(ports, request) -> Landed | Withdrawn | Failed`** (`LandRequest(backlog, task_id, checkout, minutes,
  mode, no_change)`): section 4's reads in order (`choices`, `push_barred`, then `not_done`, `not_checked` on factory.db
  read through `admit.open_store`: another schema version is `unavailable store`; the latest candidate; the checkout,
  `no_remote`, `push_url` (removed, section 29.3), one `ls_remote` of `main` and `task/<id>` (`target`, `branch_moved`, `commit_missing`); one
  tracker read, `claim_lost`, `closed`), then section 5 (`fetched`; `named` at O: `target_profile`, `target`,
  `no_required`; `Repo.squash`: `conflict` with the first 20 paths and the count; tree listings: `no_change`, `changes`;
  the required names against the checks attempt's) and the resume: a pending candidate renews its deadline and validates,
  a pushable one is delivered, anything else (none, superseded, failed) makes candidate latest + 1. Any factory.db fault
  is `unavailable store`.
- **`land_check`**: `LandPorts` (the validation's `Checking`, `LandStore`, the `remotes` view and its profile port, the
  tracker read and heartbeat, a stop event per keep-alive, this process's identity, the slot lock's probe and custody,
  this process's environment); `inserted` (a same-tree or no-change candidate with no slot and generation 0, or the
  lowest observed-free slot's reservation and the pending candidate in one transaction: `admit.free_slots`,
  `check_admit.heads`, `admit.issued`/`unheld`/`reserve`, `land_store.insert`); `validated` (the custody
  `slot_lock.landing`, the identity `LandStore.hold`, one renewal, the keep-alive around `validate.validate`,
  `validate.concluded`, `LandStore.conclude`, the settled release through `check_release.CandidateTarget` with `me`);
  `released` (section 4 step 5: a non-pending candidate still holding its slot released first under the custody).
- **`land_push`**: `same_url` (removed, section 29.3), `remote_tips` (the one `ls_remote`), `fetched` (`+refs/heads/main:refs/remotes/origin/main`,
  `timeout=PUSH_TIMEOUT`), `deliver` (the rule; `Again` makes N+1 at most once per invocation), `observed` (the rule
  without a push: the closed-task read), `withdraw`. `Delivered(row, remote_head, how)`, `Withdrawn(row)`. A delivery
  record refused because a concurrent land recorded it first answers that delivery (`already_pushed`).
- **Wiring**: `cli_composition.open_land(database, artifacts)` (the database guard, then `composition.open_checking`'s
  ports, `remotes`, `GitProfileFiles` on `remotes`, `inspect_tracker_task`, `tracker_claims().heartbeat_for`,
  `threading.Event`, `owned_processes.this_process`, `slot_lock.probe`, `slot_lock.landing`, `os.environ`).
- **Contracts and policy**: `rounds-never-land` (sources `round`, `rounds`, `operations`, `attempt_entry`, `check_entry`,
  `composition`, `validate`, `check_release`, `land_store`, indirect imports included; forbidden `land`, `land_check`,
  `land_push`); the three land modules join `cli-never-imports-the-attempt-entry`'s sources. `GIT_WRITES` gains
  `squash` (owner `land.py`); `fetch` and `push` gain the owner `land_push.py`.

**Deviations (decided here, open to veto).**

1. Three modules, not two: `land_check` holds the ports, the insert and the validation driver so each file stays small;
   it is a land module in both contracts.
2. `LandRequest.mode` is `land` or `withdraw`: `--summary` is L4's and is not stubbed. `--no-change` is built here (the
   candidate is inserted `no_change`, delivered at insert, the branch rule skipped, any concluded checks attempt; `changes`
   when S's tree is not O's); its close with "Already on main at O" is L4's. `--withdraw --no-change` is `refused
   choices`.
3. Results: `Landed(row, how, release)` with `how` `pushed`, `already_pushed`, `no_change`, or `delivered` (a delivery
   recorded before this call: only L4's close remains; L3 never answers `already_landed`); `Withdrawn(row)`; `Failed` is
   `operations.Failed`. `release` is the word of section 4 step 5's release when one ran; the land's own release after a
   validation is not carried (a held one stays on the row and the next rerun retries it first).
4. S's message is a placeholder (`land.message`: `Land <task-id>`, the branch and X) until L4's `land_summary.message`.
5. `not_done` points to `tl step show` instead of naming the attempt's `Next` (the operation reads no status view).
6. New words: `land_running` (the land process stored on a pending candidate still runs: never replaced; unknown is
   `observe`), `not_landing` (`--withdraw` with no pushable candidate). A third rejected push in one invocation is
   `target_moved` (at most three delivery passes).
7. `--withdraw` runs section 4 steps 1-6 only (no branch rule, no tracker read): it changes nothing on origin.
8. A closed task whose pushable candidate is found on origin answers `Landed` (`already_pushed`); L4 records
   `already_closed`. Not found: `refused closed`, the candidate left pushable (not superseded).
9. A concurrent land that wins while this one validates takes the slot's next generation first: the loser answers
   `unavailable no_free_slot` (the counter), not `landing`; with no slot (same tree) the insert's fence answers `landing`.
10. Section 4 step 5's release of a candidate that is neither pushable nor delivered stops the land with the release's
    word (`held:...` as `unsettled`); a pushable or delivered one goes on.
11. `check_admit._named` and `_heads` became public (`named`, `heads`), shared with the land; `owned_processes.this_process`,
    `slot_lock.landing` (role `land`) and `LandStore.slot_path` were added.

**Tests**: `test_land` (same tree: S's one parent O, X's tree, no slot, no check, the person's `main` and branch
untouched; a moved `main` validated in s1, released and parked at D, pushed; changed required names validated with the
same tree; a failed validation; a conflict; `no_change` then `--no-change` on a moved branch; `changes`; seventeen
refusals each with nothing written, no push and no check; `push_url` before any remote read, and set by a check during
the validation refused right before the push (both removed, section 29.3); another repository; failed checks refused before any remote read).
`test_land_resume` (a crash after the validation pushes on the rerun without checking again; Ctrl-C during the block
repeated whole with a renewed deadline; a killed land's check still running holds the rerun, then a new land process
replaces the identity; a live stored land process is never replaced; `slot_busy` under another custody; a concurrent
land winning first, same tree `landing` and validated `no_free_slot`; a held release retried first while the land still
pushed; an abandoned checks attempt; a claim lost at the first renewal; no free slot). `test_land_push` (origin at S after
a lost answer: delivered, no second push; built on S: delivered with the later tip; a pushable candidate onto a moved
`main` superseded and candidate 2 landed; `main` moving after the insert: `target_moved`, then the rerun; a push rejected
after the read: `target_moved`, then the rerun; `Transient`, `RemoteRejected`, `HookRejected` each leave it pushable;
the failed fetch; a delivery recorded by a concurrent land; `--withdraw` superseding then the abandon proceeding,
`--withdraw` finding S on origin, nothing to withdraw; a closed task with S on origin and without; at most one new
candidate per invocation; a pruned S superseded `gone`). `real/test_land_real` (a bare origin: a moved `main` validated
with an `sh -c` check through the real setup, block, slot lock and release, origin's `main` the S commit whose only parent
is O and whose tree holds both changes, the slot parked at D, the person's HEAD, `refs/heads/main` and index digest
unchanged; the same tree with X's tree and the person's identity; a `pushurl` elsewhere refused with nothing pushed to
either repository; no origin). `test_operations`: `open_land` refuses a missing factory.db and creates none. Thirty-two
hand mutations (each reinstalled and run against the four land test files) each fail a test (three survived the first
run: the once-per-invocation rule, the not-checked read order and `gone`; a test was added for each): the push-bar read, both
push URL checks, the same-tree and required-names rules, the ancestry read, the once-per-invocation rule, the deadline
renewal, the live-identity guard, its own-identity skip, the release first and its continue rule, the local and the
origin branch rules, the no-change rule, the closed read, the concurrent-delivery answer, the fetch refspec, the lost
claim, the claim assignee, the not-checked read order, the rejected-push loop, the withdraw supersede, the validation's
release, the checkout's repository, the relaunchable words, the delivered and no-change answers, `gone`, and R is S.

**Not verified**: no command calls the operation (L5); the close (L4); a real `RefRejected` race and a real
`RemoteRejected` (the fake and a scripted answer only); a real Ctrl-C through `stream_proc`'s supervision (the fake
raises `KeyboardInterrupt` from a check); a pruned S on real Git; the land on a remote other than `file://`.

### 27.1 Review repairs to L3 (2026-11-11)

An independent review of 990266c12 reproduced three defects and found four more; six are repaired here, each with a
test that fails without it (nine hand mutations, each failing a test). One is open.

1. **(high) `--no-change` after an earlier pushable candidate pushed an empty commit.** `deliver` superseded S `moved`,
   its `again` inserted the no-change candidate (delivered at insert) and the loop then pushed it. Now `deliver` returns
   at once when its new candidate is the no-change one (`Delivered(..., "no_change")`), and (2) keeps `--no-change` out
   of `deliver` entirely. Tests: the review's repro; `deliver` with an `again` that makes the no-change candidate.
2. **(medium) `--no-change` still validated or pushed an existing candidate.** `land._no_change`: never `validate` or
   `deliver`; pending refuses `landing`; pushable is read by the rule without a push (`land_push.observed` now answers
   `at_origin` or `moved` when not delivered): delivered is recorded, `at_origin` is `changes` (the candidate stays
   pushable), `moved` supersedes it and makes the no-change candidate (section 13). Tests: each case.
3. **(medium) `--withdraw` ran the branch rule**, so a moved task branch left no way out (the abandon refuses
   `landing`). `--withdraw` skips it (section 13). Test: the review's repro (origin's `task/<id>` moved).
4. **(medium, security, closed 2026-11-12; superseded the same day by section 29.3: the URL comparison is removed)
   only the first URL was compared.** git-porcelain 0.17.0 adds `Repo.remote_urls(remote, *,
   push=False)` (`remote get-url --all [--push]`; `FakeRepo.add_config` for a second value), committed locally in a
   new shelf worktree (`/home/iorlas/Workspaces/shelf-wt-l3`, branch `git-porcelain-remote-urls`, f6f7901; shelf
   `just check` and `check-all` green). Pushing the branch and opening the PR were refused by this session's
   permission system, so it is not merged, tagged or pinned; `same_url` still reads `remote_url` (now catching
   `GitUnavailable`, see 6). The land's side is written and waits for the pin: `fetch, push =
   repo.remote_urls(REMOTE), repo.remote_urls(REMOTE, push=True)`, passing only when `len(fetch) == 1 and fetch ==
   push`, with a real-Git test of two `pushurl` and of two `url` refused with nothing pushed.
   **Closed:** git-porcelain 0.17.0 was released (`git-porcelain-v0.17.0`, shelf 0d1ad4f) and is pinned; `same_url`
   reads `remote_urls` as written above. Tests: real Git, a second `pushurl` after one naming origin and a second `url`
   each refuse `push_url` with nothing pushed to either repository, and one `pushurl` equal to the fetch URL still
   delivers; the fake land table, a second `url` (`FakeRepo.add_config`).
5. **(low) A pruned S was superseded `gone` before origin was read.** `_step` reads origin first (R is S: delivered
   although S is gone here); `_seen` treats a missing S as not contained (`MissingRevision`), so `--withdraw` of a
   pruned S supersedes it. Tests: a pruned S already on origin is delivered; `--withdraw` of a pruned S onto a moved main.
6. **(low) `same_url` let `GitReadFailure` escape** at the push's recheck (outside the reads' handler). It answers
   `unavailable git`. Tests: at the reads, and set by a check before the recheck. (Removed with `same_url`, section
   29.3: an unreadable `origin` at step 6 is `unavailable git` from the presence check.)
7. **(low, wording)** A concurrent land that took the one free slot first now reads as `landing` (`land_check._raced`:
   a candidate numbered this one or later, or `LANDING`), not `no_free_slot`. A pushable candidate whose release was
   held, met by a moved `main`, refuses the new candidate `landing` saying the old one still holds its slot (rerun, which
   retries the release first, or `tl step release`), both at the insert's fence and when no slot is free.

Code lines after the repairs: `land` 238, `land_check` 155, `land_push` 144; `land_bench` 182, `test_land_push` 178,
`test_land_resume` 112.

## 28. As built: L4 (tl-8bh9.14.8.5)

The tracker close and its record, S's commit message, and the land summary with `--summary`; nothing of L5 (no `tl step
land` subcommand, status lines, `Next` words, guide, glossary beyond the L4 words, runbook). Code lines by the policy
counter: `land` 280 (+42), `land_close` 44 (new), `land_summary` 158 (new), `land_check` 157 (+2), `tracker_client` 78
(+21), `cli_composition` 230 (+1); `test_land_close` 148, `test_land_summary` 156 (both new), `land_bench` 199 (+17),
`real/test_land_real` 158 (+21), `test_land_resume` 111. Largest new function: `land_summary.lines` (21).

- **The tracker port** (`tracker_client`): `TrackerClaims.close(tracker_root, task_id, reason) -> Closed`, a word:
  `closed`, `already_closed`, `claim_lost`, `missing`, `unavailable`. One `Bd.show` as `taskloop`: none is `missing`,
  `closed` is `already_closed`, another assignee `claim_lost`; else `Bd.close(task, reason, if_assignee="taskloop")` (its
  same-value assignee update is the fence). A `BdError` of kind `precondition`/`not_claimable` is `claim_lost`, bd's
  deleted-bead text `missing`, anything else `unavailable`. Nothing unclaims. `LandPorts.close` carries it; `open_land`
  wires `tracker_claims().close`.
- **The close step** (`land_close.closed`, called by `land._closing` on every `Landed` but `--withdraw`'s): after the
  push (or the no-change disposition), the port with the reason `Landed <S> on main (task/<id> at <X>)` or `Already on
  main at <O>`; `closed`/`already_closed` recorded by `LandStore.record_close` (a record refused because a concurrent land
  recorded it first answers that row; a store fault is `unavailable store`, "the task is closed; rerun to record it").
  Refused: `claim_lost` is `refused claim_lost` ("close it by hand with `bd close <id>`; a rerun records it
  `already_closed`"), `missing` is `refused task`, `unavailable` is `unavailable tracker`; the task stays open and
  claimed. `land_close.NOT_SYNCED` is the line every land answer ends with (L5 prints it); nothing runs `bd dolt push`.
- **Resume** (section 12's close rows): a delivered candidate goes straight to the close (no fetch, squash, check, push or
  step 8 read): `Landed.how` `delivered`; delivered and closed answers `already_landed` with no Git or tracker call (after
  a held release is retried). A closed task whose pushable candidate is on origin records the delivery, then
  `already_closed` (`Landed.how` `already_pushed`); without it, `refused closed` as in L3.
- **The message** (`land_summary.message`, `message_at`), section 9's shape: `<title> (<task-id>)`; `Squashed from
  task/<id> at <X>:` and one `- <subject> (<12-char sha>)` per commit of X not on O (`Repo.history([X], not_on=[O])`, the
  same set as merge-base(O, X)..X), oldest first, at most 50 then `- ... and <n> more` (a bare `Squashed from ... .` when
  none); then the trailers `Task:`, `Plan:` (when `docs/design/<id>/plan.md` is in X's tree) and `Checked: <checks
  attempt id> <its conclusion> at <X>`. `one_line` turns every Unicode control, format, surrogate, private-use or
  unassigned character into a space and collapses whitespace (line and paragraph separators, NEL included), then cuts to
  72: a title or subject can add no line, paragraph or trailer (the trailers are always the last paragraph). Author and
  committer are the person (real Git: verified by `%an`/`%cn` and Git's own trailer parser in `test_land_real`).
- **The summary** (`land.land` with `mode="summary"`): section 4 steps 1-4 (any concluded checks attempt: the summary
  reports the conclusion), step 6-7 (the checkout, `no_remote`, `ls_remote`, the branch rule), one tracker read for the
  title (no status refusal), the fetch, the profile at O (`target_profile`, `target`, `no_required` as the land), S in
  Git objects; no step 5 release, no candidate, reservation, push or close. `LandSummary` (typed facts, section 10's
  seven items: `results`, `added`/`removed`, `argv`, `checks`, `setup`, `files`, `state` `same_tree`/`moved`/`conflict`/
  `no_change`, `again`, `conflicts`, `message`, `base`) and `land_summary.lines` (one printable line per fact).
  Configuration files are found by comparing the tree listings of merge-base(O, X) and X (no diff API); an argv element
  names a tracked file exactly or a folder by prefix.

**Deviations (decided here, open to veto).**

1. The close is its own module `land_close` (the plan put it in `land.py`, +45): `land.py` keeps only `_closing`. Both
   join the `rounds-never-land` forbidden list and the `cli-never-imports-the-attempt-entry` sources with `land_summary`.
2. The port answers a word, not four result classes (`Closed | ClosedBefore | CloseLost | CloseUnavailable`), and adds
   `missing` (no such task: `refused task`, the admission's word for it); since 28.1 a `CloseAnswer` (the word, the
   assignee read, bd's words) and `blocked`.
3. `--withdraw` never closes: finding S on origin it records the delivery and answers `Landed` with `close` None (it
   reads no tracker, L3 deviation 7); the next `tl step land` closes.
4. `Checked:` names the checks attempt's own conclusion (a no-change S on a failed checks attempt is never pushed, but
   its message states no false pass); an empty title is `Untitled task`; listed subjects are cut to 72 like the title.
5. `--summary` is a mode of `LandRequest` (`land`, `summary`, `withdraw`); with `--no-change` it is `refused choices`.
   The summary is not computed inside a land: "printed before every land" is L5's (it may run the summary mode first;
   that costs a second fetch).
6. The summary runs the branch rule (a moved branch is refused as the land would) and reads the profile at O twice
   (once through `_required`, once with X's).

**Tests**: `test_land_close` (the push, then one close as `taskloop` with origin already at S, the reason; a crash
(`BaseException`) before the close, the rerun closing with origin offline; a lost close record, the rerun recording
`already_closed` with the first reason kept; a concurrent close record; a claim taken during the push, `claim_lost`, the
rerun refused again, then closed by hand and recorded; `unavailable`, `claim_lost`, `missing` each leaving the task open
and claimed, the rerun closing; `already_landed` with origin offline and the tracker never asked; the no-change reason; a
closed task whose candidate is on origin; `--withdraw` never closing; the real port's argv over beads_client's `Script`
and its seven bd answers, never `unclaim`). `test_land_summary` (the message exactly; nine hostile titles and subjects:
newlines, CRLF, ANSI, U+2028/2029, NEL, NUL/BEL/TAB, zero-width and bidi format, VT/FF; the 72 cut, `Untitled task`; 53
commits; the conclusion trailer; `message_at` oldest first and the plan; S's message from the tracker title; `--summary`
changing nothing; a moved main; a conflict and no change as facts; a target profile with added and removed required
names, changed argv, a removed and a changed check, a changed setup; changed required names on the same tree; failed
checks reported and `--no-change` refused; configuration files; results and printable conflict paths).
`real/test_land_real` (S's message, the person as author and committer, Git's trailers `Task` and `Checked` only, the
close; a hostile title adding no trailer Git reads). Forty-one hand mutations (each reinstalled and run against the six
land test files): thirty-nine failed a test at once; `again` on the same tree with changed names survived the first run
and a test was added for it (now failing); the title passed to the summary mode's squash is an equivalent mutation (the
summary recomputes the message; that S object is never shown or recorded).

**Not verified**: no command calls the operation (L5); `bd close` against a real tracker (the port's argv and answers are
pinned over `Script` with bd 1.3.1's measured texts); the close of a claim whose lease lapsed between commands (`claim_lost`
from bd's fence, by the double only); the summary on a real repository (fake Git only; the message on real Git is
covered).

### 28.1 Review repairs to L4 (2026-11-12)

An independent review of b999eb000 found the close ordering, the message's injection defences and `--summary` sound, and
five defects; all repaired, each with a test that fails without it (nine hand mutations, each failing a test).

1. **(medium) A second `--withdraw` closed the task**: `_resumed` sent a delivered, unclosed candidate to the close before
   it looked at the mode. `--withdraw` now answers `Landed` (`delivered`, `close` None) with no tracker call. Test: a close
   refused `unavailable`, then `--withdraw`: not closed, the tracker asked once.
2. **(low-medium) The `claim_lost` advice did not work**: bd 1.3.1 refuses `bd close` by an actor other than the assignee.
   Measured in a scratch tracker under `~/tl-smoke` (removed afterwards): `bd close` by another actor of a task assigned
   to `someone` fails ("cannot close ...: assignee is \"someone\", actor is \"person\"; reclaim or use --force to
   override"); with `--force` it closes; an unassigned task closes with plain `bd close`. The port now returns the
   assignee it read (`CloseAnswer.assignee`; None when bd's fence refused after the read), and the advice names the
   command that works: `bd close <id>` (unassigned), `bd close <id> --force` (another actor), or `bd show <id>` first
   (taken meanwhile). A task reverted to `open` but still assigned to `taskloop` (as `bd update --status open` leaves it;
   `bd reclaim` of a fresh lease reclaims nothing) is closed by the land: the fence is the assignee.
3. **(low) `_tracker` dropped the release word**: the closed task's delivery found on origin, and `--no-change`'s, now carry
   section 4 step 5's release word like every other `Landed`. Test: a held release (`held:slot_redirected`) with S on
   origin and its record lost, for a closed task and for `--no-change`.
4. **(low) The close had no time bound**: its `Bd` is built with `timeout=BD_TIMEOUT_S` (each of its three bd calls);
   a hung bd is `unavailable tracker`. Test: the construction through the `client` seam and a timed-out answer.
5. **(low, doc)** Section 4 step 5 said a delivered candidate goes to step 8 before the close; it goes straight to the
   close, whose own `bd show` is the read.

**Also measured** (the same scratch tracker): bd 1.3.1 refuses to close a task with an open child ("cannot close <id>: 1
open child issue(s); close children first or use --force to override") or an open blocker ("cannot close blocked issue:
<id> is blocked by [<id>] (use --force to override)"), exit 1 after the fence update passed. Such a close was
`unavailable tracker` (a rerun would never succeed). It is now the word `blocked` (`refused blocked`, bd's words shown
as one printable line, the advice: close or unblock what it names, or `bd close <id> --force`), classified by bd's
"cannot close" as `GONE` is (bd has no exit code for it). Tests: both measured texts through the port, the refusal's
words and printability, the rerun closing once unblocked.

Code lines after the repairs: `land` 283, `land_close` 56, `tracker_client` 90; `test_land_close` 207. **Not verified**:
the `bd close --force` advice is not run by the factory (by design); bd versions other than 1.3.1's refusal words.

## 29. As built: L5 (tl-8bh9.14.8.6)

The command surface, status and words of the land, and the M3 runbook; nothing of the land operation changed (no edit
to `land`, `land_check`, `land_push`, `land_close`, `land_summary`, `land_store`). M3 is not reached: the [M3 live
smoke](live-smoke.md) has not run. Code lines by the policy counter: `cli_step` 191 (+27), `operations` 366 (+20),
`attempt_status` 210 (+8), `show_render` 102 (+34), `step_render` 122 (+10), `result_data` 132 (+10), `step_guide` 190
(+6), `check_release` 219 (+2), `round` 256 (+0, one `case` widened), `land_status` 41, `land_guide` 80, `land_render`
47, `land_data` 45 (all new); `tests/cli/test_land_cli` 172 and `tests/steps/test_land_status` 192 (new),
`test_checks_round` 330 (+35), `test_check_operations` 234 (+3), `test_step_cli` 592 (+2), `test_cli` 58 (+1),
`test_check_status` 136 (+0). Largest new function: `show_render._candidate` (16).

- **`tl step land TASK --backlog --checkout --minutes [--summary | --withdraw] [--no-change] [--db] [--artifacts]
  [--json]`** (`cli_step._land`): the flags become one `LandRequest` (`--summary` and `--withdraw` mutually exclusive in
  the parser: usage, exit 2; `--no-change` with either is the operation's `refused choices`), `open_land`, then
  `land.land`; the CLI parses and renders only. A later dashboard calls the same `land.land` over its own ports. Exit
  codes are the step commands' (`exit_codes`, unchanged): 0 `Landed`/`Withdrawn`/`LandSummary`, 1 refused, 3
  unavailable or unsettled (a rerun is safe); a refusal or unknown goes to stderr. The help names the flags, "never
  forced", "rounds never land" and the exit codes. `STEP_ONLY` now says "`tl step land` lands, never a round".
- **Rendering** (`land_render`): `Landed` prints `<how>: <task> (backlog ...) on origin main; <what this call did>`
  (`pushed`, `already_pushed`, `no_change`, `delivered`, `already_landed`), the candidate (`Candidate N (<id>): S <S>
  onto origin main at <O>; same tree as X, no checks | no change, no checks | checks passed on S`), `Pushed:`, a
  `Release:` word when a held release was retried, then `Closed: <word>`, the `Tracker: closed locally, not synced (bd
  dolt push shares it)` line and `git pull --ff-only`, or (close still to come, `--withdraw` finding S on origin)
  `Closed: not yet: rerun ...`. `Withdrawn`: the superseded candidate and the way to the abandon. `LandSummary`:
  `land_summary.lines` and "Nothing was recorded, reserved, pushed or closed". A refusal: `tl step land: <kind>:<reason>`,
  the detail split on newlines only, each line one printable line (`one_line`), then each guide once for the reason, its
  first word (`checks:running` is `checks`) and the kind, from `land_guide.LAND_GUIDE` before `step_guide.GUIDE`.
- **JSON** (`land_data`, additive): `Landed` `{status: <how>, backlog, task, candidate, release, synced: false}`,
  `Withdrawn` `{status: "withdrawn", backlog, task, candidate}`, `LandSummary` `{status: "summary", ...section 10's
  facts, message}`; `candidate` is the row's stored facts (no dispatch token, URL or Git output). `tl step show` gains
  the key `land` (null without a candidate: the candidate, its land process as observed, its latest block's results with
  log paths); `tl step release` gains `land` (the candidate's release, nested) and `candidate` (this release is a
  candidate's). No existing key changed.
- **Status** (`land_status`, read by `attempt_status`; no land module imported): `land_view` reads the latest candidate
  of a released checks attempt (an abandoned one's too, as history), its latest block's results when it had a slot, and
  its stored land process (observed only while it holds its slot); `land_next` over the checks view's own word: only
  `done` goes on; no candidate is `land` after passed checks (`done` after failed ones); a validated or superseded
  candidate still holding its slot is `release`; delivered and closed is `landed`; anything else (pending, pushable,
  failed, superseded, delivered not closed) `land`. `Next` gains `land` and `landed`. `round._settle` returns at once on
  both; a land's `release` reaches the default `report release` move (the checks-release case needs an unreleased
  checks attempt), so a round never releases a land's slot.
- **`tl step show`** (`show_render.land_lines`), after the check step's lines: `Land: candidate N (<id>) onto origin
  main at <O>: <S>; <same tree as X, no checks | no change: ... | same tree as X, checks run again | merged onto a moved
  main, checks run again>`, `Land required: <names> (origin main at <O>; same as the checks | the checks required ...)`,
  `Land slot: <slot>, held | released <time>, parked at <D>`, `Land process: <observed> (pid ..., started ...)` while
  it holds its slot, one `Land check:` line per result (`check_line` with the prefix and the candidate's required names),
  `Land result: <validation> | failed <reason> | pending`, `Land superseded: <why>`, `Pushed: origin main at <remote
  head>, <time>` or `Delivered: no change, ...`, `Closed: <time> (<word>)` and the tracker line. Stored words (reason,
  slot, the process start) are one printable line each. `tl step list` shows the `Next` word only.
- **Guide** (`land_guide`): `LAND_NEXT` (`land`, `landed`, a land's `release`; `step_guide.guide(word, checks=,
  land=)` uses it once the view has a candidate) and `LAND_GUIDE`, one entry for every word the land's modules write
  (a test scans their `Failed(...)` calls) plus the release's `entry_running`, `not_terminal`, `unsettled`: `push_barred`,
  `not_done`, `not_checked`, `landing`, `not_landing`, `land_running`, `observe`, `no_change`, `changes`, `conflict`,
  `checks_failed`, `target_moved`, `no_remote`, `branch_moved`, `commit_missing`, `target`, `target_profile`,
  `no_required`, `remote_rejected`, `remote`, `git`, `tracker`, `store`, `claim_lost`, `closed`, `blocked`, `task`,
  `checkout`, `choices`, `slot_busy`, `no_free_slot`, `checks`, `changed`, `abandoned`, `profile`, and `unavailable`
  (the rerun line). Words shared with the step commands keep the land's meaning first. `GUIDE` gains `land`, `landed`
  (the `Next` word and the abandon's refusal share one text) and `landing`.
- **Release order** (`operations.release_task`, `_halves`): the latest checks attempt's latest candidate, when it still
  holds its slot, first (`ChecksRelease.release_candidate`, the L2 `CandidateTarget` on the checks releaser's store),
  then the checks attempt, then (abandon) the implement attempt. Settled, a candidate's release is the answer (the
  checks attempt's, already released, changes nothing). A candidate's refusal is `Failed(..., land=True)`, rendered with
  the land's guide (`refused:entry_running` for a live land process, `refused:not_terminal` for a settled release of a
  pending one); a pushable or delivered candidate not holding a slot is refused by the checks abandon's `LANDING` fence
  (`landing`, `landed`), as built in L1. `ReleasedTask` gains `land` and `candidate`; the text prints `released: land
  candidate <id> for <task> ...` first. A rerun of the abandon never releases the candidate again (it no longer holds
  its slot). The help of `tl step release` names the order.
- **Docs**: glossary (`land` as built, `landed`, `Next` words, `T` after a land, `block`/`result sink` for candidates,
  the land flags and `--abandon`'s order), the roadmap's built table, B6 as-built row and M3 row, INDEX, and the M3
  runbook [live-smoke.md](live-smoke.md) (section 21's outline made concrete: two slots, a second clone pushing to
  `main`, eight tasks; the multi-URL step marked blocked until git-porcelain 0.17.0 is pinned).
- **Contracts**: `land_status`, `land_guide`, `land_render`, `land_data` join the sources of
  `cli-never-imports-the-attempt-entry`; `land_render` and `land_data` join the command surface the entries never
  import. `rounds-never-land` holds with `attempt_status` importing `land_status` (it imports `land_store` only).

**Deviations (decided here, open to veto).**

1. **The summary is not printed before every land** (section 10 says "printed before every land"; L4 deviation 5 left
   it to L5). Printing it would make the CLI run two operations and fetch twice; the person's route is `--summary`, then
   the land (section 1, the `land` guide, the runbook), and the land's own answer names O, S and whether the checks ran
   again.
2. **A pending candidate is `Next: land`, not `release`**, although it holds its slot: section 14's first row read
   literally would send the person to `tl step release`, which refuses a pending candidate `not_terminal`; `tl step land`
   resumes it. `release` is for a validated or superseded candidate still holding its slot (section 4 step 5's rule).
3. Four new modules (`land_status`, `land_guide`, `land_render`, `land_data`) instead of growing `attempt_status`,
   `step_guide`, `step_render` and `result_data`; `check_line` takes the required names and a prefix.
4. `Failed` gains `land` (as it has `checks`) for a candidate's refused release; `tl step land`'s own refusals are
   recognized by the command.
5. The detail of a land refusal is split on `\n` only (a U+2028 in bd's words becomes a space, never a new line).

**Tests**: `tests/cli/test_land_cli.py` (flags to `LandRequest` for five flag sets, with `open_land` and `land.land`
replaced; usage errors exit 2 before any port; an absent factory.db refused and not created; help; a real same-tree
land's lines and JSON keys; each `how`; a close still to come; the summary and a withdrawal with their JSON; six
refusals and unknowns with their exit code, stderr, land guide before the step commands' and the rerun line exactly for
`unavailable`; a hostile detail printed printable; a guide for every word the land modules write).
`tests/steps/test_land_status.py` over `land_bench` (no candidate `land` with its guide; failed checks `done`; a
same-tree land's exact `Land` lines, `landed`, JSON; a close refused after the push `land` with `Pushed:` and no
`Closed:`; a validated land's slot, `Land check:` lines and log paths; a pending candidate with its land process running
or gone; a held release `release` with the land's guide; withdrawn; no change on failed checks `landed`; a hostile stored
reason printed as one printable line; the release order settled, abandoned, held by a live land process, refused
`landing`/`landed` with nothing changed, and its rerun). `test_checks_round` (+2: rounds silent on `land` and `landed`,
a land's `release` reported once and its slot never released, nothing relaunched). Existing tests changed only where a
passed check's `Next` is now `land` (five round assertions, one status row), the new JSON keys and `STEP_ONLY`.
Seventeen hand mutations (each reinstalled and run): fifteen failed a test at once; two survived as equivalent and the
code was simplified instead (the settled early return in `_halves`; the abandoned guard in `land_view`, removed, with an
assertion that an abandoned candidate shows as history).

**Not verified**: the M3 live smoke (section 21, [runbook](live-smoke.md)); a real terminal's rendering of the land's
answers beyond the tests' text; the multi-URL push guard (section 27.1 item 4, open: git-porcelain 0.17.0 unreleased);
whether a remote `pre-receive` refusal maps to `remote_rejected` or `unavailable git` (git-porcelain's classification,
the runbook records it).

### 29.1 Review repairs to L5 (2026-11-12)

An independent review of d1aca1601 found the `Next` words, JSON keys, exit codes, runbook flags and escaping sound, and
four defects plus two wordings; all repaired, each with a test that fails without it (six hand mutations, each failing a
test).

1. **(medium) An abandon stopping half way steered the person into landing.** `release_task` abandons the candidate
   first (released, superseded `abandoned`); when the checks half then failed (`unavailable store`, `changed`), the view
   read `Next: land` and `tl step land` would make candidate 2 and could push against the abandon. Now a latest candidate
   superseded `abandoned` on a checks attempt that is not abandoned (only the abandon marks it so) is `Next: release`
   with the guide `abandoning` ("rerun `tl step release --abandon`"), and `tl step land` (every mode) refuses
   `abandoning` at section 4 step 5, before any remote read or write. The `release_task` docstring says so. Test: the
   real candidate release, then a checks release failing `unavailable store`: `Next: release` with that guide; the land,
   `--withdraw` and `--no-change` refused with nothing pushed or run; the rerun of the abandon finishes.
2. **(low-medium) A candidate's refused release was guided as a land** (`LAND_GUIDE` and "rerun `tl step land`"). Only
   `tl step land`'s own refusals go to `land_render` now; a `tl step release` refusal with `land` set reads
   `land_guide.CANDIDATE_RELEASE` first (`unavailable`: rerun `tl step release`; `entry_running`, `not_terminal`,
   `unsettled`, `changed`), then the step commands' guide. `LAND_GUIDE["git"]` names the slot reset too. Tests: a live
   land process's `refused:entry_running` and an `unavailable:changed` render the release's words, never the land's.
3. **(low) The guide-coverage test saw only literal `Failed(kind, word)`.** It now enumerates every word a land answers:
   its modules' `Failed` words (both branches of a conditional), the candidate release's `NotReleased` words and the
   park's `slot_redirected`, `repo`, `not_listed`, the `StoreRefused` words of `land_store`, `check_store` and
   `setup_store`, the checkout's and slot choice's `AdmitRefused`/`AdmitUnavailable` words, the profile at O, the
   validation's `RELAUNCHED` words and `checks`/`environment`, and the kinds (agent-only `worker_*` and the checks
   admission's `task_attempted` excluded), and requires a `LAND_GUIDE` entry for each. Added: `refused`, `abandoning`,
   `absent`, `land_changed`, `stale_reservation`, `check_changed`, `setup_changed`, `lock`, `slot_dirty`, `slot_branch`,
   `slot_unborn`, `slot_redirected`, `repo`, `not_listed`, `deadline`, `expired`, `environment`, `check_running`,
   `setup_running`, `check_unknown`, `setup_unknown`.
4. **(low) An unobservable land process read `Next: land`.** A pending candidate whose stored land process observes
   `unknown` is `Next: unknown`, so `tl step list --stuck` lists it (as the agent and checks paths do). Test: listed
   `--stuck` with `unknown`.
5. **Wording.** `GUIDE["release"]` (the round prints it for a land's `release` too) says `--abandon` does not give the
   task back once a land's S is or may be on origin's `main`. The runbook's precondition names the L5 commit
   (`merge-base --is-ancestor d1aca1601`) and the repairs (`git grep '"abandoning"'` in `land_guide.py` at `SHA`), not
   L4.

Code lines after the repairs: `land_status` 43, `land_guide` 121, `step_render` 129, `land` 287, `step_guide` 191,
`operations` 366; `test_land_cli` 182, `test_land_status` 228. **Not verified**: as in section 29 (the M3 live smoke, the
multi-URL guard, the remote `pre-receive` classification).

### 29.2 M3 smoke findings repaired (2026-11-12)

The [M3 smoke](m3-smoke-findings.md) passed; its low-severity findings 1 to 6 are taken (7 is the host). Nothing of the
land's Git, store fences or order changed.

1. **Ctrl-C on `tl step land`** (finding 1). `cli_step._land` catches `KeyboardInterrupt` around the composition and the
   operation (as `_rounds` does; no signal handler: `interrupts.py` stays the one signal owner) and answers
   `Failed("unavailable", "interrupted")`: `tl step land: unavailable:interrupted`, the guide `LAND_GUIDE["interrupted"]`
   (a check it ran was stopped with it; the rerun marks it `interrupted` and repeats its block) and the rerun line, on
   stderr; JSON the usual error. Exit 130 kept (`exit_codes`: a `Failed` with the reason `land_guide.INTERRUPTED`, the
   shell's convention as the rounds' abrupt stop); the help names it. The land's own unwinding is unchanged (the shelf
   stops the running check's tree, the store and lock close).
2. **Process lines** (finding 2). `tl step show` prints a process by its pid only: `Entry: <state> (pid N)` and `Land
   process: <state> (pid N)`. The stored start is a clock-tick token that proves identity (the JSON keeps it), not a time;
   the agent's `Entry:` line printed the same token, so both lost it.
3. **`target_moved` and `remote_rejected`** (finding 3). The detail is the fact, the guide the action, no sentence in both:
   `target_moved` names O, the candidate and S ("nothing was pushed"), its guide what the rerun does and costs;
   `remote_rejected` names S and that the candidate stays validated, its guide the hand push to read origin's reason and
   that a rerun after that hand push records and closes (smoke section 7.4). origin's text is still never printed.
4. **`refused:landed` from the stored close** (finding 4). `factory_schema.CLOSED` (a candidate of the task closed it);
   the abandon's record word `closed` (`check_store.Recorded`; `check_store.record_release`, `abandon_released`,
   `land_store.record_release`, `check_release._landing_of` from the row) keeps the refusal word `landed` but its detail
   says "delivered S ... and closed the task: nothing is left to abandon or finish"; still unclosed it says "has not
   closed the task: rerun `tl step land` to finish the close". The checks re-run's `landed` (`check_admit`) keeps its
   words (not seen in the smoke).
5. **The lapsed lease** (finding 5): recorded in section 23 (answered), no code.
6. **No `round moves=0` after skips** (finding 6): already as designed since the S6e repair (the closing line's quiet key
   is its whole text). An abandoned task that is still ready is skipped by every round, quietly after the first, so each
   round has the same move count and the unchanged `round moves=2` is quiet; `round moves=0` comes once the skips stop.
   No code change; a test pins exactly that sequence.

Tests: the Ctrl-C answer, its exit 130, stderr lines and JSON (`test_land_cli`); the two refusals from the real
operation, fact then guide with no shared sentence and no origin text (`test_land_cli`); the abandon of a landed and
closed task worded from the close (`test_land_status`) and the store's `closed` for both abandon paths
(`test_check_store`); the skip sequence (`test_round`); the pid-only process lines (existing assertions changed). The
runbook ([live-smoke.md](live-smoke.md)) and glossary (`land`, `land candidate`) follow the words. Code lines by the
policy counter: `cli_step` 195, `exit_codes` 33, `land_guide` 125, `land_push` 146, `show_render` 102, `check_release`
221, `check_store` 290, `land_store` 215, `factory_schema` 209; `test_land_cli` 216, `test_round` 540, `test_check_store`
471, `test_land_status` 230. **Not verified**: a real terminal's Ctrl-C after this change (the smoke saw the old
traceback; the test raises `KeyboardInterrupt` from the replaced operation); a Ctrl-C landing between a push and its
record still answers `interrupted` and the rerun's `already_pushed` (section 12's row, tested before).

### 29.3 Decision: origin trusted as configured (2026-11-12)

**Decided by the owner, 2026-11-12:** "let others decide how to configure origins". `tl step land` adds no guard on how
`origin`'s URLs are set: the `push_url` refusal and `land_push.same_url` (every `url` and `pushurl` compared through
git-porcelain's `remote_urls`, before the reads and again right before the push) are removed, with their tests (the
fake table's `push_url`, `second_url` and `push_insteadof` rows, the two `push_url` tests of `test_land`, the
`remote_urls` fault and its two `test_land_push` tests, the three real-Git URL tests of `test_land_real`) and the guide
entry. Section 27.1 items 4 and 6 and section 24 finding 3 are superseded.

What stays: `origin` must exist (`no_remote`, a presence check through `remote_url`, the URL never kept or printed, as
`publish` does); the delivery rule of section 7 is unchanged otherwise: R from `ls_remote`, then the bounded fetch and
ancestry, each reading `origin` as the person's Git configuration resolves it, and the push to `origin` the same way.
A person who points origin's fetch and push at different repositories owns what land then reads and records. The
D10 residual (a block editing `.git/config`) is accepted without this mitigation (section 15). git-porcelain stays
pinned at 0.17.0 (released; no revert).

## 30. Trial defects repaired (tl-8bh9.14.34, .35, .41, .42, .43, .60; 2026-11-12)

Evidence: `docs/design/self-hosting-trial-2.md`, `-trial-4.md`, `-trial-5.md` and the beads.

### 30.1 Decision: a change of the gate is refused unless accepted (.42, .43)

**Problem.** A task could change what decides a pass (check argv, `setup`, `ruff.toml`, a test) and land with the plain
output `pushed ... Closed ...`: only `--summary` listed it, and the person may never run it. After the pull, every later
task passed the weakened gate.

**Decision (this slice, proposed to the owner with the PR).** One module, `land_gate`, reads the facts between O and S
(what would land, not X against O, so a main that moved since the branch is not shown as the task's doing) and is shared
by `--summary` and the land:

1. every changed file with its diffstat (`Worktree.diff(O, S)`);
2. each check added, removed or changed (argv or timeout), a changed `setup`, a changed `required` list;
3. each changed configuration file, by **one short shape rule** instead of a name list: a file at the repository root
   that is not documentation (`.md`, `.rst`, `.txt`), a `.toml`, `.ini` or `.cfg` file at any depth (`src/ruff.toml`,
   `tests/pytest.ini`), any `conftest.py`, any tracked file a check's or `setup`'s argv names (`./` prefix and a trailing
   `/` accepted; `.`, `..`, absolute paths and options name none). Tools whose configuration is a root file or a
   `.toml`/`.ini`/`.cfg` at any depth are covered without a list; **not covered**: a configuration in another format
   below the root (a nested `.json` or `.yaml`) that no argv names;
4. each changed test module (a `.py` named `test_*`, `*_test`, or under a `tests` folder) that was **weakened**: deleted,
   no longer parsing, fewer test functions, fewer `assert` statements, or more `skip`/`skipif`/`xfail` markers (an
   attribute `pytest.mark.skip` or a bare `skip()` after `from pytest import skip`) or file-level `# ruff: noqa`
   comments (parsed with `ast` and `tokenize` at O and at S; no text matching of code). Changes under `tests/rules/` are
   **not** special any more (the old list flagged any change there): they are test modules and follow this rule.

**Accepted misses** (the diffstat still lists them): a test made vacuous with the counts kept (an early `return`, `assert
True` swapped for one real assertion), tests moved to a path the rule does not call a test module, a rewrite of a
test module that keeps the test, assertion and marker counts.

**Accepted cost (false positives).** Merging assertions into one comparison or splitting a test module shows as
`Test weakened: assertions 3 -> 2` (or `tests` fewer) and blocks the plain land: the refusal says to rerun `tl step land`
with `--accept-gate-changes`, which is the way through; it is one flag on a command the person already runs.

Items 2 to 4 are *decisive*. A land whose S has any decisive fact is **refused** `refused:gate_changed` (exit 1, nothing
recorded), the detail being the same lines `--summary` prints (`land_summary.gate_lines`), until the person reruns with
`--accept-gate-changes`. The flag belongs to the person's call, never to rounds (which never land). An accepted land that
pushed also prints those lines (`Gate changes accepted:` after `Pushed:`, and a `gate` key in `--json`), read from the
delivered S against its O, so the plain output of the land that changed the gate names what it changed. A land that
changes none of it lands exactly as before (no flag, no extra output). `--no-change` has no S to compare and needs no
flag.

Why refuse and not just print: the plain land is the person's one command, often run in a loop; a line printed after
the push cannot be acted on. Why not derive "what the checks read": that needs each tool's own rules, which a list or a
tracer would always lag; the shape rule is short and documented here. Replaces section 10 items 4 and 5 (X against O,
a fixed name list).

### 30.2 Decision: a freed slot is left to a waiting land (.34)

Rounds refilled every freed slot within seconds, so `tl step land` answered `no_free_slot` for as long as the backlog
lasted. **Decision:** while any task of the backlog is at `Next: land` (checks passed, not landed), a round does not
start a step into the **last** free slot: new tasks and advances stop with the round word `slot_for_land` (not
`no_free_slot`: a slot is free) before it, and only a land (or a release) takes it. Tests: the freed slot stays free
across a round with a ready task, and the land validates in the one free slot. No new state: `Next: land` is already read by the round. The cost is one slot idle while a land
is pending, so a single slot runs nothing new until the person lands; that is the person's pending action. A land
waiting for its own turn queues nowhere: the rerun finds the free slot.

### 30.3 A lost ref race is the race (.35)

A push answered `remote_rejected` is read again by the delivery rule: when origin's `main` is no longer at O (the
winner's push landed) it is the `rejected` race of section 7 (candidate N+1, at most `target_moved`); `remote_rejected`
stays for every answer with `main` unchanged, **including** a ref lock still held after the winner's push failed to
update (rare; the rerun lands). The bead's lock-held case is covered only when main moved.

### 30.4 Setup log failures name the artifacts directory (.41)

An artifacts directory that cannot be written when a setup or check log opens is `unavailable:log`, no longer
`environment:files` (which is the slot's own folders). The land names the directory, advises fixing its permissions or
space and says nothing about the task branch or main; a rerun is safe (the candidate resumes).

### 30.5 A checkout that is not a repository is a refusal (.60)

`checkout_repo` answers `refused:checkout` naming the path when Git says `NotARepo` (a missing directory, a directory
outside any repository), exit 1; `unavailable:git` stays for transient Git faults. Shared by `tl step next`, `start`
and the land.

## 31. Trial 6 defects repaired (tl-8bh9.14.64 to .68; 2026-11-12)

### 31.1 Decision: a checks attempt that failed `main_moved` is re-run by the round, never held (.64)

A plain land of task A moves origin `main` while task B's checks run; B's checks attempt concludes `failed:main_moved`
(`validate._moved`). Holding B was wrong twice: the cause is nobody's fault, and the hold's recovery (re-add the label)
abandons the attempt and replans and re-implements from scratch, though only the checks need to run again on the new `main`.
Decision, the smallest correct behaviour: `main_moved` is not a hold cause (`hold_status.cause` returns none for it), and a
round re-runs the checks of a done task whose latest checks attempt failed so (`round._rerun` puts such a view in the advance phase, oldest release first, so
`_advance` handles it as any advance: `start` routes to `check_status.route` `rerun`, attempt number + 1, the same commit,
the required names read again from `main`; no plan, no implement, claim kept; the move is `<task> check advance started
<id>`; a refusal is classified as the advance's: `claim_lost`/`branch_moved` hold the round-taken task, a stop word
(`ADVANCE_STOPS`, `no_free_slot` included) ends the phase, another is a per-task skip tried again next round).
**Cap (decided):** the third checks attempt of a task failing `main_moved` in a row (`hold_status.MAIN_MOVED_RUNS` = 3) is
held, as every other failure, with `hold_cause` text naming it (main moved while each of the last checks runs ran); a pusher
faster than the checks cannot loop the task. Every other check failure stays a hold. **A hand-started task is not re-run
by rounds** (`_rerun` needs the round's label): it is reported `failed:main_moved` and `tl step start` re-runs the checks
by hand, as the `main_moved` guide says.

### 31.2 A deleted task is `task_missing` whichever bd command says so (.65)

bd 1.3.1 words a deleted task two ways: `no issue found matching "X"` (update, close) and, for `bd show`, `no issues found
matching the provided IDs`. Only the first was recognised, so the advance's one tracker read classed the second
`tracker_unavailable`, stopped the round and backed off. `tracker.gone` matches both; the advance, admission and every
other caller then answer the per-task `skip task_missing`, whose detail names `tl step release --abandon <task>`. Not
verified: a deleted task with a running entry (its verify and release do not read the task through `show`).

### 31.3 `tl step show` carries a `needs_owner` explanation (.66)

A hand-started step is never held, so nothing wrote the agent's question anywhere but `answer.txt`. `show_attempt` reads the
stored valid answer's explanation (`hold_facts.explanation`, the decoder the hold uses) when the result is `needs_owner`;
`show` prints it (`hold_text.explained`: bounded, printable, quoted) under `The agent explained:` and the `Next` guide says
to answer by editing the description, then `tl step release --abandon` and `tl step start` (after `release` for a slot still
held); no check-step text.

### 31.4 Decision: a slot left on the task branch is named with its fix; a dirty slot is never cleared for you (.67, .46)

After a `factory.db` discard `tl slot adopt` refuses the slot an agent left on `task/<id>` (`attached`), so no slot row names it
and no slot read could show it; the retaken task then met `branch_held` with s2 free, and nothing said which slot held the
branch. `branch_held` now carries `prepare.held_slots` (the linked worktrees on the branch, as `attached` views named by their
folder) and a detail naming each with the fix: `git switch --detach` there (what it holds is committed or stashed first), then
`tl slot adopt`. The round writes the refusal's slots as `report unusable:<slot>:attached` lines (the path under the line in
`tl step next`), like `no_free_slot`'s. The owner decision for .46 stands: no slot's content is deleted automatically and
there is no `--discard` flag; a dirty slot is fixed by the person, and the hold comment and guide list the leftover paths
(.46's work, not this change).

### 31.5 `tl step show` lists the refs of `head_moved`; the verify guide names `branch` (.68)

`Verifier.leftovers` (the read `tl step show` and the hold use) returned nothing once HEAD moved; it now returns the same
`head_moved` listing `tl step verify` prints (the tags and branches that name a commit the agent made), unless the adopt rule's
commit settles it. `attempt_status` keeps that one non-repeatable leftover on the view (`Unsettled: head_moved` and its refs;
the next action stays `verify`). The `unsettled` guide names `branch` (the agent left the slot on another HEAD): `git switch
task/<id>` in the slot when its work is on that branch, then `tl step verify`, else `release --abandon` and start again.
