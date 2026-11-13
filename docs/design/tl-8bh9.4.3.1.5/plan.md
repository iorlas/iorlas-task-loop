# Plan verification: Git evidence for a returned plan answer

Status: **built** for this bounded successor slice. The dated proposal and preparation statements below
are historical; they do not describe current availability. Historical `tl plan` commands were superseded by
`tl step`; use the current [README](../../../README.md) and CLI help for command syntax.

Task: tl-8bh9.4.3.1.5 (proposed id; after [.4.3.1.4](../tl-8bh9.4.3.1.4/plan.md)). Design proposal, 2026-11-10, revised after
an independent review and the owner's decisions. Nothing has been run or delivered. **The design is frozen until the live
smoke has run:** Denis runs the [smoke](../tl-8bh9.4.3.1.4/live-smoke.md) before any implementation, and section 9 says
which results would reopen this document. It follows the parent [lifecycle](../tl-8bh9.4.3.1/plan.md), the
[one-shot plan](../tl-8bh9.3.2.1/plan.md) (section 6 and "Completion evidence") and
[delivery/publication](../tl-8bh9.9/delivery-publication.md).

Read: CLAUDE.md, AGENTS.md, glossary, those plans, `src/taskloop/plan*.py`, `slots.py`, `composition.py`, `attempt_entry.py`;
installed git_porcelain 0.13.0 (`api.py`, `real.py`, `real_read.py`, `real_observe.py`, `real_write.py`, `fake_read.py`,
`fake_store.py`, `errors.py`); shelf `process-lock-v0.2.1` (read-only `git show`); `bd show tl-8bh9.4.5`.

## 1. The cut and the order (decided: Q8)

Today `execute` returns a validated `PlanAnswer`. That is a well-formed claim, not Git evidence. Four pieces are missing:

1. **Verification (this slice).** Read-only Git over facts that cannot change: the stage's commit X (since [.4.3.1.7](../tl-8bh9.4.3.1.7/plan.md)
   the factory's own commit of the paths the agent listed, recorded as `plan_attempt.plan_commit`), its one step from
   the recorded base B, and the plan blob. It stores one verdict; the only Git write is [.4.3.1.7](../tl-8bh9.4.3.1.7/plan.md)`'s factory commit.
2. **Preparation and lock.** The entry takes `ProcessLock(reentrant=False)` before any worktree mutation, then moves the
   slot onto `task/<task-id>` with `Worktree.take_branch(..., mode="resume")`. The same handle spans the Supervisor and
   cleanup, and the lock check joins the slot `free` rule (O4 of .4.3.1.4).
3. **Publication.** A non-force `Worktree.push("task/<id>", head=X)` (the refspec has no `+`; `real_write.py:403-430`),
   observed through `Repo.ls_remote`. It needs the configured remote and owner push authority.
   *Built by [.4.3.1.12](../tl-8bh9.4.3.1.12/plan.md) (2026-11-10): the pinned X (B for `reused`) pushed to `origin` only, never forced,
   automatically after a verified plan and by `tl plan publish`; a rejected push is classified with one `ls_remote`;
   hooks off (no `pre-push`); recorded in `published_branch`.*
4. **Cleanup and release.** These need whole-workload stop proof (.4.4). The final "slot is at X and clean" checks are
   made here and in publication, under the lock.

**Why verification first.** It needs no process, push or new dependency. Publication then pushes the verified X, never a
moving HEAD. And it stays valid after preparation, because B is defined as **the slot HEAD that the entry observes
immediately before dispatch**: today a detached HEAD, after preparation the `task/<id>` tip the agent starts from.
Preparation first would add the lock, the dependency and the branch handling before any answer can be trusted.

## 2. Library calls (verified in installed source)

| Call | Fact used |
|---|---|
| `Repo.tree(f"{X}^{{commit}}")` (`real_read.py:128-153`) | Resolves `rev^{commit}`, then `rev^{tree}`; for this rev both fail on a tree id, so a reported tree id gives `None` (as does any nonzero rc). `Tree.sha` is the resolved commit; `Tree.files[path] = (mode, blob)` comes from `ls-tree -r`. The fake strips `^{commit}` and also gives `None` (`fake_store.py:188-198`). |
| `Repo.tree(f"{c}^")` | First parent: `Tree.sha` is its sha; `None` at a root commit. Real and fake both support `^`. The fake does **not** parse `^2` (`_STEP`, `fake_store.py:27`), so merges are found by counting (section 3). |
| `Repo.relate(B, X)` (`real_read.py:81-91`) | `ahead = \|X..B\|`; `behind = \|B..X\|` = N, the number of commits in the chain. |
| `Worktree.diff(p, c, cap=0)` (`real_read.py:240-256`) | `--raw --numstat -z --no-renames --no-ext-diff`; returns `changes`, no patch. Kinds A/M/D; a type change shows as M (`real_parse.py:124`), so modes come from `Tree.files`, never from the diff. |
| `Repo.identity()` | `key` and `root` (the common dir's parent when that dir is named `.git`). |
| `Repo.worktrees()`, `Worktree.dirty()` | The slot's `head` and `branch`; `dirty().raw` = tracked or untracked changes (ignored files not counted). |
| Errors | `MissingRevision`, `GitReadFailure` and `GitTimeout` are all `GitUnavailable`, which means **unknown**. |
| `RealRepo.run(..., timeout=None)` (`real.py:130-168`) | No local read passes a timeout (section 8). |

**Where each read runs.** Identity is read through the slot (`RealRepo(cwd).identity()`); its `key` must equal
`admission.repo_id`, else unknown `repo`. Every commit read (`tree`, `relate`, `diff`) and `worktrees()` run from
`checkouts(identity.root)`, the person's checkout, because the slot's own git dir is the file the agent was nearest to.
Only `dirty()` runs on the slot.

## 3. The verdict: what "verified" means

> Superseded in part by [.4.3.1.7](../tl-8bh9.4.3.1.7/plan.md) sections 3-8: the factory commits the agent's listed paths; the chain is one step
> (`CHAIN_CAP` and the `merge` rule are gone); reuse (Q2) happens only on the agent's explicit `unchanged`; X is
> `plan_attempt.plan_commit`, not `reported_commit`; RULES gain `nothing_written` and `file_size`.

Inputs: the stored valid answer (`planned`, commit X, `plan_path` P = `docs/design/<task-id>/plan.md`), B from
`plan_attempt.base_commit`, and the admission's `cwd` and `repo_id`. Every check reads only content-addressed objects,
so the result can be stored for good. The first failure decides.

1. `t = tree(f"{X}^{{commit}}")`. `None`, or `t.sha != X` (an annotated tag or another name that resolves to some other
   commit): reject `commit_absent`.
2. `rel = relate(B, X)`, N = `rel.behind`. `rel.ahead != 0`: reject `not_descendant`. N > **8**: reject `chain_length`.
   N == 0 (X == B) is **reuse (Q2, decided)**: skip steps 3 and 4; step 5 applies in full and P must pass step 4's path
   rules. The verdict is `verified` with `reused` set, so it never reads as new work.
3. **Chain walk.** From c = X, take exactly N first-parent steps (`tree(f"{c}^").sha`). B must be reached at step N and
   not before, else reject `merge`: a first-parent walk shorter than `|B..X|` means a merge brought in outside commits.
   A parent read that gives `None` is **unknown** (`git:Unreadable`), never `merge`: the library reads it with an
   unchecked exit code, so a root commit and a failed read look the same.
4. **Each commit in the chain** (c with parent p), over `diff(p, c, cap=0)`: every change is A or M (a D rejects `paths`);
   its path lies under `docs/design/<task-id>/` and has no empty, `.`, `..` or `.git` component in any case (macOS file
   systems ignore case), else `paths`; and `tree(c).files[path][0] == "100644"`, else `mode` (a changed path missing
   from the listing is unknown). Checking every commit catches a disallowed file that a later commit modified away.
5. **The plan at X.** `t.files.get(P)` missing: `plan_missing`; mode not `100644`: `mode`. Read the whole blob
   (`t.read(P)`; `None` for a listed path is unknown, `git:Unreadable`, never `plan_missing`); it must decode as strict UTF-8 (`plan_encoding`), not be whitespace only (`plan_empty`), and be at
   most 1 MiB (`plan_size`). The size is known only after the full read: `Tree.files` carries no sizes. There are no
   heading or structure checks, and this is never presented as review of the plan's content (3.2.1).

**Chain cap of 8.** A plan step commits the plan and perhaps a few design artifacts; a longer chain is outside the
prompt's contract. The cap also bounds the reads: about four untimed git reads per step (section 8), so about 35 in all.

**Merges** are rejected: a plan step has no reason to merge. One merge cannot be seen: a merge whose other parents are
already in B's history (the library gives no parent list, and the fake has no `^2`). It is harmless, because step 4's
first-parent diff still applies the path and mode rules to everything it brings in.

## 4. Slot preconditions (not stored; decided: Q5)

- **Admission refuses first.** `slots._clean` gains `unborn` (`WorktreeInfo.head is None`) and `attached` (`branch is
  not None`). Such a slot is `unknown`, never `free`, so admission refuses `no_free_slot`. `adopt` shares the function
  and refuses such a worktree too; that is intended (the smoke makes slots with `git worktree add --detach`).
- **The body checks again before dispatch.** In `_start`, after `_launch` and before `store.dispatch`,
  `observe_slot(checkouts, cwd)` (in `plan_verify.py`) reads `(head, branch, dirty)`. `GitUnavailable` gives
  `unavailable("git")`; unborn, a set branch or a dirty slot give `refused("slot_unborn" | "slot_branch" | "slot_dirty")`.
  A slot of another repository or one Git does not list gives `unavailable("repo" | "not_listed")`. Each leaves the
  attempt `admitted` and runs `harness.cleanup()`, as today. The reads have no timeout, so the deadline is checked again
  after them, immediately before the dispatch write (`refused("expired")`). Otherwise `dispatch(record, base=head)`
  writes `base_commit` in its conditional UPDATE.
- **B belongs on `AttemptRecord`, never on `Admission`.** `_fence` compares the whole `Admission`, so a field written
  at dispatch would make every later write fail with `changed_admission`.
- **Before the verdict**, `verify` runs the same `observe_slot` plus `head == X`. A failure returns `Unsettled(reason)`
  (`head_moved`, `branch`, `unborn`, `dirty`): nothing stored, retryable. These states can change, so they never become
  a verdict; the binding "at X and clean" check belongs to cleanup and publication, under the lock.

## 5. Storage: schema v2 -> v3 (no compat: `current()` refuses an old DB)

One owner per fact. B is owned by `plan_attempt.base_commit` and X by `plan_attempt.plan_commit` (schema v4,
[.4.3.1.7](../tl-8bh9.4.3.1.7/plan.md); schema v3 had X in `plan_execution.reported_commit`, now replaced by `commit_paths`/`commit_message`), each
written once. The verdict table holds only what is new:

```sql
-- plan_attempt gains: base_commit TEXT CHECK(base_commit IS NULL OR length(base_commit) IN (40,64)),
--                     CHECK(phase='admitted' OR base_commit IS NOT NULL)
CREATE TABLE plan_verification (
 attempt_id TEXT PRIMARY KEY REFERENCES plan_execution(attempt_id), dispatch_token TEXT NOT NULL, generation INTEGER NOT NULL,
 verdict TEXT NOT NULL CHECK(verdict IN ('verified','rejected')), reason TEXT, plan_blob TEXT, observed_at REAL NOT NULL,
 reused INTEGER NOT NULL DEFAULT 0 CHECK(reused IN (0,1)), CHECK(reused=0 OR verdict='verified'),
 CHECK((verdict='verified') = (reason IS NULL)), CHECK((verdict='verified') = (plan_blob IS NOT NULL))
);
```

**The writer** is `plan_store.py`, already the conditional SQL owner, through a new `PlanStore.verdict(admission, base,
commit, result)`. `plan_verify.py` reads Git and nothing else. `WRITERS` gains `("CREATE TABLE","plan_verification"):
plan_schema.py` and `("INSERT","plan_verification"): plan_store.py`; there is no UPDATE or DELETE. The INSERT runs in
one `begin_immediate`, only while the reservation is still held for this attempt and generation (the fence runs inside
the writer), the run was clean (`rc=0`, not timed out), the session publication is `complete`, `answer_kind='valid'`,
`disposition` `planned` or `unchanged`, and the stored `plan_commit` and `base_commit` equal the X and B that were
verified (`nothing_written` alone has no commit, with `plan_commit` NULL; [.4.3.1.7](../tl-8bh9.4.3.1.7/plan.md)); otherwise it
refuses (`stale_reservation` / `changed_answer`). It uses
`ON CONFLICT DO NOTHING`, then reads the row back. The inputs cannot change, so a second verifier computes the same
verdict and there is no conflict branch; a stored row that differs would be a defect, reported as
`unavailable("inconsistent")`. No Git call runs inside the transaction. Line risk: `plan_store.py` grows from 329 to
about 370 lines; if the 400 cap is hit, `_execution`'s row decoding moves to a reader module, and the writer stays.

**Read by collect.** `_execution` LEFT JOINs the verdict, and `StoredExecution` gains `verification`.

| Stored state | `AttemptResult` |
|---|---|
| valid `planned`, no verdict | `pending("verification")` |
| `verified` / `verified` with `reused` | `collected("verified")` / `collected("reused")` |
| `rejected` | `collected("rejected:<reason>")` |
| `incomplete` / `needs_owner`; invalid answer | `collected("<disposition>")`; `collected("answer:<kind>")` |

`collected` means "terminal": it already covers invalid answers today, so it never means success. Every `collected`
result now carries a reason, and success is `collected` with reason `verified` (new work) or `reused` (an existing plan,
no new commit). Consumers must read the reason (section 6).

## 6. Operation and the entry

`PlanVerifier(store, checkouts, clock).verify(key)` returns `Verified(reused)`, `Rejected(reason)`, `Unsettled(reason)`,
`NotApplicable(what)`, `VerifyRefused(reason)` or `VerifyUnavailable(reason)`:

1. `store.collect(key)`. `None`: refused `not_captured`. `validation_pending`: unavailable. A stored verdict: return it
   with **no Git read**. A non-planned or invalid answer, or a failed run: `NotApplicable`, with no Git read. A session
   publication still `pending`/`fault`: unavailable `session_<state>`; `conflict`: refused `session`.
2. `store.load(key)`. `StoreRefused` (stale reservation): refused. A NULL base: refused `no_base`.
3. Identity, the section 4 preconditions (`Unsettled`), then the section 3 checks, all outside any transaction. An
   unknown gives `VerifyUnavailable("git:<Type>" | "repo" | "not_listed")` and stores nothing.
4. `store.verdict(...)`.

**The entry.** `attempt_entry.enter` calls `verify` once, without retry, after `execute`/`publish` (it returns
`not_applicable` or `refused:not_captured` when there is nothing to verify). Its one log line becomes
`<status> <reason>[ publish=<s>[ then=<status>:<reason>]] verify=<verified|reused|rejected:r|unsettled:r|unavailable:r|refused:r|not_applicable>`;
the `verify=` part is always present, and after a stored verdict the leading words (or `then=`) are read back, so success
reads `collected verified verify=verified`. The identity, database and usage refusals before `execute` keep their own
one-word lines. The exit code stays display only: 0 exactly for a collected `verified` or `reused`, 1 otherwise,
including `incomplete`. A rejected or unsettled result therefore never looks like success in the log or the exit code.
`composition.open_plan_verifier(db)` wires the same operation for the coordinator, but **it has no production caller
yet**: nothing re-triggers a verification that the entry left `unsettled` or `unavailable`, so such an attempt stays
`pending("verification")` until an operator or coordinator entry point (a follow-up) calls it. A lost acknowledgment is
handled by calling `verify` again (3.2.1); the agent is never rerun.

## 7. Failure and unknown table (every row keeps the reservation and the claim)

| Situation | Stored | Result | Next |
|---|---|---|---|
| Git missing, `index.lock`, timeout, read failure | nothing | unavailable `git:<Type>` | call again (no caller yet: section 6) |
| A chain parent, a listed plan blob or a changed path's listing entry reads as nothing | nothing | unavailable `git:Unreadable` | call again; persistent: owner inspects |
| B no longer resolves (lost to gc, or an object missing) | nothing | unavailable `git:MissingRevision`, **permanently** | owner decides; no automatic path |
| Identity mismatch, or the slot is not listed | nothing | unavailable `repo` / `not_listed` | owner inspects |
| Slot HEAD is not X, on a branch, unborn, or dirty | nothing | `unsettled:<r>`, retryable | owner or cleanup slice; work retained |
| Answer not `planned`, or invalid | nothing | not_applicable | reported as in section 5 |
| X absent, not a descendant, chain too long, merge, path, mode or plan rule broken | `rejected` | `collected("rejected:<r>")` | terminal for the attempt (Q6) |
| `tree()` gives `None` because the repository is corrupt or the read failed, not because X is absent | `rejected commit_absent` | a **false terminal**, accepted | owner repairs and admits again |

The one accepted false terminal is `commit_absent`. Through `verify` it is in practice **only** that false terminal: the
slot precondition runs first and requires HEAD == X, and a HEAD is always an existing commit, so a truly absent X
reports `unsettled:head_moved`; `commit_absent` is reached only when the read of X itself fails (or X names a tag or
another name of a commit). Every other `None` read is unknown, not a verdict.
| Every rule holds | `verified` | `collected("verified")` | slice 3 pushes X |
| X == B, and the plan at B passes | `verified`, `reused` | `collected("reused")` | slice 3 publishes B; nothing new |
| Store unavailable; stale reservation | nothing | unavailable `store` / refused | call again / none |
| Before dispatch: Git unavailable; slot unborn, branched or dirty | `admitted` stays | unavailable / refused; cleanup runs | fix it; a new entry (O2) |

## 8. Still unresolved after this slice

- **Custody.** No lock is taken, and the agent's descendants have no stop proof (.4.4); later slot changes are found
  only by the lock-held checks of slices 2 and 4. No ref pins X (Q7): on a detached HEAD, X is held only by the
  worktree's HEAD and its reflog until slice 2 creates the branch.
- **The sandbox was not a boundary** (resolved in [.4.3.1.7](../tl-8bh9.4.3.1.7/plan.md)). Revision 2 of this slice set `approval_policy=on-request`
  with `approvals_reviewer=auto_review`, so an approved command ran **outside** the sandbox (smoke 3 saw the agent's
  commit succeed that way). Now `CODEX_ACCESS` sets `approval_policy=never` with no reviewer, the agent never writes
  Git, and every factory Git call runs with hooks, fsmonitor, signing and auto-maintenance off. Under the old flags an
  escalated command could write the shared `.git/config` (hooks, `core.fsmonitor`,
  `core.worktree`, include paths) and create refs and tags, none detected here. A `core.fsmonitor` set that way would run
  a program on the factory's own `git status`; git_porcelain does not neutralise it (no `-c` for it in `real_env.py`).
  Reading commits from the person's checkout narrows this but cannot close it, because `.git/config` is shared. The same
  class is unmitigated on every read from the root: `status` (fsmonitor, `core.untrackedCache`), `diff --raw --numstat`
  (`diff.<driver>.textconv`/`binary` attributes from a `.gitattributes` the agent committed or from `info/attributes`,
  which may change the counts numstat shows; the kind and path come from `--raw`, believed unaffected but not observed), `ls-tree` and `cat-file blob` (no filters).
  Whether textconv applies to `--numstat` was not observed; the verdict uses only kinds, paths, modes and blob bytes. The smoke
  records which escalations were approved (live-smoke section 7); hardening (a library `-c core.fsmonitor=false`, or a
  smaller `CODEX_ACCESS`) is decided on that evidence.
- **Hangs.** Local git reads have no timeout (`RealRepo.run`, `timeout=None`). A hung read in the entry is the existing
  ".4.3.1.4 section 7: entry alive but hung" wedge; nothing here bounds it, and the deadline does not bound Git. The
  bound belongs to git_porcelain (a read timeout, a shelf follow-up), not a factory wrapper.
- **Also open:** the task branch, publication, reservation release, an attempt whose deadline passes while `admitted`,
  and wedges in `dispatching`/`registered`.
- **process-lock (slice 2).** It is not in `uv.lock` and no dependency brings it in, so a direct pin at
  `process-lock-v0.2.1` (d3d611c) is not redundant. Any copy inherited later must use the same pin; `test_isolation.SHARED`
  gains a row; no `.holder` sidecar. It ships no fake and polls with `time.sleep`, so tests would take the real
  in-process flock on a `tmp_path` file with `timeout=0`.

## 9. Live smoke results that would reopen this design

| Smoke result | Effect |
|---|---|
| `refused identity` (start or boot changes across exec on macOS) | No live entry runs. This design is unchanged; the launcher fix comes first. |
| Commit refused, so the answer is `incomplete` | Resolved by [.4.3.1.7](../tl-8bh9.4.3.1.7/plan.md) (the factory commits). Verification is valid but never exercised live. Slice 2 must choose between a sandbox that may write the git common dir and **the factory committing the plan** (`Worktree.record(paths="own")` under the lock). In the second case X comes from the factory's `Recorded.sha`, `planned` stops requiring a reported commit (an owner decision), and the verdict's X binds to a new factory-owned column instead of `reported_commit`. |
| Commit made **through an approved escalation** | Seen in smoke 3; resolved by [.4.3.1.7](../tl-8bh9.4.3.1.7/plan.md) (`never`, hardened Git). The sandbox assumption is void (section 8): treat `.git/config` as agent-writable and harden before slice 2. |
| Slot dirty after the run, or HEAD not at X | Section 4 gives `unsettled` with nothing stored until a person or the cleanup slice acts. If common, the prompt needs work; verification does not loosen. |
| A second commit, or an extra file | Within the chain and path rules, or rejected. Confirms or tunes Q3 and the cap of 8. |
| The push bar fails (a `smoke` ref exists) | Fix it before slice 3. |
| `collect` fails from a fresh shell | A body defect; fix it before the entry hook-in. |

## 10. Tests (pytest functions; FakeRepo; no spawn; caps 400/80/800)

**Contract, then consumer.** git_porcelain's contract suite runs RealRepo and FakeRepo; the factory tests its consumer
against `git_porcelain.testing.FakeRepo`, with commits from `add_worktree`, `write_file` and `record(paths="all")`.

`tests/plan/test_verify.py` (~340 lines) holds one parametrized table:
- **Verified:** one commit; a chain of three; `reused` (X == B with a valid plan); X == B with no plan, or an empty
  plan, rejected.
- **Rejected:** `commit_absent` (a random sha; a tree id from the fake's store); `not_descendant` (X = the parent of B,
  after the slot commits once before dispatch); `chain_length` (9 commits); `paths` (an extra file; a deletion; an
  outside file that a later commit modifies away; a `.git`/`..` component in any case); `plan_missing`; `plan_empty`;
  `plan_encoding` (invalid bytes); `plan_size` (1 MiB plus one byte).
- **Unsettled** (nothing stored): a moved HEAD, `checkout_new`, an untracked file. **Unknown** (nothing stored): an
  unresolvable B, `drop_checkout`, an identity mismatch.

Further cases: not_applicable for each non-planned answer; a stored verdict returned after `drop_checkout` (proves no
Git read); a second `verify` returns the same row; a stale reservation refuses; the `collect` reasons of section 5.

**Left to the library contract and the smoke** (the fake cannot express them): `mode` (`FakeRepo.tree` always reports
`100644`), `merge` (the fake's `record` cannot make a merge commit here) and the corrupt-repository false terminal. Do
not hand-roll a Repo stub to fill these gaps.

**Fallout in existing tests.** The conftest `admitted` fixture writes `cwd = tmp_path`, but the FakeRepo clone sits at
`tmp_path/"main"`: the slot must become a real fake worktree (`root/<repo_id>/s1`) with a matching `repo_id`, which
touches `test_attempt.py`, `test_entry.py` and `test_entry_store.py`. The 13 test constructions of `PlanAttempts` (11 in
`test_attempt.py`, 1 each in `test_entry.py` and `test_admit.py`), and the one in composition, gain `checkouts` and
move to one shared conftest helper. `test_attempt.py` is at 739 of 800 lines, so new body cases go in
`test_dispatch_slot.py`: base recorded; an unborn, branched or dirty slot refused with zero run calls and `cleanup`
called; `_fence` unchanged after dispatch. `test_slots.py` gains `unborn` and `attached` rows; `tests/rules/test_policy.py`
the two `WRITERS` rows; `test_entry.py` the `verify=` field, the exit code, and no retry.

## 11. Files and acceptance

Estimates: `plan_verify.py` ~150 (new, Git only), `plan_store.py` ~+40, `plan_schema.py` +12, `plan.py` +16 (~310),
`plan_types.py` +14, `slots.py` +4, `attempt_entry.py` +10, `composition.py` +12.

1. `verify` reads Git only through the calls in section 2, with no Git write, process, lock, ref or push.
2. A verdict depends only on (B, X, chain, blob). Slot state never becomes a verdict; every `GitUnavailable` stores nothing.
3. `plan_store.py` is the only writer of `plan_verification`; the insert is conditional, never rewritten, and a repeat
   call reads no Git.
4. B is recorded at dispatch from a detached, born, clean slot; admission already refuses unborn or attached slots.
5. Success is exactly `collected("verified")` or `collected("reused")`; the entry's line always carries `verify=`, and its
   exit code is 0 only for those two.
6. `just check` and `just test` pass (run by the implementer after the smoke; no live run by an agent).

## 12. Owner decisions (none open)

Decided 2026-11-10:
- **Q1:** slot state is a non-stored precondition, not part of the verdict.
- **Q2:** reuse is allowed when X == B and a valid plan exists at B. The verdict is `verified` with a distinct `reused`
  marker, so it never reads as new work; the content floor and the path and mode rules still apply to the plan file.
  Remaining limit: in this slice B is usually the person's main line, so a reused plan was landed earlier; review can
  still judge whether reuse fits, because `reused` stays visible.
- **Q3:** A or M only, under `docs/design/<task-id>/`; every entry mode `100644`; no `.`, `..` or `.git` component;
  `plan.md` required.
- **Chain:** a short chain is allowed with every commit checked; the author set the cap at 8 and rejects merges.
- **Q4** (the author's call): strict UTF-8, not whitespace only, at most 1 MiB after a full read, mode `100644`.
- **Q5:** dispatch is refused from a dirty, branched or unborn slot, and admission refuses first through `_clean`.
- **Q6:** a rejection is terminal for the attempt. **Q7:** no ref pins X. **Q8:** preparation and lock come before publication.

## 13. Not verified

Nothing was run. Library facts come from the installed git_porcelain 0.13.0 source and `git show` of the shelf tag. Not
observed: real `tree()` on a corrupt object; that the real `rev-parse` of `X^{commit}^{tree}` fails on a tree id
(inferred from git's syntax); `worktrees()` path equality through symlinked roots; `RepoIdentity.root` for a separate git
dir (it is then the common dir itself; reads should still work, unverified); whether `process-lock-v0.2.1` is fetchable
from GitHub. All line counts are estimates.
