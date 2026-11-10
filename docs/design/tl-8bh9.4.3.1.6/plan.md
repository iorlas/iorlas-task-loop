# Plan CLI: run the implemented plan path without a driver

Task: tl-8bh9.4.3.1.6 (proposed id; after [.4.3.1.5](../tl-8bh9.4.3.1.5/plan.md)). Design, 2026-11-10, revised after the
owner's answers. Nothing has been run, implemented or reviewed. Read: CLAUDE.md, AGENTS.md, glossary,
[foundation](../tl-8bh9.8.7/plan.md), [operations](../tl-8bh9.8/operations.md), [one-shot plan](../tl-8bh9.3.2.1/plan.md),
[.4.3.1](../tl-8bh9.4.3.1/plan.md) and .1-.5, [live smoke](../tl-8bh9.4.3.1.4/live-smoke.md),
[identity contract](../tl-8bh9.1/identity-store-contract.md), [configuration review](../tl-8bh9.1/configuration-review.md),
[lifecycle](../tl-8bh9.2/lifecycle.md), [interaction contract](../tl-8bh9.7/interaction-contract.md); `src/taskloop/*.py`,
`tests/{cli,rules,plan}`, `justfile`, `.importlinter`; installed `sqlite_store/store.py`, `stream_proc/owned.py`.
`tl` here is the successor executable (`.venv/bin/tl`, `taskloop.cli:main`), not the global baseline shim or its
`tl task` bd wrapper.

## 0. Roadmap

| | What |
|---|---|
| Done | Attempt body (execute/publish/collect), managed slots (adopt/observe), admission (slot, claim, reservation), launcher and surviving entry process, answer-schema fix, Git verification of the plan commit (tested on the Git fake only) |
| This slice | The CLI: machine config, `tl config show`, `tl slot adopt`, `tl plan start/show/list/verify`, read-only diagnosis of stuck work |
| Next | Preparation and lock (`task/<id>` branch in the slot), publication (push), release and cleanup (including real force-unlock), scheduling and pause, dashboard |
| Later / pending | Machine-wide doctor, `tl slot list`. Pending: the owner's macOS live smoke (section 11) |

## 1. Words, plainly

- **Slot**: a separate checkout of the repo (a Git worktree) that the factory may use, so two tasks never edit the same files.
- **Adopt**: tell the factory that a worktree you made is one of its slots (`s1`, `s2`, ...).
- **Reserve**: mark a slot as taken by one attempt, in factory.db. Nothing un-reserves yet.
- **Claim**: mark the task as taken in the tracker (bd assignee `taskloop`), so nobody else starts it.
- **Admit**: the one check-and-record step: the task reads fine, a slot is free, the claim succeeds, then the attempt and
  its reservation are written together. Nothing runs yet.
- **Launch**: start the attempt's own background process (the entry), which keeps running after your shell closes and runs
  the agent once.

## 2. Command surface

```
tl config show [--json] [overrides]
tl slot adopt CHECKOUT [--root DIR] [--count N] [--db PATH] [--json]                  # setup/admin
tl plan start TASK --backlog B --tracker-root DIR --checkout DIR --model M --effort E --minutes N [--db PATH] [--artifacts DIR] [--json]
tl plan show TASK --backlog B [--db PATH] [--artifacts DIR] [--json]
tl plan list [--stuck] [--db PATH] [--json]
tl plan verify TASK --backlog B [--db PATH] [--json]
tl plan abandon TASK ... / tl slot release ...    # placeholders: refuse `deferred`, print the manual steps (section 8)
```

Every command takes a global `--config FILE` (Q1). The root help and `tl plan -h` say: **"attempt only: no task branch,
publication or release"**. This registers plan commands before the plan step is complete; the owner decided it as an
exception to the [foundation](../tl-8bh9.8.7/plan.md) ("do not register plan... commands") and [3.2.1](../tl-8bh9.3.2.1/plan.md)
("do not register a plan CLI command") **for this surface only**. `tl plan` alone still exits 2.

## 3. Machine config: one reader, one default per fact

**File**: `~/.config/task-loop/config.toml` (from `Path.home()`), or `--config FILE`. The machine config owns locations
and capacity ([lifecycle](../tl-8bh9.2/lifecycle.md) "Local machine configuration"; configuration review: machine
capacity/accounts outside a task branch). This also settles the deferred capacity home (Q2 of .4.3.1.3): machine config.

| Key | Type | Built-in default | Who reads it |
|---|---|---|---|
| `db` | absolute path (`~` expanded) | `~/.local/state/task-loop/factory.db` | slot adopt, plan * |
| `artifacts` | absolute path | `~/.local/state/task-loop/artifacts` | plan start, plan show |
| `slots_root` | absolute path | `~/.local/share/task-loop/slots` | slot adopt only |
| `slot_count` | int >= 1 | `1` | slot adopt only |

Why these defaults: factory.db and evidence are disposable local state (XDG "state"); slots hold work that must be kept
(XDG "data"). **Not `~/.config/task-loop/`**: on this machine that folder is the baseline factory's live home
(`factory.db`, `delegate/`, `githooks`, checked 2026-11-10); a shared path would put two factories on one database
(the successor refuses another schema version loudly, but the folder and its files are the baseline's).

**Precedence**: flag > file > default, per key. No environment variable is read (pushback on `$XDG_CONFIG_HOME`: it
would be a hidden source that moves every fact; `Path.home()` still reads `HOME`, which is unavoidable). Model, effort,
minutes, backlog, tracker root and checkout are **not** config keys (decided Q8 of .4.3.1.2: explicit per call).
Sandbox is not a flag or key: the operation passes `plan.SANDBOX`, the only value execute accepts.

**Reader**: `src/taskloop/machine_config.py` (~70 SLOC), the only module that knows keys and defaults. `DEFAULTS`
(one table), `Setting(value, source: Literal["flag","file","default"])`, `resolve(text: str | None, flags, home) ->
Effective | ConfigRefused`. Composition reads the file (missing file = all defaults; unreadable = refused). Refusals
(fixed words, exit 1, every command): `toml` (malformed), `unknown_key`, `type`, `relative_path`, `count`. The entry
never reads config: it receives absolute db and artifacts paths in argv, as today.

`tl config show` prints, per key, the effective value and its source, plus the file path and whether it exists.
JSON: `{"file": {"path", "exists"}, "settings": {"db": {"value", "source"}, ...}}`.

**Identity settings.** The identity contract does not define a machine config location; it defines bindings: RepoId
comes from Git (never configured), a task is scoped by its backlog, and "resolved local bindings" live in factory.db
behind a store owner, one enabled execution binding per backlog. That binding store does not exist. So `--backlog`,
`--tracker-root` and `--checkout` stay flags in this slice, and the tracker actor stays the constant `taskloop`
(`composition.ACTOR`). A later binding slice (`tl repo register`-like) replaces the three flags with a factory.db row,
not a config key (Q2).

**Only `slot adopt` creates factory.db.** The other commands open it read-only first (`Store.open_ro`): absent ->
refused `database`; other version -> refused `schema` (`open_ro` raises `SchemaError`, `sqlite_store/store.py:71-77,154`).
Today `open_plan_admission` and `open_plan_verifier` use `shared_rw`, which would create an empty DB at a wrong path.

## 4. `tl plan start`: one command, the existing operations underneath

`plan_ops.start(reader, admission, launcher, request)`:
1. `PlanStore.attempt_of(backlog, task)` (read-only). An attempt exists -> skip to 3; the given model/effort/minutes are
   not applied and the output says "existing attempt; its admitted choices stand". Re-running therefore needs no tracker.
2. `PlanAdmission.admit`: task read, checkout, lowest free slot, claim, then reservation and attempt in one transaction
   (unchanged). `task_attempted` (a concurrent start won) -> go to 3. Any other refusal or unknown -> stop, no launch.
3. `Launcher.launch(backlog, task)` (unchanged): starts the entry, reports it running, refuses after dispatch, or
   replaces an entry it observed gone.

| `status` word | Meaning | Exit |
|---|---|---|
| `started` | admitted now and launched | 0 |
| `relaunched` | existing admitted attempt, dead entry replaced | 0 |
| `already_running` | its entry still runs | 0 |
| `already_dispatched` | the run started earlier (`show` tells how it ended) | 0 |
| `refused:<reason>` | an `AdmitRefused` reason, or a launch refusal (`database`, `registration_refused`, ...) | 1 |
| `unavailable:<what>` / `uncertain` | tracker/git/store, a launch failure, or `LaunchUncertain`; re-run `start` | 3 |

`claim_leaked` prints first, on stderr: "the tracker claim on TASK may still be held by taskloop; check `bd show TASK`".
`no_free_slot` lists each slot's state. Real trackers are allowed; help and the `started` output say the claim and the
slot stay held and nothing releases them yet (`Bd.claim` vs tl-8bh9.3.5 remains open).

## 5. Show, list, verify

`plan_ops.status` -> `PlanStatus`: `attempt_id`, `slot`, `phase`, `entry` (`none`|`running`|`gone`|`different_process`|
`unknown`, via `observe_owned`, a native process-table read, no spawn or signal), `result` (`collect`'s status and
reason, the entry.log words), `succeeded` (`plan.succeeded`), `deadline_passed`, the attempt directory and entry.log
path (computed; `PlanFiles.entry_log` would mkdir, so `show` uses `directory(key)` only), and `next`:

| State | `next` |
|---|---|
| `admitted`, entry none/gone/different, deadline ahead | `start` (relaunch) |
| any phase, entry running, deadline ahead | `wait` |
| entry running past the deadline | `stuck:hung` |
| entry `unknown` | `unknown` |
| collected | `done` (read `succeeded`) |
| captured, `pending verification`, entry not running | `verify` |
| `admitted` past its deadline; `dispatching`/`registered` with entry gone; `pending session_*`/`validation_pending` with entry gone; `conflict` | `stuck:<kind>` (section 8) |

`tl plan list [--stuck]`: one row per attempt (task, slot, phase, entry, result, `next`); `--stuck` keeps
`stuck:*`/`unknown`. It needs one new read, `PlanStore.attempts()` (SELECT only; `WRITERS` unchanged). This is the
"doctor-style" listing; a machine-wide `tl doctor` (install, DB, prerequisites) is later.
`tl plan verify`: `attempt_of` -> `PlanVerifier.verify(key)`, the first production caller of `open_plan_verifier`.
Exit 0 `verified`/`reused`; 1 `rejected:<rule>`, `not_applicable`, refused; 3 `unsettled:<r>`, `unavailable:<r>`.
A stored verdict returns with no Git read; running it while the entry verifies is safe (same inputs, insert-once).

## 6. Output, exit codes, `--json`

Results are typed; `plan_ops.as_data(result)` gives the one JSON shape (a dashboard reuses it); `cli_plan.py` renders
human text. Control fields are fixed words from the existing `Literal` types; `detail`/`message` are diagnostic only.
`dispatch_token` is never printed. Convention kept from `repo inspect`/`task show`: data on stdout; refusal/unknown as
`{"error": {"kind", "reason", "message", ...}}` on stderr. Exit: 0 done or already so; 1 refused; 2 usage; 3 unknown,
re-run is safe (`repo`/`task` keep 1). No version field, no compatibility promise: one exact-keys test per command pins
the shape, and a test renders every value of each `Literal`.

## 7. Where the code goes (no logic in `cli*.py`)

- `machine_config.py` (new, ~70): keys, defaults, precedence, refusals. Pure: text in, values out.
- `plan_ops.py` (new, ~170): `start`, `status`, `attempts_status`, `verify_task`, `require_database`, `deadline_after(minutes,
  clock)`, `as_data`. Ports in, values out.
- `plan.py`: `PlanAttempts.collect`'s body becomes module `collect(store, key)` (method delegates; 342 SLOC, net zero).
- `plan_store.py` (318 SLOC): one `attempts(backlog=None, task=None)` read (key, slot, phase, entry, deadline) serving
  `show` and `list` (~+15); `attempt_of` and its launcher/entry callers stay unchanged.
- `slots.py`: `NotAdopted.path: Path | None`, so a refused adopt shows where to run `git worktree add --detach`.
- `composition.py` (153 -> ~200): config file read, read-only opener, the database guard, `open_plan_start`.
- `cli.py` (92; `main` 45/80) keeps root parser, `repo`, `task`; `cli_plan.py` (new, ~220) registers config/slot/plan
  parsers and renders. If it nears 400, `cli_slot.py` splits off.
- `.importlinter`: layers `__main__ > cli > cli_plan`; new forbidden contract: `cli`, `cli_plan`, `plan_ops`,
  `machine_config` may not import `attempt_entry`. No-`subprocess` and no-network rules stand; processes start only via
  the launcher's injected `popen_registered`. No hook or dashboard code exists in the successor, so no hook/dash rule applies.

Re-run: `slot adopt` is idempotent (another root is `other_root`, never moved); `start` per section 4; `verify` until
settled. Nothing here releases a reservation or claim, retries an agent, or makes a second attempt for a task.

## 8. Stuck work: what is possible now, what is deferred

**Now (safe, read-only):** `tl plan show`/`list --stuck` name the kind and print fixed manual steps:

| `stuck:<kind>` | What a person does by hand now |
|---|---|
| `expired_admitted` | Nothing in the factory can release it. Leave it, or discard the whole factory.db (below). |
| `entry_lost` (`dispatching`/`registered`, entry gone) | The agent may still run: check `worker_pid` as live-smoke section 8 (cwd = slot), kill only that verified group; then as above. |
| `hung` (entry running past its deadline) | Kill the entry by verified PID (live-smoke section 8); then `show` again. |
| `unpublished` (captured, session/validation pending, entry gone) | Result incomplete; keep evidence; as above. |
| `conflict` | Owner inspects evidence; as above. |
| verify `unsettled:<r>` | Inspect the slot; if HEAD is the reported commit and only stray files make it dirty, remove them, then `tl plan verify`. |

**Whole-DB discard** is the only release that exists (AGENTS.md: deliberate discard permits reevaluation): stop all
entries and workers first (verified PIDs), delete factory.db and its `-wal`/`-shm`, then by hand `bd update TASK
--assignee ""` (or `bd unclaim`) for each claimed task, inspect each slot worktree, and adopt again. It drops every
slot and attempt. Never edit rows by hand: a deleted reservation silently fences out a still-running worker.

**Deferred: force-release (its own slice, after preparation and lock).** `tl plan abandon` / `tl slot release` are
registered now as placeholders that refuse `deferred` (exit 1) and print the steps above. The real verbs need:
1. **Stop proof**: entry and worker identities observed `gone`/`different_process` (never `unknown`), plus whole-workload
   stop proof (.4.4) or an explicit, recorded owner acknowledgment that descendants were checked (owner choice then).
2. **Custody**: the slot's process lock free and taken by the releaser (preparation slice), never a free lock alone.
3. **Schema (v4)**: `plan_attempt.phase` has no `abandoned` value and `UNIQUE(adapter, backlog, task_id)` forbids a second
   attempt; release needs an end phase and an attempt number in that key (or an owner rule that an abandoned task never
   retries). `reservation` (PK `(repo_id, slot)`, `attempt_id UNIQUE`) gets a DELETE writer with a `WRITERS` row; its
   absence is what fences stale writers (`_load` refuses `stale_reservation`); `GENERATION` becomes monotonic.
4. **Order**: durable abandon intent and reservation delete in one transaction first, then `Bd.unclaim(if_assignee=
   "taskloop")` outside it; a failed unclaim is reported and retried, never forced.
5. **Slot state**: dirty, branched or unknown slots stay held (quarantined) for the owner; release never resets work.

## 9. Failure table

| Situation | Stored | Result | Next |
|---|---|---|---|
| Config malformed / unknown key | nothing | refused `toml`/`unknown_key`, 1 | fix the file (`tl config show`) |
| DB absent or other schema | nothing, no file made | refused `database`/`schema`, 1 | `tl slot adopt` creates it |
| Tracker down (first start) | nothing (claim compensated when proven) | `unavailable:tracker`, 3 | re-run start |
| No free slot | nothing | `refused:no_free_slot` + slot states, 1 | adopt more or wait |
| Launch failed after admission | admitted row | 3 | re-run start (relaunches) |
| Codex missing in the shell | admitted (entry exits before dispatch) | start 0; `show next=start`; entry.log `unavailable credentials:<w>` | fix PATH, re-run start |
| Deadline passed while admitted | admitted | `refused:registration_refused`, 1; `stuck:expired_admitted` | section 8 |
| Entry dead after dispatch | unchanged | `already_dispatched`; `stuck:entry_lost` | section 8 |
| Verification left pending | captured | `next=verify`; verify 3 until settled | re-run verify |
| Ctrl-C in start | during the commit: claim compensated; during the bd call: unknown | Python default | `bd show TASK`, re-run |

## 10. Tests (pytest functions; no spawn; existing fakes)

- `tests/cli/test_config.py` (~120): precedence per key, every refusal word, `~` expansion, no env read (monkeypatched
  `XDG_CONFIG_HOME` ignored), `config show` sources. Pure text in, no file needed.
- `tests/plan/test_ops.py` (~280): `start` over the conftest file DB with a recording admission/launcher (first start,
  existing admitted with dead entry, already running, dispatched, `task_attempted` race, refusal stops before launch,
  re-run does not touch the tracker); `status`/`list` with a fake `observe` for each `ProcessObservation` kind -> the `next`
  table; `show` creates nothing; `verify_task` with `drop_checkout` after a stored verdict (no Git read).
- `tests/cli/test_plan_cli.py` (~300): flags -> requests via monkeypatched composition openers (as `test_task_cli.py`
  patches `composition.Bd`); one parametrized table of result -> exit, human lines, exact JSON keys; `claim_leaked`
  banner; placeholders refuse `deferred`. `test_cli.py`: help wording; `plan`/`implement`/`land` still exit 2.
- `test_slots.py`: `NotAdopted.path`. Gates: `just check`, `just test` by the implementer; no live run by an agent.

## 11. Live smoke: runbook changes

Driver (`driver.py`, `D()`) removed; env.sh writes a scratch `config.toml` (db, artifacts, slots_root under `$SMOKE`,
`slot_count = 1`) and `T() { "$TL/.venv/bin/tl" --config "$SMOKE/config.toml" "$@"; }`; `T config show` is checked first.
- Section 3: `T slot adopt "$REPO"` prints `s1 not_listed <path>`; `git worktree add --detach <path>`; adopt again.
- Section 4 (launcher busy probe, needs an admitted attempt with no live entry): first
  `env PATH=/usr/bin:/bin T plan start ...` (no `codex`: the entry exits `unavailable credentials:codex`, attempt stays
  admitted), then `(echo 'BEGIN IMMEDIATE;'; sleep 4; echo 'ROLLBACK;') | sqlite3 "$DB"` in tab B and
  `time T plan start ...` in tab A: expect exit 3 `unavailable:store` in ~1.5 s, then `T plan show` `next=start`.
- Section 5: `T plan start ... --json | tee launch.txt` (expect `relaunched`); `D status` -> `T plan show`; second start
  -> `already_running` or `already_dispatched`; on `next=verify` run `T plan verify`. Section 6's "nothing re-runs a pending
  verification" row now names `tl plan verify`; add a `T plan list --stuck` check.
- Section 7 pastes command `--json` outputs. Raw `sqlite3 -readonly`, `ps`, `lsof`, push probe, reset and do-nots stay.

## 12. Acceptance

1. Section 2's commands exist, each one operation; `cli*.py` has no Git, SQL, clock or process logic.
2. One config reader; flag > file > default; no environment source; unknown keys refused.
3. Only `slot adopt` creates factory.db; `show`/`list` write nothing; `start` re-run never touches the tracker.
4. Exit codes and JSON per section 6; `dispatch_token` never printed; `verify` has its production caller.
5. No new SQL writer, schema version, dependency or subprocess; import-linter forbids cli -> attempt_entry.
6. The runbook runs with commands only; `just check` and `just test` pass.

## 13. Owner questions (few; each with a recommendation)

- **Q1 Config location and override.** Rec: `~/.config/task-loop/config.toml` without reading `$XDG_CONFIG_HOME`, and a
  global `--config FILE` flag (the smoke uses a scratch file). Context: you asked for no environment source; XDG is one.
- **Q2 Backlog, tracker root and checkout stay flags** until a repo-binding slice stores them in factory.db, as the
  identity contract says. Rec: yes. Context: putting them in machine config would make a second owner of the binding.
- **Q3 State defaults** `~/.local/state/task-loop/{factory.db,artifacts}` and `~/.local/share/task-loop/slots`. Rec: yes.
  Context: `~/.config/task-loop` is where the old factory keeps its live database on this machine.

Decided (owner, 2026-11-10): CLI first; register plan commands with the warning; one `plan start`; machine config with
one reader; sandbox fixed; `--minutes` required; exit 3; real tracker allowed with the warning; `tl slot list` later;
force-release deferred with section 8's conditions.

## 14. Not verified

Nothing was run. Read from source: the operations and their results, `shared_rw` creating a DB, `open_ro` returning
None or raising `SchemaError`, `observe_owned` reading the process table natively, no import contract forbidding
cli -> attempt_entry. Observed: `~/.config/task-loop/` holds the baseline's `factory.db`. Not verified: the sqlite3 CLI
holding `BEGIN IMMEDIATE` across a piped `sleep` on macOS; that `PATH=/usr/bin:/bin` makes `which("codex")` miss on the
owner's Mac; Ctrl-C inside the bd claim; `bd unclaim` behaviour against a real tracker; whether the smoke has run.
All line counts are estimates.
