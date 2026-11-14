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

Start with [First landed task](#first-landed-task-linux) for an ordered setup and delivery walkthrough.

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

## First landed task (Linux)

Use one Linux account and the same shell for this walkthrough. You need a writable Git origin with a `main` branch
and this repository's committed profile and check tooling. A read-only upstream clone cannot publish or land tasks;
use your team's writable fork. The example assumes its origin URL ends in `task-loop.git`; replace `YOUR_TEAM` below.
For another origin name, replace the `task-loop` folder beneath the slots root too: adoption derives it from the URL.

### 1. Install and verify

Install system Git at `vars.git_version` in [mise.toml](mise.toml), following the
[Git Linux installation instructions](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git).
Set your Git author name/email and authenticate SSH or HTTPS with your Git host for fetches and pushes to `main`
and `task/*`. Branch protection must permit the owner's manual delivery operation.

Install [mise](https://mise.jdx.dev/getting-started), then clone and inspect the tool configuration before trusting it:

```bash
curl -fsSL https://mise.run | sh
export PATH="$HOME/.local/bin:$PATH"
checkout="$HOME/task-loop"
git clone git@github.com:YOUR_TEAM/task-loop.git "$checkout"
cd "$checkout"
git config user.name "YOUR NAME"
git config user.email "YOU@EXAMPLE.COM"
git switch main
git fetch origin main
# Read mise.toml before approving its configuration.
mise trust
mise install
eval "$(mise env --shell bash)"
just install
tl() { uv run --directory "$checkout" --frozen --no-sync python -I -m taskloop "$@"; }
tl version
tl repo inspect "$checkout"
tl profile show --checkout "$checkout" --at HEAD --target origin/main
prek install
just check
just test
```

Mise supplies the declared Python, Codex, Tailwind, Beads (`bd`), uv, just, prek and check tools; no separate Node
installation is needed. The `tl` shell function runs the installed package in this checkout's `.venv` from any directory.
The explicit mise environment keeps those tools on the factory's inherited PATH when it enters a slot. In a new shell,
set `checkout`, enter it, reload that environment and define the function again, or configure
[mise shell activation](https://mise.jdx.dev/getting-started#_4-activate-mise-optional).
The inspection must identify your writable origin and the profile must show your intended setup and required checks.
Keep `land` absent or `manual` in the profile on origin's `main` for this walkthrough. Both local gates must pass.
There is no CI workflow: enforcement stays with `just check`, `just test`, the prek hook and the factory's checks step.

### 2. Authenticate Codex with a file login

In `${CODEX_HOME:-$HOME/.codex}/config.toml`, set the top-level `cli_auth_credentials_store = "file"`, preserving any
other settings. Then authenticate under the same Linux account that will run rounds:

```bash
codex login
codex login status
test -f "${CODEX_HOME:-$HOME/.codex}/auth.json"
```

Login status must report an authenticated account and the file check must exit zero. On a host without a browser, use
`codex login --device-auth` instead; see [Codex authentication](https://developers.openai.com/codex/auth/).
The factory requires that local file; a keyring-only login or an API key environment variable does not supply it.
Keep `auth.json` outside Git and private. The default agent choices already select Codex for plan and implementation.

### 3. Initialize the task tracker

Use the checkout as the explicit tracker root and `first-run` as the logical backlog key throughout this example.
The key is your chosen factory configuration, independent of Beads' task ID prefix.
For a new team tracker, initialize it once:

```bash
cd "$checkout"
bd init --prefix first --skip-agents --skip-hooks --non-interactive
bd info
```

Beads uses embedded Dolt; this path needs no separately managed database server. The skip flags preserve the repository's
agent instructions and prek hook. If the team already published tracker data, use `bd bootstrap` instead of `bd init`
to obtain it on a fresh clone; an initialized tracker receives later updates with `bd dolt pull`.
`bd info` must identify the intended checkout's tracker.
Review `git status --short`; commit and push any intended tracker configuration before continuing, leaving the checkout
clean. Keep the local database ignored. Beads' [command reference](https://github.com/gastownhall/beads/blob/main/docs/CLI_REFERENCE.md)
documents initialization and remote setup; tracker data is synchronized separately from code.
Inspect `bd dolt remote list`: new initialization normally wires `origin` automatically. If absent, configure the team's
remote, for example `bd dolt remote add origin git+ssh://git@github.com/YOUR_TEAM/task-loop.git`, then commit and push the
resulting `.beads/config.yaml` change.
See [Beads sync concepts](https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md).

### 4. Create and adopt one slot

Create `~/.config/task-loop/config.toml` (and its parent directory) with these top-level settings, preserving existing
settings if present:

```toml
slots_root = "~/.tls"
slot_count = 1
backlog = "first-run"
```

The short slots root stays outside the checkout and the default state/artifacts directories. Check the length before
creating the detached worktree: the printed byte count must be at most 64. If your home path is too long, choose a shorter
absolute slots root you own and use it consistently in the config and commands.

```bash
printf %s "$HOME/.tls/task-loop/.t/s1" | wc -c
mkdir -p "$HOME/.tls/task-loop"
git -C "$checkout" worktree add --detach "$HOME/.tls/task-loop/s1" origin/main
tl config show
tl slot adopt "$checkout" --count 1
```

Expect `s1 adopted` with the created worktree's path. Adoption creates `factory.db`; it does not create the worktree.
The worktree must be clean and detached. Keep its files for factory use and use the same machine config for every command.

### 5. Specify, approve and run one task

Create a small task with concrete acceptance criteria, then inspect it before granting approval. This example adds a
single documentation file without changing checks or runtime behavior:

```bash
cd "$checkout"
task_id=$(bd create "Document the team's first task" --type task \
  --description "Add docs/first-task.md explaining how this team approves one task and reviews its land summary." \
  --acceptance "The file names our approval label first-run-approved and manual land policy. just check and just test pass." \
  --silent)
tl task show "$task_id" --backlog first-run --tracker-root "$checkout"
bd label add "$task_id" first-run-approved
bd ready --label first-run-approved
tl step rounds --backlog first-run --tracker-root "$checkout" --checkout "$checkout" \
  --label first-run-approved --max-running 1 --minutes 30
```

Only the task you intend to run should carry `first-run-approved`; it must be open, unclaimed and unblocked to appear
in the ready listing. The factory claims it and advances plan, implementation and checks. Rounds run in the foreground;
the dashboard URL is printed at startup (normally `http://127.0.0.1:8765`). Inspect progress there, or in a second shell
with the same environment using `tl step show TASK_ID --backlog first-run` and `tl step list --stuck`.
Wait for the checks attempt to show `Step: checks`, passed required check results and `Succeeded: yes`, then stop rounds
with Ctrl-C. Under manual land it waits for delivery; a published `task/<id>` branch alone is not completion.

If the task is held, read its cause and evidence in `step show` and the tracker. Edit its description or acceptance
criteria to answer the issue, complete any reported cleanup, then restore `first-run-approved` and start rounds again.
A discussion comment alone does not answer the agent. For other refusals, follow the supplied reason and detail.

### 6. Review and land

In the original shell, where `task_id` is still set (otherwise set it to the ID from the tracker):

```bash
tl step show "$task_id" --backlog first-run
tl step land "$task_id" --backlog first-run --checkout "$checkout" --summary
git -C "$checkout" diff "origin/main...task/$task_id"
# Read the summary and diff before delivery.
tl step land "$task_id" --backlog first-run --checkout "$checkout" --minutes 30
tl step show "$task_id" --backlog first-run
tl task show "$task_id" --backlog first-run --tracker-root "$checkout"
git -C "$checkout" pull --ff-only
```

The summary records, pushes and closes nothing. The explicit land pushes the accepted change to origin's `main` and
closes the local task. Success reports delivery and `Closed:`; confirm the tracker status is closed and your checkout
contains `docs/first-task.md`. If delivery succeeded but closing did not, repeat the same land command to reconcile it.
If land reports changes to what decides a pass, review those listed changes before deliberately adding
`--accept-gate-changes`; do not add it routinely. `--minutes` allows validation when main has advanced.

Finally, synchronize the tracker from its root and confirm the push reports success:

```bash
cd "$checkout"
bd dolt push
```

Land and `git push` of code do not perform tracker synchronization; a closed local task has not yet been shared until
this separate push succeeds. Resolve any remote or credential refusal before treating the shared tracker as current.

The previous implementation remains in Git history. [docs/design/INDEX.md](docs/design/INDEX.md) lists every design folder
and document; [docs/glossary.md](docs/glossary.md) holds the vocabulary, the commit letters and the CLI flag table.
The [decision records](docs/design/INDEX.md#decision-records) distinguish accepted decisions, later qualifications
and their enforcing tests.

Install system Git at the exact version in `mise.toml`'s `vars.git_version` first.
That file is the authoritative source for supported Git, Codex, Python and Tailwind
versions. Run `mise install` after trusting the repository configuration through normal
mise setup, and activate mise in your shell. Mise installs the pinned Python and standalone
Codex and Tailwind executables; Node is not required. `.python-version` selects that same
Python for uv; the package's `>=3.15` compatibility range is separate from this development pin.
The committed `mise.lock` records managed downloads.

`just check`, `just test`, the prek lint hook and `just css` verify these versions locally.
A missing tool, unexpected executable version or contradictory committed declaration fails
with the tool's expected version and observed detail. Install the declared version and check
your shell's PATH before retrying; verification never installs or upgrades external tools.

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
