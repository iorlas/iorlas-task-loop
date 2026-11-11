# Live smoke: the implement step's environment (S5e) and M1 end to end (owner-run)

**Status: not run.** The S5e part is a checklist (below); the [M1 end-to-end](#m1-end-to-end-smoke-plan-round-advance-implement-owner-run-after-s5c)
part is a full runbook that covers most of it. The owner-run live smoke of [S5e](plan.md) (setup, S5e-1; access, S5e-2), on Linux
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

# M1 end-to-end smoke: plan, round advance, implement (owner-run, after S5c)

**Status: passed 2026-11-11** at `9b8c62367` ([findings](m1-smoke-findings.md)). The [roadmap](../self-hosting-roadmap.md)'s milestone M1 is reached when this run passes: a
`tl step rounds` loop from a runner worktree plans and implements one small task of **this repository** (with a new test
the agent ran offline in its sandbox) on `task/<id>`, without a second claim and without the label after the claim. It
covers the S5e steps above in passing (setup, access, scratch); run them first if anything below fails. Linux only. Run
by Denis, or by an agent Denis authorized for that one run. Scratch remote, scratch tracker and scratch factory.db only:
nothing reaches the real `origin`, the real tracker or `~/.local/state/task-loop`. Never open or paste `auth.json`
(stat it only).

## 0. Runner, layout and machine config

The factory under test **and** the code the task changes are the successor (this branch), not `main`: on `main`
the baseline's `.task-loop.json` (`{"engine": ...}`) is refused `unknown_key`, there is no `just bootstrap` and no
`round_log.py`. So the scratch remote's `main` is set to the successor commit `SHA`, and the slots, the plan and the
implement commit all start from it.

```bash
M1=$HOME/tl-smoke/m1; mkdir -p "$M1" && cd "$M1"
SRC=$HOME/PATH/TO/a-checkout-of-this-repository             # edit: any checkout whose object store holds SHA
SHA=<the S5c repair commit or later on claude/factory-continuation>   # edit: the successor commit under test
G() { git --no-optional-locks -c core.hooksPath=/dev/null "$@"; }
G -C "$SRC" cat-file -e "$SHA^{commit}" && echo "SHA present"
G -C "$SRC" worktree add --detach "$M1/runner" "$SHA"       # the runner: the factory version under test, never edited
mise settings add trusted_config_paths "$M1"                 # before any `just` under $M1 (see the prerequisites)
(cd "$M1/runner" && just install)                            # non-editable wheel in runner/.venv
T() { "$M1/runner/.venv/bin/tl" --config "$M1/config.toml" "$@"; }
G clone -q --bare "$SRC" "$M1/remote.git"                    # scratch origin: the publish goes here only
G -C "$M1/remote.git" update-ref refs/heads/main "$SHA"      # the scratch main is the successor commit
G -C "$M1/remote.git" for-each-ref --format='%(refname)' 'refs/heads/task/*' | while read -r ref; do
  G -C "$M1/remote.git" update-ref -d "$ref"; done           # no stale task/<id> from the source
G clone -q --branch main "$M1/remote.git" "$M1/repo"
G -C "$M1/repo" rev-parse HEAD                               # prints SHA
G -C "$M1/repo" show HEAD:.task-loop.json                    # "setup": [["just", "bootstrap"]], checks check/test
T profile show --checkout "$M1/repo" --at HEAD               # the same profile, no refusal
mkdir -p "$M1/state" "$M1/artifacts" "$M1/slots"
printf 'db = "%s"\nartifacts = "%s"\nslots_root = "%s"\nslot_count = 1\n' \
  "$M1/state/factory.db" "$M1/artifacts" "$M1/slots" > "$M1/config.toml"
T config show                                                # every value under $M1, source `file`
```

Prerequisites this layout meets, each a refusal otherwise:

- **factory.db is schema v11** (S5b). An older factory.db anywhere is refused `refused:schema`; this run uses a fresh
  path. To reuse an older one instead: finish or abandon its attempts (`T step list` shows none `wait`, `start`,
  `verify`, `repeat` or `release`), stop its `tl step rounds`, delete the file and its `-wal`/`-shm`, then adopt again.
- **db and slots_root are not nested** (`environment:roots`): factory.db's folder (`$M1/state`) and the artifacts root
  must not hold the slots root, nor the other way round; the old `~/tl-smoke/config.toml` (db in `~/tl-smoke`, slots in
  `~/tl-smoke/slots`) refuses.
- **`<slots_root>/<repo_id>/.t/<slot>` is at most 64 bytes** (`environment:path_long`): with `$HOME=/home/<u>` and a
  12-hex repo id, `$M1/slots/<id>/.t/s1` is 43 + len(u) bytes (49 for `iorlas`).
- **mise trusts `$M1`** (D14; it holds the runner, the slots and the review worktree, each with this repository's
  `mise.toml`): `mise settings add trusted_config_paths "$M1"` (mise 2026.5.12: appends to `~/.config/mise/config.toml`),
  run before the runner's `just install`, which otherwise fails `not trusted`, so the `codex`, `just` and `uv` shims run there. Check: `(cd "$M1/repo" && just --version)`
  prints no trust error.
- `codex` on `PATH` in the shell that starts the rounds (the entry inherits it); `codex --version`;
  `test -f "${CODEX_HOME:-$HOME/.codex}/auth.json" && echo ok`. `bd` on `PATH`. Network for `setup` (it runs outside
  the sandbox: `just bootstrap` fills the slot's uv cache).

## 1. Slot and tracker

```bash
T slot adopt "$M1/repo"                  # `s1 not_listed <path>` (exit 1): creates factory.db
SLOT=PASTE-the-path-it-printed           # <slots_root>/<repo_id>/s1
mkdir -p "$(dirname "$SLOT")" && G -C "$M1/repo" worktree add --detach "$SLOT"
T slot adopt "$M1/repo"                  # `s1 adopted <path>` (exit 0)
(cd "$SLOT" && codex sandbox -- true; echo "probe exit=$?")   # 0, no mise trust error
mkdir "$M1/tracker" && cd "$M1/tracker" && git init -q && bd init --non-interactive --skip-hooks --skip-agents -p m1 -q
TASK=$(bd create "Test the round log words" --silent)   # `src/taskloop/round_log.py` exists at SHA, without a test
bd update "$TASK" -d "Add tests/steps/test_round_log.py with pytest functions for src/taskloop/round_log.py: \
fixed keeps a valid word and turns an invalid one into 'invalid'; ident does the same for ids; stamped prints the \
UTC time, the backlog and the words. Change no source file." \
  --acceptance "The new test file exists and passes; just check and just test pass."
bd label add "$TASK" auto
T task show "$TASK" --backlog m1 --tracker-root "$M1/tracker"
```

## 2. Rounds (tab A) and observation (tab B)

```bash
# tab A, from $M1 (never from a slot or the main checkout)
T step rounds --backlog m1 --tracker-root "$M1/tracker" --checkout "$M1/repo" --label auto \
  --model <model> --effort <effort> --minutes 90
# tab B
tail -f "$M1/artifacts/rounds.log"
```

1. As soon as `rounds.log` shows `<task> plan start started <a1>`: in tab B, `bd label remove "$TASK" auto` (D3: the
   label is ingestion's only; removing it after the claim must not stop the task). `bd show "$TASK"`: `in_progress`,
   assignee `taskloop`.
2. Expect, in order (other lines between are fine; an identical line is never repeated):
   `<task> plan verify verified release=released branch=published <a1>` (or, if the entry published it first, nothing
   for verify and the next line directly), then `<task> implement advance started <a2>` (and perhaps
   `<task> implement report running <a2>`), then `<task> implement verify verified release=released branch=published
   <a2>` (again absent when the entry published first: `T step show`'s `Last entry result` says `verify=verified ...
   branch=published`), then a quiet loop (`round moves=0` once).
   No `skip claim_lost`, `skip branch_moved` or `advance refused:*` line; no second `bd` claim (`bd show` history).
3. `T step show "$TASK" --backlog m1`: `Step: implement`, `Next: done`, `Setup: run 1 passed at <B>; log ...`
   (`just bootstrap`), `Earlier: <a1> advanced`. `T step list`: one row, `implement ... done`. If setup fails twice
   instead, the row reads `stuck:setup_failed` and rounds stop relaunching it: paste `setup-<run>.log`.
4. Ctrl-C once in tab A: `Rounds stopped: interrupted.`; `rounds.log` ends `rounds stopped interrupted`.

Restart (optional, covers "an intact factory.db continues"): Ctrl-C while the implement agent runs (`implement report running`
in `rounds.log`), then start the same `T step rounds` again: it reports `running` until the entry ends, then
verifies and publishes; no second implement attempt (`T step show` has one `Earlier` line).

## 3. Evidence in Git and the attempt

```bash
G -C "$M1/repo" fetch -q origin "task/$TASK"
G -C "$M1/repo" log --oneline -3 "origin/task/$TASK"     # the implement commit on the plan commit on main
G -C "$M1/repo" show --stat "origin/task/$TASK"          # tests/steps/test_round_log.py; no .beads/, no .git* path
G -C "$SLOT" status --porcelain=v1 --ignored=no          # empty: the slot is clean after the release
ls -A "$(dirname "$SLOT")/.t/s1" 2>/dev/null              # empty or absent: the scratch emptied by the release
```

- The implement answer's `explanation` names `just check` and `just test` and how they ended, and the new test file.
  `T step show` does not print it: read the answer file in the attempt's `Directory:` (the one `T step show` prints).
- The agent's transcript in the attempt folder (`stdout.txt`) shows `just check` and `just test` run and passing. It
  shows `UV_OFFLINE=1` and `TMPDIR` under `.t/s1` only if the agent printed them; otherwise the evidence is the codex
  argv's `shell_environment_policy.set.*` keys (`/proc/<worker pid>/cmdline` while it runs) and the offline runs passing.

## 4. The person's own checks (what M1 still leaves by hand)

```bash
G -C "$M1/repo" worktree add --detach "$M1/review" "origin/task/$TASK"
cd "$M1/review" && just check && just test                # outside any sandbox, as the person
```

Read the diff. Landing stays by hand and is **not** part of this smoke (nothing here pushes to the real `origin`).

## 5. Paste back

`codex --version`; `T config show`; both `T slot adopt`; the probe exit; the whole `rounds.log`; `T step show` and
`T step list`; the three Git commands' output; the explanation and the transcript lines naming `just check`/`just test`;
step 4's last lines. A refusal: the `Stopped:`/`skip` word, `T step show`, and the attempt's `entry.log` last lines.
