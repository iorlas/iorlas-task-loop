# tl-8bh9.14.8: land and close (block B6, milestone M3)

Design, 2026-11-11, against 08784fe34 (M2 built, M2 smoke passed and its findings fixed). Docs only: nothing built or
run. Read: CLAUDE.md, [glossary](../../glossary.md), [roadmap](../self-hosting-roadmap.md) (B4, B6, B7, D1-D14, O1-O6),
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
for minutes when checks run); nothing else does. It is **never automatic**: an import-linter contract `rounds-never-land`
forbids `round`, `rounds`, `operations`, `attempt_entry` and `check_entry` from importing `land`, `land_push` or
`land_summary` (status reads `land_store`, which only records). Rounds keep running beside a land; they see its slot reserved and nothing else.

`LandRequest(backlog, task_id, checkout, minutes, summary_only: bool, no_change: bool)`. CLI:

```
tl step land TASK --backlog KEY --checkout PATH --minutes N [--summary] [--no-change] [--db] [--artifacts] [--json]
```

The tracker root is the implement attempt's stored one (as the checks entry renews the claim there), so no
`--tracker-root` flag (decided here: one tracker per task, never a second binding).

`--minutes` is the deadline of a validation block if one runs (required, as for `tl step start`; unused otherwise).
`--summary` prints the land summary (section 10) and changes nothing in factory.db, the slots, the remote or the tracker
(it fetches, see section 5). `--no-change` accepts the no-change disposition (section 5, step 6). Exit codes as every
step command: 0 landed (or already), 1 refused, 3 unknown (rerun is safe).

**Foreground, not an entry process (decided here).** Validation runs inside the `tl step land` process, not through a
launched entry: the land is the person's command and waits for its result; rounds must not relaunch it. Restart safety
comes from the same records the checks entry uses (every command's identity committed before it runs, the reconcile
before any slot access), not from relaunch. No land lock: the factory.db fences of section 11, the slot's custody lock
during validation, and idempotent Git and tracker actions make two concurrent `tl step land TASK` safe (the second
refuses `landing` or finds the work done). A Ctrl-C ends the process (Python's default; no signal handler, `one-signal-owner`
stays true); a check it started keeps running in its own session and the rerun reconciles it.

## 4. Preconditions, in order, every read before any effect

Refusal words are `refused <word>` (exit 1) unless written `unavailable` (exit 3).

1. `--minutes` valid (`deadline`); this process's environment does not carry the agent's push bar
   (`url.delegate-push-refused://.pushInsteadOf` among `GIT_CONFIG_*`): **`push_barred`** ("land runs only from the
   person's own shell"). An agent's environment therefore cannot land even if it reaches `tl`.
2. factory.db current (v13), else `unavailable store` / `refused schema`.
3. The task's current agent attempt is a done implement attempt: implement, verified, released `kept`, published at X
   (`admit_chain`'s done-ness reads, shared with `check_admit`), else **`not_done`** naming its `Next`. The plan step is
   implied: an implement attempt 1 exists only as the advance from a verified, published plan (`after_commit`), so land
   does not re-read the plan attempt (decided here).
4. Its latest checks attempt: concluded `passed`, released, not abandoned, else **`not_checked`** with that attempt's
   `Next` and result (a failed one: re-run with `tl step start`, or abandon).
5. The checkout's repository is the attempt's (`checkout`); `origin` exists (`no_remote`).
6. **X is still the task's work**: the local `task/<id>` (else the remote-tracking one) is exactly X, and origin's
   `task/<id>` is exactly X (one `ls_remote` with the two patterns `refs/heads/main` and `refs/heads/task/<id>`). Ahead of X
   or elsewhere is **`branch_moved`** ("commits after the checked X: abandon and restart, or reset the branch"): land lands
   exactly what was checked. X unreadable is `commit_missing`.
7. One tracker read (`admit.read_task`): `in_progress` assigned `taskloop`, else **`claim_lost`**; `closed` with no pushed
   candidate is **`closed`** ("closed in the tracker without a land"); `closed` with one goes to section 8's record.
8. The latest land candidate of this checks attempt (section 11), if any, decides where to resume (section 12). It is
   read right after step 4: a closed one answers `already_landed` with no Git or tracker call; a delivered one skips
   steps 5-6 and goes to the close (section 8) after step 7's read.

The checks attempt's claim is kept by the implement attempt's release; land neither claims nor unclaims (a `bd unclaim`
would reopen the task). Its close ends the claim.

## 5. The candidate S (one squash commit, no checkout)

Letters (glossary additions): **O** is origin's target tip as the land fetched it; **S** is the land candidate, one
commit whose parent is O and whose tree is X merged onto O. T keeps its meaning (the remote tip after a push: after the
land's push T is S).

1. **Fetch** `+refs/heads/main:refs/remotes/origin/main` through the `remotes` view of the person's checkout (bounded
   transport, hooks off, the person's config and credentials): a remote-tracking ref, as the person's own `git fetch`
   writes it; never a local branch, index, HEAD or worktree. `Transient` is `unavailable remote`. O is the fetched
   remote-tracking ref; origin without `main` is `refused target`.
2. **The target profile at O** (`profile.read_profile` on the checkout's `GitProfileFiles` at O): `Refused` is
   `target_profile`; its `target` must be `main` (another land branch is not built: `target`); `required` non-empty
   (`no_required`). The required list at O is stored with each name's argv digest at O (`check_store.required_json`).
3. **Squash** through a new git-porcelain operation (slice L0): `Repo.squash(onto=O, head=X, message) -> Squashed(sha,
   tree) | Conflicted(paths)`, object writes only (real: `git merge-tree --write-tree` then `git commit-tree -p O`; the
   person's `user.name`/`user.email` as author and committer; no hook, no signing). `Conflicted` is **`conflict`** with
   the first 20 paths and a count; nothing is recorded. The commit message is section 9's.
4. **Same tree?** S's tree is X's tree (`Repo.tree_id`, also L0) exactly when O is an ancestor of X, or main's changes were
   already in X.
5. **Required names changed?** The set of names required at O differs from the checks attempt's stored names.
6. **No change**: S's tree is O's tree (main already holds X's changes, for example a hand land) is **`no_change`**
   unless `--no-change` is given; with it the candidate is recorded with `validation` and `delivery` `no_change` (no
   slot, no push) and section 8 closes the task with the reason "already on main at O" (the delivery contract's explicit
   no-change disposition).

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
   land of the task meets), held to the release.
3. **Claim keep-alive**: one renewal (`attempt_entry.renewal`; `lost` concludes `failed claim_lost` after the
   reconcile), then `claim_lease.keeping` for the setup and the block, as the checks entry.
4. **The shared validation flow** (slice L2 extracts it from `check_entry` into `validate.py`, unchanged in behavior for
   checks): the reconcile of the latest setup run and the latest block's unsettled results (alive `unavailable
   checks:running`, unknown `checks:unknown`, gone `interrupted`); the deadline (`expired`); the profile at S on the slot's
   pinned view (`profile:<reason>`), its digest stored once; a completed latest block concluded as it stands; S taken
   detached (`prepare.detach_at`); reset to exactly S and `setup` at S (`environment.prepare_for`, no probe, no reuse);
   the block (`checks.Block.run` with `BlockTarget(slot, view, S, required at O, deadline, check_env(scrubbed))` and
   `CheckSink(store, candidate key, files, clock)`); the conclusion from the latest block (`checks.conclusion`). The one
   difference from checks: no local `main` watch (`moved` is None for land). The required names were read from the
   remote target's immutable objects at O, and the push itself verifies O (section 7), so a rewritten local ref cannot
   make a land pass.
5. Section 6.1 of the checks plan maps the words: a terminal one concludes the candidate `failed <reason>`; a relaunchable
   one leaves it pending and the land answers `unavailable <word>` (no counter: nothing relaunches a land but the person).
6. **Release** of the slot under the lock it holds (`check_release`'s release, generalized over its target in L2): the
   stop proof, the reset to S, the park at D, the record, `slot_release.free`, the scratch emptied. A held release
   (`held:check_running`, `held:slot_dirty`) does not stop a passed land from pushing; the rerun retries it, and `tl step
   release TASK` can release it (section 13).
7. Passed goes on to section 7. Failed answers **`checks_failed`** with the reason (`<name>:<conclusion>`, `setup:...`,
   `expired[:<name>]`, `claim_lost`, ...) and the log paths; nothing is pushed.

A rerun of `tl step land` with a pending candidate renews its deadline to `now + --minutes` (one fenced update: the
person's new command is new consent) and resumes at step 2. Its results go to `check_result` and its setup runs to
`setup_run` under the candidate's key (section 11); its logs are `check-<block>-<name>.log` and `setup-<run>.log` in the
candidate's evidence directory.

## 7. The push (non-forced, pinned, resumable)

Through `land_push.py` (new; it shares `publish._relation` and the `remotes` view):

1. **Read origin's `main` now** (`ls_remote`): equal to S, or containing S, is already delivered: record `pushed`
   (`remote_head` the tip read; the answer says `already_pushed`). Not O and not containing S is **`target_moved`**:
   nothing pushed; the candidate stays as history; the person reruns and the rerun makes a new candidate (number + 1),
   validated as section 5 says. At most one new candidate per invocation, so a busy `main` costs the person a rerun,
   never an unbounded loop (decided here).
2. **Push** S with the existing push port, exactly as `publish` pushes `task/<id>`:
   `repo.worktree(checkout).push("main", remote="origin", head=Sha(S))` from the person's checkout, never forced, no
   force-with-lease, no refspec with `+`, hooks off. Git's fast-forward rule is the condition: it refuses unless origin's
   `main` is still an ancestor of S, that is still O (S's only parent). `Pushed` records `pushed` (`remote_head` S) in
   one fenced transaction. `RefRejected`: one `ls_remote` again, then step 1's classification (another lander won the
   race: `target_moved`). `Transient` is `unavailable remote`; `RemoteRejected` is **`remote_rejected`** ("origin refused
   by its own policy, for example a protected `main` that requires a pull request; PR mode is held: push by hand to see
   why"); `HookRejected` is `unavailable git`.
3. **Uncertain acknowledgment** (the process died, `Transient` after the remote updated): no record; the rerun's step 1
   observes origin and records `already_pushed`. Nothing is ever pushed twice in a way that changes the remote: a second
   push of S to a remote at S is up to date.

The factory's push to origin's `main` (O3, decided here as the roadmap recommends): only from `tl step land`, with the
person's credentials through their Git configuration (SSH agent, credential helper, `pushurl` and `insteadOf` rules
apply as in their shell); never from an agent process (step 1 of section 4, and an agent's push bar makes any push fail
anyway).

## 8. Close the task (tracker port), and tracker sync (O4)

`TrackerClaims` gains `close(tracker_root, task_id, reason) -> Closed | ClosedBefore | CloseLost | CloseUnavailable`
(`tracker_client`: one tracker read, `Bd.show`; `closed` is `already_closed`; else `Bd.close(task, reason,
if_assignee="taskloop")`, its fence a same-value update; `BdError` of kind `precondition`/`not_claimable` is `claim_lost`,
any other `unavailable tracker`). Reason: `Landed <S> on main (task/<id> at <X>)`, or `Already on main at <O>` for a
no-change land. Recorded once (`closed_at`, `close`), fenced on the delivered candidate.

After a push, a failed close leaves the candidate delivered and the task open: `tl step show` says `Pushed:` and `Next:
land`; the land answers `unavailable tracker` (rerun) or `refused claim_lost` ("the code is on main; close the task by
hand with `bd close`; a rerun then records it `already_closed`"). A rerun goes straight to the close: no fetch, squash,
check or push.

**Tracker sync (O4, decided here): never automatic.** Land closes the task in the person's local tracker only. Its
answer always ends with `Tracker: closed locally, not synced (bd dolt push shares it)`; the factory
never runs `bd dolt push`, `bd sync` or any remote tracker operation (a remote operation needs its own authority, as Git
pushes do; one machine needs none). Land is complete for the factory once the close is recorded.

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

The title is the tracker's (`TaskInspection.title`, read in section 4 step 7): one line, control characters dropped,
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
4. Checks added, removed or changed at X against O (they ran on the host too), and a changed `setup` (both shown).
5. Every changed check-configuration file between merge-base(O, X) and X: `.task-loop.json`, `justfile`,
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
 checks_attempt_id TEXT NOT NULL REFERENCES checks_attempt(attempt_id),  -- the passed, released checks attempt of X
 number INTEGER NOT NULL CHECK(number >= 1),                             -- 1, then + 1 per new candidate
 target_commit TEXT NOT NULL CHECK(length(target_commit) IN (40,64)),    -- O: origin's main as fetched
 commit_sha TEXT NOT NULL CHECK(length(commit_sha) IN (40,64)),          -- S
 tree_same INTEGER NOT NULL CHECK(tree_same IN (0,1)),                   -- S's tree is X's
 required TEXT NOT NULL,                                                 -- JSON [[name, argv digest at O], ...], 1..32
 slot TEXT, slot_head TEXT CHECK(slot_head IS NULL OR length(slot_head) IN (40,64)),  -- the validation slot and its D
 deadline REAL, profile_digest TEXT CHECK(profile_digest IS NULL OR length(profile_digest)=64),
 validation TEXT CHECK(validation IN ('same_tree','no_change','passed','failed')), reason TEXT, validated_at REAL,
 released_at REAL, parked TEXT CHECK(parked IS NULL OR length(parked) IN (40,64)),
 delivery TEXT CHECK(delivery IN ('pushed','no_change')), delivered_at REAL,
 remote_head TEXT CHECK(remote_head IS NULL OR length(remote_head) IN (40,64)),
 close TEXT CHECK(close IN ('closed','already_closed')), closed_at REAL,
 rev INTEGER NOT NULL DEFAULT 0,
 CHECK((slot IS NULL) = (slot_head IS NULL) AND (slot IS NULL) = (deadline IS NULL)),
 CHECK((slot IS NULL) = (validation IN ('same_tree','no_change'))), CHECK((validation IS 'no_change') = (delivery IS 'no_change')),
 CHECK((validation IS NULL) = (validated_at IS NULL)), CHECK((validation IS 'failed') = (reason IS NOT NULL)),
 CHECK((released_at IS NULL) = (parked IS NULL)), CHECK(released_at IS NULL OR slot IS NOT NULL),
 CHECK((delivery IS NULL) = (delivered_at IS NULL)), CHECK((delivery IS 'pushed') = (remote_head IS NOT NULL)),
 CHECK(delivery IS NULL OR validation IN ('same_tree','no_change','passed')),
 CHECK((close IS NULL) = (closed_at IS NULL)), CHECK(close IS NULL OR delivery IS NOT NULL),
 UNIQUE (checks_attempt_id, number)
);
CREATE UNIQUE INDEX land_delivered ON land_candidate(checks_attempt_id) WHERE delivery IS NOT NULL;
```

`check_result` loses `REFERENCES checks_attempt(attempt_id)`: its `attempt_id` names a checks attempt or a land
candidate (both uuid4 hex), as `setup_run`'s already names an attempt or a checks attempt. Nothing else in v12 changes.
**What else batches into v13 (decided here): nothing**; B7 has no design yet (if its DDL is settled before L1 is built,
it joins v13 so the owner discards once).

**What the rows mean.** One row per candidate; "latest" is the highest `number` of one checks attempt. A no-change
candidate has no slot and is inserted with `validation` and `delivery` both `no_change`. A candidate is **pending** while it holds
a slot with `validation` NULL; **superseded** when it is not the latest; a pending one released without a validation (an
abandon's or a hand release) is dead and the next land makes a new one. At most one candidate of a checks attempt is
delivered (the partial unique index). No task fact is copied: every read joins `checks_attempt` and `attempt` for the
task, repository, tracker root and X, as `check_store` does.

**Fences** (`land_store`, the one writer of `land_candidate`):
- `insert`, in the transaction that reserves the slot: the checks attempt is the latest of its implement attempt,
  `passed`, released, not abandoned; the implement attempt is current (`factory_schema.SUCCESSOR`'s `LATER` part) and its
  claim `kept`; no candidate of it is delivered; the latest candidate holds no slot; `number` is the latest + 1 (a lost
  race is `landing`).
- Validation writes (`renew`, `profiled`, `conclude`) and its results and setup runs: `land_store.HELD`, the candidate
  pending and its reservation held at its generation. `check_store.HELD` becomes `UNION ALL` of the checks fence and
  `land_store.HELD` (bound with the key twice), so `CheckSink`, `CheckStore.block/start/registered/finish/undefined/
  results/unsettled` serve a candidate key unchanged; `setup_store.HELD` becomes the three-way union (key three times).
- `record_release` (in `check_release`'s transaction), `record_delivery` (after `Pushed`, or observed), `record_close`.
- **The abandon fence** `factory_schema.LANDING`: a checks attempt with a delivered candidate, or a candidate holding a
  slot, cannot be abandoned. `check_store.record_release(..., abandoned=True)` and `abandon_released` add `NOT LANDING`;
  their refusal words are `landed` and `landing`.

**Writers** (`test_policy.WRITERS`): `CREATE TABLE land_candidate` and the index by `factory_schema.py`; `INSERT`/`UPDATE`
of `land_candidate` by `land_store.py`. `GIT_WRITES` gains `squash` (owner `land.py`), and `fetch` and `push` gain the
owner `land_push.py` (`push` keeps `publish.py`).

## 12. Restart and recovery: a rerun does only what is missing

| Interrupted after | factory.db | The rerun |
|---|---|---|
| nothing written (fetch, squash, a refusal) | no candidate | starts over |
| the close recorded | delivered and closed | `already_landed`, nothing called |
| a same-tree insert | latest `same_tree`, not delivered | section 7 step 1: origin at O pushes; at or past S records; moved is `target_moved` |
| part of a block (Ctrl-C, crash, reboot) | pending, slot reserved, results unfinished | deadline renewed; reconcile (a check still running: `unavailable checks:running` until it ends); the interrupted block repeats whole, a completed one concludes as it stands |
| a concluded validation, slot not released | `passed`/`failed`, `released_at` NULL | the release (stop proof first), then the push if passed |
| the push sent, its answer lost | `passed`, not delivered | origin read first: S there is recorded `already_pushed`, never pushed again |
| the push recorded | delivered | straight to the close |
| `bd close` done, its record lost | delivered, not closed | tracker read: `closed` is recorded `already_closed` |
| S pruned by `git gc` (a candidate left unpushed for weeks) | `passed`, not delivered | S unreadable: the candidate is superseded, a new one is made |
| factory.db discarded after the push | nothing | `refused not_done` (no done attempt): the person closes the task by hand; origin's `main` has S, its subject names the task. No reconstruction (CLAUDE.md) |

There is no exactly-once across Git and the tracker: each external effect is observed before it is repeated, and the
record follows the observation.

## 13. Abandon, release and D4

- **Before a delivery**: `tl step release --abandon TASK` goes land candidate first, then the checks attempt, then the
  implement attempt (`operations.release_task` gains the first half): a candidate holding a slot is released in abandon
  mode (the generalized checks release: stop proof, reset to S, park at D; no flag on the candidate, which is then dead),
  then the existing order. A failure between halves shows `Next: release`; rerunning `--abandon` finishes. D4 applies:
  the next start is a fresh plan.
- **After a delivery**: the abandon refuses **`landed`** (`LANDING` in the checks abandon fence): the code is on `main`;
  `tl step land` finishes the close. The race with a land's insert is fenced both ways (the insert requires the checks
  attempt not abandoned; the abandon requires no candidate holding a slot or delivered); both orders tested.
- **`tl step release TASK`** (settled) with a concluded candidate still holding its slot releases it, so a person can
  free a slot a land left held without landing.
- **A failed land validation** leaves the task `Next: land`: rerun (flaky: a new candidate runs the block again), or
  abandon (D4: plan, implement on the current branch, checks, land). A conflict likewise: the person merges `main` into
  `task/<id>` by hand and pushes it, then abandons; the restarted plan and implement agents find the merge on the branch
  (each answers `unchanged` or commits), and the checks run on the new X. That costs two agent runs; a merge step is
  deliberately not built.
- **A hand land** (the M2 way) is reported by the next `tl step land` as `no_change`; `--no-change` records it and closes
  the task.

## 14. Status: `tl step show`, `list`, `Next`; rounds untouched

`attempt_status`: when the view is a checks attempt `passed` and released, `land_store.latest(checks attempt)` and its
latest block's results fill `AttemptView.land: LandView | None`. `Next` (the checks view's `done` when passed):

| State | `Next` |
|---|---|
| no candidate, or the latest not delivered, or delivered and not closed | `land` |
| delivered and closed | `landed` |
| failed checks attempt | `done` (unchanged) |

`round._settle` treats `land` and `landed` as silent (`case "land" | "landed": return`): rounds never act on, report or
release a land. `tl step show` adds, after the check step's lines (JSON key `land`, null without a candidate):

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

A same-tree candidate prints `...: <S>; same tree as X, no checks` and no slot or check lines. `tl step list`: the
`Next` word only. GUIDE gains `land` ("read the diff and `tl step land TASK --summary`, then `tl step land TASK`"),
`landed` ("nothing left; `git pull --ff-only` in your checkout"), and one sentence for each new refusal word.
`STEP_ONLY` names `land`.

## 15. Security

- **Who pushes**: the `tl step land` process, from the person's checkout, with the person's environment, Git
  configuration and credentials (`remotes` view: no push bar, hooks off, bounded transport, no prompt). Only the existing
  push port, never forced, pinned to S. Section 4 step 1 refuses an environment with the agent's push bar. Rounds and
  entries cannot import land (`rounds-never-land`). An agent session in the person's shell can run `tl step land` only
  as a person can: by CLAUDE.md that needs the person's explicit authority for remote publication; the factory cannot tell
  who typed the command.
- **What runs before the push**: a validation block runs the candidate's `setup` and checks on the host (D10, accepted),
  as the checks step did; S combines only code the person read (X's diff) with code already on `main`.
- **Accepted residual, recorded (D10)**: code run by a block shares the repository's Git directory with the person's
  checkout and could edit `.git/config` (`remote.origin.pushurl`, `url.*.insteadOf`, `core.sshCommand`) before the land
  pushes with the person's credentials. Not mitigated beyond D10's acceptance; the summary cannot detect it. A later
  review of the change set for suspicious code (roadmap section 6, deferred) is the place for it.
- **Remote truth, not local refs**: O comes from a fetch, the required names from O's objects, and the push's
  fast-forward rule and `ls_remote` check origin itself; a block rewriting a local ref changes nothing land relies on.
- Unsigned commits only (`hardened` views): a target that requires signed commits answers `remote_rejected`.

## 16. Failing-land routes

| Answer | What the person does |
|---|---|
| `not_done`, `not_checked` | Finish the steps (`tl step show`), re-run failed checks with `tl step start`, or abandon |
| `branch_moved` | Reset `task/<id>` (local and origin) to X, or abandon and restart (D4) to check the new commits |
| `conflict` | Merge `main` into `task/<id>` by hand, push it, abandon; the restart checks the merge (section 13) |
| `checks_failed` | Read the `Land check:` logs; rerun `tl step land` (flaky), or fix as for a conflict |
| `target_moved` | Rerun: a new candidate onto the new `main` (validated if its tree differs) |
| `no_change` | Confirm `main` holds the work, then `tl step land --no-change` |
| `remote_rejected` | Origin's policy (protected `main`, signed commits): land by hand or change the policy; PR mode is held |
| `claim_lost`, `closed` | Another actor owns the task: inspect it in the tracker; a pushed land needs only `bd close` |
| `push_barred` | Run land from your own shell |
| `target`, `target_profile`, `no_required` | Fix `main`'s `.task-loop.json` |
| `unavailable remote`, `tracker`, `store`, `git`, `slot_busy`, `no_free_slot`, `checks:running`, `checks:unknown` | Rerun later (a free slot: wait for one or stop rounds) |
| `landed` (from `--abandon`) | Rerun `tl step land` to finish the close |

## 17. Glossary changes (slice L5)

| Term | Meaning |
|---|---|
| land (as built) | `tl step land TASK`: the person's command that squashes the checked X onto origin's `main` as one commit S, validates S when its tree is not X's or `main`'s required names changed, pushes it never forced, and closes the task; a rerun does only what is missing. Never run by rounds. |
| landed | The land's end: S (or the no-change disposition) delivered to origin's `main` and the task closed in the local tracker. `Next: landed`. Tracker sync stays the person's (O4). |
| land candidate | One squash S of X onto one O, with its validation (`land_candidate`): `same_tree` or a block's `passed`/`failed`; numbered per checks attempt; at most one delivered. |
| land summary | The facts printed before a land (`--summary`): the checks, the required names at O, changed argv, checks and `setup`, changed check-configuration files, the commit message. Facts, no judgment. |
| O, S (commit letters) | O: origin's target tip as the land fetched it (`land_candidate.target_commit`). S: the land candidate (`commit_sha`). |

Also: `Next` gains `land` and `landed`; `land` replaces the roadmap's "not built" row; `check result` and `block` say a
land candidate's block uses the same rows; `result sink` names `CheckSink` for both; the `T` row says after a land T is S;
STEP_ONLY and the CLI flags table (`--summary`, `--no-change`).

## 18. Owner questions

**Blocking: none.** Decided here, each built so unless vetoed:

1. **O3**: the factory pushes to origin's `main` only from the person's `tl step land`, a direct squash push, no PR.
2. **O4**: land never syncs the tracker; it says so and names `bd dolt push`.
3. **Validation on a changed result only**: the whole block on S when S's tree differs from X's or the required names
   changed; none otherwise (no pass lookup: the same tree). Cost in section 5.
4. **Foreground validation**, no entry process, no relaunch, no land lock.
5. **At most one new candidate per invocation** (`target_moved`: rerun).
6. **`branch_moved` when `task/<id>` holds commits after X**, locally or on origin: land lands exactly X.
7. **`--no-change`** for a target that already holds X's changes; refused without it.
8. **Squash in Git objects** through a new git-porcelain operation (slice L0), never in a slot or the person's checkout.
   Not chosen: `Worktree.record(mode="squash_to")` and `rebase_onto` in a slot (a slot for every land, and a rebase's
   squash rule unverified on a detached HEAD); `history.merge` (an unpinned module function on a path).
9. **Commit message** from the tracker title and the branch's commit subjects; author the person; no co-author trailer.
10. **Branches kept**: land deletes neither `task/<id>` nor anything else.

## 19. Slices (caps: 400 code lines per file, 80 per function, 800 per test file)

Code lines by the policy counter at 08784fe34 in brackets.

| Order | Slice | What | Source | Tests |
|---|---|---|---|---|
| 0 | **L0 shelf: git-porcelain squash** | `Repo.squash(onto, head, message) -> Squashed(sha, tree) \| Conflicted(paths)` and `Repo.tree_id(rev)` in git-porcelain 0.16.0 (real: `merge-tree --write-tree`, `commit-tree`; fake over `fake_merge.merge_trees`; one contract suite); the pin bump here | shelf ~+110; here `pyproject`/`uv.lock` | shelf ~+220 (clean, conflict, already merged, same tree, identity, no hook) |
| 1 | **L1 schema v13 and the land store** | DDL (section 11) and column lists; `land_store.py` (`LandRow` joined, `insert`, `latest`, `of_checks`, `renew`, `profiled`, `conclude`, `record_release`, `record_delivery`, `record_close`, `HELD`); `check_store.HELD` union, `LANDING` in its abandon fences; `setup_store.HELD` three-way; `WRITERS` | `factory_schema` [153] +40, `land_store` new ~220, `check_store` [~280] +12, `setup_store` [99] +3 | `test_land_store.py` ~420; `test_check_store` +50 (candidate key through the union, abandon refused `landed`/`landing`); `test_setup_store` +20 |
| 2 | **L2 shared validation and release** | `validate.py` extracted from `check_entry` (reconcile, profile, completed block, take, environment, block, conclusion; `moved` a parameter; `concluded` moved with it): checks behavior unchanged; `check_release.ChecksRelease` over a `ReleaseTarget` port (row read and record) with the checks target and `land_store`'s | `validate` new ~170, `check_entry` [~215] -110, `check_release` [~135] +25, `land_store` +25 | `test_check_entry` unchanged and green (the guard); `test_validate.py` ~200 (the `moved` None path, a candidate key); `test_check_release` +90 (a candidate released settled and abandoned, reset to S, park at D) |
| 3 | **L3 the land operation: candidate, validation, push** | `land.py` (section 4's reads, the fetch, the target profile, the squash, the candidate insert with its reservation, the validation driver with the keep-alive and release, the resume table of section 12 without the close); `land_push.py` (section 7, sharing `publish._relation`); `composition.open_land` (over `open_checking`'s `Checking`); `GIT_WRITES` owners; `rounds-never-land` contract | `land` new ~260, `land_push` new ~110, `composition` [146] +35, `publish` +2 | `test_land.py` ~650 (each refusal with nothing written; same tree pushes; moved target validates; required changed validates; conflict; resume after each row of section 12 but the close; concurrent lands; the abandon race both orders); `test_land_push.py` ~330 (every push result, observed delivery, `target_moved`); `real/test_land_real.py` ~180 (a bare origin: same tree, moved main validated with `sh -c` checks, `RefRejected` after a racing push) |
| 4 | **L4 close, message, summary** | `tracker_client` close port (+18); `land.py` close and record (+45); `land_summary.py` (section 9 message, section 10 summary); `--summary` path | `land_summary` new ~150, `land` +45, `tracker_client` [~70] +18 | `test_land_summary.py` ~300 (each summary item, message bounds and sanitizing); `test_land.py` +150 (close, already closed, `claim_lost` after push, record lost, no-change); tracker double +30 |
| 5 | **L5 surface and words** | `cli_step` `land` subcommand and flags (+25), `cli_composition` (+30), `result_data` `Landed` (+30), `show_render` land lines (+45), `attempt_status`/`check_status` `LandView` and `Next` (+40), `round._settle` silent (+2), `operations.release_task` land first (+25), `step_guide` (+30); glossary (section 17), roadmap B6 row, INDEX status; the M3 runbook `live-smoke.md` | about +230 | `tests/cli/test_land_cli.py` ~300; `test_check_status` +70; `test_check_operations` +90 (release and abandon order with a candidate); `test_checks_round` +40 (rounds silent on `land`/`landed`, never release a land's slot) |
| 6 | **M3 live smoke** | Section 21's runbook, owner-run or by an authorized agent; findings file | none | none |

Total about +1,300 source here (+110 in the shelf) and +3,000 test lines. Largest new functions: the land driver split
into reads, candidate, validation, delivery and close (each under 60); `validate`'s flow keeps `check_entry`'s split.
After the slices: `operations` ~370, `check_store` ~292, `land` ~305, `composition` ~181.

Tracker: L0 tl-8bh9.14.8.1, L1 .2, L2 .3, L3 .4, L4 .5, L5 .6, the M3 smoke .7 (children of tl-8bh9.14.8, with the
dependency edges below).

Dependencies: L0 and L1 independent; L2 after L1; L3 after L0 and L2; L4 after L3; L5 after L4; the smoke after L5. Each
slice lands green with `just check` and `just test`, independently reviewed. M3 is reached when the smoke passes.

## 20. Tests (pytest functions, fakes through ports, no process in factory tests)

- **Store** (L1): every CHECK of `land_candidate` (and valid rows), the unique delivered index, `UNIQUE(checks_attempt_id,
  number)`; `insert`'s fences one by one (a failed, unreleased or abandoned checks attempt; a later implement attempt;
  claim not kept; a delivered candidate; a pending one); validation writes off `HELD`; a candidate key's results and
  setup runs through the unions and a checks key unaffected; `LANDING` refusing both abandon paths.
- **Validation and release** (L2): `test_check_entry` passes unchanged after the extraction (mutation: drop the reconcile,
  the completed reading, the deadline from `validate`, each fails a checks test); a candidate validated with `moved` None;
  its release resets to S and parks at D; abandon mode of a pending candidate.
- **Land** (L3, L4), over a factory.db file, the Git fake (origin, `main`, `task/<id>`), the real profile reader, the
  scripted registered start and a tracker double: section 4's refusals in order with nothing written and no remote call
  before the fetch; same tree pushes S (parent O, X's tree, the message) with no slot; a moved `main` reserves a slot,
  runs the block on S, releases, pushes; a changed required set validates although the tree is the same; a failed block
  pushes nothing and leaves `Next: land`; each row of section 12 by stopping the operation at that point (a port that
  raises) and rerunning; `RefRejected` then `target_moved`; a racing second land (`landing`, then `slot_busy`); the close
  paths; `--summary` writes nothing (factory.db, slots, remote, tracker unchanged); `--no-change`; `push_barred`.
- **Real** (L3): a temporary bare origin, a checkout and one slot: the same-tree land (origin `main` at S, its parent O,
  its tree X's), a moved `main` with a passing and a failing `sh -c` check, a conflict, and a racing push.
- **Surface** (L5): show lines and JSON, `Next` rows, list, the abandon order and its rerun, rounds silent.

## 21. M3 live smoke (outline; the runbook is written in L5)

Base: the M2 runbook ([live-smoke.md](../tl-8bh9.14.6/live-smoke.md)) with a new scratch folder `$M3`: runner at the L5
commit, a scratch bare remote whose `main` is that commit, scratch tracker, factory.db new (v13), two slots.

1. Two `auto` tasks A and B through rounds to `Next: land` (both cut from the same `main`). Stop rounds.
2. `TL step land A --summary`: required names `same`, `same tree as X`, the message; nothing changed (factory.db
   `land_candidate` empty; remote `main` unchanged; `bd show`: in progress).
3. `TL step land A`: no slot used; remote `main` at S (`git log -1`: parent the old `main`, subject `<title> (A)`, tree
   X's); `bd show A`: closed with the reason; `TL step show A`: `Pushed:`, `Closed:`, `Next: landed`; the person's
   checkout and local `main` byte-for-byte unchanged (`git status`, `rev-parse main` before and after).
4. `TL step land B`: `merged onto a moved main, checks run again`; `Land check:` lines while it runs (second shell);
   pushed after `Land result: passed`; slot parked at D and clean.
5. **Interrupt and resume**: task C (cut before A landed, so its land validates); Ctrl-C during its block; rerun:
   `unavailable checks:running` while a check still runs, then the block repeats and the land finishes. Rerun `TL step
   land A` once more: `already` landed, no fetch, push or tracker write (remote `main` and `bd show A` unchanged). The
   window between push and close has no live trigger: tests cover it (section 20).
6. **Moved target during the land**: task D; while its block runs, push a commit to the scratch remote's `main` by hand:
   `target_moved`, nothing pushed; rerun makes candidate 2 and lands.
7. **Conflict**: task E editing the same line as a hand commit on `main`: `conflict` with the path, nothing recorded.
8. **Refusals**: `--abandon` after A is landed refuses `landed`; land from a shell carrying the push bar refuses
   `push_barred`; `remote_rejected` by a scratch `pre-receive` hook on the bare remote refusing `main`.
9. Record findings in `docs/design/tl-8bh9.14.8/m3-smoke-findings.md`.

## 22. Risks

- **A busy `main`** costs one block per moved land and one rerun per race (`target_moved`); with one slot and rounds
  running, a land may wait for a free slot (`no_free_slot`).
- **Foreground minutes**: a land with a validation block holds the person's shell; Ctrl-C is safe (section 12).
- **Agent cost of a conflict or `branch_moved`**: the abandon route re-runs the plan and implement agents.
- **Task code edits the shared Git config before a land's push** (section 15): accepted under D10, not mitigated.
- **Local `main` stale after a land** until the person pulls: new task branches are cut from the local `main` (.15
  section 17), so tasks admitted before the pull start behind and their lands validate on a moved `main`.
- **Branch protection** on a real forge (GitHub requiring PRs or signed commits) makes every land `remote_rejected`; PR
  mode stays held.
- **Schema discard** at v13: finish or abandon attempts first (the existing runbook).
- **A shelf dependency** (L0) on `merge-tree --write-tree` (Git 2.38 or later; this machine has 2.54).

## 23. Not verified

- `stream_proc.run_registered`'s behavior when the `tl` process receives Ctrl-C mid-check (whether its stop takes the
  tree, or the check survives in its session): the reconcile covers both; the smoke step 5 records which.
- That `commit-tree` through the `hardened` view takes the person's identity from their configuration as expected.
- `bd close` with `if_assignee` against a claim whose lease lapsed during a long block (the keep-alive renews it; a lapse
  between commands is pinned by a tracker-double test and the smoke).
- Line estimates, from the counts at 08784fe34.
