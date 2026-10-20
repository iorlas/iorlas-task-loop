# worker-run v1: how the engine asks a launcher to run one AI step

Status: implemented (delegate 0.14.0, task-loop 0.4.0). Owner: task-loop (the consumer), like agent-runs v1. Producer:
delegate's `route.py run`. Since task-loop 0.5.0 the engine has no launcher of its own: delegate is required.

## Why

The engine needs lane and model choice, plan limits, the credit ledger, lane-out marking and resume for every node.
Delegate already does the first four. The engine should not grow a second copy, and should not need a Claude session
(the Agent tool) to run a node.

## What stays in the engine

- Running checks and gates (outside any sandbox: a sandboxed worker cannot bind localhost on macOS).
- The task budget (sum of `cost` across calls), rounds, routing, landing, close.
- Git: the engine commits, squashes and lands. Workers leave changes uncommitted.

## Call

```
<python> <route.py> run ROLE --cwd DIR --brief FILE
        [--schema FILE] [--resume REF] [--authored-by openai|claude] [--failed I,J]
        [--unattended] [--host | --no-sandbox] [--timeout SECS] [--cap USD] [--parent SESSION] [--task ID] [--title TEXT]
```

| flag | meaning |
|---|---|
| `ROLE` | delegate role. Engine mapping (since task-loop 0.6.0, no verify or judge step): plan → planner, write → worker, review → reviewer `--authored-by <family that wrote the thread, from the engine's record>` (`--writer` before delegate 0.17.0; the engine picks the flag by the installed version), a hard stage → hard |
| `--schema FILE` | JSON Schema for the answer. Codex: `--output-schema FILE`; claude: `--json-schema`. The producer parses the answer; it does not need to validate it (the engine does) |
| `--resume REF` | continue the thread or session `REF` from an earlier result, on the same lane. Codex: `codex exec resume REF` takes no `-s`/`-C`: set the sandbox with `-c sandbox_mode=...` and the folder through the process cwd. Claude: `--resume REF`. A lane that is now out → `status: "lane_out"`, never a silent switch to another lane (a new thread loses the writer's context; the engine decides) |
| `--unattended` | the caller is an engine, not a Claude session; required for engines (delegate 0.19.0+; `--headless` in 0.18.x, no alias). The engine passes it and no `--timeout`/`--cap` (delegate has no default limits since 0.18.0); before 0.18.0 the engine passes `--timeout` instead. The engine still kills a worker at its own `engine.node_timeout_min` |
| `--host` | delegate 0.23.0+: this work needs the host (Unity, an editor, devices); it cannot run in a sandbox. 0.24.0+: any lane takes it; a Claude step gets Bash with it (a read-only step too) under the auto classifier; Codex runs as without it: workspace-write or read-only sandbox, no network, and its automatic reviewer approves or refuses each command that asks to leave the sandbox. 0.23 sent it to Claude only. A `--resume` whose host flag differs from the original run answers `error`. The engine passes it on every step from 0.24 (on write steps only for 0.23) when `.task-loop.json` on the base branch grants it (`engine.host`, `engine.host_beads`) |
| `--no-sandbox` | delegate 0.20.0–0.22.x, removed in 0.23.0 (no alias): Codex runs `-s danger-full-access`, a read-only `claude -p` gets Bash; write steps from 0.20.0, every step from 0.21.0. The engine sends it instead of `--host` to a delegate older than 0.23.0, gated per step on the installed version (older still: one ⚠, the step runs sandboxed) |
| `--cap USD` | spend cap for this call (credit lanes). Absent → the role's step cap |
| `--parent`, `--task`, `--title` | written into the agent-runs record (`parent_session`, `task`, `title`). The engine strips `CLAUDE_*` from the child env, so `$CLAUDE_CODE_SESSION_ID` is not there to read |

The brief is passed as a file (or stdin when `--brief` is absent). The producer may prepend its git rules.

## Output and headless mode

- `run` always prints exactly one JSON object (below) on stdout, for every caller; worker chatter and diagnostics go
  to stderr.
- Unattended is `--unattended` (delegate 0.19.0+; `--headless` in 0.18.x). Before 0.18.0 it was derived from the environment: no
  `CLAUDE_CODE_ENTRYPOINT` (the engine strips `CLAUDE_*`, and still does for the child env). Then: never `agent`, never `ask_user`, never `needs_input`; Agent-tool lanes are
  unavailable; unknown subscription use does not block.

## Result (stdout, one object)

| field | type | meaning |
|---|---|---|
| `v` | 1 | contract version |
| `status` | `done` \| `failed` \| `timeout` \| `lane_out` \| `stop` \| `error` | `lane_out`: this lane hit a limit during the call (`retry_after` says when); `stop`: no lane can run the role now, or delegate's state is busy (a lock held over 10 s, from 0.23.0); `error`: bad call or setup, permanent (retrying the same call cannot help, from 0.23.0) |
| `data` | object \| null | the parsed answer when `--schema` was given and the answer parsed |
| `text` | string | the raw final answer |
| `ref` | string \| null | thread id (codex) or session id (claude), for `--resume` and the live log |
| `lane`, `model`, `effort`, `family` | string | what ran; `family` is `openai` or `claude` |
| `cost` | number | dollars charged by this call (0 on a subscription) |
| `tokens` | object \| null | `{in, cached, out}`; `in` counts all input, cache reads (and Claude cache writes) included. Delegate 0.22.0+ |
| `secs` | number | wall clock |
| `run_id` | string | the agent-runs record id |
| `transcript` | string \| null | path of the worker's log file, when known |
| `retry_after` | number \| null | epoch seconds; with `lane_out` and `stop` |
| `say` | string | one human line; with `stop`, `error`, `failed` |
| `git_violation` | list of strings | git changes the worker made (see Git). Reported, never turned into a failure |
| `denied` | list of `{tool, input}` | delegate 0.23.0+: commands the Claude classifier refused (git writes left out); 0.24.0+ also escalations Codex's reviewer refused (`input` is the raw shell line). No status of its own: it rides on `done` or `failed`. An accident filter, not a boundary. Engine: an answer still invalid with a denial blocks the task "needs a human: <command>"; a valid answer with a denial is a ⚠ in the trace; a second denied write in the task (any lane, any run) blocks it with every refused command listed |

Exit code: 0 when the object was printed, whatever `status` says; non-zero only when the producer itself crashed
(then the engine treats the call as `error` and uses stderr).

## Behaviour the engine relies on

1. **Early record.** The agent-runs v1 record is written before the worker starts and updated with `ref` as soon as it
   is known (codex `--json`: the `thread.started` event; claude: the session id is chosen up front). The dashboard
   shows the live log from that moment. The engine then publishes no record of its own for that call.
2. **Process group.** The worker runs in its own process group; timeout kills the group (as `run` does today).
3. **Env.** The worker gets the caller's env minus `CLAUDE_*`, `ANTHROPIC_*` (except the key the producer sets) and
   `DELEGATE_*`, plus `DELEGATE_DEPTH=1`. stdin is closed after the brief.
4. **Git.** Measure only the cwd's HEAD and current branch, for every caller. Other refs and the worktree list change
   during a call when other slots of the same repo work and land in parallel; comparing them gives false violations.
   Cost: a worker that creates a side branch or worktree is no longer caught (accepted).
5. **Headless limits.** Lane limits come from what a headless process can read (codex app server, the credit ledger,
   a limits file). Unknown subscription use must not make the call wait for input.
6. **Encoding.** UTF-8 in and out, errors replaced (a cp1252 Windows console must not crash the call).

## Engine side

- route.py: `.task-loop.json → engine.delegate` (a path) when set, else the newest installed `iorlas-delegate` 0.14.0+.
  None → the task is blocked with the install command.
- `lane_out` and `stop` make the step wait (up to `engine.lane_wait_min`, 60), then block the task.
- `docs/dev/integrations.md` names the call sites.

## Claude nodes (owner, 2026-10-18)

Engine Claude nodes run on the subscription, never on API credit. Headless, delegate runs `CLAUDE_SUBSCRIPTION` with
`claude -p` on the logged-in subscription (no API key) and never picks `CLAUDE_CREDIT`; with no usable subscription
lane the answer is `stop` with `retry_after`. Subscription use comes from delegate's usage feeds (state.json from an
orchestrator, `~/.claude/state/max-limits.json` from the status line), and the orchestrator reserve applies when a
reading exists. Since delegate 0.18.0 (owner, 2026-10-19) a headless run no longer stops when every feed is stale: an
unattended factory keeps running. Before 0.18.0 it answered `stop`. A limit refusal marks the lane out (`lane_out`). Needs `claude auth login` on the machine.

`cost` is 0 on a subscription, so the engine's dollar budget does not see Claude nodes; the engine budgets minutes and
calls per task as well. Workers get `DELEGATE_DEPTH=1`: they cannot delegate.

Why delegate's roles and not an engine profile: routing.json roles say which model is adequate for a kind of work, true
for any caller. The orchestrator rules (never delegate plan or acceptance, consent prompts) are skill text the engine
never reads. In the engine, plan is an AI node because the plan lives in the bead; acceptance is a rule over the engine's
own checks, the cross-family review and the gate. A role no orchestrator needs → a new role in routing.json,
never a second table.

Usage feed (part of this contract): `route.py status --claude-usage '<get_usage plan.windows JSON>'` stores the reading;
delegate applies the reserve while the reading is fresh. In attended mode the coordinator feeds it every 20 minutes (the
status-line file exists only where a terminal session runs). Unattended has no feed: since 0.18.0 Claude nodes run
anyway, without the reserve.

Left to the engine (delegate never does these): waiting until `retry_after` on `stop`/`lane_out`; `--failed I,J` for the
`hard` role; acting on `git_violation`; staggering parallel `run` calls (delegate has no in-flight reservation yet, so N
launches in the same second can overshoot a lane threshold together); a per-run log of its own (agent-runs records are
deleted after 7 days and carry no token numbers; delegate 0.19.0 keeps its own history.jsonl with tokens).

delegate 0.19.0 behaviour the engine relies on: at most 4 runs in flight per lane (1 at 80%+ of the 5-hour window), a
full lane answers `stop`/`lane_out` with a jittered `retry_after`; a second `run` with the same `--task` while the first
is alive answers `stop`; killing route.py (SIGTERM, or the parent dying under `--unattended`) stops the worker; a state
lock held over 10 s answers `error`, which the engine retries twice after 30 s. From 0.23.0 that lock answers `stop` with
`retry_after` and `error` is permanent: the engine retries an `error` only once, without `--resume` (a resume whose host
flag differs from the original run is an `error`), and not at all otherwise.

Version: the result's `v` is checked by the engine; another major blocks the task (update task-loop).
