# M5 live smoke, B8 part: findings (2026-11-12)

**Result: passed on Linux** (steps 0-7 and 9); **step 8 (macOS) not run** (no Mac available to the agent). Every
expectation of [live-smoke.md](live-smoke.md) held on Linux, after six runbook commands were adjusted (deviations
below). No factory bug was seen: no wrong install, pin, exec, refusal word, exit code, schema answer or written
database. One build-environment surprise (finding 1: installs are built by whatever `uv` the installs root resolves,
here the system uv 0.11.21, not the project's pinned 0.13.0) needs an owner decision. Run by an agent the owner
authorized (agent-run smokes, 2026-11-11); nothing committed or pushed.

## Setup

- **A** = `e6c1a2ab28e08cb76c2a7908779f24fad2f78be7` (the I3 commit), annotated tag `factory-smoke-a` and lightweight
  `smoke-light` in a scratch clone `$M5/src` only. **B** = `755a264ae688c0f0c31d073dc91cae8136e0ad30` (A + one README
  line). **C** = `cdd3a4431aafaaa2d3aaa62624ad94d151d6d668` (B + `version=15` and `CREATE TABLE m5_smoke`).
- `$M5` = `~/tl-smoke/m5`; `$SAVE` in the session scratchpad; runner `$M5/runner` at A (`just install`, 4.5 s);
  scratch remote `$M5/remote.git` (main = A + the smoke profile commit), checkout `$M5/repo`, one slot `s1`, tracker
  `$M5/tracker` (bd, prefix `m5`), schema 14. Profile: M4's `marker` profile (setup `just bootstrap`).
- Host: Linux aarch64 (OrbStack, NixOS userland), user `iorlas` (uid 501, not root), `uv` on PATH as a mise shim
  (`uv --version` 0.13.0 in the repository, 0.11.21 elsewhere: finding 1), no `sqlite3`/`lsof` (factory.db read with
  Python read-only, as M4), bash at `/run/current-system/sw/bin/bash` (rounds started as `bash <script>`, as M4). Codex
  model `gpt-6.1-sol`, effort `low`, `--minutes 20 --every 20`; `auth.json` checked with `test -f` only.
- `~/.local/share/task-loop` did **not exist** before the run: `installs.before` was empty; the person's real
  `~/.config/task-loop/` listing was saved and compared after every pin (unchanged; no `config.pin.toml` written there).
- mise: `trusted_config_paths` gained `$M5` (needed for the runner's `just install`); `~/.local/share/task-loop` was
  not trusted and did not need to be (no `mise.toml` in the installs root's chain). Restored at the end: sha256
  `baf490e4...` before and after.

## Results

| Step | Command | Actual | Result |
|---|---|---|---|
| 0 | layout, tags, B, C, runner | as runbook; no `$IN/<A|B|C>` before; `TL slot adopt`: `s1 not_listed` (exit 1), then `s1 adopted` (exit 0); `user_version` 14 | pass |
| 1 | `TL install factory-smoke-a --checkout $M5/src` | the five lines (`Install: factory-smoke-a = e6c1a2ab... (annotated tag) from $M5/src`, `Export: 311 files to $IN/<A>/source`, `Build: uv --project <A>/source sync --frozen --no-editable --no-dev --reinstall-package iorlas-task-loop (log .../install.log)` + uv's lines, `Verify: running from $IN/<A>/venv`, `Installed: e6c1a2ab28e0 (factory-smoke-a); not pinned (tl pin factory-smoke-a runs it from the next start)`), exit 0, **7.0 s** | pass |
| 1 | `cat $IN/$A/install.toml` | exactly `format = 1`, `commit`, `tag = "factory-smoke-a"`, `installed_at`, `checkout` | pass |
| 1 | install again | `Installed: already e6c1a2ab28e0 (factory-smoke-a) ($IN/<A>)`, exit 0; manifest mtime and sha256 unchanged | pass |
| 1 | `smoke-light` / `main` / `A^{tree}` | `refused not_annotated: tag smoke-light is a lightweight tag; ...`; `refused revision: no tag main in the checkout (a branch or short id is not accepted)`; `refused revision: 1243243... is not a commit in the checkout`; each exit 1; `$IN` holds only A and `A.lock` | pass |
| 1 | `S status`, `rev-parse HEAD`, `for-each-ref` | unchanged by every install | pass |
| 2 | `TL install $B`, Ctrl-C during `Build:` | `^Ctl install: unavailable interrupted: $IN/<B> is left without a manifest. Check that no uv or tl install runs under that path (ps ... grep 755a264ae688), remove the directory, and install again.`, exit 130, no traceback; `$IN/<B>`: `install.log source venv` (no manifest); `ps`: no process names B | pass |
| 2 | install again | `refused incomplete: $IN/<B> has no manifest (an earlier install did not finish). Check ... remove the directory, and install again.`, exit 1; nothing removed | pass |
| 2 | remove, install | `Installed: 755a264ae688; not pinned (tl pin 755a264a...c0f0... runs it from the next start)`, exit 0, 3.4 s | pass |
| 2 | B aside, install, terminal closed during `Build:` | `tl install` ended by SIGHUP (signal 1, no message); **uv survived as an orphan** (`ppid 1`, its own session and group) for under 2 s, then ended by itself (finding 2); then `refused incomplete` (exit 1); removed, B moved back: `Installed: already 755a264ae688 ($IN/<B>)` | pass (recorded) |
| 3 | `TL version` | `Running: unmanaged ($M5/runner/.venv)`, `Pinned: none` | pass |
| 3 | `TL pin factory-smoke-a` | `Pinned: e6c1a2ab28e0 (factory-smoke-a), in $M5/config.pin.toml`, `Was: none`, the drain line ending `If rounds or attempts still run: tl pin --clear back, drain, then make this change again.`; `~/.config/task-loop/` unchanged | pass |
| 3 | `TL version` | `Running: unmanaged (...)`, `Pinned: e6c1a2ab28e0 (factory-smoke-a) since 2026-11-12T05:50:08Z ($M5/config.pin.toml)` | pass |
| 3 | `TL step list` | runs (header only), exit 0 | pass |
| 3 | rounds started, `ps -o pid=,command= -p <r>` | pid written by the script's `bash` (`$$`) = `$IN/<A>/venv/bin/python -I -m taskloop --config $M5/config.toml step rounds ...`: one pid through bash's `exec`, the launcher's exec and the pinned interpreter | pass |
| 3 | `TL pin "$A"` | `Pinned: already e6c1a2ab28e0 (factory-smoke-a), in ...`, exit 0; `SUM -c` OK | pass |
| 4 | P (`m5-lc7`) and rounds | `rounds started every=20 pid=3395385`, `rounds install e6c1a2ab28e0 factory-smoke-a`, `m5-lc7 plan start started` | pass |
| 4 | `TL pin "$B"` while P's plan runs | `Pinned: 755a264ae688, in ...`, `Was: e6c1a2ab28e0 (factory-smoke-a)`, the drain line ending `tl pin factory-smoke-a back, drain, then make this change again.` | pass |
| 4 | `ps` of rounds and entry | rounds 3395385 and entry 3395600 (`taskloop.attempt_entry ... m5 m5-lc7`) both `$IN/<A>/venv/bin/python`; no new `rounds install` line | pass |
| 4 | drain line followed | `TL pin factory-smoke-a` (`Was: 755a264ae688`), SIGINT to the verified rounds pid (`Rounds stopped: interrupted.`, exit 0), `TL step list` until P no longer `running` (`plan ... captured gone collected verified advance`), `TL pin "$B"`, rounds again: `rounds install 755a264ae688` (no tag); rounds pid and P's implement entry both `$IN/<B>/venv/bin/python`; P went implement, check, `collected passed land` under B | pass |
| 5 | `TL install "$C"` | five lines, exit 0, 6.7 s | pass |
| 5 | `TL pin "$C"; TL step list --json` | `{"error": {"kind": "refused", "reason": "schema", "message": "factory is schema v14, this code knows v15: the writer has not upgraded it yet"}}`, exit 1; factory.db digest unchanged | pass (wording: finding 4) |
| 5 | `TL pin factory-smoke-a; TL step list` | P listed, exit 0 | pass |
| 5 | factory.db aside, `TL pin "$C"; TL slot adopt` | `s1 adopted`, exit 0; `user_version` 15; table `m5_smoke` present | pass |
| 5 | `TL pin factory-smoke-a` | only its own three lines, no word about the database (Q13 notice-only) | pass |
| 5 | A on the v15 file: `step list --json`, `step show --json`, `slot adopt --json`, `slot adopt` | each `refused` `schema` "factory is schema v15, this code knows v14: update it", exit 1; `SUM -c v15.sha` OK (nothing written; `-wal` 0 bytes) | pass |
| 5 | restore v14 | `SUM -c v14.sha` OK; `TL step list` under A lists P | pass |
| 6 | missing (`eeee...`) | `tl: refused pin:missing: pinned eeeeeeeeeeee (factory-smoke-a) is not installed under $IN; tl install factory-smoke-a --checkout PATH, or tl pin --clear`, exit 1; `TL version` works; `TL pin --clear`: `Pin cleared (was eeeeeeeeeeee (factory-smoke-a)); tl runs the install it is started from` + drain line (finding 5); again: `Pin cleared: already` | pass |
| 6 | broken (B's `venv/bin/python` moved aside) | `step list`: `refused pin:broken: pinned 755a264ae688 at $IN/<B> is broken ($IN/<B>/venv/bin/python is not an executable file); move it aside and tl install ... or tl pin --clear`; `install`: `refused broken: ... Check that nothing runs from it (ps), move it aside, and install again.`; `pin`: `refused broken`; each exit 1; restored, `step list` works | pass |
| 6 | invalid (`format = 2`) | `refused pin:invalid: the pin file ... is invalid: format is 2, not 1; tl pin REV, or tl pin --clear`, exit 1; `TL version`: `Pinned: invalid ($M5/config.pin.toml)`; `TL pin factory-smoke-a`: `Was: invalid (format is 2, not 1)` and "The earlier pin was invalid: nothing to go back to." | pass |
| 7 | `runner/.venv/bin/python -I -m taskloop ... version` with pin B | `Running: unmanaged ($M5/runner/.venv)`, `Pinned: 755a264ae688 since ...` | pass |
| 7 | P's implement input | contains the exact sentence "`tl` on this machine runs the owner's pinned factory install, never this checkout's code; exercise the code under test through its checks or tests."; `taskloop` 0 times | pass |
| 8 | macOS | not run | **not run** |
| 9 | cleanup | see below | pass |

Extra checks (not in the runbook): `$IN/<A>/venv/bin/tl --config ... version --json` from `/` and `$IN/<B>/venv/bin/python
-I -m taskloop ... version` from `/tmp` both run and name their own install (`Running: e6c1a2ab28e0 (factory-smoke-a)
(...)`, `Running: 755a264ae688 (...)`): the uv environment outside the project works from any working directory
(plan section 20, item 2). Shebang of `$IN/<A>/venv/bin/tl`: `#!/home/iorlas/.local/share/task-loop/installs/<40 hex>/venv/bin/python`, **104 bytes**
(Linux limit 256). `venv/bin/python` is a symlink to uv's minor-version link
`~/.local/share/uv/python/cpython-3.15-linux-aarch64-gnu/bin/python3.15` (CPython 3.15.0b2).

## uv build outcome and timing

Real builds succeeded for A, B (twice) and C. Wall time of `tl install` (start to `Installed:`): A 7.0 s (uv cache
warm; shelf Git dependencies rebuilt), B 3.4 s, C 6.7 s. Export of 311 files was not timed separately: the Ctrl-C test
reached uv's `Building iorlas-task-loop` line 3.0 s after start, so process start, export and venv creation together
took under 3 s (plan section 20, item 1: no shelf `archive` needed). `install.log` ends with the verification answer
(`verify: exit 0: {"running": {"prefix": ".../venv", "install": null, ...}, "pinned": null}`): `install` is null since
the manifest is written after the verification, and `pinned` is null since the verification runs without `--config`
(it reads the default pin path, absent here; read only).

## Findings

1. **The build uses whatever `uv` the installs root resolves (surprise; owner decision).** `pyvenv.cfg` of every
   install says `uv = 0.11.21`; during the hang-up test `ps` showed `/run/current-system/sw/bin/uv` (the Nix system uv).
   The repository pins `uv = "0.13.0"` in `mise.toml`, and the runner's venv was built by 0.13.0, but from
   `~/.local/share/task-loop/installs` the mise shim finds no config that activates uv (`mise which uv`: "uv is a mise
   bin however it is not currently active") and falls through to the next `uv` on PATH. The plan (section 6.1) states
   this as D14 (the person's prerequisite) and checked `--frozen`/`UV_NO_CONFIG` with 0.13.0 only; this run shows a
   different, older uv builds installs silently and the manifest does not record which. It worked here; a `uv.lock`
   that 0.11.21 cannot read would end as `refused build`. Options for the owner: put `uv` in the global mise config (or
   a trusted `~/.local/share/task-loop/mise.toml`), or record the uv version in `install.log` (already there through
   `pyvenv.cfg`) and accept the drift.
2. **SIGHUP: uv survives briefly.** Closing the terminal ended `tl install` by SIGHUP (no message, as designed: no
   unwinding). uv, in its own session (stream_proc `start_new_session`), was seen as an orphan (`ppid 1`, `Ssl`) right
   after and was gone 1 s later, most likely ending on its closed output pipe. The design's assumption ("may run on as
   an orphan") holds; on this host the window was short. `refused incomplete` followed as designed.
3. **Ctrl-C stops uv's tree.** A typed `^C` on the terminal reached only `tl` (uv is in another session); `tl` stopped
   uv's tree itself: no process named B afterwards, exit 130, the right refusal.
4. **Wording (cosmetic): older file under newer code.** "factory is schema v14, this code knows v15: the writer has not
   upgraded it yet" suggests an upgrade will come; there is no migration (the procedure is: move factory.db aside, `tl
   slot adopt`). The word `schema` and exit 1 are right.
5. **Wording (cosmetic): the drain line after clearing a missing pin.** `tl pin --clear` of a pin to `eeee...` tagged
   `factory-smoke-a` says "If rounds or attempts still run: tl pin factory-smoke-a back", which would pin the installed
   A (`e6c1a2ab`), not the cleared commit. Only the tag form is wrong here; the commit form would be refused
   `not_installed`, which is the truth. Also "tl pin --clear back" (when `Was: none`) reads oddly. `tl version` shows a
   missing pin without saying it is missing (by design: no listing in `tl version`).
6. **Mixed versions observed as designed (section 7, row 2).** After `TL pin "$B"` in step 4, the hand `TL step show`
   and `TL step list` ran under B beside A's rounds and entry on the same v14 factory.db; nothing went wrong in this
   short window; the plan does not claim it safe.

## Runbook deviations (commands adjusted; the runbook text is unchanged except its status)

1. **Ctrl-C and the hang-up through a pty driver.** An agent has no interactive terminal: `tl install` ran on a fresh pty
   (Python `pty.fork`); when uv printed `Building iorlas-task-loop`, the driver typed `\x03` (Ctrl-C) or closed the pty
   master and exited (a real terminal hang-up). This is closer to a person's terminal than signals to a pid.
2. **`rm -rf "$IN/$B"`** written as `rm -rf "${IN:?}/${B:?}"` (an empty variable must not expand to `/`); the cleanup
   block already uses `${IN:?}`.
3. **Rounds** run as `bash $M5/rounds.sh` (`echo $$ > rounds.pid; exec tl ... step rounds ... --every 20`), "Ctrl-C" as
   SIGINT to that pid after `ps -o pid=,command=` named `$IN/<A|B>/venv/bin/python -I -m taskloop --config
   $M5/config.toml step rounds` (M4 correction 5).
4. **The scratch remote's `main`** is A plus the smoke profile commit (M4 section 1 commits and pushes the profile), not
   `$A` itself as section 0 says.
5. **Step 7's input file:** `tl step show` does not name the input file; it is `input.txt` in the attempt's
   `Directory:` (`artifacts/attempts/<hash>/input.txt`).
6. **The installs root itself:** `~/.local/share/task-loop/` did not exist before the run; the cleanup block removes
   the smoke's installs and locks but leaves the empty `installs/` and `task-loop/` folders this run made. They were
   removed with `rmdir` (only empty folders, only because `installs.before` was empty and the folder absent). The
   runbook's cleanup could add: when `$IN` did not exist before, `rmdir "$IN" ~/.local/share/task-loop`.

## Not exercised

- **macOS (step 8):** paths, `os.execv` of a uv-managed CPython 3.15 on macOS, `Path.resolve()` of `sys.prefix`
  through `/private`, the macOS shebang length. Plan section 20 items stay unverified there.
- `refused busy` (two concurrent installs of one commit), `refused ambiguous` (a moved tag), `unavailable uv` (no uv on
  PATH), the build timeout, a 64-hex commit id: covered by tests only.
- An installed launcher (`$IN/<A>/venv/bin/tl`) resolving a pin to another install on a resolved command (only its
  exempt `version` ran); the runner launcher's exec was exercised throughout.
- A human Ctrl-C at a real terminal (emulated on a pty, deviation 1). P was not landed (not in the runbook).

## Cleanup

Rounds stopped by SIGINT to the verified pid each time (exit 0, `rounds stopped interrupted`). No process with A, B, C
or `tl-smoke/m5` in its command line before removal. Removed only `$IN/<A>`, `<B>`, `<C>` and their `.lock` files
(none listed in the empty `installs.before`; `diff <(ls "$IN") installs.before`: no difference), then the empty
`installs/` and `task-loop/` folders. Runner worktree removed from the source repository (`worktree remove --force`,
`prune`); `~/tl-smoke/m5` removed (`chmod -R u+rwX` first; other `~/tl-smoke` content untouched); no smoke tag or
branch in the source repository (they lived in the scratch clone); `~/.config/mise/config.toml` restored (sha256
`baf490e4...` equal to before); `~/.config/task-loop/` listing equal to before. Evidence (install outputs, logs,
manifests, rounds.log) was kept in the session scratchpad only.
