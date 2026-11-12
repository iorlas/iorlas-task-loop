# Dashboard UI (mock, proposed)

Status: **proposed**. The page under `src/taskloop/dash/static/` renders fake data from `fixtures.json` so the owner
can judge the look. No server, no live data and no runtime code exist yet; the backend slices implement the shapes
below. Terms: [dashboard, board, live tail](../glossary.md). This is separate from the retired round mockups in
`docs/design/dashboard/`, which were ideas only.

## Decisions (owner design interview, 2026-11-12, and review of the first mock)

- Read-only: no buttons that change anything, no auth, no charts, no history pages. The controls are the theme switch,
  the board layout switch and drawer navigation.
- One board on one screen. A card is a task, newest activity first in its column. Columns: Ready, Plan, Implement,
  Checks, Land, Held, Landed (the glossary says *ready* for a task not yet admitted; the interview said "Waiting").
- Two layouts of the same board: **Steps** (one column per step) and **By slot** (swim lanes: one row per slot, plus
  "no slot" for tasks holding none). Switching animates the cards into place.
- A card shows task id and title, attempt number, a *repeat* or *restarted at plan* badge with its reason, time in the
  current step, slot, and the hold cause. A card that changes column animates to its new place.
- Clicking a card opens a wide drawer (see below): task fields, then the task's history, then the lines of one attempt.
- The drawer's history is one **trail** of attempts in the order they happened, left to right, wrapping. A label between
  two nodes names a jump: `↻ repeat` (the same step again) or `↩ back to plan` (restarted at plan, D4); an ordinary
  advance is a plain arrow. Dashed nodes at the end are the steps still to come. Click a node to see that attempt: how it
  ended, why it began (the jump reason) and its lines. Clicking nothing selects the last attempt. No tabs: the first mock's
  "From plan N" tabs showed that a restart happened but not why or from where.
- Header: id, title, then one muted line of facts (column, slot, priority, task branch, created), the description and,
  for a held task, the cause.
- **Quiet**: a running step that has produced no line for 2 minutes shows `💤 quiet 5m 40s` (amber; red from 15 minutes)
  on its card, with a coloured card border, and in the drawer's attempt bar. Any new line resets it. Display only, from
  the time of the latest agent line (the B10 fact); it decides nothing and the word stuck stays the engine's.
- A line is a compact styled row, never raw JSON: ⚙️ command with ⏱ how long it ran (❌ and the exit code when not 0),
  💬 agent message, ✅/❌ check result with its duration, 🚦 attempt started. Before a command, when the agent took
  2 s or more to issue it, a faint 🤔 "agent thought 33s" hint. That number is the time from the previous line to this
  command's start; it is *not* part of the command's own duration (the first mock showed both as unlabeled ⏱ and ⌛).
- Stack: plain HTML, one vanilla JS ES module (`app.js`), no framework, no npm at runtime. `mock.js` is the throwaway
  fake source, deleted when the server slice lands. Styling is Tailwind compiled once; `dash.css` is committed, so nobody
  installs Tailwind to use or serve the page. Light and dark theme follow the system; the switch overrides and is
  remembered in `localStorage` (optional, failure ignored).
- Later slices: a stdlib server in a thread of the rounds process, JSON endpoints and SSE. Typed agent events come from
  any-agent. The page already consumes the shapes below; `mockSource` is the one part to replace.

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
  "hold_cause": null
}
```

`column` is one of `waiting plan implement checks land held landed` (`waiting` is shown as Ready). `attempt` is the
number of the current or last attempt of the step (0 before any). `repeat` is `null` or `{kind, reason}`: `repeat` is a
new attempt of the same step, `restart_at_plan` is a task sent back to plan. `step_started_at` starts "time in step"
(for Landed: time since landing). `last_activity_at` is the sort key (newest first): the last step change or live
event. `slot` is `null` when the task holds none. `hold_cause` is the sentence the hold owner already shows, only in
`held`.

### Board snapshot: `GET /api/board`

```json
{"generated_at": "2026-11-12T10:22:00Z", "slots": ["s1", "s2"], "tasks": [ <card>, ... ]}
```

`slots` lists every slot, so By slot shows idle ones.

### Task detail: `GET /api/tasks/<id>`

```json
{
  "task": <card>,
  "fields": {"priority": "P1", "labels": ["auto"], "branch": "task/tl-7d5", "claimed_by": "factory@devbox",
             "created_at": "...", "description": "..."},
  "attempts": [
    {"step": "implement", "n": 2, "state": "failed", "started_at": "...", "ended_at": "...",
     "summary": "failed: deadline exceeded after 30m",
     "after": "repeat", "reason": "failed: the agent finished without a diff",
     "feed": [ <live event>, ... ]}
  ]
}
```

`attempts` is every attempt of the task, oldest first. `n` counts per step. `state` is `running`, `succeeded` or `failed`;
`summary` says how it ended (the verdict or conclusion the owner of that fact already states); `ended_at` is `null`
while running. `after` says how the attempt began: `null` (the previous step succeeded), `repeat` or `restart_at_plan`,
with the `reason` the engine recorded. `feed` is the last 20 lines of that attempt, oldest first, read behind the
evidence reader; display only, never control state.

### Live event

One line. `id` identifies a command so its `finished` event replaces its `running` one.

| `type` | fields | shows |
|---|---|---|
| `step` | `step`, `attempt` | 🚦 attempt started |
| `command` | `id`, `cmd`, `state` (`running` or `finished`), `waited_ms`, and when finished `duration_ms`, `exit_code` | ⚙️ the command, ⏱ how long it ran (a running one counts up); ❌ and the exit code when not 0; 🤔 `waited_ms` = how long the agent took before issuing it |
| `message` | `text` | 💬 an agent message |
| `check` | `name`, `passed`, `duration_ms` | ✅ or ❌ a check result |

Every event carries `at`. `waited_ms` is measured by the producer: from the previous event's end to this command's start.

### Stream: `GET /api/events` (SSE)

Each message is one of:

```json
{"kind": "task", "task": <card>}
{"kind": "feed", "task_id": "tl-7c4", "step": "implement", "attempt": 1, "event": <live event>}
```

A `task` message replaces the card of that id (a changed `column` is the move); the page animates the difference and,
if that task's drawer is open, reloads its detail because a step or attempt began or ended. A `feed` message appends to
the named attempt's lines. The page loads the snapshot first, then the stream, and the detail when a drawer opens.

## Mock mode

`fixtures.json` holds `tasks` (ages as `*_ago_s` seconds so the data never goes stale), `slots`, `history` (per task: stages of
attempts with lines, grouped by start from plan; `mock.js` flattens them) and `script`: timed steps (`after_s`) that replay as stream messages, with task steps as patches
merged into the current card. `mock.js` keeps its own detail in step with them. The fixture covers every column, a
task restarted at plan, repeats, a held task with its cause, landed tasks and one long feed.
