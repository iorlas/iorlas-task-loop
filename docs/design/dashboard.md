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

### Timeline records (engine log, since tl-bxk.12.3)
The engine log `engine/<bead>-<YYYYMMDD-HHMMSS>.jsonl` keeps its old records and text; these are added, never printed:
| kind | fields |
|---|---|
| `node` (existing) | + `id` (run-scoped, from 1), `step` reset/plan/replan/write/checks/review/verify/land/close, `stage`, `stages`, `write`, `round`, `fix`, `fixes`, `try` |
| `end` | `id`, `step`, `outcome` (green, red, clean, sent back, asks, paused, landed, gate red, ...), `detail`, `secs`, `sessions` [refs] |
| `transition` | `from` (node id), `to` (a step, `next`, `ask`, `pause`, `close`), `cause`, `detail`; `lane`, `until` on pauses |
| `checks` | `node_id`, `round`, `items` [{id, cmd, group, exit, status, secs, tries, cached, why, log}] |
| `run` | `run`, `bead`, `prev_run`, `started_because` first/answer/resume/retry/fresh, `ask`, `slot`, `worktree` |
| `session`, `msg` (existing) | + `node_id`; session + `resume`, `flag` |

Causes: checks_red, checks_green, review_sendback, accepted, bad_checks, rounds_used, writer_decided, plan_sent_back,
invalid_output, lane_out (a new thread), lane_wait, paused, decision/verify/ticket/stuck/waiting (an ask), verify_open,
verify_wrong, verified, gate_red, conflict, push_race, landed, done, failed, stopped. Check logs keep every round:
`checks/NN-id.rK.log`, `engine-checks.rK.json` (`engine-checks.json` is the latest). `traces.jsonl` lines add
`prev_run`, `started_because`, `ask`. Logs from before these records are read from their node/session/warn text.
There is no `judge` step: the engine has none yet.
