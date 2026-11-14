# Header
Task: tl-8bh9.14.152.4. Base: f92999d16e0be38b733cb6542593012d3f72f578.
Depth: small; one dashboard behaviour. No missing decision or explicitly unlanded dependency. Evidence budget: 6 model calls. Size: 3 changed files including this plan, 1 behaviour, 30 implement model calls.

## Outcome and non-goals
Explain recorded stopped rounds on automatic-land waiting cards. Owner attention, fault wording and stream/last-round health are delivered. Extend their page and fixtures; preserve policy, scheduling, drawer contracts and storage.

## Settled decisions
- Consume only rows supplied by the owning rounds.log reader through the existing dashboard log API and stream.
- This is display information, never a scheduling or liveness decision; qualify the explanation as the last recorded rounds state.
- Keep manual-land, unavailable-policy and active-landing explanations authoritative.

## Open decisions
- None.

## Change map
- `src/taskloop/dash/static/app.js` — extend `reloadRound`/`observeRound`; `fillCard` shows stopped rounds. Refresh via `renderBoard`; consult callers `resync`, `start`, `resyncBoard`, `setLanes`, task updates and gone handling. Retain `onLog` forwarding.
- `tests/dash/owner-attention.test.js` — extend snapshot, stream and race fixtures.
- `docs/design/tl-8bh9.14.152.4/plan.md` — new implementation plan.
- `src/taskloop/dash/static/api.js` — consult `apiSource.logs`/`subscribe`.
- `src/taskloop/dash_composition.py` — consult `log`, the reader integration.
- `src/taskloop/round_reader.py` — consult `LogRow`/`read_round_log`.
- `src/taskloop/rounds.py` — consult producers `run_rounds`, `_Backoff`, `_end`, `abrupt`.
- `src/taskloop/dash/static/ui.js` — consult `LAND`; reuse existing card wording and styling.

## Read list
- `src/taskloop/dash/static/app.js:19-73` — existing log observation, reload and race guards.
- `src/taskloop/dash/static/app.js:114-175` — land callout and board rendering.
- `src/taskloop/dash/static/app.js:200-259` — callers.
- `src/taskloop/dash/static/app.js:270-300` — stream callers.
- `src/taskloop/dash/static/api.js:13-35` — existing log source and reconnect producer.
- `src/taskloop/dash/static/ui.js:29-35` — land presentation states.
- `src/taskloop/dash_composition.py:65-68` — owning reader integration.
- `src/taskloop/round_reader.py:18-58` — structured row and ordered bounded tail.
- `src/taskloop/rounds.py:67-75` — lifecycle row writer.
- `src/taskloop/rounds.py:88-100` — wait producer.
- `src/taskloop/rounds.py:108-135` — start and normal termination.
- `src/taskloop/rounds.py:166-175` — stopped and abrupt producers.
- `tests/dash/owner-attention.test.js:17-60` — HTTP, clock and stream fixtures.
- `tests/dash/owner-attention.test.js:130-185` — existing land/waiting assertions.
- `tests/dash/owner-attention.test.js:187-245` — health helpers.

## Contract
Intent: observe the latest current-backlog rounds row with first word started, wait or stopped; reader order breaks timestamp ties. Effect: snapshots and streamed rows update a page-local observation and rerender cards. Extend revision guards against delayed snapshots; empty/failed reads clear unsupported claims. Result: land=waiting cards explain the recorded stop and awaited rounds resumption; start/wait clears it. No persisted field, endpoint or control state.

## Work packages
1. Update app and fixtures; closes both acceptance lines. Run the offline browser fixture; report unavailable tooling. Last, run once each preserving pipeline failure: `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`.

## Acceptance behaviours
- Snapshot/stream normal and abrupt stops explain automatic-land waiting in both themes; start/wait clears it, including after reconnect.
- Other backlogs, round summaries, missing/failed tails and delayed reloads cannot invent or restore a stopped claim; manual, active landing and existing health/owner-attention wording remain accurate.
