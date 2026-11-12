# M5 live smoke, B8 part: install, pin and the version a running factory keeps (owner- or authorized-agent-run, after I3)

**Status: not run.** Written with I3 (2026-11-12), from [plan.md](plan.md) section 17.

Milestone M5 of the [roadmap](../self-hosting-roadmap.md), its B8 part: `tl install` builds one immutable install per
commit, `tl pin` chooses one for a machine config, every start of `tl` resolves the pin once (one exec), a running
`tl step rounds` and its entries keep their version until restarted, and a newer or older factory.db stays `refused
schema` (design: [plan.md](plan.md) sections 1-17; as built: section 21). Linux first; steps 1-3 again on macOS (step 8).

Scratch everything except the installs: a scratch clone of this repository (its tags and branches are never pushed to
the real `origin`), a scratch remote, a scratch tracker, a scratch machine config at `$M5/config.toml` (so the pin is
`$M5/config.pin.toml`: the person's real `~/.config/task-loop/config.pin.toml` is never written), schema **v14**, one
slot. Installs go to the real `~/.local/share/task-loop/installs/` (additive: `tl install` never touches another
install); step 0 stops if any of the smoke's commits is already installed, and the cleanup removes only the
directories this run made (ids absent from `$SAVE/installs.before`), after `ps` shows nothing runs from them. Kill nothing by name: every pid is verified first (`ps -o pid=,user=,command= -p <pid>`). Never
open or paste `auth.json`.

Not decided here: **Q9** (dropping the baseline `devbox-ok` acknowledgement and macOS pin restriction) blocks the first
`factory-v*` release, not this smoke; no `factory-v*` tag is made. **Q13** stays proposed and needs the owner's
sign-off; I3 is built per its recommendation (notice-only): `tl pin <older>` onto a newer factory.db writes the pin and
says nothing about the database, and the older code's `refused schema` at its first command is the refusal (step 5).

macOS has no `sha256sum` or GNU `stat`: `SUM` and `MTIME` below pick `shasum -a 256` and `stat -f %m` there.

## 0. Commits, runner, layout and machine config

The layout is the [M4 runbook](../tl-8bh9.14.9/live-smoke.md)'s section 0 (read it and its
[findings](../tl-8bh9.14.9/m4-smoke-findings.md)) with `$M5` and one slot; only the differences are spelled out.

```bash
M5=$HOME/tl-smoke/m5; mkdir -p "$M5" && cd "$M5"
SRC=$HOME/PATH/TO/a-checkout-of-this-repository             # edit; its refs, index and tree are never written (the
                                                             # runner's `worktree add` records the runner in its .git)
A=<the I3 commit, full id>                                   # edit
G() { git --no-optional-locks -c core.hooksPath=/dev/null "$@"; }
S() { G -c user.name=m5 -c user.email=m5@localhost -c commit.gpgsign=false -c tag.gpgSign=false -C "$M5/src" "$@"; }
SUM() { if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }
MTIME() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1"; }
SAVE=<a folder outside $M5 that outlives it>                 # edit
mkdir -p "$SAVE"
if test -f ~/.config/mise/config.toml; then SUM ~/.config/mise/config.toml | tee "$SAVE/mise.before"
  cp -p ~/.config/mise/config.toml "$SAVE/mise.config.toml.orig"; else echo "no mise config" | tee "$SAVE/mise.before"; fi
mise settings add trusted_config_paths "$M5"
mise settings get trusted_config_paths                       # record: is ~/.local/share/task-loop trusted (D14)?
IN=~/.local/share/task-loop/installs
ls "$IN" 2>/dev/null | tee "$SAVE/installs.before"           # none of these is ever touched or removed
G clone -q "$SRC" "$M5/src"                                  # the scratch source: tags and branches made here only
S tag -a factory-smoke-a -m "m5 smoke A" "$A"                # annotated, local to the scratch clone
S tag smoke-light "$A"                                       # lightweight
S switch -q -c smoke-b "$A" && echo "m5 smoke B" >> "$M5/src/README.md" \
  && S commit -qam "m5 smoke B: harmless" && B=$(S rev-parse HEAD)
S switch -q -c smoke-c "$B" && python3 - "$M5/src/src/taskloop/factory_schema.py" <<'EOF'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); s = p.read_text()
assert s.count("version=14,") == 1
p.write_text(s.replace("version=14,", "version=15,").replace('ddl="""\n', 'ddl="""\nCREATE TABLE m5_smoke (id INTEGER PRIMARY KEY);\n', 1))
EOF
S commit -qam "m5 smoke C: schema v15" && C=$(S rev-parse HEAD)
printf 'A=%s\nB=%s\nC=%s\n' "$A" "$B" "$C" | tee "$M5/commits" "$SAVE/m5-commits"
for id in "$A" "$B" "$C"; do test -e "$IN/$id" && echo "STOP: $IN/$id exists before the smoke; do not run"; done
G -C "$SRC" worktree add --detach "$M5/runner" "$A"          # the launcher: a runner at A, never edited
(cd "$M5/runner" && just install)
TL() { "$M5/runner/.venv/bin/tl" --config "$M5/config.toml" "$@"; }
```

Then the scratch remote, the person's checkout `$M5/repo`, `$M5/state`, `$M5/artifacts`, `$M5/slots`, the config
(`slot_count = 1`), `DB`, `RUN` (backlog `m5`) and `SHOW` exactly as M4 section 0, and the profile, the one slot and
the tracker as M4 section 1 (one slot, the `marker` profile or a simpler one; `DB 'pragma user_version'`: 14). The
scratch remote's `main` is `$A`.

## 1. Install A by its tag; the refusals of a revision

```bash
TL install factory-smoke-a --checkout "$M5/src"
```

- Five lines (plan section 6.1): `Install: factory-smoke-a = <A> (annotated tag) from $M5/src`, `Export: <n> files to
  $IN/<A>/source`, `Build: uv --project <A>/source sync --frozen --no-editable --no-dev --reinstall-package
  iorlas-task-loop (log .../install.log)` followed by uv's lines, `Verify: running from $IN/<A>/venv`, `Installed:
  <A12> (factory-smoke-a); not pinned (tl pin factory-smoke-a runs it from the next start)`. Exit 0. Record the time.
- `cat "$IN/$A/install.toml"`: exactly `format`, `commit`, `tag`, `installed_at`, `checkout`.
- `TL install factory-smoke-a --checkout "$M5/src"` again: `Installed: already <A12> (factory-smoke-a) (...)`,
  exit 0, nothing written (`MTIME "$IN/$A/install.toml"` unchanged).
- `TL install smoke-light --checkout "$M5/src"`: `refused not_annotated`; `TL install main --checkout "$M5/src"`:
  `refused revision`; `TL install "$(G -C "$M5/src" rev-parse "$A^{tree}")" --checkout "$M5/src"`: `refused revision`.
  Each exit 1, nothing new under `$IN` but A.
- `S status --porcelain=v1` and `S rev-parse HEAD`: unchanged by every install.

## 2. Interrupted installs

```bash
TL install "$B" --checkout "$M5/src"      # press Ctrl-C once while `Build:` streams uv's lines
```

- `tl install: unavailable interrupted: ...` (exit 130), the detail says `$IN/<B>` is left without a manifest and how
  to check and remove it; no traceback. `ls "$IN/$B"`: no `install.toml`. `ps -o pid=,ppid=,command= -u "$USER" | grep
  "$B"`: no uv left.
- `TL install "$B" --checkout "$M5/src"`: `refused incomplete` naming `$IN/<B>` (exit 1); nothing removed.
- Remove it by hand (`rm -rf "$IN/$B"`, after the `ps` above), install again: `Installed: <B12>; not pinned ...`.

Then the hang-up: move B aside (`mv "$IN/$B" "$SAVE/B.complete"`), start `TL install "$B" --checkout "$M5/src"` in a
second terminal and close that terminal during `Build:` (SIGHUP). Record whether uv survives (`ps -o pid=,ppid=,command=
-u "$USER" | grep "$B"`, every pid verified); wait until no such process remains, then `TL install "$B" ...`: `refused
incomplete`; remove the directory, `mv "$SAVE/B.complete" "$IN/$B"` (or install again), `TL install "$B" ...`:
`already`.

## 3. Unpinned, then pinned: one resolution per start

```bash
TL version
TL pin factory-smoke-a
TL version
TL step list
```

- First `TL version`: `Running: unmanaged ($M5/runner/.venv)`, `Pinned: none`.
- `TL pin factory-smoke-a`: `Pinned: <A12> (factory-smoke-a), in $M5/config.pin.toml`, `Was: none`, then the drain
  line (`Takes effect at the next start of tl; ... Drain before pinning: ... If rounds or attempts still run: tl pin
  --clear back, drain, then make this change again.`). `ls ~/.config/task-loop/`: no `config.pin.toml` written by this run.
- Second `TL version`: still `Running: unmanaged (...)` (`version` is exempt: it describes the launcher), `Pinned: <A12>
  (factory-smoke-a) since <time> ($M5/config.pin.toml)`.
- `TL step list` runs. While a resolved command runs (start `RUN auto` in its own tab), `ps -o pid=,command= -p <pid of
  that TL step rounds>` (verified) shows `$IN/<A>/venv/bin/python -I -m taskloop --config $M5/config.toml step rounds
  ...`: one process, the launcher replaced by the exec (same pid). Stop it (Ctrl-C).
- `TL pin "$A"`: `Pinned: already <A12> (factory-smoke-a), in ...`, the file unchanged (`SUM`).

## 4. A pin change while rounds of A run (the mistake the drain line corrects)

The procedure is drain, then pin, then start (plan sections 7 and 10). This step pins **before** draining on purpose,
to see that the running rounds keep A, then follows the drain line's way back.

```bash
T P "M5 file" "$(FILE P)" auto        # the M4 tiny-task text; sets $P
RUN auto                              # tab A; `tail -f "$M5/artifacts/rounds.log"` in tab B
```

- `rounds.log`: `rounds started every=... pid=<r>`, then `rounds install <A12> factory-smoke-a` (log words, no
  parentheses).
- While P's plan agent runs: `TL pin "$B"`: `Pinned: <B12>, in ...`, `Was: <A12> (factory-smoke-a)`, the drain line
  ending `If rounds or attempts still run: tl pin factory-smoke-a back, drain, then make this change again.`
- The rounds' and the entry's command lines (`ps -o pid=,command= -p <r>` and the entry pid from `SHOW "$P"`, verified)
  still name `$IN/<A>/venv/bin/python`; no new `rounds install` line.
- Follow the drain line: `TL pin factory-smoke-a` (back; `Was: <B12>`), Ctrl-C the rounds (exit 0), wait until `TL
  step list` (A's code again) shows nothing running for `"$P"`, then `TL pin "$B"` and `RUN auto`: `rounds install
  <B12>` (no tag). P finishes under B (`ps` of its next entry names `$IN/<B>/venv/bin/python`).

## 5. Schema: a newer code, then a rollback onto a newer factory.db

```bash
TL install "$C" --checkout "$M5/src"
# drain (step 4), then:
TL pin "$C"; TL step list --json                       # refused schema: a v14 file met by v15 code
TL pin factory-smoke-a; TL step list                   # rollback with a compatible factory.db: works
SUM "$M5/state/factory.db" > "$SAVE/v14.sha"
mkdir "$M5/state.v14" && mv "$M5/state/factory.db"* "$M5/state.v14/"   # the person moves factory.db aside
TL pin "$C"; TL slot adopt "$M5/repo"; DB 'pragma user_version'          # to verify: s1 adopted, exit 0; 15
SUM "$M5/state/factory.db" > "$SAVE/v15.sha"
TL pin factory-smoke-a                                  # written: not a word about the database
TL step list --json; TL step show "$P" --backlog m5 --json; TL slot adopt "$M5/repo" --json
SUM -c "$SAVE/v15.sha"                                  # OK: nothing written
mkdir "$M5/state.v15" && mv "$M5/state/factory.db"* "$M5/state.v15/" && mv "$M5/state.v14/"* "$M5/state/"
SUM -c "$SAVE/v14.sha"; TL step list                    # the v14 file restored; A runs on it
```

- v15 code on the v14 file: `{"error": {"kind": "refused", "reason": "schema", ...}}`, exit 1.
- A on the v15 file: every command `refused schema`, its message saying this code knows v14 and the file is v15
  ("update it"), exit 1, `slot adopt` included; `tl pin` printed only its own lines (Q13 as proposed: notice-only, no
  database read).

## 6. Missing, broken and invalid pins

```bash
cp -p "$M5/config.pin.toml" "$SAVE/pin.good"
python3 - "$M5/config.pin.toml" <<'EOF'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); p.write_text(p.read_text().replace(p.read_text().split('"')[1], "e" * 40, 1))
EOF
TL step list; TL version; TL pin --clear; cp -p "$SAVE/pin.good" "$M5/config.pin.toml"
```

- `TL step list`: `tl: refused pin:missing: pinned eeeeeeeeeeee (factory-smoke-a) is not installed under $IN; tl
  install factory-smoke-a --checkout PATH, or tl pin --clear` (exit 1); `TL version` and `TL pin --clear` still work
  (`Pin cleared (was eeeeeeeeeeee (factory-smoke-a)); ...` and the drain line).
- Broken: `TL pin "$B"`, `mv "$IN/$B/venv/bin/python" "$SAVE/python.B"`: `TL step list` is `refused pin:broken` naming
  the path, `TL install "$B" --checkout "$M5/src"` is `refused broken`, `TL pin "$B"` is `refused broken`; move it back.
- Invalid: `printf 'format = 2\n' > "$M5/config.pin.toml"`: `TL step list` is `refused pin:invalid`; `TL version` says
  `Pinned: invalid ($M5/config.pin.toml)`; `TL pin factory-smoke-a`: `Was: invalid (format is 2, not 1)`.
- Ambiguous needs a moved tag: not made here (tests cover it).

## 7. Development bypass and agents

- `"$M5/runner/.venv/bin/python" -I -m taskloop --config "$M5/config.toml" version` with a pin set: `Running:
  unmanaged ($M5/runner/.venv)`, `Pinned: <the pin>`: `python -I -m taskloop` never resolves.
- The implement input of P (`SHOW "$P"` names its input file) contains the sentence "`tl` on this machine runs the
  owner's pinned factory install, never this checkout's code; exercise the code under test through its checks or
  tests." and no `taskloop`.

## 8. macOS

Steps 0 (runner, scratch clone and commits only), 1 and 3 on a Mac: the same paths (`~/.local/share/task-loop/installs`,
`$M5/config.pin.toml`), the exec into a uv-managed CPython (`ps` of a resolved `TL step rounds`, as step 3), and
`Path.resolve()` of `sys.prefix` through `/private`: the install's own launcher, `"$IN/$A/venv/bin/tl" --config
"$M5/config.toml" version`, says `Running: <A12> (factory-smoke-a) (...)`. Record the shebang length of `$IN/<A>/venv/bin/tl`
(`head -1 "$IN/$A/venv/bin/tl" | wc -c`).

## 9. Paste back and cleanup

The output of every step, `rounds.log`, `install.log` of each install, `cat` of each manifest and pin file, the `ps`
lines. Record findings in `docs/design/tl-8bh9.8.3/m5-smoke-findings.md` (the plan's section 20 items: export time,
uv's environment outside the project, SIGHUP survival, shebang length, macOS exec).

Then: stop rounds (verified pid); confirm no process runs from `$IN/<A>`, `<B>` or `<C>` (`ps -o pid=,command= -u
"$USER" | grep -e "$A" -e "$B" -e "$C"`); remove only what this run made, never a name listed in
`$SAVE/installs.before`:

```bash
for id in "$A" "$B" "$C"; do for name in "$id" "$id.lock"; do
  grep -qxF "$name" "$SAVE/installs.before" && echo "kept $name (existed before)" && continue
  test -e "$IN/$name" && rm -rf "${IN:?}/$name"; done; done
diff <(ls "$IN") "$SAVE/installs.before"                     # no difference
```

`G -C "$SRC" worktree remove --force "$M5/runner"` and `G -C "$SRC" worktree prune`; `chmod -R u+rwX "$M5" && rm -rf
"$M5"` (the scratch clone, its tags and branches with it); restore `~/.config/mise/config.toml` from `$SAVE` (when it
existed) and compare `SUM` with `$SAVE/mise.before`; `ls ~/.config/task-loop/` shows no file this run made.
