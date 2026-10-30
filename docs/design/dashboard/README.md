# task-loop dashboard

One read-only server per machine (`python3 -m taskloop_dash` on the interpreter `tl dash ensure` runs on, so it has msgspec), one page, one API.

- **The rule:** [dash-spec.md](dash-spec.md). Owner decisions: [dash-decisions.md](dash-decisions.md). The mocks it names
  (`dash-round-*.html`) show the result; older mocks are history.
- **The API:** [docs/contracts/dash-api.md](../../contracts/dash-api.md), records in `src/taskloop/contracts/dash.py`.
- **What it reads:** the engine logs, asks, the ask ledger, decisions, loop state and lane status under `~/.config/task-loop`,
  and bd through the typed `Beads` port. It runs no process and writes only through `Ports` (the owner's verbs). Every format
  it does not own is in [docs/dev/integrations.md](../../dev/integrations.md).

## Code

| where | what |
|---|---|
| `src/taskloop_dash/static/` | the page: `index.html`, ES modules under `js/`, CSS under `css/`, Preact + HTM vendored in `vendor/` (pinned by hash). No build, no CDN, 100 KB gzip budget (`tests/dash/test_dash_static.py`) |
| `src/taskloop_dash/http.py` | the routes: the page and its modules, GET `/api/snapshot`, `/api/bead`, `/api/live`, `/api/artifact`, `/api/look-shot`, `/api/version`, POST `/api/<verb>` |
| `src/taskloop_dash/api/` | `reads.py` (snapshot with ETag, bead), `liveview.py` + `live.py` (the live tail), `writes.py` (the verbs), `looks.py`, `artifacts.py` |
| `src/taskloop_dash/readers/` | `world.py` gathers one `World` per snapshot from records, bd, runs and looks |
| `src/taskloop_dash/views/` | pure builders from the world to the contract records (`snapshot.py`, `bead_detail.py`, `board.py`, `passes.py`, ...) |
| `dev/dash_fixtures.py` | the page against `tests/fixtures/dash/`, no engine |
| `dev/dash_check.py` | headless-Chrome checks of the page against the fixtures, or read-only against a running dash (`--base`) |

## Server

- Bind: 127.0.0.1 plus the Tailscale address when present (`TASK_LOOP_DASH_BIND` overrides, `TASK_LOOP_DASH_PORT` the port).
  A POST from loopback or Tailscale needs no token; any other source needs `dash.token` (`bind.post_allowed`).
- `/api/version` names the code that runs; `tl dash ensure` restarts a server whose code is older.
- It exits after hours with no task-loop event and no page request (`TASK_LOOP_DASH_IDLE_H`, default 6).
- A broken record answers that request with a 500 and the error; it never takes the page down.
