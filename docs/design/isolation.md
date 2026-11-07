# ISOLATION: task-loop knows no harness; one thin Agent surface (tl-hwv5.1, SEAM-D)

Owner's rule (2026-11-05): task-loop has no clue which harness is underneath. The factory never calls `stop_pid`; it calls `stop` on
an agent. Principles: no optionality, no backward compatibility, no redundancy, isolation, injected classes.

Status: accepted by Denis, 2026-11-07. Epic tl-hwv5; children tl-hwv5.2 (A, process), .3 (B, harness), .4 (C, delegate internals).

## Where the code is today (read 2026-11-06, origin/main 99154664)

The epic was written before two things landed; the design starts from the tree, not from the bead text.

- delegate is a library in this repo (`src/delegate`); the engine imports `delegate.api` only (`docs/contracts/delegate-api.md`).
  `route.py` as a subprocess, `RouteDelegate` and `delegate_route.py` are gone. **Migration step 1 of the bead ("collapse the two
  launchers") is already done**: `adapters/runner.py` `ApiRunner` is the one launcher (a thread running `api.run`, `api.cancel` on a
  Handle).
- What still crosses the line, in order of weight: (a) the pid protocol: `api.Handle` (pid, pgid, start), `WorkerEnd.survivors`,
  `ApiRunner.obs/stop/outer` dicts, `worker_call.survivors/log_kill`, `parts_run.lock_worker(s)`, `EngineLock.route/workers`;
  (b) the live file: engine numbers it, `ApiRunner` polls it for `WorkerStarted`, dashboard tails it; (c) `api.status()` JSON read as a
  dict (`lane_status`, `role_status`) and the ~60-word pause table over `DelegateResult.stop` facts; (d) context size / resume /
  transcript knowledge (`context_size.py`, `FRESH_ABOVE_K`, `writer_family`, `TranscriptKind`); (e) `api.history()` rows read by
  `app/report/planner.py`.

## The surface

Two modules, both owned by task-loop's `contracts/` (the Protocol) and implemented by an adapter over `delegate.api`:

```
lanes() -> list[Lane]                  # name, usable: yes|no|unknown, why, until   (the one answer to "what is running or available")
start(call: Call) -> Agent             # Call = brief, schema, role, cwd, tools, budget, policy, resume ref
Agent.id                               # opaque
Agent.events() -> Iterator[Event]      # message | tool_call | tick | end ; pull, the engine ticks it
Agent.stop(graceful: bool) -> Ended    # returns only when the tree is proven dead; the only way to end an agent
Agent.outcome                          # done(data) | needs_owner(question) | failed(reason, retry_after) ; cost, tokens, ref
agents() -> list[AgentRef]             # agents still alive, for a task-loop that restarted
```

Everything else the engine does today with a worker is either an argument of `start` (budget, tools, role, policy) or delegate's.
`Agent.transcript()` is dropped from the first cut (judged below).

## Options, judged

| # | Option | Verdict | Why it fails / why it wins |
|---|---|---|---|
| 1 | Keep `api.run/cancel/Handle`, tidy callers | ❌ | The Handle IS a pid; every consumer keeps a survivor protocol. That is the bug (epic A), not a fix. |
| 2 | Push callback `on_event(Event)` | ❌ | Needs a thread per agent in task-loop and a lock around engine state; delegate already owns threads. Pull iterator fits the engine's own tick. |
| 3 | `Agent` as a Python class imported from `delegate.api` into the engine | ⚠️ works today, decays | Binds the engine to delegate's Python and version; breaks the moment delegate moves (DELEGATEHOME, tl-w7lt.37) or a remote executor lands (TOPOLOGY, tl-w7lt.38). |
| 4 | `Agent` is a **Protocol in task-loop `contracts/`**; one adapter implements it over whatever delegate is (in-process `delegate.api` now; a stdio/remote client later) | ✅ chosen | The engine imports the Protocol only. DELEGATEHOME either way (this repo, own repo, installed package) changes the adapter, never a consumer. A fake `Agent` replaces `procsim` for AI workers in engine tests. |
| 5 | stdio protocol between engine and delegate now | ❌ now | Right shape for a remote executor, wrong first step: a process boundary we just removed (api.py docstring). Option 4 leaves the door open at the cost of one adapter later. |
| 6 | Expose retry/reroute/resume to the engine as knobs | ❌ | "Optionality": the engine would keep a RetryPlan and the 60-word pause table, vendor knowledge copied. Outcome is terminal; the one extra fact is `failed.retry_after`. |
| 7 | `Agent.alive()` / `pid` for the engine lock | ❌ | A pid by another name. Liveness is `agents()`: delegate says which runs still go. |
| 8 | `Agent.transcript()` in the first cut | ❌ now | Needed by `tl trace` and the dashboard only; `events()` persisted by task-loop in its own run log (a log reader hides the storage) covers both. Revisit if a harness event is lossy. |
| 9 | Budget as `Agent` methods (`set_budget`) | ❌ | Policy the owner sets once per call: an argument of `start`. |
| 10 | Network probe stays in the engine | ❌ | delegate probes before a call already; the engine's `await_net` loop and `RouteProbe` go. |
| 11 | Compat shim: old and new surface side by side for a release | ❌ | No backward compatibility, no redundancy. Each step cuts over and deletes. |
| 12 | `stop()` returns at once, survivors reported | ❌ | Leaves the survivor protocol in the engine. `stop` returns when the tree is dead or raises `StopFailed(reason)`, which is `failed` (needs_owner), not a pid list. |

Open question answered by the design: **library vs protocol (tl-hwv5.1)**: neither is decided in code; the Protocol (option 4) makes the
answer a one-adapter swap. Recommended later: stdio, with TOPOLOGY. DELEGATEHOME is not decided here and nothing below depends on it.

## Migration order (each step releasable; the epic's grep narrows each time)

Sizes: S under 200 changed lines, M under 600, L more. "delegate" = a change in `src/delegate`, same repo, same PR today.

| Step | What | Size | Epic child |
|---|---|---|---|
| **A1** | `contracts/agent.py` (`Agent` Protocol) and `adapters/agent.py` `ApiAgent` (thread, Handle and cancel hidden inside); `ApiRunner` drives an `ApiAgent` and stops touching `api.Handle`/`api.cancel`. Behaviour unchanged. | S | .2 |
| A2 | `ApiAgent.stop` returns `Ended(dead: bool)`; delegate keeps its own survivor registry (a survivor blocks the next `start` in the same cwd inside delegate). Delete `worker_call.survivors/log_kill` pid lists, `Survivor`, `WorkerEnd` use in the engine, `obs/stop` dicts. | M, plus delegate S | .2 |
| A3 | `agents()` (run registry in delegate); delete `lock_worker(s)`, `EngineLock.route/workers`, the lock reader's pid probes for workers. LOCK V bump. | M | .2 |
| A4 | `events()` replaces live-file polling: `WorkerStarted` poll, `live_path`, `DELEGATE_LIVE_FILE`; engine persists events to its run log; dashboard reads that. `reflect.py` goes through `start`. | L | .2, .4 |
| B1 | Budget (`usd/min/tokens`), tools, role, policy move into `start(Call)`; delete `to_argv` knowledge (`only_family`, `engine_only`, `writer_exec_allow`) from the engine. Delegate adopts them. | M, delegate M | .3 |
| B2 | Retry/reroute/resume/pause words into delegate; outcome becomes `done|needs_owner|failed(retry_after)`. Delete `pauses.py`, `pause_reasons.py`, `retry.py`, `policy.decide`, resume counters, `FRESH_*`. | L, delegate L | .3 |
| B3 | Context size, compaction, transcripts, `context_size.py`, family/lane names in report and dashboard go. | M | .3 |
| C1 | `lanes()` replaces `status_json/lane_status/role_status`, `app/wire/lanes.py`, `usage.py`; lane cards render from it; `history()` read in `planner.py` becomes an outcome field. | M | .4 |
| C2 | Delete dead vocabulary (`Family`, `LIVE_SECONDS`, `opencode_updated`, `catalog/pins` delegate parts). Final grep. | S | .4 |

Order reason: A1 is pure move (cheapest, no behaviour); A2/A3 remove the only thing the epic calls a bug (two protocols for a pid);
A4 before B because the engine cannot persist events until it pulls them; B2 is the largest deletion and needs B1's arguments first;
C last because `lanes()` is the smallest read but its consumers (dashboard) change with A4.

## What a Fake gives

`tests/support/fake_agent.py` implements the Protocol (scripted events and outcome, `stop` records the call). Engine tests for worker
calls use it; `FakeApi` and `procsim` for AI workers go with A4. Real-process tests stay only in the delegate adapter's own tests.

## Judged risks

- ⚠️ A2 needs delegate to be strictly correct about "proven dead": today `kill_tree` names survivors; moving the protocol into delegate
  must not weaken it. Test: the existing `tests/live/test_stop_tree.py` scenario against `ApiAgent`.
- ⚠️ `failed(retry_after)` loses "which lane is out". The dashboard lane cards get it from `lanes()` (C1). Between B2 and C1 the card
  reads the old status; acceptable, short.
- ⚠️ The Protocol must not grow a second consumer-shaped method per feature. Rule: a new method needs an owner decision and a row here.

## Decisions recorded

| Decision | Status |
|---|---|
| Agent is a Protocol in `contracts/`, adapter over delegate (option 4) | accepted, 2026-11-07, Denis: "Protocol then protocol. Accept as written" |
| Pull `events()`, no callbacks | accepted, 2026-11-07, Denis: "Protocol then protocol. Accept as written" |
| `stop` = proven dead or `StopFailed` | accepted, 2026-11-07, Denis: "Protocol then protocol. Accept as written" |
| Terminal outcomes only; `retry_after` the single extra field | accepted, 2026-11-07, Denis: "Protocol then protocol. Accept as written" |
| Library vs stdio, DELEGATEHOME (tl-w7lt.37) | accepted, 2026-11-07, Denis: "Protocol then protocol. Accept as written" |

## B2b: the behaviour change that needs the owner (written 2026-11-06)

B2a (additive, landed with this note) adds `domain/lanes/outcome.py`: `outcome_of(result)` reads a stop as `Done | NeedsOwner(question) |
Failed(reason, retry_after)` from the answer's own facts (`permanence`, `retry.at`, `fix`). Nothing uses it yet.

B2b makes the engine act on that outcome alone and deletes `policy.TABLE` (19 rows), `retry.PLAN`, `pauses.py`, `pause_reasons.py`, the
resume counters and the in-process waits. **Old and new, for a stop the engine sees today:**

| Case | Old (engine decides) | New (delegate decides, engine sees the end) |
|---|---|---|
| lane busy / blip (`lane transient poll`) | engine polls 3 times, 20 s apart, then reroutes | delegate polls and reroutes inside the call; engine sees Done or Failed |
| lane out, back at T (`predicted`) | engine waits in-process if T is under 180 s, else pauses the bead with a wake time | delegate waits or fails; engine sees `Failed(retry_after=T)` and re-queues the bead after T (always a pause, never an in-process wait) |
| network down (`machine transient poll`) | engine waits up to 600 s on its own probe, then pauses | delegate waits on its probe; engine sees Failed(retry_after) |
| delegate crash | engine retries twice (30 s, 120 s), then faults | delegate's concern; engine sees Failed |
| worker failed / timed out | engine tries another lane once, then asks the owner | delegate reroutes once; then NeedsOwner |
| needs_owner stops | engine routes to the right ask or pause kind | one NeedsOwner(question) |

What is lost: the engine can no longer say WHICH lane is out or why (the dashboard gets it from `lanes()`, C1), and a short lane-out
under 180 s now pauses the bead instead of waiting in the same run. **Decision for the owner:** is `Failed(retry_after)` enough, with no
lane name in the engine? Recommended: yes. Accepted by Denis on 2026-11-07: "Protocol then protocol. Accept as written".

B2b-1 done (2026-11-07): delegate owns worker network waits and resumes; engine network stops pause immediately.

B2b-2 done (2026-11-07): lane polls and short lane-out waits are delegate's

B2b-3a done (2026-11-07): worker_failed retry and the write reroute are delegate's; a delegate crash fails at once (fail fast). Rows left in policy.TABLE until B3 (resume/context behind the Agent): resume_refused, denied_secret, NewThread/Reroute for RESUMED calls, lane stops of resumed calls.
