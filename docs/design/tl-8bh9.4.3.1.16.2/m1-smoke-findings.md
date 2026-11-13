# M1 end-to-end smoke: findings (2026-11-11)

Status: **evidence**. Dated findings, measurements and their limits, retained with the original commands and
environment. This is not a current setup runbook; use the [README](../../../README.md) for implemented commands.

**Result: passed.** One `tl step rounds` loop planned and implemented task `m1-h1q` of this repository on a scratch
remote, tracker and factory.db, with one claim, the `auto` label removed after the claim, and a new test the agent ran
offline in its sandbox. Run by an agent the owner authorized for this one run ("do it for me"), following
[live-smoke.md](live-smoke.md) "M1 end-to-end smoke". No factory bug found; three runbook corrections (end of file).

## Setup

- Factory and code under test: `9b8c6236757389de049eba366be8a69b35031e15` (S5c review repairs), runner
  `~/tl-smoke/m1/runner` (non-editable wheel), scratch `~/tl-smoke/m1` (state, artifacts, slots, remote.git, repo,
  tracker, review). Nothing pushed anywhere but `~/tl-smoke/m1/remote.git`.
- `codex-cli 0.167.0`, model `gpt-6.1-sol`, effort `medium`, `--minutes 90`; `auth.json` checked with `test -f` only.
  mise `2026.5.12`, Linux arm64 (OrbStack).
- mise trust: `mise settings add trusted_config_paths "$M1"` ran (it appends to `~/.config/mise/config.toml`;
  now `[..., "/home/iorlas/tl-smoke/m1"]`). It must run **before** `just install` in section 0: the first
  `just install` in the runner failed `Config files in ~/tl-smoke/m1/runner/mise.toml are not trusted`.
- `T profile show`: `Setup: just bootstrap`, checks `check`, `test`, required both, target `main`, no refusal.
  `T config show`: every value under `$M1`, source `file`; `round_seconds = 60 (default)`.
- `T slot adopt`: first `s1 not_listed /home/iorlas/tl-smoke/m1/slots/3e088f29047a/s1` (exit 1), after the worktree
  `s1 adopted ...` (exit 0). `.t/s1` path 49 bytes. `codex sandbox -- true` from the slot: exit 0.

## rounds.log (whole)

```
2026-11-11T16:34:27Z m1 rounds started every=60 pid=574790
2026-11-11T16:34:27Z m1 m1-h1q plan start started 534537141e5945f7b08aa28fe6e299eb
2026-11-11T16:34:27Z m1 round moves=1
2026-11-11T16:35:18Z m1 m1-h1q implement advance started a61ae0e9a0c347d6885f99aefdde1331
2026-11-11T16:35:18Z m1 round moves=1 stopped=no_free_slot
2026-11-11T16:36:18Z m1 m1-h1q implement report running a61ae0e9a0c347d6885f99aefdde1331
2026-11-11T16:36:18Z m1 round moves=1 stopped=no_free_slot
2026-11-11T16:36:46Z m1 round moves=0
2026-11-11T16:42:26Z m1 rounds stopped interrupted
```

Neither `plan verify` nor `implement verify` appears: both entries verified and published themselves before the next
round (`Last entry result: collected verified verify=verified claim=held release=released branch=published`). No
`skip claim_lost`, `skip branch_moved` or `advance refused:*`. One SIGINT to the verified rounds pid printed
`Rounds stopped: interrupted. Launched steps keep running; ...`; the process exited 0. Plan took 51 s, implement 87 s
(setup about 25 s of it).

## Tracker

`bd label remove m1-h1q auto` right after `plan start`. `bd show`: `in_progress`, assignee `taskloop`. `bd history`:
one transition to `in_progress` (16:34:27); the second `in_progress` entry (16:34:35) is the label removal. No second
claim. The bd lease reads expired after the run (the claim stays `in_progress` for the person).

## Steps

`T step show m1-h1q --backlog m1` after the run:

```
Step: implement
Attempt: a61ae0e9a0c347d6885f99aefdde1331 (1 of at most 3)
Earlier: 534537141e5945f7b08aa28fe6e299eb advanced
Phase: captured
Result: collected verified
Succeeded: yes
Released: 2026-11-11 16:36:45 UTC, slot parked at 9b8c6236757389de049eba366be8a69b35031e15; claim kept
Published: task/m1-h1q at e5aea8383c6f04a158b4438dda14c4c8eec543e7 on origin, 2026-11-11 16:36:45 UTC
Setup: run 1 passed at 8752330b3e60cfdc341f4c365df57e835cb53e3a; log .../7916e50e.../setup-1.log
Next: done
```

`T step list`: one row `m1-h1q m1 implement 1/3 s1 captured gone collected verified done`.

During the plan attempt: `Setup: none`, `setup_run` had 0 rows, the codex argv carried
`sandbox_workspace_write.writable_roots=[]` and the codex process environment had no `TMPDIR` or `UV_*`.

## Implement environment

- `setup-1.log`: `$ just bootstrap` (uv sync creating `.venv`, ruff, pyrefly, import-linter pins), ends `exit 0`.
- Codex argv: `-s workspace-write --ignore-user-config --ignore-rules`, `network_access=false`,
  `writable_roots=[".t/s1", ".env/s1/uv-cache", ".env/s1/uv-tools"]` (absolute, under the slots root),
  `exclude_slash_tmp=true`, `exclude_tmpdir_env_var=true`, and `shell_environment_policy.set.` keys `TMPDIR`
  (`.t/s1`), `UV_CACHE_DIR`, `UV_TOOL_DIR`, `UV_OFFLINE="1"`. The codex process's own environment
  (`/proc/<pid>/environ`) had no `TMPDIR` or `UV_*`.
- Input carries section 7's words (plus the explanation sentence naming test files).
- Transcript (`stdout.txt`, JSON events), commands in order: read the plan, `.agents/skills/beads/SKILL.md`, glossary,
  justfile, `round_log.py`; `git status --short; ...; bd prime`; `just install` (0); `uv run ... pytest -q
  tests/steps/test_round_log.py` (0, `15 passed`); `just check` (0, `All checks passed!`, `0 errors`, contracts kept);
  `git status --short; git diff --stat` (0); `just test` (0, `1622 passed in 16.14s`). So the agent ran the checks
  and the tests inside the sandbox, without network, and they passed. The transcript does **not** print `TMPDIR` or
  `UV_*` values: the agent never echoed its environment, so item 12's "transcript shows" is unverified as such; the
  evidence is the argv keys above and that offline `uv`/`just` runs succeeded from the setup-filled cache.
- Answer (`answer.txt`): `implemented`, paths `["tests/steps/test_round_log.py"]`, explanation names `just install`,
  the focused pytest run, `just check` passed, `just test` passed (1622), and the new file.

## Git

```
e5aea8383 test: cover round log validation and UTC formatting      (Task-Loop-Attempt: a61ae0e9...)
8752330b3 docs: plan round log word tests                           (docs/design/m1-h1q/plan.md, +50)
9b8c62367 S5c review repairs: advance stop set, stuck:setup_failed, smoke base (tl-8bh9.4.3.1.16.4)
```

`show --stat origin/task/m1-h1q`: only `tests/steps/test_round_log.py | 33 +` (no `.beads/`, no `.git*` path). The
file: pytest functions `test_fixed_preserves_valid_words`, `test_fixed_replaces_invalid_words`,
`test_ident_preserves_valid_identifiers`, `test_ident_replaces_invalid_identifiers`,
`test_stamped_formats_utc_time_backlog_and_ordered_words`, `test_stamped_replaces_an_invalid_backlog` (parametrized,
15 cases). Slot `status --porcelain=v1 --ignored=no`: empty. `.t/s1` after the release: empty (the folder remains);
`.env/s1/uv-cache` and `uv-tools` stay. No process with its cwd under `~/tl-smoke/m1` after the run.

Section 4 by hand, outside any sandbox, in `$M1/review` at `origin/task/m1-h1q`: `just check` ends
`Contracts: 8 kept, 0 broken.`; `just test` ends `1622 passed in 10.73s`.

## Items 10 to 12

- **10 (ignored `mise.local.toml`)**: planted `[env] TL_M1_X = "set"` in the slot, excluded through the repo's
  `.git/info/exclude`, before the rounds. The probe (which runs before the reset, cwd `.t/s1`) passed: no
  `environment:sandbox`, no mise error naming the slot. The probe's own environment is not recorded, so "no `X`" is
  shown only indirectly: `mise env` from `.t/s1` does not export `TL_M1_X`, from the slot it does; the implement codex
  process had no `TL_M1_X`. The reset then removed the file as designed (gone by the time setup ran).
- **11 (user `profile` / `shell_environment_policy`)**: not shown. `~/.codex/config.toml` names only `model`, no
  `profile`, `sandbox_mode` or `shell_environment_policy`; the probe passed. The run did not change the user config.
- **12 (scratch contents)**: `.t/s1` during setup held `codex-bwrap-synthetic-mount-targets-501` (left by the probe's
  `codex sandbox`) **and** `uv-148040bc5d5bd493.lock` (uv's lock from setup, which also gets `TMPDIR`), so "only the
  mount registry" is not exact; both are emptied by the release. Transcript values: see above (not printed).

## Surprising, not a factory bug

- The agent ran `bd prime` inside the sandbox; it created ignored `.beads/embeddeddolt/` and `.beads/backup/` in the
  slot (17:35:55), which survive the release (slot clean by `--ignored=no`) and go at the next reset. It touched no
  real tracker. The repo's agent instructions invite it; harmless here, but it is agent-side tracker tooling running
  in the implement sandbox.
- `tl step rounds` exits 0 after an interrupt.

## Runbook corrections made with this file

1. Section 0: the mise trust command moved before `just install` (otherwise the runner install fails untrusted).
2. Section 2 step 2: `implement verify` (like `plan verify`) is absent when the entry publishes first; an
   `implement report running` line may appear while the agent runs.
3. Section 3: the transcript shows `TMPDIR`/`UV_*` only if the agent prints them; the codex argv's
   `shell_environment_policy.set.*` keys and offline passing runs are the evidence otherwise.
