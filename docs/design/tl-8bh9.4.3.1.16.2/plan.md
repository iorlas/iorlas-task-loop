# S5e: the environment for running checks and tests in the agent sandbox (block B2)

Task: tl-8bh9.4.3.1.16.2. Design, 2026-11-11, against HEAD 8eced01f6. Docs only: nothing built or run. Read: CLAUDE.md,
glossary, [roadmap](../self-hosting-roadmap.md) (B2, B3, D1-D14), [.16](../tl-8bh9.4.3.1.16/plan.md) (2.8, 2.9, 3.3,
6, 11), [Run S](../tl-8bh9.4.3.1.16/run-s-findings.md), [profile reader](../tl-8bh9.14.1/plan.md), and `attempt`,
`attempt_entry`, `prepare`, `launch`, `slot_state`, `slot_lock`, `slot_release`, `profile`, `composition`, `steps`,
`evidence_files`, `machine_config`, `factory_schema`, the installed `stream_proc` 0.5.0 and `git_porcelain` 0.14.0.
Everything not marked **decided (owner)** is proposed. Section 11 lists the only owner questions.

## 1. What changes for the owner

An implement attempt starts in a prepared slot: before the agent, the entry runs the repository's `setup` (profile at
B, default `just install`) outside the sandbox with network, records it in factory.db, keeps its output as an evidence
file, and launches the agent with three writable folders outside the slot and an offline environment, so `just check`
and `just test` run inside the sandbox (D2). Plan attempts are unchanged byte for byte. `tl step show` prints a
`Setup:` line. Nothing else (round, CLI words, exit codes) changes.

## 2. Decisions this design respects

D1 any plain file; D2 the agent must run tests; D10 scrubbed environment and push bar; D11/D12 `setup` from the profile
at the commit under test, by the factory, before the agent, outside the sandbox, with network, default `just install`;
D14 every factory folder inside the hidden per-user folder (here: beside the slots, under the configured `slots_root`,
default `~/.local/share/task-loop/slots`), `mise` trust is the person's machine prerequisite, no workaround for shims,
no developer-tooling management. Run S findings 1-6 are taken as observed facts for Linux with codex 0.167.0.

## 3. Folders (D14) and their lifetimes

All under `<slots_root>/<repo_id>/`, beside the slots and `.locks/` (`repo_id` is 12 hex characters). The factory
creates each with mode 0700 before launch (Codex silently drops a missing root, Run S finding 2).

| Folder | Path | Agent | Lifetime | Emptied / removed |
|---|---|---|---|---|
| scratch (`TMPDIR`) | `.t/<slot>` | writable root | one attempt | emptied at every preparation (attempt 1 and repeats) before setup; removed by the slot release after its stop proof (best effort; the next preparation empties it anyway) |
| uv cache (`UV_CACHE_DIR`) | `.env/<slot>/uv-cache` | writable root | the slot's current task | emptied by a reset (below) |
| uv tools (`UV_TOOL_DIR`) | `.env/<slot>/uv-tools` | writable root | the slot's current task | emptied by a reset |

Three roots, as Run S ran them (finding 3: `uv tool run` needs a writable `UV_TOOL_DIR`). The slot's own ignored files
(`.venv/`) belong to the same lifetime as the uv folders.

**Reset (proposed, owner question Q1).** Before attempt 1's setup, when the last `setup_run` row of this slot (any
attempt) belongs to another task, or there is none (a fresh slot, or factory.db was discarded), the entry resets the
slot's environment: `clean((), ignored=True)` on the slot's pinned view (attempt 1 is clean on its branch, so only
ignored files go) and the contents of `.env/<slot>/` removed. The new row records `reset=1` only after the reset
finished, so an interrupted reset is done again. Nothing is ever deleted by age: every removal is keyed to an owning
fact (the slot's reservation for `.t`, the recorded task for `.env`). Deletion is `shutil.rmtree` only where
`rmtree.avoids_symlink_attacks` holds (checked in preflight), so a link the agent planted is removed, never followed.

**Short scratch path.** A Unix socket path holds at most 107 bytes plus NUL on Linux (103 on macOS). The factory caps
`TMPDIR` at **64 bytes** (preflight refuses `environment:path_long`), leaving 43 bytes for what a test appends:
`tempfile.mkdtemp()` adds 12 (`/tmpXXXXXXXX`), leaving 31 for a socket name. Default shape for home `/home/<u>`:
`/home/<u>/.local/share/task-loop/slots/<12 hex>/.t/s1` = 54 + len(u) bytes (60 for `iorlas`), so user names up to 10
characters fit the default; a longer one needs a shorter `slots_root`. pytest's `tmp_path` appends
`/pytest-of-<user>/pytest-<N>/<test name, at most 30>0/`, up to 53 + len(user) bytes, so a socket under `tmp_path`
fits only for short test names (the 64-byte cap leaves 43 bytes); Linux `multiprocessing` uses abstract sockets and is unaffected (Run S finding 5). The hashed evidence path is never used as scratch.

## 4. Setup: where, when, how recorded

**Where.** In the entry process, inside `Attempts._start`, after `prepare.base` (slot on `task/<id>`, clean, B read)
and before the registration warm-up and the dispatch write, under the slot custody lock the entry already holds and
inside the claim keep-alive. Only for a step kind with `environment=True` (implement); the attempt stays `admitted`
on every failure, nothing is dispatched.

**What runs.** `profile.read_profile(files, B).setup` read from Git at B (never the working tree) through
`GitProfileFiles` with the slot's view pinned to the verified G; a `missing`/refused profile is `refused
environment:profile`, unavailable Git `unavailable environment:profile`. Each argv in order, cwd the slot, stopping at
the first non-zero exit. Environment: the agent's (`codex_machine_credentials`: scrubbed, venv dropped, push bar) plus
`TMPDIR`, `UV_CACHE_DIR`, `UV_TOOL_DIR` set to the folders; no `UV_OFFLINE` (setup has network, D12). A setup that
needs credentials it does not get (a private Git dependency) fails (Q3). Through the shelf process API only:
`stream_proc.run_registered` (section 8, shelf slice S5e-0): the command's identity is committed to factory.db by the
`registered` callback before it executes, its output lines go to the setup log, its wall timeout is the attempt's
remaining deadline (the library stops and proves its own tree on timeout).

**When it runs again** (all decided by factory.db rows, never by logs):

| Case | Behavior |
|---|---|
| Plan attempt; any repeat (number 2, 3) | No setup. Repeats reuse attempt 1's environment in the same slot (the takeover keeps the slot); scratch is emptied. |
| Attempt 1 of implement, first entry | Reset if the slot's last setup was another task's; run 1. |
| Relaunch, latest run `passed` at the same B and setup digest | Reuse, no run (phase `admitted`: no agent ran since). |
| A new ref (B differs from the passed run's commit) or another digest | Run again (no reset for the same task). |
| Latest run unfinished (no conclusion) | Reconcile: other boot, no registered identity, or `observe_owned` gone and `group_alive(pgid)` false: write `interrupted`, run again. Alive: `unavailable environment:running` (never signalled). Unknown: `unavailable environment:unknown`. |
| A command exits non-zero | `failed`; `unavailable environment:exit`; the next relaunch runs once more. |
| Two runs of the attempt ended `failed`, `timed_out` or `lingering` | `refused environment:failed` without running anything; the attempt expires (`stuck:expired_admitted`); the person abandons. |
| Timeout (deadline reached) | `timed_out`; `refused expired` path as today. |
| Commands passed but the setup's process group still has a member | `lingering` (counts as failing); dispatch refused. A detached (`setsid`) descendant is not observable: residual, as .4.4. |

Two runs per attempt (`SETUP_RUNS = 2`) tolerate one transient network failure while a broken `setup` costs at most
two runs before the rounds stop running it.

**factory.db (state only).** One new table, `setup_run`; the output stays a file.

```sql
CREATE TABLE setup_run (
 attempt_id TEXT NOT NULL REFERENCES attempt(attempt_id), run INTEGER NOT NULL CHECK(run >= 1),
 dispatch_token TEXT NOT NULL, generation INTEGER NOT NULL,
 commit_sha TEXT NOT NULL CHECK(length(commit_sha) IN (40,64)),  -- B: where the profile and the slot were read
 digest TEXT NOT NULL CHECK(length(digest)=64),                   -- sha256 of the setup argv list, canonical JSON
 reset INTEGER NOT NULL CHECK(reset IN (0,1)), command INTEGER NOT NULL DEFAULT 0 CHECK(command >= 0),
 pid INTEGER, pgid INTEGER, proc_start TEXT, boot TEXT,          -- the running command's registered identity
 started_at REAL NOT NULL, ended_at REAL, rc INTEGER,
 conclusion TEXT CHECK(conclusion IN ('passed','failed','timed_out','lingering','interrupted')),
 CHECK((ended_at IS NULL) = (conclusion IS NULL)), PRIMARY KEY (attempt_id, run)
);
```

Every write is fenced by `(attempt_id, dispatch_token, generation)` against the held reservation, like the other
per-attempt rows; the one writer is `setup_store.py` (added to `test_policy.WRITERS`). "Whose environment is in this
slot" is a query (latest row joined to `attempt` on `repo_id`, `slot`), not a second fact.

**Schema: one discard.** The table goes into **v11 with S5b's attempt changes** (.16 3.3). S5b is built before the
wiring slices (section 9) and carries this DDL; S5e-1 and S5e-2 change no schema. The person discards factory.db once,
at the first runner upgrade past S5b. A v11 created by S5b's commit is the final v11.

**Evidence.** `EvidenceFiles.setup_log(key, run) -> Path`: `attempts/<hash>/setup-<run>.log` (0600, append), each
command framed by the factory's own lines `$ <shlex.join(argv)>` and `exit <rc>` / `timed out`; at most 32 MiB per run,
then one `[truncated]` line. `tl step show` reads the conclusion from factory.db and prints the path; nothing reads the
log for control.

## 5. Access and environment for the agent

`access.py` (new leaf) owns the Codex values; `SANDBOX` and `CODEX_ACCESS` move there unchanged.

```python
SANDBOX: Final = "workspace-write"                     # both kinds; attempt.sandbox and _refusal unchanged
CODEX_ACCESS: Final = (...)                            # plan: today's bytes, writable_roots=[]
def prepared_access(folders: Folders) -> tuple[str, ...]
    # CODEX_ACCESS with writable_roots=<json.dumps([tmp, cache, tools])> (a valid TOML array); network off;
    # exclude_slash_tmp and exclude_tmpdir_env_var stay true (TMPDIR, itself a root, stays writable: finding 2b)
def agent_env(folders: Folders) -> dict[str, str]
    # TMPDIR, UV_CACHE_DIR, UV_TOOL_DIR, UV_OFFLINE=1 (no name contains KEY, SECRET or TOKEN: Codex's default
    # shell_environment_policy drops those; the factory's own scrub drops them too)
```

`StepKind` gains `environment: bool` (plan False, implement True). `Attempts._launch` passes `CODEX_ACCESS` or
`prepared_access(folders(slot))` and merges `agent_env` over the credentials' env; scrubbing and the push bar stay
(Run S finding 1: everything arrives unchanged; `MISE_TRUSTED_CONFIG_PATHS` is not set, D14). The sandbox word stays
`workspace-write`, so no stored value changes.

**Plan gets no environment (decided here).** Plan writes only `docs/design/<id>/`; nothing it does needs an installed
environment. Running setup for it would execute task-branch code with network outside the sandbox with no use, add
minutes to every plan (D4 re-plans after each abandon) and change plan's access bytes that S3's constants guard.

## 6. Preflight (environment kinds, in the entry, before reset and setup)

| Check | Refusal (`refused` unless marked) |
|---|---|
| `sys.platform == "linux"` | `environment:platform` |
| `TMPDIR` at most 64 bytes | `environment:path_long` |
| Each root resolves under `<slots_root>/<repo_id>/`, and none equals, contains or is inside the slot, its G or C (from the verified pointer), the person's checkout, the evidence root or factory.db's folder | `environment:roots` |
| `shutil.rmtree.avoids_symlink_attacks` | `environment:remove_unsafe` |
| Folders created and emptied (0700) | `unavailable environment:files` |
| Sandbox usable: `codex sandbox linux` with `prepared_access`'s `-c` keys runs `/bin/sh -c` writing a file in each root and failing if `/tmp` is writable; exit 0 within 30 s, through `stream_proc.capture` (an external-tool reason: only Codex knows its backend) | `environment:sandbox` |

On Linux the backend is bubblewrap (unprivileged user namespaces), not Landlock (Run S finding 2); the probe tests
that, not a kernel setting. **macOS: nothing is observed.** Seatbelt with `writable_roots` outside the cwd, the two
`exclude_*` keys, environment pass-through, offline uv and process containment have never been run; the default
`slots_root` there also gives a `TMPDIR` of 55 + len(user) bytes against a 103-byte socket limit. Until a macOS Run S
passes, an implement attempt on macOS is refused `environment:platform` before any setup (Q2); plan runs as today.

**Security of the new roots against the pointer and pin rules.**

1. The `/tmp` exclusion existed so the agent could not build a Git directory outside the slot and have it swapped
   into the slot's `.git` pointer between a check and a Git call. That swap is now closed independently: every slot
   Git view opens pinned to the G its full check verified (tl-8bh9.14.2), `<slot>/.git` is never re-read, and the
   pointer check itself requires G directly under `<C>/worktrees` with C bound to this repository, so a G in a root
   is `redirected`.
2. The factory opens no Git view on any path under a root and reads no file there for control; its only operations
   there are create, empty and symlink-safe delete. The scratch is never a Git directory: it is created empty by the
   factory, emptied before every attempt, and preflight refuses any overlap with the slot, G, C, the person's checkout,
   the evidence root and factory.db's folder. Tests may create repositories under `TMPDIR` (real-Git tests); Codex
   mounts a `.git` that exists at start read-only (finding 2), and none exists in an emptied scratch.
3. The roots sit beside `.locks/`, not above it: the custody lock files stay unwritable. The evidence (input, answer,
   `entry.log`) stays outside every root, so the agent cannot alter what the factory reads back.
4. The new exposure is persistence, not escape: what the agent writes into the uv folders or the slot's ignored files
   is executed later outside the sandbox by setup (and by checks if they run there). Q1 bounds it.
5. The worker-gone gate before every factory Git write, and the release's stop proof before the scratch is emptied,
   are unchanged; the agent's command processes cannot outlive it (section 8, stop-proof wording).

## 7. Input words (implement)

Appended to implement's closing words (.16 2.2) by S5e-2, replacing its "both run offline" sentence; generic, no
repository command is hard-coded (the agent reads the profile file in its checkout):

> The factory ran this repository's `setup` before you started; there is no network now. Before answering, run every
> command listed under `checks` in `.task-loop.json` (while you work, a focused part such as one test file is fine)
> and fix what they report. Temporary files go to `$TMPDIR`, which is emptied after the step; do not write elsewhere
> outside the repository. Your runs are evidence for you: after this step the checks run again outside your control,
> and only those results count. In `explanation`, name each command you ran and how it ended.

"Run again outside your control" is true at M1 (the person runs them) and after B4.

## 8. Types, ports and modules

| Module | Contents | Code lines |
|---|---|---|
| `access.py` (new leaf) | `SANDBOX`, `CODEX_ACCESS` (moved), `prepared_access`, `agent_env` | about 40 |
| `environment.py` (new) | `Folders(tmp, cache, tools)`, `folders(slot_path)`; `preflight(...) -> str \| None`; `Preparation.prepare(record, slot: Prepared) -> None \| AttemptResult` (reconcile, reuse, reset, run loop, conclusion) | about 190 |
| `setup_store.py` (new) | `SetupRow`, `latest(attempt)`, `slot_owner(repo_id, slot)`, `begin`, `registered`, `conclude`, `failures(attempt)`; the `Setup:` read for status | about 90 |
| `prepare.py` | `base` returns `Prepared(head, gitdir, root)` instead of the bare head | +4 |
| `attempt.py` | optional `prepare_env` port called for `environment` kinds; `_launch` picks access and env | +12, -20 moved |
| `steps.py`, `plan_step`/`implement_step` | `environment` field | +3 |
| `evidence_files.py` | `setup_log` | +12 |
| `slot_release.py` | empty `.t/<slot>` after the park, both modes, best effort | +8 |
| `composition.py` | `RealEnvFiles`, the probe, the setup process adapter, wiring in `open_attempts` | +40 |
| status/render, `step_guide` | `Setup:` line and JSON key `setup`; GUIDE `environment` | +20 |

Ports (Protocols, each with a semantic fake in `tests/steps/doubles.py`):

```python
class SetupProcess(Protocol):   # real: stream_proc.run_registered
    def __call__(self, argv: Sequence[str], *, registered: Callable[[OwnedProcess], None], cwd: str,
                 env: Mapping[str, str], timeout: float, line: Callable[[bytes], None]) -> SetupEnded: ...
@dataclass(frozen=True)
class SetupEnded: rc: int | None; timed_out: bool; pgid: int
class EnvFiles(Protocol):       # real: RealEnvFiles (os.makedirs 0700, symlink-safe rmtree of contents)
    def fresh(self, path: Path) -> bool: ...          # made and empty
    def remove(self, path: Path) -> bool: ...
type SandboxProbe = Callable[[Folders], bool]         # real: codex sandbox via stream_proc.capture
type GroupGone = Callable[[OwnedProcess], bool]       # real: observe_owned + group_alive, as worker_gone
```

**Shelf slice S5e-0.** `stream_proc` 0.6.0 adds `run_registered`: `popen_registered`'s exec gate (the callback commits
the identity before the command executes) plus `run`'s line pumping, wall timeout and `stop_tree`. Without it a setup
killed with its entry would leave an unrecorded tree in the slot, and factory source may not wait on a `Popen` itself.
One shelf release, one pin bump.

**Stop-proof wording (S5e-2, docs and docstrings).** `composition.worker_gone` and the glossary's `agent process` row:
the agent's shell commands run in a new session under `bwrap --unshare-pid --as-pid-1 --die-with-parent`, outside
Codex's process group by design; they are contained by that PID namespace, which ends when its parent ends (Run S
finding 6, Linux only), so "the worker is gone and its group is empty" is the stop proof for them too. Setup processes
are never in the agent's group: the entry proves the setup's own group empty before dispatch. Detached descendants of
setup remain unobservable (.4.4).

## 9. Slices (caps 400 per file, 80 per function, 800 per test file)

| Order | Slice | What | Source | Tests |
|---|---|---|---|---|
| 1 | **S5e-0 shelf** | `stream_proc.run_registered`, release, pin | none here (shelf about +60) | shelf's own |
| 2 | **S5b** (.16) | as designed, plus this `setup_run` DDL in v11; implement input without section 7's words | DDL +14 | one CHECK test |
| 3 | **S5e-1 setup** | `environment.py` (folders, reconcile, reuse, reset, run loop), `setup_store.py`, `setup_log`, `prepare.Prepared`, `StepKind.environment`, wiring in `Attempts._start` and `open_attempts`: implement runs setup, agent still on plan's access | about +290 | about +330 |
| 4 | **S5e-2 access** | `access.py`, preflight and probe, `_launch` access/env, release empties scratch, `Setup:` show line, GUIDE, section 7's words, stop-proof wording | about +150 | about +220 |
| 5 | S5c (.16) | round advance; waits for S5e-2 (D2) | | |

Changes against the tracker: S5e (tl-8bh9.4.3.1.16.2) blocks S5b today; here S5b comes first so every S5e slice is
reachable through the real implement kind and tested through it, and S5c depends on S5e-2. The Run S spike part is done.

## 10. Tests and smoke

pytest functions, fakes through the ports above; no subprocess in source or tests; no test per private helper.

- `test_access.py`: `CODEX_ACCESS` and `SANDBOX` bytes equal today's (S3 guard); `prepared_access` names exactly the
  three roots in a TOML-valid array and keeps network off and both excludes; `agent_env` names, none containing
  KEY/SECRET/TOKEN; a plan attempt launches with today's argv and no added env, an implement attempt with both.
- `test_environment.py`: first setup in a fresh slot resets, records `reset=1`, runs each argv in order in the slot
  with the folders in env and no `UV_OFFLINE`; same task next step: no reset; another task: reset; reset interrupted
  (fake raises): no row, next prepare resets again; passed run at the same B and digest is reused (no process call);
  a new B runs again; non-zero exit stops at that command (`unavailable environment:exit`), the second failure then
  `refused environment:failed` with no process call; timeout `timed_out`; lingering group refuses; unfinished row:
  other boot / gone group -> `interrupted` and a new run, alive -> `environment:running` with nothing run or signalled;
  profile missing/refused/unavailable words; identity is stored before the fake "executes" (registered callback order);
  preflight table (platform, 64-byte limit with a 65-byte root, overlap with slot/G/C/evidence, rmtree flag, probe
  false); the attempt stays `admitted` and `dispatch` is never called on any refusal.
- `test_setup_store.py` (real sqlite in `tmp_path`): fencing by token and generation; the v11 CHECKs (conclusion with
  `ended_at`); `slot_owner` after a discard is None.
- `real/test_env_files_real.py`: `RealEnvFiles.remove` deletes a planted symlink, never its target; `fresh` empties.
- `test_slot_release.py`: settled and abandoned releases empty the scratch after the stop proof; a failed removal
  does not fail the release. `test_step_cli`/`test_operations`: the `Setup:` line and JSON key.
- **Live smoke (owner-run, scratch repo with a uv project and a profile, scratch tracker and remote, Linux):**
  (1) a plan attempt's codex argv shows `writable_roots=[]` and no setup row; (2) implement: preflight passes,
  `setup_run` row `passed` at the plan commit with `reset=1`, `setup-1.log` holds `just install`; (3) the transcript
  shows `just check` and `just test` run offline and passing, `TMPDIR` is `.t/s1` (at most 64 bytes); (4) after
  release `.t/s1` is empty or gone, `.env/s1` kept; (5) a second task in the same slot records `reset=1` and a new
  `.venv`; (6) a task branch whose `setup` exits 1: two runs, then `refused environment:failed`, no agent tokens;
  (7) the person kills a running entry by its recorded pid during setup: `environment:running` while the setup lives,
  then `interrupted` and a new run; (8) no process with its cwd in the slot after release. No agent runs it.

## 11. Open owner questions (each with a recommendation)

**Q1. Agent-written environment reused outside the sandbox.** The uv folders and the slot's ignored files (`.venv`)
are agent-writable; the next setup (and B4's checks, if run in that slot) executes from them outside the sandbox, with
network, and nothing of it appears in the diff. Options: (a) keep across tasks (cheapest, keeps large pre-downloaded
assets such as the Unity example, but one task's agent can plant code that runs for any later task and fake its
checks); (b) reset when the slot changes task (cross-task closed; within a task, the same class the owner accepted in
D10/D12, but invisible in the diff); (c) reset before every setup (strongest, a full download per attempt).
**Recommendation: (b)**, and B4 runs the checks only after a reset of their slot.

**Q2. macOS.** Nothing of the sandbox environment is observed there. **Recommendation: refuse implement on macOS
(`environment:platform`) until an owner-run Run S on macOS passes; plan runs as today.**

**Q3. Setup's environment.** Setup gets the agent's scrubbed environment (no `SSH_AUTH_SOCK`, no `GH_*`/tokens) and
the push bar, like the checks (D10), so a repository whose setup needs private credentials fails. **Recommendation:
keep it scrubbed; a repository needing credentials for setup is not for the factory yet.**

## 12. Risks

- **Setup cost counts against `--minutes`.** A cold slot's first setup took about 40 s plus minutes of tool downloads
  in Run S; every reset repeats it. The person raises `--minutes`.
- **A failed setup holds the attempt until its deadline** (`stuck:expired_admitted`, then abandon, which restarts at
  plan by D4). Holds with a reason are B7.
- **Socket paths.** Tests binding Unix sockets under `tmp_path` fail on every home (section 3); the 64-byte cap only
  makes a short `mkdtemp` work.
- **A task-changed `mise.toml` or `uv.lock`** is installed only by `setup` from the committed branch (D14); an agent
  changing them mid-step works offline against the old environment until the next step's setup.
- **Process containment** of the agent's commands is bwrap's, observed on one Linux machine with codex 0.167.0; another
  codex version may change it. Detached setup descendants are unobservable.
- **attempt.py is near its cap** (352 lines; audit tl-8bh9.14.21): S5e moves 20 lines out and adds about 12.

## 13. Not verified

- `codex sandbox linux` accepting `--ignore-user-config` and the same `-c` keys as `exec` (Run S used an empty
  `CODEX_HOME` instead; the slice copies Run S's argv and checks it).
- That `git clean -x` through the pinned view removes `.venv` without touching tracked files (git_porcelain's fake has
  `clean`; the real call is not run here).
- Codex keeping an existing `.git` inside a root read-only (finding 2) for uv's Git-source cache under `uv-cache`:
  read-only to the agent and read only by uv, never by the factory; not run with Git sources offline beyond Run S's pass.
- Line estimates, from the counts at this tree.
