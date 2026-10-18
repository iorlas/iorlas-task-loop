# task-loop dashboard: strategy (v2, after Fable review 2026-10-18)

## Goal
Real time: which tasks are in flight, in which repo; click a task, see every session working on it with a live
log (the orchestrating Claude session, Agent-tool subagents, Codex runs, `claude -p` runs). Also the whole
backlog as a tree. Viewable from the phone over Tailscale.

## Ownership
- New plugin repo `iorlas-task-loop`, in iorlas-marketplace; ideas tracked as beads there.
- task-loop owns the dashboard and the recording. Delegate is suggested, not required, and its files are never
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
