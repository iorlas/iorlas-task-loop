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
- The Attempts tab is a master and a detail. Left, the **attempt rail**: every attempt of the task, **newest first** so
  the running attempt is what the drawer shows on opening (Lines still follow the tail: new lines at the bottom), one
  aligned row each (step, number, duration; a failed one adds its summary). Between two rows a
  jump names how the next attempt began: `↻ Repeat` (the same step again) or `↩ Back to plan` (restarted at plan, D4)
  with its reason when that adds something; the label sits under the attempt it began. Steps still to come are dim rows
  above the newest. A task with ten attempts is ten rows and the rail scrolls. Right, the selected attempt, in three tabs:
  - **Lines**: the log grid (below). Opens first for a running attempt.
  - **Result**: the conclusion, the agent's answer (disposition and text) and for checks each check's result with its
    full output (a failed check shows its output at once). Opens first for an ended attempt.
  - **Prompt**: exactly what the agent was told in that attempt, repeat feedback included; a step that runs commands
    (checks, land) has none. The chosen tab stays when another attempt is selected, so prompts can be compared.
  An attempt that began as a jump also shows why, naming the attempt it follows ("Repeat of Checks #5").
- Design language: emoji only as step and column icons (Plan, Implement, Checks, Land, Held, Landed), never for state
  or log lines. A state is a coloured dot and a word, a badge is one outlined label, a
  reason is a callout (one accent line, no fill: amber repeat, violet back to plan, rose held or failed, sky running,
  green succeeded), numbers are tabular and right-aligned, colour means status only. The first mocks used emoji for
  everything and read as noise; the owner accepts a few.
- Header: id, title, then the facts line, the description and, for a held task, the cause.
- **Quiet**: a running step that has produced no line for 2 minutes shows `Quiet 5m 40s` (amber; red from 15 minutes)
  on its card, with a coloured card border, and in the drawer. Any new line resets it. Display only, from the time of
  the latest agent line (the B10 fact); it decides nothing and the word stuck stays the engine's.
- A line is one row of a grid, never raw JSON: offset from the attempt's start, kind (`CMD`, `MSG`, `CHECK`, `STEP`),
  content, duration right-aligned (with the exit code in red when not 0). Before a command, when the agent took 2 s or
  more to issue it, a faint "agent thought 33s" line. That number is the time from the previous line to this command's
  start; it is *not* part of the command's own duration (the first mock showed both as unlabeled durations).
- Stack: plain HTML and vanilla JS ES modules (`app.js` board, `drawer.js`, `logs.js`, `ui.js`), no framework, no bundler, no npm
  at runtime. `mock.js` is the throwaway fake source, deleted when the server slice lands. Styling is Tailwind compiled once; `dash.css` is committed, so nobody
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
  "fields": {"priority": "P1", "labels": ["auto"], "branch": "task/tl-7d5", "claimed_by": "factory@devbox",
             "created_at": "...", "updated_at": "...", "depends_on": ["tl-6e6"],
             "description": "...", "acceptance": "...", "design": "...", "notes": "..."},
  "comments": [{"author": "factory", "at": "...", "text": "..."}],
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
`feed` is the last 20 lines of that attempt, oldest first. `fields` and `comments` are the tracker's, shown as given (empty
text is omitted from the page); `comments` are oldest first. Lines, prompt and outputs are read behind the evidence reader;
all of it is display only, never control state.

### Live event

One line. `id` identifies a command so its `finished` event replaces its `running` one.

| `type` | fields | shows |
|---|---|---|
| `step` | `step`, `attempt` | `STEP` attempt started |
| `command` | `id`, `cmd`, `state` (`running` or `finished`), `waited_ms`, and when finished `duration_ms`, `exit_code` | `CMD` the command and how long it ran (a running one counts up); the exit code in red when not 0; `waited_ms` as the "agent thought" line before it |
| `message` | `text` | `MSG` an agent message |
| `check` | `name`, `passed`, `duration_ms` | `CHECK` name, passed or failed, duration |

Every event carries `at`. `waited_ms` is measured by the producer: from the previous event's end to this command's start.

### Stream: `GET /api/events` (SSE)

Each message is one of:

```json
{"kind": "task", "task": <card>}
{"kind": "log", "row": <log row>}
{"kind": "feed", "task_id": "tl-7c4", "step": "implement", "attempt": 1, "event": <live event>}
```

A `task` message replaces the card of that id (a changed `column` is the move); the page animates the difference and,
if that task's drawer is open, reloads its detail because a step or attempt began or ended. A `feed` message appends to
the named attempt's lines. The page loads the snapshot first, then the stream, and the detail when a drawer opens.

## Mock mode

`fixtures.json` holds `tasks` (ages as `*_ago_s` seconds so the data never goes stale), `slots`, `rounds` (the log), `comments`, `history` (per task: stages of
attempts with lines, grouped by start from plan; `mock.js` flattens them) and `script`: timed steps (`after_s`) that replay as stream messages, with task steps as patches
merged into the current card. `mock.js` keeps its own detail in step with them. The fixture covers every column, a
task restarted at plan, repeats, a held task with its cause, landed tasks and one long feed.
