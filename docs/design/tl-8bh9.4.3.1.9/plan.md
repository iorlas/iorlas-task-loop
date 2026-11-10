# Keep the tracker claim's lease alive while a step runs

Task: tl-8bh9.4.3.1.9 (proposed id; answers the owner question in [.4.3.1.2](../tl-8bh9.4.3.1.2/plan.md) section 5,
"The tracker claim's lease"). Design proposal, 2026-11-10, revision 1. Nothing here is built or run. Owner decision taken
as given: **heartbeat the claim, as part of the tracker contract, in the background while the factory runs a step**; this
note picks the pattern and the placement. Read: CLAUDE.md, AGENTS.md, glossary, .4.3.1.2, .4.3.1.4, .4.3.1.8,
`src/taskloop/{attempt_entry,plan_admit,plan_repeat,plan_launch,plan_session,plan,composition,cli_plan,tracker}.py`,
`tests/rules/test_policy.py`, beads_client 0.1.0 and any_agent 0.4.0 in `.venv`, `bd` 1.3.1 help texts.

## 1. Facts (verified 2026-11-10 unless marked)

- **The library already has the call.** `beads_client.Bd.heartbeat(bead) -> None` runs `bd --actor A heartbeat <id>
  --json` through `Bd.call` (the shelf's one `Runner`, `subprocess_runner`, lock retry with `Bd`'s injected `sleep`) and
  raises `BdError` on any failure. `Bead.lease_expires_at` is read by `Bd.show`. `Bd(timeout=None)` is the default: a hung
  bd waits forever unless the caller passes `timeout`. No shelf change is needed for this slice.
- **The TTL is fixed and not ours to set.** `bd update --help` has no lease or TTL flag; `bd config --help` lists only
  `claim.pools` under `claim.*`; the binary names an internal `issueops.LeaseTTL` but no flag, config key or `BEADS_*`
  variable for it was found (searched help texts and binary strings, not bd's source). Measured: lease expiry =
  claim time + 300 s.
- **Measured outcomes** (scratch tracker in the scratchpad, actor A): own heartbeat -> exit 0,
  `{"status":"heartbeat"}`, ~0.25 s wall; another actor's heartbeat -> exit 1 `issue already claimed by A`; after
  `unclaim` -> exit 1 `issue not claimable: <id> status open`; after `close` -> exit 1 `... status closed`. All three
  failures classify (`beads_client.classify.error_of`) as `BdError(kind="not_claimable")`. Earlier round (.2): a
  heartbeat on a lapsed, unreaped lease succeeds and re-arms it.
- **Not measured (stated, not verified):** the words after a real `bd reclaim` (needs a lease lapsed past the 10-minute
  grace). `reclaim` sets status open and clears the assignee, so the `status open` case above is expected; the design
  treats every `not_claimable` / `precondition` alike, so the exact words do not matter.
- **Lifetime.** The entry process (`python -I -m taskloop.attempt_entry`) spans exactly one step attempt: identity check,
  `execute` (the agent), up to 3 publication retries, one verification, one log line, exit. Between steps (captured,
  awaiting `tl plan verify` or a repeating `tl plan start`) **no factory process runs**. A repeat takes the held claim
  over and claims nothing (`admit_repeat` has no tracker call).
- **The entry does not know the tracker.** `plan_attempt` stores `adapter='beads', backlog, task_id`, not the tracker
  root; `Launcher.launch(backlog, task_id)` and the entry's argv carry no root either.
- **any_agent's `RunHooks.beat`** exists: called from `Watchdog.touch` on the output pump thread, at most every 30 s,
  only when the worker prints. Codex's harness allows 3600 s of silence and has shown rollout gaps up to 2,298 s.

## 2. Patterns compared

| pattern | covers a running step | covers the idle gap | cost / risk | verdict |
|---|---|---|---|---|
| (a) keep-alive thread in the entry | all of it: agent, publish retries, verify | no | one daemon thread, one bd call per 100 s | **chosen** |
| (b) renew on `RunHooks.beat` / ref | only while the agent prints; never during publish/verify | no | a 2,298 s silent gap lapses the 300 s lease; a bd call (unbounded without a timeout) on the pump thread stalls output draining; widens `plan.py` to the tracker | reject |
| (c) longer lease at claim time | yes, if it existed | only if huge | bd 1.3.1 offers no TTL option; a huge TTL disables the reaper for real dead workers | not available |
| (d) renew in CLI verbs (`plan start/show/verify`) | no (verbs end before the step) | only when a person happens to run one | `show` must stay a read; `verify` is a Git step, not a claim owner | reject (start is covered by (a)'s first beat) |
| (e) separate resident daemon | yes | yes | a second long-lived process with its own lifecycle, registration and liveness, i.e. another scheduler; nothing in the foundation runs resident | reject |

**Why (a).** It is the textbook lease-holder pattern (bd's own help: "a worker keeps its claim alive by heartbeating
faster than the TTL"): the process that holds the work renews it on a timer independent of what the work prints, and
stops renewing when it stops. A thread inside the entry dies with the entry, so a dead entry stops renewing, which is
exactly what the lease is for. Nothing new is scheduled or registered.

## 3. Design of (a)

**Contract (factory side).** In a new module `src/taskloop/claim_lease.py` (~90 lines, no IO of its own):

```python
type Beat = Literal["held", "lost", "unrenewed"]          # one renewal's outcome
type Heartbeat = Callable[[], Beat]                         # bound to one tracker root and task by composition
type ClaimWord = Literal["held", "lost", "unrenewed", "fault"]
LEASE_TTL_S = 300.0; BEAT_EVERY_S = 100.0; BD_TIMEOUT_S = 30.0   # TTL/3; one bd call (no lock retry) per beat, capped
```

`Heartbeat` joins the existing `Claim` / `Unclaim` aliases (plan_admit.py) as the third tracker operation; the
narrow-port style already used there is kept rather than introducing a `Claims` Protocol class now.
`composition.tracker_claims(run)` returns all three (a frozen `TrackerClaims(claim, unclaim, heartbeat_for)` record,
replacing the tuple), `heartbeat_for(tracker_root, task_id) -> Heartbeat` building
`Bd(ACTOR, cwd=resolved_root, run=run, timeout=BD_TIMEOUT_S)` and mapping: return -> `held`; `BdError.kind in
{"not_claimable", "precondition"}` -> `lost`; an `other` error with bd's deleted-bead words (`resolving X: no issue
found matching "X"`, measured) -> `lost`; any other `BdError` (timeout, missing_binary, other, malformed, version) ->
`unrenewed`. composition.py stays the only module that constructs `Bd` (a new rule, section 5).

**`KeepAlive`** (in claim_lease.py): `__init__(beat: Heartbeat, stop: Stop, clock, interval=BEAT_EVERY_S)` where `Stop`
is a Protocol `wait(timeout: float) -> bool` and `set() -> None` (`threading.Event` satisfies it). Methods:
- `first() -> Beat`: one synchronous beat in the caller's thread (re-arms a lease that lapsed since admission).
- `run() -> None`: the thread body: `while not stop.wait(interval): record(beat()); if lost: return`. Every exception
  is caught and kept as `fault:<TypeName>` (as `SessionLatch` does), never raised out of the thread.
- `word() -> ClaimWord` under a `threading.Lock`: `lost` if any beat said lost; else `fault` if one faulted; else
  `held` only if at least one beat held and the lease cannot have lapsed; otherwise `unrenewed`. Lapse is judged
  conservatively by the injected clock: a held beat renewed no earlier than its start; at every beat's end, and again
  when the word is read at the end of the step, the time since the last held beat began must stay under `LEASE_TTL_S`.
  So one failed beat between held ones is not a lapse; two in a row then a held one reach the TTL (100 s cadence) and
  read as `unrenewed`.
- context manager `keeping(alive) -> Iterator[KeepAlive]`: starts `threading.Thread(target=alive.run, daemon=True)`,
  and in `finally` calls `stop.set()` then `join(BD_TIMEOUT_S + 5)`. Daemon, so a bd hung past its own timeout cannot
  hold the entry's exit.

**Entry (`attempt_entry.enter`).** Gains one injected parameter `heartbeat_for: Callable[[str, str], Heartbeat]`. Order:
DB exists -> attempt row (now with `tracker_root`) -> identity check (the entry is registered before this) ->
`alive.first()` -> **if `lost`: log `refused claim_lost`, return 1, the agent never starts** (owner Q1) -> `with
keeping(alive):` execute, publish retries, verify -> the log line gains `claim=<word>` as its last word. Current maximum
is 5 words (`status reason publish= then= verify=`), so 6 fits `plan_ops.ENTRY_WORDS = 6` and `WORD` already matches.
`enter` grows ~10 lines (now ~41, cap 80). The keep-alive thread touches no SQLite connection and no store: its only IO
is the bd process through the shelf runner; `KeepAlive`'s state is behind its own lock.

**Where the root comes from (decided here).** Admission stores the resolved tracker root:
`plan_attempt.tracker_root TEXT NOT NULL`, inserted by `plan_admit.py` (already the `INSERT plan_attempt` owner) and
copied by `admit_repeat` from the previous attempt; `Schema(version=6)`, an older factory.db refused loudly, no migration
(CLAUDE.md). Rejected: a fifth entry argv (the relaunch path in `plan_ops` and `PlanRepeat` have no root to pass, and a
fact the claim was taken at belongs with the attempt; the later release slice needs it for `unclaim` too).

## 4. Failure semantics (no automatic release, ever)

| when | beat says | entry does | final words |
|---|---|---|---|
| before the agent | held | run the step | `... claim=held` |
| before the agent | lost | refuse, agent not started, nothing released or re-claimed | `refused claim_lost` |
| before the agent | unrenewed | run the step (bd unreachable is not proof of loss; the thread keeps trying) | `held` once a later beat holds in time, else `unrenewed` |
| before the agent | unexpected exception | run the step with no renewal at all (the thread stops at once) | `... claim=fault` |
| while running | lost | stop beating; **the agent is not stopped**; publish and verify proceed | `... claim=lost` |
| while running | unrenewed for >= TTL | keep beating | `... claim=unrenewed` |
| while running | unexpected exception | stop beating | `... claim=fault` |

`tl plan show` prints the entry's last line through `last_entry` unchanged, so `claim=lost` / `refused claim_lost`
appear on its `Last entry:` line with no new reader. It is display only: no state is derived from the log (CLAUDE.md),
and nothing acts on it. For `refused claim_lost` the attempt stays `admitted` and `Next:` stays `start`; the GUIDE line
for it gains: "If the last entry says `claim_lost`, the tracker claim was taken back: check `bd show <task>`; re-claim it
by hand as `taskloop` before `tl plan start`, or leave it." While an entry runs, `plan show` cannot tell a loss
(the line is written at exit); see Q4.

## 5. The idle gap between steps (honest answer)

**Nobody heartbeats between steps, and this design does not pretend otherwise.** The lease lapses about 5 minutes after
an entry exits. What that costs: **nothing unless someone runs `bd reclaim` (or `bd update --force`) on that tracker**:
measured, a lapsed lease keeps the bead `in_progress`, assigned to `taskloop`, out of `bd ready`, and another actor's
`--claim` is refused. The simplest sufficient guarantee, built here: **every running step holds a live lease, and every
step begins by renewing it or learning it was lost before the agent runs** (the first beat re-arms a lapsed lease;
a reaped one is refused). The gap needs either no reaper on factory trackers or a reaper scoped away from factory claims;
`bd reclaim --exclude-label <label>` exists for that (owner Q2).

## 6. Tests, rules, caps (no subprocess anywhere in factory src or tests)

- `tests/plan/test_claim_lease.py` (new, ~150 lines, unit layer, no thread for the loop logic): `run()` called directly
  with a scripted `Stop` (its `wait` returns False n times, then True) and a scripted `Heartbeat`; one parametrized table:
  all held -> `held`, beats counted; lost at beat 2 -> `lost`, no third beat; two failures then held -> `held`; failures
  spanning `LEASE_TTL_S` on the fake clock -> `unrenewed`; a raising beat -> `fault`. Thread lifecycle, deterministic
  with no sleep: `keeping()` with a real `threading.Event` and `interval=1e9`: the thread blocks in `wait`, the `with` block
  exits, `set` wakes it, `join` returns, exactly zero thread beats (precedent: threads in `test_entry_store.py`).
- `tests/plan/test_entry.py`: `enter` gets a fake `heartbeat_for` (always held; existing cases unchanged but the line
  gains `claim=held`); new cases: first beat lost -> `refused claim_lost` and the fake run never called; a run whose fake
  heartbeat turns lost -> step completes, line ends `claim=lost`.
- `tests/plan/test_admit.py`: the existing `tracker_claims(Script())` wiring test extends to `heartbeat_for`: argv is
  `[exe, "--actor", "taskloop", "heartbeat", id, "--json"]`; replies with the measured bd 1.3.1 error JSON map to `lost`,
  code 124 to `unrenewed`. `Script` (beads_client.testing) is a fake runner: no process starts.
- Rules: WRITERS unchanged (the new column is written by the existing `INSERT plan_attempt` owner). New rule in
  `tests/rules/test_policy.py`, beside `git_writers`: `Bd` is imported only by `composition.py` (true today), so the
  tracker's write operations (claim, unclaim, heartbeat) have one wiring owner.
- Caps 400/80/800 hold: claim_lease.py ~90, composition.py 297 -> ~315, attempt_entry.py 165 -> ~185, plan_ops.py
  unchanged except one GUIDE string.

## 7. Docs that change with the code

- [.4.3.1.2](../tl-8bh9.4.3.1.2/plan.md) lease paragraph: keep the measured facts; replace the owner question with
  "Decided in [.4.3.1.9](../tl-8bh9.4.3.1.9/plan.md): the entry renews the lease every 100 s while a step runs; nothing
  renews it between steps."
- `cli_plan.HELD` becomes: "The slot and the tracker claim stay held; nothing here releases them. While a step runs its
  entry renews the claim's bd lease every 100 s; between steps nothing does, so a `bd reclaim` run on that tracker can
  revert the claim once its lease lapses: at the earliest about 5 minutes after a step ends (bd's default reclaim
  grace is 10 minutes, so about 15 minutes with a plain `bd reclaim`)."
- .4.3.1.4 entry log words: add `claim=` and `refused claim_lost`. Glossary: none (lease keeps its standard meaning).

## 8. Owner questions

- **Q1. A claim found lost before the agent starts.** Context: the first beat can learn the task was reaped or taken by
  someone else; running the agent then works on a task the factory no longer holds. Options: refuse before the agent
  (`refused claim_lost`), or run anyway and only record. **Recommendation: refuse**, and do not re-claim automatically.
- **Q2. The idle gap.** Context: between steps no process renews the lease; harmless today because nothing runs
  `bd reclaim`. Options: (i) accept and document "no reaper on factory trackers, or a reaper with `--exclude-label`";
  (ii) also label every factory claim now (one more tracker write at admission, one more thing to remove at release).
  **Recommendation: (i)**; add the label only in the slice that introduces a reaper.
- **Q3. A claim lost mid-run.** Context: owner said a failed beat is a recorded fault, not a kill. Confirming: the step
  completes, publishes and verifies; only the word `claim=lost` records it, and nothing releases. **Recommendation: yes.**
- **Q4. Live claim state in `plan show`.** Context: the loss is visible only after the entry exits. A later slice could
  add one `Claim:` line from a `bd show` read (assignee, status, `lease_expires_at`), which also covers the idle gap.
  **Recommendation: later, not in this slice**; it adds a tracker read to a command that has none.
- **Q5 (shelf, optional).** beads_client has a read contract (`TaskReadClient` + `task_read_contract` + a fake) but no
  claim contract. Asking the shelf for a `ClaimClient` Protocol (claim, unclaim, heartbeat with typed held/lost results)
  with a fake run against the same contract suite would let the factory drop its own mapping. **Recommendation: file it,
  do not wait for it**; the factory mapping above works on beads-client 0.1.0 as is.

## 9. Decisions recorded and as built (2026-11-10)

| question | decision |
|---|---|
| Q1 | Refuse before the agent: `refused claim_lost`, never re-claimed. |
| Q2 | (i): no reaper on a factory tracker, or a reaper scoped away from factory claims (`bd reclaim --exclude-label <label>`); the label is added only in the slice that introduces a reaper. The `HELD` banner states the idle gap. |
| Q3 | Yes: a claim lost mid-run is only `claim=lost`; the step completes, publishes and verifies; nothing releases. |
| Q4 | Later: no live `Claim:` line in `plan show` in this slice. |
| Q5 | File a shelf follow-up for a beads_client `ClaimClient` contract with a fake; do not wait for it. |

Built as sections 3-7 say, with these differences:

- `KeepAlive.renew()` is the one renewal, used by the entry for the beat before the agent and by the thread body; the
  entry then reads `word()` (there is no separate `first()`).
- A faulting renewal records only the word `fault` (the log's fixed vocabulary), not `fault:<TypeName>`.
- `word()` reports `held` only after a held beat, and judges a lapse at each beat and at the end of the step (section 3,
  revised after review).
- Each heartbeat is one bd call: `Bd(timeout=BD_TIMEOUT_S, lock_retries=0)` (bd's lock retry could stretch a beat to
  about 121 s). `keeping` joins for at most BD_TIMEOUT_S + 5 s; a daemon thread stuck past that may outlive the log line,
  and its late result changes nothing written (`word` is read under the lock). `tracker_claims(run, client=Bd)` takes
  the `Bd` class as a seam so a test checks that construction.
- bd's location overrides beat cwd (measured: `BEADS_DIR` sent a heartbeat to another tracker). beads_client's runner
  takes no environment, so as an interim both process entry points (`tl` and the attempt entry) drop `BEADS_DIR`,
  `BEADS_DB` and `BD_DB` from their own environment first (`composition.tracker_located`), before any thread or bd call;
  every bd child, the launched entry and the agent inherit that. `BEADS_DB` and `BD_DB` changed nothing in an embedded
  tracker (measured) and are dropped as named location overrides; the `BEADS_DOLT_SERVER_*` variables configure a
  server, not discovery, and are kept (not measured). Shelf follow-up: a beads_client `Runner` (or `Bd`) that takes the
  child environment, e.g. `subprocess_runner(argv, cwd, timeout, env=...)` and `Bd(..., env=...)`, so the factory can
  scrub per call instead of per process.
- **Known gap (owner-decided, not built):** `tl plan verify` does not check the claim. A verify run after the claim was
  reverted in the idle gap still commits and stores its verdict; only a later slice that reads the claim (Q4) or
  releases it would see that.
- `Heartbeat`, `HeartbeatFor` and `Beat` live in `claim_lease.py`; `TrackerClaims(claim, unclaim, heartbeat_for)` in
  composition binds them.
- `plan_attempt.tracker_root` has `CHECK(substr(tracker_root,1,1)='/')`; admission resolves the root once and uses that
  same value for the claim, the compensating unclaim and the stored row. The entry reads it with
  `PlanReads.tracker_root(key)` before its identity check (no new argv).
- `enter` is split into `_registered` (the refusals) and `_step` (execute, publish retries, verify) to keep the return
  count and length under the lint caps.
- Rule: `tests/rules/test_policy.py::test_only_composition_constructs_the_tracker_client` (no module but composition.py
  imports `beads_client.Bd`).
