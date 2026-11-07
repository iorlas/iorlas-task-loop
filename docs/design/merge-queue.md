# Merge queue (MQUEUE): speculative, serial in meaning, parallel in execution (design only, 2026-11-07)

Verdicts: ✅ do, ❌ refuse. Tags on external facts: [V] read in a primary source, [S] secondary report, [I] inference. Anything marked
`[unverified]` was not re-checked: numeric limits and defaults of other systems came from lossy page summaries and must be re-read before
they are copied into config. Inputs: land-speed.md, slot-grant.md, stages.md section 6, dashboard/dash-spec.md section 4, and the code under
`src/taskloop/app/land/` (stack.py, stackgate.py, cleanup.py, lander.py), `contracts/runkey.py`, `app/checks/cache.py`.

Decided before this doc, not reopened: bead deps are a scheduling gate only (no child starts or merges before its parent is on main); child
PRs always branch off main; no stacked PRs; no epic or integration branches by default (trunk, dark flags, queue); branches are updated by
merging main in (plain pushes, no force); landing stays squash, one commit per bead.

## As decided (Denis, 2026-11-07; section 15 has the reasoning)

| # | Question | Decision | Section |
|---|---|---|---|
| 1 | Queue commits | keep `gh pr merge --squash`; fast-forward the tested commit if the tree assertion fires twice | 2, 15 |
| 2 | `land_mode` push in the queue | no; one mode per repo; push mode is an out-of-queue pusher | 8, 10 |
| 3 | Path claims | display and queue rule only; delay dispatch within one epic after a month of overlap data | 11 |
| 4 | Lock main | lightweight: ruleset (no force-push, no deletion) plus a pre-push judge that refuses unmarked pushes to main; `tl doctor` fails on drift; full queue-only lock stays an owner option | 8.1 |
| 5 | Gates in flight: floor and cap | floor 1, cap 4, cap 3 if wasted ratio >0.5 in shadow; "window" and "lookahead" retired | 6 |
| 6 | Executor slot | freed at enqueued-green; back-pressure at queue length 2 x gates in flight | 10 |
| 7 | Tree mismatch | no blind revert; freeze, evidence, repair agent dispatched automatically; human only after two failed repairs | 2.1 |
| 8 | Quarantine | none in v1 or v2; retry, main check, flake score, auto fix bead; v2 owner-approved skip, 7 days, no silent renewal | 7 |
| 9 | Required-check set | profile is authoritative; `tl doctor` fails on drift | 8.1 |
| 10 | Stuck-head timeout | 2 x p90 gate seconds, measured in shadow; no number before data | 8 |

## 1. Problem and goals

Today (landing-code-map, `app/land/stack.py`): `land-stack` gates open PRs in parallel (prewarm, `--jobs` default 4), then merges serially
under the land lock. Each merge moves main, the next PR's receipt misses (base is in the RunKey), Carry may rescue it, else the gate reruns.
land-speed.md: 84 attempts, 46 landed, 25 gate-red, 7 conflict, 6 head-moved.

| Pain | Evidence | Cost |
|---|---|---|
| Slots idle while landing is serial | prewarm only helps independent PRs; the first failure stops the run (stack.py:82-88) | slot hours |
| Drift | every merge invalidates the receipts of PRs still waiting; Carry misses without `closure_cmd` or when main moved in closure files | CI seconds |
| Rework tokens | a conflict or red gate after someone else's merge goes back to the owning agent | tokens, the dear resource |
| Landing lag is invisible | `LandTry` logs fetch_s, rebase_s, gate_s (lander.py:213-226); whether anything shows them is unverified | Denis cannot see why "done" is not "on main" |

Goals, in order:
1. Never land a tree that was not tested (section 2).
2. Test PR N against main plus PRs 1..N-1 in parallel with the others, so a merge does not invalidate what is waiting.
3. Retest, never rework: a failure of an earlier PR costs CI, not agent tokens (section 5).
4. One config key falls back to today's path (section 14).
5. Landing lag and queue state are visible on Floor and Board (section 9).

Non-goals: batching in v1, probabilistic speculation, multiple queues per repo, replacing `tl land` (land_mode push) in v1.

## 2. Core invariant: tested tree == landed tree

**Invariant.** For every PR the lander merges, `tree(main after merge) == tree(the commit that was gated)`, and the parent of the new main
commit is the main the gate assumed. Everything else (gates in flight, AIMD, ejection) is allowed to be wrong in cost; this one is not allowed to be
wrong at all, because a silent mismatch ships untested code.

Why it is the first-ranked risk:
- GitHub merge queue, 2026-04-23 [S]: squash merges in multi-PR groups produced wrong commits for about 4 h; 658 repos and 2,092 PRs
  reported; cause a merge-base computation on a ref-update path; tests mostly used single-PR groups; no alert fired. Source is Mergify's
  write-up and a news report, not GitHub's postmortem [unverified]. The lesson that matters here does not depend on the numbers: the system
  that tested one commit and landed another had no check between them.
- Mergify's TLA+ model [S]: bugs found in the cross of freeze, batching and speculative skip (a frozen PR could still merge, a skipped
  intermediate result promoted untested code). Invariant list not seen [unverified]. Lesson used here: model the queue as a state machine
  and test the cross products (section 13), not the happy path.
- Bors [V] fast-forwards main to the tested `staging` commit, so the landed commit is the tested one by construction.

**How squash relates.** We keep squash (decided). GitHub computes the squash tree server side as the 3-way merge of the PR head into
current main. The queue computes the same merge locally before testing: `git merge-tree --write-tree Q(N-1) head(N)`. Equal trees follow
when `tree(main) == tree(Q(N-1))` and the merge bases agree (experiment, section 3.4).

**Three layers, none optional:**
1. *Pre-merge prediction* (under the land lock, before `gh pr merge`): `tree(main)` must equal `tree(Q(N-1))`, and
   `merge-tree(main, head(N))` must equal `T(N)`, the tested tree. Else do not merge; reset the item (section 5).
2. *Match-head*: `gh pr merge --squash --match-head-commit head(N)` stays (stack.py `merged`). It guards the head, not the base.
3. *Post-land assertion* (under the same lock, after fetch): `tree(merge_sha) == T(N)` and `parent(merge_sha) == main_before`.

**Action on mismatch** (layer 3 only; layers 1-2 just refuse):
- Parent differs from `main_before`: someone pushed to main between prediction and merge ("raced"). Run the gate on new main head as a
  backstop, record an incident row, reset the queue. No freeze.
- Parent as expected, tree differs ("corrupt"): freeze the queue (no merge, no new gate starts), incident row with evidence, then the
  recovery flow of section 2.1. No blind revert: a revert is a second write to main on the same broken path, and the cause may be an
  out-of-queue push, not the squash. Until the repair bead (section 16) lands, the interim is freeze plus one ask, as in tl-7s2f.3.
- ❌ Rejected: trusting `--match-head-commit` plus the gate. Head match says nothing about the base; this is the GitHub failure shape.
- ❌ Rejected: fast-forwarding main to the queue commits (bors style) in v1. Queue commits are already one per PR, so it would meet "one
  commit per bead" and the invariant by construction. But it bypasses `gh pr merge`: the PR would not show merged (queue commits are not
  the PR's commits), branch protection and merge record change. Revisit when the assertion fires twice (section 12): then queue commits are fast-forwarded (decision 1).

### 2.1 Recovery flow (decision 7: AI sorts it out, a human is the last resort)
States and moves, in words:
1. **Frozen.** A "corrupt" mismatch freezes the queue. Evidence is written first: both tree ids, the PR, `main_before`, `merge_sha`, the
   diff between the two trees, the events since the last clean assertion, and whether `origin/main` has any commit not made by the queue.
2. **Repair dispatched.** The engine starts a repair agent with that evidence, no ask. Default repair: a **revert PR** of the bad commit.
   Alternatives the agent may choose when the evidence says a revert is wrong: **fix-forward** (a PR that makes main equal the tested
   tree), or **re-merge main into the owner's branch** and re-gate. Whatever it picks is a normal PR: it enters the queue, gets the same
   gates and the same assertion. The queue is unfrozen for that one item only; everything else waits.
3. **Landed clean.** The repair PR passes the assertion: unfreeze, rebuild the rest from new main (section 4 invalidation), close the
   incident row.
4. **Textual merge conflict** (a different path, not a mismatch): the item is ejected with `conflict` and goes back to its **writer
   agent** to update from main (merge main in, plain push). The queue then rebuilds behind it and gates again. No human.
5. **Repair failed.** The repair PR is ejected or its assertion fires again: one more repair attempt with the first one's evidence added.
   Failing a second time is the only case that asks a human (Decisions tab and one ask to Denis). The queue stays frozen until the ask is
   answered.
The invariant is not weakened: the repair goes through layers 1-3 like any PR. What changes from the first draft is who acts, not what
is checked. Bead: repair dispatch (section 16).

## 3. Queue model

### 3.1 Semantics
Serial in meaning: PRs land in queue order, each on exactly the main it was tested on. Parallel in execution: up to G gates run at once
(G = gates in flight, section 6). Candidate N is gated on `main + PR1..PR(N-1) + PR(N)`, assuming 1..N-1 pass. If one fails the assumption is
repaired (section 5), never papered over.

```
 main:  M0
 Q1  = M0 + A        gate runs on tree T1
 Q2  = Q1 + B        gate runs on tree T2      (parallel with Q1)
 Q3  = Q2 + C        gate runs on tree T3      (parallel)

 merge order: A (needs main==Q0, T1 green) -> B (needs main tree==T1, T2 green) -> C (needs main tree==T2, T3 green)
```

### 3.2 The queue ref (ephemeral, local, not a PR)
- `Q(0)` is the main SHA at build time. `Q(N)` = commit with tree `merge-tree --write-tree Q(N-1) head(N)` and parent `Q(N-1)`
  (`git commit-tree`). It is a squash-shaped commit: one per PR, parent the previous. Stored as `refs/tl/queue/<n>-<short head>`.
- Local refs only. The gate is `tl check` in a worktree detached at `Q(N)` (`StackGate.fresh`, stackgate.py:151), so nothing is pushed
  and no CI trigger prefix exists to get wrong (GitHub needs `gh-readonly-queue/` [V]).
- A textual conflict at `merge-tree` is a result, not an exception: PR N is ejected with `conflict` (section 5).
- ❌ Rejected: a stacked PR (PR N based on branch of PR N-1). Decided; also GitHub retargets or closes children when the parent branch goes
  [S], and squash of the parent leaves duplicate commits in the child [S]. The queue ref is not a PR, has no author, is never merged, and
  is deleted after the item leaves the queue.

### 3.3 Smallest Carry change
Why Carry is needed: the gate runs on `Q(N)`, whose tree is `T(N)`; the receipt key is `(tree=T(N), base=Q(N-1))`. After A lands, main
is a new commit `S(A)` with `tree(S(A)) == T(A)`, so the landed commit of B has tree `T(N)` but base `S(A)`; key differs from the receipt
in `base` only. That is exactly `earlier_pass` (cleanup.py:325: key differs only in base), except Carry today proves the pass still holds by
closure comparison. Here we have a stronger fact: the parent tree is identical.

Change (about 30-60 lines in cleanup.py and stackgate.py, from the code map): a second carry mode `queue_parent`. A receipt whose `key.base`
is the item's recorded `Q(N-1)` counts under `base = main` when `tree(main) == tree(Q(N-1))` and the item's key matches (section 4). Carry
rewrites it with `carry_over` under the new base, `origin` naming the queue run. No closure command is needed, so checks without
`closure_cmd` stop missing. The closure mode stays for the non-queue path.

- ✅ Why not change RunKey: `base` is a SHA field shared by every check. A tree-valued base field would touch every receipt. The mode
  is a lookup rule, not a key change.
- ❌ Rejected: gating on `head(N)` and relying on Carry alone (today). The head tree does not contain A, so the tested tree is not
  `T(N)` and the invariant has nothing to compare.
- Unverified: how `authorization.results` and `memo.key` pick `base` for a queue worktree; the bead (b) starts by reading them.

### 3.4 Experiment: does the squash of A have exactly A-head's tree?
Run 2026-11-07 on pix, git 2.54.0, scratch repos under `~/tmp/mq-exp/` (scripts `exp.sh`, `exp2.sh`). The squash was `git merge --squash`
on the moving main, the stand-in for GitHub's server squash (GitHub's own computation is not reproduced here [unverified]).

| Case | Result |
|---|---|
| Chain A (2 commits, new file + edit), B (other hunk of same file + another file), C (same file, middle hunk): queue trees `Q1..Q3` built by `merge-tree --write-tree` + `commit-tree`; then A, B, C squashed one by one onto main | tree after each squash == tree of `Q1`, `Q2`, `Q3`. 3 of 3 equal |
| D updated by merging main in (main moved on an unrelated file), tested via `merge-tree(main, D)` | tested tree == landed tree. Equal |
| A updated by merging current main in, then squashed | squash tree == A head tree. Equal |
| A2 branched from old base, main moved on an unrelated file, A2 squashed | squash tree != A2 head tree. They differ, as they must |
| Adjacent-line edits by two PRs (line 2 and line 3 of one file) | textual conflict, as expected; the queue ejects with `conflict` |

Result and its limit:
- "Squash of A has exactly A-head's tree" is **true only when A's head already contains the main it is squashed onto**. The general true
  statement is: `tree(squash(A onto main')) == merge-tree(main', A)`. The queue therefore never uses a head tree; it builds `T(N)` from
  `merge-tree` and compares trees at landing.
- Property test (bead a, `tests/land/real/test_queue_tree_equality.py`, git 2.54.0, 2026-11-07): 1,000 seeded cases of 2-4 PRs of 1-3
  commits each (edit, add, delete, rename; branched stale from the base or from a main that moved on), the `merge-tree` chain
  `Q1..Qn` against `git merge --squash` onto the moving main. 2,126 PRs compared, 0 tree inequalities; 851 PRs the queue ejected on a
  conflict, and in every one the squash conflicted too (no case where one side was clean and the other not).
- Renames (a rename in one PR, an edit of the renamed file in another, a third PR after them): queue trees == squash trees. Equal.
- Criss-cross (two branches merging each other, `merge-base --all` returns 2 bases): queue trees == squash trees. Equal.
- Still unverified: GitHub's server-side squash. The real PR pair was not run: the `gh` token has no `delete_repo` scope, so a throwaway
  repo could not be removed afterwards. Layer 1 and the post-land assertion of section 2 (bead l) stay the guard for it.

### 3.5 How a queue commit is gated and keyed, and what `queue_carried` promises (bead tl-7s2f.4, part 3)
Written before the wiring so the review is of the rule, not of the diff. Code: `domain/land/queue_model.py` (planner), `app/land/queue_refs.py`
(Q(N)), `app/land/queue_run.py` (runner), `Carry.queue_carried` (cleanup.py), `QueueKey` (domain/land/queue_key.py), `TreeGuard` (treecheck.py).

**Keying of the gate run on Q(N).** The gate for entry N judges a detached worktree at `Q(N)`:
- `RunKey.tree` = `tree(Q(N))` = `T(N)`, the merge-tree result; this is the tree that will land.
- `RunKey.base` = `Q(N-1)`, the commit of the queue ahead (main itself for the first entry). A receipt is therefore made at a base that
  contains exactly the PRs it was tested with. All other fields (cmd, config, toolchain, env, inputs, selected, execution) are read as
  `tl check` reads them today, from the profile **at `Q(N-1)`** (not at origin/main): a profile change by an earlier PR in the queue is
  in force for the PRs behind it, as it will be on main once that PR lands.
- The profile-change rule of `StackGate.require` compares `.task-loop.json` of `Q(N-1)` with that of `Q(N)`: only the entry that changes
  the profile needs the owner's authorisation, and an entry behind it is not blamed for it.
- `StackGate.require` therefore gains one parameter, `base_override: str` (the parent queue commit). Without it nothing changes. With
  it, `moved_during` must not compare the override with origin/main (main moves under the queue by design); it compares the worktree HEAD
  only. A move of origin/main is the queue's own reconcile (section 9), not the gate's regate.
- The head entry has `Q(N-1) == main`, so its gate equals today's gate on the merge result (`merge-tree(main, head)`), plus the assertion.

**Crossing to main (`Carry.queue_carried`).** After the entries ahead landed, main is `S` with `tree(S) == T(N-1)` (the assertion of
section 2 guarantees it, or the queue is frozen). The receipt of entry N is at `base = Q(N-1)`; the land needs one at `base = S`. The
function promises exactly this and nothing more:
1. It stores a receipt under `base = main` **only if** `tree(main) == tree(Q(N-1))` (compared by tree id, not by commit) and an existing
   *passed*, *satisfied* receipt at `base = Q(N-1)` equals the key expected at `base = main` in **every other field** (`replace(base=...)`),
   including `tree = T(N)`. Any difference in any field is a miss and the step runs again.
2. The stored record keeps `origin` = the run that made the pass, so the log says where the green came from; the new row is the carry's.
3. It needs no `closure_cmd`: a check without one stops missing on a moved base. The closure mode (`Carry.carried`) is unchanged and is
   not used in the queue path.
4. It does **not** promise that `T(N)` is what will land. That is `TreeGuard` (refuse before the merge: `tree(main)` equals the tested
   parent tree and `merge-tree(main, head)` equals `T(N)`; verify after it). Carry proves the check result applies to a base; the
   guard proves the tree; neither replaces the other.
5. It does not carry a failure, a skip, or a flake verdict, and it never writes under a base other than the one asked for.
If main moved by a third party (tree differs from `T(N-1)`), the carry misses, the queue is rebuilt from the new main (section 5), and
the gate runs on a new `Q(N)`; nothing is merged on the old receipt.

**Open for review before the wiring.** (a) `base_override` and `RunKey.base` semantics for a check with `inputs_only` (base is `""` for
those, so the override is irrelevant to their key); (b) whether the gate's `named()` message should name the queue ahead; (c) the
profile read at `Q(N-1)` makes the very first run after a profile-changing PR depend on that PR having landed in the queue ref only.

## 4. Result key

```
QueueKey = (base_sha, [head_sha of PR1..PR(N-1), ordered], head_sha(N), check_set_hash)     identity of a build
Result   = QueueKey -> { tree T(N), Q(N) sha, per-check receipts (RunKey), started, finished, outcome }
Reuse    = by tree: a Result for tree T and the same check_set_hash serves any queue state producing the same T
```

- Source of the first form: Tide's staleness key, base SHA plus each PR head SHA [V]. Zuul freezes a repo state per item and reuses
  nothing [I]; GitHub keys on the group head SHA. We add the tree, which no fetched source does [I]: rebases, amends and re-ordering that
  give identical content reuse a Result. Chromium's trivial-rebase equivalence is the closest relative [V].
- `check_set_hash`: hash over the gate steps of the profile read at `base_sha` (ids, `cmd`, `config`, `toolchain` digests, which RunKey
  already computes per check). A profile change at base changes it. The same hash is what branch protection must require (section 8).
- **Invalidation**, each a rule not a heuristic:

| Event | Effect |
|---|---|
| main moved (any push) | `base_sha` differs; every build for the old base is dead, except an item whose parent tree still equals (pure fast case: main moved by landing the head of the queue) |
| head of any PR in the list changed (push, force-push by an agent) | that PR's builds and all builds behind it are dead; PR re-enters at its position |
| PR ahead ejected | builds containing it are dead; builds ahead of it live |
| check set changed (profile at base) | all dead |
| profile change PR itself (owner path) | barrier: one gate in flight around it, everything behind rebuilt |

- **Relation to RunKey and Carry:** RunKey stays the receipt identity per check. QueueKey is the identity of a build, one level up. Carry
  `queue_parent` (3.3) is the single place where a receipt crosses from `base = Q(N-1)` to `base = main`. Receipts are never
  keyed on the queue ref SHA alone.
- Freshness dial: Chromium bounds reuse by commit distance or 24 h [V, default unverified]. Our reuse is exact (tree + check set), so no
  time bound in v1; non-deterministic inputs (network, unpinned deps) are the failure of that choice. They are the flake policy's
  problem (section 7), not the key's.
- ❌ Rejected: keying on commit SHA only. Squash and update-by-merge create new SHAs for identical content; every merge would be a miss.
- ❌ Rejected: Uber-style build-target hashes (section 12).

## 5. Failure handling

Culprit classes and what happens:

| Class | Detect | Action | Back to agent? |
|---|---|---|---|
| Own gate failure | gate on `Q(N)` red, retry+main check (section 7) say not flake | eject N; rebuild only items behind N | yes: failing check output, once |
| Textual conflict | `merge-tree` conflicts at build, or at pre-merge prediction | eject N; items behind rebuilt | yes: conflict files + the merged diff of what landed (section 11 edge 3) |
| Culprit is ahead | gate on `Q(N)` red but `Q(N-1)` gate red too | N is not blamed; wait for the ahead item's verdict; rebuild after | **never** |
| Flake | section 7 | retry, then not blamed | no |
| Infra (timeout, killed) | per-gate timeout | retry once, then hold the item as `stuck`, not ejected | no; one ask |

Mechanics:
- **Attribution.** Gates run in parallel, so a red `Q(N)` could be N's or any ahead PR's fault. Rule: the earliest red item in order is
  the culprit candidate. N's red counts against N only when `Q(N-1)` is green or N is first. Else N waits (Zuul has the same ambiguity
  and degrades to serial worst case [V]).
- **Eject.** Culprit removed from the queue list; its item goes `ejected(reason)`; the bead goes back to its owner only per the table.
- **Rebuild only behind.** Items ahead of the culprit keep their builds. Items behind get new `Q` refs without the culprit and are retested.
  GitHub/GitLab/Zuul restart all behind [V]; Mergify prunes to speculations containing the culprit [V]. Ours is the Mergify rule and it is
  cheap to get right because the QueueKey carries the ahead list: an item is dead iff the culprit is in its list.
- **Do not send agents back when the culprit is ahead.** Their branch is untouched; only the local queue ref changes. Rework costs
  tokens, retest costs CI seconds.
- **Cancel in-flight gates containing the culprit.** Today prewarm is a blocking `pool.map` (stack.py:104-118, `warm` in stackgate.py:99):
  nothing can be cancelled and the first failure aborts the run. Needed: futures with a process-group handle per gate (spawner exposes
  `run`; a cancel API is unverified), `killpg` on cancel, worktree removed in `finally` (already the pattern in `warm`). Wasted seconds
  of a cancelled gate are booked to `wasted_gate_s` (section 6).
- A gate that already finished green with the culprit in its list is not reused (its QueueKey differs), but its per-check receipts feed
  tree-level reuse when the rebuilt tree is identical (rare but free).
- Concurrency of reset: all mutations (eject, rebuild, reorder) are one reconcile step over durable state (section 9), never edits from
  several threads.

## 6. Gates in flight

- **Terms** (docs/glossary.md, worked example there): *gates in flight* G = how many PRs are being tested at the same time, each on main
  plus the PRs ahead of it; G = 1 is today's serial behaviour. *Floor* = fewest in flight, 1. *Cap* = most in flight, default 4.
  *Queue depth* = PRs waiting, a different number. G starts at 1, grows by 1 after each success, halves after a failure, and stays
  between floor and cap. The draft words "window" and "lookahead" are retired (window also names an account's usage window; lookahead
  told nobody anything). Suggested config key: `land.queue.max_in_flight` (the cap).
- **Start at G = 1** per repo: the queue then equals today's serial behaviour with the new invariant and bookkeeping. This isolates
  correctness bugs from cost-tuning bugs.
- **AIMD, Zuul style** [V for the shape; defaults unverified]: Zuul grows linear on merge (+1) and halves on failure, window 20, floor 3
  by default [unverified]. Ours: floor 1, +1 per merged PR, halve (round down, min 1) per *own gate failure or conflict eject*, not per
  flake or infra stop. Cap configurable, default 4 (the current `--jobs` default, cli/land_stack.py:102). Per repo; one queue per repo in
  v1, so a flaky repo does not shrink another's gates in flight (Zuul isolates per change queue [V]).
- **Why gates in flight are bounded.** If a gate fails with probability p, the chance a speculative build d gates deep build survives is about (1-p)^d [I,
  not from a source]. land-speed.md shows 25 of 84 attempts gate-red, about 30%. Much of that is owners running `just test` not
  `just check` (code map), which the queue does not change for pre-queue red but which should fall once the owner gate is the same check
  set. At p = 0.3 and d = 4 only 24% of the deepest builds survive [I]: a cap of 4 is already generous, and AIMD is what will find the
  real number. Uber still builds ~2x per change after tuning [V]; expect waste.
- **Wasted-gate accounting** (on every ejection and every change of G): `wasted_gate_s` = seconds of gates that were cancelled or
  invalidated; `useful_gate_s` = seconds of gates whose result was used. Ratio over the last 20 merges above 0.5 holds G (no increase)
  [threshold is a guess, tunable]; above 0.5 in shadow, the cap drops to 3. Each wasted build records its cause (culprit ahead, base moved, head changed, config change).
- **Batching only when queue depth regularly exceeds 3** (median queue length over a week). Then: group the front K PRs as one build,
  on red bisect by halving, never retest the last (if all earlier parts pass, the last is the culprit; Mergify trick [V]). Batch only
  PRs of equal priority and no overlap (section 11). Costs: loses per-commit greenness, lengthens attribution [V Graphite caveat].
  Not v1: single owner, volume is a handful of PRs a day [I].
- ❌ Rejected: starting at many gates in flight at once. One bug in section 2 or 4 would turn into mass wasted CI and mass ejections at once.

## 7. Flakes

A flake that ejects a good PR resets everything behind it, and agents then "fix" green code. So no red is blamed before:
1. **Retry the failed shard once**, same config, no rebuild (Chromium [V]). `app/checks/attempts.py:113-126` already retries checks
   flagged flaky and refuses on exit 124, compile error, or identical output twice; the queue reuses it and adds the next step.
   Whether any real check has the `retry` flag set is unverified.
2. **Still red: run the failing test(s) on clean main** ("without patch", Chromium [V]). Main also fails: not the PR's fault. The
   item is not ejected; it is marked `held(main-red)`, one ask to Denis, and the queue does not merge until main is green again (a red main
   makes every verdict moot).
3. Main passes, PR fails twice: blame the PR (section 5).
4. **Flake score log**: per test id, `(fails that passed on retry or on main) / runs`, rolling, one row per event. Feeds shared.md "known
   flakes" and the dashboard.

Reconcile with `stages.md` section 6 rule 4 ("a known flake red at a gate = retry once, then ask once, not a fix round") and shared.md
known flakes (rule 1c, design only): rule 4 is the writer-side statement of steps 1-2. The "ask once" becomes "log once, ask when the
score crosses a threshold or main is red" (asking per flake would generate the noise rule 4 tried to stop). The known-flakes list is
the human-readable projection of the flake score log. Neither has a registry in code today (code map).

- **No automatic quarantine, in v1 or v2** (decision 8; Denis's rule is fail early, fail often). In plain words: a quarantined test is a
  test that stops being able to fail the gate. The gate then says green about code it no longer checks, and nobody sees the hole. So a
  flaky test keeps failing loudly, and we make that cheap and then make it get fixed:
  1. A red shard is retried once; still red, the failing test runs on clean main (steps 1-2 above). A test that fails on main or passes on
     retry is *not blamed on the PR*; it is not hidden either: every such event is a row in the flake score.
  2. When one test has more than 3 flake rows in a week, the engine files a **fix bead** for it automatically (owner: the next free
     slot, normal priority). The test stays in the gate.
  3. v2 only: the owner may approve a **skip** for one test, with a hard expiry of 7 days. It shows on Board and Floor as a hole. It
     cannot be renewed silently: at expiry the test is back in the gate, and a new skip is a new owner approval with the fix bead still open.
  Cost accepted: a flaky test can still delay the queue (retry plus main check, minutes). Gain: no unseen coverage loss.
- ❌ Rejected: unlimited retry (hides real failures; OpenStack's recheck-spamming, fixed by a "clean check" policy [S]). Retry cap is 1.
- ❌ Rejected: Aviator-style "a later green covers the earlier red" [V] and Mergify `skip_intermediate_results` [V]: they give up
  per-state validation, which is the invariant.

## 8. Out-of-queue pushes, hotfix, freeze, required checks, timeouts

- **Push to main outside the queue** (human, `tl land` push mode, a hotfix): detected each tick by comparing `origin/main` with the
  queue's `base_sha`, and always at pre-merge. Action: reset all builds (section 4 invalidation), rebuild from new main. Items keep order.
  Cost: full re-speculation; accepted, it is how every system does it (GitHub jump-to-top, GitLab merge-immediately, Mergify priority
  [V]).
- **Hotfix lane.** A PR labelled hotfix jumps to position 1, cancels in-flight builds, and rebuilds the rest behind it. It gets the same
  gates and the same assertion; "without restarting" merges [V GitLab] are ❌ refused: untested relative to the queue. The owner can
  push directly; that is just the case above.
- **Owner freeze.** One switch in config/dash: no new gate starts, no merge; in-flight gates finish and keep results; unfreeze runs
  reconcile. Also the automatic reaction to a "corrupt" mismatch (section 2).
- **Required-check set declared once.** The set is the gate steps of the profile at `base_sha`; its hash is `check_set_hash` in the
  QueueKey (section 4) and the value that GitHub branch protection must list. Any drift between the two is a silent hole (Aviator needs
  explicit required-check config on drafts [V]). The profile is authoritative (decision 9): `tl doctor`
  compares its set with the repo's protection rules via `gh api` and **fails** on any difference, no warn-only phase (section 8.1).
- - **Timeouts.** Per gate (default 2 x the 90th percentile of recent gate seconds for that repo, floor from config) and stuck-head (the
  item at queue head with a green gate that cannot merge for N min; N = 2 x p90 gate seconds, measured in shadow mode first, no number
  committed before data: decision 10): per-gate expiry gives `stuck`, retry once; head stuck gives an
  incident row, ejection of the head with reason `stuck`, rebuild behind. Without these a hung gate blocks everyone (GitHub, bors, Aviator,
  GitLab all have one [V]). Shopify's lesson: do not eject for a *pending* check, wait for it [V]; our timeout is on running time, not
  on pending.

### 8.1 Automatic guard rails (decision 4: boundaries so drift cannot happen)
Goal: the settings that make the invariant true on GitHub are checked by the machine on every `tl doctor` run, not remembered by a person.
- **Finding, 2026-11-07 (read-only `gh api`, as admin of iorlas/iorlas-task-loop):** `branches/main/protection` returns 404 "Branch not
  protected", `branches/main` reports `protected: false`, `rulesets` is `[]`. So today **nothing** stops a direct push to main and no
  check is required. This is what the "raced" class (section 2) rests on. Not checked: other branches, org-level rulesets, GitHub
  merge-queue settings.
- **Applied 2026-11-07 (by the owner's lead, not by code):** ruleset id 26735683 "main: no force-push, no deletion": rules `deletion` and
  `non_fast_forward`, no bypass actors. Denis prefers lightweight over GitHub rules. Deliberately **no** required PR and **no** required
  status checks on main: `land_mode: push` (`app/land/push.py`) and release (`app/release/publish.py`, `push.py`: `git push origin
  HEAD:main`) push to main directly and a PR rule would break both. Rollback: `gh api -X DELETE repos/iorlas/iorlas-task-loop/rulesets/26735683`.
  The repo is public and the owner is admin. The earlier "queue-only pushes" lock (decision 4) is therefore met by the hook layer below,
  not by GitHub; the full lock stays an owner option once push mode and release go through the queue.
- **Lightweight layer: the pre-push judge.** `app/land/push_judge.py` is extended to refuse any push to main that does not carry tl's land
  or release marker. Agent worktrees push to `claude/<slug>` branches only, so they never meet the rule. Limit: a git hook is bypassable
  with `--no-verify` (forbidden by our rules) and covers only machines with tl installed. That is why the ruleset stays: it is the
  floor for everything the hook cannot see.
- **What doctor checks, each a FAIL (non-zero exit) on drift, never a warning:**
  1. the ruleset exists: `deletion` and `non_fast_forward` on main, no bypass actors (an absent or loosened ruleset fails);
  2. the pre-push hook is installed in **every registered worktree** and is the current judge (a missing hook fails);
  3. no required-PR or required-status-check rule is present unless the profile's check set equals it (names and `check_set_hash`,
     section 4; decision 9, the profile is authoritative);
  4. strict "branch must be up to date" is off (the queue handles it; on, GitHub rejects queue merges).
  Mode gating: all four fail in every mode once the ruleset exists; the optional full lock (queue-only pushes, hotfix bypass) is a
  later owner step and adds its own rows then.
- **The bead produces, it does not apply.** Changing GitHub settings stays the owner's act. The bead outputs the exact `gh api` calls and
  settings (a printed script) for the ruleset and for the optional full lock, plus the doctor checks.
- Reads `gh api` only; needs admin scope to see protection, and doctor says "cannot read protection (token scope)" as a FAIL, not a pass.
- Same rule for `tl doctor`'s other queue checks: the reconcile loop (section 9) and these guard rails are the two things doctor owns.

## 9. Durability, reconcile loop, visibility

**State that must survive a crash:** queue list (PR, bead, head SHA, state, position, entered_ts), builds (QueueKey, `Q` sha, tree,
state, worktree path, owner pid + start_id + lease expiry, started, finished), event log (ejections, resets, flake rows), flags (freeze,
gates in flight, last base_sha).

**Where.** Direction: factory.db, SQLite, one transaction per state change. slot-grant.md names it for the slot family and
sqlite-store-plan.md describes the stores; the exact family and schema are for bead (g) [I; the plan was not re-read for this doc]. Files
first would repeat the slot-grant lesson (take files with races). Until factory.db is available the interim is one JSON file written
atomically under the land lock; the reconcile loop is the same either way.

**Reconcile loop** (idempotent, runs each loop tick and in `tl doctor`, read-only there). A pure function from
`(db state, git refs, worktrees, live pids, origin/main, forge PR states)` to a list of actions. Same input, same actions; running it
twice does nothing the second time. It fixes:
- orphaned build (pid dead or lease expired): kill group if any, remove worktree, remove `refs/tl/queue/*` not named by a live build;
- half-reset state (crash between "mark dead" and "start rebuild"): every item must have either a live build for its current QueueKey or
  be in state `pending`; anything else is reset to `pending`;
- merged but not recorded (crash between `gh pr merge` and `tl land` record, stack.py `merged`): PR is MERGED on the forge and `merge_sha`
  exists -> run the post-land assertion, then record; never merge again;
- ejected items whose bead was not notified;
- gates-in-flight state not matching the last events (recompute).
Zuul's 2024 orphaned-changes report [S] and Tide's partial-merge TODO [V] are the failure shapes. Pattern is the slot watchdog
(slot-grant.md (b)): a pure function plus a heal, one incident row per episode.

**How bead (g) is built (decided 2026-11-07, for review).** Written before the code so the review is of the rule. Three slices, in this order:
1. *Reconcile, pure (domain, no store, can start now).* `domain/land/queue_reconcile.py`:
   `reconcile(entries: Sequence[Entry], facts: Facts) -> list[Action]`, where `Facts` holds the observed world as plain values: the queue
   refs that exist, the worktrees that exist, the pids that are alive (with their start ids), `main_sha`, the forge state of each PR
   (`open | merged(merge_sha) | closed`), and the clock. `Action` is a closed set of frozen dataclasses: `KillBuild`, `RemoveWorktree`,
   `DropRef`, `ResetPending(branch)`, `AssertAndRecord(branch, merge_sha)`, `NotifyEjected(branch)`. The rules are the bullets above, one
   function each; the result is sorted so the same input gives the same list. Tests: a table per rule; a property test that
   `apply(reconcile(x)) == x'` and `reconcile(x') == []` (twice equals once); a crash simulation (`tests/land/test_queue_crash_sim.py`)
   that cuts the sequence eject, rebuild, merge at every step boundary with a fake clock and fake pids and asserts that one reconcile
   leaves every item with a live build for its current QueueKey or in `pending`, and no ref or worktree that no entry names.
2. *The record and its store (after the contracts move to packages/kernel).* **One document per repo**, not a row per entry: the queue is
   tens of items, and a document replace is already one SQLite transaction (`RowDocs` on the `kv` table, prefix `queue:`, next to
   `queue-state:` of section 2). No new table, no schema file. `QueueDoc(V=1)`: `entries` (the planner's `Entry` plus the QueueKey
   fields `base`, `ahead`, `check_set`, and per build `pid`, `start_id`, `lease_expires`, `worktree`), `in_flight` (the AIMD value),
   `last_base`. The freeze flag and incidents stay in `QueueState` (they have a different writer and lifetime). **Events are not in the
   document:** ejections and resets are engine-log rows (the existing log), flake rows are their own `DocSet` of the last 30 days. The
   single writer is the runner thread (`QueueRun` gets one `on_change(entries)` callback that replaces the document); the dashboard and
   `tl doctor` only read. Revisit the document shape if a queue ever holds more than a few hundred entries. This is the schema/family
   decision the bead asks to record against sqlite-store-plan.md.
3. *Wiring.* `QueueLand.run` calls `reconcile` once before it builds anything and applies the actions through the existing ports (git,
   spawner, forge); `tl doctor` calls the same function and prints the actions without applying them (`app/doctor/queue.py`). A
   merged-but-not-recorded PR is `AssertAndRecord`: the tree assertion first (`TreeGuard.verify`), then `tl land`; the merge is never
   repeated. Dark: nothing runs unless `engine.land_queue` is on.
Files are out: the interim JSON file of the first paragraph is dropped, because factory.db is available now and a file repeats the slot-grant races.

**Visibility** (extends dash-spec.md section 4 Floor; names are suggestions):
- Floor: a **land lock** segment on the bead line while the item holds the lock (gate runs outside it, so the segment is short and
  honest); a new row group "Queue" with one row per gate in flight (gate running, waiting on culprit, green waiting for merge).
  Colours follow the colour contract: red tint for a failed gate, grey hatch for waiting behind an item, teal live.
- Landing strip: one strip under the Floor, queue order left to right, each PR as a chip: gate state, wait so far, a marker for ejected.
- Board: card badge `queued #n`, `ejected: reason`; Decisions tab lists asks from section 7 and 8.
- Numbers: queue depth, wait per PR (enter to merged), ejections by reason, **landing lag** = bead `done` timestamp to
  `merged to main` timestamp, per bead and p50/p90.
Dash slices stay owned by the dashboard bead owners; bead (h) supplies the data contract and one view.

## 10. Slots

Today `land_mode` has `pr` (the loop opens a PR; `pr_land.py` never merges) and `push` (the lander merges under the land lock, up to
`land_optimistic_tries = 2`, config.py:191).

- Queue applies to `pr` mode and `land-stack` only (decision 2). Push mode keeps its optimistic path; it is an out-of-queue pusher
  (section 8), so pairing it with a live queue costs resets. One mode per repo.
- **Free the slot at "enqueued with its own gate green"**, not at merge. The agent has nothing left to do: its work is judged, and if the
  queue ejects it for its own failure the bead returns as a new dispatch (slot-grant's atomic grant, a resumed worker). Holding the slot
  to merge parks slots on a wait the queue is designed to hide (goal 1, 2).
- Risk: freeing early starts more beads, which means more PRs, deeper queue, more drift. Counter: back-pressure. When
  `queue_len >= 2 * G` (default) the dispatcher does not start new beads for that repo. [Threshold is a guess; bead (m) tunes it.]
- ❌ Rejected: free at merge. Idle-slot hours are the problem statement.
- ❌ Rejected: free at PR open (before the own gate). The own gate is the agent's feedback loop (stages.md); leaving earlier moves
  failures from a loop the agent owns to a queue it does not.

## 11. Bead dependencies as scheduling gate (decided) and six edge cases

Rule: a bead's `blocked-by` edge means the child is not dispatched, not enqueued and not merged until the parent is **merged to main**.
Child branches off main, unaffected by the parent's branch. The queue therefore never holds a child ahead of a parent it needs. Evidence:
no surveyed system infers merge order from a tracker graph; order comes from ancestry or an explicit declaration on the change [I, from
deps-topology research]. Tracker edges are intent, not code fact. Beads' own dependency semantics were not re-checked [unverified].

1. **Cycle.** Reject at dep-add (a check in the `tl task create/dep` path, section 16 bead (j)); the lander re-checks at enqueue and fails
   loud with the cycle. Never deadlock the queue. Zuul rejects cycles by default and makes them opt-in [V]; we have no opt-in.
2. **Parent abandoned** (closed unmerged, bead reopened or cancelled). Child goes `blocked(parent-abandoned)` after a timeout, one ask
   to Denis: re-parent, drop the edge, or cancel. Never waits forever.
3. **Parent squash-merged, child already started on old main.** Child branch is not stacked, so there is no duplicate-commit problem.
   Update the child by merging main in (plain push). Clean merge: continue. Conflict: re-dispatch the agent with the parent's merged
   diff as context (the squash commit's diff). Evidence for the message: telling an agent about the concurrent change recovered 82% of
   semantic collisions in constructed tasks [V abstract; constructed rate, not real-world].
4. **Bead graph vs code graph.** Edges and touched code disagree both ways. Edge without overlap: honour the edge anyway (order is intent).
   Overlap without edge: for every open PR pair, compute touched paths from the diff and `git merge-tree` the pair; any overlap (path or
   textual conflict) makes the later PR **not speculated past** the earlier one: it waits for the earlier to merge before its gate
   starts (cost: less parallelism; gain: no certain-to-be-wasted build). Plus **path claims on the bead**: the bead's `## Touches` (in all
   211 briefs, read by nobody: stages.md) is recorded as a claim and shown on Board/Floor; in v1 the claim only feeds the queue overlap
   rule and the display, never delays dispatch. stages.md rule 3 said drop Touches (5 of 73 overlapping pairs shared a planned file); that
   argues against a dispatch scheduler, not against using it as a predictor here. Open question 3 (section 15).
5. **Parent changes an interface after child started.** Child merges clean but breaks on main. After the parent merges, the child's gate
   runs on current main (the queue does this by construction: `Q(N)` includes everything ahead). If red, the agent gets: failing check
   plus the list and diffs of what merged since its base. Post-merge main gate is the backstop. Real-PR rate is low (1 in 834 Django PR
   pairs [V abstract]) but near-certain when two agents change one interface [V, constructed].
6. **Partial landing.** Parent merged, child stuck or failed: gate is "merged to main", not "lands atomically". The parent sits on main
   behind its flag (dark). If the child fails for good: a follow-up bead is filed; revert the parent only when a flag cannot isolate it.
   Also: no branch deletion at merge (`gh pr merge` runs without `--delete-branch`, code map), so a parent branch going away cannot
   close a child [S, GitHub user reports].

## 12. Why not (and the condition to revisit)

- **Epic or integration branches.** Fowler's feature-branch critique applies with a bigger feature: integration deferred, drift grows with
  branch age, the final merge is the big uncertain one [V]. DORA correlates trunk-based practice with delivery performance, fewer than
  three active branches, hours-long branches [V; correlational; the 2.3x figure is secondary and unverified]. An epic branch also needs its
  own queue and CI. Revisit if: a feature cannot be made dark behind a flag and must change an interface in several PRs atomically; then
  only an hours-lived branch for 2-3 PRs, merged through the queue as one item.
- **Stacked PRs.** Squash leaves children with stale commits and artificial conflicts (restack, `rebase --onto`) [S]; retarget can
  close children [S]; most tools need force-push for restack, which is out. Revisit if: queue wait per PR p90 exceeds the work time
  of the child *and* the parent is long-lived; even then use the queue ref, not a PR.
- **Merge-commit landing.** Would make the landed commit equal the tested merge commit with no assertion (what GitHub's group branch
  is [V]). But history becomes N merge commits plus N PR commits, breaks one-commit-per-bead and the lander's `already` check, which
  reads the bead id off the last subject (rewrite-land.md M-227). Revisit if: the post-land assertion fires twice (open question 1).
- **Rebase-update.** Rewrites head SHAs, needs force-push (decided out), invalidates every SHA-keyed result and `--match-head-commit`
  evidence. Merging main in costs a noisier branch and nothing the squash cares about.
- **Uber build-target-hash conflict analysis, probabilistic speculation.** Uber's analyzer needs a build graph and an ML speculation
  engine trained on 100k+ changes; production since 2018 across 6 monorepos, tens of thousands of changes a month [V 2025 paper], builds
  per change still 1.85 to 2.57 [V]. We have a handful of PRs a day [I] and no target graph; touched-path overlap (section 11 edge 4) is
  the cheap shadow of it. Revisit if: queue depth is regularly >6 and the p50 wasted ratio stays above 0.5 with AIMD at floor; then
  commutativity (Uber BLRD [V]) is the first thing to try, not the predictor.
- **Aviator "merge everything up to the completed draft"** and **GitLab "merge without restarting"**: untested merges by design [V].
  Violates section 2.

## 13. The five first-implementation failure modes

| # | Failure | Test or ratchet that catches it |
|---|---|---|
| 1 | Tested tree != landed tree (rebase/squash after test; main moved between test and push; merge bases differ) | (a) property test over random PR sets: `merge-tree` prediction == real squash on local git; (b) mandatory post-land assertion in every land test, deleting it fails a rules test (ratchet: `tests/rules` greps that `merged()` calls `assert_landed_tree`); (c) fault injection: main moved by a fake third party between prediction and merge -> expect "raced" incident, not silence |
| 2 | Stale result reused (base moved, force-push, config change; QueueKey incomplete) | table-driven test over every row of section 4: mutate one input, expect miss; a key-fields ratchet: adding a field to the Result without adding it to QueueKey fails (mirror of the RunKey rule) |
| 3 | Flake evicts a good PR and resets the rest | simulation with scripted flaky test at p = 0.1, 0.3: assert zero innocent ejections when retry+main-check is on; control run with the policy off must break it (as slot_sim's control does, slot-grant.md (c)) |
| 4 | Crash leaves half-reset state | crash-injection at every step boundary of eject/rebuild/merge (fake clock, fake processes, as `tests/slots/test_slot_sim.py`); invariant: after one reconcile pass every item has a live build for its current QueueKey or is `pending`, no orphan refs/worktrees; reconcile twice == once |
| 5 | Re-speculation cost spiral (jump, eject, base move cancel work repeatedly) | simulation metric `wasted_gate_s / useful_gate_s`; CI ratchet that the replay of the recorded attempts (section 14) stays under the committed bound; a unit test that W halves and never drops below 1 |

All five need a model of the queue as a pure state machine (items, builds, events -> actions). That is the design constraint: logic in
a pure function, effects (git, spawner, forge) behind ports, the reconcile loop and the simulator calling the same function. The slot
watchdog and `slot_sim` are the template.

## 14. Extras

- **Day-one metrics** (from `LandTry` rows plus new queue events): queue wait per PR, gate seconds per build, ejections by reason, wasted
  gates and `wasted_gate_s`, flake score, landing lag. Whether `LandTry` rows are read anywhere today is unverified; bead (h) starts there.
- **Kill switch.** One config key, `land.queue = off | shadow | on`; `off` runs today's `land-stack` serial path unchanged. The key is
  read at the start of each queue tick; flipping it during a run finishes the current merge and stops. Each stage of rollout below adds
  no code path that `off` cannot reach.
- **Shadow mode.** The old path lands; the queue builds and gates in parallel for the same PRs and writes what it *would* have done
  (order, ejections, trees, waits) as events. Comparisons: its predicted tree vs the tree that actually landed (invariant check with no
  risk), and its wait vs actual. Shadow gates cost CI; run them niced and only for PRs enqueued by `land-stack`.
- **Simulation harness.** land-speed.md records only aggregates for the 84 attempts (46 landed, 25 gate-red, 7 conflict, 6 head-moved),
  not the per-attempt timeline. The raw rows (arrival, gate seconds, outcome) are the `LandTry` rows [unverified that they survive].
  Harness: replay arrivals and outcomes through the pure queue model with a fake clock, output the metrics above for G = 1, 2, 4 and AIMD,
  and compare with the recorded serial result. Policy changes to G, cap, retry or timeouts must show their replay delta (Uber's simulator
  [V]).
- **Staged rollout.** shadow -> G = 2 -> AIMD (cap 4) -> batching only if queue depth regularly >3 -> done. Gate to advance: replay and live
  metrics within bounds, zero invariant incidents for a week of landed PRs [week is a guess].

## 15. Decisions (were open questions; Denis, 2026-11-07)

1. **Queue commits: keep `gh pr merge --squash`.** Fast-forward the tested commit only if the tree assertion fires twice. Why: squash
   keeps one commit per bead and the PR shows merged; fast-forward bypasses the merge record and branch protection. The assertion is
   the evidence that decides, so no guess now.
2. **`land_mode` push is not in the queue.** One mode per repo; push mode counts as an out-of-queue pusher. Why: two writers to main
   is the "raced" class by definition.
3. **Path claims: display and queue rule in v1.** They may delay dispatch only within one epic, after a month of overlap data. Why:
   stages.md found 5 of 73 pairs overlapped; a scheduler on that is a cost with no measured gain.
4. **Lock main, lightweight** (revised same day: Denis prefers lightweight over GitHub rules): a ruleset against force-push and deletion
   (applied), a pre-push judge that refuses unmarked pushes to main, and `tl doctor` failing on drift (section 8.1). No required PR or
   checks: push mode and release push to main directly. A full queue-only lock with owner bypass remains an option for later.
5. **Gates in flight: floor 1, cap 4.** Cap 3 if the wasted-gate ratio exceeds 0.5 in shadow. Why 4: the current `--jobs` default; at p = 0.3
   deeper builds mostly die. "Window" is retired for this (terms in section 6, docs/glossary.md).
6. **Free the executor slot at enqueued-green**, with back-pressure at queue length 2 x gates in flight. Why: idle slots are the problem
   statement; back-pressure stops the faster slots from growing drift.
7. **Tree mismatch: no blind auto-revert; an agent repairs it, a human only after two failed repairs** (section 2.1). Why: the queue
   still verifies the repair; a person is slower and is not the dear resource to spend on a recoverable event.
8. **Quarantine: none in v1 or v2** (section 7). Flake policy instead: retry once, check on clean main, flake score, auto fix bead at
   more than 3 rows a week, v2 owner-approved skip with a 7-day expiry. Why: quarantine hides failures; fail early, fail often.
9. **Required-check set: the profile is authoritative**; `tl doctor` fails on drift against GitHub, no warn-only phase (section 8.1).
10. **Stuck-head timeout: 2 x p90 gate seconds**, measured in shadow mode first; no number is committed before data.

## 16. Slices (beads under the epic "MQUEUE: speculative merge queue")

Epic tl-7s2f. Order: a, then b and l; c needs b and l; d, f, g need c; e needs d; h needs g; i needs c, g, l; j needs c; k needs d, g;
m needs i, e, k, h; n (guard rails) needs k; o (repair) needs d, g, l; p (glossary) needs e; q (flake fix beads) needs f; r (skip registry, v2) needs q, m. tl-7s2f.3 keeps its interim freeze-plus-ask until o lands. The config key `land.queue = off|shadow|on` (kill switch) lands in c; m proves it.

| Bead | Slice | Deps |
|---|---|---|
| tl-7s2f.1 (a) | experiment: squash tree == queue-built tree, property test + one real GitHub pair | none |
| tl-7s2f.2 (b) | QueueKey + Carry `queue_parent` mode | a |
| tl-7s2f.3 (l) | tested-tree == landed-tree assertion in today's land-stack | a |
| tl-7s2f.4 (c) | queue ref builder, gate on main + ahead, `land.queue` key | b, l |
| tl-7s2f.5 (d) | eject, rebuild only behind, cancellable gates | c |
| tl-7s2f.6 (e) | AIMD gates in flight, wasted-gate accounting | d |
| tl-7s2f.7 (f) | flake policy and score log | c |
| tl-7s2f.8 (g) | durable state + reconcile loop | c |
| tl-7s2f.9 (h) | metrics, Floor land-lock, Landing strip, Board | g |
| tl-7s2f.10 (i) | shadow mode + replay harness | c, g, l |
| tl-7s2f.11 (j) | bead-dep gate, cycle check, overlap check, path claims | c |
| tl-7s2f.12 (k) | hotfix, freeze, check-set hash, timeouts | d, g |
| tl-7s2f.13 (m) | staged rollout, kill switch proof, slot back-pressure | i, e, k, h |
| tl-7s2f.14 (n) | guard rails: pre-push judge refuses unmarked pushes to main, `tl doctor` fails on ruleset or hook drift (section 8.1) | k |
| tl-7s2f.15 (o) | recovery flow: repair agent on a tree mismatch (section 2.1) | d, g, l |
| tl-7s2f.16 (p) | glossary alignment: gates in flight replaces window in code, config, views | e |
| tl-7s2f.17 (q) | flake escalation: auto fix bead at more than 3 rows a week | f |
| tl-7s2f.18 (r) | v2: owner-approved test skip, 7-day hard expiry | q, m |
The `## Touches` paths in the beads are best guesses from the code map; each bead's first step confirms them.

## Unverified (collected)

- GitHub's own account of the 2026-04-23 incident; the figures (4 h, 658 repos, 2,092 PRs) are from secondary reports.
- Mergify's TLA+ invariants; Zuul, GitLab, Mergify, Tide numeric limits and defaults (Zuul window 20, floor 3, 20 parallel pipelines, 128 checks).
- GitHub's server-side squash equals local `git merge --squash` on the experiment's cases (not tested against GitHub).
- Criss-cross merge bases and renames in the equality of queue tree and landed tree.
- Spawner cancel API; `authorization.results` base handling for a queue worktree; whether checks set `retry`; whether `LandTry` rows are
  surfaced or retained; sqlite-store-plan family and schema; whether this repo has branch protection or required checks on GitHub.
- All thresholds marked as guesses in sections 6, 8, 10, 14. The (1-p)^d survival figure is an inference.
- Beads' own dependency semantics (cycle rejection at dep-add; `blocked-by` direction).
