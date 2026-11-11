# Run S: sandbox and environment spike for block B2 (2026-11-11)

Owner-authorized spike for the unknowns in [the self-hosting roadmap, B2](../self-hosting-roadmap.md). Run by an agent
on the owner's word of 2026-11-11. Scratch only under `~/tl-smoke/run-s`; no other `~/tl-smoke` content touched.

## Machine

| | |
|---|---|
| Host | OrbStack Linux VM on Apple Silicon: `Linux pix 7.2.12-orbstack-00394-gbecdd6130068 #1 SMP PREEMPT aarch64` |
| LSMs | `/sys/kernel/security/lsm`: `capability,landlock,yama,bpf` (Landlock available) |
| Codex | `codex-cli 0.167.0`; `codex` on `PATH` is a mise shim (`~/.local/share/mise/shims/codex -> mise`) |
| Sandbox backend | bubblewrap 0.12.0 (`/run/current-system/sw/bin/bwrap`); `max_user_namespaces` 2147483647 |
| Tools | just 1.58.0, uv 0.13.0 (mise), project Python 3.15.0b2 (uv managed) |
| Model for the one agent run | `gpt-6-luna`, effort `low`; one `codex exec` run, 33.5k input / 0.8k output tokens |

macOS (Seatbelt) was not and cannot be tested here.

## Method

The slot was a `git clone --no-hardlinks` of this branch at `f5ee65990` into `~/tl-smoke/run-s/slot` (a clone, not a
worktree; see "not observed"). Most sandbox questions were answered without a model through `codex sandbox`, which runs
one command under the same Linux sandbox as `codex exec`, with an empty `CODEX_HOME` so no user config applied and the
same `-c` keys as `attempt.CODEX_ACCESS`. The environment question needs a real agent shell, so one `codex exec` run
used the factory's own launch values: `taskloop.composition.codex_machine_credentials()` for the executable and scrubbed
environment (push bar included), `taskloop.attempt.CODEX_ACCESS` and `SANDBOX` imported from the slot's installed
package, and argv in `any_agent` `CodexHarness.launch_spec` order, with only `writable_roots` replaced and B2's
variables added:

```
~/.local/share/mise/shims/codex exec -m gpt-6-luna -c model_reasoning_effort="low" -s workspace-write
  --ignore-user-config --ignore-rules -c sandbox_workspace_write.network_access=false
  -c sandbox_workspace_write.writable_roots=["~/tl-smoke/run-s/uvcache","~/tl-smoke/run-s/scratch","~/tl-smoke/run-s/uvtools"]
  -c sandbox_workspace_write.exclude_slash_tmp=true -c sandbox_workspace_write.exclude_tmpdir_env_var=true
  -c approval_policy=never -c tool_output_token_limit=3000 --json -o ~/tl-smoke/run-s/answer.txt -
env additions: TMPDIR=<run-s>/scratch UV_OFFLINE=1 UV_CACHE_DIR=<run-s>/uvcache UV_TOOL_DIR=<run-s>/uvtools
               MISE_TRUSTED_CONFIG_PATHS=<run-s> RUNS_MARK=1
```

The prompt asked the agent to run one probe script and return its output verbatim. Cache warm-up ran outside the
sandbox, with network, as B2's `setup` would: `UV_CACHE_DIR=<run-s>/uvcache uv sync --frozen --no-editable`, then
`uv tool run ruff@0.17.2 --version`, `uv tool run pyrefly@1.4.0 --version` and
`uv run --frozen --no-sync --with import-linter==2.15 lint-imports --help`. Cache afterwards: 254 MB.

## Findings

| # | Unknown | Observed | Evidence (excerpt) | Consequence for B2 |
|---|---|---|---|---|
| 1 | `TMPDIR`, `UV_*`, `PATH` reach the agent's commands under `--ignore-user-config` | Yes. Every added variable arrived unchanged; `HOME` too; the push bar's `GIT_CONFIG_COUNT=1` arrived. Codex prepends its own directories to `PATH`, the rest is the factory's `PATH` in order. | Agent output: `TMPDIR=<run-s>/scratch`, `UV_CACHE_DIR=…/uvcache`, `UV_OFFLINE=1`, `UV_TOOL_DIR=…/uvtools`, `RUNS_MARK=1`, `nenv=75 GIT_CONFIG_COUNT=1`, `PATH=…/codex-path:~/.codex/tmp/arg0-linux/…:<factory PATH>` | Holds: the environment is the access mechanism, no `shell_environment_policy` override needed. Codex's default policy is documented to drop names containing `KEY`/`SECRET`/`TOKEN` (not tested here), so no B2 variable should contain those words. |
| 2 | `writable_roots` outside the cwd works with Landlock on this Linux | Works, but the mechanism is **bubblewrap, not Landlock**. Codex 0.167.0 refuses the legacy Landlock path for restricted file systems. A root is a `--bind` mount; a missing root is skipped silently. A `.git` inside a root is mounted read-only. | Root `<run-s>/outside`: `WRITE ok <run-s>/outside/w-root`, without it `WRITE fail`. `codex sandbox --enable use_legacy_landlock …`: `panicked … filesystem-restricted execution requires bubblewrap to isolate app-server sockets`. Root `<run-s>/missing-root`: exit 0, nothing created. Root with `git init`: `<root>/.git/f: Read-only file system`. | Holds. The factory must create every root before launch (a missing scratch fails only when a test writes there). Preflight for B2 on Linux is "bwrap usable" (unprivileged user namespaces), not Landlock. |
| 2b | `exclude_slash_tmp` / `exclude_tmpdir_env_var` still honoured with a root set | Yes. With roots set, `/tmp` and a non-root `$TMPDIR` are refused; control without the two keys makes both writable. When `TMPDIR` is itself a root, it is writable. | With keys: `WRITE fail /tmp/runs-probe-2`, `WRITE fail TMPDIR`; without: `WRITE ok /tmp/runs-probe-2`, `WRITE ok TMPDIR`. Agent run: `WRITE ok <run-s>/scratch/w`, `WRITE fail /tmp/runs-agent`. | Holds: keep both keys and make the scratch the `TMPDIR` and a root. |
| 3 | `uv sync --frozen --no-editable --reinstall-package` offline from a prepared cache; `uv tool run` of pinned tools offline | Sync rebuilds the project wheel offline (hatchling 1.33.0 is in the warmed cache). `uv tool run` **fails unless `UV_TOOL_DIR` is writable**: it writes a temporary file and lock in `~/.local/share/uv/tools` even for a cached ephemeral tool. With a per-slot `UV_TOOL_DIR` root, `just check` passes; `just test` passes. | Agent run: `sync exit=0`, `1 passed` (a `tmp_path` test). Without tool dir: `error: Could not create temporary file … Read-only file system (os error 30) at path "~/.local/share/uv/tools/.tmplbNvHa"`, `recipe lint failed`. With it: `Contracts: 8 kept, 0 broken.`, `check exit=0`; `1380 passed in 34.81s`, `test exit=0`. | Change: add `UV_TOOL_DIR` (per slot, made by preparation) as a third writable root beside the per-slot `UV_CACHE_DIR` and the per-attempt scratch. The uv-managed interpreter and mise installs need read only. |
| 4 | mise shims and `just` run without writing outside the roots | They run: `just check`/`just test` through shims succeeded read-only. But **a shim refuses to run in an untrusted directory**, and `codex` itself is a shim. The owner's mise trusts `~/.cache/task-loop` and `~/Workspaces`; the default slots root `~/.local/share/task-loop/slots` is not trusted. | `codex sandbox` from the scratch slot, before setting trust: `mise ERROR Config files in ~/tl-smoke/run-s/slot/mise.toml are not trusted.` (exit 1). With `MISE_TRUSTED_CONFIG_PATHS=<run-s>`: shims ran. | Change (design point): the slots root must be under a trusted mise path, or the factory resolves real tool binaries and does not depend on the slot's `mise.toml`. Trusting the slot means trusting a task-changeable `mise.toml` (its versions and `[env]`); with `UV_OFFLINE`/no network a version the task adds is not installed in the sandbox, so `setup` must install mise tools too. Applies to today's plan step as well if slots move to the default root. |
| 5 | A long scratch path breaks Unix socket paths (108 bytes) | The default-shaped scratch `~/.local/state/task-loop/artifacts/attempts/<64 hex>/tmp` is 123 bytes for this home, over the limit before any file name; pytest adds `pytest-of-<user>/pytest-N/<test>0/`. No test or source here binds a Unix socket (no `AF_UNIX`/`socket` in `src` or `tests`); Python 3.15 `multiprocessing` (forkserver) works with that `TMPDIR` because Linux uses an abstract socket. `.beads` holds no socket. | `bind FAIL 138 AF_UNIX path too long`; with pytest-like suffix 191. `TMPDIR=<long> python mp.py`: `start method forkserver`, `[2, 4]`. | Change: keep the scratch path short (for example a short per-slot directory, not under the attempt's hashed evidence path; aim under ~50 bytes so pytest's suffix fits). Not a blocker for this repository on Linux; a near-certain failure on macOS (file-system forkserver sockets in `$TMPDIR`). |
| 6 | Tests that spawn processes leave descendants outside the agent's process group | Every agent command runs as `bwrap --as-pid-1 --new-session --die-with-parent --unshare-pid --unshare-net …`, so its processes are in a **new session, outside codex's process group**, but inside a PID namespace whose init dies with its parent. `setsid` and `nohup` children were gone when the command ended, and when the codex process group was killed mid-command. | `ps` during a held command: codex pgid 2106211, bwrap pgid/sid 2106257, sleeps in sids 2106260/2106258. After `kill -KILL -- -2106211` (the group of the process this spike started, PID verified): no bwrap, no `codex-linux-sandbox`, no sleep. Agent run: `setsid sleep 4246 &` left no survivor; `ns pid of self=2`. | Holds, by a different mechanism: containment is the PID namespace plus `--die-with-parent`, not the process group. The stop proof's process-group check does not see these processes, but they cannot outlive the codex process group. Side effect: a background process cannot survive between two agent commands. |
| 7 | (control) network and other writes | Network refused; cwd writable; slot `.git` read-only; `~/.cache` and other directories refused. | `Temporary failure in name resolution`; `WRITE ok ./w-cwd`, `WRITE fail .git/runs-probe`, `WRITE fail ~/.cache/runs-probe`. | As designed. |

## Consequences for B2

The proposed shape holds; no redesign before building. Amend the B2 plan with:

1. Writable roots are three, all made by the factory before launch: per-slot `UV_CACHE_DIR`, per-slot `UV_TOOL_DIR`,
   per-attempt scratch (`TMPDIR`). A root that does not exist is dropped by Codex without error.
2. The scratch path is short and outside the hashed attempt evidence path (Unix socket limit; macOS later).
3. Linux preflight is "bubblewrap usable", not Landlock; Codex 0.167.0 has no Landlock fallback for this mode.
4. **Decided by the owner (D14, 2026-11-11):** slots stay under the hidden per-user folder; mise trust is a machine prerequisite, the factory does nothing about it, and a task-changed `mise.toml` is `setup`'s concern. (Original question follows.) mise trust is a precondition of every shim, including `codex` itself: either the slots root lives under a trusted
   path (owner machine config) or the factory launches real binaries. Decide which, and what a task-changed `mise.toml`
   means offline (`setup` installs the tools it names).
5. Process containment for the stop proof comes from bwrap's PID namespace and `--die-with-parent`; record that, since
   the agent's command processes are deliberately outside the codex process group.
6. `setup` warm-up for this repository is `uv sync --frozen --no-editable` plus one `uv tool run` of each pinned tool
   (ruff, pyrefly) and one `uv run --with import-linter==…`, all with the per-slot cache; offline afterwards, `just check`
   and `just test` pass inside the sandbox.

## Not observed

- macOS / Seatbelt: not testable here.
- The slot as a `git worktree` (its `.git` is a file; its Git directory lives in the main repository, outside every root,
  so it is read-only like any other path; not run).
- Killing only the codex PID rather than its process group (whether `codex-linux-sandbox`, in the same group, would
  survive and keep bwrap alive).
- `bd` inside the sandbox, and the "setup inputs changed" key.
- The exact first-time warm-up time on a fast network (here about 40 s for `uv sync`, minutes for the tool downloads).
