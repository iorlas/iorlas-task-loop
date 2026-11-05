# delegate.api: the one interface between task-loop and delegate

Owner: delegate (`src/delegate`, in this repo). task-loop imports `delegate.api` and nothing else of delegate; delegate imports nothing of
task-loop. Both rules are import-linter contracts (`.importlinter`) and ruff bans (`TID251`). It replaces worker-run v4 (the `route.py`
subprocess and its JSON wire): there is no process boundary to the router any more, only to the workers.

## Calls

| Call | In | Out |
|---|---|---|
| `run(request, started=None)` | `RunRequest`; `started(Handle)` fires when the worker exists | `RunResult` (contract 4 answer) |
| `status(claude_usage=None)` | the Claude plan's usage windows, when the caller has them | `Status` (lanes, cockpit, running, holds, roles, network) |
| `cancel(handle)` | the `Handle` from `started` | `WorkerEnd` (SIGTERM, SIGKILL after the grace; survivors named) |
| `accounts()` / `set_account(lane, enabled)` | | `list[Account]` (lane, enabled, ready, fix) / the owner's choice stored |
| `network(hosts=())` | vendor hosts, else all | reachable now (sockets only) |
| `contract()` | | contract.json: reasons with scope/permanence/retry, capabilities |
| `as_json(record)` | a `RunResult` or `Status` | its wire object |

## Rules

- `run` never raises for a delegate fault: any exception or `SystemExit` becomes a `RunResult` with `stop.reason == "crash"`.
  A worker's failure is a stop in the result (`stop` is null exactly when the call is done).
- Workers stay child processes in a process group of their own. `cancel` stops the group; a call on another thread then returns.
- One `run` at a time per process: the request's environment (`DELEGATE_LIVE_FILE`, `worker_env`) is set on `os.environ` for its duration.
- Signal handlers are installed on the main thread only.
- `RunRequest.tools` (tool servers the factory provides for the call, bound to bead, run, stage and attempt) is carried and not wired to any
  harness yet; a spike proves injection per harness first (tl-jvpm.10).
- `writer_exec_allow` is honored for a Codex (openai) write step only; delegate validates binaries against its `host.json`. A granted argv
  runs writer-written code on the host with network until NETISO (tl-7i9k.59) lands.

## State

Settings, the account profile, lane state and history live in `<XDG_CONFIG_HOME or ~/.config>/task-loop/delegate` (`DELEGATE_CONFIG_DIR`
overrides). The first use copies the retired plugin's data dir (`~/.claude/plugins/data/iorlas-delegate-iorlas-marketplace`) there, once.
The state is shared by every process that calls the API: a two-process test (leases, resume refs, history) holds it to that.

## Consumers

`src/taskloop/adapters/delegate.py` (`call`, `status_json`, `accounts`, `RouteProbe`), `adapters/runner.py` (`ApiRunner`: the thread, the
live file, `cancel` at the wall limit or a stop of the run), `domain/lanes/policy.py` (`stop_of`, `decide`). Setup and status of accounts:
`tl accounts`, `tl setup`.
