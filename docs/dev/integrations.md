# What task-loop relies on (read before changing the dashboard, tl.py, or the skill's Workers section)

A plugin install ships only `skills/` and `hooks/`, so nothing here is loaded when someone just runs the loop.

task-loop reads formats it does not own. Each has one reader in a module of `src/taskloop_dash/` (or `tl.py`); when a
format changes, only that reader changes, and a broken reader must cost one panel, never the page (the handler
returns an error for that request; parsers skip lines they cannot read).

| source | owner | reader | what breaks if it changes |
|---|---|---|---|
| asks `~/.config/task-loop/asks/<bead>.json` (`v` 3), the ask ledger `ask-ledger.jsonl`, decisions `decisions/<repo>-<hash>/ADR-n.json` + `uses.jsonl` | **us** (`taskloop.contracts.ask.Ask`) | `AskStore` and `LedgerStore` (`taskloop.contracts.stores`), `AdrStore` (`taskloop.contracts.adrs`): the engine, `tl` and the dashboard all read and write through them | an older or unknown `v` reads as no ask; the card text is rendered from the record's fields by `domain/asks/text.py` |
| loop state `~/.config/task-loop/loop/<repo>-<hash>.<pid>.json` (`v` 2), commands `...command.json` (`v` 1) | **us** (`taskloop.contracts.loop.LoopState`, `LoopCommand`) | `LoopFiles` (`taskloop.app.loop.files`): the loop writes both, `tl` writes commands; the dashboard (`taskloop_dash.readers.world`) reads | a file of another `v` is no loop; the dashboard shows no queue without a live loop |
| `route.py status --json` (delegate's lane status, `v` 1) | delegate | `taskloop.contracts.delegate_status.snapshot_of`, run by `tl lanes` / `tl usage` and by the loop's `chores` step when the snapshot is 20 min old (`app/wire/lanes.chore`); the dashboard reads the `StatusSnapshot` they file and runs nothing | lane cards and banner; `tests/adapters/test_delegate_status.py` runs the reader on `tests/fixtures/delegate_status_0.51.0_real.json` and on the installed delegate's own answer |
| `$CLAUDE_CODE_SESSION_ID`, `$CLAUDE_PID` in a session's Bash env; SessionStart hook stdin (`session_id`, `transcript_path`) | Anthropic | `ident.actor`, `app/wire/hook.py` (run by `hooks/hook.py`) | the per-session bd actor (fallbacks exist), log lookup |
| OpenCode sessions, SQLite `~/.local/share/opencode/opencode.db` (`OPENCODE_DB` overrides), tables `session`, `message`, `part` only (never the credential tables); delegate's family `xai`, kind `opencode` | OpenCode | `adapters/opencode.py` (`transcript_of("xai", ses_...)` -> `opencode:ses_...`), `adapters/context_size.py` `context_tokens` | Grok lane runs; read only, short timeout, a missing DB or unknown id is empty |
| `bd list --json`, `bd show --json`, `bd update --claim`, `bd heartbeat`, `bd unclaim`, `bd provenance record` | beads (bd 1.3+) | `adapters/bd.py` `BdStore` (the one process site); the dashboard gets it as `Ports.store` and reads and writes only through the typed `Beads` port (`taskloop_dash.readers.beads`), so no raw `bd` argv lives in `taskloop_dash` (a rules test greps for it) | the tree, claims, slots, provenance (provenance failures only warn), the dashboard's bead lists, the look gallery's writes |
| lease table `~/.config/task-loop/leases`: `<name>.limit`, `<name>-<n>.lock` (flock + JSON holder record `label` `bead:check`, `meta` bead/check/lane) | shelf `any_lease` (vendored, `dev/vendor.py`) | `Leases` in `taskloop.app.checks.resources` (takes and waits), `adapters.locks.resource_holders` (read only: `tl status --brief`, the dashboard); manual runs use `python3 -m any_lease run --root <table>` | a resource limit or holder shown wrong; the engine and a manual run stop sharing units |

## Commands the repo profile and the plan carry

Every command task-loop runs for a repo (`land`, `slots.setup`, `engine.prepare.cmd`, a profile check (`engine.checks`, which holds the gate's steps: `run` gate or both), a plan check, a shot-table
method) is an argv list: a program and its arguments, run by `subprocess` with no shell. A string there is refused (the profile
load and the plan lint say so in one line). A pipeline, redirect or loop belongs in a repo recipe, called `["just", "name"]`.
Inside the engine the canonical text of a check is `shlex.join(argv)` (check identity, logs, the dashboard); `shlex.split`
turns it back. Nothing in task-loop parses shell syntax.

### Check fields

`engine.checks` declares `id`, `argv`, `group`, and `run` (`stage`, `gate`, or `both`).
`needs` lists declared resources whose leases the check holds during execution.
`run_in` is `clean` by default: land checks execute committed HEAD in a fresh checkout. Use `slot` for checks that need
gitignored setup inputs in the host's own worktree, such as Unity's installed dependencies. Both modes require the slot's
tree hash to equal `HEAD^{tree}`. Stage checks still run in the slot. Unknown `run_in` values fail profile loading.
Mixed gates preserve plan order, dependencies, resource leases, and skip-after-red behavior. Receipts identify the execution
location; a clean receipt cannot substitute for a slot receipt. Slot input keys include ignored files matching `inputs`.

`inputs` must list every file the check reads, directly or through the scripts it runs (helpers, imports, config, pin files). A missed file
is a stale green: a cache hit lands untested code. There is no sampling audit; fix the glob when a bug traces to a missed input (SKILL.md, Check inputs).

An ask whose reason contains `is not set up` receives an engine-authored `retry` answer when its failing gate check now
declares `run_in: slot`, or when that bead's engine starts. This happens at most once per bead per release version, recorded
in bead metadata as `setup_retry_versions`. The answer reopens the bead and restores a pick label only if parking removed it.

`engine.prepare` optionally declares coordinator prerequisites, for example
`{"cmd": ["dotnet", "restore"], "inputs": ["**/*.csproj", "Directory.Packages.props", "**/packages.lock.json"], "timeout_min": 30}`.
The coordinator runs the argv through Spawner in the bead's worktree, with its own network access, before the first write.
A successful `prepare.stamp` under the run directory records the input fingerprint. Subsequent writes skip prepare while
matching file contents are unchanged and their mtimes are no newer than the stamp; tracked deletions invalidate it too.
This complements `slots.setup`, which belongs to slot setup rather than write rounds. `timeout_min` defaults to 30 minutes.
`triggers` defaults to `["restore", "project.assets.json", "NU1"]`: a case-insensitive match in writer bad-check/problem text
or failed check diagnostics forces prepare and retries the same write once, without spending a write attempt or replan.
A second such report follows the normal failure path. Stdout and stderr tails are kept in the run log; a nonzero exit,
timeout or spawn error ends the run as `FAULT_INFRA`, with the output tail in the reason and no successful stamp.

`engine.plan_cmd` optionally names the full argv of a repo's gate-plan producer, for example
`["python", "tools/gate_plan.py", "steps", "--json"]`. Task-loop appends only `--base <resolved sha>` and
`--paths-stdin`, runs in the checkout being judged, and feeds NUL-separated changed paths from the merge-base
to the judged tree (equivalent to `git diff --name-only -z <base>...HEAD` in a clean checkout).
The command has 30 seconds to print one JSON document with `version: 1`, `base`, `empty`, `full`,
`full_reasons`, and `steps`. Each step carries `name`, `lane`, `run`, `argv`, `pre`, `recipe`, and `reason`;
`id` and `why` are aliases for `name` and `reason`. Unknown fields are ignored. Only a registry step explicitly
listed with `run: false` is skipped, with that reason. Other registry steps remain required, regardless of `when`.
The repo supplies the decision; task-loop owns execution, results, and scheduling. A failed, timed-out or malformed
plan makes every step required and prints its warning once per run per distinct reason. When `python` is absent from PATH,
the producer uses `python3`, or the coordinator's interpreter if neither spelling exists. An unresolved executable ends
the run with a clear config error and one Note row. Without `plan_cmd`, the existing `when` rules apply.
`tl check --all` and explicitly named checks bypass the plan. Planned skips are recorded only after a clean round,
for the exact tree and base; `tl green` and the land gate read those records through the existing result store.

At land, the gate steps and their plan producer run in a fresh detached worktree of the judged commit, created and
removed through the Git port. Ignored and untracked slot files are never copied into it, and the slot is never cleaned.
Checks write declared results through the existing `TL_ARTIFACT_DIR`; `TL_WORKTREE` names the temporary checkout.
Evidence referenced by committed documents must be tracked: a link into a slot's ignored `.task/` folder cannot pass
the land gate. Gate receipts use a separate execution identity, so a stage or standalone check's pass from the slot
cannot authorize delivery. Passes from clean gates remain reusable for the same inputs, base and execution environment.

## Delegate

task-loop requires delegate for the engine (decided 2026-10-18: everyone installs both; power users never call
delegate directly). The two touch in three places only:

1. **`route.py status --json`**: the lane status the dashboard's lane cards come from (the table above).
2. **The Workers table in `skills/task-loop/SKILL.md`** maps the loop's worker kinds (reader, writer,
   reviewer, hard) to delegate's role names. That mapping is the only delegate vocabulary in this plugin. When
   delegate renames roles or changes how it is asked, update that table.

3. **worker-run v3** (`docs/contracts/worker-run-v3.md`): the engine runs each AI step with `route.py run ROLE` and
   feeds usage with `route.py status --claude-usage` (`tl usage`). Code: `WorkerCall` in `app/run/worker_call.py`,
   `worker_request.request`, `RunRequest.to_argv`, `tl.py` `usage`. Before recovery, WorkerCall prepares the effective request
   and identifies the worktree, cwd, HEAD, tree contents, policy, schema and answer producer contract. Completed writer
   effects are bound to their resulting tree; interrupted threads resume only with a matching identity. Log destinations
   are excluded. Legacy prompt-only records require execution again; their raw output is retained for inspection.
   The write step passes `--engine-only RECIPE` once per bare `just` recipe of
   a configured check (or the gate) its writer must not run (delegate 0.50+; `RunRequest.engine_only`, built only by `to_argv`); read-only
   steps pass none. A worker call also passes `--only-family F` once per family of `engine.writer_family` (or the bead's `writer-family:<f>`
   labels; delegate PINFAMILY; `RunRequest.only_family`, `domain/lanes/pin.py`); the planner, reviewer and reflect calls pass none. A `stop`
   with reason `only_family_unready` (or `no_lane` while pinned) pauses the run with the pin in words (`lane_acts.end`). Only route.py from delegate 0.14.0 or later is used; none installed, or an
   answer with another `v`, blocks the task with what to do. Delegate keeps its state in its plugin data dir, so always call the
   installed route.py, never a checkout's (a checkout reads `~/.config/delegate`, another store).

Never read delegate's files, and call `route.py` only through worker-run v3. A new need from delegate becomes a new optional
field in worker-run (minor) or a new major version (breaking: change the spec, make the reader accept both, then the
producer).
