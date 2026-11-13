# Dashboard UI

Status: **built, slice 1**. `tl step rounds ... --dash-port PORT` serves this page and the endpoints below on
`127.0.0.1:PORT` from a thread of the rounds process (0 picks a free port; without the flag nothing is served). Terms:
[dashboard, board, live tail](../glossary.md). The page (`src/taskloop/dash/static/`) was designed on a mock first; the
owner's decisions below stand. What slice 1 cannot show yet is under *Not in slice 1*.

## Decisions (owner design interview, 2026-11-12, and review of the first mock)

- Read-only: no buttons that change anything, no auth, no charts, no history pages. The controls are the theme switch,
  the board layout switch and drawer navigation.
- One board on one screen. A card is a task, newest activity first in its column. Columns: Ready, Plan, Implement,
  Checks, Land, Held, Landed. The Land column is the person's: a card there says *Waiting for you* with the command (`tl step land <id>`, rounds never land) and says *Delivering* only while a land process is observed running (tl-8bh9.14.72). (The glossary says *ready* for a task not yet admitted; the interview said "Waiting").
- Two layouts of the same board: **Steps** (one column per step) and **By slot** (swim lanes: one row per slot, plus
  "no slot" for tasks holding none). Switching animates the cards into place.
- A card shows task id and title, where the task is (`step 2 of 4 · try 1`: a step and a try are different things; a repeat is a new try of the same step), a *repeat* or *restarted at plan* badge with its reason, time in the
  current step, slot, and the hold cause. A card that changes column animates to its new place.
- Clicking a card opens a wide drawer (see below): task fields, then the task's history, then the lines of one attempt.
- Two screens, chosen in the header: **Board** and **Logs**. The layout switch (Steps, By slot) belongs to the Board.
- **Logs** is the factory's one log, `rounds.log`: append-only, beside `attempts/` in the factory's artifacts folder, one
  line per move (a round's action or sight for one task), written by the rounds process for all tasks and slots. Slots
  have no log of their own, so one stream is faithful: newest first, grouped by day, live, with the time, the task (click
  to open its drawer), the move and its words, and a filter *All moves / Needs attention* (hold, skip, repeat, failed,
  unusable slot, no free slot). The per-attempt evidence files (stdout, `entry.log`, check logs) stay per attempt and are
  read in the drawer. If one factory serves several repos with separate artifacts folders, the reader merges their
  lines by time; each line carries its backlog. Display only, never control state (CLAUDE.md: no control from logs).
- The drawer has two top-level tabs: **Attempts** (below) and **Task**: the task as the tracker holds it, laid out like
  a Jira issue. Left, the full text (description, acceptance criteria, design, notes) and under it the **comments**,
  the tracker's discussion oldest first (the factory's hold and landing comments, the person's answers). Right, a
  **Details** sidebar (priority, labels, task branch, claim, dependencies, created, updated). Above the tabs: id, a
  badge for where the task is on the board, the slot, one sentence of what the badge means (hover help on each column
  header says the same: *Held* is the glossary's hold, the factory will not advance the task until a person acts), the
  title and, for a held task, the hold cause.
- The Attempts tab is a master and a detail. Left, the **attempt rail**: every attempt of the task, in the **order they happened, top to bottom** (plan, implement, checks, land, each with its own try number; steps still to come are dim rows below; the drawer opens on the newest attempt), one
  aligned row each (step, number, duration; a failed one adds its summary). Between two rows a
  jump names how the next attempt began: `↻ Repeat of Checks` (the same step again) or `↩ Back to plan` (restarted at plan, D4)
  with its reason; the label sits above the attempt it began. Between two rows an `⏸ idle 4m 00s` line shows the time nothing
  ran (5 s and up). The Land row is the card's state (waiting for you, delivering, delivered). A task with ten attempts is ten rows and the rail scrolls. Right, the selected attempt, in three tabs:
  - **Lines**: the log grid (below). Opens first for a running attempt. New lines never change the tab, the selection or the
    scroll place: the view follows the end only when it was already at the end. No count in the tab name; a quiet line says
    how many lines are kept and whether it is live. A pause of 2 s or more before a line is a faint `⏸ paused 33s` row (the
    producer's `waited_ms`, else the time since the previous line ended). An agent message is shown in full; the events carry
    no separate thinking text, so none is shown.
  - **Result**: the conclusion, the agent's answer (disposition and text) and for checks each check's result with its
    full output (a failed check shows its output at once). Opens first for an ended attempt.
  - **Prompt**: exactly what the agent was told in that attempt, repeat feedback included; a step that runs commands
    (checks, land) has none. The chosen tab stays when another attempt is selected, so prompts can be compared.
  An attempt that began as a jump also shows why, naming the attempt it follows ("Repeat of Checks #5").
- Design language: emoji as step and column icons (Plan, Implement, Checks, Land, Held, Landed) and, since 2026-11-12, as the kind of an agent line (see below), never for state
  or log lines. A state is a coloured dot and a word, a badge is one outlined label, a
  reason is a callout (one accent line, no fill: amber repeat, violet back to plan, rose held or failed, sky running,
  green succeeded), numbers are tabular and right-aligned, colour means status only. The first mocks used emoji for
  everything and read as noise; the owner accepts a few.
- The drawer opens at once from factory.db and the evidence files (`GET /api/tasks/<id>`); the tracker's fields and comments
  (`bd` calls, slow under load) are a second request (`GET /api/tasks/<id>/tracker`) that the page cancels when the drawer
  closes or another task opens. The Task view shows a skeleton while it loads and the reason with *Try again* when it fails.
- Header: id, title, then the facts line, the description and, for a held task, the cause.
- **Quiet**: a running step that has produced no line for 2 minutes shows `Quiet 5m 40s` (amber; red from 15 minutes)
  on its card, with a coloured card border, and in the drawer. Any new line resets it. Display only, from the time of
  the latest agent line (the B10 fact); it decides nothing and the word stuck stays the engine's.
- A line is one row of a grid, never raw JSON: offset from the attempt's start, kind (an emoji: 💻 command, 🧰 tool, 💬 message,
  ❌ error, ⏳ waiting, 🧪 check, 🚦 step; the owner asked for emoji on the agent's lines, 2026-11-12), content, duration right-aligned (with the exit code in red when not 0). Before a command, when the agent took 2 s or
  more to issue it, a faint "agent thought 33s" line. That number is the time from the previous line to this command's
  start (a message and a tool carry the same hint); it is *not* part of the command's own duration (the first mock showed both as unlabeled durations).
- Stack: plain HTML and vanilla JS ES modules (`app.js` board, `drawer.js`, `logs.js`, `ui.js`), no framework, no bundler, no npm
  at runtime. `api.js` is the one data source (fetch and an event stream). Styling is Tailwind compiled once; `dash.css` is committed, so nobody
  installs Tailwind to use or serve the page. Light and dark theme follow the system; the switch overrides and is
  remembered in `localStorage` (optional, failure ignored).

## Words

The page uses glossary terms only: task, step, attempt, repeat, slot (`s1`), hold (cause), landed, check, command, agent,
live tail. "Cycle", "run", "worker", "waiting" and "in flight" are not used: *restarted at plan* is the glossary's
restart at plan (D4); the count in the header says "running"; an attempt's state is `running`, `succeeded` or `failed`
(a *pass* is a stored check result, not an attempt state). "Quiet" is a display word for time without agent lines.

## Tailwind

`just css` runs the **standalone Tailwind CLI** (v4.1.11, a single binary; no npm, no Python dependency):

```bash
just css
```

Obtain the binary once and put it on `PATH` as `tailwindcss`: download `tailwindcss-<os>-<arch>` for tag `v4.1.11`
from <https://github.com/tailwindlabs/tailwindcss/releases>, `chmod +x`, rename. With mise:
`mise use -g github:tailwindlabs/tailwindcss@4.1.11`. Re-run `just css` after changing class names in `index.html` or
`app.js` (the Tailwind scanner reads literal class strings, so build no class name from parts) or `dash.input.css`, and
commit `dash.css`.

## JSON shapes

Times are ISO 8601 UTC strings. Durations are integer milliseconds. Unknown optional values are `null`, never absent.

### Card (one task on the board)

```json
{
  "id": "tl-7d5",
  "title": "Carry the entry lease through relaunch",
  "column": "implement",
  "attempt": 3,
  "repeat": {"kind": "restart_at_plan", "reason": "plan rejected: ..."},
  "step_started_at": "2026-11-12T10:15:00Z",
  "last_activity_at": "2026-11-12T10:21:50Z",
  "slot": "s2",
  "hold_cause": null,
  "land": null
}
```

`column` is one of `waiting plan implement checks land held landed` (`waiting` is shown as Ready). `attempt` is the
number of the current or last attempt of the step (0 before any). `repeat` is `null` or `{kind, reason}`: `repeat` is a
new attempt of the same step, `restart_at_plan` is a task sent back to plan. `step_started_at` starts "time in step"
(for Landed: time since landing). `last_activity_at` is the sort key (newest first): the last step change or live
event. `slot` is `null` when the task holds none. `hold_cause` is the sentence the hold owner already shows, only in
`held`. `land` is `null` outside the `land` column; in it `waiting` (the person has to run `tl step land`) or `delivering` (a land
process is observed running).

### Board snapshot: `GET /api/board`

```json
{"generated_at": "2026-11-12T10:22:00Z", "slots": ["s1", "s2"], "tasks": [ <card>, ... ]}
```

`slots` lists every slot, so By slot shows idle ones.

### Factory log: `GET /api/log`

```json
{"backlog": "tl", "rows": [
  {"at": "2026-11-12T10:22:00Z", "backlog": "tl", "task": "tl-7d5", "move": "hold", "words": ["held", "repeats_exhausted"]}
]}
```

The last 200 lines of `rounds.log` read through its reader, oldest first. `task` is `null` for a line about no task
(`no_free_slot`, `unusable:s4:dirty`). `move` is the line's verb (`admit advance repeat report hold skip land` in the
mock; the grammar is `round_log.py`'s) and `words` are its fixed words, shown as written. A live line arrives on the
stream as `{"kind": "log", "row": <row>}`.

### Task detail: `GET /api/tasks/<id>`

```json
{
  "task": <card>,
  "attempts": [
    {"step": "implement", "n": 2, "state": "failed", "started_at": "...", "ended_at": "...",
     "summary": "failed: deadline exceeded after 30m",
     "after": "repeat", "reason": "failed: the agent finished without a diff",
     "input": "You are the implementing agent for task tl-7d5. ...",
     "result": {"summary": "failed: deadline exceeded after 30m",
                "answer": {"disposition": "incomplete", "text": "..."},
                "checks": [{"name": "types", "passed": false, "duration_ms": 23000, "output": "ERROR ..."}],
                "output": null},
     "feed": [ <live event>, ... ]}
  ]
}
```

`attempts` is every attempt of the task, oldest first. `n` counts per step. `state` is `running`, `succeeded` or `failed`;
`summary` says how it ended (the verdict or conclusion the owner of that fact already states); `ended_at` is `null`
while running. `after` says how the attempt began: `null` (the previous step succeeded), `repeat` or `restart_at_plan`,
with the `reason` the engine recorded. `input` is the prompt text the agent was given (`null` for a step that runs commands). `result.answer` is the
agent's answer (`null` before it ends or for checks and land); `result.checks` are the check results of a checks attempt
with the full output of each failed one; `result.output` is any other failure output, such as a stopped command's.
`feed` is the last 20 lines of that attempt, oldest first. A task with no attempt answers a waiting card and no attempts. This
answer never waits for the tracker.

### Tracker part: `GET /api/tasks/<id>/tracker`

```json
{"fields": {"priority": "P1", "labels": ["auto"], "branch": "task/tl-7d5", "claimed_by": "factory@devbox",
            "created_at": "...", "updated_at": "...", "depends_on": ["tl-6e6"],
            "description": "...", "acceptance": "...", "design": "...", "notes": "..."},
 "comments": [{"author": "factory", "at": "...", "text": "..."}]}
```

`bd` reads, cached (a task 5 s). `fields` and `comments` are the tracker's, shown as given (empty text is omitted from the
page); `comments` are oldest first. 404: the tracker has no such task; 500/503: the read failed and nothing was read before (the
drawer says so and offers a retry).

Lines, prompt and outputs of an attempt are read behind the evidence reader;
all of it is display only, never control state.

### Live event

One line. `id` identifies a command or tool so its `finished` event replaces its `running` one. Unused fields are `null`.

| `type` | fields | shows |
|---|---|---|
| `step` | `step`, `attempt` | 🚦 attempt started |
| `command` | `id`, `cmd`, `state` (`running`, `finished`, or `unfinished`: its attempt ended with no finish line), `waited_ms`, and when finished `duration_ms`, `exit_code` | 💻 the command and how long it ran (a running one counts up); the exit code in red when not 0; `waited_ms` as the "agent thought" line before it |
| `tool` | `id`, `name`, `cmd` (its main argument), `state`, `waited_ms`, `duration_ms` | 🧰 a non-shell tool call (file edit, search, MCP call) |
| `message` | `text`, `waited_ms` | 💬 an agent message |
| `error` | `text` | ❌ the harness's failure text |
| `waiting` | `text` | ⏳ the harness is retrying, reconnecting or waiting for the network |
| `check` | `name`, `passed`, `duration_ms` | 🧪 name, passed or failed, duration |

Every event carries `at` (when the action began). `waited_ms` is measured by the producer: from the previous action's end to
this one's start. The agent lines come from `any_agent.activity` (one record per action, the same model for Codex, Claude
Code and OpenCode); the factory never parses a vendor line.

### Agent lines: `GET /api/tasks/<id>/attempts/<step>/<n>/feed[?after=<cursor>]`

```json
{"events": [ <live event>, ... ], "cursor": "93375728:4096", "replaced": false, "available": true}
```

Without `after`: the attempt's latest 20 actions, oldest first. With `after`: what came after that cursor. The cursor is
opaque (the page hands back what it was given). `replaced` is true when the cursor was not this attempt's file (replaced
or shorter): `events` are then the fresh tail and the page drops its lines first. `available` is false when the attempt
has no events file yet (an attempt from before the file existed, one that never ran an agent, or one whose agent has not acted yet; its `cursor` is `0:0`, which follows the file from its first byte once it appears); that is evidence
availability, not the attempt's state. A bad cursor is a 400; an unknown attempt or a checks attempt is a 404. The same
last-20 and cursor are in the task detail (`feed`, `feed_cursor` of each agent attempt).

### Stream: `GET /api/events` (SSE)

Each message is one of:

```json
{"kind": "task", "task": <card>}
{"kind": "log", "row": <log row>}
```

A `task` message replaces the card of that id (a changed `column` is the move); the page animates the difference and,
if that task's drawer is open, reloads its detail because a step or attempt began or ended. The agent's lines are not on the stream: the open
drawer follows the selected running attempt through the feed endpoint every 2 s with its cursor, and stops when the drawer
closes or another attempt is selected. The page loads the snapshot first, then the stream, and the detail when a drawer opens.

## Backend

| Piece | Module | Reads |
|---|---|---|
| server, stream, static page | `dash_server` (the one importer of `http.server`) | calls the ports below; one poller thread, only while a page is connected |
| wiring, `--dash-port` | `dash_composition`, `cli_step` | the same read-only factory.db opening as `tl step list`, one per request |
| board | `dash_board` | `attempt_status.list_attempts`, the tracker's ready tasks and titles |
| task detail | `dash_task` | attempts, checks attempts and their results, hold, evidence files, the tracker's task and comments |
| tracker reads | `dash_tracker`, `tracker_client` | `bd` (cached: titles for good, ready 10 s, a task 5 s; a failure keeps the last answer and sets the board's `notice`) |
| round log | `round_reader`, `EvidenceFiles.round_tail` | `rounds.log`, display only |
| agent lines | `activity_file`, `EvidenceFiles.activity_tail/activity_after`, `command_sink` | the attempt's `events.jsonl`, written while the agent runs (capped 8 MiB), display only |

Where a fact has no stored owner yet the page shows a proxy or nothing, never a guess:

- **Step and attempt start**: an attempt row stores none. The start is the modification time of its `input.txt` (written
  at admission); a checks attempt's is its first check's start; a held task's is the hold's `held_at`; a landed task's the
  land's `closed_at`. End: the slot release or the checks attempt's `concluded_at`, else none (shown as a dash).
- **Quiet**: from `last-command` (the B10 fact), only while the attempt's entry runs.
- **Restart at plan**: derived (a plan attempt with a task `seq` above 1); the reason is not recorded, so it reads
  "restarted at plan".
- **Tracker**: priority, labels, design, notes, dates, dependencies and comments through new `tracker.py` reads.

### Not in slice 1

- **Agent lines of attempts that ran before `events.jsonl` existed**: `available: false`, "No lines recorded"; nothing is
  rebuilt from `stdout.txt`. Full retained history (older than the latest 20) and session-reuse bounds are tl-8bh9.7.4 and
  tl-8bh9.7.1's remainder ([plan](tl-8bh9.7.4/plan.md)).
- **Exact start and end times**: need a start and end column on `attempt` (a schema version, therefore a factory.db
  discard, the owner's call) instead of the file-time proxies above.
- **Land attempts** in the history (the board's Land column and card are real).
- **Answers for failed agent runs**: `stdout`/`stderr`/`diagnostics` tails are not read yet; a failed check's log tail is.
- **Move words**: the Logs filter and colours know the real actions (`start relaunch repeat verify advance release publish
  report skip hold`); more words (`round`, `rounds`, `no_free_slot`) are shown as written.
