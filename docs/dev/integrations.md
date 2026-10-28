# What task-loop relies on (read before changing the dashboard, tl.py, or the skill's Workers section)

A plugin install ships only `skills/` and `hooks/`, so nothing here is loaded when someone just runs the loop.

task-loop reads formats it does not own. Each has one reader in `skills/task-loop/dash/server.py` (or `tl.py`); when a
format changes, only that reader changes, and a broken reader must cost one panel, never the page (the handler
returns an error for that request; parsers skip lines they cannot read).

| source | owner | reader | what breaks if it changes |
|---|---|---|---|
| agent-runs v1 (`~/.config/agent-runs`) | **us** (`docs/contracts/agent-runs-v1.md`); delegate is one producer | `contract_runs`, `contract_lanes` | nothing silently: other major versions are skipped |
| Claude Code transcripts `~/.claude/projects/*/<session>.jsonl`, subagents `<session>/subagents/agent-*.jsonl` + `.meta.json` | Anthropic, undocumented | `claude_events`, `transcript_of`, `find_transcript` (a task-view block's session) | orchestrator and subagent logs |
| `$CLAUDE_CODE_SESSION_ID`, `$CLAUDE_PID` in a session's Bash env; SessionStart hook stdin (`session_id`, `transcript_path`) | Anthropic | `tl.actor`, `tl.session_alive`, `tl.cmd_hook` | the per-session bd actor (fallbacks exist), heartbeat exit, log lookup |
| codex plugin job state `~/.claude/plugins/data/codex-openai-codex/state/*/jobs/*.json` (+ `.log`) | OpenAI's codex plugin | `codex_log_events` | Codex runs started through the plugin (they carry the launching `sessionId`) |
| Codex rollouts `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | OpenAI | `rollout_events` (with `exec_cmds` for the `exec` tool's code input), `find_transcript` | Codex runs started with `codex exec` |
| OpenCode sessions, SQLite `~/.local/share/opencode/opencode.db` (`OPENCODE_DB` overrides), tables `session`, `message`, `part` only (never the credential tables); delegate's family `xai`, kind `opencode` | OpenCode | `tl.opencode_*`, `opencode_events` (ADAPTERS `opencode`), `tl.transcript_of("xai", ses_...)` -> `opencode:ses_...`, `context_tokens` | Grok lane runs; read only, short timeout, a missing DB or unknown id is empty |
| `bd list --json`, `bd show --json`, `bd update --claim`, `bd heartbeat`, `bd reclaim`, `bd unclaim`, `bd provenance record` | beads (bd 1.3+) | `beads_of`, `tl.py` | the tree, claims, slots, provenance (provenance failures only warn) |

## Delegate

task-loop requires delegate for the engine (decided 2026-10-18: everyone installs both; power users never call
delegate directly). The two touch in three places only:

1. **agent-runs v1**: delegate publishes its `claude -p` runs and lane limits; the dashboard shows them. Delegate's
   side of it is described in its repo, `docs/dev/integrations.md`.
2. **The Workers table in `skills/task-loop/SKILL.md`** maps the loop's worker kinds (reader, writer,
   reviewer, hard) to delegate's role names. That mapping is the only delegate vocabulary in this plugin. When
   delegate renames roles or changes how it is asked, update that table.

3. **worker-run v1** (`docs/contracts/worker-run-v1.md`): the engine runs each AI step with `route.py run ROLE` and
   feeds usage with `route.py status --claude-usage` (`tl usage`). Code: `engine.find_route`, `engine.call_delegate`,
   `Engine.ai_delegate`, `tl.py` `usage`. Only route.py from delegate 0.14.0 or later is used; none installed, or an
   answer with another `v`, blocks the task with what to do. Delegate keeps its state in its plugin data dir, so always call the
   installed route.py, never a checkout's (a checkout reads `~/.config/delegate`, another store).

Never read delegate's files, and call `route.py` only through worker-run v1. A new need from delegate becomes a new optional
field or record in agent-runs v1 (minor) or v2 (breaking: change the spec, make the reader accept both, then the
producer).

## Changing the contract

- New optional field: add it to the spec table, read it with `.get()`, keep `v: 1`.
- Breaking change: write v2 in the spec, make the reader accept v1 and v2, release, then tell producers.
- Tests: `tests/test_dash.py`, class `Contract`.
