# tl-8bh9.8.3: install, pin and release (block B8, milestone M5)

Design, 2026-11-12, against 26be8f7ae (M1-M4 built and on `main` through PR #723; schema v14); revised the same day
after an independent review (section 21). Docs only: nothing built, installed, tagged or run. Read: CLAUDE.md,
[glossary](../../glossary.md), [self-hosting roadmap](../self-hosting-roadmap.md) (B8, D6, D9, D14, O6, M5),
[operations](../tl-8bh9.8/operations.md) (accepted version strategy; proposed release contract; lightweight skill),
`bd show tl-8bh9.8.3` (INSTALL-OWNER), the [land plan](../tl-8bh9.14.8/plan.md) (style and the schema refusal), and
`__main__`, `cli`, `cli_composition.load_config`, `machine_config`, `composition` (`open_launcher`,
`open_checks_launcher`, `keep_awake_spawn`), `launch`, `owned_processes`, `keep_awake`, `rounds_lock`,
`operations.require_database`, `factory_schema`, `implement_step`, `tests/rules/test_policy.py`, `.importlinter`,
`pyproject.toml`, the installed `sqlite_store` 0.1.0 (`_validate_version`, `migrate.upgrade`), `git_porcelain` 0.17.0
(`Repo.tree`, `Repo.refs`, `Repo.history`) and `stream_proc` 0.6.0 (`run`, `capture`).

Every choice not listed in section 2 is **proposed** (a recommendation, open to veto); section 19 collects them with a
recommendation each. **Owner questions that block something:** Q9 (dropping the baseline `devbox-ok` and macOS pin
policy) blocks the first release made under this design, not the slices; Q13 (rollback onto a newer factory.db never
refused at pin time) needs the owner's sign-off before I3 is built. Q1 and Q2 are the others most worth a look.

## 1. Goal: what changes for the owner

Today the factory runs from a runner worktree's `.venv` (O6's interim): the person creates a detached worktree at a
commit, runs `just install` there, and starts `<runner>/.venv/bin/tl ...`; adopting a newer factory means stopping the
rounds and re-creating the runner by hand. After B8:

1. **`tl install REV --checkout PATH`** builds one immutable install of a commit (named by an annotated tag or a full
   commit id) under the D14 per-user folder: `~/.local/share/task-loop/installs/<commit>/`. It never touches the
   person's checkout (reads Git objects only), never touches another install, and never pins.
2. **`tl pin REV`** records the owner's choice of install in a pin file beside the machine config. **`tl pin --clear`**
   removes it. Nothing else writes the pin; nothing switches versions automatically.
3. **`tl` resolves once at start**: the `tl` command reads the pin before importing the CLI and replaces itself (one
   `exec`) with the pinned install's interpreter. A missing, incomplete or broken pinned install refuses (`refused
   pin:<word>`); no other install is ever guessed.
4. **Running rounds never change version.** A pin change takes effect at the next start of `tl`; the running `tl step
   rounds` and every entry process it launches keep the interpreter they started with (`sys.executable`) until the
   person stops and restarts them (D9).
5. **`tl version`** says which install runs and which is pinned.
6. **Release** is an annotated tag on `main` made and pushed by the person. The factory makes no tag, no marketplace
   entry, no plugin cache write and no canary.
7. **Adopting a landed factory change** (self-hosting): land, pull, optionally tag, `tl install`, then always drain
   (stop the rounds, wait for or abandon running attempts), pin, start (section 10). A schema change additionally needs
   factory.db discarded, exactly as today; the new version refuses `schema` until then.

## 2. Owner decisions this design respects

| # | Decision | Where it binds here |
|---|---|---|
| D9 | Runtime version fixed until restart ([operations](../tl-8bh9.8/operations.md), accepted 2026-11-09): resolve an installed version once per factory process, honour the explicit owner pin, workers and children use the same install; updates and pin changes affect the next start; no live upgrade, re-exec at step boundaries, counter transfer or automatic bad-version fallback. | Sections 5, 7 |
| D14 | All temporary and slot files in one hidden per-user folder, default `~/.local/share/task-loop`; installed as a pip package; the factory does not care about developer tooling and neither moves its folders nor bypasses shims; `mise` trust of that folder is a machine prerequisite the person meets once. | Sections 4, 6.1, 12 |
| D6 | The factory never starts at boot; a foreground `tl step rounds`, Ctrl-C to stop. | A pin change is adopted by that restart; no service reload |
| INSTALL-OWNER acceptance (tl-8bh9.8.3) | One shared resolver; explicit pin, else the installation manager's selected version; a missing or corrupt selection is a typed failure, never a newest-directory guess; the pin is durable configuration outside factory.db, with no database or file fallback; a factory.db discard keeps the pin; explicit rollback refuses an incompatible database rather than restoring or deleting it. | Sections 4, 5, 8 |
| This block's brief (2026-11-12) | Install directory per version under the D14 folder; no marketplace, plugin cache or canary; release is an annotated tag by the person; a newer schema met by older code stays `refused schema`; must also work once installed as a pip/uv package; Linux and macOS paths. | Sections 4, 8, 9, 12 |
| CLAUDE.md | Owner pin: explicit owner operation, never automatic switching. Installed plugin/cache: only the normal installation operation. No subprocess in factory source; native Python first; a process needs a concrete external-tool reason. No deletion based on presumed staleness. One owner per fact. No backward compatibility or dual readers. | Sections 4, 5, 6 |

Not carried (proposed, **Q9, blocking for release**): the baseline's `devbox-ok` acknowledgement and macOS pin
restriction. [operations](../tl-8bh9.8/operations.md) says to keep them "unless the owner explicitly changes it"; both
belong to the baseline's canary and marketplace rollout, which this block's brief excludes. The slices can be built
without the answer; the first `factory-v*` release waits for it.

## 3. Today: how the code finds its interpreter and its entries

- `pyproject.toml`: `[project.scripts] tl = "taskloop.cli:main"`; `python -m taskloop` runs `taskloop/__main__.py`,
  which calls the same `cli.main()`. Nothing resolves a version; `pyproject` says `version = "0"`.
- Entry processes are started with **this process's interpreter**: `composition.open_launcher` and
  `open_checks_launcher` pass `sys.executable`; `launch.Launcher._start` runs
  `[sys.executable, "-I", "-m", "taskloop.attempt_entry" | "taskloop.check_entry", <db>, <artifacts>, <backlog>, <task>]`
  in a new session. So an entry always runs the same install as the `tl` that launched it, and `-I` keeps `PYTHONPATH`
  and the user site out. This is already the D9 property for children; B8 keeps it untouched.
- `owned_processes` observes registered entries, setup commands and agents by **identity** (pid, start time, boot id),
  never by executable path: a rounds process of version B treats a still-running entry launched by A as running and
  does not relaunch it. This makes a version change survivable, not safe: B then reads and continues rows A's code
  wrote. Section 10 therefore drains before every switch.
- `keep_awake` resolves `caffeinate` / `systemd-inhibit` and `tail` on `PATH`: independent of the install.
- `rounds_lock`: one `tl step rounds` per (factory.db, backlog); holder meta is informational only.
- The machine config is `~/.config/task-loop/config.toml` (`machine_config.config_file`) or `--config FILE`; defaults
  put factory.db and artifacts under `~/.local/state/task-loop/` and slots under `~/.local/share/task-loop/slots`, the
  same on Linux and macOS.
- A newer or older factory.db is refused: `sqlite_store._validate_version` raises `SchemaError` ("this code knows vN:
  update it" for a newer file; "the writer has not upgraded it yet" read-only for an older one; `migrate.upgrade`
  "missing upgrade step" read-write, as `factory_schema.SCHEMA.steps` is empty), and `operations.require_database` maps
  it to `Failed("refused", "schema", ...)`.
- On the owner's machine the **baseline** factory still lives in `~/.config/task-loop/` (its `factory.db`, `bin/`,
  `pinned.json`, `worktrees/`, ...), its launcher is `~/.local/bin/tl` (a shell script running the baseline's
  `tl.py`), and its release tags are `v0.23.*` in this repository. B8 collides with none of these (sections 4, 9).

## 4. Data and state ownership

### 4.1 Layout

```
~/.local/share/task-loop/                 D14 per-user folder (same path on Linux and macOS, Q5)
  slots/...                               unchanged (machine config `slots_root` default)
  installs/                               uv's working directory while it builds (section 6.1)
    <commit>/                             one install per commit: 40 (or 64) lowercase hex, the directory name
      source/                             the commit's tree as exported from Git objects
      venv/                               uv's project environment: venv/bin/python, venv/bin/tl, site-packages
      install.log                         uv's output and the verification answer
      install.toml                        the manifest: written last, by atomic rename; its presence means "complete"
    <commit>.lock                         the install lock (process_lock, label `taskloop-install`)
<folder of the machine config in use>/    default ~/.config/task-loop/ (Q2)
  config.toml                             unchanged (machine_config)
  config.pin.toml                         the owner pin of that config: `<config stem>.pin.toml` (new)
```

The installs root is fixed at `<home>/.local/share/task-loop/installs` (no config key, no environment variable, `<home>`
from `Path.home()` as `load_config` reads it). Nothing of B8 lives in a slot, a checkout, factory.db or the artifacts.
Every reader opens `installs/<commit>/` by name; the one enumeration (`tl pin TAG`, section 6.2) considers only
directories named by 40/64 lowercase hex, so a `.lock` or a `*.tmp` file is never taken for an install.

### 4.2 Owners

| Fact | The one writer | Where | Readers | Lifetime |
|---|---|---|---|---|
| An install's files | `tl install` (`install_op`), once, under the install lock; never modified after its manifest exists | `installs/<commit>/source`, `venv` | the exec of section 5; entries through `sys.executable` | until the person removes it by hand (section 14) |
| An install's manifest | `install_op`, written last, by atomic rename | `installs/<commit>/install.toml` | resolver, `tl pin`, `tl version`, `tl install` (all through one validity function, `installs.state`) | with the install |
| The owner pin | `tl pin REV` and `tl pin --clear` only (`pin_file`), atomically | `<config folder>/<config stem>.pin.toml` | the resolver, `tl version` | durable; a factory.db discard does not touch it |
| The running version | the process itself: `sys.prefix` and the manifest beside it | memory; one `rounds install ...` line in `rounds.log` per rounds start | `tl version`, the person | the process |
| factory.db | unchanged (schema v14 stays; B8 adds no table or column and never opens it) | | | |
| The install lock | `process_lock` | `installs/<commit>.lock` | a second `tl install` of the same commit | kernel `flock`, freed on exit; nothing deletes the file |

No install fact enters factory.db: factory.db is disposable execution state, the pin is owner configuration, and the
running version is a property of the process (operations: "Resolved running version and release-operation progress
remain runtime facts"). The `rounds install` log line is display only, never read back.

**The lock and the readers.** Only installers take the install lock, and `tl install` decides an install's state
(absent, incomplete, broken, complete) only while holding it. The resolver, `tl pin` and `tl version` take no lock: they
rely on the manifest being the last write and an atomic rename, so they see either no manifest (`incomplete`, also while
an install is still building) or a whole one; never a partial manifest.

### 4.3 The manifest `install.toml`

```toml
format = 1
commit = "3f2a9c...<40 hex>"
tag = "factory-v0.2.0"            # only when installed by an annotated tag name
installed_at = "2026-11-20T10:00:00Z"
checkout = "/home/u/src/task-loop" # informational: the checkout whose objects were read
```

Exact keys, no others. `installs.state(<commit>)` is the one validity rule every command uses: **complete** when the
manifest parses with exactly these keys, `format = 1`, its `commit` is the directory name, and `venv/bin/python` exists
and is executable after following links; **incomplete** when the directory exists without a manifest; **broken** when a
manifest exists and any other condition fails; **absent** otherwise. The writer is a fixed formatter over validated
values (hex id, a tag name of `[A-Za-z0-9._/-]` with Git's ref-name rules, an ISO time, a path written as a TOML basic
string with `\`, `"` and control characters escaped); readers use `tomllib`. Written to `install.toml.tmp`, fsynced,
`os.replace`d, the folder fsynced.

### 4.4 The pin file `<config stem>.pin.toml`

```toml
format = 1
commit = "3f2a9c...<40 hex>"
tag = "factory-v0.2.0"            # as recorded in the install's manifest at pin time; display only
pinned_at = "2026-11-20T10:05:00Z"
```

Only `commit` decides. Same writer discipline as the manifest. `--clear` removes the file (`unlink`, then folder fsync).
Its place (Q2) is beside the machine config in use, named after it: `~/.config/task-loop/config.pin.toml` by default,
`<dir>/<stem>.pin.toml` for `--config <dir>/<stem>.toml`. So the pin belongs to one factory (one machine config: one
factory.db, one slots root); two configs in one folder have two pins; a scratch smoke with `--config $M/config.toml`
has its own (absent: unpinned); the M1-M4 runbooks, which run `<runner>/.venv/bin/tl --config ...`, keep running their
runner. The name does not collide with the baseline's `pinned.json` in the same folder.

## 5. Resolution at start (the one resolver)

### 5.1 Two ways in

| Invocation | Resolves the pin | Used by |
|---|---|---|
| `tl ...` (the console script, now `taskloop.start:main`) | yes, once, before the CLI is imported | the person, always |
| `python -I -m taskloop ...` (`__main__`, unchanged: calls `cli.main()`) | no | the exec target of 5.2; an explicit development or by-path invocation |
| `python -I -m taskloop.attempt_entry` / `taskloop.check_entry` | no | the launcher: inherits the launching process's interpreter |

`__main__` deliberately does not resolve and never imports `start` (import contract, 5.3): the exec lands there, so one
start resolves exactly once and an exec loop is impossible by construction (no marker variable, no hop counter).
Development from a source checkout is explicit: `uv run python -I -m taskloop ...` (or the runner's
`.venv/bin/python -I -m taskloop`), never a fallback for a failed pin.

### 5.2 The algorithm (`start.resolve`, pure; `start.run` applies it)

Inputs: the argv, `Path.home()`, this process's `sys.executable`, and file reads through a narrow port (`installs.Reads`).
As built (I1): the resolver lives in `start.py`, not `installs.py`, because `pin_file` imports `installs` (the shared
atomic writer, escaping and commit check) and `installs.resolve` would have needed `pin_file` back, an import cycle; it
takes no `sys.prefix`, which only `tl version` reads.

1. **The pre-scan.** The top-level options are `--config FILE`, `--config=FILE`, `-h`, `--help`. Tokens are read left
   to right: `--config` consumes the next token as its value whatever it is (so `tl --config install step list` has
   the config `install` and the command `step`); the first token that is not a top-level option or its value is the
   command word. Nothing else of argv is interpreted. As built: a `--config` value without a name (`--config /`,
   `--config=`, an empty value) has no pin file and refuses `pin:invalid` for a resolved command (`tl version` reports it
   `invalid`).
2. **Exempt commands run their own install, unresolved**: the command word `install`, `pin` or `version`, no command
   word, or `-h`/`--help`. They manage installs and must work while the pin names a missing or broken install.
3. **The pin file**: `<config folder>/<config stem>.pin.toml` (section 4.4). **Absent**: run the own install (the
   installation manager's selection: whichever `tl` the person started).
4. **Pin invalid** (unreadable, not TOML, an unknown key, `format` not the integer 1, `commit` not 40/64 lowercase hex,
   a `tag` that is not a tag name): `refused pin:invalid`.
5. **The pinned install's state** (`installs.state`, section 4.3): absent `refused pin:missing`, incomplete `refused
   pin:incomplete`, broken `refused pin:broken`.
6. **Exec.** Complete: `os.execv(<install>/venv/bin/python, [<that path>, "-I", "-m", "taskloop", *argv[1:]])`. "Run the
   own install" in steps 2 and 3 is the same exec with `sys.executable` (Q15): `start` never imports the CLI, so nothing
   heavier than the resolver is imported before the decision, and every start ends in the same `-I -m taskloop` process
   shape. The environment, working directory, open standard streams and pid are kept; nothing was opened or printed
   before. An `OSError` from `execv` is `unavailable pin:exec` (exit 3).

Refusals print one line on stderr, exit 1, and change nothing:

```
tl: refused pin:missing: pinned 3f2a9c4e1b07 (factory-v0.2.0) is not installed under ~/.local/share/task-loop/installs; tl install factory-v0.2.0 --checkout PATH, or tl pin --clear
```

With `--json` anywhere in argv the refusal is `{"error": {"kind": "pin:missing", "commit": "...", "message": "..."}}` on
stderr, as every command's JSON refusal.

### 5.3 The one exec owner and the imports (proposed, Q1, Q15)

`os.execv` is a native call, not a spawn, wait or signal: the process replaces its own image and keeps its pid, so no
child exists to own. It is used once, in `start.py`, before any lock, database, tracker, Git call or child.

- **Policy AST test** `test_only_start_replaces_the_process` in `tests/rules/test_policy.py`: in factory source and
  tests, `execv` is allowed only in `start.py`; every other `os.exec*` name (`execl`, `execle`, `execlp`, `execlpe`,
  `execv`, `execve`, `execvp`, `execvpe`), `os.posix_spawn`, `os.posix_spawnp`, `os.fork`, `os.forkpty`, `os.spawn*`, any
  import of `pty` or `multiprocessing` (also through `import_module`/`__import__`) fails, as the one-signal-owner test
  does for signals.
- **Import contracts**: `main-depends-on-cli` gains `taskloop.start | taskloop.__main__` as independent top-layer
  siblings (neither imports the other); a new forbidden contract `start-decides-before-the-cli` keeps `taskloop.start`
  from importing `taskloop.cli`, `cli_step`, `cli_composition`, `composition`, and the shelf libraries `git_porcelain`,
  `sqlite_store`, `stream_proc`, `beads_client`, `any_agent`, `process_lock` (directly or indirectly): `start` imports
  only the standard library, `installs` and `pin_file`, which import nothing of the factory but each other and
  `machine_config` (as built: `pin_file` takes the default config location from `machine_config.config_file`, its one
  owner, rather than a second copy; the policy test `test_nothing_but_the_standard_library_is_imported_before_the_decision`
  holds `machine_config` to the standard library only).
- As built, the policy also refuses `os.system`, `os.popen`, `asyncio.create_subprocess_exec`/`_shell`,
  `ProcessPoolExecutor`, `_posixsubprocess.fork_exec`, imports of `_posixsubprocess` and `concurrent.futures.process`, and
  any of these names reached by string (`getattr`, `vars(...)[...]`, `.__dict__[...]`); it counts uses, so `start.py` has
  exactly one `os.execv`.
- Not chosen for "run here": `importlib.import_module("taskloop.cli").main()` (typed `Any`: CLAUDE.md forbids new Any)
  or a function-level `import` (ruff `PLC0415`, and a `noqa` is an ignore escape). The cost of exec'ing the own
  interpreter is one more interpreter start (tens of milliseconds).

### 5.4 Alternatives considered (Q1)

- **Refuse instead of exec** (`refused pin:elsewhere` naming the pinned `bin/tl`): no exec owner, but every start from
  the launcher would refuse, so the person must keep a PATH entry in step with the pin by hand: a second, manual copy of
  the pin.
- **A `current` symlink** (`installs/current -> <commit>`, PATH `tl` pointing at `installs/current/venv/bin/tl`; `tl pin`
  repoints it): no exec and no resolver. Rejected: a missing or broken target fails as a shell `No such file or
  directory` or a Python traceback, not a typed `refused pin:<word>` naming the commit and the fix; one link serves every
  machine config (no per-factory pin, smokes would share it); and the link and any record of "what is pinned" would be two
  representations of one fact. Exec stays.

### 5.5 What resolution does not do

No version comparison, no "newest" scan, no fallback to the launcher when the pin is bad, no re-resolution after start,
no network, no Git, no reading of factory.db. The rounds, the step commands and the entries never read the pin file.

## 6. Commands and exact outputs

Exit codes as every command: 0 done (or already), 1 refused, 3 unavailable (rerun is safe). Only `tl version` has
`--json` (its `running` block is `tl install`'s verification answer); `tl install` and `tl pin` print text only.

### 6.1 `tl install REV --checkout PATH`

`REV` is an **annotated tag name** or a **full commit id** (40 or 64 hex). A branch name, a short id, a lightweight tag,
a tree or blob id, or any other revision is refused (`revision`, `not_annotated`): an install names an immutable
version (Q4).

1. **Resolve** in the person's checkout through `git_porcelain` (read only, hooks off, no fetch: the person fetches or
   pulls). A full hex `REV`: `Repo.tree(REV)` must resolve and `Repo.history([REV], limit=1)`'s first commit must be
   `REV` itself (a tree or blob id, which `Repo.tree` also accepts, has no history: `revision`). A tag name: it must pass
   the tag-name filter of 4.3; `Repo.refs(["refs/tags/<REV>"])` is a prefix listing, so only the row whose name is
   exactly `refs/tags/<REV>` counts (`refs/tags/<REV>-rc` is ignored); none is `revision`. **Annotated** when that ref's
   object id differs from the commit id `Repo.tree(REV).sha` (the peeled commit) and the object is not itself a commit
   (`Repo.history([<object id>], limit=1)` does not start at that id); otherwise `not_annotated`. A tag of a tag is
   accepted (it peels to a commit); a tag of a tree is `revision`.
2. **Lock** `installs/<commit>.lock` without waiting: `refused busy` when another `tl install` of the same commit holds
   it. Everything below happens under the lock.
3. **State** (`installs.state`, the same validity as the resolver, `tl pin` and `tl version`): complete: `Installed:
   already ...`, exit 0, nothing written (a manifest whose `tag` differs from the given tag name is still the same
   install; the output names both); broken: `refused broken` naming the path; incomplete: `refused incomplete` naming
   the path (section 6.4); absent: build.
4. **Export** the tree into `installs/<commit>/source/` natively: every entry of `Tree.files` with mode `100644` or
   `100755` written with `Tree.read(path)` and that mode; a symlink (`120000`) or gitlink (`160000`) is `refused tree`
   with the path (this repository has neither); a path with an empty, `.` or `..` part is `refused tree`. About 300
   `cat-file` reads at 26be8f7ae (293 tracked files); not verified for time (section 20).
5. **Build** with uv, the one external tool (it owns environment creation and the locked dependency set):
   ```
   cwd: ~/.local/share/task-loop/installs
   uv --directory <commit>/source sync --frozen --no-editable --no-dev --reinstall-package iorlas-task-loop
   env: the person's environment without every UV_* variable and VIRTUAL_ENV, plus UV_PROJECT_ENVIRONMENT=<install>/venv
   ```
   through `stream_proc.run` (foreground; lines to the terminal and `install.log`; timeout 15 minutes). The working
   directory is the installs root, never the exported source, so a `mise.toml` or `.python-version` inside the commit
   cannot choose the tools that build it; mise resolves `uv` from the installs root's config chain (D14: trusting that
   folder is the person's prerequisite). Stripping `UV_*` and `VIRTUAL_ENV` keeps a shell's active environment, cache or
   index settings from leaking into the build. `--reinstall-package` matches `just install` (the project wheel is
   always rebuilt). `uv` is found with `shutil.which` on `PATH` (a mise shim is fine): absent is `unavailable uv`. A
   non-zero exit or the timeout is `refused build` with the last line and the log path.
6. **Verify**: `<install>/venv/bin/python -I -m taskloop version --json` through `stream_proc.capture` (timeout 60 s),
   run with the same working directory; the answer must parse and its `running.prefix` must resolve to this venv.
   Anything else is `refused verify`. This is the one cross-process read: validated JSON, as CLAUDE.md allows across a
   process boundary. The `tl version` it runs is built in I1, so I2 lands alone.
7. **Manifest** (section 4.3), written last. Lock released.

```
Install: factory-v0.2.0 = 3f2a9c4e1b07... (annotated tag) from /home/u/src/task-loop
Export: 293 files to /home/u/.local/share/task-loop/installs/3f2a9c4e1b07.../source
Build: uv --directory 3f2a9c4e1b07.../source sync --frozen --no-editable --no-dev --reinstall-package iorlas-task-loop (log .../install.log)
Verify: running from /home/u/.local/share/task-loop/installs/3f2a9c4e1b07.../venv
Installed: 3f2a9c4e1b07 factory-v0.2.0; not pinned (tl pin factory-v0.2.0 runs it from the next start)
```

`tl install` never pins, never removes anything, never edits `PATH`, a shell profile, `~/.local/bin` or another install,
and never touches the checkout's working tree, index or refs.

### 6.2 `tl pin REV` and `tl pin --clear`

`REV` is a full commit id or a tag name, resolved **only from installed manifests** (no Git, no checkout: the pin
selects among installs). A commit id opens `installs/<commit>/` by name; a tag name makes `tl pin` read
`installs/<commit>/install.toml` of each directory whose name is 40/64 lowercase hex (lock and temp files skipped by
name; the only enumeration of `installs/`). A tag found in two manifests (a moved tag) is `refused ambiguous`; give the
commit.

Checks: `installs.state` of the install: absent `not_installed`, incomplete `incomplete`, broken `broken`. Then the pin
file is written (section 4.4). `tl pin` never opens factory.db (Q13).

```
Pinned: 3f2a9c4e1b07 (factory-v0.2.0), in /home/u/.config/task-loop/config.pin.toml
Was: 9b1e07d2aa31 (factory-v0.1.0)
Takes effect at the next start of tl. Before relying on it: stop the rounds, wait for or abandon running attempts, then start them again (a running `tl step rounds` and its entries keep their version).
```

Pinning the already-pinned commit prints `Pinned: already ...`, exit 0, file unchanged. `tl pin --clear`: `Pin cleared
(was 3f2a9c4e1b07 factory-v0.2.0); tl runs the install it is started from`, or `Pin cleared: already` with no file.

### 6.3 `tl version [--json]` (built in I1)

Read-only: this process and the pin of the machine config in use (`--config` honoured). No factory.db read, no listing.

```
Running: 3f2a9c4e1b07 factory-v0.2.0 (/home/u/.local/share/task-loop/installs/3f2a9c4e1b07.../venv)
Pinned: 3f2a9c4e1b07 factory-v0.2.0 since 2026-11-20T10:05:00Z (/home/u/.config/task-loop/config.pin.toml)
```

A process whose `sys.prefix` has no complete install beside it says `Running: unmanaged (<sys.prefix>)`; no pin says
`Pinned: none`; an invalid pin says `Pinned: invalid (<path>)`. JSON: `{"running": {"prefix": "...", "install": "<commit>"
| null, "tag": "..." | null}, "pinned": {"commit": "...", "tag": "...", "pinned_at": "...", "file": "..."} | null}`.
Being exempt, `tl version` started from a launcher with a pin describes the launcher's own install; compare `Running`
with `Pinned` to see whether a resolved start would exec elsewhere.

### 6.4 An interrupted install

A Ctrl-C during the build unwinds through `stream_proc`, which stops uv's process tree; the directory stays without a
manifest. A hang-up (the terminal closed: SIGHUP's default action), `kill -9` or a crash ends `tl install` **without**
unwinding: uv is not stopped and may run on as an orphan, still writing `venv/`. Either way the next `tl install` of that
commit refuses:

```
tl install: refused incomplete: /home/u/.local/share/task-loop/installs/3f2a9c4e1b07... has no manifest (an earlier install was interrupted). Check that no uv or tl install runs under that path (ps -o pid=,command= -u "$USER" | grep 3f2a9c4e1b07), remove the directory, and install again.
```

The factory removes nothing: the free lock proves no `tl install` runs, but not that an orphaned uv has stopped
(CLAUDE.md: no deletion on presumed staleness). The person checks `ps` and removes it.

### 6.5 The rounds line

`tl step rounds` writes one line when it starts, after the rounds lock: `<time> <backlog> rounds install <commit12>
[<tag>]`, or `rounds install unmanaged`. Fixed words, display only. No other command changes.

### 6.6 Not commands (minimum set)

No `tl update`, `tl rollback` (it is `tl pin <older>`), `tl uninstall`/`prune`, `tl release`, `tl doctor`, no
`--from-branch`, no `--json` on `install`/`pin`, no automatic `tl install` after a land. Section 14.

## 7. Running rounds on a pin change

| Moment | What runs which version |
|---|---|
| `tl pin B` while rounds of A run | Rounds keep A: their interpreter is A's `venv/bin/python`, and nothing in the rounds reads the pin. Entries they launch afterwards are A (`sys.executable`). Their `rounds.log` start line still says A. |
| A hand `tl step ...` in another shell after the pin | B (a new start resolves). It runs beside A's rounds and entries on the same factory.db. **This is not claimed safe**, even at the same schema: B's code may read A's rows with other assumptions (a changed word, a fence, a status rule). Different schema: B refuses `schema` and changes nothing. |
| Ctrl-C the rounds | The rounds stop (exit 0 or 130). Entries launched by A run on in their own sessions to their conclusion, writing A's results. |
| Start rounds again while A's entries still run | B. B observes A's entries by identity and waits for them; the mixed state of the row above lasts until they end. |

Hence the procedure (section 10, printed by `tl pin`): **drain first** (stop the rounds, wait for every running attempt
to end or abandon it), then pin, then start. `tl pin` does not check for running rounds or entries (reading a held
`flock` needs taking it; entries are only visible through factory.db) and does not refuse while they run (Q7): D9 says
a pin change affects the next start; the drain is the person's step.

## 8. factory.db across versions

- **No schema change in B8**: v14 stays; no install or pin fact in factory.db; no B8 command opens it.
- **A newer factory.db met by older code stays `refused schema`**, unchanged: `require_database` maps the store's
  `SchemaError` for every command that opens factory.db; an older entry still running against a database a newer
  `tl slot adopt` created would refuse at its own open. I3 adds one test per direction at the operations level (a v15
  file under v14 code: `refused schema` "update it"; a v13 file under v14 code: `refused schema`), so B8 pins the word.
- **Upgrade with a schema change** (the existing runbook, no migration): drain with the old version (section 10),
  move factory.db aside (the person's operation), pin the new install, `tl slot adopt` (creates the new schema), start.
- **Rollback** is `tl pin <older>`. With a compatible factory.db it simply runs. Onto a newer factory.db, `tl pin`
  writes the pin anyway (it never opens factory.db) and the older code refuses `schema` at its first command, naming
  both versions; the person pins forward again or discards factory.db. Nothing restores, migrates or deletes factory.db
  automatically, which meets the INSTALL-OWNER acceptance ("explicit rollback refuses an incompatible runtime DB")
  through the refusal at use, not at pin time. This reading needs the owner's sign-off (**Q13**).
- A factory.db discard never touches the pin file or `installs/`.

## 9. Release

A release is an **annotated tag** on a commit of `main`, made and pushed by the person:

```
git -C <checkout> tag -a factory-v0.2.0 -m "factory v0.2.0: <one line>" <commit on main>
git -C <checkout> push origin factory-v0.2.0
```

The factory makes no tag, publishes nothing, reads no release notes, and keeps no release record. `tl install` accepts
the tag by name and records it in the manifest; it also accepts a full commit id, so a landed change can be adopted
without a release (section 10). Tag names (Q6): a `factory-v<major>.<minor>.<patch>` prefix keeps them apart from the
baseline's `v0.23.*` release line in the same repository, whose tooling may still read `v*` tags; the prefix is a
convention, not checked. The proposed release contract in [operations](../tl-8bh9.8/operations.md) (release clone,
manifest bump, marketplace effects) stays unbuilt and proposed; the brief's "no marketplace" excludes it here. The first
release waits for Q9.

## 10. Adopting a self-hosting land of factory code

| # | Who | Step |
|---|---|---|
| 1 | person | `tl step land T`: S is on origin's `main` (M3). The running factory is unaffected (D9). |
| 2 | person | `git -C <checkout> pull --ff-only` (the factory never writes the main checkout). |
| 3 | person, optional | Tag S (section 9) and push the tag. |
| 4 | person | `tl install factory-v0.2.0 --checkout <checkout>` (or `tl install <S>`): rounds may keep running. |
| 5 | person | **Drain**, always: Ctrl-C the rounds; with `tl step list` (old version, still pinned) wait until no attempt runs, or `tl step release --abandon` the ones that should not finish. |
| 6 | person | Same schema: `tl pin factory-v0.2.0`; start the rounds. Schema changed (the new code refuses `schema` at once: try `tl step list` after pinning, or read S's diff of `factory_schema.py`): move factory.db aside, `tl slot adopt <checkout>`, start the rounds. Abandoned tasks restart at plan (D4). |
| 7 | person, on trouble | Drain, `tl pin <previous>`, start (section 8 for the schema case). |

Checklist item 7 of the roadmap ("changes landed on `main`, including changes to the factory, never affect the running
factory; they take effect when the person changes the pin and restarts") is this table.

## 11. Refusal words

`refused <word>` exits 1, `unavailable <word>` exits 3. Every refusal changes nothing, except that an interrupted build
leaves its own incomplete directory (section 6.4).

| Command | Word | When |
|---|---|---|
| `tl` (resolver) | `pin:invalid` | pin file unreadable, not TOML, an unknown key, `format` not 1, a bad commit id |
| `tl` | `pin:missing` | no `installs/<commit>/` |
| `tl` | `pin:incomplete` | the directory has no manifest (an install never finished, or is still building) |
| `tl` | `pin:broken` | a manifest that fails `installs.state` (bad keys, other commit, python missing or not executable) |
| `tl` | unavailable `pin:exec` | `execv` failed |
| `tl install` | `revision` | REV is neither an exactly named tag nor a full commit id of a commit in the checkout (a tree or blob id included) |
| `tl install` | `not_annotated` | REV is a lightweight tag |
| `tl install` | `checkout` | PATH is not a supported checkout (`inspect_checkout`'s kinds) |
| `tl install` | `busy` | another `tl install` of the same commit holds its lock |
| `tl install` | `incomplete` | the directory exists without a manifest (section 6.4) |
| `tl install` | `broken` | the directory has a manifest that fails `installs.state` |
| `tl install` | `tree` | a symlink, gitlink or unsafe path in the commit's tree |
| `tl install` | `build` | uv exited non-zero or timed out |
| `tl install` | `verify` | the new install's `version --json` failed, timed out or named another prefix |
| `tl install` | unavailable `uv`, `git`, `write` | uv not on `PATH`; Git unreadable; the installs folder cannot be written |
| `tl pin` | `not_installed`, `incomplete`, `broken` | `installs.state` of REV's install |
| `tl pin` | `ambiguous` | a tag name recorded by two installs |
| `tl pin` | unavailable `write` | the pin file cannot be written or removed |
| every factory.db command | `schema` | unchanged (section 8) |

## 12. Installed as a pip/uv package, and macOS

- **The launcher is whatever `tl` the person runs.** Any B8-or-later venv-based install is a launcher: a `uv tool
  install` or `pipx install` of `iorlas-task-loop` (its `tl` console script is `taskloop.start:main`), a `pip install`
  into a virtual environment, an install directory's `venv/bin/tl`, or a runner `.venv/bin/tl`. **Only venv-based
  installs are supported launchers**: a `pip install --user` (or into the system interpreter) puts the package in the
  user or system site, which the exec's `-I` (no user site) hides, so `python -I -m taskloop` would not find it; no code
  works around this. Unpinned, it runs itself; pinned, it execs the pin. B8 needs no package index: section 6.1
  installs from Git objects. A later `tl install --index VERSION` (not built) would write the same layout with an index
  version as the directory name and manifest key; resolution would not change.
- **PATH is the person's.** B8 writes no PATH entry. On the owner's machine `~/.local/bin/tl` is the baseline's
  launcher: B8 never replaces it (CLAUDE.md: preserve foreign PATH entries). Until the cutover the person invokes the
  successor by path or an alias (for example `alias tlx=~/.local/share/task-loop/installs/<first>/venv/bin/tl`; any
  install works as the launcher once a pin exists). Replacing `~/.local/bin/tl` is the person's cutover.
- **macOS**: the same paths (`~/.local/share/task-loop/installs`, `~/.config/task-loop/config.pin.toml`), as
  `machine_config` already uses `~/.local/...` on every platform (Q5). `~/Library/Application Support` is not used: its
  space breaks console-script shebangs (installers fall back to a `/bin/sh` trampoline) and it would split the D14
  folder from the slots default. Path comparison uses `Path.resolve()` on both sides (`/var` versus `/private/var`).
  `os.execv` and a uv-managed CPython behave the same on both; not observed on macOS (section 20).
- **Windows**: not supported (roadmap section 6).

## 13. Security and risks

- **An install runs code from the named commit at build time** (hatchling and any build hook in that commit's
  `pyproject.toml`) with the person's environment (minus `UV_*`, `VIRTUAL_ENV`) and network. The person names the
  commit; the land summary already lists build and check configuration changes. Accepted, as D10/D12 accept setup.
- **The uv and Python that build an install** come from the person's machine: mise picks `uv` from the installs root's
  config chain (global config, unless the person put a `mise.toml` above it); an untrusted config there makes the mise
  shim refuse (`refused build` with mise's line; trusting is the D14 prerequisite). A `uv` older than the one that wrote
  `uv.lock` may refuse the lock (`refused build`; the person upgrades uv). The venv's `bin/python` links to a uv-managed
  CPython by its exact version directory (for example `cpython-3.15.0-linux-x86_64-gnu`): `uv python upgrade` or
  `uninstall` of that patch version can remove the target, making every install built on it `broken`; the person moves
  the directory aside and installs again.
- **A tag can be moved** by whoever can push tags. The install is keyed by commit; a moved tag yields a second install
  and `tl pin <tag>` refuses `ambiguous`.
- **Agents and checks that run `tl` get the pinned factory** (Q14). The resolver runs for every `tl`, including one an
  implement agent or a check starts inside a slot (its `.venv/bin/tl` from `setup`): with a pin set, that process execs
  the pinned factory install, not the code under test, against the person's machine config (the agent's environment
  keeps `HOME`). Before B8 it ran the slot's code against the same config. Resolution stays unconditional (no
  environment switch that an agent could also set). The sandbox still keeps an implement agent from writing outside its
  slot; checks run on the host (D10) and this repository's checks never start `tl` (its tests call `cli.main`
  in-process). Proposed, slice I3: the implement input (`implement_step`) and AGENTS.md/CLAUDE.md (mirrored) say "`tl`
  runs the owner's pinned factory; run the code under test as `uv run python -I -m taskloop ...` or through the tests".
- **Mixed versions on one factory.db** (section 7) are avoided by the drain, not by the schema check.
- **Removing an install by hand while something runs from it** breaks that process: the person checks `ps` first
  (section 14).

## 14. What is not built

- Removing, pruning or rebuilding installs, an incomplete directory included (section 6.4): no liveness proof of who
  runs from an install, or of an orphaned uv, exists. The person removes a directory after checking with `ps`.
- Any marketplace, plugin cache, canary, ring, `devbox-ok` acknowledgement or macOS pin restriction (Q9).
- A release command, release clone, version bump, changelog, package-index publication or release record.
- Live upgrade, step-boundary re-exec, counter transfer, automatic fallback to another install, newest-directory
  selection, auto-pin after `tl install`, auto-install after a land.
- A pin per backlog or per repository; a pin read by rounds, entries or the dashboard.
- Any factory.db read in B8: no schema notice in `tl pin`, no `stored_version` (Q13); no schema or Python version in the
  manifest; no installs listing in `tl version`; no version column in factory.db (Q11); no check for running rounds
  before a pin change (Q7).
- `--json` on `tl install` and `tl pin`.
- Session hooks, a `tl doctor`, PATH or shell-profile edits, the baseline cutover of `~/.local/bin/tl`.
- Windows.

## 15. Glossary changes (slice I3)

Add **install** ("one immutable build of one commit under `~/.local/share/task-loop/installs/<commit>/`, complete when
its manifest exists and `installs.state` accepts it; made only by `tl install`, removed only by the person"), **pin**
("the owner's choice of install for one machine config, `<config stem>.pin.toml` beside it, written only by `tl pin`;
read once by `tl` at start"), **launcher** ("whichever `tl` the person starts; it execs the pinned install or, unpinned,
its own interpreter"). Amend **release** ("an annotated tag on `main` by the person; the factory makes none") and
**config** (the pin is beside it, not in it).

## 16. Test plan (pytest functions, fakes through ports, no process in factory tests)

- **Resolver** (I1), pure over a file-read port, `home`, `executable` and `prefix`: each exempt command, with and
  without a bad pin; no pin (exec of the own `sys.executable`); every `pin:invalid` case (unreadable, bad TOML, unknown
  key, `format = 2`, short id); `missing`; `incomplete`; `broken` (bad manifest, other commit, python absent, python not
  executable, python a dangling link); exec with the exact argv (`-I -m taskloop` and argv[1:] unchanged, including
  `--config` and `--json`). **Pre-scan**: `--config FILE` and `--config=FILE` choose the pin; `tl --config install step
  list` takes `install` as the config value and `step` as the command (resolved, not exempt); a subcommand's own flag
  after the command word is not read. **Two configs in one folder** (`a.toml`, `b.toml`) read `a.pin.toml` and
  `b.pin.toml`. `start.main` with a recording exec port: no exec on a refusal, the JSON refusal shape, `pin:exec` on
  `OSError`.
- **Exec loop, end to end** (I1): a launcher prefix and a pinned install in `tmp_path`; `start.main` execs into the
  pinned python with `-m taskloop`; then `__main__`'s path (`cli.main`, called in-process with the same argv) runs
  without calling the resolver (a resolver port that fails the test if called); the import contract proves `__main__`
  never imports `start`.
- **Nothing imported before the decision** (I1): the `start-decides-before-the-cli` contract; a policy test reading
  `start.py`, `installs.py` and `pin_file.py`'s AST imports (standard library and each other only, no dynamic import).
- **Policy** (I1): `execv` only in `start.py`; every other `os.exec*`, `posix_spawn*`, `fork*`, `spawn*`, a `pty` or
  `multiprocessing` import fails (mutation: add each to another module); the console script in `pyproject.toml` names
  `taskloop.start:main`; `entry-never-imports-the-command-surface` gains `start`, `installs`, `pin_file`, `install_op`,
  `cli_install`; `process-lock-owners` gains `install_op`.
- **Pin file, manifest, `installs.state`** (I1): round trip of the writers through `tomllib`; escaping of a path with
  `"` and `\`; atomic replace leaves the old file on a failed write (a write port that raises); `--clear` of an absent
  file; each state of 4.3 (absent, incomplete, broken per condition, complete).
- **`tl version`** (I1): lines and JSON for managed, unmanaged, pinned, unpinned, invalid pin; it reads no lock or temp
  file (a `<commit>.lock` and `install.toml.tmp` present change nothing).
- **Install** (I2), over the git-porcelain fake (a repository with an annotated tag, a lightweight tag, a tag of a tag,
  tags `v1` and `v1-rc`, a branch, a symlink entry), a scripted run port (exit codes, lines, timeout,
  `KeyboardInterrupt`) and a scripted capture port (good JSON, bad JSON, wrong prefix, timeout): each refusal of section
  11 with nothing written beyond the incomplete directory; **tree-id and blob-id REV** refused `revision`; **tag prefix**:
  `v1` finds only `refs/tags/v1`; the manifest written last (a failure in verify leaves no manifest); `already` writes
  nothing; **a broken manifest** refuses `broken` (same `installs.state` as pin); **an incomplete directory** refuses
  `incomplete` naming the path and removes nothing; **an orphaned build** (the run port reports nothing because the test
  stops the operation as a `kill -9` would: no unwinding, the directory left without manifest; a second invocation)
  refuses `incomplete`; **manifest-vs-lock race**: while the lock is held by the test and no manifest exists, `tl pin`
  and the resolver say `incomplete` and `tl install` says `busy`; a reader during the manifest's write sees the old
  absence or the whole file (the write port pauses between temp write and rename); **uv cwd and argv**: the run port
  receives cwd = the installs root, the exact argv of 6.1 step 5, an environment with no `UV_*` but
  `UV_PROJECT_ENVIRONMENT` and no `VIRTUAL_ENV`; modes 100644/100755 exported; the checkout's refs and index untouched
  (the fake's state compared).
- **Pin** (I3): pin by commit and by tag; `ambiguous`; `already`; each `installs.state` refusal; factory.db never
  opened (a database path that does not exist and a port that fails if touched). The `rounds install` line written once
  after the lock (rounds test with the existing doubles). The implement input's `tl` sentence (Q14).
- **Schema words** (I3): a v15 factory.db under the v14 code refuses `schema` for `tl step list`, `show`, `start`,
  `next`, `land --summary` and `slot adopt`; a v13 file the same; nothing written (file digest equal).
- **Real** (I2, under `tests/steps/real/` if the existing real-Git tests allow it without a process in factory tests):
  export of a temporary repository's annotated tag through the real `git_porcelain`, modes and bytes compared; a tree id
  refused. The uv build is not run in tests (network, minutes): the live smoke covers it.

## 17. Live smoke plan (M5's B8 part; runbook written in I3)

Base: the [M4 runbook](../tl-8bh9.14.9/live-smoke.md) section 0 with `$M5`: scratch remote, scratch tracker, scratch
`config.toml` at `$M5/config.toml` (so the pin is `$M5/config.pin.toml`: the person's real pin is never touched),
schema v14, one slot. Installs go to the real `~/.local/share/task-loop/installs/` (additive; the runbook lists the
smoke's commit ids and, at the end, removes those directories after `ps` shows nothing runs from them). Linux first;
steps 1-3 again on macOS.

0. Commits: **A** = the I3 commit; **B** = A plus one harmless change on a scratch branch (never pushed to the real
   origin); **C** = B with `factory_schema.SCHEMA` version 15 and a no-op DDL addition (scratch branch). Tag A
   `factory-smoke-a` (annotated, local only); B and C by commit id. Launcher: `$M5/runner/.venv/bin/tl` (a runner at A);
   `TL() { "$M5/runner/.venv/bin/tl" --config "$M5/config.toml" "$@"; }`.
1. `TL install factory-smoke-a --checkout $SRC`: the five lines; `TL install` again: `already`. A lightweight tag:
   `not_annotated`; `main`: `revision`; `A^{tree}`'s id: `revision`.
2. Interrupts: `TL install <B>` and Ctrl-C during `Build`: no manifest, no uv left (`ps`); `TL install <B>`: `refused
   incomplete` naming the path; remove it by hand; install again. Then `TL install <B>` from a second terminal that is
   closed during `Build` (SIGHUP): record whether uv survives (`ps -o pid=,ppid=,command= -u "$USER" | grep <B>`); wait
   for it to end, then `refused incomplete`, remove, install.
3. Unpinned: `TL version`: `Running: unmanaged (.../runner/.venv)`, `Pinned: none`. `TL pin factory-smoke-a`; `TL
   step list` resolves (`ps -o pid=,command= -p <pid of a TL step rounds>` shows `.../installs/<A>/venv/bin/python -I -m
   taskloop ...`).
4. Rounds of A with one `auto` task (the M4 tiny-task text). While its plan agent runs: `TL pin <B>`; the pin output's
   drain line; the rounds' and the entry's command lines (`ps`, verified pids) still name A; `rounds.log`'s start line
   says A. Drain (Ctrl-C, wait until `TL step list` shows nothing running), start again: `rounds install <B>`; the task
   finishes under B.
5. Schema: `TL install <C>`, drain, `TL pin <C>`; `TL step list`: `refused schema` (v14 file, v15 code). `TL pin
   factory-smoke-a` (rollback): works. Move factory.db aside, `TL pin <C>`, `TL slot adopt`: v15; `TL pin
   factory-smoke-a`: written without a word about the database; `TL step list` refuses `schema` "update it"; factory.db's
   digest unchanged. Restore the v14 file.
6. Broken and missing: hand-edit `$M5/config.pin.toml` to an absent commit: `TL step list` is `refused pin:missing`; `TL
   version` and `TL pin --clear` still work. Rename B's `venv/bin/python` aside (a smoke-made install): `refused
   pin:broken`, and `TL install <B>` refuses `broken`; restore it. A `format = 2` pin: `pin:invalid`.
7. Development bypass: `$M5/runner/.venv/bin/python -I -m taskloop --config $M5/config.toml version` with a pin set:
   `Running: unmanaged`, `Pinned: <pin>`.
8. macOS: steps 1-3 (paths, exec, uv-managed Python).
9. Record findings in `docs/design/tl-8bh9.8.3/m5-smoke-findings.md`.

## 18. Slices (caps: 400 code lines per file, 80 per function, 800 per test file)

| Order | Slice | What | Source | Tests |
|---|---|---|---|---|
| 1 | **I1 resolver, pin file, manifest validity, the one exec, `tl version`** | `installs.py` (layout, manifest read/validate, `state`), `pin_file.py` (read, write, clear), `start.py` (console entry, pre-scan, `resolve` (section 5.2), refusal rendering, `os.execv` of the pinned or own interpreter), `cli_install.py` with `tl version [--json]`, the `pyproject` script entry, the exec policy test, the import contracts (`start` in the layers, `start-decides-before-the-cli`) | `installs` ~130, `pin_file` ~70, `start` ~60, `cli_install` ~60, `cli` +5, `pyproject` 1, `.importlinter` ~20 | `test_installs.py` ~330, `test_pin_file.py` ~120, `test_start.py` ~260 (pre-scan, two configs, exec loop), `test_version_cli.py` ~120, `test_policy` +70 |
| 2 | **I2 `tl install`** | `install_op.py` (REV checks, lock, state under the lock, native export from `Tree`, uv build with cwd/argv/env of 6.1, verify through `tl version --json`, manifest), the `install` subcommand in `cli_install`, real ports in `cli_composition` (`stream_proc.run`/`capture`, `process_lock`) | `install_op` ~230, `cli_install` +50, `cli_composition` +35 | `test_install_op.py` ~600 (split in two files if it passes 800), `tests/cli/test_install_cli.py` ~150, real export ~80 |
| 3 | **I3 `tl pin`, rounds line, words and docs** | `pin` and `--clear` in `cli_install`, the `rounds install` line, the implement input's `tl` sentence and the AGENTS.md/CLAUDE.md mirror (Q14), schema-word tests, glossary (section 15), roadmap B8 and section 1 rows, INDEX status, the M5 runbook `live-smoke.md` | `cli_install` +90, `rounds` +8, `implement_step` +2 | `tests/cli/test_pin_cli.py` ~220, schema words ~120, rounds +30, implement input +10 |
| 4 | **M5 B8 smoke** | Section 17, owner-run or by an authorized agent; findings file | none | none |

Total about +760 source and +2,200 test lines (I1 ~345 / ~900, I2 ~315 / ~830, I3 ~100 / ~380); no shelf change (REV
checks and export use `Repo.tree`, `Repo.refs` and `Repo.history` of git-porcelain 0.17.0; builds and the verification
use `stream_proc` 0.6.0's `run` and `capture`). Dependencies: I2 after I1 (its verification runs I1's `tl version`), I3
after I2 (its tests need only `installs.state`, but its runbook needs `tl install`), the smoke after I3. Each slice lands green with `just check` and `just test`, independently reviewed. The runner
worktree (O6's interim) stays the way to run the factory until I3 is built; the first install is made by the runner's
`tl install`. Tracker: children of tl-8bh9.8.3 (filed when the owner accepts this plan).

## 19. Open questions, each with a recommendation

1. **Q1. Exec into the pinned install, refuse, or a `current` symlink?** **Recommendation: exec once at start
   (sections 5.3, 5.4)**, with `start.py` the only exec user, enforced by a policy test. Refusing makes the person keep
   a PATH entry in step with the pin; a symlink loses the typed refusal and the per-config pin.
2. **Q2. Where the pin lives.** **Recommendation: `<config stem>.pin.toml` beside the machine config in use** (default
   `~/.config/task-loop/config.pin.toml`): one pin per factory, two configs in one folder kept apart, scratch smokes
   isolated by `--config`, no rewrite of the person's `config.toml`. Alternatives: a fixed per-user file (smokes would
   touch the real pin), or a `pin` key in `config.toml` (the person's hand-edited file rewritten by a command).
3. **Q3. Install identity.** **Recommendation: the full commit id is the directory name and the pin's key; a tag is a
   recorded label.** An untagged commit may be installed and pinned (daily self-hosting without a release).
4. **Q4. What `tl install` accepts.** **Recommendation: an exactly named annotated tag or a full commit id of a commit
   only**; no branch, short id, lightweight tag, tree or blob id.
5. **Q5. The D14 folder on macOS.** **Recommendation: `~/.local/share/task-loop` on both Linux and macOS**, as
   `machine_config` already does for slots; not `~/Library/Application Support` (space in shebangs, split folder).
6. **Q6. Tag names.** **Recommendation: `factory-v<major>.<minor>.<patch>`**, not continuing `v0.23.*`, so baseline
   release tooling never mistakes a successor release for its own. Convention only.
7. **Q7. A pin change while rounds run.** **Recommendation: allowed; `tl pin` prints the drain procedure; the person
   drains before relying on it.** Alternative: refuse while a rounds lock of the configured factory.db is held (needs a
   non-taking lock read from `process_lock`, not available today, and still misses entries without rounds).
8. **Q8. An incomplete install directory.** **Recommendation: `refused incomplete` naming the path; the person removes
   it after checking `ps`** (review H2). Rejected: an automatic remove-and-rebuild under the install lock, since the free
   lock does not prove an orphaned uv (after SIGHUP or `kill -9`) has stopped.
9. **Q9. Baseline `devbox-ok` and the macOS pin restriction. BLOCKING FOR THE FIRST RELEASE.** **Recommendation: not
   carried** (canary and marketplace rollout policy, excluded by this block's brief). [operations](../tl-8bh9.8/operations.md)
   says to keep them unless the owner changes it, so the owner must say so before a `factory-v*` tag is made under this
   design. The slices do not depend on the answer.
10. **Q10. Removing old installs.** **Recommendation: by hand only**, until a liveness proof of the processes running
    from an install exists.
11. **Q11. Record the version per attempt in factory.db?** **Recommendation: no** (one `rounds install` log line and
    `tl version`); revisit with the dashboard, batched into a later schema change if wanted.
12. **Q12. Unpinned behaviour.** **Recommendation: run the started `tl`'s own install** (the installation manager's
    selection, INSTALL-OWNER), never refuse for a missing pin; the `rounds install` line shows `unmanaged` or the id.
13. **Q13. Rollback onto a newer factory.db. Needs the owner's sign-off.** **Recommendation: notice-only through the
    existing refusal**: `tl pin <older>` never opens factory.db and never refuses; the older code's `refused schema` at
    its first command is the refusal the INSTALL-OWNER acceptance asks for. Alternatives: `tl pin` refuses when the
    install's known schema is older than factory.db's (needs a schema record in the manifest and a database read in
    `tl pin`, both cut as over-building), or prints a notice (the same reads, no refusal).
14. **Q14. Telling agents that `tl` is the pinned factory.** **Recommendation: resolution always applies; the
    implement input and AGENTS.md/CLAUDE.md say `tl` runs the owner's pinned factory and the code under test runs as
    `uv run python -I -m taskloop ...` or through the tests.** Rejected: an environment variable that skips resolution
    (an agent could set it as easily as read it).
15. **Q15. "Run here" also execs.** **Recommendation: `start` execs the own `sys.executable -I -m taskloop` when no pin
    applies**, so it never imports the CLI (no `Any`, no ignore escape); costs one interpreter start.

## 20. Not verified

- Time and correctness of exporting ~300 files through one `cat-file` per blob (`Repo.tree(...).read`); a shelf
  `archive` operation is the fallback if it is slow (not proposed now).
- That `uv --directory <source> sync --frozen --no-editable --no-dev --reinstall-package iorlas-task-loop` with
  `UV_PROJECT_ENVIRONMENT` outside the project and the installs root as cwd builds a working environment whose
  `venv/bin/tl` and `python -I -m taskloop` run from any working directory.
- `Repo.history([<tree id>], limit=1)` raising or answering empty on the real repository and the fake (the tree-id
  refusal relies on it; I2's real test checks it first).
- Whether uv survives a SIGHUP of `tl install` (smoke step 2 records it); the design assumes it may.
- That uv's console-script shebangs under `installs/<64-hex>/venv/bin/` stay under the kernel's shebang length limit
  (Linux 256 bytes; macOS 512): about 100 bytes with a 40-hex id and a short home.
- `os.execv` of a uv-managed CPython 3.15 on macOS; `Path.resolve()` equality of `sys.prefix` through macOS's `/private`
  links.
- Whether the baseline's installed tooling reads `factory-v*` tags (Q6 assumes it reads `v*` only).
- Line estimates, from the module sizes at 26be8f7ae.

## 21. Review repairs (2026-11-12)

An independent review of the first version of this plan found the points below; all are taken.

| # | Finding | Repair |
|---|---|---|
| H1 | I2's verify called `tl version --json`, built only in I3 | A minimal `tl version [--json]` (the `running` block) moves into I1 (sections 6.3, 18) |
| H2 | Automatic remove-and-rebuild of an incomplete directory deleted on presumed staleness; an orphaned uv after SIGHUP or `kill -9` can still write | `refused incomplete` naming the path; the person checks `ps` and removes it (section 6.4, Q8) |
| H3 | Install state was decided partly outside the lock, and `already` used its own validity | `tl install` decides the state only under the lock; one `installs.state` for every command; `refused broken` for a present but invalid manifest (sections 4.2, 4.3, 6.1, 11) |
| M1 | uv ran in the exported source with the person's `UV_*`/`VIRTUAL_ENV` | cwd the installs root, `uv --directory <source> sync --frozen --no-editable --no-dev --reinstall-package iorlas-task-loop`, `UV_*` and `VIRTUAL_ENV` stripped; mise trust and uv-version risks stated; cwd/argv/env test (sections 6.1, 13, 16) |
| M2 | Q9 was not marked blocking; rollback's relation to the acceptance was unclear | Q9 blocking for the first release; Q13 states that `tl pin` never refuses and the older code's `refused schema` is the refusal, for the owner's sign-off (sections 2, 8, 19) |
| M3 | The plan said matching schemas made mixed versions safe | Removed; the upgrade and rollback procedures always drain first (sections 3, 7, 10) |
| M4 | Agents and checks running `tl` in a slot would get the pinned factory, unstated | Stated; resolution stays unconditional; implement input and AGENTS.md/CLAUDE.md note proposed in I3 (section 13, Q14) |
| M5 | The exec policy covered too little; `start` imported the CLI before deciding | Policy covers every `os.exec*`, `posix_spawn*`, `fork*`, `spawn*`, `pty`, `multiprocessing`; `start` in the layers contract and a forbidden contract; `start` execs the own interpreter instead of importing the CLI (sections 5.2, 5.3, Q15) |
| 9 | Over-building | Cut: the factory.db schema notice and `stored_version`, `schema`/`python` in the manifest and the verification, the installs listing and `Resolves to:` in `tl version`, `--json` on `install`/`pin`; slices re-sized (section 18) |
| 10 | Low items | Tree and blob ids refused (`history` check); exact tag-name match; stricter annotated test; the pin file is `<config stem>.pin.toml`; `tl version` reads no lock or temp file, and the only enumeration of `installs/` (`tl pin`'s tag lookup) skips them; the uv-managed Python's patch-version link noted (sections 4, 6.1, 6.2, 13); roadmap B8/O6 wording fixed |
| 11 | Missing tests | Added: manifest-vs-lock race, orphaned uv, uv cwd/argv/env, broken manifest install, tree-id REV, tag prefix, `--config install` pre-scan, two configs in one folder, exec loop end to end, nothing imported before the decision (section 16) |

Also recorded: the `current`-symlink alternative and why exec stays (section 5.4).

**I1 as built (2026-11-12).** Deviations, each stated in its section: `resolve` lives in `start.py` and takes no
`sys.prefix` (5.2); `pin_file` imports `machine_config.config_file`, held to the standard library by the policy test
(5.3); a nameless `--config` is `pin:invalid` (5.2); only venv-based launchers (12). Also: `installs.state` examines
`installs/<commit>` and its manifest through the port's `kind` (a file, a link to nothing or an unexaminable path is
`broken` with a detail, never `absent` or `incomplete`); a `tag` is checked as a tag name on read; `format` must be the
integer 1; the atomic writer uses a unique temporary file beside its target and removes it on any failure; `tl version`
counts a prefix as managed only under this home's installs root, and reports an invalid pin as
`{"invalid": <why>, "file": <path or null>}` in JSON. Unrelated stale-test repair in the same change:
`tests/rules/test_isolation.py` expected the shelf tag `git-porcelain-v0.16.0` after `pyproject.toml` moved to v0.17.0
(dfba4675c); it now expects v0.17.0.
