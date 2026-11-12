# Dashboard UI (mock, proposed)

Status: **proposed**. The page under `src/taskloop/dash/static/` renders fake data from `fixtures.json` so the owner
can judge the look. No server, no live data and no runtime code exist yet; the backend slices implement the shapes
below. Terms: [dashboard, board, live tail](../glossary.md). This is separate from the retired round mockups in
`docs/design/dashboard/`, which were ideas only.

## Decisions (owner design interview, 2026-11-12)

- Read-only: no buttons that change anything, no auth, no charts, no history pages. The only control is the theme switch.
- One board on one screen. A card is a task, newest activity first in its column. Columns: Waiting, Plan, Implement,
  Checks, Land, Held, Landed.
- A card shows task id and title, attempt number, a replan or repeat badge with its reason, time in the current step,
  slot, and the hold cause. A card that changes column animates to its new place.
- Clicking a card opens a drawer: task fields and metadata, the attempts so far and the live tail of the current attempt
  (the last 20 lines at most): commands run, how long each ran, how long we waited before it, agent messages and check
  results, as compact styled lines. Never raw JSON.
- Stack: plain HTML, one vanilla JS ES module, no framework, no npm at runtime. Styling is Tailwind compiled once;
  `dash.css` is committed, so nobody installs Tailwind to use or serve the page. Light and dark theme follow the system;
  the switch overrides and is remembered in `localStorage` (optional, failure ignored).
- Later slices: a stdlib server in a thread of the rounds process, JSON endpoints and SSE. Typed agent events come from
  any-agent. The page already consumes the shapes below; `mockSource` in `app.js` is the one part to replace.

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
  "repeat": {"kind": "replan", "reason": "plan rejected: ..."},
  "step_started_at": "2026-11-12T10:15:00Z",
  "last_activity_at": "2026-11-12T10:21:50Z",
  "slot": "slot-2",
  "hold_cause": null
}
```

`column` is one of `waiting plan implement checks land held landed`. `attempt` is the number of the current or last
attempt of the step (0 before any). `repeat` is `null` or `{kind: "replan" | "repeat", reason}`; replan means the task
went back to plan, repeat means the same step ran again. `step_started_at` starts "time in step" (for Landed: time since
landing). `last_activity_at` is the sort key (newest first): the last step change or live event. `hold_cause` is the
sentence the hold owner already shows, only in `held`.

### Board snapshot: `GET /api/board`

```json
{"generated_at": "2026-11-12T10:22:00Z", "tasks": [ <card>, ... ]}
```

### Task detail: `GET /api/tasks/<id>`

```json
{
  "task": <card>,
  "fields": {"priority": "P1", "labels": ["auto"], "branch": "task/tl-7d5", "claimed_by": "factory@devbox",
             "created_at": "...", "description": "..."},
  "attempts": [{"n": 1, "step": "implement", "started_at": "...", "result": "failed: ..."}],
  "feed": [ <live event>, ... ]
}
```

`feed` is the last 20 events of the current attempt, oldest first. `fields` are the tracker's, shown as given.

### Live event

One line of the live tail. `id` identifies a command so its `finished` event replaces its `running` one.

| `type` | fields | shows |
|---|---|---|
| `step` | `step`, `attempt` | 🚦 entered the step |
| `command` | `id`, `cmd`, `state` (`running` or `finished`), `waited_ms`, and when finished `duration_ms`, `exit_code` | ⚙️ the command, ⏱ how long it ran (a running one counts up), ⌛ how long we waited for the agent before it started; ❌ when `exit_code` is not 0 |
| `message` | `text` | 💬 an agent message |
| `check` | `name`, `passed`, `duration_ms` | ✅ or ❌ a check result |

Every event carries `at`. Waiting time is measured by the producer from the previous event to this command's start.

### Stream: `GET /api/events` (SSE)

Each message is one of:

```json
{"kind": "task", "task": <card>}
{"kind": "feed", "task_id": "tl-7c4", "event": <live event>}
```

A `task` message replaces the card of that id (a changed `column` is the move); the page animates the difference. The
page loads the snapshot first, then the stream, and loads the detail when a drawer opens.

## Mock mode

`fixtures.json` holds `tasks` (ages as `*_ago_s` seconds so the data never goes stale), `feeds`, `attempts` and `script`:
timed steps (`after_s`) that replay as stream messages, with task steps as patches merged into the current card. The
fixture covers every column, a replanned task (attempt 3), a held task with its cause, landed tasks and one task with a
long feed.
