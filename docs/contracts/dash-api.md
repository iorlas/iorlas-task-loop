# dashboard API: contract

Status: built; the only API the dashboard has. The page (`src/taskloop_dash/static/index.html`) is served at `/`, its modules
beside it, and talks to nothing else.
Source of truth: `src/taskloop/contracts/dash.py` (records, enums, `WRITES`). Sample data: `tests/fixtures/dash/` (built by
`tests/support/dash_fixtures.py` from the round-8b mock; `UPDATE_GOLDEN=1` rewrites it). Test: `tests/contracts/test_dash.py`.
Design: `docs/design/dashboard/dash-spec.md` §11.

Neither side changes a field alone: a change is a commit to `dash.py` plus regenerated fixtures, and both sides follow it.

## Endpoints

| method, path | body / query | answer |
|---|---|---|
| GET `/api/snapshot` | `since=<version>` optional | `Snapshot` with `ETag: "<version>"`; 304 when `since` or `If-None-Match` equals the current `version` |
| GET `/api/bead` | `project`, `id` | `BeadDetail`; 404 for an unknown bead |
| GET `/api/live` | `project`, `id`, `since=<cursor>`, `wait=<s>` | `LivePage` with lines after the cursor; long-poll over `api/live.py` and `runlife` |
| POST `/api/<verb>` | the `WRITES[verb]` record as JSON | `Result` |
| GET `/api/artifact` | `bead`, `name` | a file the run kept (`ConfigDir.artifacts`); HTML only as a download |
| GET `/api/look-shot` | `repo`, `path` | a picture an open look item names, read from the repo |
| GET `/api/version` | | `{version, pid, urls, started, script, binds, port}`: what `tl dash ensure` checks |

Verbs: `answer`, `look`, `stick`, `prune`, `cause`, `ack`, `park`, `stop`, `note`. The dashboard runs no process: a write is an
in-process Port call (as `Ports.answer` is today), never a raw bd argv. Auth stays `bind.post_allowed`. A refused write is
`Result(ok=false, message=...)` with status 200, so the page shows `message`; a malformed body is 400.

- **Built (backend items 3, 4, 6, 7 and 8):** `live`, `answer`, `look`, `cause`, `ack`, `stick`, `prune`, `park`, `stop`, `note`, and
  `answer` with `kind=ask_back`; every verb of `WRITES` is routed to a Port, none answers "Not available yet.". `live` takes `id` (the bead; its newest
  run) and ignores `project`; its cursor is `api/live.py`'s byte-offset cursor; 404 for a bead with no run. Each write is one `Ports`
  call into an `Intake` verb (`taskloop/app/asks/intake.py`): `answer` re-sent for an answered, unused ask amends it; `look` is keyed by
  the look item id (`<source bead>#<n>`; the source bead also works while it has one waiting item), `redo` needs a note; `cause` and
  `ack` are bd metadata `owner_cause` (JSON `scope, cause, t, by`) and `owner_ack` (JSON `scope, t, by`), `scope` the bead's newest
  run id (an ask id when `cause` names an ask); `ack=false` unsets the key. `ToolCall.name` is delegate's one `text` until it types more.
- **Built (backend item 5):** engine-log records `Said(step, who, text)` (every comment `Engine.comment` posts, `step` the open or last
  step id), `Assumed(step, text, reversible)` (replaces the `Assumption:` Note), `Stuck(why, step, since, limit_s, sig)` and
  `RunStart.branch`. They fill `Pass.messages` (Said, and the open Stuck, newest first), `Cell.last` (the stage's last Said, first
  line), `BeadCard.assumptions` (Assumed records over the bead's runs), the `stuck` marker, cell, `PassEnd` and `LiveBox`, and
  `Resumed.branch`. Stuck: `domain/stuck.py` at every Beat and once before the Close; limits in `contracts/runlife.py`
  (`SILENT_LIMIT` per step, `SAME_RED` = 3); one record per episode.
- **Undo** is client-side: the page holds an answer 5 s before it POSTs. The server has no undo.
- **Option** is the 0-based index into `AskCard.options`.
- **stick** (`Intake.stick`, from the ledger, so it also works for an ask a newer ask replaced; the ask must be answered): `adr` writes
  a decision under the task-loop state dir (`decisions/<repo>-<hash>/ADR-n.json`, never into a checkout: `tl` and the engine write
  only there and to bd), which the plan stage reads and cites; `ref` links the ask to a decision in force (`text` names `ADR-n`,
  else the one the ask's repeat key matched); `factory` files a bead (label `factory`) in the registered repo named
  `iorlas-task-loop`, refused when none is registered; `fix` appends the owner's `text` to the bead description, so the brief
  changes and the plan runs again; `demote` and `once` record the outcome only (demote does not yet make a kind non-blocking).
  `Stick` gained `ref`. A second tap of the same outcome files nothing twice. Every outcome is one ledger row.
- **prune** (`PruneReq`: `project`, `adr`) retires a decision in force: it stays in the store with `retired_by` and `retired_t`, the plan
  stage and repeat detection stop reading it, and `Snapshot.adrs` drops it. Refused for an unknown or already retired id.
- **ask_back** appends an `owner` entry to the ask's thread and leaves the ask open; the helper that answers is not built.
- **Ask v3** (`contracts/ask.py`): `owner_cause` and `cause_by` (declared by the agent through the answer schemas' `owner_cause`;
  the owner corrects it through the `cause` verb when `ask` names an ask), `blocking`, `default`, `key`, `similar`, `thread`,
  `outcome`. A soft ask (`blocking=false`) is filed when a plan's question is about a step that can be undone (tl-ntp): the run goes
  on with the `default` assumption (also written as the typed `Assumed` record, as every plan assumption is) and the ask stays open, so the owner can still answer; it is closed when the run lands.
  Repeat key: `<ask class>:<up to 12 distinct significant words of the question, sorted>` (`domain/asks/similar.py`); `similar`
  holds the ADR ids and the (up to 3) answered past asks of the same key.
- **Ask ledger** `<state dir>/ask-ledger.jsonl` (`LedgerEntry`, append-only, never swept): one row per `raise`, `answer` (also an
  amend), `consume`, `close`, `withdraw`, `cause`, `stick`, `demote`, each carrying the question, cause and outcome as of then.
  `Snapshot.ledger` lists asks that wait or were answered, newest first (at most 500); an ask that ended unanswered is not a row.
- **Learning** is weekly (Monday to Monday, local), from the ledger and the traces, and starts at the week of the oldest row or
  landed run (at most 8 weeks), so it has fewer than 8 points until the ledger is old enough. `sendbacks_per_bead` is plan redos
  (`RunTrace.stats.replans`) per landed run: look send-backs are not retained. `causes` counts asks only, this week against last.
  `AdrRow.project` was added (two repos both have an ADR-1).
- **Needs you** `Snapshot.needs` (`NeedRow {kind, project, bead, why, since, until, title}`, oldest first, `views/needs.py`) is a view over
  records the engine already writes, no new recorder: beads labelled `needs-ac`/`needs-info`/`owner-taste`/`owner-look`; blocked beads
  (the newest `block` event's reason); the queue's `parked` and `capped` skips (`Park.t` gives the time); `pauses/<bead>.json`
  (network); a lane that is out and delegate's `needs_input`; held and set-aside slots (slot bead metadata, `slot_hold`/`slot_aside`
  events) and failed `slot_setup`; reconcile strays; a stalled loop. Beads with an open ask are not rows (Decisions). `ServerInfo.loops[]`
  carries the strip: `health` ok, `stalled` (a loop beats, holds no bead, `ready` beads wait and the repo logged no event for
  `LOOP_STALL_S`, `contracts/reconcile.py`) or `absent` (the reconcile NoLoop rule, `LOOP_ABSENT_S`). Not shown: the storm stop (its file
  is read by an adapter) and a loop's in-memory network wait. events.jsonl rows carry no `v` and spell kinds `slot-hold`, so the
  dashboard reads them tolerantly (`Records.seen_events`), not through `events.decode`.
- **park, stop, note** (built, backend item 7) are the bead's newest run's request file `runs/<run>/owner-request.json`
  (`contracts/requests.py` `OwnerRequest {park, stop, notes[], by, t}`, merged under `owner-request.lock`, `app/run/requests.py`).
  The engine takes it at every step boundary (`Steps` guard, and before each worker call): `park` ends the run there as
  `Kind.OWNER_PARK` (Close `why_code=paused`, branch and checkpoint kept), each note is a `Said(who=owner)` and ends the next
  worker's prompt. `stop` is also read at each Beat and sets the run's stop flag (the SIGTERM halt path; Close
  `stopped_by_coordinator`, why "failed: stopped by the owner"). park and stop also set the bead's `owner_hold`, so the loop does not
  start it again (`tl hold BEAD --release`). With no live run: `stop` is refused, `park` only holds, `note` is the `owner_hint`. A
  request left at the close is dropped; the run-log sweep removes the file. CLI: `tl park BEAD`, `tl note BEAD text` (`tl stop` stays
  the loop's verb).

## Semantics both sides rely on

- Times are unix seconds (float). Durations are `*_secs` ints. Tokens are ints.
- `Snapshot.version` changes whenever a field other than `t` changes. The page polls every 2.5 s while visible and sends
  `since`. On a 304 it keeps the old `t` and ages from it plus the browser time elapsed since that fetch.
- Every bead id in the API is the full bd id including the project prefix ("lifesim-4buv", "tl-8k4"), never the short tail.
  The page may strip "<project>-" for display only; ids sent back in writes are the full ones.
- Bead ids are paired with a project wherever a row can come from more than one (`Piece`, `Slot`, `AskCard`, `LedgerRow`).
- Trims: `pieces` cover 8 h back to 2 h ahead; done beads since local midnight; `beads` holds at most 200 backlog beads and
  `backlog_more` counts the rest. `Totals` cover the passes still in the run logs (7 days).
- Every bead id in `pieces`, `slots`, `asks`, `needs`, and open `ledger` rows exists in `beads`. `needs` lists open blockers
  only. Answered ledger rows may name beads trimmed away.
- `Piece.n` counts a bead's pieces from 0; `from_slot`/`to_slot` link a comeback (a resume in another slot is a new piece).
- `Phase` maps engine steps: plan/replan → plan, write → write, checks → test, review + verify → review, look → look,
  gate + land → land. The spec calls these stages; the code says phase because three `Stage` records exist.
- `Slot.lane` is the lane of the slot's current or last call; lanes are per call.
- `Totals.tone` is computed by the backend (watch at 2× usual, bad at 4×); the page never recomputes a threshold.
- `CheckCount` comes only from typed check results, never from log text. `ToolCall` has name and argument only until delegate
  types the outcome. Absent means unknown.
- `LiveBox` is null when nothing runs; `kind=stuck` carries `why` and `silent_secs`. Stuck is decided by the engine at the
  Beat tick, never by the dashboard.
- `LivePage.state` is `runlife.liveness`: live, ended, crashed.
- Strict decode: an unknown key is an error on both sides. A new field is added with a default first.

## Who builds what

- **Frontend** (`taskloop_dash` static assets): layout, filters, deep links, drafts, the 5 s answer hold. It derives nothing
  listed below.
- **Backend** (pure builders under `views/`, each with fixture tests): column and marker as pure functions over typed facts,
  status line, passes and pieces, comeback joins, roll-up (`Epic.done/total`), goal roots, lane forecast, learning series,
  cause counts. The bd bead list is cached; a poll never runs bd.

## Backend order

Readers first; they are safe while a loop runs:

| # | builds | size | page slice it feeds |
|---|---|---|---|
| 1 | `views/snapshot.py`: beads (column, marker, status), slots, epics, server | M | 1 shell |
| 2 | pieces and `BeadDetail` passes and cells | L | 2 board + drawer |
| 3 | `LivePage` over `api/live.py` and `runlife` | S | 2 drawer live tail |
| 4 | write ports: answer, look, cause, ack, as Intake verbs behind Ports | M | 3 asks, 4 floor |

New engine facts follow, in one cutover freeze per `docs/cutover.md`, because a running loop refuses unknown log tags and Ask v2:

| # | builds | size | fills |
|---|---|---|---|
| 5 | records `Said(step, who, text)`, `Assumed`, `Stuck`, `RunStart.branch` | M | `Pass.messages`, `Cell.last`, `assumptions`, stuck `LiveBox`, `Pass.resumed` |
| 6 | Ask fields (`owner_cause`, `cause_by`, `blocking`, `default`, `similar`, `thread`) and an append-only ask ledger | L | `AskCard`, `ledger`, soft asks |
| 7 | park, stop and note request files | L | 6 controls |
| 8 | ADR store, `PlanAnswer.cited`, learning series | L | 5 decisions (`adrs`, `learning`, `stick`) |
| 9 | lane usage history (at, used_pct) and the forecast | M | 8 lanes (`state`, `window_pct`, `week_pct`, `locked_until`; `forecast_pct` and `resets_at` wait for a typed reset time in delegate's status) |

Until a field is built the backend sends its default (empty list, 0, null, ""); the page renders that as "no data", not as an
error. Open: `Seg` kind `projected` (the Floor forecast) has no writer yet; `LaneCard.plan` has no source; so far `LaneCard.forecast_pct`, `resets_at`, `forecast` have none either: delegate's contract types
the `five` and `week` percents but no reset time, and names `windows[]` with free strings. History (`usage-history.jsonl`, `contracts.usage`)
keeps every window as named and `usage.forecast` is ready for the day the reset is typed.
