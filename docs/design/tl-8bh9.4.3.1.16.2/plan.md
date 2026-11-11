# S5e: the environment for running checks and tests in the agent sandbox (block B2)

Task: tl-8bh9.4.3.1.16.2. Design, 2026-11-11, against HEAD 8eced01f6; revised the same day after an independent review
(section 14). Docs only: nothing built or run. Read: CLAUDE.md, glossary, [roadmap](../self-hosting-roadmap.md) (B2,
B3, D1-D14), [.16](../tl-8bh9.4.3.1.16/plan.md) (2.8, 2.9, 3.3, 6, 11), [Run S](../tl-8bh9.4.3.1.16/run-s-findings.md),
[profile reader](../tl-8bh9.14.1/plan.md), and `attempt`, `attempt_entry`, `prepare`, `launch`, `slot_state`,
`slot_lock`, `slot_release`, `profile`, `composition`, `steps`, `evidence_files`, `machine_config`, `factory_schema`,
`justfile`, `.task-loop.json`, the installed `stream_proc` 0.5.0 and `git_porcelain` 0.14.0. Everything not marked
**decided (owner)** is proposed. Section 12 lists the only owner questions.

## 1. What changes for the owner

An implement attempt starts in a prepared slot: before the agent, the entry resets the slot's environment, runs the
repository's `setup` (profile at B; for this repository a new `just bootstrap`) outside the sandbox with network,
records it in factory.db, keeps its output as an evidence file, and launches the agent with three writable folders
outside the slot and an offline environment, so `just check` and `just test` run inside the sandbox (D2). Plan
attempts are unchanged byte for byte. `tl step show` prints a `Setup:` line; a slot release also waits for a setup
process. Nothing else (round, CLI words, exit codes) changes.

## 2. Decisions this design respects

D1 any plain file; D2 the agent must run tests; D10 scrubbed environment and push bar; D11/D12 `setup` from the profile
at the commit under test, by the factory, before the agent, outside the sandbox, with network, default `just install`;
D14 every factory folder inside the hidden per-user folder, `mise` trust is the person's machine prerequisite, no
workaround for shims, no developer-tooling management. D14 names "the platform equivalent elsewhere", but
`machine_config` as built defaults `slots_root` to `~/.local/share/task-loop/slots` on every platform; this design and
its byte budget assume the code as built. Run S findings 1-6 are observed facts for Linux with codex 0.167.0 only.

## 3. Folders (D14) and their lifetimes

All under `<slots_root>/<repo_id>/`, beside the slots and `.locks/` (`repo_id` is 12 hex characters). The factory
creates each with mode 0700 before launch (Codex silently drops a missing root, Run S finding 2).

| Folder | Path | Agent | Lifetime | Emptied |
|---|---|---|---|---|
| scratch (`TMPDIR`) | `.t/<slot>` | writable root | one preparation to the next | before setup, after setup, and by the slot release after its stop proof (best effort) |
| uv cache (`UV_CACHE_DIR`) | `.env/<slot>/uv-cache` | writable root | one setup to the next | by every reset |
| uv tools (`UV_TOOL_DIR`) | `.env/<slot>/uv-tools` | writable root | one setup to the next | by every reset |

**Reset before every setup.** Every setup run starts with a reset: the slot's ignored files removed (`-ffdx`, so
nested repositories go too; section 8) and an ignored-files listing of the slot then empty, else `refused
environment:reset`; and the contents of `.env/<slot>/` removed. The only setup that is skipped is a relaunch of the
same attempt whose latest run `passed` at the same B and setup digest while the attempt is still `admitted` (no agent
has run since). Keyed on the attempt, not on "whose environment is in the slot": any agent (a plan agent, an
abandoned task's agent, a repeat) may have written the slot's ignored files or the uv folders, and nothing of it may
reach a run outside the sandbox. The cost is that downloads are not kept across setups (owner question Q1). B4's
checks must likewise run only after a reset of their slot.

Removals never follow links and never go by age: each is keyed to an owning fact (the slot's reservation for `.t`,
the running setup for `.env`). Removal is `shutil.rmtree` only where `rmtree.avoids_symlink_attacks` holds, with an
`onexc` handler that, for a `PermissionError` on an entry `lstat` shows to be a directory and not a symlink, adds owner
`rwx` and retries once (an agent can create a 0o000 directory in its roots); anything else stays and the removal
reports failure.

**Short scratch path.** A Unix socket path holds at most 107 bytes plus NUL on Linux (103 on macOS). `TMPDIR` is capped
at **64 bytes** (preflight refuses `environment:path_long`), leaving 43 bytes for what a test appends:
`tempfile.mkdtemp()` adds 12 (`/tmpXXXXXXXX`), leaving 31 for a socket name. Default shape for home `/home/<u>` and
slot name `<s>`: `/home/<u>/.local/share/task-loop/slots/<12 hex>/.t/<s>` = 52 + len(u) + len(s) bytes (60 for
`iorlas`, `s1`): user names up to 10 characters fit slots `s1`-`s9`, up to 9 characters from `s10`. Longer needs a
shorter `slots_root`. pytest's `tmp_path` appends `/pytest-of-<user>/pytest-<N>/<test name, at most 30>0/`, up to 53 +
len(user) bytes, so a socket under `tmp_path` fits only for short test names; Linux `multiprocessing` uses abstract
sockets and is unaffected (Run S finding 5). The hashed evidence path is never scratch.

## 4. Setup: where, when, how recorded

**Where.** In the entry process, inside `Attempts._start`, after `prepare.base` (slot on `task/<id>`, clean, B read)
and before the registration warm-up and the dispatch write, under the slot custody lock the entry already holds and
inside the claim keep-alive. Only for a step kind with `environment=True` (implement). On every refusal the attempt
stays `admitted`; nothing is dispatched.

**Order, attempt 1 of implement** (a repeat runs steps 1-4 and 9-11 only):

1. Failure count: two runs of this attempt concluded `failed`, `timed_out`, `lingering` or `dirty`: `refused
   environment:failed`, nothing run (before the probe, so a dead attempt costs nothing).
2. Reconcile the latest run of this attempt while it is unfinished or concluded `lingering` or `timed_out` (a process
   may be left in its last command's group): other boot, no registered identity, or `observe_owned` gone and
   `group_alive(pgid)` false: an unfinished run is written `interrupted` (a concluded one keeps its conclusion). Alive:
   `unavailable environment:running`, never signalled. Unknown: `unavailable environment:unknown`. (Review repair, 2026-11-11.)
3. Preflight (section 6): checks and folder creation only, no emptying.
4. Empty the scratch.
5. Reuse: latest run `passed` at this B and digest: skip to 9.
6. Reset (section 3).
7. Run each argv of `profile.read_profile(files, B).setup` in order, cwd the slot; after each command check its
   process group empty (else `lingering`; since tl-8bh9.14.6 S6b also when the deadline's stop left survivors,
   checked before `timed_out`); stop at the first non-zero exit (`failed`) or the deadline (`timed_out`).
8. Re-read the slot through the pinned view: HEAD not B or not on `task/<id>` is `dirty` with the word
   `environment:moved` (review repair); tracked or untracked changes are `dirty` (a failed run; the slot stays dirty, so later relaunches refuse `slot_dirty` from `prepare` and `tl step show` names setup as the
   cause; the person removes the files as the `slot_dirty` guide says).
9. Empty the scratch again (setup's temp files never reach the agent).
10. Renew the claim once (the entry's keep-alive, passed in as a port): `lost` refuses `claim_lost`.
11. Deadline check, then the dispatch write as today.

**What runs.** The profile is read from Git at B (never the working tree) through `GitProfileFiles` with the slot's
view pinned to the verified G; a missing or refused profile is `refused environment:profile`, unavailable Git
`unavailable environment:profile`. Environment: the agent's (`codex_machine_credentials`: scrubbed, venv dropped, push
bar) plus `TMPDIR`, `UV_CACHE_DIR`, `UV_TOOL_DIR`; no `UV_OFFLINE` (setup has network, D12). The scrub removes
credential variables only: `HOME` stays, so files under it (SSH keys, `~/.netrc`, Git credential helpers) are reachable,
and the push bar is an environment entry a task-written setup can unset (Q3). Through the shelf process API only:
`stream_proc.run_registered` (section 8); the command's identity is committed to factory.db by its `registered`
callback before it executes; its wall timeout is the attempt's remaining deadline (the library stops and proves its own
tree on timeout).

| Run result | Conclusion | Entry word |
|---|---|---|
| All commands exit 0, groups empty, slot clean | `passed` | (dispatch continues) |
| A command exits non-zero, or fails to exec after registration | `failed` | `unavailable environment:exit` (the next relaunch runs once more) |
| Deadline reached | `timed_out` | `refused expired` |
| A command's group still has a member after it ended, or its stop (the deadline) left survivors (tl-8bh9.14.6 S6b) | `lingering` | `unavailable environment:lingering` |
| The slot is not clean after setup | `dirty` | `refused environment:dirty` |
| Start uncertain (identity committed, exec unknown) | none yet | `unavailable environment:uncertain`; step 2 reconciles it |

`SETUP_RUNS = 2` failing runs per attempt: one transient network failure is tolerated; a broken `setup` costs at most
two runs before relaunches stop running it. A detached (`setsid`) setup descendant is not observable: residual, as .4.4.

**factory.db (state only).** One new table; the output stays a file.

```sql
CREATE TABLE setup_run (
 attempt_id TEXT NOT NULL REFERENCES attempt(attempt_id), run INTEGER NOT NULL CHECK(run >= 1),
 dispatch_token TEXT NOT NULL, generation INTEGER NOT NULL,
 commit_sha TEXT NOT NULL CHECK(length(commit_sha) IN (40,64)),  -- B: where the profile and the slot were read
 digest TEXT NOT NULL CHECK(length(digest)=64),                   -- sha256 of the setup argv list, canonical JSON
 command INTEGER NOT NULL DEFAULT 0 CHECK(command >= 0),           -- the command running or last run
 pid INTEGER, pgid INTEGER, proc_start TEXT, boot TEXT,          -- its registered identity
 started_at REAL NOT NULL, ended_at REAL, rc INTEGER,
 conclusion TEXT CHECK(conclusion IN ('passed','failed','timed_out','lingering','dirty','interrupted')),
 CHECK((ended_at IS NULL) = (conclusion IS NULL)), PRIMARY KEY (attempt_id, run)
);
```

"Latest" always means the highest `run` of one attempt; no read orders rows by wall-clock time. Every write is fenced
by `(attempt_id, dispatch_token, generation)` against the held reservation; the one writer is `setup_store.py` (added to
`test_policy.WRITERS`). The reset decision needs no cross-attempt query (it is keyed on the attempt).

**Schema: one discard.** The table goes into **v11 with S5b's attempt changes** (.16 3.3), carried by S5b, so S5e-1
and S5e-2 change no schema and the person discards factory.db once, at the first runner upgrade past S5b. **S5b's DDL
waits for this plan to be final** (Q1 answered): a different answer to Q1 could change the table.

**Evidence.** `EvidenceFiles.setup_log(key, run) -> Path`: `attempts/<hash>/setup-<run>.log` (0600, append); stdout and
stderr merged; each command framed by the factory's own lines `$ <shlex.join(argv)>` and `exit <rc>` / `timed out`; at
most 32 MiB per run, then one `[truncated]` line. `tl step show` reads the conclusion from factory.db and prints the path;
nothing reads the log for control.

**This repository's `setup` (in S5e-1).** `just install` alone does not make `just check` work offline: `uv tool run`
of ruff and pyrefly and `uv run --with import-linter` need their tools in the cache (Run S finding 3). A new recipe:

```just
# Prepare a slot: the project environment and every pinned check tool in the uv cache (the factory's `setup`).
bootstrap: install
    uv tool run "ruff@$(just pin ruff)" --version
    uv tool run "pyrefly@$(just pin pipx:pyrefly)" --version
    uv run --frozen --no-sync --with "import-linter==$(just pin pipx:import-linter)" lint-imports --help
```

and `.task-loop.json` `"setup": [["just", "bootstrap"]]`. The profile default for a repository naming no `setup`
stays `just install` (B3).

**Slot release (S5e-1).** The release's stop proof (both modes, settled and abandon) gains one check after the agent's:
the attempt's latest `setup_run`, while unfinished or concluded `lingering` or `timed_out`, must name an identity that is
gone with an empty group, observed boot-aware as the entry does (another boot is gone), else `unsettled setup_running`
(`unavailable setup_unknown` when it cannot be observed), nothing changed. The release does not stop it: CLAUDE.md allows the
factory no signal outside `interrupts.py`, and the release never stops an agent either; the person stops the recorded
pid by hand or waits.

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
(Run S finding 1; `MISE_TRUSTED_CONFIG_PATHS` is not set, D14). The sandbox word stays `workspace-write`.

**Plan gets no environment (decided here).** Plan writes only `docs/design/<id>/`; nothing it does needs an installed
environment. Setup for it would run task-branch code with network outside the sandbox for no use, add minutes to every
plan (D4 re-plans after each abandon) and change plan's access bytes that S3's constants guard.

## 6. Preflight (step 3 of section 4)

Checks and folder creation only; emptying is steps 4, 6 and 9.

| Check | Refusal (`refused` unless marked) |
|---|---|
| `sys.platform == "linux"` | `environment:platform` |
| `TMPDIR` at most 64 bytes | `environment:path_long` |
| Each root resolves under `<slots_root>/<repo_id>/`, and none equals, contains or is inside the slot, its G or C (from the verified pointer), the person's checkout, the evidence root or factory.db's folder | `environment:roots` |
| `shutil.rmtree.avoids_symlink_attacks` | `environment:remove_unsafe` |
| The three folders exist (created 0700 when missing) | `unavailable environment:files` |
| Sandbox usable: `codex sandbox linux` with `prepared_access`'s `-c` keys runs `/bin/sh -c` that creates and removes one file in each root and fails if `/tmp` is writable; exit 0 within 30 s, through `stream_proc.capture` (an external-tool reason: only Codex knows its backend) | `environment:sandbox` |

The probe removes its own files, so a reuse (no reset) leaves the uv folders as setup left them. On Linux the backend is
bubblewrap (unprivileged user namespaces), not Landlock (Run S finding 2); the probe tests that, not a kernel setting.
**macOS: nothing is observed.** Seatbelt with `writable_roots` outside the cwd, the two `exclude_*` keys, environment
pass-through, offline uv and process containment have never been run; the default `slots_root` there also gives a
`TMPDIR` of 53 + len(user) + len(slot) bytes against a 103-byte socket limit. Until a macOS Run S passes, an implement
attempt on macOS is refused `environment:platform` before any setup (Q2); plan runs as today.

**Security of the new roots against the pointer and pin rules.**

1. The `/tmp` exclusion existed so the agent could not build a Git directory outside the slot and have it swapped
   into the slot's `.git` pointer between a check and a Git call. That swap is now closed independently: every slot
   Git view opens pinned to the G its full check verified (tl-8bh9.14.2), `<slot>/.git` is never re-read, and the
   pointer check requires G directly under `<C>/worktrees` with C bound to this repository, so a G in a root is
   `redirected`.
2. The factory opens no Git view on any path under a root and reads no file there for control; its only operations
   there are create, empty and symlink-safe delete. The scratch is never a Git directory: created empty, emptied before
   and after setup, and preflight refuses any overlap with the slot, G, C, the person's checkout, the evidence root and
   factory.db's folder. Tests may create repositories under `TMPDIR`; Codex mounts a `.git` that exists at start
   read-only (finding 2), and none exists in an emptied scratch.
3. The roots sit beside `.locks/`, not above it: the custody lock files stay unwritable. The evidence (input, answer,
   `entry.log`, setup logs) stays outside every root.
4. The exposure is persistence, not escape: what any agent writes into the uv folders or the slot's ignored files would
   be executed later outside the sandbox. The reset before every setup (section 3) removes it; B4 must reset too.
5. The worker-gone gate before every factory Git write and the release's stop proof (now including setup) are
   unchanged in kind; the agent's command processes cannot outlive the worker (section 8, stop-proof wording).

## 7. Input words (implement)

S5b ships implement with neutral words about checks (".16 2.2" without its "both run offline in this slot" sentence).
S5e-2 adds, with a constant test:

> The factory ran this repository's `setup` before you started; there is no network now. Before answering, run every
> command listed under `checks` in `.task-loop.json` (while you work, a focused part such as one test file is fine)
> and fix what they report. Temporary files go to `$TMPDIR`, which is emptied after the step; do not write elsewhere
> outside the repository. Your runs are evidence for you: after this step the checks run again outside your control,
> and only those results count. In `explanation`, name each command you ran and how it ended.

Generic: no repository command is hard-coded; the agent reads the profile file in its checkout. "Run again outside
your control" is true at M1 (the person runs them) and after B4.

## 8. Types, ports and modules

| Module | Contents | Code lines |
|---|---|---|
| `access.py` (new leaf) | `SANDBOX`, `CODEX_ACCESS` (moved), `prepared_access`, `agent_env` | about 40 |
| `environment.py` (new) | `Folders(tmp, cache, tools)`, `folders(slot_path)`; `preflight`; `Preparation.prepare(record, slot: Prepared, renew) -> None \| AttemptResult` (section 4's order) | about 210 |
| `setup_store.py` (new) | `SetupRow`, `latest(attempt)`, `failures(attempt)`, `begin`, `registered`, `conclude`; the `Setup:` read for status and the release | about 95 |
| `prepare.py` | `base` returns `Prepared(head, gitdir, root)` instead of the bare head | +4 |
| `attempt.py` (289 code lines by the policy counter) | optional `prepare_env` port for `environment` kinds; `execute(..., renew)`; `_launch` picks access and env | +14, -20 moved |
| `attempt_entry.py` | passes the keep-alive's renewal to `execute` | +3 |
| `steps.py`, `plan_step`/`implement_step` | `environment` field | +3 |
| `evidence_files.py` | `setup_log` | +12 |
| `slot_release.py` | setup in the stop proof; empty `.t/<slot>` after the park, best effort | +18 |
| `composition.py` | `RealEnvFiles`, the probe, the setup process adapter, wiring in `open_attempts` | +45 |
| status/render, `step_guide` | `Setup:` line and JSON key `setup`; GUIDE `environment`, `setup_running` | +22 |
| `justfile`, `.task-loop.json` | `bootstrap` recipe; `setup` names it | +6 |

Ports (Protocols, each with a semantic fake in `tests/steps/doubles.py`):

```python
class SetupProcess(Protocol):   # real: stream_proc.run_registered
    def __call__(self, argv: Sequence[str], *, registered: Callable[[OwnedProcess], None], cwd: str,
                 env: Mapping[str, str], timeout: float, line: Callable[[bytes], None]) -> SetupEnded: ...
@dataclass(frozen=True)
class SetupEnded: rc: int | None; timed_out: bool; exec_failed: bool; pgid: int
class EnvFiles(Protocol):       # real: RealEnvFiles (os.makedirs 0700; symlink-safe rmtree of contents with onexc)
    def ensure(self, path: Path) -> bool: ...         # exists as a directory, not a link
    def empty(self, path: Path) -> bool: ...
type SandboxProbe = Callable[[Folders], bool]         # real: codex sandbox via stream_proc.capture
type GroupGone = Callable[[OwnedProcess], bool]       # real: observe_owned + group_alive, as worker_gone
type Renew = Callable[[], Literal["held", "unrenewed", "lost"]]
```

**Shelf slice S5e-0 (tracked separately).**

- `stream_proc.run_registered(argv, *, registered, cwd, env, timeout, on_line, registration_timeout) -> Result`:
  `popen_registered`'s exec gate (the callback commits the identity before the command executes) plus `run`'s line
  pumping, wall timeout and `stop_tree`. stdin `/dev/null`; stderr merged into stdout (one ordered log). An exec failure
  after the commit (ENOENT, EACCES) returns a `Result` marked exec-failed (the row is concluded `failed`, the identity
  never ran); `RegisteredStartUncertainError` propagates (the row keeps the identity, no conclusion; the next entry
  reconciles it). `stream_proc` ships from the `any-agent` tag (see `uv.lock`), so this is one `any-agent` release and
  two pins (`stream-proc`, `any-agent`) from one shelf commit.
- `git_porcelain` `Worktree.clean(keep, *, ignored, nested=False)`: `nested=True` runs `git clean -ffdx` (0.14.0 runs
  `-fdx`, which skips nested repositories), and an ignored-files listing usable for the whole slot (`dirty`'s
  `ignored_under` refuses the empty pathspec, .16 2.4). One release, one pin.

Without `run_registered` a setup killed with its entry would leave an unrecorded tree in the slot, and factory source
may not wait on a `Popen` itself.

**Stop-proof wording (S5e-2, docs and docstrings).** `composition.worker_gone` and the glossary's `agent process` row:
the agent's shell commands run in a new session under `bwrap --unshare-pid --as-pid-1 --die-with-parent`, outside
Codex's process group by design; they are contained by that PID namespace, which ends when its parent ends (Run S
finding 6, Linux only), so "the worker is gone and its group is empty" is the stop proof for them too. Setup processes
are never in the agent's group: the entry proves each command's group empty before dispatch, and the release proves
any unfinished setup gone. Detached descendants of setup remain unobservable (.4.4).

## 9. Slices (caps 400 per file, 80 per function, 800 per test file)

| Order | Slice | What | Source | Tests |
|---|---|---|---|---|
| 1 | **S5e-0 shelf** (own tracker task) | `run_registered` (any-agent release), `clean(nested=True)` and the ignored listing (git-porcelain release), three pins | shelf about +90; here pins only | shelf's own |
| 2 | **S5b** (.16) | as designed, plus this `setup_run` DDL in v11; neutral input words; its DDL waits for Q1 | DDL +14 | one CHECK test |
| 3 | **S5e-1 setup** | `environment.py` (section 4 order without the probe), `setup_store.py`, `setup_log`, `prepare.Prepared`, claim renewal, `StepKind.environment`, release stop proof for setup, `bootstrap` and the profile: implement runs setup; the agent still has plan's access | about +330 | about +380 |
| 4 | **S5e-2 access** | `access.py`, preflight and probe, `_launch` access and env, release empties scratch, `Setup:` show line, GUIDE, section 7's words, stop-proof wording | about +150 | about +230 |
| 5 | **S5c** (.16) | round advance; depends on S5e-2 (D2) as well as S5b | | |

Tracker edges (made with this revision): S5e-0 is its own task; S5e depends on S5e-0 and on S5b (the old edge S5b ->
S5e is flipped); S5c depends on S5e. The Run S spike is done.

## 10. Tests

pytest functions, fakes through the ports above; no subprocess in source or tests; no test per private helper.

- `test_access.py`: `CODEX_ACCESS` and `SANDBOX` bytes equal today's (S3 guard); `prepared_access` names exactly the
  three roots in a TOML-valid array and keeps network off and both excludes; `agent_env` names, none containing
  KEY/SECRET/TOKEN; a plan attempt launches with today's argv and no added env, an implement attempt with both.
- `test_environment.py`: the order of section 4 as observed calls (failure count before probe; reconcile before
  emptying; reset before setup; scratch emptied before and after); every setup resets, also for the same task and
  after a plan attempt in the slot; a passed run at the same B and digest is reused only while `admitted` (no reset,
  no process call); a new B runs again; non-zero exit stops at that command; the second failure then `refused
  environment:failed` with no probe and no process call; exec failure is `failed`; start uncertain keeps the identity;
  timeout; a lingering group after the first of two commands; a dirty slot after setup is `dirty`; unfinished row:
  other boot or gone group -> `interrupted` and a new run, alive -> `environment:running` with nothing run or
  signalled; identity stored before the fake "executes"; claim `lost` after setup refuses `claim_lost` before
  dispatch; profile missing/refused/unavailable; preflight table (platform, a 65-byte root, overlap with slot/G/C/
  evidence, rmtree flag, probe false); `dispatch` never called on any refusal.
- `test_setup_store.py` (real sqlite in `tmp_path`): fencing by token and generation; the v11 CHECKs; "latest" is the
  highest `run`.
- `real/test_env_files_real.py`: `empty` deletes a planted symlink, never its target; empties a planted 0o000
  directory through the `onexc` retry; `ensure` refuses a symlink in place of a folder.
- `test_slot_release.py`: settled and abandon releases refuse `setup_running` while the recorded setup lives and
  succeed once it is gone; both empty the scratch after the stop proof; a failed removal does not fail the release.
- `test_step_cli`/`test_operations`: the `Setup:` line and JSON key.

**Live smoke (owner-run, this repository on a scratch tracker and scratch remote, Linux).** (1) A plan attempt's codex
argv shows `writable_roots=[]` and no setup row. (2) Implement: preflight passes; a `setup_run` row `passed` at the
plan commit; `setup-1.log` shows `just bootstrap`. (3) The transcript shows this repository's `just check` and `just
test` run offline and passing; `TMPDIR` is `.t/s1`, at most 64 bytes. (4) After release `.t/s1` is empty or gone. (5) A
relaunch before dispatch reuses the passed run; a next setup in the slot shows the reset (a new `.venv`). (6) A task
branch whose `setup` exits 1: two runs, then `refused environment:failed`, no agent tokens. (7) The person kills a
running entry by its recorded pid during setup: `environment:running` and `tl step release --abandon` refusing
`setup_running` while the setup lives; once gone, `interrupted` and a new run. (8) No process with its cwd in the slot
after release. No agent runs it.

## 11. Size

Source about +480 lines in this repository over S5e-1 and S5e-2 (plus the S5b DDL and the shelf), tests about +610.
Largest new function: the preparation sequence, about 45 lines. `test_environment.py` about 330, under 800.

## 12. Open owner questions (each with a recommendation)

**Q1. Downloads are not kept across setups.** D12 names pre-downloaded environments as the reason for slots (the Unity
example). Resetting before every setup (section 3) re-downloads everything for every implement attempt (Run S: about
40 s for `uv sync`, minutes for the tools, 254 MB for this repository). Keeping downloads safely needs storage that only
setup can write and the agent can only read; uv needs a writable cache, and Run S did not test a read-only one.
**Recommendation: accept the cost for now (small repositories); revisit with a read-only seed cache when a large-asset
repository appears.**

**Q2. macOS.** Nothing of the sandbox environment is observed there. **Recommendation (confirm): refuse implement on
macOS (`environment:platform`) until an owner-run Run S on macOS passes; plan runs as today.**

**Q3. Credentials reachable by setup through `HOME`.** Setup runs task-branch code with network and the agent's
scrubbed environment: credential variables are gone, but `HOME` stays, so SSH keys, Git credential helpers and
`~/.netrc` are readable, and the push bar is an environment entry a task-written setup can unset. A scratch `HOME` was
rejected for checks (D10). **Recommendation: accept for now, the same trust as D10 gives the checks; the land summary
lists every changed `setup` for the person.**

## 13. Risks

- **Setup cost counts against `--minutes`** and is paid by every implement attempt 1 (Q1). The person raises
  `--minutes`.
- **A failed setup holds the attempt until its deadline** (`stuck:expired_admitted`, then abandon, which restarts at
  plan by D4). Holds with a reason are B7. A `dirty` setup leaves the slot for the person to clean.
- **An orphaned setup** (its entry killed) runs unbounded; the release refuses until it is gone; the factory never
  signals it.
- **Socket paths.** Tests binding Unix sockets under `tmp_path` fail on every home (section 3).
- **A task-changed `mise.toml` or `uv.lock`** is installed only by `setup` from the committed branch (D14); an agent
  changing them mid-step works offline against the old environment.
- **Process containment** of the agent's commands is bwrap's, observed on one Linux machine with codex 0.167.0.

## 14. Review repairs (2026-11-11)

An independent review of 01e06b3fe found sixteen points; all are taken.

| # | Finding | Repair |
|---|---|---|
| 1 | Reset keyed on the last `setup_run` misses agents that ran without setup (a plan agent, an abandoned task) | Reset before every setup; only a same-attempt relaunch with no agent since a passed run skips it (section 3); `reset` column and the slot-owner query dropped; B4 resets too |
| 2 | Release ignored a live setup | Setup in the stop proof, both modes, `unsettled setup_running` (section 4). Stopping the orphan with `stream_proc.stop_pid` is **not** adopted: CLAUDE.md gives the factory no signal outside `interrupts.py`, and the release never stops an agent either |
| 3 | `just install` does not make `just check` work offline | `just bootstrap` and the profile change in S5e-1; the smoke runs this repository |
| 4 | Setup may dirty the slot | Status re-read after setup; `dirty` is a failed run (section 4 step 8) |
| 5 | Preflight emptied folders; order unclear | Preflight only creates; order in section 4 |
| 6 | `git clean -fdx` skips nested repositories | Shelf `clean(nested=True)` (`-ffdx`) and an empty ignored listing afterwards |
| 7 | Claim not re-checked after a long setup | Renewal after setup, before dispatch |
| 8, 9 | Tracker edges; v11 frozen too early; wall-clock ordering | Edges in section 9; S5b's DDL waits for Q1; "latest" is the highest `run` |
| 10 | `rmtree` stops at a 0o000 directory | `onexc` handler and a real test |
| 11 | Q3's premise (the scrub does not remove files under `HOME`) | Wording corrected; Q3 restated |
| 12 | Lingering checked only at the end | Each command's group, right after it ends |
| 13 | `run_registered` underspecified | stdin, stderr, exec failure, start uncertain, release scope (section 8) |
| 14 | S5b words | Neutral in S5b; S5e-2 adds the environment words |
| 15 | Setup's temp files reached the agent | Scratch emptied after setup |
| 16 | Path budget, line count, probe order and leftovers, D14 platform path | Budget with the slot name; 289 code lines; failure count before the probe; the probe removes its files; section 2 states `machine_config` as built |

## 15. Not verified

- ~~`codex sandbox linux` accepting `--ignore-user-config` and the same `-c` keys as `exec`.~~ Checked by S5e-2 (section 18):
  codex 0.167.0 has no `linux` subcommand and rejects `--ignore-user-config`; the probe is `codex sandbox -c
  sandbox_mode="workspace-write" <the agent's -c keys> -- <command>`.
- ~~That `git clean -ffdx` through the pinned view removes `.venv` and nested repositories without touching tracked
  files.~~ Verified by S5e-1's real test (section 16).
- That `just bootstrap` warms everything `just check` needs offline beyond what Run S ran by hand (the same commands).
- Line estimates, from the counts at this tree.

## 16. As built: S5e-1 (setup, 2026-11-11)

Tracker tl-8bh9.4.3.1.16.2, on S5b (schema v11 with the `setup_run` DDL, no migration) and the S5e-0 pins. The implement
attempt's entry now resets the slot and runs the profile's `setup` before its agent; the agent still launches with plan's
access (`CODEX_ACCESS`, no writable roots, no added environment): S5e-2 adds them. Plan attempts are unchanged byte for
byte (no environment event, no setup row; the S3 constants pass unchanged).

- **`environment.py` (new, 197 code lines).** `Folders(tmp, cache, tools)` and `folders(slot)` (`.t/<slot>`,
  `.env/<slot>/uv-cache`, `.env/<slot>/uv-tools` beside the slots); `setup_env` (the credentials' scrubbed environment
  plus `TMPDIR`, `UV_CACHE_DIR`, `UV_TOOL_DIR`, no `UV_OFFLINE`); `setup_digest` (sha256 of the argv list as compact
  JSON); the ports `SetupProcess`, `EnvFiles`, `SetupSeen` (tri-state `gone`/`alive`/`unknown`), `GroupAlive`,
  `SlotProfiles`, `Renew`, gathered in `EnvironmentPorts`; and `Preparation.prepare(record, slot: Prepared, renew, env)`
  in section 4's order. A repeat (`number > 1`) runs steps 1-4 and 9-11. The preflight of S5e-1 is the platform check
  (`refused environment:platform` off Linux, Q2's recommendation, before any setup), `refused environment:remove_unsafe`
  and the three folders created (`unavailable environment:files`); `path_long`, `roots` and the sandbox probe are
  S5e-2's. The reset is `Worktree.clean(ignored=True, nested=True)` on the slot's pinned view, then
  `dirty(ignored_under=["."]).ignored` must be empty (`refused environment:reset`), then `.env/<slot>` emptied and its two
  folders made again. Each command is framed in the log (`$ <shlex.join>`, then `exit <rc>`, `timed out`, `not started`,
  `ended by a signal` or `start uncertain`, and `lingering`); a lingering group is checked before the exit code. After
  the commands the slot's status through the pinned view must be clean (`dirty`).
- **Words chosen here (the plan was silent).** A start failing before any registration (`OSError` from the spawn) is a
  `failed` run like an exec failure (`unavailable environment:exit`); `GitUnavailable` in the reset is `unavailable git`
  with no run row (the reset runs before `start`), and in the final listing or status read `unavailable git` with the
  run left unfinished (the next entry reconciles it `interrupted`); a log that cannot
  be opened is `unavailable environment:files` before the run row is written (the run number is the latest plus one,
  so the log is opened first). An environment kind with no wired `Preparation` or no `renew` is `unavailable
  environment:unwired` (never an implement agent without its setup).
- **`setup_store.py` (new, 76).** `SetupStore(AttemptReads)`: `latest`, `failures` (`failed`, `timed_out`, `lingering`,
  `dirty`; `interrupted` is not the setup's fault), `start` (named so because `AttemptReads.begin` is the transaction),
  `registered`, `conclude`. Every write checks the key against the held reservation of an `admitted` attempt
  (`StoreRefused("stale_reservation")`); a concluded or existing run is `setup_changed`. `running(con, attempt_id)` is
  the release's read: the latest run's registered identity while it has no conclusion (none registered: nothing ran).
  Composition passes the bounded registration connection, so the identity write inside the registered start's window
  waits at most `REGISTRATION_BUSY_MS`. `test_policy.WRITERS` names it for `INSERT` and `UPDATE setup_run`.
- **`attempt.py`** (+11): `Attempts(..., environment=None)`; `execute(key, me, renew=None)`; `_prepared` runs
  `prepare.base`, then the preparation for a kind with `environment`; `_launch` also returns the credentials' env.
  **`prepare.base`** returns `Prepared(head, gitdir, root)`. **`steps.StepKind.environment`** (implement True).
  **`attempt_entry.renewal(alive)`** is the `Renew` port: one keep-alive renewal now, then its word.
- **`composition.py`** (292 to 358): `setup_process` (`stream_proc.run_registered`; `RegisteredStartUncertainError` is
  `uncertain`), `setup_seen` (`observe_owned`, another boot `gone`, else `group_alive`), `RealEnvFiles` (`mkdir` 0700;
  `empty` unlinks links and files and removes directories with `shutil.rmtree`, whose `onexc` gives an unreadable
  directory owner `rwx` and removes it once more), `slot_profiles` (`GitProfileFiles` on the slot's view pinned to its
  G), wired in `open_attempts`. The chmod follows `lstat`, so a directory swapped for a link between the two is a
  residual race; no agent runs while setup does.
- **`evidence_files.py`**: `setup_log(key, run)` and `open_setup_log` (`SetupLog`: 0600, append, close-on-exec, 32 MiB
  then one `[truncated]` line). **`slot_release.py`**: the stop proof, both modes, ends with the unfinished setup's
  command through the agent's `gone` rule: `unsettled setup_running` (`held:setup_running`), nothing changed; the
  plan's `setup_unknown` is folded into it (the `gone` port already counts unknown as alive). Emptying the scratch after
  the release is S5e-2's. **`step_guide`**: GUIDE `environment` and `setup_running`. No `Setup:` show line (S5e-2).
- **Policy**: `clean` joins `test_policy.GIT_WRITES`, owned by `environment.py`.
- **`justfile`**: `bootstrap` as section 4; `.task-loop.json` `setup` is `[["just", "bootstrap"]]` (ran here: it
  warms ruff, pyrefly and import-linter).

Tests: `test_environment.py` (new, 24 tests): the order as observed events (failure count, preflight, scratch, reset,
commands with each group check, scratch, renewal, agent), the identity committed before the fake executes, the env,
cwd, timeout and log; the reset removing ignored files; `environment:reset`; reuse on relaunch after `claim_lost`
(no reset, no command); another B or setup digest runs again; exit, exec and spawn failures, the second failure then
`environment:failed` with nothing observed or run; uncertain start, then `running`, `unknown`, and `interrupted` plus a
new run; an unregistered unfinished run; timeout and a deadline between commands; lingering after the first of two
commands; `dirty`, then `slot_dirty`; profile missing, not an object, bad value, unavailable; platform, remove_unsafe,
files; an uncleanable `.env`; unwired; a plan attempt on another platform runs no setup; a repeat. `test_setup_store.py`
(13): fencing by token, generation and attempt, a released or dispatched attempt, no rewrite of a concluded run,
"latest" the highest run, the failure count, `running`, the v11 CHECKs. `test_slot_release.py` (+3): both modes
`held:setup_running` while the latest unfinished run's command lives (an earlier run's live pid is never asked), then
released; an unregistered run does not hold. `test_attempt_entry.py` (+4): the renewal port. Real:
`real/test_env_files_real.py` (7: a planted link removed and its target kept, 0o000 directories emptied, a link in place
of a folder, `setup_process` registering before the command runs with its output and exit, an exec failure, a process
left in the group seen alive), `real/test_environment_real.py` (1: real Git and a real process: the committed profile
read through the pinned view while the working tree's differs, `-ffdx` removing an ignored nested repository and files,
the command run in the slot with the slot's folders, `passed`). `test_admit_chain` and `test_prepare` wire a passing
fake environment for their implement attempts. Mutations of the failure bound, the reuse key, the repeat rule, the
reconcile's alive and unfinished checks, the renewal, both scratch emptyings, the lingering, exit and deadline checks,
the dirty read, the reset's listing and `nested`, the `onexc` retry, the release's setup proof, and the store's phase,
`conclusion IS NULL` and run ordering each fail a test (run by hand, not kept).

Gates: `just check` clean (ruff, pyrefly 0 errors, import-linter 8 contracts kept); `just test` 1530 passed. Code lines
(policy counter): source +408 against the estimate of about +330 (`environment` 197, `setup_store` 76, `composition`
358, `attempt` 300, `slot_release` 257, `attempt_entry` 225, `evidence_files` 107); tests +567 against about +380
(`doubles` gained the environment fakes: 90 to 191). Live smoke not run (owner-run, section 10; its steps 3 and 4 need
S5e-2).

## 17. Review repairs: S5e-1 (2026-11-11)

An independent review of bbbb0c775 found eight points; all are repaired, each with a test that fails without it (run by
hand, not kept).

| # | Finding | Repair |
|---|---|---|
| 1 | A run concluded `lingering` (or `timed_out` with survivors the adapter dropped) left a live group no later step checked | `setup_store.LIVE_AFTER = ("lingering", "timed_out")` and `SetupRow.unsettled`: the latest run's command while unfinished or concluded so. The entry's reconcile and the release's `running` read both require that group gone (`environment:running`, `held:setup_running`); a concluded run keeps its conclusion. Chosen over leaving a lingering run unconcluded: no extra state, and the failure count still sees it |
| 2 | `RealEnvFiles.empty` stopped at one vanished entry | Only the folder's own `lstat`/`scandir` maps `FileNotFoundError` to empty; a vanished entry is skipped and the rest removed; any entry left makes it False |
| 3 | The release used `worker_gone` for setup (an old boot's identity maybe alive) and its guide said to kill `-<pgid>` | `SlotRelease.setup_seen` (a new port, composition's `setup_seen`: another boot gone, unknown `unavailable setup_unknown`); the `setup_running` guide lists the group's members and checks each one's cwd is the slot before any stop |
| 4 | Step 8 read only the status | Through the pinned view's worktree listing, HEAD must be B on `task/<id>`, else `dirty` with the word `environment:moved` (no new conclusion: the v11 CHECK stays) |
| 5 | Every setup write used the 1.5 s bounded connection | `SetupStore(connect, begin, registering)`: only `registered` uses the bounded registration connection |
| 6 | The `onexc` handled only unreadable directories, once, without nesting | `_Writable`: a PermissionError from `unlink`/`rmdir` chmods the parent u+rwx and retries; an unreadable directory is chmodded and removed with the same handler (nested 0o000 folders), each path once; the folder's own entries go through it too |
| 7 | An `OSError` after the start was taken as "nothing ran" | The `registered` callback records the identity: after it, the run is judged by its group (`lingering`, else `failed`, log `ended uncertainly`) |
| 8 | Section 16 said a reset `GitUnavailable` leaves an unfinished run | Corrected above |

Also found, not fixed here: the shelf's `stream_proc._pump` buffers a line without a newline without bound, so setup
output can grow the entry's memory before the 32 MiB log cap applies. Tracked as tl-8bh9.14.25 (shelf, label
architecture-review).

## 18. As built: S5e-2 (access, 2026-11-11)

Tracker tl-8bh9.4.3.1.16.2, on S5e-1. The implement agent now launches with three writable roots outside its slot and an
offline environment; plan attempts are unchanged byte for byte (`CODEX_ACCESS`, no added environment, no probe). No
schema change.

- **`access.py` (new leaf, 51 code lines).** `SANDBOX` and `CODEX_ACCESS` moved from `attempt` unchanged; `Folders`,
  `folders` (moved from `environment`, with `roots`); `TMP_BYTES = 64`; `prepared_access(found)` (CODEX_ACCESS with
  `writable_roots=<json.dumps([tmp, cache, tools])>`, a valid TOML array); `agent_env(found)` (`TMPDIR`, `UV_CACHE_DIR`,
  `UV_TOOL_DIR`, `UV_OFFLINE=1`); `PROBE` and `probe_argv(exe, found)`.
- **`attempt._launch`**: for a kind with `environment`, `prepared_access` (since section 19 it also carries `agent_env`
  as shell-only keys; the launch environment is the credentials' alone); it returns the credentials' own `(exe, env)`
  for the preparation, so setup still has network (no `UV_OFFLINE`).
- **Preflight** (`environment._preflight`, section 6's order): `platform`, `path_long` (TMPDIR bytes over
  `EnvironmentPorts.tmp_bytes`, composition `TMP_BYTES`), `roots` (`_apart`: every root resolved through the new
  `EnvFiles.resolve`, links followed; each strictly inside the resolved `<slots_root>/<repo_id>/`; no two roots, nor a root
  and the slot, G, C = G's grandparent, the person's checkout, or `EnvironmentPorts.protected` (composition: the
  artifacts root and factory.db's folder) equal or nested; an unresolvable path refuses), `remove_unsafe`, the folders
  made (`files`), then the probe (`sandbox`). The failure count and the reconcile stay before it, so a dead attempt never
  probes.
- **The probe** (`slot_env.sandbox_probe`): `stream_proc.capture` of `codex sandbox -c sandbox_mode="workspace-write"
  <every -c key of prepared_access> -- /bin/sh -c PROBE sh <tmp> <cache> <tools>`, cwd the slot, the agent's environment,
  30 s; True only for exit 0, not timed out, no survivors; an `OSError` at start is False. `PROBE` makes and removes a
  `.tl-probe-<pid>` folder in each root (`mkdir`/`rmdir`, no `rm`), exits 3 when a root is not writable and 4 when `/tmp`
  is. Checked by hand on this machine (codex 0.167.0, bubblewrap): the full key set exits 0; a missing root exits 3;
  without the `exclude_*` keys exits 4; without `sandbox_mode` the roots are read-only (exit 3); `--ignore-user-config`
  is rejected (exit 2). Then `sandbox_probe` itself, by hand against the real `codex` with roots under `~/tl-smoke`: True;
  with the tools root removed, False. Codex leaves its own `codex-bwrap-synthetic-mount-targets-<uid>` in `TMPDIR` (the
  scratch); step 4 empties the scratch after the preflight, so it never reaches the agent; the uv folders stay as they
  were.
- **`slot_env.py` (new, 84).** `RealEnvFiles` (with `resolve`), `_Writable`, `_remove` and `setup_process` moved out of
  `composition` (358 to 317 code lines), plus `sandbox_probe`. `composition.open_attempts` wires the probe and the
  protected paths.
- **`slot_release`**: a new port `scratch` (`RealEnvFiles().empty`); after the recorded release, still under the lock and
  after the stop proof, `.t/<slot>` is emptied; its answer is ignored (the next preparation empties it again before any
  agent). Both modes; a refusal empties nothing.
- **`tl step show`**: `Setup: run <n> <conclusion|unfinished> at <B>; log <attempt dir>/setup-<n>.log`, or `Setup: none`;
  JSON key `setup` (`run`, `conclusion`, `commit`, `log`, or null). Read through `SetupStore.latest` on the status
  store's connection; the log path is computed, never created.
- **Words.** `implement_step.ENVIRONMENT` is section 7's text (the closing "In `explanation`, name each command you ran
  and how it ended" merged with the existing words about test files). GUIDE `environment` names `path_long`, `roots`,
  `sandbox` and `files`. `composition.worker_gone`'s docstring and the glossary's `agent process` row carry the
  stop-proof wording of section 8.
- **Import contract**: `slot_env` and `access` join the entry's "never imports the command surface" sources.

**Deviations from the plan.** (1) The probe runs `codex sandbox`, not `codex sandbox linux`, and without
`--ignore-user-config` (both refused by 0.167.0); the person's Codex config is therefore read beneath the agent's `-c`
keys, which override every key the probe depends on, while the agent itself still ignores that config. (2) The probe
makes and removes a folder, not a file (no `rm` in the script). (3) `tmp_bytes` is an `EnvironmentPorts` value
(composition passes `TMP_BYTES`) so the sequence tests in `test_prepare`, `test_admit_chain` and the real setup test, whose
slots sit under pytest's long `tmp_path`, can widen it; `test_environment` keeps 64 with a short fake slots root.
(4) Per section 6, a root inside factory.db's folder or the artifacts root is refused even though only a root equal to or
holding them exposes them: a machine config with `slots_root` under factory.db's folder (the owner's `~/tl-smoke` config:
`db = ~/tl-smoke/factory.db`, `slots_root = ~/tl-smoke/slots`) refuses `environment:roots` (owner decision below).

Tests: `test_access.py` (new, 4): plan's bytes, the three roots as a TOML array with nothing else changed, `agent_env`
names surviving the factory's scrub, the probe argv. `test_environment.py` (+5 tests, 11 cases): the implement agent's
argv and env and the probe's inputs; a plan attempt's argv and env unchanged and no probe; TMPDIR of 64 bytes passes and
65 refuses before any folder; six `roots` cases (a link into the slot, an evidence root holding a root, a link outside
the slots, roots nested in each other, slots inside factory.db's folder, an unresolvable root); a failed probe after the
folders, nothing run. `test_slot_release.py`: the scratch emptied after a settled release, not on a refusal, and a
failed emptying still releases. `test_step_cli.py`: the `Setup:` line (none, failed, unfinished), the JSON key, and a
real read of a stored run. `test_steps.py`: section 7's words. Real: `real/test_sandbox_probe_real.py` (3: a stand-in
`codex` script records cwd, TMPDIR, UV_OFFLINE and the argv and maps exit 0/1; a missing executable; `PROBE` itself on a
read-only root fails and leaves no folder behind). Mutations of the budget comparison, the slot/G/C/checkout list, the
protected list, the inside-the-slots rule, the root-to-root check and the probe's environment each fail a test (run by
hand, not kept).

**Owner decisions.** (a) Keep section 6's "is inside" for the artifacts root and factory.db's folder (then move the smoke
config's `db` out of `~/tl-smoke` or `slots_root` elsewhere), or narrow it to "equals or holds" for those two.
(b) Q2 stands as built: implement refuses `environment:platform` off Linux.

**Not verified.** No live run: no implement agent has run `just check`/`just test` inside the real sandbox through the
factory; the probe ran against the real `codex` only by hand (above), not from an entry with the scrubbed credentials'
environment. Steps for the owner-run smoke: [live-smoke.md](live-smoke.md).

## 19. Review repairs: S5e-2 (2026-11-11)

An independent review of 55022eac7 found seven points. Six are repaired as asked; the first is repaired in part, because
a check with the real `codex` showed its suggested fix cannot keep Codex's sandbox launcher out of the scratch. Each
repair has a test that fails without it, except where noted.

| # | Finding | Repair |
|---|---|---|
| 1 | `TMPDIR=.t/<slot>` (and `UV_*`) reached Codex's own process, so Codex's temporary files land in an agent-writable root | The four variables are now `-c shell_environment_policy.set.<NAME>=<TOML string>` keys appended to `prepared_access` (plan's bytes unchanged); the agent's launch environment is the credentials' alone, for plan and implement alike; the probe is given the same keys and the credentials' environment, and `PROBE` exits 5 unless its shell has `TMPDIR` = the first root and `UV_OFFLINE=1`. **Not fully achievable, checked under `~/tl-smoke/s5e2-probe` with codex 0.167.0:** `codex sandbox ... -c shell_environment_policy.set.TMPDIR=<root>` gives the shell `TMPDIR` and `UV_OFFLINE` (verified), but Codex's Linux sandbox launcher, which runs outside bubblewrap per command, still makes its mount registry `codex-bwrap-synthetic-mount-targets-<uid>/lock` in the command's TMPDIR: inside the scratch, even with the person's own `TMPDIR` set elsewhere; with no TMPDIR for the shell it goes to `/tmp`. Codex's default workspace-write sandbox makes both `/tmp` and `$TMPDIR` agent-writable, so the registry lives in an agent-writable folder by Codex's own design, and the binary refuses a registry that is a symlink ("synthetic mount registry must not be a symlink"). What the repair does keep private is everything else Codex's own process does with TMPDIR (for `codex exec`, not observed: no agent run). The alternative, no `TMPDIR` for the shell (only `TEMP`/`TMP`), leaves `mktemp`, Rust and uv temporary files in the unwritable `/tmp`; not adopted (owner question c below) |
| 2 | A root made read-only, or a probe folder left behind, failed every later probe | `RealEnvFiles.ensure` makes an existing folder 0700 again through `os.open(O_DIRECTORY | O_NOFOLLOW)` and `fchmod` (never a link's target); `PROBE` uses `mktemp -d "$d/.tl-probe-XXXXXX"`; the probe runs after the scratch is emptied (below); the `sandbox` guide says the folders were already made 0700 and emptied, so a failure is the sandbox itself, and names the shell-variable case. The `mktemp` change has only a text test: the stand-in `codex` runs no PID namespace, so the old fixed name (`$$`, 1 or 2 inside bubblewrap's namespace) never collides there |
| 3 | The probe ran the Codex shim with cwd = the slot before the reset | The probe's cwd is the scratch, and the probe moved after step 4: failure count, reconcile, preflight (checks, folders), scratch emptied, probe. The registry the probe's Codex leaves in the scratch is emptied by step 9 (after setup, or on a reuse or repeat) |
| 4 | `_apart` let a root resolve into a sibling slot or `.locks/` | Each root must resolve exactly to `folders(resolve(<slots_root>/<repo_id>) / <slot>)`, so no link below the base; that subsumes the inside-the-base and root-to-root checks. The overlap with the slot, G, C, the checkout and the protected paths stays. Two new cases: `.t` linked to a sibling slot, `.env` linked to `.locks` |
| 5 | The release emptied `.t/<slot>` without the link check | The release's port is now `RealEnvFiles.empty_scratch(slot)`: it empties only when the scratch resolves exactly to `resolve(<slots_root>/<repo_id>)/.t/<slot>`; otherwise nothing is touched (real test: `.t` linked to another slot) |
| 6 | The probe's `/tmp` check used a fixed name | `mktemp -d /tmp/.tl-probe-XXXXXX`; a success is a writable `/tmp` (exit 4) |
| 7 | A repeat of implement showed `Setup: none` | `tl step show` follows the repeats to the step's attempt 1 and shows its latest run: `Setup: run 1 passed at <B> (attempt <id>'s, which this repeat keeps); log <that attempt's dir>/setup-1.log`; JSON `setup.attempt_id` (null for the shown attempt's own) |

**Owner decisions added.** (c) Accept Codex's launcher registry in the scratch (Codex's own default places it in an
agent-writable `/tmp` or `$TMPDIR` and refuses a symlinked registry), or give the shell no `TMPDIR` (only `TEMP`/`TMP`)
at the cost of tools that use `TMPDIR` alone. (a) and (b) of section 18 stand.

**Not verified.** That `codex exec` applies `shell_environment_policy.set` under `--ignore-user-config` as `codex
sandbox` does (no agent run); that Codex's own process writes nothing else into the scratch during `exec`; the two items
added to the [live smoke](live-smoke.md) (a slot's `mise.local.toml` and a person's Codex `profile`).

Gates after the repairs: `just check` clean (ruff, pyrefly 0 errors, import-linter 8 kept); `just test` 1585 passed.
Code lines (policy counter): `access` 54, `slot_env` 96, `environment` 230, `attempt` 286, `attempt_status` 143,
`slot_release` 263.
