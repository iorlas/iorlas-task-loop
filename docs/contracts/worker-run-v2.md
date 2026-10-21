# worker-run v2: how the engine asks delegate to run one AI step

Status: implemented (task-loop 0.15.0, delegate 0.29). Owner: task-loop (the consumer). Producer: delegate's
`route.py run`. Replaces [worker-run v1](worker-run-v1.md); there is no v1 shim on either side.

## Why v2

Under v1 the engine knew too much about delegate: it parsed `say` for "oauth session expired" and "ENOTFOUND",
guessed that a fast failure with no tokens was a vendor blip, carried five version checks, wrote its own sandbox and
escalation text into worker briefs, and re-asked on output that did not fit the schema. On 2026-10-20 three of six
failures came from that layer. v2 moves each of these to delegate and gives the engine one rule to act on.

## What stays in the engine

- Running checks and the gate (outside any sandbox), rounds, replans, routing, landing, close.
- Git: the engine commits, squashes and lands. Workers leave changes uncommitted.
- Policy: how long to wait, when to pause, what to ask the owner. Delegate says what happened; the engine decides.
- Steps and roles: plan → `planner`, write → `worker`, review → `reviewer`; before a verify ask at land (0.15.6), one
  verify step → `reviewer` (read-only rungs) with `--authored-by` the writer's family and the `verify` schema
  (`items: [{n, verdict: settled|wrong|open, evidence, why}]`). A verify step that pauses or fails lands nothing: every
  item goes to the owner.

## Handshake

```
<python> <route.py> contract --json
```

prints one line:

| field | meaning |
|---|---|
| `worker_run` | 2. The engine refuses to start a task on anything else ("update delegate" or "update task-loop") |
| `features` | `reason`, `next`, `context`, `schema_reask`, `denied`, `tokens_include_child_threads`, `secrets_guard` |
| `reasons` | `{reason: next}`, the whole table below |
| `lanes` | what a worker sees, per lane (`codex`, `claude`, `both`): `sees`, `hidden`, `sandbox`, `cannot_block` |

The engine records `lanes` once per run in the trace, so a result can be traced to what the workers were given.

## Call

```
<python> <route.py> run ROLE --cwd DIR --brief FILE --unattended
        [--schema FILE] [--resume REF] [--authored-by openai|claude] [--failed I,J]
        [--host] [--parent SESSION] [--task ID] [--title TEXT]
```

| flag | meaning |
|---|---|
| `ROLE` | plan → planner, write → worker, review → reviewer `--authored-by <family that wrote the thread>`, a hard stage → hard |
| `--unattended` | always: the engine is no Claude session |
| `--schema FILE` | JSON Schema for the answer. Delegate checks it (type, required, properties, items, enum), re-asks once in the same thread, then answers `failed` / `schema_invalid` |
| `--resume REF` | continue a thread on the same lane; a lane now out answers `lane_out`, never a silent switch |
| `--host` | the work needs the host (Unity, an editor). Granted only by `.task-loop.json` on the base branch (`engine.host`, `engine.host_beads`) |

The brief is the task, the plan and the stage. It says nothing about sandboxes, escalation, credentials or git:
delegate prepends its own rules for those, per lane.

## Answer (stdout, one object, exit 0)

| field | meaning |
|---|---|
| `v` | 2 |
| `status` | `done`, `failed`, `timeout`, `lane_out`, `stop`, `error` (for wording; the engine acts on `next`) |
| `reason`, `next` | null on `done`; otherwise both set. `next` is the engine's whole policy; `reason` is for wording and stats only |
| `retry_after` | epoch seconds, with every `retry` |
| `context` | `{instructions: [repo instruction files given], env_keys: [names passed]}` |
| `data`, `text`, `ref`, `lane`, `model`, `effort`, `family`, `flag`, `cost`, `tokens`, `denied`, `secs`, `run_id`, `transcript`, `say`, `git_violation` | as in v1. `tokens` include Codex's automatic reviewer and any sub-agent; with a schema re-ask, both turns are summed |

| `next` | reasons | engine |
|---|---|---|
| `retry` | lane_out, busy, duplicate_task, lock, vendor_prework, network, no_lane | wait in the slot until `retry_after`, up to `engine.lane_wait_min`; longer, pause (bead open, slot freed, checkpoint resumes it). Except `lane_out` on a `--resume` call, whether `next` is `retry` or `owner` (no `retry_after`): at once, once, the same call without `--resume` (a new thread gets the role's next rung; the brief says to continue the earlier writer's work in the tree); its thread and `family` become the writer's. That thread is a fallback for the lane `L` that was out (the checkpoint keeps `L`): each later write round reads `route.py status --json`; while `lanes[L].out` is false it calls without `--resume` with the same brief, so delegate can route back to `L`; while `L` is out it resumes the fallback thread; a status with no lane `L` makes it no fallback (tl-bxk.10.5). A retry from that call waits as above |
| `owner` | logged_out, setup, secrets, bad_request, crash; a retry reason with no `retry_after` | `logged_out`, `setup`: pause with the fix ("run claude auth login"), no ask. `lane_out` (a call that did not resume; a resumed one goes on as a new thread, see `retry`): pause "no lane", no ask. `secrets`, `bad_request`, `crash`: block with a verify ask naming `say` |
| `fail` | caller, timeout, worker_failed, schema_invalid | one more try: without `--resume` when the call resumed a thread (a refused resume is `caller`), else the same call once more; a second `fail` fails the task |

A retry reason with no `retry_after` answers `owner`. No answer object at all (route.py crashed, printed nothing, or the
engine's own node timeout killed it) counts as `fail`.

A refusal with `denied` is handled first (the denial rules below); `owner` raises its ask only when `denied` is empty,
so the secrets tripwire (`reason: secrets` with the blocked path in `denied`) asks once.

`denied` (commands the Claude classifier or Codex's reviewer refused, and the secrets tripwire's blocks) rides on any
status. The engine's rule stays: a refused command with no valid answer blocks the task "needs a human"; a second
refused write in a bead blocks it with every command listed; a valid answer with a refusal is a ⚠ in the trace.

## What delegate guarantees a worker sees (0.29.0)

- Codex: delegate's rules, the brief, the repo instruction files. Hidden: user config and rules, every skill (system,
  `~/.codex/skills`, `~/.agents/skills`, repo `.agents`/`.codex` skills), MCP servers, hooks. Sandbox workspace-write or
  read-only, no network; the automatic reviewer may let one command out. Cannot block: sub-agents (a brief that asks
  gets one; the brief says not to).
- Claude: delegate's rules, the brief, the repo instruction files appended. Hidden: user and repo settings, hooks except
  delegate's secrets guard, plugins, skills, MCP servers. The auto-mode classifier reviews every tool call; Bash only on
  write steps or with `--host`.
- Both: instruction files are AGENTS.md, else CLAUDE.md, in each folder from the repo root down to the cwd. The env is
  the caller's minus `CLAUDE_*`, `ANTHROPIC_*`, `DELEGATE_*` and credential-looking names.

## Behaviour kept from v1

Early agent-runs record, the worker in its own process group, UTF-8, git measured on the cwd's HEAD and branch only,
the engine's own `engine.node_timeout_min` kill. `route.py status --json` stays v1 and is one line; its `recent` rows
and delegate's history.jsonl carry `reason`.
