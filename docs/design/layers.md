# Layers: which software manages which

Bead tl-isfa.3 (epic tl-isfa, "Remove factory self-management"). Written 2026-11-12. Documentation only: no code changed.

**Status: every judgment below is proposed** unless it is a quoted owner decision. Nothing here moves, renames or
deletes code; tl-isfa.1 (code removal) and tl-isfa.2 (docs removal) are separate tasks.

Owner decision (2026-11-12, quoted from the epic's brief): the factory should care only about its own work and its
children's work (tasks, steps, slots, agents). Software that manages software (installs, versions, pins, releases,
host machine state) is a different layer. Terms follow [the glossary](../glossary.md).

## 1. The layers (proposed)

| Layer | What it is | What it manages | Knows about |
|---|---|---|---|
| L0 person | The owner at a terminal | Everything below, by deciding and typing commands | n/a |
| L1 package manager | uv, mise, just and repo scripts (`justfile`, `mise.toml`, `uv.lock`) | Which software of which version is on the machine: the factory's own install, tool pins, the project's environment, releases | The host; not the factory's tasks |
| L2 host / OS | The machine: file system, process table, power, platform tools (`caffeinate`, `systemd-inhibit`) | Processes, files, sleep, users | Itself |
| L3 factory | `taskloop` (`tl`): tasks, steps, attempts, slots, factory.db, rounds, check, land | Its work and its children: slots, agent attempts, check attempts, delivery | The layers below it only through explicit ports |
| L4 agents | Codex or Claude Code, run by the factory inside a slot | One attempt's conversation and its edits in the slot | The slot's files and the prompt; nothing of the factory's state |
| external owners | Task tracker (bd) and Git | Tasks, requirements, discussion (tracker); code, plans, task branches, refs (Git) | Themselves. Factory reads and writes them through typed clients (`beads_client`, `git_porcelain`) |

"Manages" reads top-down: the person manages the package manager, which puts the factory (and its pinned tools) on
the host; the factory manages agents. The tracker and Git are not layers in that stack: they are owners of facts
that the factory and agents consume (CLAUDE.md "one owner per fact").

What the owner decision removes from L3: installing a build of the factory (`tl install`), choosing which build runs
(`tl pin`, the `start` exec shim), reporting which is running (`tl version`), and the per-user install folder and pin
file. All of those are L1 work: uv, mise or a script does it before `tl` runs, and the person (L0) picks the version.

## 2. Dependency direction (proposed)

Rule: **a layer knows only itself and the layer directly below it.** Knowing means importing, naming in code,
parsing its files or printing instructions about it.

- L3 factory reaches the host only through explicit ports (CLAUDE.md "state/time/IO enter through narrow ports"):
  process, lock, file and agent APIs of the shelf. It never imports, shells to or mentions uv, mise, just, a pin, an
  install folder or a release.
- L3 factory does not know L1 at all. A repo may name `just bootstrap` in its own `.task-loop.json` `setup`: that is
  the repo (L0's data) addressing L1; the factory runs an argv it was given and does not interpret it.
- L4 agents know the slot and the prompt. They never read factory.db, install state or pins.
- L1 never reads factory.db or tracker data; it may build the factory but does not schedule work.
- Nothing below ever depends on something above (the host does not know the factory; the factory does not know the
  person's CLI choices beyond its own arguments).

### How import-linter could enforce a few of them (proposal only; nothing added here)

The repo already has contracts in `.importlinter` (`one-signal-owner`, `process-lock-owners`, `no-runtime-mechanisms`,
`profile-is-domain`). Candidates, each a new contract a later task would write and test:

1. `factory-has-no-package-manager`: type `forbidden`, `source_modules = taskloop`, forbidden `venv`, `ensurepip`,
   `site`, `sysconfig`, `zipapp`, `tomllib` outside the profile and machine-config readers (via `ignore_imports`).
   It catches the install/pin machinery coming back as imports. It cannot catch strings such as `"uv"` or
   `".local/share/task-loop"`: that needs the existing policy AST test extended (a literal scan of `src/taskloop`).
2. `host-only-in-adapters`: type `forbidden`, `source_modules` the domain and store modules (the factory core listed in
   section 4), forbidden `shutil`, `platform` and `sys` (platform use), `ignore_imports` for the named adapter
   modules (`composition`, `cli_composition`, `slot_env`, `keep_awake` if it stays, `agent_credentials`, `slot_files`).
   Whether `os`/`sys` can be included depends on how much the core uses them today: measure first.
3. `factory-layers`: type `layers` over the factory's own internals: `cli` over `operations` over the step machinery
   over stores over `factory_schema`, with `exhaustive = true` so a new module must be placed. That enforces "each layer
   knows the one below" inside L3 and makes section 4's table checkable.
4. `agent-environment-is-an-adapter`: type `forbidden` keeping `access`, `slot_env` and `environment` unimported by
   the domain/store modules, so the agent-environment code (flagged in section 5) stays behind one boundary and can be
   moved or deleted without a ripple.

Contract 3 is the most valuable and the largest; 1 is the cheapest and directly guards this epic.

## 3. CLI commands (proposed owner)

Source: `cli.py`, `cli_step.py`, `cli_install.py` (6 install modules and 3 commands exist on main after PR #724).

| Command | Owner layer | Note |
|---|---|---|
| `tl install REV --checkout PATH` | removed: package-manager layer | `cli_install`, `install_op`, `installs` |
| `tl pin REV` / `tl pin --clear` | removed: package-manager layer | `pin_op`, `pin_file` |
| `tl version [--json]` | removed: package-manager layer | reports install and pin; the factory has nothing to say about its own build |
| `tl` console script (`start`, the exec shim) | removed: package-manager layer | resolves the pin, then `os.execv` |
| `tl repo inspect` | factory | read-only Git view of a checkout |
| `tl task show` | factory | tracker read through the tracker client |
| `tl profile show` | factory | prints `.task-loop.json` read from Git |
| `tl config show` | factory | machine config (paths, slot count); see flag on its contents in section 5 |
| `tl slot adopt` | factory | registers a managed slot |
| `tl step start` | factory | admit, relaunch, repeat or advance |
| `tl step show` / `tl step list` | factory | read-only status |
| `tl step verify` | factory | settle a stored answer |
| `tl step release` | factory | free a slot reservation |
| `tl step next` | factory | one scheduling round |
| `tl step rounds` | factory | rounds until stopped; also starts keep-awake (see flag) |
| `tl step publish` | factory | push the verified plan to `task/<id>` |
| `tl step land` | factory | squash, validate, push, close |

Not a `tl` command but a layer-spanning thing: `python -I -m taskloop.attempt_entry` and `taskloop.check_entry`, the
factory's own entry processes for one admitted attempt (factory).

## 4. Modules in `src/taskloop` (proposed owner)

89 files. Owner layer is one of: **factory**, **host**, **removed: package-manager layer**. No module is proposed for
L1 (kept) or L4: agents are external programs, and the code that builds their environment is a factory adapter
(flagged in section 5). Tracker and Git adapters are factory code even though the facts they read are owned by the
tracker and Git.

### Removed: package-manager layer (6)

`cli_install`, `install_op`, `installs`, `pin_file`, `pin_op`, `start`.

### Host (1, flagged)

| Module | Role |
|---|---|
| `keep_awake` | Asks the OS not to idle-sleep while rounds run (`caffeinate`, `systemd-inhibit`). Flagged below. |

### Factory (82)

| Area | Modules |
|---|---|
| Command surface | `__main__`, `cli`, `cli_step`, `cli_composition`, `exit_codes`, `step_guide`, `step_render`, `show_render`, `result_data`, `step_text` |
| Wiring and operations | `composition`, `operations`, `round`, `rounds`, `rounds_lock`, `round_log`, `interrupts`, `selection` |
| Machine config and profile | `machine_config`, `profile` |
| Store and schema | `factory_schema`, `attempt_store`, `attempt_reads`, `attempt_types`, `attempt_status`, `check_store`, `check_status`, `hold_store`, `land_store`, `setup_store`, `evidence_files` |
| Slots | `slots`, `slot_state`, `slot_lock`, `slot_files`, `slot_release`, `prepare`, `slot_env` (flagged) |
| Admission and attempts | `admit`, `admit_chain`, `attempt`, `attempt_entry`, `launch`, `session`, `claim_lease`, `repeat`, `owned_processes`, `validate`, `verdict`, `verifier`, `factory_commit` |
| Step kinds | `steps`, `plan_step`, `implement_step`, `publish` |
| Agent environment (flagged) | `access`, `environment`, `agent_credentials` |
| Checks | `checks`, `check_admit`, `check_entry`, `check_release` |
| Land | `land`, `land_check`, `land_close`, `land_data`, `land_guide`, `land_push`, `land_render`, `land_status`, `land_summary` |
| Hold | `hold`, `hold_facts`, `hold_guide`, `hold_status`, `hold_text` |
| Tracker and Git adapters | `tracker`, `tracker_client`, `task`, `repo`, `git_views` |
| Package | `__init__` |

Counts: removed 6, host 1, factory 82 (total 89). A script check of this table against the directory should be part of
the task that adopts it, so a new module has to be placed.

## 5. Flagged items (all recommendations are proposed)

1. **`keep_awake.py` (proposed: host; recommend moving out of the factory).** It spawns a platform tool and knows
   `sys.platform`, `caffeinate` and `systemd-inhibit`: host machine state, the same family as the removed layer. It
   is best effort and the factory never verifies it, so correctness does not depend on it. Recommendation: delete it
   from the factory (and its `cli_composition` and `composition` wiring and the `rounds` log line) and let the person
   wrap rounds (`caffeinate -i tl step rounds ...`), the OS power setting or a launcher script do it. Fallback if the
   owner wants it kept: leave it, but as the single host adapter listed in contract 2 above.
2. **Agent uv folders, `slot_env`, `access`, `environment` (proposed: keep in the factory as one agent-environment
   adapter, shrink later).** The factory legitimately decides what an agent may write (Codex `writable_roots`, scratch
   `TMPDIR`) and runs the repo's `setup`: that is its child's sandbox. What is doubtful is `UV_CACHE_DIR`, `UV_TOOL_DIR`
   and `UV_OFFLINE=1` in `access.Folders`, the reset of the uv folders and the glossary's "uv folders": that bakes a
   package manager (L1) into L3. Recommendation: make the environment folders generic (named folders the profile
   lists, plus the scratch), let the repo's `setup` or the agent's own config decide that they hold a uv cache, and
   drop uv names from `access`, `slot_env` and `environment`. Keep the sandbox probe and the scratch rules, which are
   about the slot. Decide before touching: this changes the preflight's contract, so it is its own task.
3. **Profile `setup` and `DEFAULT_SETUP` in `profile.py` (proposed: keep `setup`; remove the default).** `setup` is the
   repo naming its own preparation command; the factory runs an argv. `DEFAULT_SETUP = (("just", "install"),)` makes the
   factory assume just and a recipe name. Recommendation: no default (an absent key means no setup); this repository
   already names `just bootstrap` in `.task-loop.json`. Update the glossary entry for `setup` in the same change.
4. **`factory_schema.refusal` text (proposed: shorten to a fact).** It tells the person to "move it aside, then
   `tl slot adopt`" and, for a newer file, that "this code must be updated". Both are operating and version-management
   advice (L0/L1). Recommendation: say only which schema version the file records and which this code knows; leave
   what to do to docs. The "newer file" wording that implies an install step should go with tl-isfa.1.
5. **`justfile` and `mise.toml` pins (proposed: stay as the repo's own L1 config; never referenced from `src/taskloop`).**
   The `pin` recipe reads `mise.toml`; `bootstrap` warms the pinned check tools. That is the project's tooling, correct
   in the package-manager layer, and not factory behavior. Risks: `.task-loop.json` couples to the recipe names
   (`bootstrap`, `check`, `test`), and CLAUDE.md names `just check`/`just test` as gates. Recommendation: keep, and
   treat the recipe names as the repo's contract with the factory, stated in the profile only. Remove the `just`/`uv`
   facts from factory docs that describe the factory itself.
6. **`.task-loop.json` (proposed: factory per-repo data, authored by the repo).** Read by `profile.py` from Git; keys
   `setup`, `checks`, `required`, `target`. The file is consumed by L3 but its contents (`just bootstrap`, `just check`)
   address L1. Recommendation: keep. No factory code may branch on those argv values.
7. **`agent_credentials` (doubtful, low priority).** Finds the machine's `codex` on PATH and its login file. It is host
   configuration the factory reads to launch its child, so factory adapter is acceptable; recommend keeping it narrow
   (existence checks only, as now).
8. **`machine_config` (doubtful, low priority).** Holds `db`, `artifacts`, `slots_root` and `slot_count`: factory
   settings, kept in factory. The pin file's location was defined beside it (`<config stem>.pin.toml`); removal belongs
   to tl-isfa.1.

## 6. Follow-ups this document implies (not started)

- tl-isfa.1 removes the six modules and their tests, the `tl install/pin/version` commands, the `start` console script
  and the install checks in `.importlinter`.
- tl-isfa.2 removes install, pin and release prose from the docs and glossary.
- Not yet filed (owner decision needed): items 1, 2, 3 and 4 above, and the proposed import-linter contracts.
