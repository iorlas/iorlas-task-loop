# Prepared agent shell environment in both Codex policies

## Problem and decision

At source commit `a66a610b90c09c258e2d9f463111c1c36005bad1`,
`agents.launch.codex_access` supplies `agent_env(found)` only for
`CodexSandbox.WORKSPACE_WRITE`. Its full-access return omits `shell_env`.
The credentials environment is deliberately scrubbed and cannot supply the
prepared slot's paths: it only retains a host `TMPDIR` when one exists.

Pass the same prepared shell environment under both policies. Keep its single
definition in `access.agent_env`: `TMPDIR`, `UV_CACHE_DIR`, `UV_TOOL_DIR`, and
`UV_OFFLINE=1`. The first three point to the existing managed slot folders.
Do not depend on the host exporting any of them.

`UV_OFFLINE=1` does not disable network access for other tools. Full access does
not enforce the implement prompt's current claim that there is no network.
Replace that claim with the common, accurate instruction that setup has run and
uv uses the prepared cache offline. This requires no new policy plumbing into
prompt construction. Preserve the instruction to use the managed `TMPDIR`,
subject to the existing cleanup behavior described below.

## Implementation

1. In `src/taskloop/agents/launch.py`, compute the shell environment from `found`
   once and pass it to both `FactoryCodexAccess` constructions. When `found` is
   absent, keep the empty shell override used for unprepared steps. Preserve
   approval, user-config isolation and output limits. Full access must still
   request neither workspace sandbox settings nor the sandbox probe; retain
   the workspace-write network and writable-root restrictions.
2. Confirm the existing lifecycle rather than adding another folder owner.
   `Preparation._preflight` ensures all three roots;
   `_ready` and `_finish` empty scratch before agent dispatch, including when
   the probe is absent. `SlotRelease._parked` empties scratch after the stop proof
   and release record. `RealEnvFiles.empty_scratch` owns safe physical removal.
   These paths are independent of Codex sandbox policy. Correct only a missing
   connection demonstrated by the regression tests; do not add a full-access
   bypass, another scratch location or cleanup before process liveness is known.
3. In `src/taskloop/implement_step.py`, replace the unconditional network denial
   with the prepared uv-cache/offline statement. Cleanup after release is
   currently best effort, with mandatory emptying before the next agent. Make
   the scratch sentence accurately describe that lifecycle if it continues to
   promise unconditional emptying after every step. Do not claim network
   isolation merely because uv is offline.

## Regression coverage

- Extend `tests/steps/test_agent_launch.py` with a parametrized launch-contract
  test for `WORKSPACE_WRITE` and `DANGER_FULL_ACCESS`. Decode the generated
  `shell_environment_policy.set.*` settings from the actual launch arguments
  and assert the four literal names and their expected values, deriving paths
  from the managed slot layout rather than deriving expectations from
  `agent_env`. Start with credentials that have no temporary or uv variables;
  also cover a conflicting host `TMPDIR` to show the shell override wins.
  Retain assertions that full access has no sandbox probe or workspace-write
  configuration. Unprepared launches must add no managed-folder variables.
- Extend the existing environment tests in `tests/steps/test_environment.py`
  to exercise a prepared full-access implement attempt: all roots are ensured,
  setup scratch is emptied before dispatch, the launch names those same roots,
  and no sandbox probe is called. Preserve setup's online environment.
- Add focused lifecycle coverage using `RealEnvFiles` through the existing
  preparation and release ports, extending the current environment/release
  fixtures where practical. For a full-access attempt, assert its shell's
  `TMPDIR` exists and is empty at dispatch, write a scratch file there, complete
  the stopped attempt's release, and assert the directory remains and is empty.
  Preserve sibling-slot files and the existing symlink-safety and stop-proof
  protections. Use semantic agent/process/Git fakes; no live Codex or direct
  subprocess use. The real-file tests must prove physical cleanup, not merely
  record a callback invocation.
- Update focused implement-prompt coverage for the truthful environment wording.
  Do not introduce a second prompt variant or new vocabulary just to describe
  the shared uv behavior.

## Validation and completion

During implementation, run focused tests for the changed launch, environment,
release and prompt behavior using the declared installed project environment.
Run the required final gates `just check` and `just test` according to the
implement step's supplied command rules. No implementation gates are required
for this plan-only step.

Complete when both prepared Codex policies emit the four shell settings,
full-access scratch creation and cleanup have physical regression evidence,
unprepared steps and sandbox restrictions retain their behavior, and the
implement prompt makes no false network or unconditional cleanup claim.
No dependency changes, credentials expansion, new state, fallback reader or
baseline runtime code is needed.
