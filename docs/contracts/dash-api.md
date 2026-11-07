# dashboard API: contract

Status: built; the only API the dashboard has. The page (`src/taskloop_dash/static/index.html`) is served at `/`, its modules
beside it, and talks to nothing else.
Source of truth: `packages/kernel/src/tlkernel/dash.py` (records, enums, `WRITES`). Sample data: `tests/fixtures/dash/` (built by
`tests/support/dash_fixtures.py` from the round-8b mock; `UPDATE_GOLDEN=1` rewrites it). Test: `tests/contracts/test_dash.py`.
Design: `docs/design/dashboard/dash-spec.md` §11.

Run state comes only from factory.db. `Snapshot.server.database_error` is omitted when healthy; otherwise it carries the plain
database-unavailable line shown by the page, and no run state is served. `/api/version.database_error` reports the same health
check (an empty string when healthy). Logs stay behind `readers/logs.py`; clients treat all live-feed cursors as opaque.

Neither side changes a field alone: a change is a commit to `dash.py` plus regenerated fixtures, and both sides follow it.

`Project.id` and every `project` reference carry the registered checkout key (`contracts.ids.loop_key(repo)`, also used by
snapshots and locks). `Project.name` is the directory's display name; only colliding names gain a parent-directory suffix. Runs are joined
by `(project, bead)` using the manifest's repo. Drawer links retain that project key separately from the board's filter.
`BeadCard.run`, `AskCard.run` and `LedgerRow.run` carry the observed run id. `stop`, `park`, `note`, `cause` and `ack` require
`project`, `bead` and `run` in their JSON body, plus their verb-specific fields. Missing fields are 400; a run outside that
repo/bead or no longer live is refused with `ok=false` before any request, hold, hint or metadata write. Commands never select
a newer run in place of the one the owner saw. A cause naming an ask also verifies the ask's repo, bead and run.

## Endpoints

| method, path | body / query | answer |
|---|---|---|
| GET `/api/snapshot` | optional `since=<version>`, `wait=<seconds>` (max 25) | `Snapshot` with `ETag: "<version>"`; 304 when `since` or `If-None-Match` equals the current `version`, including a long-poll timeout |
| GET `/api/bead` | `project`, `id`, `since=<version>` optional | `BeadDetail` with its own content-hash `version` and `ETag`; 304 for a matching `since` or `If-None-Match`; 404 for an unknown bead |
| GET `/api/cost` | `window=24h\|7d`, `last=<runs>`, `project`, `since=<version>` optional | `CostPage` with its own `version` and `ETag`; 304 for a matching token. Time, fresh tokens and cost summed per stage and bead over the kept engine logs; `last` takes that many newest runs; missing cost is counted as `unknown` calls; 400 for another window |
| GET `/api/live` | `project`, `id`, `since=<cursor>`, `wait=<s>` | `LivePage` with lines after the cursor; long-poll over `api/live.py` and `runlife` |
| POST `/api/<verb>` | the `WRITES[verb]` record as JSON | `Result` |
| GET `/api/artifact` | `repo`, `bead`, `run`, `stage`, `attempt`, `name` | a registered file of the store `<config>/artifacts/<repo>/<bead>/<run>/<stage>-<attempt>/<name>` that has its `<name>.json` sidecar; images, video, audio and PDF inline, the rest (HTML, SVG too) as a download |
| GET `/api/look-shot` | `repo`, `path` | a picture an open look item names, read from the repo |
| GET `/api/version` | | `{version, pid, urls, started, script, binds, port, database_error}`: what `tl dash ensure` checks |

With a matching `since` and positive `wait`, snapshot reads wait on factory.db's `PRAGMA data_version`, checked every
50 ms through one long-lived read-only connection shared under a lock. An idle timeout returns 304 with the same ETag
without building or hashing a snapshot. A committed indexer/engine change wakes the request and refreshes the shared build.
The token is read before building, so a commit during a build wakes the next request. First loads, unmatched versions,
absent/zero/invalid waits, unavailable watchers, and database health errors use the ordinary snapshot path and its existing TTL.
Negative waits mean zero; waits above 25 seconds are capped. `If-None-Match` alone does not hold a request.
The page sends `wait=20` after loading and retries 50 ms after completion; bead, live and cost keep their separate read patterns.
Bead listings and bd health arrive through the indexer's factory.db projection, so their commits wake this counter.
Non-DB inputs (transcripts and delegate live lines) cannot wake it. The timeout bounds each wait,
but an idle 304 does not refresh those inputs: they become visible on a subsequent DB wake or ordinary snapshot refresh.

Verbs: `answer`, `look`, `stick`, `prune`, `cause`, `ack`, `park`, `stop`, `note`. The dashboard runs no process: a write is an
in-process Port call (as `Ports.answer` is today), never a raw bd argv. There is no auth (the bind is loopback and Tailscale only). A refused write is
`Result(ok=false, message=...)` with status 200, so the page shows `message`; a malformed body is 400.

Every POST requires `X-Taskloop-Dash: 1` and `Content-Type: application/json` (media type parameters are allowed).
Host must name a bound address or `localhost`, `127.0.0.1`, or `[::1]`, on the dashboard's actual port.
Origin, when present, must match that Host's HTTP origin; clients without Origin still require the custom header.
Invalid Host, Origin, or custom headers return 403; unsupported media types return 415, before reading the body or invoking a Port.
Tailnet reachability remains an owner access grant; these checks prevent browser origin forgery and do not authenticate peers.

- **Built (backend items 3, 4, 6, 7 and 8):** `live`, `answer`, `look`, `cause`, `ack`, `stick`, `prune`, `park`, `stop`, `note`, and
  `answer` with `kind=ask_back`; every verb of `WRITES` is routed to a Port, none answers "Not available yet.". `live` takes `id` (the bead; its newest
  run in `project`); its cursor is the log reader's opaque cursor; 404 for a bead with no run in that project, 503 when run state is unavailable. Each write is one `Ports`
  call into an `Intake` verb (`taskloop/app/asks/intake.py`): `answer` re-sent for an answered, unused ask amends it; `look` is keyed by
  the look item id (`<source bead>#<n>`; the source bead also works while it has one waiting item), `redo` needs a note; `cause` and
  `ack` are bd metadata `owner_cause` (JSON `scope, cause, t, by`) and `owner_ack` (JSON `scope, t, by`), `scope` the observed
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
  is read by an adapter) and a loop's in-memory network wait. events.jsonl rows are the typed `Event` records
  (`trail.event` is the one writer); the dashboard reads them with `events.decode` and skips a row that does not decode.
- **park, stop, note** (built, backend item 7) write the observed run's request file `runs/<run>/owner-request.json`
  (`contracts/requests.py` `OwnerRequest {park, stop, notes[], by, t}`, merged under `owner-request.lock`, `app/run/requests.py`).
  The engine takes it at every step boundary (`Steps` guard, and before each worker call): `park` ends the run there as
  `Kind.OWNER_PARK` (Close `why_code=paused`, branch and checkpoint kept), each note is a `Said(who=owner)` and ends the next
  worker's prompt. `stop` is also read at each Beat and sets the run's stop flag (the SIGTERM halt path; Close
  `stopped_by_coordinator`, why "failed: stopped by the owner"). park and stop also set the bead's `owner_hold`, so the loop does not
  start it again (`tl hold BEAD --release`). Dashboard commands require a live run; CLI park/note with no run retain the hold/hint behavior. A
  request left at the close is dropped; the run-log sweep removes the file. CLI: `tl park BEAD`, `tl note BEAD text` (`tl stop` stays
  the loop's verb).

## Semantics both sides rely on

- Times are unix seconds (float). Durations are `*_secs` ints. Tokens are ints.
- Each `Project` carries `bd_ok_at` (last successful bd listing, or null before any success) and `bd_error` (empty after a
  successful read). `BeadDetail` carries the same fields for its comments read. A failure retains the last good rows and
  success time; it is retried on the next read rather than reused as a successful observation. Shared listings preserve their
  original success time. Both fields participate in the resource's content hash. The page shows failures with the first
  error line and last-success age, or “no data yet” before the first success.
- Snapshot, bead detail and cost each have a content-hash `version`, excluding `t` and the token itself. Every 2.5 s while
  visible, the page revalidates the snapshot and its mounted drawer/cost resources independently, retaining their data during
  requests and backing off on errors. A 304 validates the retained data; the drawer and cost show seconds since validation.
  The server clock ages from the snapshot's original successful body fetch, including across 304 responses.
- `Snapshot.adhoc` lists every live run without a bead, independent of the ten retained headers in `runs`. `RunHeader.branch`
  is the manifest branch, short SHA, or worktree basename. `Snapshot.leases` lists live resource holder hints, joined to runs
  by PID; the dashboard never acquires a lease. Configured slot lanes remain present while idle or before their first run.
- `Pass.detail` preserves the leaving transition's full detail; `end_text` supplies its cause in words. The drawer clips the
  reason to one line with the full text on hover. A sent-back plan starts a new pass even when both steps have phase `plan`.
- `Pass.logs[]` carries `{phase, roles: [{role, attempts: [{id, t, secs, outcome, lane, model, live, lines}]}]}`.
  Attempts stay in call order within each recorded role; `lines` are typed `TermLine` records. Worker events join by
  `CallStart.n` to the run's existing live file; check sections carry recorded results and tails, and the engine section
  carries step summaries and the leaving Transition. An absent stage log or empty roles means no log for this stage.
  These fields participate in the bead ETag. Selecting a stage survives revalidation; live attempts show the newest ten
  lines, clipped with click-to-expand. `Cell.state=done` always shows a check mark, duration and `outcome`, even for short
  stages; `overrun` is amber, `failed` red, `live` pulses, and `empty` is pending. Optional `budget_s` comes from recorded
  overrun budgets or check wall limits; the cell shows planned seconds against actual `secs` only when that evidence exists.
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
- A claimed slot with a known open or in-progress `held_bead` and no live run is `starting`: `bead` names that work,
  `t` is its slot claim time (`held_since`, falling back to `updated_at`), and `idle_why` says `starting <bead>`.
  `startup` is a short line of recent claim/setup/rebase phases from the project events already loaded; empty when unavailable.
  A live run takes precedence, and a claimed slot without known work keeps its idle/stray explanation.
- `Totals.tone` is computed by the backend (watch at 2× usual, bad at 4×); the page never recomputes a threshold.
- `CheckCount` comes only from typed check results, never from log text. `ToolCall` has name and argument only until delegate
  types the outcome. Absent means unknown.
- `LiveBox` is null when nothing runs; `kind=stuck` carries `why` and `silent_secs`. Stuck is decided by the engine at the
  Beat tick, never by the dashboard.
- `LivePage.state` is `runlife.liveness`: live, ended, lost (the run's recorded state).
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
