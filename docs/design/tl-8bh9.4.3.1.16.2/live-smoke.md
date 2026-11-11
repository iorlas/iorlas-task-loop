# Live smoke: the implement step's environment, S5e (owner-run, placeholder)

**Status: not run.** A placeholder for the owner-run live smoke of [S5e](plan.md) (setup, S5e-1; access, S5e-2), on Linux
only (macOS refuses implement with `environment:platform`). Run by Denis, or by an agent Denis has authorized for that one
run; never on an agent's own initiative. This repository on a scratch tracker, a scratch remote and a scratch
`factory.db`, with the successor executable `$TL/.venv/bin/tl` and a scratch machine config, as the
[registered entry smoke](../tl-8bh9.4.3.1.4/live-smoke.md) sets them up. The full runbook (commands, expected lines,
evidence to paste) is to be written before the run; the steps below are what it must cover.

## Before the run

- The machine config must keep the agent's folders apart from factory.db's folder and the artifacts root (plan section
  6, `environment:roots`): the existing `~/tl-smoke/config.toml` puts `db` in `~/tl-smoke` and `slots_root` at
  `~/tl-smoke/slots`, which refuses. Move `db` (for example `~/tl-smoke/state/factory.db`) or `slots_root` first, or
  decide plan section 18's owner question (a) otherwise.
- `<slots_root>/<repo_id>/.t/<slot>` at most 64 bytes (`environment:path_long`), the slots root trusted by mise (D14), and
  `codex sandbox -- true` run from the slot exits 0 (the probe's backend: bubblewrap with unprivileged user namespaces).

## Steps (plan section 10, with S5e-2's)

1. A plan attempt: its codex argv shows `sandbox_workspace_write.writable_roots=[]`, its environment has no `TMPDIR`,
   `UV_*` from the factory, no `setup_run` row; `tl step show` says `Setup: none`.
2. Implement: preflight passes (the probe included, no `environment:sandbox`); a `setup_run` row `passed` at the plan
   commit; `setup-1.log` shows `just bootstrap`; `tl step show` prints `Setup: run 1 passed at <B>; log ...`.
3. The implement agent's codex argv names exactly `.t/<slot>`, `.env/<slot>/uv-cache`, `.env/<slot>/uv-tools` as
   `writable_roots`, keeps `network_access=false` and both `exclude_*` keys; the transcript shows `just check` and
   `just test` run offline and passing, `TMPDIR` = `.t/<slot>` (at most 64 bytes), `UV_OFFLINE=1`; the agent's input
   carries section 7's words.
4. After the release `.t/<slot>` is empty or gone; the uv folders stay.
5. A relaunch before dispatch reuses the passed run (no new `setup-<n>.log`); a later setup in the slot shows the reset
   (a new `.venv`).
6. A task branch whose `setup` exits 1: two runs, then `refused environment:failed`, no agent tokens, no probe.
7. The person kills a running entry by its recorded pid during setup: `environment:running`, and `tl step release
   --abandon` refusing `setup_running` while the setup lives; once gone, `interrupted` and a new run.
8. No process with its cwd in the slot after the release (`readlink /proc/<pid>/cwd`).
9. (S5e-2) The probe refuses: with a root made unwritable (`chmod 500 .env/<slot>/uv-tools`) the next relaunch says
   `refused environment:sandbox` with nothing run; restore it.
10. (S5e-2 review, unverified) A slot holding an ignored `mise.local.toml` (for example `[env] X = "set"`) while the probe
    runs: the probe runs `codex` through the mise shim with cwd `.t/<slot>`, never the slot, so the file must not be
    evaluated (no `X` in the probe's environment, no mise trust prompt or error naming the slot).
11. (S5e-2 review, unverified) A person's `~/.codex/config.toml` naming a `profile` (or a `shell_environment_policy`)
    that sets another `sandbox_mode` or drops the shell's variables: the probe, which cannot pass `--ignore-user-config`,
    may refuse `environment:sandbox` (a false refusal) while the agent itself would work; record what it says and whether
    `-c` keys beat the profile.
12. (S5e-2 review) The agent's transcript shows `TMPDIR`, `UV_CACHE_DIR`, `UV_TOOL_DIR`, `UV_OFFLINE` in its shell
    although the codex argv's environment has none of them; `.t/<slot>` holds only Codex's
    `codex-bwrap-synthetic-mount-targets-<uid>` during the step.
