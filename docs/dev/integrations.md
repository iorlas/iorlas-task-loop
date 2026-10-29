# What task-loop relies on (read before changing the dashboard, tl.py, or the skill's Workers section)

A plugin install ships only `skills/` and `hooks/`, so nothing here is loaded when someone just runs the loop.

task-loop reads formats it does not own. Each has one reader in a module of `src/taskloop_dash/` (or `tl.py`); when a
format changes, only that reader changes, and a broken reader must cost one panel, never the page (the handler
returns an error for that request; parsers skip lines they cannot read).

| source | owner | reader | what breaks if it changes |
|---|---|---|---|
| asks `~/.config/task-loop/asks/<bead>.json` (`v` 3), the ask ledger `ask-ledger.jsonl`, decisions `decisions/<repo>-<hash>/ADR-n.json` + `uses.jsonl` | **us** (`taskloop.contracts.ask.Ask`) | `AskStore` and `LedgerStore` (`taskloop.contracts.stores`), `AdrStore` (`taskloop.contracts.adrs`): the engine, `tl` and the dashboard all read and write through them | an older or unknown `v` reads as no ask; the card text is rendered from the record's fields by `domain/asks/text.py` |
| loop state `~/.config/task-loop/loop/<repo>-<hash>.<pid>.json` (`v` 2), commands `...command.json` (`v` 1) | **us** (`taskloop.contracts.loop.LoopState`, `LoopCommand`) | `LoopFiles` (`taskloop.app.loop.files`): the loop writes both, `tl` writes commands; the dashboard (`taskloop_dash.readers.world`) reads | a file of another `v` is no loop; the dashboard shows no queue without a live loop |
| `route.py status --json` (delegate's lane status, `v` 1) | delegate | `taskloop.contracts.delegate_status.snapshot_of`, run by `tl lanes` / `tl usage` and by the loop's `chores` step when the snapshot is 20 min old (`app/wire/lanes.chore`); the dashboard reads the `StatusSnapshot` they file and runs nothing | lane cards and banner; `tests/test_delegate_status.py` runs the reader on `tests/fixtures/delegate_status_0.51.0_real.json` and on the installed delegate's own answer |
| `$CLAUDE_CODE_SESSION_ID`, `$CLAUDE_PID` in a session's Bash env; SessionStart hook stdin (`session_id`, `transcript_path`) | Anthropic | `ident.actor`, `app/wire/hook.py` (run by `hooks/hook.py`) | the per-session bd actor (fallbacks exist), log lookup |
| OpenCode sessions, SQLite `~/.local/share/opencode/opencode.db` (`OPENCODE_DB` overrides), tables `session`, `message`, `part` only (never the credential tables); delegate's family `xai`, kind `opencode` | OpenCode | `adapters/opencode.py` (`transcript_of("xai", ses_...)` -> `opencode:ses_...`), `adapters/context_size.py` `context_tokens` | Grok lane runs; read only, short timeout, a missing DB or unknown id is empty |
| `bd list --json`, `bd show --json`, `bd update --claim`, `bd heartbeat`, `bd reclaim`, `bd unclaim`, `bd provenance record` | beads (bd 1.3+) | `adapters/bd.py` `BdStore` (the one process site); the dashboard gets it as `Ports.store` and reads and writes only through the typed `Beads` port (`taskloop_dash.readers.beads`), so no raw `bd` argv lives in `taskloop_dash` (a rules test greps for it) | the tree, claims, slots, provenance (provenance failures only warn), the dashboard's bead lists, the look gallery's writes |

## Commands the repo profile and the plan carry

Every command task-loop runs for a repo (`land`, `slots.setup`, a profile check (`engine.checks`, which holds the gate's steps: `run` gate or both), a plan check, a shot-table
method) is an argv list: a program and its arguments, run by `subprocess` with no shell. A string there is refused (the profile
load and the plan lint say so in one line). A pipeline, redirect or loop belongs in a repo recipe, called `["just", "name"]`.
Inside the engine the canonical text of a check is `shlex.join(argv)` (check identity, logs, the dashboard); `shlex.split`
turns it back. Nothing in task-loop parses shell syntax.

## Delegate

task-loop requires delegate for the engine (decided 2026-10-18: everyone installs both; power users never call
delegate directly). The two touch in three places only:

1. **`route.py status --json`**: the lane status the dashboard's lane cards come from (the table above).
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
field in worker-run (minor) or a new major version (breaking: change the spec, make the reader accept both, then the
producer).
