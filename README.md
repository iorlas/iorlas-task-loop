# Task-loop successor foundation

The successor task factory implements plan, implement and checks, task holds, explicit land, and an optional
read-only dashboard. It admits approved tasks into free slots, publishes verified agent results as `task/<id>` on
`origin`, and runs the repository profile's checks. Before implementation and checks, it prepares the slot's
environment and runs the profile's `setup` (Linux only); Codex agents work offline with that environment.
Rounds advance tasks through checks. Land defaults to `manual`: the person delivers a checked task with `tl step land`.
With `land: auto` in the target profile read from origin's `main`, a round runs the same land operation for at most
one task per round. Refusals about the task's change hold it with the recorded cause, preventing repeated attempts
until the person answers. Other refusals leave it waiting; unavailable results can be retried.
Review remains future work; the retained designs describe more than the implemented factory.

- `tl repo inspect PATH [--json]` reports the local repository identity, common directory, selected checkout and origin.
- `tl task show TASK_ID --backlog BACKLOG --tracker-root PATH [--json]` reads the explicitly configured Beads tracker,
  preserving requirements, acceptance and dependency relationships. The backlog key is supplied configuration; it is
  not inferred from Git. Missing, malformed and unavailable reads are distinct nonzero results; JSON errors go to stderr.
- `tl config show [--count N]` prints each effective machine setting and its source.
- `tl profile show [--checkout PATH] [--at REV] [--target REF] [--json]` prints the repository profile: `setup` and
  checks at the commit `--at`, `required` and `target` from `--target` (read-only).
- `tl slot adopt CHECKOUT [--count N]` adopts hand-made detached worktrees as slots and creates `factory.db`.
- `tl step start|show|list|verify|release|publish` run, inspect, verify, release (`--abandon` returns the tracker
  claim) and publish one task's current attempt. `tl step start` on a done plan admits implementation; after a verified
  implementation it admits checks. Checks run the profile's commands in the factory, with results and logs available
  through `tl step show`. `tl step next` runs one
  scheduling round: it settles existing attempts, advances each claimed task whose step is done (no label check), then
  admits approved ready tasks (`--label`) into the slots left while fewer than `--max-running` (default 3) of the backlog's
  tasks are in flight (a step running, or passed and waiting for land). `--max-new` is removed and rejected.
- `tl step show TASK [--backlog KEY]` selects the explicit backlog, then the machine config's `backlog`, then the sole
  distinct backlog retained in `factory.db` (including ended attempts). With none or several, supply the flag or config
  default. `tl step list` lists all backlogs; its `hold cause` column shows the recorded or due reason after `next`.
- `tl drain [--db PATH] [--artifacts PATH] [--json]` durably blocks new work across the resolved factory database and
  waits for existing entries, agents, setup, checks and synchronous operations to finish. Success verifies idle; it
  preserves claims, reservations, sessions and unlaunched attempts. Uncertainty exits 3 and Ctrl-C exits 130, leaving
  the fence in place. JSON writes progress and the final result as JSON Lines.
- `tl step rounds` repeats rounds in the foreground until Ctrl-C. `--retake-lapsed` on `next` or `rounds` is for recovery
  after discarding `factory.db`: it also takes the factory's expired claims absent from that database, assuming one
  factory on the tracker. Prefer one `next` invocation for that recovery.
- `tl step land TASK --backlog BACKLOG --checkout PATH` is the person's delivery command: squash the checked commit
  onto origin's `main`, validate again when required, push without force, then close the task in the local tracker.
  Use `--summary` to inspect first. Some lands require `--minutes N` for validation. Reruns reconcile unfinished actions;
  changes to what decides a pass require `--accept-gate-changes` when reported by land. Tracker synchronization remains
  the person's responsibility. Publishing a task branch does not land it.

For a refusal, retain its kind, reason and supplied detail and follow the reason-specific guidance. To inspect the
local situation without advancing work, use `tl config show`, `tl repo inspect CHECKOUT`,
`tl profile show --checkout CHECKOUT --at REV --target main`, and
`tl task show TASK --backlog KEY --tracker-root TRACKER`. Inspect retained execution with
`tl step list --stuck` and `tl step show TASK --backlog KEY`; add `--json` to these reads for structured output.
Use the same machine config and database/artifacts overrides as the factory being inspected.

`step show` prints `Directory:`, `Entry log:` and `Events:`; JSON includes `directory`, `entry_log` and `events_path`.
These belong to the selected attempt, including a repeat or the latest checks attempt. Candidate logs are identified
separately. An events path is a location even before launch or when no events file exists; showing it neither creates
nor reads that file. Preserve the evidence when investigating a refusal, and review configuration, origins, agent
input and transcripts for private data before sharing them.

Dedicated doctor and bug-report commands are deferred. The implemented inspection commands above provide the manual
diagnostic procedure. A future doctor needs an agreed definition of health and partial-failure behavior; a collected
bug report also needs an agreed content and redaction policy. No report is collected automatically.

Before a clean step starts, the factory brings its retained task branch onto fetched origin main. Main advancing does
not replay the plan. Textual conflicts use up to three separately recorded resolution executions; unsupported or
ambiguous conflicts hold the task with its work preserved. Preparation also runs under `land: manual`: that policy
controls delivery. Free slots may park at different commits belonging to main or the selected task history.

A required check that exits nonzero can repeat implementation after its checks slot is released. Preparation first
validates the exact checked source, then integrates current main. The next agent starts in a free clean slot with
the first failed required check's name, exact argv and bounded output
tail in its prompt. Path repeats and check-driven repeats share the three-attempt implement limit; an unchanged answer
also receives fresh checks. Infrastructure failures and optional failures alone do not trigger repair. Unsafe-path
feedback names the actual unsafe file, including a nearby Git file omitted from the answer.

Factory schema v20 stores each agent attempt's complete typed access policy (v19 added saved held work; v18 added the
durable drain boundary and external-action ownership records; v17 added the source checks link). Older databases are refused, with no migration. For subsequent upgrades, drain with the pinned matching release
before changing code. The first installation of v18 needs the supervisor to stop admission and verify that the previous
runtime's entries, agents, checks and other writers finished; the new command cannot drain an incompatible database.
Discard remains an owner decision through its authorized operation. Drain performs no upgrade, discard or restart.

A completed drain stays fenced. An explicit new rounds invocation rechecks liveness, then reopens it under matching
code while preserving unfinished work. An invocation encountering an incomplete drain finishes draining and exits;
a later explicit invocation can reopen it. One-shot commands never reopen admission, and earlier rounds cannot resume
scheduling across that boundary. Unresolved external actions or unprovable process identities keep drain from reporting
success. Retrying drain observes the same durable request; it never launches an unstarted attempt to make progress.

Rounds hold tasks they took when work needs a person: the approval label is removed, `held` is added, and a comment
explains the cause, evidence and claim state. `tl step list --stuck`, `tl step show` and `bd list --label held` expose
them. Answer by editing the task's description or acceptance criteria, then add its approval label back; the next
round starts it again at plan. Follow any pending cleanup instructions before reapproval. Comments alone are not answers.

`tl step rounds` serves the dashboard on `127.0.0.1:8765` for the lifetime of rounds; `--dash-port PORT` changes the port (0 chooses a free port).
`--no-dashboard` serves none. A dashboard startup failure warns on stderr while rounds continue.
`step rounds --json` writes JSON Lines: one start record and one end record for a normal graceful session.
Dashboard notices go to stderr in this mode, as do early refusals and abrupt end results; stdout records keep their
existing shapes. Other commands' `--json` output is a single document.

Exit codes are 0 for success/already complete (including a graceful rounds stop), 1 for refusals and task/repo
inspection failures, 2 for invalid syntax, 3 for no reliable result (profile unavailable or a step classified unknown;
retry is safe), and 130 for an abrupt rounds stop or interrupted land or drain. Task/repo inspection failures remain 1 even
when a backend read is unavailable. Continuous rounds retry unknown results themselves.

The machine config is `~/.config/task-loop/config.toml` or `--config FILE`; state defaults to
`~/.local/state/task-loop`. Its optional `backlog = "KEY"` sets the default for `step show`; `config show` reports
`unset` (JSON null) when absent. Other commands are rejected until their behavior is implemented. `tl <command> --help`
is the reference; the design index links each slice's plan and implementation evidence. `tl plan` is no longer a command.
Agent choices live in the machine config, independently for each built agent step. With no agent flags,
start, next and rounds use Codex with `gpt-6.1-sol`, high effort for plan and medium for implement. These effort defaults
are the owner's convention, not vendor guidance. For example:

```toml
[agents.plan]
harness = "codex"
effort = "high"
[agents.plan.access]
sandbox = "workspace-write"

[agents.implement]
harness = "claude"
model = "opus"
effort = "medium"
[agents.implement.access]
settings_file = "~/.config/task-loop/claude-settings.json"
permission_mode = "dontAsk"
```

`--harness`, `--model` and `--effort` optionally override their fields on each newly admitted step (flag, then file,
then default). A different harness needs its own model and policy in configuration; a harness flag cannot borrow
another harness's policy. Provider is derived from the harness and model. `config show` accepts these overrides too
and reports sources and safe access summaries. Claude settings must be a JSON object; the mode defaults to `dontAsk`,
including for plan. OpenCode uses `harness = "opencode"`, an explicit model identifier (including its provider prefix
when required), and optional `access.sandbox_file`: a JSON object containing `readable`, `scratch` and `runners`.
Policy paths must be absolute or home-expanded. Omitting the OpenCode file uses the released library defaults.
Unknown keys, malformed documents and incomplete choices fail before admission.

A Codex step's `access.sandbox` may be `danger-full-access` (set it on both `[agents.plan.access]` and
`[agents.implement.access]`): the agent then runs with no sandbox and can read and write everything the factory's user can and
reach the network, so use it only on a machine whose container is the boundary. No `codex sandbox` probe runs for it and
the dashboard shows "full access: the container is the boundary". `workspace-write` stays the default.

Rounds capture configuration and policy contents once at startup. An advance selects the next step's setting;
repeats, failed-check repairs and relaunches keep their admitted settings even if policy files change or disappear.
Attempt headers show the stored harness, provider, model, effort and access summary. Codex uses its local file login;
Claude uses its local subscription login, and OpenCode uses the released harness's local configuration. Claude and
OpenCode skip sandbox and writable-root preflight; shared setup and safe folder cleanup still apply. OpenCode's
released shell sandbox uses macOS `sandbox-exec`, so Linux enforcement is not promised. Harness routing and fallback
remain future work.

The previous implementation remains in Git history. [docs/design/INDEX.md](docs/design/INDEX.md) lists every design folder
and document; [docs/glossary.md](docs/glossary.md) holds the vocabulary, the commit letters and the CLI flag table.
The [decision records](docs/design/INDEX.md#decision-records) distinguish accepted decisions, later qualifications
and their enforcing tests.

Python 3.15 and the tool versions in `mise.toml` are required. Run `mise install` after
trusting the repository configuration through normal mise setup.

```bash
just install
uv run --frozen --no-sync python -I -m taskloop --help
uv run --frozen --no-sync python -I -m taskloop repo inspect . --json
just check
just test
```

Both required checks rebuild and install the current project as a wheel in this
worktree's `.venv`. Tests use that installed package and verify its source provenance;
no old editable install, vendored runtime or baseline source path supplies imports.
`just test` runs the CLI, step and architecture checks. `tests/steps/` holds all the factory tests, including the lock, lease and
rounds tests (the folder name is historical). No historical test bootstrap or kernel is included.
The Git, task tracker, agent, SQLite, process-lock and stream boundaries come from released
[shelf](https://github.com/yoselabs/shelf) libraries, pinned in [pyproject.toml](pyproject.toml) and [uv.lock](uv.lock)
and checked for portable source provenance.

The direct runtime dependencies are pinned as follows:

| Package | Version |
| --- | --- |
| any-agent | 0.11.0 |
| beads-client | 0.2.0 |
| git-porcelain | 0.21.0 |
| process-lock | 0.2.1 |
| pydantic | 2.14.3 |
| sqlite-store | 0.1.0 |
| stream-proc | 0.9.0 |

The build requirement is hatchling 1.33.0. Development requirements are pytest 9.2.0
and pytest-xdist 3.8.0. [pyproject.toml](pyproject.toml) owns these declarations;
[uv.lock](uv.lock) owns the frozen dependency resolutions. stream-proc's package
version is 0.9.0, but its shelf source uses the `any-agent-v0.11.0` tag so that
stream-proc and any-agent resolve to the same shelf commit.

[Design and acceptance](docs/design/tl-8bh9.8.7/plan.md) describe the boundary of this
foundation. Preserved design documents may describe future behavior or the historical implementation;
they are not additional executable commands.

`.task-loop.json` is this repository's profile (`setup`, `checks`, `required`, `target`), read from Git by
`tl profile show` ([tl-8bh9.14.1](docs/design/tl-8bh9.14.1/plan.md)). An implement attempt's entry runs its `setup`
(`just bootstrap`: `just install` plus every pinned check tool warmed in the uv cache) in the slot before the agent
([S5e](docs/design/tl-8bh9.4.3.1.16.2/plan.md)), on Linux only; the agent then writes three folders beside the slots
(`TMPDIR`, the uv cache and tools) with uv offline and is told to run every command under `checks` itself. The factory's
checks step independently runs the profile's setup and checks on the committed implementation. A slots root must keep
`<slots_root>/<repo name>/.t/<slot>` within 64 bytes and lie outside
the checkout, the artifacts root and factory.db's folder.
