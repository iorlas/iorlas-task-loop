# worker-run v1: how the engine asks a launcher to run one AI step (draft, 2026-10-18)

Status: proposed, not implemented. Owner: task-loop (the consumer), like agent-runs v1. First producer: delegate's
`route.py run`. Without a producer the engine keeps its built-in launcher (`call_codex`, `call_claude` in
`skills/task-loop/engine.py`), so nothing here is required for task-loop to work.

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
<python> <route.py> run ROLE --json --headless --cwd DIR --brief FILE
        [--schema FILE] [--resume REF] [--writer openai|claude] [--failed I,J]
        [--timeout SECS] [--cap USD] [--parent SESSION] [--task ID] [--title TEXT]
```

| flag | meaning |
|---|---|
| `ROLE` | delegate role. Engine mapping: plan → planner, write → worker, verify → reviewer `--writer <write family>`, review → reviewer `--writer <write family>`, judge → light, a hard stage → hard |
| `--json` | stdout is exactly one JSON object (below), nothing else. Worker chatter and diagnostics go to stderr |
| `--headless` | no human and no Claude session behind the caller: never answer `agent`, never `ask_user`, never `needs_input`. Lanes that need the Agent tool count as unavailable unless a headless runner exists for them |
| `--schema FILE` | JSON Schema for the answer. Codex: `--output-schema FILE`; claude: `--json-schema`. The producer parses the answer; it does not need to validate it (the engine does) |
| `--resume REF` | continue the thread or session `REF` from an earlier result, on the same lane. Codex: `codex exec resume REF` takes no `-s`/`-C`: set the sandbox with `-c sandbox_mode=...` and the folder through the process cwd. Claude: `--resume REF`. A lane that is now out → `status: "lane_out"`, never a silent switch to another lane (a new thread loses the writer's context; the engine decides) |
| `--cap USD` | spend cap for this call (credit lanes). Absent → the role's step cap |
| `--parent`, `--task`, `--title` | written into the agent-runs record (`parent_session`, `task`, `title`). The engine strips `CLAUDE_*` from the child env, so `$CLAUDE_CODE_SESSION_ID` is not there to read |

The brief is passed as a file (or stdin when `--brief` is absent). The producer may prepend its git rules.

## Result (stdout, one object)

| field | type | meaning |
|---|---|---|
| `v` | 1 | contract version |
| `status` | `done` \| `failed` \| `timeout` \| `lane_out` \| `stop` \| `error` | `lane_out`: this lane hit a limit during the call (`retry_after` says when); `stop`: no lane can run the role now; `error`: bad call or setup |
| `data` | object \| null | the parsed answer when `--schema` was given and the answer parsed |
| `text` | string | the raw final answer |
| `ref` | string \| null | thread id (codex) or session id (claude), for `--resume` and the live log |
| `lane`, `model`, `effort`, `family` | string | what ran; `family` is `openai` or `claude` |
| `cost` | number | dollars charged by this call (0 on a subscription) |
| `secs` | number | wall clock |
| `run_id` | string | the agent-runs record id |
| `transcript` | string \| null | path of the worker's log file, when known |
| `retry_after` | number \| null | epoch seconds; with `lane_out` and `stop` |
| `say` | string | one human line; with `stop`, `error`, `failed` |
| `git_violation` | list of strings | git changes the worker made (see Git). Reported, never turned into a failure |

Exit code: 0 when the object was printed, whatever `status` says; non-zero only when the producer itself crashed
(then the engine treats the call as `error` and uses stderr).

## Behaviour the engine relies on

1. **Early record.** The agent-runs v1 record is written before the worker starts and updated with `ref` as soon as it
   is known (codex `--json`: the `thread.started` event; claude: the session id is chosen up front). The dashboard
   shows the live log from that moment. The engine then publishes no record of its own for that call.
2. **Process group.** The worker runs in its own process group; timeout kills the group (as `run` does today).
3. **Env.** The worker gets the caller's env minus `CLAUDE_*`, `ANTHROPIC_*` (except the key the producer sets) and
   `DELEGATE_*`, plus `DELEGATE_DEPTH=1`. stdin is closed after the brief.
4. **Git.** Measure only the cwd's HEAD and current branch. Other refs and the worktree list change during a call
   when other slots of the same repo work and land in parallel; comparing them gives false violations.
5. **Headless limits.** Lane limits come from what a headless process can read (codex app server, the credit ledger,
   a limits file). Unknown subscription use must not make the call wait for input.
6. **Encoding.** UTF-8 in and out, errors replaced (a cp1252 Windows console must not crash the call).

## Engine side (when built)

- `.task-loop.json` → `engine.launcher`: `"builtin"` (default today), `"delegate"`, or an explicit command prefix.
  `"delegate"` finds route.py in the newest installed `iorlas-delegate` plugin; missing → builtin, with a ⚠ line.
- `lane_out` and `stop` pause the task until `retry_after` (later: pause the dispatch pass); they never fail it.
- `docs/dev/integrations.md` changes from "never call route.py" to "call it only through this contract".

## Open

- Subscription Claude headless: delegate's `CLAUDE_SUBSCRIPTION` lane runs through the Agent tool only. A headless
  runner (`claude -p` on the logged-in subscription) plus a headless reader of its use would let the engine use it;
  until then Claude nodes run on `CLAUDE_CREDIT` (API dollars, $150/month cap on this Mac).
