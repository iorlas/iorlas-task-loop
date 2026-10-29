# What task-loop relies on (read before changing the dashboard, tl.py, or the skill's Workers section)

A plugin install ships only `skills/` and `hooks/`, so nothing here is loaded when someone just runs the loop.

task-loop reads formats it does not own. Each has one reader in a module of `src/taskloop_dash/` (or `tl.py`); when a
format changes, only that reader changes, and a broken reader must cost one panel, never the page (the handler
returns an error for that request; parsers skip lines they cannot read).

| source | owner | reader | what breaks if it changes |
|---|---|---|---|
| asks `~/.config/task-loop/asks/<bead>.json` (`v` 3), the ask ledger `ask-ledger.jsonl`, decisions `decisions/<repo>-<hash>/ADR-n.json` + `uses.jsonl` | **us** (`taskloop.contracts.ask.Ask`) | `AskStore` and `LedgerStore` (`taskloop.contracts.stores`), `AdrStore` (`taskloop.contracts.adrs`): the engine, `tl` and the dashboard all read and write through them | an older or unknown `v` reads as no ask; the card text is rendered from the record's fields by `domain/asks/text.py` |
| loop state `~/.config/task-loop/loop/<repo>-<hash>.<pid>.json` (`v` 2), commands `...command.json` (`v` 1) | **us** (`taskloop.contracts.loop.LoopState`, `LoopCommand`) | `LoopFiles` (`taskloop.app.loop.files`): the loop writes both, `tl` writes commands; the dashboard (`taskloop_dash.readers.loops`) reads | a file of another `v` is no loop; the dashboard shows no queue without a live loop |
| `route.py status --json` (delegate's lane status, `v` 1) | delegate | `taskloop.contracts.delegate_status.snapshot_of`, run by `tl lanes` / `tl usage` and by the loop's `chores` step when the snapshot is 20 min old (`app/wire/lanes.chore`); the dashboard reads the `StatusSnapshot` they file and runs nothing | lane cards and banner; `tests/test_delegate_status.py` runs the reader on `tests/fixtures/delegate_status_0.51.0_real.json` and on the installed delegate's own answer |
| agent-runs v1 (`~/.config/agent-runs`) | **us** (`docs/contracts/agent-runs-v1.md`); delegate is one producer | `contract_runs`, `contract_lanes` | nothing silently: other major versions are skipped |
| Claude Code transcripts `~/.claude/projects/*/<session>.jsonl`, subagents `<session>/subagents/agent-*.jsonl` + `.meta.json` | Anthropic, undocumented | `claude_events`, `transcript_of`, `find_transcript` (a task-view block's session) | orchestrator and subagent logs |
| `$CLAUDE_CODE_SESSION_ID`, `$CLAUDE_PID` in a session's Bash env; SessionStart hook stdin (`session_id`, `transcript_path`) | Anthropic | `ident.actor`, `app/wire/hook.py` (run by `hooks/hook.py`) | the per-session bd actor (fallbacks exist), log lookup |
| codex plugin job state `~/.claude/plugins/data/codex-openai-codex/state/*/jobs/*.json` (+ `.log`) | OpenAI's codex plugin | `codex_log_events` | Codex runs started through the plugin (they carry the launching `sessionId`) |
| Codex rollouts `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | OpenAI | `rollout_events` (with `exec_cmds` for the `exec` tool's code input), `find_transcript` | Codex runs started with `codex exec` |
| OpenCode sessions, SQLite `~/.local/share/opencode/opencode.db` (`OPENCODE_DB` overrides), tables `session`, `message`, `part` only (never the credential tables); delegate's family `xai`, kind `opencode` | OpenCode | `tl.opencode_*`, `opencode_events` (ADAPTERS `opencode`), `tl.transcript_of("xai", ses_...)` -> `opencode:ses_...`, `context_tokens` | Grok lane runs; read only, short timeout, a missing DB or unknown id is empty |
| `bd list --json`, `bd show --json`, `bd update --claim`, `bd heartbeat`, `bd reclaim`, `bd unclaim`, `bd provenance record` | beads (bd 1.3+) | `adapters/bd.py` `BdStore` (the one process site); the dashboard gets it as `Ports.store` and reads and writes only through the typed `Beads` port (`taskloop_dash.readers.beads`), so no raw `bd` argv lives in `taskloop_dash` (a rules test greps for it) | the tree, claims, slots, provenance (provenance failures only warn), the dashboard's bead lists, the look gallery's writes |

## Commands the repo profile and the plan carry

Every command task-loop runs for a repo (`gate`, `land`, `gate_only`, `slots.setup`, a profile check, a plan check, a shot-table
method) is an argv list: a program and its arguments, run by `subprocess` with no shell. A string there is refused (the profile
load and the plan lint say so in one line). A pipeline, redirect or loop belongs in a repo recipe, called `["just", "name"]`.
Inside the engine the canonical text of a check is `shlex.join(argv)` (check identity, logs, the dashboard); `shlex.split`
turns it back. Nothing in task-loop parses shell syntax.

## Delegate

task-loop requires delegate for the engine (decided 2026-10-18: everyone installs both; power users never call
delegate directly). The two touch in three places only:

1. **agent-runs v1**: delegate publishes its `claude -p` runs and lane limits; the dashboard shows them. Delegate's
   side of it is described in its repo, `docs/dev/integrations.md`.
2. **The Workers table in `skills/task-loop/SKILL.md`** maps the loop's worker kinds (reader, writer,
   reviewer, hard) to delegate's role names. That mapping is the only delegate vocabulary in this plugin. When
   delegate renames roles or changes how it is asked, update that table.

3. **worker-run v3** (`docs/contracts/worker-run-v3.md`): the engine runs each AI step with `route.py run ROLE` and
   feeds usage with `route.py status --claude-usage` (`tl usage`). Code: `engine.find_route`, `engine.call_delegate`,
   `Engine.ai_delegate`, `tl.py` `usage`. The write step passes `--engine-only RECIPE` once per bare `just` recipe of
   a configured check (or the gate) its writer must not run (delegate 0.50+; `RunRequest.engine_only`, built only by `to_argv`); read-only
   steps pass none. Only route.py from delegate 0.14.0 or later is used; none installed, or an
   answer with another `v`, blocks the task with what to do. Delegate keeps its state in its plugin data dir, so always call the
   installed route.py, never a checkout's (a checkout reads `~/.config/delegate`, another store).

Never read delegate's files, and call `route.py` only through worker-run v3. A new need from delegate becomes a new optional
field or record in agent-runs v1 (minor) or v2 (breaking: change the spec, make the reader accept both, then the
producer).

## Changing the contract

- New optional field: add it to the spec table, read it with `.get()`, keep `v: 1`.
- Breaking change: write v2 in the spec, make the reader accept v1 and v2, release, then tell producers.
- Tests: `tests/test_dash.py`, class `Contract`.
