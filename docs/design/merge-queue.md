# Merge queue (MQUEUE): speculative, serial in meaning, parallel in execution (design only, 2026-11-07)

Verdicts: ✅ do, ❌ refuse. Tags on external facts: [V] read in a primary source, [S] secondary report, [I] inference. Anything marked
`[unverified]` was not re-checked: numeric limits and defaults of other systems came from lossy page summaries and must be re-read before
they are copied into config. Inputs: land-speed.md, slot-grant.md, stages.md section 6, dashboard/dash-spec.md section 4, and the code under
`src/taskloop/app/land/` (stack.py, stackgate.py, carry.py, lander.py), `contracts/runkey.py`, `app/checks/cache.py`.

Decided before this doc, not reopened: bead deps are a scheduling gate only (no child starts or merges before its parent is on main); child
PRs always branch off main; no stacked PRs; no epic or integration branches by default (trunk, dark flags, queue); branches are updated by
merging main in (plain pushes, no force); landing stays squash, one commit per bead.

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
commit is the main the gate assumed. Everything else (depth, AIMD, ejection) is allowed to be wrong in cost; this one is not allowed to be
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
- Parent as expected, tree differs ("corrupt"): freeze the queue (no merge, no new gate starts), incident row, one ask to Denis with
  both tree ids and the PR. No automatic revert in v1: a revert is a second write to main on the same broken path, and the cause may be
  an out-of-queue push, not the squash.
- ❌ Rejected: trusting `--match-head-commit` plus the gate. Head match says nothing about the base; this is the GitHub failure shape.
- ❌ Rejected: fast-forwarding main to the queue commits (bors style) in v1. Queue commits are already one per PR, so it would meet "one
  commit per bead" and the invariant by construction. But it bypasses `gh pr merge`: the PR would not show merged (queue commits are not
  the PR's commits), branch protection and merge record change. Revisit when the assertion fires more than once (section 12).

## 3. Queue model

### 3.1 Semantics
Serial in meaning: PRs land in queue order, each on exactly the main it was tested on. Parallel in execution: up to W gates run at once
(W = window, section 6). Candidate N is gated on `main + PR1..PR(N-1) + PR(N)`, assuming 1..N-1 pass. If one fails the assumption is
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
in `base` only. That is exactly `earlier_pass` (carry.py:325: key differs only in base), except Carry today proves the pass still holds by
closure comparison. Here we have a stronger fact: the parent tree is identical.

Change (about 30-60 lines in carry.py and stackgate.py, from the code map): a second carry mode `queue_parent`. A receipt whose `key.base`
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
- Not covered by the experiment: criss-cross histories with several merge bases (recursive/ort picks a synthetic base; the queue chain and
  the real main may pick differently), renames, GitHub's server squash. Layer 1 of section 2 exists for these; bead (a) re-runs the
  experiment with a property test (random edits, 1,000 cases) and one real PR pair against GitHub on a throwaway repo before bead (c)
  starts.

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
| profile change PR itself (owner path) | barrier: window 1 around it, everything behind rebuilt |

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

## 6. Depth and window

- **Start at W = 1** per repo: the queue then equals today's serial behaviour with the new invariant and bookkeeping. This isolates
  correctness bugs from cost-tuning bugs.
- **AIMD, Zuul style** [V for the shape; defaults unverified]: Zuul grows linear on merge (+1) and halves on failure, window 20, floor 3
  by default [unverified]. Ours: floor 1, +1 per merged PR, halve (round down, min 1) per *own gate failure or conflict eject*, not per
  flake or infra stop. Cap configurable, default 4 (the current `--jobs` default, cli/land_stack.py:102). Per repo; one queue per repo in
  v1, so a flaky repo does not shrink another's window (Zuul isolates per change queue [V]).
- **Why depth is bounded.** If a gate fails with probability p, the chance a depth-d speculative build survives is about (1-p)^d [I,
  not from a source]. land-speed.md shows 25 of 84 attempts gate-red, about 30%. Much of that is owners running `just test` not
  `just check` (code map), which the queue does not change for pre-queue red but which should fall once the owner gate is the same check
  set. At p = 0.3 and d = 4 only 24% of the deepest builds survive [I]: a cap of 4 is already generous, and AIMD is what will find the
  real number. Uber still builds ~2x per change after tuning [V]; expect waste.
- **Wasted-gate accounting** (on every ejection and every window change): `wasted_gate_s` = seconds of gates that were cancelled or
  invalidated; `useful_gate_s` = seconds of gates whose result was used. Ratio over the last 20 merges above 0.5 holds W (no increase)
  [threshold is a guess, tunable]. Each wasted build records its cause (culprit ahead, base moved, head changed, config change).
- **Batching only when depth regularly exceeds 3** (median queue length over a week). Then: group the front K PRs as one build,
  on red bisect by halving, never retest the last (if all earlier parts pass, the last is the culprit; Mergify trick [V]). Batch only
  PRs of equal priority and no overlap (section 11). Costs: loses per-commit greenness, lengthens attribution [V Graphite caveat].
  Not v1: single owner, volume is a handful of PRs a day [I].
- ❌ Rejected: starting at a deep window. One bug in section 2 or 4 would turn into mass wasted CI and mass ejections at once.

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

- **No automatic quarantine in v1.** Reasons: (1) a quarantined test is a hole in the gate nobody sees, and nothing in the fetched sources
  documents quarantine inside a queue [unverified]; (2) no registry with owner, expiry and un-quarantine exists (M, ~150 lines per
  code map); (3) retry plus main-check already removes the harm that matters (innocent ejection) without removing coverage. Revisit
  when one test appears in more than 3 flake rows a week (section 12).
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
  explicit required-check config on drafts [V]). A doctor check compares the profile's set with the repo's protection rules via `gh api`
  and warns on difference. Whether this repo has required checks on GitHub at all is unverified; if none, the hash still keys the queue.
- **Timeouts.** Per gate (default 2x the 90th percentile of recent gate seconds for that repo, floor from config) and stuck-head (the
  item at queue head with a green gate that cannot merge for N min): per-gate expiry gives `stuck`, retry once; head stuck gives an
  incident row, ejection of the head with reason `stuck`, rebuild behind. Without these a hung gate blocks everyone (GitHub, bors, Aviator,
  GitLab all have one [V]). Shopify's lesson: do not eject for a *pending* check, wait for it [V]; our timeout is on running time, not
  on pending.

## 9. Durability, reconcile loop, visibility

**State that must survive a crash:** queue list (PR, bead, head SHA, state, position, entered_ts), builds (QueueKey, `Q` sha, tree,
state, worktree path, owner pid + start_id + lease expiry, started, finished), event log (ejections, resets, flake rows), flags (freeze,
window, last base_sha).

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
- window state not matching the last events (recompute).
Zuul's 2024 orphaned-changes report [S] and Tide's partial-merge TODO [V] are the failure shapes. Pattern is the slot watchdog
(slot-grant.md (b)): a pure function plus a heal, one incident row per episode.

**Visibility** (extends dash-spec.md section 4 Floor; names are suggestions):
- Floor: a **land lock** segment on the bead line while the item holds the lock (gate runs outside it, so the segment is short and
  honest); a new row group "Queue" with one track per build window slot (gate running, waiting on culprit, green waiting for merge).
  Colours follow the colour contract: red tint for a failed gate, grey hatch for waiting behind an item, teal live.
- Landing strip: one strip under the Floor, queue order left to right, each PR as a chip: gate state, wait so far, a marker for ejected.
- Board: card badge `queued #n`, `ejected: reason`; Decisions tab lists asks from section 7 and 8.
- Numbers: queue depth, wait per PR (enter to merged), ejections by reason, **landing lag** = bead `done` timestamp to
  `merged to main` timestamp, per bead and p50/p90.
Dash slices stay owned by the dashboard bead owners; bead (h) supplies the data contract and one view.

## 10. Slots

Today `land_mode` has `pr` (the loop opens a PR; `pr_land.py` never merges) and `push` (the lander merges under the land lock, up to
`land_optimistic_tries = 2`, config.py:191).

- Queue applies to `pr` mode and `land-stack` only in v1. Push mode keeps its optimistic path; it is an out-of-queue pusher (section 8),
  so pairing it with a live queue costs resets. A repo picks one mode.
- **Free the slot at "enqueued with its own gate green"**, not at merge. The agent has nothing left to do: its work is judged, and if the
  queue ejects it for its own failure the bead returns as a new dispatch (slot-grant's atomic grant, a resumed worker). Holding the slot
  to merge parks slots on a wait the queue is designed to hide (goal 1, 2).
- Risk: freeing early starts more beads, which means more PRs, deeper queue, more drift. Counter: back-pressure. When
  `queue_len >= 2 * W` (default) the dispatcher does not start new beads for that repo. [Threshold is a guess; bead (m) tunes it.]
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
  the cheap shadow of it. Revisit if: depth is regularly >6 and the p50 wasted ratio stays above 0.5 with AIMD at floor; then
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
  Harness: replay arrivals and outcomes through the pure queue model with a fake clock, output the metrics above for W = 1, 2, 4 and AIMD,
  and compare with the recorded serial result. Policy changes to W, cap, retry or timeouts must show their replay delta (Uber's simulator
  [V]).
- **Staged rollout.** shadow -> W = 2 -> AIMD (cap 4) -> batching only if depth regularly >3 -> done. Gate to advance: replay and live
  metrics within bounds, zero invariant incidents for a week of landed PRs [week is a guess].

## 15. Open questions for Denis (each with a recommendation)

1. **Fast-forward queue commits instead of `gh pr merge --squash`?** Recommend no for v1 (section 2); yes if the assertion fires twice.
2. **Include land_mode push in the queue?** Recommend no; one mode per repo; push mode is an out-of-queue pusher.
3. **Do path claims ever delay dispatch?** Recommend: only for beads in the same epic, after a month of overlap data; v1 display and
   queue rule only.
4. **Lock main to queue-only pushes (branch protection)?** Recommend yes once shadow shows clean, with a hotfix bypass for the owner.
   Removes the "raced" class; costs the direct-push escape. Unverified: whether branch protection is enabled on this repo.
5. **Window cap default 4?** Recommend 4 with floor 1; AIMD finds the truth. Lower to 3 if wasted ratio >0.5 in shadow.
6. **Free slot at enqueued-green (section 10)?** Recommend yes with the `2 * W` back-pressure.
7. **Auto-revert on a "corrupt" mismatch?** Recommend no in v1: freeze and ask.
8. **Quarantine in v2?** Recommend yes behind an owner-approved registry with expiry, when one test exceeds 3 flake rows a week.
9. **Where is the required-check set authoritative: profile or GitHub?** Recommend profile, with a doctor warning on drift.
10. **Stuck-head timeout value.** Recommend 2x p90 gate seconds, measured in shadow; no number committed before data.

## 16. Slices (beads under the epic "MQUEUE: speculative merge queue")

IDS_PLACEHOLDER

## Unverified (collected)

- GitHub's own account of the 2026-04-23 incident; the figures (4 h, 658 repos, 2,092 PRs) are from secondary reports.
- Mergify's TLA+ invariants; Zuul, GitLab, Mergify, Tide numeric limits and defaults (window 20, floor 3, 20 parallel pipelines, 128 checks).
- GitHub's server-side squash equals local `git merge --squash` on the experiment's cases (not tested against GitHub).
- Criss-cross merge bases and renames in the equality of queue tree and landed tree.
- Spawner cancel API; `authorization.results` base handling for a queue worktree; whether checks set `retry`; whether `LandTry` rows are
  surfaced or retained; sqlite-store-plan family and schema; whether this repo has branch protection or required checks on GitHub.
- All thresholds marked as guesses in sections 6, 8, 10, 14. The (1-p)^d survival figure is an inference.
- Beads' own dependency semantics (cycle rejection at dep-add; `blocked-by` direction).
