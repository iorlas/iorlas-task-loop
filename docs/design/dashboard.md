# task-loop dashboard: strategy (v2, after Fable review 2026-10-18)

## Goal
Real time: which tasks are in flight, in which repo; click a task, see every session working on it with a live
log (the orchestrating Claude session, Agent-tool subagents, Codex runs, `claude -p` runs). Also the whole
backlog as a tree. Viewable from the phone over Tailscale.

## Ownership
- New plugin repo `iorlas-task-loop`, in iorlas-marketplace; ideas tracked as beads there.
- task-loop owns the dashboard and the recording. Delegate is required for the engine (since 0.5.0), and its files are never
  read: any launcher (delegate included) shows its runs and lane limits by writing agent-runs v1 records
  (docs/contracts/agent-runs-v1.md). Decided 2026-10-18: delegate's internals change often; only the contract is
  stable.

## Records: who worked on what
| record | written by | where | gives |
|---|---|---|---|
| session index | plugin hook `SessionStart` (stdin has session_id, transcript_path, cwd) | ~/.config/task-loop/sessions/<session_id>.json | session id -> transcript path |
| bead claim/suspend/resume/land/close | `tl.py` (wraps the bd calls the loop makes) | `bd provenance record --issue <id> --kind claim ... --ref <session_id> --ref-kind transcript` | bead -> sessions, many per bead (reclaim, block/resume) |
| worker run | worker contract `tl.py worker <bead> --kind codex|claude-p --id <thread or session id>` | bd provenance, `--ref-kind work-id` | bead -> Codex thread / `claude -p` session |
| subagents | nothing extra | `<session dir>/subagents/agent-*.jsonl` + `.meta.json` (toolUseId, agentType) | orchestrator -> its subagents |

Why: measured 2026-10-18, a desktop orchestrator's transcript keeps its start cwd, so cwd cannot map a task to a
session; provenance is append-only, idempotent, shared through bd, needs no delegate. A per-task view of the
orchestrator = the transcript ranges between that bead's claim and its next suspend/land/close events.

Worker ids:
- `claude -p` via delegate: run-claude passes `--session-id <uuid>` and publishes an agent-runs v1 record with
  `parent_session`, so the dashboard links it with no extra call.
- Codex: capture `thread_id` from `codex exec --json` (`thread.started`), record it; the rollout file name holds it.

## Server
- `dash.py`: Python 3.8+ stdlib, `ThreadingHTTPServer`, one per machine.
- Autostart: the skill's start step runs `tl.py dash ensure`: detached spawn (new session, closed fds, scrubbed
  env, log to file); `/api/version` = hash of the server code, a mismatch restarts it (plugin updates); exits after
  2 h without a live loop.
- Bind: 127.0.0.1 plus the Tailscale IP (`tailscale ip -4`) when present. Not 0.0.0.0: the laptop travels and the
  page shows code and tool output verbatim. Tailscale ACL is the auth.
- bd reads: per repo, watch `.beads/last-touched` mtime; run `bd list --json --all` only when it changed, at most
  every 5 s, serialized, with timeout and retry. The worktrees' `.beads` resolve to the main repo's database.
- Transcripts tailed by byte offset (they reach hundreds of MB), SSE to the page.
- Retention: the page lists finished runs for 7 days; transcripts are never touched.

## UI
The vendor lane cockpit sits above the main view, with a row for every lane, including available and credit lanes.
It reads `delegate` from the unauthenticated GET `/api/asks` response. The server invokes only
`route.py status --json` on each request, without the former 60-second cache; this is a reporting operation,
not a vendor call. The page polls every 2.5 seconds after the previous refresh completes while visible, and
refreshes immediately when brought back into view. Outages and recoveries appear on the next completed refresh.

`delegate.lanes` is an ordered array of `{name, family, kind, model, emoji, out, out_until, reason, notes, usage}`.
`out` is true, false or unknown; `out_until` is Unix seconds or null. Each usage item supplies
`{window, used_pct, resets_at}` (reset time in Unix seconds). The server accepts named lane maps or lists and
adapts legacy `five`/`week` percentages into `5h`/`week` windows without duplicating supplied windows.
Existing `ok`, `out`, `detail`, and `needs_input` fields remain available to older clients.
The UI shows the supplied emoji, or a state emoji when none is supplied, and labels missing model, reason,
unlock time and usage as unknown. Every supplied window has a labelled usage bar and reset time; unknown
percentages stay indeterminate. Bar widths clamp to 0–100 while the label preserves the reported percentage.
Unlock dates use the browser's local time. Countdowns tick every second; expiry says "awaiting delegate status"
and never changes availability. Status failures replace stale rows with an explicit message. Vendor text is
escaped. Rows stack their fields at phone width. No additional login or authentication is introduced.

`tests/cockpit_scenario.py --evidence-dir <directory>` exercises the real page and dashboard GET handler with
mocked delegate subprocess responses. Tracker/local state access and external requests are blocked. It checks
fields, unknown values, escaping, countdowns, automatic outage/recovery, failure/recovery and phone bounds,
and saves desktop/phone screenshots and `cockpit-assertions.json` in the supplied directory.

One page, vanilla JS + CSS, no build; dark-first; mobile stacked, desktop three panes:
repos -> task tree (epic > children, deps as badges, filter in flight / ready / blocked / all; in-flight rows pulse)
| the task's sessions and workers (kind, model, state, last activity) | live log (text, tool calls one line each,
results collapsed, follow mode).

## Build order (all in this session)
1. Repo + plugin skeleton + beads for every item below.
2. Server, tree, in-flight from provenance, orchestrator log, subagent logs, bind.
3. task-loop skill rewritten around `tl.py` (claim/close/worker/dash), hook shipped.
4. Delegate: worker ids for `claude -p` and Codex; lanes panel.
5. Later beads: pruning, multi-machine view, idle tuning.

## Task view (v3, 2026-10-21, tl-bxk.12.3)
The unit is the task. Home (`/`) lists every bead the engine ran in the last 7 days: live state and stage
(planning, writing stage 2/3, checks, review, fix round 1 · writing, landing, waiting on you, paused: Codex out until
HH:MM), slot, time. A task (`#task=<id>`) shows every run of the bead, oldest first, each headed by why it started; a
run is a chain of blocks (one stage + one session), the arrow into each block says why the run moved there. A block
(`#task=..&run=<run>&block=<node>.<k>&tab=transcript|checks|engine|answer`) opens a drawer: the session's
transcript cut to the block's time, the checks of its round (command, exit, output tail, full log), the engine lines of
the step. Asks are answered on the task (and on `#asks`). The old three-pane viewer is `/classic`.

Endpoints: `/api/tasks`, `/api/task-timeline?repo&id`, `/api/block?run&node&k`, `/api/file?run&path` (a file of the
run's folder only). `dash/timeline.py` builds runs -> blocks -> arrows.
Stages: a write, checks or review block carries `stage_index`, `stage_count`, `stage_title` (the first sentence of the
stage's goal, from the plan node's answer in the log, else `runs/<run>/plan.json`; old logs read `stage i/N` from the
node text). The run is drawn in sections, "Stage i of N · title" (fix rounds: "Fix round k"); plan, verify and land sit
outside them, and each block also shows an `i/N` chip. A review or verify block has `same_family: true` when its
session's family is the family of the last write before it (or delegate flagged `same_family`): it shows "same family
as writer — weaker review".
A task's status, in order: running; an open ask ("waiting for your answer"); an open bead it depends on with a
`blocks` dependency ("blocked by <id> (<title>)", state `blocked_by`, from the repo's cached `bd list`: one bd call per
repo per refresh); else the last run's close reason. A run that ended asking whose ask is no longer open never reads as
waiting: "answered: waits for the next run" when answered, else "ask closed: <why>".

### Timeline records (engine log, since tl-bxk.12.3)
The engine log `engine/<bead>-<YYYYMMDD-HHMMSS>.jsonl` keeps its old records and text; these are added, never printed:
| kind | fields |
|---|---|
| `node` (existing) | + `id` (run-scoped, from 1), `step` reset/plan/replan/write/checks/review/verify/land/close, `stage`, `stages`, `write`, `round`, `fix`, `fixes`, `try` |
| `end` | `id`, `step`, `outcome` (green, red, clean, sent back, asks, paused, landed, gate red, ...), `detail`, `secs`, `sessions` [refs] |
| `transition` | `from` (node id), `to` (a step, `next`, `ask`, `pause`, `close`), `cause`, `detail`; `lane`, `until` on pauses |
| `checks` | `node_id`, `round`, `items` [{id, cmd, group, exit, status, secs, tries, cached, why, log}] |
| `run` | `run`, `bead`, `prev_run`, `started_because` first/answer/resume/retry/fresh, `ask`, `slot`, `worktree` |
| `gate` | `tree`, `cmd`, `exit`, `secs`, `cached` (already green on this tree), `node_id` |
| `vendor_error` | `node`, `step`, `attempt`, `status`, `reason`, `error`, `stop`, `secs`, `lane`, `model`, `family`, `node_id`, `error_observed`; `started_t`, `first_error_t`, `last_event_t`, `ended_t`, `kill_t` (null when the boundary was not observed) |
| `kill` | `what` (check/command/delegate), `why`, `exit`, `hung`, `secs`, `node_id`, `alive` (worker pids that survived), `observed_t` (actual stop time), `started_t`, `last_event_t` (last observed check output/file/CPU activity, frozen before the stop), `kill_t`, `ended_t`; written only when the engine really stopped a tree, so a command that exits 124 by itself has no kill record. Shutdown output and the synthetic hang notice do not advance `last_event_t` or `kill_t` |
| `cache` | `round`, `tree`, `base`, `hits`, `misses`, `items`, `changed` (task paths), `node_id` |
| `session`, `msg` (existing) | + `node_id`; session + `resume`, `flag` |

Causes: checks_red, checks_green, review_sendback, accepted, bad_checks, rounds_used, writer_decided, plan_sent_back,
invalid_output, lane_out (a new thread), lane_wait, paused, decision/verify/ticket/stuck/waiting (an ask), verify_open,
verify_wrong, verified, gate_red, conflict, push_race, landed, done, failed, stopped. Check logs keep every round:
`checks/NN-id.rK.log`, `engine-checks.rK.json` (`engine-checks.json` is the latest). `traces.jsonl` lines add
`prev_run`, `started_because`, `ask`, and `fingerprint`: a stable slug of the failure cause (bead ids, session refs,
paths, shas, numbers and quoted payloads normalised; empty for a landed/done run) so the lifecycle report can group
runs across weeks. Logs from before these records are read from their node/session/warn text.
There is no `judge` step: the engine has none yet.

## Roadmap (v4, 2026-10-23, replaces the Plan graph)
Home (`/`, `#roadmap&repo=R`). The Plan tab's dependency graph (401 nodes on lifesim, cytoscape + dagre, 3 vendored
libraries) is cut: nobody acted on its "not auto" / "blocked" counts, and a dependency only matters as what a landing
lets go. `#plan` links open the Roadmap; the task list moved to `#tasks`.
- One lane per slot: the last 5 passes that left it (landed / parked / failed / paused; "taken" = lost a claim race, not
  shown), the bead running now with its stage rail (plan, write, checks, review, verify, land) and the block trail, and
  a git-graph tree of what its landing unlocks. A landed pass names the beads it released.
- Up next: the queue in the order `tl next` takes it (`loop.queue`, fetch off), as a git log: each bead a commit, the
  beads that wait on it branch off (depth 3, 5 wide, "+N more needed" = it also waits on other open beads).
- Held back: ready beads the loop skips for now (an area is busy), most unblocking first, same tree.
`GET /api/roadmap?repo` -> `dash/roadmap.build()` (pure); inputs: `graph.build()` nodes and edges, `loop.queue()`, the
loop's state files and pass log (`loop/<key>*.json`, `<key>.jsonl`, read only: a dead loop's file is left), the engine
log's blocks (`timeline.run_timeline`). Mockups of the three options considered: `docs/design/mockups/`.

### Cockpit layer (2026-10-23, after a Sonnet ops-UX review of the Roadmap)
Gaps found: asks were one badge, a lane outage and a 51-park single-cause storm were invisible, churn and token spend
were not on the page. Added:
- Signal strip (`dash/signals.py`, pure; thresholds are named constants fitted to lifesim's real distribution): lane
  out / usage >= 90 % (red/amber), beads held by nothing (red), >= 4 parks with one normalised cause within 3 h (red),
  asks aging (info > amber 12 h > red 24 h or parking within 24 h), churn (checks failed >= 3, planned >= 3, or >= 12
  steps; amber), token hog (fresh tokens > 500k and 3x the median), budget near-miss (<= 115 % of the limit; info),
  good news (landings in 24 h, median time, first-run share; green). Red first. The strip says "Nothing wrong" when none fire.
- Tokens: "fresh" = input - cached + output (95 % of input is cache read, so raw totals mislead); summed over all runs of
  a bead (`tokens_all`); the median is of fresh tokens per bead of the repo. Each running bead gets a verdict line.
- Hover on any bead id: title, state and why, runs, steps, time, tokens (`briefs` in `/api/roadmap`). Click: panel
  (`#roadmap&repo=R&bead=ID`, `GET /api/bead`): description, acceptance, notes, comments newest first, transitions per
  run with duration and tokens, dependencies, link to the full run timeline.

## Looks gallery (owner-look beads)

Taste items never block a land: the engine files them into the owner-look bead (metadata `looks`, see `Engine.write_looks`).
The **Looks** tab (`#looks&repo=R`, `dash/gallery.py`, `/api/looks`) shows one card per item: the judge's note, before | after
pictures (a before-only or after-only item shows what it has), and two answers:

- **Good**: the item's status becomes `good`; when no item of the look bead waits, the bead closes.
- **Redo** with a note (required): files a follow-up bead "Redo look: ..." (related to the source bead) whose description and
  `looks` metadata carry the note and the pictures; the item becomes `redo` and keeps `redo_bead`.
- **Undo** on an answered card: the item is open again, the follow-up bead is closed, a closed look bead is reopened.

Pictures are served by `/api/look-shot` only when an item lists that exact path (never a caller's path), inside the repo,
with a picture extension; read from the checkout, else from HEAD / origin/main / main / master; an LFS pointer is not served.
An old look bead (no metadata) is read from its description: `## <bead>: <title>` sections, each `- path` an "after".
The Roadmap's strip shows one signal, "N looks wait for you" (info, amber after 12 h), linking to the tab. Answers go through
`POST /api/look` with the same access rule as asks (loopback and Tailscale, else the token). Writes are read-modify-write of
the bead's metadata; the engine's own write of `looks` keeps answered items, and the race window is two bd calls.

## Where the time went (tl-9h2)

The bead panel's "Where the time went" is one bar across the bead's whole life, one segment per step, check, wait and idle
stretch, with totals per kind (working, checks, waiting by cause, idle). `timeline.bead_segments` builds it from the engine logs
of every run (`api_bead` -> `timeline`); hover a segment for its name, length, holder and start.

- **Engine records.** `wait` records (quiet kind): `{what, t0, secs, holder?, in_budget}`. `add_wait` writes one for each wait that
  is already excluded from budget_min (lane, Unity slot, editor lock, delegate crash, network; `in_budget=false`). `Engine.locked`
  wraps `tl.os_lock` for the land lock and the review lock: when the lock is taken, the open node ends first (the wait is no longer
  booked to the step before it, engine.py land loop) and a `wait` record names the lock, the holder, the start and the length
  (`in_budget=true`: lock waits still count against budget_min, as before). A free lock logs nothing.
- **Segments.** A wait that starts inside a step is cut out of that step (nothing counts twice); a lock wait is a bar of its own
  between steps. Unexplained time inside a run of 10 s or more is "between steps" (idle). Time between runs is "owner ask" (the
  earlier run ended asking), "paused" (it ended paused) or "between runs" (idle).
- **Live runs end now.** `run_timeline(alive=True)` gives the open step and the run an end of now, not of the last record.
- **Not recorded yet** (outside the engine's log, so no segment): the slot-take lock (tl.py), the area lock (loop.py), the gap
  from claim to the engine's start, push duration while running. They show up as the unexplained start of a run.

## Old windows of a huge transcript (tl-65w)

`/api/events` for a run worked hours ago in a long session no longer shows nothing: `window_lines` (server.py) bisects the
transcript on byte offsets by timestamp (they only grow) to the start of the run's window and reads from there, at most 40 MB.
A small file, no window, or a window the last 6 MB already holds is read as before.

## Causes (tl-bl5)

`#causes` lists the last 24 h of run reflections clustered by cause class (`/api/reflections`, `reflect_digest.view`): title, run
count, files named, and the bead filed for the cause. Seen-once causes are dimmed; two or more runs make a cause recurring.
`tl reflect digest` (daily from the loop, detached) files one bead per recurring cause: engine and prompt in task-loop, delegate
in delegate, the rest in the project the runs ran in. Run ids are the evidence; the acceptance says the next 3 comparable runs
show no such item. A cause already filed (state file, or an open bead of that repo with a like title) gets a comment with its new
runs; one whose bead was closed and recurs gets a new bead naming the old. `--dry-run` files nothing.
