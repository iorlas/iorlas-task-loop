# Registered attempt entry: launch an admitted attempt into a surviving process

Task: tl-8bh9.4.3.1.4 (proposed id; after [.4.3.1.2](../tl-8bh9.4.3.1.2/plan.md) and [.4.3.1.3](../tl-8bh9.4.3.1.3/plan.md)).
Design proposal, 2026-11-09, revised after independent review and owner answers. Not delivered, nothing run.
Follows the parent [lifecycle](../tl-8bh9.4.3.1/plan.md) and the [body](../tl-8bh9.4.3.1.1/plan.md). It answers .4.3.1.2
section 8 (F1, F2, F4, F8, F9, F10, F13). Read: CLAUDE.md, AGENTS.md, glossary, those plans, `src/taskloop/plan*.py`,
`slots.py`, `composition.py`, `tests/rules/*`, installed any_agent 0.4.0, stream_proc 0.5.0 and sqlite_store 0.1.0, and
shelf `process-lock-v0.2.1` (read-only, `git show`). Baseline env and Codex flags were read only from commit 731b7c76.

## 1. The cut: two slices

- **Slice A (now; no `stream_proc` import):** `PlanStore.register_entry`; the body dispatches only for its
  registered entry; credentials, files and `launch_spec` resolve before dispatch; the gate's register write is bounded;
  machine credential source; fixed Codex access constant; tests replace the test-only registration.
- **Slice B:** the launcher (`popen_registered`), its recovery read `attempt_of` (moved
  here from A: it has no caller before the launcher) and the entry process (`inspect_process`).
  Unblocked by the owner's direct stream-proc pin at any-agent's commit (O1, section 2); no shelf release was needed.

After A, the path to `execute` is complete apart from the real process start and the real self-identity read.

## 2. Owner decisions recorded

- **Q3:** admission's `Bd.claim` is the successor's task claim; tl-8bh9.3.5 later adds readiness on top of it.
- **Credentials:** an injected callable from composition, resolved before dispatch is consumed. Login v1 is file-based.
- **O1 (revised by the owner for Slice B):** a direct stream-proc pin at the same source `uv.lock` already resolved
  through any-agent: `tag=any-agent-v0.4.0`, commit 5e4a4a2, `packages/stream-proc`; no shelf change. `test_isolation.py`
  pins every shared dependency by a `{name: tag}` table and asserts stream-proc's locked commit equals any-agent's.
  (`stream-proc-v0.5.0` points to 8240407 with an identical tree; it is not used.)
- **O2:** a registration may be replaced only while the attempt is `admitted` and the old process is observed `gone` or
  `different_process`.
- **O3:** baseline style: the whole entry environment minus credential-looking variables (section 5). File login v1.
- **O4:** the lock is deferred to the worktree-preparation slice; the live smoke runs only on a scratch-repo slot.
- **O5 (author):** a fixed `LaunchInputs.access` constant is passed in this slice (section 5). No push this session.

## 3. Library facts (verified against installed source)

| Call | Fact |
|---|---|
| `stream_proc.popen_registered` (`registered.py:122-190`) | Starts the `-I -S _exec_gate.py` bootstrap and calls `registered(OwnedProcess)` in the caller's thread before the target is permitted. If the callback raises, the child is cleaned up and never execs. Once the permit send has begun, an error becomes `RegisteredStartUncertainError(identity)`. An exec failure reported afterwards clears `permission_possible` and raises plain `OSError` (`:183-185`), after the callback committed. stdin and stdout are always pipes; `stderr` may be an int fd. One deadline covers ready, identity, callback, send and exec status. |
| `any_agent.procs.spawn` (`procs.py:53-70`) | Wraps it with the fixed default `registration_timeout=5.0`. `Supervisor.run` uses it for the harness (`supervisor.py:265`). |
| `stream_proc.inspect_process` / `observe_owned` (`owned.py:60-87`) | Return `matching`, `gone` (absent or zombie), `different_process` (start or boot differs) or `unknown`. `start` is the kernel start time, read from source only (`procfs`, `procmac.py:162`). |
| sqlite_store `_open` (`store.py:124-161`) | `timeout=5.0`, `busy_timeout=5000`. `open_rw`/`shared_rw` create a missing file with the schema. `open_ro` returns `None` for a missing file. `SchemaError` is re-raised. |
| `CodexHarness.launch_spec` (`codex.py:94-117`) | Non-sealed: builds argv only and refuses an empty `exe`/`cwd`. `overlay` is never assigned in 0.4.0, so `cleanup` does nothing here. `access` is spliced in before `--json`. `spec.env` becomes the harness's whole environment (`registered.py:144`). |
| "Credentials" | any_agent has no Credentials type. The contract is the factory's own `plan.Credentials = Callable[[], tuple[str, dict[str, str]]]`, i.e. `(LaunchInputs.exe, LaunchInputs.env)`. Codex reads `$CODEX_HOME/auth.json`, default `~/.codex` (`codex.py:45`, `codex_overlay.py:21`). |

## 4. Slice A: store and body

**`register_entry(key, entry, now, replacing=None) -> "accepted" | "conflict" | "refused"`** goes in `plan_store.py`.
That module stays the only `UPDATE plan_attempt` writer, so `WRITERS` is unchanged. `entry` is `(pid, start, boot)`.
`replacing` is the narrow observation value
`Replaced(identity: tuple[int, str, str], seen: Literal["gone", "different_process"])`. It is produced only by Slice B's
launcher from `observe_owned`; A cannot verify it, so trusting it is the launcher's responsibility. One `begin`:
1. Read the row by the full key, joined with the reservation. Missing, a reservation not held for this attempt and
   generation, or `now >= deadline` -> `refused`.
2. `phase != 'admitted'` -> `conflict`.
3. If `entry_*` is NULL and `replacing is None`, or `entry_*` equals `replacing.identity` and differs from `entry`: set
   it, `rev+1`, `accepted`. Anything else -> `conflict` (a same-identity replace would only bump `rev` and make a live
   `dispatch` report `pending/dispatching` on a row that is still `admitted`). The UPDATE carries no revision predicate:
   the row was read in the same immediate transaction.

There is no `already_same`: one callback cannot commit twice, and a second launcher with the same identity is not possible.
The read cannot reuse `_load`, because `_load` raises `unregistered_entry` on exactly this row.

**`attempt_of(backlog, task_id) -> (AttemptKey, phase, entry | None) | None`** (Slice B) is the single read for recovery (F10). It
replaces the separate `unlaunched` and `entry_of` reads of the first draft. It returns the stored entry as well as
`(key, phase)`, because the launcher has to observe that entry. A coordinator that crashed after `admit` reads the key here.

**Only the registered entry dispatches (moved into the body).** `PlanAttempts.execute(key, me)`, where `me` is the
caller's `(pid, start, boot)`. On the `_start` path it returns `refused("not_entry")` unless `admission.entry == me`,
checked before credentials and dispatch. `_fence` already compares the whole `Admission`, `entry` included, so a
replacement between load and dispatch raises `changed_admission`. `_resume` (finishing a captured `validation_pending`)
and `collect` take no `me`: they never start an agent.

**Before dispatch (F1).** `_start` calls `_launch` after the input read and before `store.dispatch`, inside
`try/finally: harness.cleanup()` on every non-run exit. Inside that block it re-checks the deadline (a deadline crossed
while resolving the launch leaves `admitted`), then opens the gate store's connection on this thread (`PlanStore.warm`),
so the first gated open and its checks never run inside the harness registration window and a gate store fault surfaces
while still `admitted`. On dispatch `conflict` it returns `pending/dispatching`.
`_run(admission, harness, spec)` recomputes the deadline and calls `_call` as today. A credentials, `prepare` (idempotent
immutable writes) or `launch_spec` failure now leaves the attempt `admitted`. `_start` also returns `refused("sandbox")`
unless `admission.sandbox == "workspace-write"`, the only mode the access flags constrain.

**Bounded gate write (High1, F4 for the harness).** `PlanAttempts` takes an optional `gate: PlanStore`, used only by
`registration_gate`. Composition builds it on a separate `Store(SCHEMA)`, whose per-thread connection gets
`PRAGMA busy_timeout=1500` each time it is handed out. The main `PlanStore` keeps the library's 5 s for dispatch,
capture, session and answer. That leaves the harness gate (1.5 s plus one short write) well inside `procs.spawn`'s fixed 5 s.

## 5. Slice A: credentials and access

**`composition.codex_machine_credentials(environ=os.environ, which=shutil.which, exists=Path.is_file)`**:
- `exe`: `which("codex", path=environ["PATH"])`, resolved to an absolute path, required. `home`: `environ["CODEX_HOME"]`,
  else `~/.codex`; `home/auth.json` must exist (stat only; the contents are never opened).
- `env`: the whole `environ` minus the baseline `child_env.scrub` defaults (`_vendor/child_env/__init__.py`, re-stated in
  composition, never imported). That drops:
  prefixes `CLAUDE_ ANTHROPIC_ DELEGATE_ MCP_ OTEL_ CODEX_COMPANION`; names `CLAUDECODE AI_AGENT API_TIMEOUT_MS BAGGAGE
  DISABLE_MICROCOMPACT DISABLE_AUTOUPDATER USE_LOCAL_OAUTH USE_STAGING_OAUTH`; upper-cased prefixes `AWS_ GH_ GITHUB_` and
  `SSH_AUTH_SOCK`; any upper-cased name containing `TOKEN SECRET PASSW CREDENTIAL API_KEY APIKEY ACCESS_KEY ACCESSKEY
  PRIVATE_KEY PRIVATEKEY`.

  On top of that it drops the virtualenv (`VIRTUAL_ENV`, `VIRTUAL_ENV_PROMPT`, `PYTHONHOME`, `__PYVENV_LAUNCHER__`,
  `PYTHONEXECUTABLE`, and `$VIRTUAL_ENV/bin` from `PATH`). Baseline `child_env` had this (`without_venv`,
  `scrub(strip_venv=True)`) but never enabled it for a worker; here it is on, because the entry runs inside the
  factory's venv and the agent must not inherit it.
- **Push bar (baseline `delegate/app/env.py` `push_bar`, re-stated):** the env gets one more git env-config entry,
  `GIT_CONFIG_KEY_n=url.delegate-push-refused://.pushInsteadOf`, `GIT_CONFIG_VALUE_n=` (empty: every push URL), and
  `GIT_CONFIG_COUNT=n+1`, appended after any existing `GIT_CONFIG_*` entries. An approved out-of-sandbox `git push` then
  fails whatever SSH key or keychain login exists; fetch is untouched. A `GIT_CONFIG_COUNT` that is not a nonnegative
  integer refuses with `git_config` (baseline raised on non-integers and clamped negatives to 0). Not carried: the
  Claude-only output caps, and `DELEGATE_DEPTH=1`, which nothing in this repo reads.
- `SHELL`, `LOGNAME`, `USER`, `TMPDIR`, locale, proxy (`HTTPS_PROXY`...) and certificate (`SSL_CERT_FILE`...) variables pass
  under the whole-environment policy. `CODEX_HOME` passes.
- Any miss raises `CredentialsUnavailable(reason)` with a fixed reason word (`path codex home auth git_config`), which
  becomes `unavailable/credentials:<reason>` with the attempt still `admitted`; any other exception from the source is
  reported by its type name only, never its text.
- Unsupported in v1, stated: a keyring-stored Codex login (no `auth.json`) and API-key-only login via env (scrubbed by the
  `API_KEY` marker).
- Baseline's `UV_CACHE_DIR`/`UV_OFFLINE` additions (`decide.py:48-60`) are not carried. A plan step needs no uv.

**`plan.CODEX_ACCESS`** is `--ignore-user-config`, `--ignore-rules`, and `-c` for each of
`sandbox_workspace_write.network_access=false`, `sandbox_workspace_write.writable_roots=[]`, `approval_policy=never`,
`tool_output_token_limit=3000` (since [.4.3.1.7](../tl-8bh9.4.3.1.7/plan.md); it was baseline `decide.py:32-45`, with `on-request` and
`approvals_reviewer=auto_review`). It goes into `LaunchInputs.access`. Candid limits:
- "Network off" holds for sandboxed commands; under `never` a blocked command fails back to the model, nothing runs
  outside the sandbox (read from the codex binary's strings, unobserved live).
- With `writable_roots=[]`, a `git commit` in a linked worktree (git dir under the main checkout) fails in the sandbox;
  the factory commits the paths the agent lists ([.4.3.1.7](../tl-8bh9.4.3.1.7/plan.md)).
- These flags are accepted by the codex-cli baseline used (0.162.1 per `decide.py:26-30`). The installed codex version is unverified.

## 6. Slice B: launcher and entry

**Exact stream_proc imports:** `popen_registered`, `RegisteredStartUncertainError`, `IdentityUnavailableError`, `OwnedProcess`,
`ProcessObservation`, `inspect_process`, `observe_owned`. B also brings the direct stream-proc pin (O1) and the `test_isolation.py`
`{name: tag}` table. The injected `start` is typed by a factory `Protocol`, as is its returned child (`stdin`
and `stdout` with `close()`), so neither source nor fakes import `subprocess`.

**Launcher** (`plan_launch.py`, ~130 lines). `launch(backlog, task_id) -> Launched | AlreadyRunning | LaunchRefused |
LaunchUnavailable | LaunchUncertain`:
0. A relative `database` is refused (`database`) before any read: the entry refuses it only after the registration
   committed. `open_launcher` makes the path absolute.
1. `attempt_of`: if the phase is not `admitted`, refuse with `dispatched`. If an entry is set, observe it: `matching` ->
   `AlreadyRunning`, `unknown` -> `LaunchUnavailable("observe")`, `gone`/`different_process` -> `Replaced`.
2. `open_ro(db)` must not be `None`; a missing DB refuses. Then open a dedicated `open_rw` connection with
   `busy_timeout=plan_store.REGISTRATION_BUSY_MS` (1500, the one constant the harness gate also uses), before the spawn. A file removed between the two opens would still be created; this is accepted
   and not claimed impossible.
3. Open `PlanFiles.entry_log(key)` (`<directory(key)>/entry.log`, append, 0600, cloexec); `EvidenceError` or `OSError`
   -> `LaunchUnavailable("log")`, nothing started. Call `start([sys.executable,
   "-I", "-m", "taskloop.attempt_entry", db, artifacts, backlog, task_id], registered=cb, cwd=artifacts, env=None,
   stderr=log_fd, start_new_session=True, registration_timeout=5.0)`. `cb` calls `register_entry(..., now=clock())` and
   raises on anything but `accepted`, recording in a closure flag that it committed.
4. Close the log fd and the child's stdin and stdout pipes. Never write, wait, signal or kill.

`registration_timeout=5.0` is stated explicitly, and the callback is bounded at 1.5 s plus one write. The rest of the
window covers the bootstrap's start, which the first draft's 10 s was meant to pad. Without a measurement 10 s is not
justified, so it is dropped.

Exception mapping: `ValueError` is a programming error and propagates. `SchemaError` or `sqlite3.Error` on open ->
`LaunchUnavailable("store")`. The following happen before any commit and mean nothing was registered, so they map to
`LaunchUnavailable("start")`: `OSError` from `Popen`; `IdentityUnavailableError`; `RuntimeError`
("bootstrap failed"); `TimeoutError`; our own refusal raised from `cb` (-> `LaunchRefused`, or `StoreUnavailable` ->
`LaunchUnavailable("store")`). `OSError` after `cb` committed (the exec status reported a failure) ->
`LaunchUnavailable("exec_failed_after_commit")`: the row names a process that never ran the entry, which the next launch
replaces. `RegisteredStartUncertainError` -> `LaunchUncertain(identity)`. Not caught: an error from the library's own
child cleanup (`_abort`, e.g. a `wait` timeout before the permit) propagates untyped; catching it would need a
subprocess import. The failure table names it.

**Entry** (`attempt_entry.py`, ~100 lines). `main(argv)` wraps a testable `enter(...)`:
1. `os.dup2(2, 1)` so stdout goes to the log (F8). stdin is ignored. The entry is its own session leader.
2. Paths must be absolute, and `open_ro(db)` must not be `None`. The entry never creates a DB (F13).
3. `me = inspect_process(os.getpid())`, then the row by `attempt_of(backlog, task_id)` (the one recovery read; argv
   carries the task, not the attempt id). `me` must be `matching` and equal the stored entry; otherwise exit `identity`
   with no credentials or agent call.
4. `execute(key, me)`. The body itself refuses `not_entry`. If the result is `unavailable` with a `PendingPlanResult`
   (the body never returns one with `pending`; a `conflict` is not retried), retry `publish` only while it returns `unavailable`. Retries stop at 3 or when `clock() >= deadline`,
   whichever comes first, with an injected wait. The agent never runs again.
5. Write one line to the log: `status` and `reason` only (fixed words; a retried publication adds `publish=<s>` and,
   once accepted, the collected `then=<status>:<reason>`), never facts, env, argv or exception text. A top-level
   `BaseException` is logged by type name only (Low6). The exit code is display only: 0 exactly when `plan.succeeded`
   (collected with a disposition reason: clean run, valid answer), 1 otherwise. `collected` alone is terminal, not
   success: a failed run logs `collected run:<reason>`, an unusable answer `collected answer:<kind>`. Limit: the module's imports
   (sqlite_store, stream_proc, composition and its libraries) run before `main`, so a failing import (a broken install)
   writes Python's traceback, with its text, to the log unbounded. Deferring them would need imports inside functions,
   which lint forbids.

**Token (Low7, not overclaimed):** the dispatch token is not in the entry's argv. It is still readable by any same-user
process from factory.db, and the log directory name is derived from it. It is correlation, not authority. Authority is the
registered boot-aware identity, checked by the body against the caller's own `inspect_process`.

**Lock (O4, F2):** deferred to the worktree-preparation slice. A lock with no other taker excludes nobody, and the slot
`free` rule (.4.3.1.3, lines 137-141) gains the lock check in that same change. Until then custody is the held reservation
plus the registered entry. A person writing in the slot is not excluded, and the agent runs on the slot's detached HEAD.

## 7. Failure table (every row keeps the reservation and the claim)

| Where it fails | DB state | Leak / wedge | Next `launch` (B) |
|---|---|---|---|
| Coordinator dies before spawn | admitted, entry NULL | none | starts via `attempt_of` |
| Bootstrap, identity, `TimeoutError` before `cb`; `cb` refused or busy | unchanged | none; the library cleans the child | starts, or `conflict` |
| `cb` committed, then exec `OSError` (`exec_failed_after_commit`) or coordinator death | admitted, entry = never-run pid | none once observed | `gone`/`different_process` -> replace |
| Permit send or exec status fails after the commit (`LaunchUncertain`); the library waits 0.2 s, then SIGKILLs the leader (`leader_reaped`) | admitted, entry = that pid | the target may have exec'd and been killed mid-run; descendants not proven stopped | `gone` -> replace; `matching` -> `AlreadyRunning` |
| Library child cleanup itself fails (`_abort` re-raises its error) | unchanged before the commit, else entry = that pid | untyped exception from `launch`; leader may survive | observe decides as above |
| Relative database path, or `entry.log` cannot be opened | unchanged | none; nothing started | refused `database` / `LaunchUnavailable("log")` |
| Observation `unknown` (process table unreadable) | unchanged | attempt waits | `LaunchUnavailable`, retried later |
| Deadline passes while admitted | admitted | **unresolved** until a release slice | `register_entry` refuses `expired` |
| Entry: DB missing, identity mismatch, `not_entry`, sandbox, credentials/files/`launch_spec` | admitted | entry exits | replace after the cause is fixed; no auto-loop |
| Entry alive but hung before dispatch | admitted, entry live | **wedged**: nothing stops it in A or B | `AlreadyRunning` forever |
| Entry dies after `dispatching`, before harness registration | dispatching | **wedged** (body's accepted limit) | refused `dispatched` |
| Entry dies after harness `registered` | registered; harness may run on | **wedged**; result lost; tree not proven stopped | refused |
| Entry dies after capture (`validation_pending`) | captured | none; `execute` finishes without agent | refused |
| Coordinator dies after the permit | any | none (own session; pipes closed) | `AlreadyRunning` |
| Reboot | any | per phase | admitted -> replace (boot differs) |

A zombie entry under a living coordinator is reported `gone`, which is correct. A dropped `Popen` may warn `ResourceWarning`.

## 8. Out of scope

Git prep/verify/publish, the lock, release and generation reuse, retry/resume, stopping a hung entry, CLI, dashboard,
scheduler, other harnesses, whole-tree stop proof, uv cache env. `taskloop.attempt_entry` is a module, not a console script.

## 9. Tests (pytest functions; no spawn; caps 400/80/800)

**A:**
- `tests/plan/test_entry_store.py` (~180, in-memory SQLite): `register_entry` first wins, second `conflict`; replacement
  only with the exact stored identity and only while `admitted`; `refused` on stale reservation/generation and on
  `now >= deadline`; `conflict` after `dispatching`; a same-identity replace is `conflict`; two file-DB connections
  contend and exactly one is accepted. (`attempt_of`'s test moves to Slice B with it.)
- `tests/plan/test_attempt.py`: the 39 `execute(KEY)` calls become `execute(KEY, ENTRY)` (seed `7,'entry-start','boot'`);
  `:407` becomes "credentials failure leaves `admitted`, a second call refuses again with no dispatch"; new cases:
  `not_entry` (zero credential/run calls), sandbox refusal, `cleanup` on every pre-run exit, the gate uses `gate`, the
  gate connection opens before dispatch (its fault leaves `admitted`), an entry replaced between load and dispatch is
  refused `changed_admission` with nothing run.
- `tests/plan/test_admit.py`: `register_for_test_only` (`:125`) is deleted. Its call sites `:161` and `:395` use production
  `register_entry`, and `:161` now proves `admit -> register_entry -> execute(key, me) -> collected planned`.
- `tests/plan/test_credentials.py` (~90): scrub table (parametrized), venv strip, missing exe or `auth.json`, keyring case
  refuses, push bar appended after existing `GIT_CONFIG_*`, with injected `environ`, `which` and `exists`.
- Doc update in the same change: the .4.3.1.1 limits text (lines 263-265, "credentials failure ... leave `dispatching`")
  becomes `admitted` (Low14).

**B:**
- `test_launch.py` with a `Protocol` fake honouring the library contract: callback before permit; raise means no exec;
  exec `OSError` after commit; Uncertain; unknown observation; replace; missing DB never created.
- `test_entry.py` with `FakeRun`. Real `inspect_process(os.getpid())` reads the process table without spawning, so it is
  usable in the unit layer.

**Unreachable without a live run:** real gate and exec, survival after coordinator exit, start stability across exec on
macOS, observation truthfulness, Codex accepting the flags and the auth, timings under contention.

**Live smoke (owner-run, never agent-run, after B):** on a scratch repo with one adopted slot and a trivial task:
admit; launch; kill the coordinator after `Launched`; from a new shell confirm the attempt reaches `captured`, `collect`
returns it, a second `launch` reports `AlreadyRunning`/`dispatched`, and exactly one Codex session exists.

The agent's own commit fails under `never`; the factory commits the listed paths ([.4.3.1.7](../tl-8bh9.4.3.1.7/plan.md)). The smoke proves the launch path, not plan quality.

## 10. Files and acceptance

A: `plan_store.py` 269 -> ~315, `plan.py` 241 -> ~265, `composition.py` 95 -> ~155, `plan_types.py` +~6 (`Replaced`), tests.
B: `plan_launch.py` ~130, `attempt_entry.py` ~100, `plan_files.py` +4, dependency and rule changes. Estimates, under caps.

1. `register_entry` is the only writer of `entry_*`. It is a single winner, and replacement follows O2 only. `WRITERS` is unchanged.
2. `execute` dispatches only for `me == admission.entry`. Credentials, files and `launch_spec` resolve before dispatch;
   their failure leaves `admitted`; cleanup runs on every pre-run exit.
3. Only the gate's register write is bounded at 1.5 s. The other writes keep 5 s.
4. Credentials follow the stated scrub rule; `auth.json` is checked by existence only. `CODEX_ACCESS` reaches `LaunchInputs.access`.
5. No `stream_proc` or `subprocess` import in A. No wait, signal or kill anywhere. `just check` and `just test` pass (not run).

## 11. Owner questions

None open. O1 is resolved by the owner's direct stream-proc pin at `any-agent-v0.4.0` (5e4a4a2); no shelf release.

## 12. Review findings not applied as stated

`attempt_of` (Slice B) also returns the stored entry, because the launcher must observe it. "Retries only on unavailable" applies
to `publish`; the agent is never retried. The F4 window keeps the library's 5 s rather than a padded 10 s (Low11).

## 13. Not verified

Nothing was run. Library behavior comes from installed source only. Not observed: start stability across `exec` on macOS,
the installed codex version's acceptance of the baseline flags, and real SQLite busy timing. The review's original text was
not available; findings are taken from the coordinator's summary. Line counts are estimates.
