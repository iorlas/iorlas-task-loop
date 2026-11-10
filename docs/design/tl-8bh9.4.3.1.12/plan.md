# Publish the verified plan: push `task/<id>` to the remote

Task: tl-8bh9.4.3.1.12 (proposed id). Design proposal, 2026-11-10, against HEAD e9be414e5. Nothing here is built. The
commands run were source reads, the policy line counter over HEAD, and one scratch experiment with the installed
git_porcelain 0.13.0 against a local bare remote under the session scratchpad (section 12), deleted afterwards. The
shelf checkout `/home/iorlas/Workspaces/shelf` was read only; its `api.py` push signature and `real_remote.py` are
identical to the pinned 0.13.0.

Read: CLAUDE.md, glossary, [.8.7](../tl-8bh9.8.7/plan.md), [delivery/publication](../tl-8bh9.9/delivery-publication.md)
(owner-agreed 2026-11-09), [.4.3.1](../tl-8bh9.4.3.1/plan.md), slices [.2](../tl-8bh9.4.3.1.2/plan.md) to
[.11](../tl-8bh9.4.3.1.11/plan.md), the [live smoke](../tl-8bh9.4.3.1.4/live-smoke.md); source `attempt_entry, plan_ops,
plan_release, plan_schema, plan_reads, plan_store, plan_verify, plan_prepare, slot_lock, composition, cli_composition,
cli_plan, plan_launch`, `.importlinter`, `ruff.toml`, `tests/rules/test_policy.py`, `tests/plan/conftest.py`; git_porcelain
0.13.0 `api.py`, `api_results.py`, `real.py`, `real_write.py` (`push`), `real_remote.py` (`classify_push`),
`real_operations.py` (`ls_remote`), `real_env.py`, `errors.py`, `fake_flow.py` (`push`), `fake_operations.py`.

## 1. Words, and what earlier slices said

| Word | Meaning here (glossary) | Earlier slices |
|---|---|---|
| **publish** the task branch | make the configured remote's `task/<id>` contain the verified commit X, so another PC can fetch it. The fact is **published** (delivery note: "the configured remote task branch contains the intended committed checkpoint"). | .5 section 1 named it slice 3: "a non-force `Worktree.push("task/<id>", head=X)` ... observed through `Repo.ls_remote`"; .5/.7 tables say "slice 3 pushes X" / "publishes B". |
| **push** | the Git transport that does it: one non-force push of the pinned X. | .4 section 5 bars the agent's push (`push_bar`: `url.delegate-push-refused://.pushInsteadOf` in `CODEX_ACCESS`'s env); .7 says the factory's hardened `checkouts` "will serve the later publication push, so `pre-push` hooks will not run either; slice 3 must accept that or build its own repo". |
| **land** | not this slice: accepted integration into the target, confirmed task completion and any required task sync. Publishing an unfinished task branch does not land it. | delivery note; .11 section 2 ("a verified plan is not task completion (land is)"). |
| **merge**, **PR**, **release** (software), installation | out of scope (section 11). `tl plan release` keeps meaning a slot reservation release (.11). | .8.7: "attempt only: no task branch, publication or release"; .10 and .11: publication, push, fetch, merge out of scope. |

**Name collision, stated once.** `plan_execution.publication` (`complete`/`pending`/`conflict`/`fault`, "publication
complete" in the attempt row), `PlanAttempts.publish`, `PublicationResult` and the entry's `publish=` word are the
**DB acceptance of the agent's session result** (.4.3.1.1), not a Git push. This slice does not rename them (a hard cut
across plan, store, entry and tests, unrelated to pushing); it avoids every one of those identifiers. New names: the
person's verb `tl plan publish`, the next word `publish`, the table `published_branch`, the module `plan_publish.py`,
the entry word `branch=`. A rename of the session-result words (to `accepted`/`acceptance`) is proposed as its own task.

## 2. What changes

After a stored `verified` verdict (new or `reused`), the factory pushes X = `plan_attempt.plan_commit` to
`origin`'s `refs/heads/task/<id>`, never forced, as the person, from the person's checkout, and records the published
fact in factory.db. One operation, `PlanPublish.publish(key)`, with three callers: the entry (after its settled release,
outside the slot lock), `tl plan verify` (after its release) and the person's `tl plan publish` (first try or retry).
The agent still cannot push (the push bar stays). Nothing merges, opens a PR, deletes a remote ref, fetches or lands.

## 3. Preconditions, in order (all read before any network call)

1. **Attempt.** The task's current attempt (`attempt_of`, highest `seq`) exists, else `refused:absent`.
2. **Not abandoned.** A `plan_release` row with `abandoned=1` -> `refused:abandoned` (the attempt was thrown away; a
   fresh start publishes its own result).
3. **Already published.** A `published_branch` row for the key -> `AlreadyPublished`, exit 0, no Git and no network.
4. **Verified result.** A `plan_verification` row with `verdict='verified'` and `plan_commit` X set; otherwise
   `refused:not_verified` (detail: rejected with its rule, or not yet verified: `tl plan verify`). Phase, entry and
   worker are not re-checked: a stored verdict already required a captured, clean, stopped step, and X is immutable.
5. **Repository.** The slot path from the `slot` table (the adopted fact: the reservation may already be released) gives
   the repository through `plan_verify.pointer` (file reads only; a redirected pointer makes no Git call) and
   `identity()` from the pointer's root, whose key must equal `plan_attempt.repo_id` and whose common dir must equal the
   pointer's: else `refused:repository`. Every later Git call runs on `remotes(root)`, the person's checkout, never on
   the slot, which another attempt may hold by now.
6. **Remote.** `repo.remote_url("origin")` succeeds; `MissingRemote` -> `refused:no_remote`. The URL is only a presence
   check: never stored, logged or printed (it may carry userinfo). Measured: without this check a missing `origin`
   reaches the push as `Transient` ("does not appear to be a git repository"), indistinguishable from a network fault.
7. **Branch rule (local).** `refs(["refs/heads/task/"])`, exact name filtered in our code: `refs/heads/task/<id>`
   must exist and contain X (`is_ancestor(X, tip)`), else `refused:branch_moved` (the person deleted or rewrote the
   local branch after the verdict; publishing X would fork the remote from local work). A local tip that descends
   from X is accepted: X, not the tip, is pushed. The name was validated at admission (.10 rule 1); no holder check
   (a push checks nothing out).

**Not preconditions, decided.** *Slot state and lock custody:* the push reads only content-addressed objects and writes
only the remote ref and `refs/remotes/origin/task/<id>` in the shared ref store; it never touches a worktree, index or
HEAD. So it needs no reservation, no slot lock and no stop proof, and it never pins a slot during a network call (the
delivery note: "publication waits should not pin otherwise reusable capacity"). *Remote-tracking ref:* not read before
the push; the push itself is the authoritative check, and a stale or absent tracking ref proves nothing about the remote.
*Claim:* not checked or renewed (section 8).

## 4. The push and its results

```python
remotes(root).worktree(root).push(task_branch(task_id), remote="origin", head=X)   # `X:refs/heads/task/<id>`, no `+`
```

One process; the pinned full sha avoids a HEAD read and any moving HEAD. Measured on real Git (section 12): a success
also moves `refs/remotes/origin/task/<id>` to X (Git's opportunistic tracking update for a configured remote; the fake
does the same); the same push again returns `Pushed` ("up to date"); an older or diverged X and a remote holding commits
unknown here both return `RefRejected`; an unreachable host returns `Transient`.

| Library result | Then | Result word |
|---|---|---|
| `Pushed` | record `remote_head = X` | `published` |
| `RefRejected` (non-fast-forward, fetch first, stale) | one `ls_remote("origin", ["refs/heads/task/<id>"])`, exact name filtered: tip T, **for the refusal word only, never recorded** (as built, see section 17) | see next rows |
| ... T == X (another publisher won the race) or T absent (deleted meanwhile) | nothing recorded; the rerun's push is `Pushed` (up to date) and records | `unavailable:changed` |
| ... T known here and an ancestor of X (it moved during the push) | nothing recorded | `unavailable:changed` |
| ... T known here and `is_ancestor(X, T)` (someone added commits on top) | nothing recorded | `refused:remote_ahead` |
| ... T known here, neither contains the other | nothing recorded, nothing pushed again | `refused:diverged` |
| ... `is_ancestor` raises `MissingRevision`/`GitReadFailure` (T not in this repository) | nothing recorded | `refused:remote_moved` ("fetch `task/<id>` and compare; rerun") |
| ... `is_ancestor` raises another `GitUnavailable` (timeout) | nothing recorded | `unavailable:git` |
| ... `ls_remote` raises | nothing recorded | `unavailable:remote` (rerun) |
| `RemoteRejected` (server policy: protected branch, hook) | nothing recorded | `refused:remote_rejected` |
| `Transient` | nothing recorded | `unavailable:remote` (exit 3) |
| `HookRejected` (cannot occur: hooks are off, section 7) or `GitUnavailable`/`GitTimeout` | nothing recorded | `unavailable:git` (exit 3) |

**Only `Pushed` records (review, 2026-11-10).** `ls_remote` reads the *fetch* URL; a `pushurl` or `pushInsteadOf` may
send the push to another repository, so a tip read from the fetch side never proves the push target holds X. The
"contained counts as published" rule below is therefore not built: a remote that already holds X plus later commits is
`refused:remote_ahead` and stays unrecorded (the delivery note's "contains" fact is left to the next mutating step).

**Never force, never fetch.** Divergence preserves both histories: the factory neither pushes `+X` nor rewrites the
local branch nor fetches the remote tip (no hidden write to the tracking ref .10's rule reads). Contained counts as
published because the delivery note defines the fact as "contains"; reconciling the newer remote commits is the next
mutating step's concern, and `tl plan show` names T. **No output is printed or stored**: git output may name hosts or
paths, and `detail` is fixed text plus shas. A person who needs Git's message runs the same push by hand (the guide gives
`git push origin <X>:refs/heads/task/<id>`, no `--force`). **Auth versus network:** the library classifies an SSH
`Permission denied` as `Transient` (its regex matches "Could not read from remote repository") and an HTTPS auth
failure as `GitUnavailable`; the factory does not re-parse output (no regex over display text), so both are rerun-able
`unavailable:*` words and the guide names credentials first. Recorded as a shelf observation, not fixed here.

**Timeout.** `remotes(path)` is `checkouts(path)` with `remote_timeout=PUSH_TIMEOUT = 120` s (the library default is
600 s), so a hung transport ends as `GitTimeout` -> `unavailable:git` within two minutes.

## 5. factory.db schema v8 (direct; v7 refused `schema`, discarded, no migration)

```sql
CREATE TABLE published_branch (
 attempt_id TEXT PRIMARY KEY REFERENCES plan_verification(attempt_id), dispatch_token TEXT NOT NULL, generation INTEGER NOT NULL,
 commit_sha TEXT NOT NULL CHECK(length(commit_sha) IN (40,64)),     -- X, the verified commit pushed
 remote_head TEXT NOT NULL CHECK(length(remote_head) IN (40,64)),   -- the remote tip confirmed: X, or T that contains X
 published_at REAL NOT NULL
);
```

`PUBLISHED = "attempt_id,dispatch_token,generation,commit_sha,remote_head,published_at"` in `plan_schema.py`. The remote
name and branch are derived (`origin`, `task_branch(id)`), never stored. **Only success is recorded.** "Pending" is
derived, not stored: a verified, unabandoned current attempt with no row. No failure row, retry counter or outbox: a
rerun recomputes everything from Git, and the last failure's word is display-only (the entry log's `branch=`, never a
control input).

**The write.** One `begin_immediate` transaction in `plan_publish.py`: an existing row for the key with the same
`commit_sha` -> `AlreadyPublished`; otherwise the fence
`plan_verification.verdict='verified' AND plan_attempt.plan_commit=X AND` no abandoned `plan_release` row `AND` no
successor attempt, then `INSERT`. Fence lost -> `refused:abandoned` (an abandon committed during the push: the remote
keeps X; nothing else is undone) or `unavailable:changed`.

**Crash points (no atomicity between Git and the DB is claimed).**

| Dies or fails | State | Rerun |
|---|---|---|
| before the push | nothing | pushes |
| push sent, reply lost (`Transient`, timeout, kill) | remote may hold X; no row | push again: `Pushed` (up to date) or the rejected path -> recorded |
| after `Pushed`, before the row | remote and tracking ref at X; no row | `Pushed` (up to date) -> recorded |
| row write fails | same | `unavailable:store`; rerun records |
| two publishers at once (entry and `tl plan publish`) | both push X (idempotent) | the second transaction sees the row: `AlreadyPublished` |

Writers (`tests/rules/test_policy.WRITERS` gains): `("CREATE TABLE", "published_branch")`: plan_schema.py;
`("INSERT", "published_branch")`: plan_publish.py. `GIT_WRITES` gains `push`; expected gains `("push", "plan_publish.py")`.

## 6. The operation and its surfaces

`src/taskloop/plan_publish.py`: `PlanPublish(store: PlanStore, remotes: Checkouts, slot_files: SlotFiles, clock)`,

```python
def publish(self, key: AttemptKey) -> BranchPublished | AlreadyPublished | NotPublished
@dataclass(frozen=True) class BranchPublished:  commit: str; remote_head: str      # contained when remote_head != commit
@dataclass(frozen=True) class AlreadyPublished: commit: str; remote_head: str; published_at: float
@dataclass(frozen=True) class NotPublished:     kind: Literal["refused", "unavailable"]; reason: str; detail: str
def word(result) -> str   # published | refused:<r> | unavailable:<r>
```

Its own fenced read (one `SELECT` joining `plan_attempt`, `plan_verification`, `plan_release`, `published_branch` and
`slot`), like `plan_release`'s; it imports neither `plan_ops` nor `plan_repeat` (the entry's import closure).
`plan_verify` gains `repository(checkouts, files, cwd, repo_id) -> Path | Literal["repo", "redirected"]`, the first half
of `observe_slot`, which `observe_slot` then calls (one owner of the rule).

**Consumers, one operation:**

- **Entry** (`attempt_entry.enter`): `_claimed` returns its line and exit code instead of logging; after the lock's
  `finally` (the slot is released or held, the keep-alive stopped), when the step succeeded (`succeeded(latest)`),
  `PlanPublish(..., remotes, ...).publish(key)` once, no retry, no wait; the line gains `branch=<word>` last and is then
  logged. `plan_ops.ENTRY_WORDS` becomes 8 (`WORD` already matches `branch=unavailable:remote`). A failed step logs no
  `branch=`. The entry dies during the push: no line, no row; `tl plan show` says `Next: publish`.
- **`tl plan verify`** (`plan_ops.verify_task(reader, verifier, releaser, publisher, ...)`): after `Verified` and the
  release, one publish; `Checked` gains `published` (the word). A failed publish does not change verify's exit code
  (as a held release does not); the word and `Next: publish` tell the person.
- **`tl plan publish TASK --backlog B [--db] [--json]`** (`plan_ops.publish_task(reader, publisher, backlog, task_id)
  -> PublishedTask | Failed`): the person's verb and the one a dashboard calls and renders through `as_data`.
  `PublishedTask(backlog, task_id, attempt_id, outcome)`. Exit 0 published or already; 1 refused; 3 unavailable.
- **`tl plan start`**: unchanged (`already_dispatched` for a settled release); it never publishes.

**Status, next and display** (`AttemptRow` gains `published: PublishedRow | None` through one more `LEFT JOIN` in
`attempts()`; `plan_reads.published_of(key)`):

| State | `next` | GUIDE |
|---|---|---|
| collected `verified`/`reused`, reservation held | `release` (unchanged: freeing the slot comes first) | unchanged |
| collected `verified`/`reused`, released (settled), no `published_branch` row | `publish` (new) | "The plan is verified but not on `origin` yet: `tl plan publish`. A `refused` word names what to fix; `unavailable:remote` is often credentials: check that `git push` works from this shell." |
| published | `done` | unchanged |
| rejected or failed result | `done` | unchanged (nothing to publish) |

`tl plan show` adds `Published: task/<id> at <X> on origin, <UTC time>` and, when contained, `; the remote is ahead at
<T>`. JSON: status gains `published` (`{"commit", "remote_head", "published_at"}` or null); `Checked` gains `published`;
`tl plan publish --json` is `{"status": "published"|"already_published", "backlog", "task", "attempt_id", "commit",
"remote_head", "contained"}`. Help: `ATTEMPT_ONLY` becomes `PLAN_ONLY = "plan step only: publishes task/<id>; no merge
or land"` (root help, `tl plan -h`, `start`, `show`, `list`, `verify`, `release`), and `tl plan publish -h` says "Push the
verified plan commit to origin's task/<id> as you, never forced; nothing merges or lands".

**Cap relief.** `plan_ops.py` is 373 SLOC (cap 400). `as_data` and its five helpers (about 60 lines) move unchanged to a
new `plan_data.py` ("the one JSON shape of every result"), imported by `cli_plan`; `plan_ops` then has room for
`publish_task` and the `next` row.

## 7. Credentials and environment

- **Who supplies them:** the person, through their own Git setup (ssh-agent, a credential helper, a keychain, `insteadOf`
  or `pushurl` in their Git config). The factory reads, stores, prints and passes no credential, token or environment
  value; there is no new config key. The push runs as the person: their config, their keys.
- **Which environment:** `tl plan publish` and `tl plan verify` inherit the person's shell. The entry inherits the
  environment of the `tl plan start` that launched it (`plan_launch` passes `env=None`), so an `SSH_AUTH_SOCK` there
  reaches the entry's push. The agent's environment is unchanged: scrubbed of `SSH_AUTH_SOCK`, `GH_*`, `GITHUB_*`,
  `*TOKEN*` and the rest, and push-barred; `remotes` never adds the push bar (it is only in `CODEX_ACCESS`'s env).
- **No prompt:** git_porcelain's base env sets `GIT_TERMINAL_PROMPT=0` and `GIT_SSH_COMMAND=ssh -o BatchMode=yes`; a
  locked key or missing login fails (`unavailable:*`) instead of hanging the detached entry.
- **Hardened view:** `remotes` is `checkouts` (hooks off, no fsmonitor, no signing, no auto-maintenance) plus the
  timeout, so **no `pre-push` hook runs** (owner question 2). Signed-commit repositories stay unsupported (.7): X is
  pushed as committed.
- **Output:** the library redacts URL userinfo in its own diagnostics; the factory prints none anyway (section 4).
- **What the push uploads (review finding 2).** Pushing X sends every ancestor of X that `origin` lacks. If the slot's
  admission base D (the person's local `main`, say) holds commits never pushed, they reach `origin` under `task/<id>`
  with the plan. No refusal is added; the person keeps unpublished work off the base they start tasks from.
- **SSH command (review finding 3).** git_porcelain's base environment sets `GIT_SSH_COMMAND=ssh -o BatchMode=yes`,
  which overrides a `core.sshCommand` in the person's Git config (a per-repo key selected that way is not used). Keys
  work through ssh-agent or `~/.ssh/config`; the `remote` guide says so. Shelf follow-up: honour `core.sshCommand`
  (append `-o BatchMode=yes` to it instead of replacing it).
- **Transport config is not hardened (review finding 12).** `remotes` hardens hooks, fsmonitor, signing and
  maintenance only; `url.*.insteadOf`/`pushInsteadOf`, `remote.origin.pushurl`, `core.sshCommand` and credential
  helpers come from the common `.git/config` and are honoured as the person's. What protects the push is that the agent
  cannot write that file: its sandbox's writable root is the slot, and a linked worktree's config lives in the common
  `.git` outside it (`.4.3.1.7`, Run C).

## 8. Interactions

- **Release (.11).** Independent. The entry releases first (inside the lock), then publishes (outside it). A held
  release (`slot_dirty`, `slot_busy`) does not stop publication: X is committed in shared Git. `tl plan release` never
  publishes; publication never parks. Release leaves `task/<id>` at X, so precondition 7 holds after a park.
- **Abandon.** Publishing an abandoned attempt is refused. Abandoning a published attempt is allowed and touches nothing
  remote: the remote `task/<id>` keeps X (no remote deletion: never automatic, and `delete_remote_at` is not used). The
  fresh attempt resumes the branch through .10's rule (the local and tracking tips both contain D), and its own
  verified result publishes by fast-forward, or as "up to date" when it answers `unchanged` at X.
- **Repeat (.8).** Repeats happen only before a verdict, so only a chain's verified end is ever published, under its
  own key. A repeat never sees a `published_branch` row.
- **`branch_diverged` and the tracking ref (.10).** A successful push moves `refs/remotes/origin/task/<id>` to X, which
  contains every D the task's slots started from, so the admission rule keeps passing. A rejected push changes no ref.
  A person who later fetches a diverged remote tip makes the rule refuse `branch_diverged` for a fresh start, and
  `tl plan publish` refuse `diverged`; both details already say how to move the ref aside. Publication adds no fetch.
- **Heartbeat and claim (.9).** The keep-alive covers only the step (agent, session-result retries, verify); the push
  runs after it stops and neither checks nor renews the claim. Reason: the claim is the tracker's assignment, the push
  is a non-force transport of the factory's own verified commit, which cannot overwrite another actor's work; a lost
  claim is already reported by `claim=`. No tracker read or write is added.

## 9. Failure and refusal words

Nothing changes on a refusal or unknown; the remote changes only on `published`. Exit: published/already 0, refused 1,
unavailable 3.

| When | Result | Next |
|---|---|---|
| no attempt / abandoned / not verified | `refused:absent` / `abandoned` / `not_verified` | start, or verify |
| slot pointer or repository not the attempt's | `refused:repository` | inspect the slot |
| no `origin` | `refused:no_remote` | `git remote add origin ...`, rerun |
| local `task/<id>` missing or not containing X | `refused:branch_moved` | restore the branch, rerun (or abandon) |
| remote tip known and containing X plus more (as built) | `refused:remote_ahead` (T in detail), never recorded | compare; the next mutating step reconciles |
| remote tip known and not containing X | `refused:diverged` (T in detail) | compare `X..T`; the person merges or moves the remote aside; never forced |
| remote tip not in this repository | `refused:remote_moved` | `git fetch origin task/<id>`, rerun (then `published` contained, or `diverged`) |
| server policy refused | `refused:remote_rejected` | the push by hand shows why |
| network, auth over SSH | `unavailable:remote` | check credentials in this shell, rerun |
| Git failure, timeout, auth over HTTPS | `unavailable:git` | same |
| record failed / fence lost | `unavailable:store` / `unavailable:changed` | rerun |

## 10. Tests

Factory tests consume `FakeRepo`/`FakeRemote` (`push`, `ls_remote`, `remote_url`, `refs`, `is_ancestor`; the fake
updates the tracking ref like Git), the `factory` fixture, `FakeSlotFiles` and a fake clock. Two results the fake's
`push` cannot produce (`RemoteRejected`, a raised `GitUnavailable`) come from a test-local `FakeWorktree` subclass that
overrides `push` only. The push contract itself is git_porcelain's suite. Pytest functions, parametrized tables.

- **`tests/plan/test_publish.py`** (new, about 300 lines): a verified attempt (seeded through `execute` and `verify` as
  `test_release.py` does) publishes: remote `task/tl-1` == X, tracking ref == X, row (`remote_head` X); a second call
  `AlreadyPublished` with zero Git calls (an observer `Repo` counting calls); `reused` publishes B; each precondition
  refuses with zero push (absent, abandoned, not verified, rejected, redirected pointer with zero Git calls, other
  repository, no `origin`, branch missing, branch rewritten); remote ahead and containing X -> recorded with T; remote
  diverged with T known -> `diverged`, remote unchanged; T unknown -> `remote_moved`; offline remote -> `unavailable:remote`;
  `RemoteRejected` and `GitUnavailable` rows; an abandon committed during the push (the hook of the subclass) ->
  `refused:abandoned`, no row; a store that fails the insert -> `unavailable:store`, then a rerun records; two publishers
  -> one row; the published slot already released (no reservation) still publishes; the slot reserved by another attempt
  is never read (Git observer: no call on the slot path).
- **`test_entry.py`**: a verified step ends `... release=released branch=published` after the lock is released (the
  `occupy` fixture can take the lock while the push runs); offline -> `branch=unavailable:remote`, exit 0 kept for a
  verified plan; a failed step has no `branch=`; `last_entry` accepts eight words.
- **`test_ops.py`**: `next` rows (`publish` after a settled release, `done` after the row, `release` still first);
  `verify_task` publishes after a verified release and reports a failed publish without changing its kind;
  `publish_task` result mapping and exit codes; `as_data` keys (now from `plan_data`).
- **`tests/cli/test_plan_cli.py`**: `plan publish` human lines and exact JSON keys; help text `PLAN_ONLY`;
  `tests/cli/test_cli.py`: the root help wording.
- **Real layer, `tests/plan/real/test_publish_real.py`** (new, about 150 lines): set-up through
  `git_porcelain.testing.git` under `tmp_path` with `apply_hermetic_env`; a bare `remote.git`, a clone with `origin` as
  `file://`, a `--detach` slot, adopt, admit, `execute` with a `FakeRun` agent, verify, release, publish. Rows: published
  (`ls-remote` and `refs/remotes/origin/task/tl-1` both X; the slot detached at D untouched); the second call makes no
  Git process (observer); a second clone pushes a commit on top -> recorded as contained; a second clone pushes an
  unrelated commit -> `remote_moved`, then after a fetch `diverged`, the remote ref unchanged; origin removed ->
  `no_remote`; origin URL at a missing path -> `unavailable:remote`; a `pre-push` hook in the repository's own
  `.git/hooks` that writes a marker -> no marker (hooks off).
- **Rules**: the `WRITERS` and `GIT_WRITES` rows (section 5); `.importlinter`'s entry contract already forbids
  `plan_publish` from reaching `plan_ops`; `plan_data` joins the `cli-never-imports-the-attempt-entry` sources.
- **Churn**: `test_ops.py`, `test_plan_cli.py` and `test_admit.py` seeds unaffected by the new table; every
  `verify_task(` site gains a publisher; the `as_data` import moves.

Budgets (total lines today): `test_ops.py` 576, `test_entry.py` 377, `test_plan_cli.py` 351: each stays under 800.

## 11. Out of scope

Merge into `main` or any target, PR creation or update, land, task completion or closure, task sync (`bd dolt push`),
software release or installation, deleting or moving a remote ref, fetch, force or lease pushes, publishing after other
steps (implement/repair), a retry scheduler or backoff, remote names other than `origin`, a dashboard page (its data is
`as_data`), renaming the session-result `publication` words (section 1), a GitHub/forge API.

## 12. Measured (scratch, 2026-11-10)

Installed git_porcelain 0.13.0 on Linux, a bare `file://` remote, `core.hooksPath=/dev/null` in `GIT_CONFIG_*`:
`Worktree.push("task/t1", head=X)` -> `Pushed`, and `refs/remotes/origin/task/t1` == X; the same push -> `Pushed`
("[up to date]"); an older commit -> `RefRejected`; after another clone pushed on top -> `RefRejected` and the tracking
ref unchanged; `ls_remote("origin", ["refs/heads/task/t1"])` -> the one row; an SSH URL to a closed port -> `Transient`;
`origin` removed -> the push is `Transient`, `remote_url` raises `MissingRemote`; `is_ancestor` with an object not in
the repository raises `GitReadFailure` (not `MissingRevision`). Not measured: real SSH/HTTPS authentication failures
(the `Transient`/`GitUnavailable` split above is read from `classify_push` and `TRANSIENT`), macOS keychain prompts
under `BatchMode`, a real hosted remote's protected-branch refusal.

## 13. Smoke runbook additions (owner-run; scratch `remote.git` only)

In [live-smoke.md](../tl-8bh9.4.3.1.4/live-smoke.md):

- Section 2: the first bead's acceptance becomes "The factory commits docs/design/$TASK/plan.md on task/$TASK and
  publishes task/$TASK to origin (the scratch remote.git)." Section 6's "Push refused" row stays for the agent's push
  (`smoke`/`probe` refs must not exist); `refs/heads/task/*` in `remote.git` are now the factory's. The entry.log row
  gains `[ branch=<w>]` last.
- New **Run F (section 6e)**, after moving the previous run aside (a v7 factory.db is refused `schema`):

```bash
mkdir "$SMOKE/runE" && for f in "$DB" "$DB-wal" "$DB-shm" "$ART"; do [ -e "$f" ] && mv "$f" "$SMOKE/runE/"; done
cd "$TRACKER" && TASK5=$(bd create "Smoke publish" --silent) && TASK6=$(bd create "Smoke diverged" --silent) \
  && printf 'TASK5=%s\nTASK6=%s\n' "$TASK5" "$TASK6" >> "$SMOKE/env.sh"
for t in "$TASK5" "$TASK6"; do bd update "$t" -d "Write docs/design/$t/plan.md with one short paragraph. Answer planned and \
list the plan in paths." --acceptance "The plan is committed on task/$t and published to origin."; done
T slot adopt "$REPO"
# F1, a publish that fails, then the retry: origin pointed at a missing path for the run
G -C "$REPO" remote set-url origin "file://$SMOKE/missing.git"
S5=(plan start "$TASK5" --backlog "$BACKLOG" --tracker-root "$TRACKER" --checkout "$REPO" --model "$MODEL" --effort "$EFFORT" --minutes 30)
T "${S5[@]}"; T plan show "$TASK5" --backlog "$BACKLOG"   # repeat until the entry ends: ... release=released branch=unavailable:remote; Next: publish
G -C "$REPO" remote set-url origin "file://$SMOKE/remote.git"
T plan publish "$TASK5" --backlog "$BACKLOG" --json      # published; commit == remote_head
G -C "$SMOKE/remote.git" show-ref; G -C "$REPO" rev-parse "task/$TASK5" "refs/remotes/origin/task/$TASK5"   # all X
G -C "$REPO" remote set-url origin "file://$SMOKE/missing.git"
T plan publish "$TASK5" --backlog "$BACKLOG" --json      # already_published, exit 0: no network was needed
G -C "$REPO" remote set-url origin "file://$SMOKE/remote.git"
# F2, a remote branch someone else made: a scratch clone pushes an unrelated task/$TASK6 first
git clone -q "$SMOKE/remote.git" "$SMOKE/other" && cd "$SMOKE/other" && git switch -q --orphan "task/$TASK6" \
  && git -c user.name=o -c user.email=o@example.invalid commit -q --allow-empty -m other && git push -q origin "task/$TASK6" && cd "$SMOKE"
S6=(plan start "$TASK6" --backlog "$BACKLOG" --tracker-root "$TRACKER" --checkout "$REPO" --model "$MODEL" --effort "$EFFORT" --minutes 30)
T "${S6[@]}"; T plan show "$TASK6" --backlog "$BACKLOG"   # until: ... branch=refused:remote_moved; Next: publish
G -C "$SMOKE/remote.git" rev-parse "task/$TASK6"           # still the other clone's commit: nothing forced
G -C "$REPO" fetch -q origin "task/$TASK6"; T plan publish "$TASK6" --backlog "$BACKLOG"   # refused diverged, exit 1
ls "$SMOKE/markers"   # empty: no hook ran
```

| Check | Pass | Fail means |
|---|---|---|
| F1 failure | `branch=unavailable:remote`, `Next: publish`, the slot released, no `task/$TASK5` in `remote.git` | `branch=published` against a missing path; the release waited on the push |
| F1 retry | `published`; `remote.git`, local branch and tracking ref all at X | a different sha anywhere; a `+` (forced) update |
| already published | `already_published` with origin unreachable | any Git error (it touched the network) |
| F2 | `remote_moved`, then `diverged` after the fetch; `remote.git` keeps the other commit | the remote ref changed |
| agent push | still no `smoke`/`probe` ref | the push bar does not hold |

Cleanup: `rm -rf "$SMOKE/other"` with the rest of `~/tl-smoke`. Section 9 is unchanged: push nowhere but `remote.git`.

## 14. Modules and caps

SLOC by the policy counter today -> estimate; caps 400 file, 80 function, 800 test file.

| Module | Change | SLOC |
|---|---|---|
| `plan_publish.py` (new) | `PlanPublish`, results, `word`, its read, push mapping, rejected-path classification, the fenced insert | ~200 |
| `plan_data.py` (new) | `as_data` and helpers moved from `plan_ops`, plus the publish and `published` shapes | ~75 |
| `plan_ops.py` | `publish_task`, `PublishedTask`, `next` word `publish`, verify publishes, `ENTRY_WORDS = 8`; `as_data` out | 373 -> ~335 |
| `plan_schema.py` | v8, `published_branch`, `PUBLISHED` | ~+10 |
| `plan_reads.py` | `PublishedRow`, `published_of`, the `attempts()` join | 153 -> ~170 |
| `plan_verify.py` | `repository()` split out of `observe_slot` | 181 -> ~185 |
| `attempt_entry.py` | publish after the lock, `branch=` word, `remotes` port | 202 -> ~220 |
| `composition.py` | `remotes` (`PUSH_TIMEOUT`), `open_publisher` | 240 -> ~255 |
| `cli_composition.py` | `open_plan_publish`; verify gains the publisher | ~+12 |
| `cli_plan.py` | `plan publish` verb and rendering, `Published:` line, `PLAN_ONLY`, GUIDE rows | 239 -> ~265 |

`PlanPublish.publish` stays under 80 lines by splitting into `_read`, `_refusal`, `_repository`, `_pushed`, `_rejected`,
`_record` (each at most four returns: `PLR0911`, C90 12). No subprocess, signal, `Any`, `cast` or ignore; the only new Git
write is `push`, in `plan_publish.py`; no new dependency (git-porcelain 0.13.0 already pinned).

## 15. Docs to update with the code

- [.4.3.1.5](../tl-8bh9.4.3.1.5/plan.md) section 1 item 3 and [.4.3.1.7](../tl-8bh9.4.3.1.7/plan.md) section 5 ("slice 3
  must accept that"): a note pointing here (hooks off accepted or not, per question 2).
- [.4.3.1.10](../tl-8bh9.4.3.1.10/plan.md) section 7 and [.4.3.1.11](../tl-8bh9.4.3.1.11/plan.md) section 10: "publication
  delivered by .12" notes; [.4.3.1.6](../tl-8bh9.4.3.1.6/plan.md) section 1's "Next" list.
- [.8.7](../tl-8bh9.8.7/plan.md) line 48 and [tl-8bh9.3.2.1](../tl-8bh9.3.2.1/plan.md) line 8: the help wording.
- [delivery/publication](../tl-8bh9.9/delivery-publication.md): one line under "Proposed publication boundaries" item 1,
  "built for the plan step in .4.3.1.12 (push only; land not built)".
- The live smoke (section 13). The glossary needs no change (push/publish/land already match).

## 16. Owner questions

1. **Does the factory push without asking?** Today nothing leaves your machine. With this slice, every verified plan is
   pushed to `origin` by the entry (and by `tl plan verify`) right after the verdict, using whatever Git credentials the
   shell that ran `tl plan start` has (your ssh-agent or credential helper). The alternative is to push only when you
   run `tl plan publish`. **Recommendation: push automatically.** You agreed in the delivery note that a completed plan
   is published before the next step, and a manual verb would leave every plan unpublished by default. The push is
   never forced, so it cannot overwrite anything on the remote. It does upload every commit under X that `origin` lacks:
   local commits on the base you started the task from that you never pushed go to `origin` under `task/<id>` (section 7).
   *Decided (owner, 2026-11-10): push automatically.*
2. **May the factory's pushes skip `pre-push` hooks?** All factory Git calls run with hooks off, because a hook path can
   point into files the agent wrote, and a hook runs programs with your credentials. So a repository that relies on a
   `pre-push` hook (a secret scanner, a test run) will not get it for `task/*` pushes. That includes git-lfs's own
   `pre-push` hook: LFS objects are not uploaded by the factory's push, so a plan commit that adds LFS pointers would
   reach `origin` without their content (plans are plain markdown, so the plan step does not do this). **Recommendation:
   keep hooks off.** Checks belong to the checks step; server-side rules still apply (they show as `remote_rejected`).
   *Decided (owner, 2026-11-10): hooks off.*
3. **Is the remote always `origin`?** The branch rule from .10 already reads `refs/remotes/origin/task/*`, and Git still
   honours your `pushurl`/`pushInsteadOf` for `origin`. A repository without `origin` is refused `no_remote`.
   **Recommendation: `origin` only in v1**; a profile key comes when a real repository needs another name.
   *Decided (owner, 2026-11-10): `origin` only.*

Decided here, open to veto: push after the release and outside the slot lock; no fetch, never force, no remote deletion
(abandon included); a remote that contains X counts as published (the delivery note's definition), T shown; only success
is stored, pending is derived; one try in the entry, retry is the person's `tl plan publish`; no claim check; 120 s push
timeout; no git output printed; the names in section 1 and the `plan_data.py` split.

## 17. As built (2026-11-10, on e9be414e5, uncommitted)

Built as designed: schema v8 with `published_branch` (v7 refused `schema`, no migration), `plan_publish.py`
(`PlanPublish.publish`, `BranchPublished`/`AlreadyPublished`/`NotPublished`, `word`), `plan_data.py` (`as_data` moved
unchanged, plus the publish and `published` shapes), `composition.remotes` (`checkouts` plus `PUSH_TIMEOUT = 120.0`) and
`open_publisher`, `cli_composition.open_plan_publish`, the entry's `branch=` word after the lock, `tl plan verify`
publishing after its release (`Checked.published`), `tl plan publish`, `Next: publish`, the `Published:` line, `PLAN_ONLY`
help, `ENTRY_WORDS = 8`, the `WRITERS` and `GIT_WRITES` rows, `plan_data` in both entry/CLI import contracts, Run F
(section 6e of the live smoke) and the doc notes of section 15. SLOC by the policy counter: `plan_publish` 179,
`plan_data` 79, `plan_ops` 338, `plan_reads` 171, `plan_verify` 188, `attempt_entry` 208, `composition` 246,
`cli_composition` 122, `cli_plan` 285; tests `test_publish` 237, `real/test_publish_real` 145, `test_ops` 521,
`test_entry` 324, `test_plan_cli` 345 (before the review repair). Gates after the review repair and the smoke 6
fixes: `just check` clean (ruff, pyrefly 0 errors, import-linter 5 kept); `just test` 1029 passed.

Decided while building (open to veto):

- **Fixtures adopt the slot.** `tests/plan/conftest.py`'s `admitted` and `registered` now insert the `slot` row an
  adoption makes (production admission already requires it); publication reads the slot path only from `slot`, so
  without it every fake publish refused `repository`.
- **One owner of the repository rule.** `plan_verify._repository` returns the view and the root; `repository()` (the
  root) and `observe_slot` both call it, so `observe_slot` opens no extra view. Publication opens `remotes(root)` twice
  (the identity check, then the push view); never the slot.
- **Entry port.** `attempt_entry.enter` gains `publishing: Checkouts` (`composition.remotes` in `main`); `_claimed`
  returns its line and whether the plan was verified; the line is logged once, after the publish.
- **Only `Pushed` records (review repair).** A rejected push's `ls_remote` reads the fetch side, so it only picks the
  word (section 4's table): T == X or absent, or T behind X, is `unavailable:changed` (the rerun's push is `Pushed`, up to
  date, and records); T containing X is `refused:remote_ahead`; neither is `diverged`. `remote_head` is therefore always
  X, and the `contained` property, its JSON key and the "remote is ahead" text are gone.
- **Exception mapping.** A `GitUnavailable` before the push (identity, `remote_url` other than `MissingRemote`, `refs`,
  the local `is_ancestor`) is `unavailable:git`; `ls_remote` raising after a rejected push is `unavailable:remote`; the
  remote-tip ancestry raising `MissingRevision`/`GitReadFailure` (T not here) is `refused:remote_moved`, any other
  `GitUnavailable` (a timeout) `unavailable:git`. A plain `Rejected` push result is `refused:remote_rejected`, like
  `RemoteRejected`; `HookRejected` is `unavailable:git`.
- **Entry never loses its line.** `attempt_entry._branch` maps a publication that raises outside `publish`'s own mapping
  (`GitUnavailable`, `ValueError`, `OSError`: `unavailable:git`; `sqlite3.Error`, `StoreUnavailable`:
  `unavailable:store`), so the line is logged and a verified plan exits 0. Residual: any other exception type (a bug)
  still reaches `main`'s `failed <Type>` line and exit 1.
- **Lost fence.** `refused:abandoned` when an abandoned release row exists, else `unavailable:changed`; a row already
  there is `AlreadyPublished` (the second of two publishers).
- **Surface.** `tl plan verify` prints `Publish: <word>` and the publish guide unless `published`; GUIDE gained `remote`
  (naming the `GIT_SSH_COMMAND` override of `core.sshCommand`), `git`, `repository`, `not_verified`, `no_remote`,
  `branch_moved`, `remote_moved`, `remote_ahead`, `diverged`, `remote_rejected`; `Started` text says "This runs the plan
  step only: ...". `PlanReads.published_of` was not kept (unused: `attempts()` joins the row).
- **Rules.** `GIT_WRITES` also lists `fetch`, `sync`, `delete_remote_at`, `push_refspecs`, `push_request`,
  `push_lease` and `delete_branch` with no expected owner, so any use in factory source fails the policy test.
- **Runbook.** Run F also moves `$SMOKE/markers` aside and recreates it, as Runs B-E do, so its final `ls` is meaningful.
  The .4.3.1.6 note sits after its section 0 roadmap table, where the "Next" list is.

After smoke 6 (Run F passed on real Codex):

- **JSON refusals.** `as_data(result, admission=...)`: a refusal or unknown is `{"error": {kind, reason, message}}`;
  only `tl plan start` (admission) adds `claim_leaked`, `admitted` and `slots`. `cli_plan` passes `admission` for
  `plan start` only.
- **`Next: publish` after a refusal.** The last publish word is not stored (only success is; the entry log's `branch=`
  is display, never a control input), so `Next` stays `publish`. The publish guide now says that after
  `refused:diverged`, `remote_moved` or `remote_ahead` rerunning does not help: fetch, compare, then merge or move one
  branch aside by hand. Runbook 6e says the same.
- **Runbook 6e.** Moves the previous run into a new timestamped directory, uses new variable names (`PUB_BASE`,
  `PUB_RETRY`, `PUB_DIVERGED`), adds the F0 baseline row (`branch=published`, the `Published:` line, the remote ref ==
  `plan_commit`), and records what smoke 6 observed and what is still unobserved.

Documented after review (no code): the push uploads every unpushed ancestor of X (section 7, Q1); hooks off also
skips git-lfs's `pre-push` (Q2); `GIT_SSH_COMMAND` overrides `core.sshCommand` (section 7, shelf follow-up); transport
config in the common `.git/config` is not hardened and is protected by the agent sandbox not writing it (section 7).

Not verified: the live smoke Run F (owner-run), real SSH/HTTPS authentication failures, macOS keychain prompts under
`BatchMode`, a hosted remote's protected-branch refusal (section 12's list stands).
