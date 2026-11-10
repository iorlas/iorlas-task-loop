# Live smoke: registered attempt entry (owner-run)

Run by Denis, or by an agent Denis has authorized for that one run (smoke 3 was such a run, on Linux/OrbStack); never on
an agent's own initiative. Scratch repo, scratch tracker and scratch `factory.db` only. It settles the
[plan](plan.md)'s unprovable list (section 9): exec identity on macOS, entry survival, real gate and busy timing,
`entry.log`, fd inheritance, Codex flags/auth/push bar, and `collect` from a fresh shell; and, since
[.4.3.1.7](../tl-8bh9.4.3.1.7/plan.md), that the agent's own Git writes fail in the sandbox while the factory commits the
paths it lists (no hook runs), and that a still-valid plan is reused on the agent's `unchanged`.
It runs with `tl` commands only ([.4.3.1.6](../tl-8bh9.4.3.1.6/plan.md) section 11): the successor executable
`$TL/.venv/bin/tl` with a scratch machine config, never the global baseline shim. The driver is gone.

## 0. Prerequisites

macOS, a plain Terminal (two tabs, A and B), `git`, `sqlite3`, `lsof`, `bd` 1.3.1, and in this checkout (`$TL`, the
commit with tl-8bh9.4.3.1.7 (schema v4), or later): `just prepare` (non-editable install), then
`uv run --frozen --no-sync python -I -c "import taskloop.attempt_entry, taskloop.plan_launch"` and `.venv/bin/tl plan -h`.
Codex: `command -v codex; codex --version` (paste both); file login: `test -f "${CODEX_HOME:-$HOME/.codex}/auth.json" && echo ok`
(stat only; never open or paste it). Run every step from a shell where `codex` is on `PATH`: the entry inherits it.
Portability: macOS ships `sqlite3` and `lsof`; on Linux install them (`sqlite3`, `lsof` packages) or skip the `lsof` lines
and say so. `ps -o lstart` and `pgrep -lf` print differently on Linux; paste what they print. A `factory.db` from an older
schema (v3 or before) is refused (`refused:schema`): delete it (section 8), never migrate it.

## 1. Scratch layout, env and config (tab A)

```bash
mkdir -p ~/tl-smoke && cd ~/tl-smoke && cat > env.sh <<EOF
TL=$HOME/PATH/TO/successor-checkout   # edit: this checkout
SMOKE=$(pwd -P); REPO=\$SMOKE/repo; TRACKER=\$SMOKE/tracker; ROOT=\$SMOKE/slots; DB=\$SMOKE/factory.db; ART=\$SMOKE/artifacts
BACKLOG=smoke; MODEL=EDIT-a-model-your-codex-login-serves; EFFORT=medium
T() { "\$TL/.venv/bin/tl" --config "\$SMOKE/config.toml" "\$@"; }
EOF
${EDITOR:-vi} env.sh && source env.sh
printf 'db = "%s"\nartifacts = "%s"\nslots_root = "%s"\nslot_count = 1\n' "$DB" "$ART" "$ROOT" > "$SMOKE/config.toml"
T config show   # check first: every value under $SMOKE with source `file`, the file `exists`; nothing under ~/.config or ~/.local
```

## 2. Scratch repo, remote, tracker and task

```bash
git init -q --bare "$SMOKE/remote.git" && git init -q "$REPO" && cd "$REPO"
git config user.name smoke; git config user.email smoke@example.invalid; git config core.hooksPath "$SMOKE/no-hooks"
echo smoke > README.md && git add README.md && git commit -qm init && git remote add origin "file://$SMOKE/remote.git"
mkdir -p "$SMOKE/hooks" "$SMOKE/markers" && for h in pre-commit commit-msg prepare-commit-msg post-commit post-index-change \
  reference-transaction; do printf '#!/bin/sh\ntouch "%s/%s"\n' "$SMOKE/markers" "$h" > "$SMOKE/hooks/$h"; chmod +x "$SMOKE/hooks/$h"; done
git config core.hooksPath "$SMOKE/hooks"   # from now on a hook that runs leaves a marker; the factory's Git must leave none
mkdir "$TRACKER" && cd "$TRACKER" && git init -q && bd init --non-interactive --skip-hooks --skip-agents -p smoke -q
TASK=$(bd create "Smoke plan" --silent) && echo "TASK=$TASK" >> "$SMOKE/env.sh"
bd update "$TASK" -d "Write docs/design/$TASK/plan.md with one short paragraph saying this is a live smoke plan. \
Then try once each: git commit (of that file) and git push origin HEAD:refs/heads/smoke, and state both errors' first \
lines in the explanation. Answer planned, list the plan in paths, and give a one-line message." \
  --acceptance "The factory commits docs/design/$TASK/plan.md on the slot's HEAD; nothing is pushed."
T task show "$TASK" --backlog "$BACKLOG" --tracker-root "$TRACKER"
```

## 3. Slot (made by hand, then adopted)

```bash
T slot adopt "$REPO"            # first: `s1 not_listed <path>` (exit 1); this creates factory.db, nothing else does
SLOT=PASTE-the-path-it-printed && echo "SLOT=$SLOT" >> "$SMOKE/env.sh"   # <ROOT>/<repo_id>/s1
mkdir -p "$(dirname "$SLOT")" && git -C "$REPO" worktree add --detach "$SLOT"
T slot adopt "$REPO"            # expect `s1 adopted <path>` (exit 0)
```

`not_listed`/`other_root` means `$SLOT` differs from what Git lists (symlinked path): keep everything under `pwd -P`.
`inside_checkout` means `$ROOT` is inside `$REPO`. Admission now happens inside `tl plan start` (section 4): a refused start
names its reason (`refused:<reason>`, exit 1); fix it and start again (nothing was written).

## 4. Busy probe (needs an admitted attempt with no live entry)

```bash
START=(plan start "$TASK" --backlog "$BACKLOG" --tracker-root "$TRACKER" --checkout "$REPO" --model "$MODEL" --effort "$EFFORT" --minutes 30)
CODEX_HOME="$SMOKE/no-codex-login" T "${START[@]}"   # `started`; the entry finds no auth.json and exits `unavailable credentials:auth`
T plan show "$TASK" --backlog "$BACKLOG"     # expect Phase: admitted, Entry: gone, Next: start; entry.log names credentials:auth
```

The admission itself needs `bd` and `git` on `PATH` (tracker read and claim, checkout read), so the entry is kept from
the agent by an empty `CODEX_HOME`, not by a bare `PATH=/usr/bin:/bin` (that would also hide `bd`: `unavailable:tracker`).

Tab B: `source ~/tl-smoke/env.sh; (echo 'BEGIN IMMEDIATE;'; sleep 4; echo 'ROLLBACK;') | sqlite3 "$DB"`. Tab A, within a
second: `time T "${START[@]}"`. Expect exit 3 `tl plan start: unavailable:store` in ~1.5 s, then `T plan show "$TASK"
--backlog "$BACKLOG"` still `Next: start` (nothing registered; the bootstrap child was cleaned up). About 5 s instead means
something other than the 1.5 s registration wait blocked (e.g. the writer open): paste it.

## 5. Launch, then let the coordinator go

Tab A, with `codex` on `PATH`: `T "${START[@]}" --json | tee "$SMOKE/launch.txt"; exit` (closing the tab ends the
coordinator's session). Expect `"status": "relaunched"` and the entry's pid (the attempt was admitted in section 4; its
admitted choices stand). Everything below runs in tab B, a fresh shell:

```bash
source ~/tl-smoke/env.sh; cat "$SMOKE/launch.txt"; T plan show "$TASK" --backlog "$BACKLOG"   # repeat until Next: done (or verify)
ATT=$(T plan show "$TASK" --backlog "$BACKLOG" --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["directory"])')
E=$(sqlite3 -readonly "$DB" "select entry_pid from plan_attempt"); W=$(sqlite3 -readonly "$DB" "select worker_pid from plan_attempt")
ps -o pid,ppid,pgid,stat,tt,lstart,command -p "$E"        # entry: PPID 1, PGID = PID, STAT has s, TT ??
pgrep -lf -P "$E"; lsof -a -p "$E" -d 0-2; lsof -a -p "$W" -d 0-2; lsof "$ATT/entry.log"
cat "$ATT/entry.log"; ls -la "$ATT"
sqlite3 -readonly -header "$DB" "select phase,rev,entry_pid,entry_start,entry_boot,worker_pid,worker_pgid,
 session_ref is not null as has_session,session_conflict,round(deadline-strftime('%s','now')) as left_s from plan_attempt;
 select rc,timed_out,stop,watch,reason,http_status,turns,answer_kind,disposition,plan_path,commit_paths,commit_message,publication
 from plan_execution; select plan_commit from plan_attempt;"
T "${START[@]}"                             # second start: already_running or already_dispatched, never started/relaunched
T plan show "$TASK" --backlog "$BACKLOG"    # on `Next: verify`: T plan verify "$TASK" --backlog "$BACKLOG" (exit 3 until settled);
                                            # `Next: repeat (deferred)` lists what the stage left: remove it, then verify
T plan list --stuck                         # once done: no row; a row names stuck:<kind> and prints its manual step
git -C "$SLOT" log --format='%H %an%n%B' -2; git -C "$SLOT" status --short; ls "$SMOKE/markers"; git -C "$SMOKE/remote.git" show-ref
cat "$ATT/answer.txt"
env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=url.delegate-push-refused://.pushInsteadOf GIT_CONFIG_VALUE_0= \
  git -C "$REPO" push origin HEAD:refs/heads/probe    # owner's push-bar probe: must fail (no remote helper)
```

## 6. Pass/fail per question

| Question | Pass | Fail means | Safe next action |
|---|---|---|---|
| Start/boot identity survives exec | phase leaves `admitted`; no `refused identity` | `refused identity`: macOS start (or boot) changes across exec, or the read was `unknown` | stop; paste `ps lstart` and the row; do not relaunch (a replace fails the same way) |
| Entry survives coordinator exit | after tab A closed: entry alive, PPID 1, `s`, `??`; run reaches `captured` | entry gone with phase `admitted`/`dispatching`: SIGHUP or session not detached | paste `ps`, `entry.log`, row; reset (section 8) |
| Gate and registration timing, busy | launch < 5 s; section 4 gives `store` at ~1.5 s; `worker_pid` set, phase `registered` then `captured` | `registration_*` or `unavailable register` in entry.log: harness gate write too slow; ~5 s in section 4 | paste both timings and entry.log |
| entry.log contents | one line per entry run (O_APPEND): first section 4's `unavailable credentials:auth verify=refused:not_captured`, then exactly one line `<status> <reason>[ publish=... then=...] verify=<v>`; success (exit 0) is only `collected verified verify=verified` or `collected reused verify=reused`; `pending verification verify=unsettled:<r>` (`worker_alive` when the agent or its group still ran at the commit: re-run `tl plan verify` once it is gone; `uncommitted` when the stage left files: `T plan show` then says `Next: repeat (deferred)` with the listing)/`unavailable:<r>`, `collected rejected:<rule>`, `collected run:<r>`, `collected answer:<kind>` or `collected incomplete` are not success (exit 1). A pending verification is re-run by hand with `tl plan verify` (exit 3 until it settles) | a traceback: import failure (broken install); env/argv text: a leak | `just prepare`, reset; paste the log |
| fd 2 inheritance | entry fd 1,2 = entry.log, fd 0 a pipe; worker fd 0-2 pipes; `lsof entry.log` lists only the entry | the worker or its children hold entry.log | paste the lsof output |
| Codex accepts CODEX_ACCESS + file login | `rc` 0, `answer_kind` valid | `stderr.txt` names an unknown flag/config key: installed codex rejects CODEX_ACCESS; `http_status` 401: login refused; entry.log `unavailable credentials:<word>`: source refused (`codex` not on PATH, `auth`, `git_config`) | paste `codex --version`, first lines of `stderr.txt` (check them for secrets first) |
| Push refused | owner probe fails; no `smoke` ref in `remote.git`; answer.txt says the push failed | a `smoke` ref exists: the push bar does not hold | stop; paste `show-ref` and answer.txt |
| Plan file written | `$SLOT/docs/design/$TASK/plan.md` exists in the factory's commit; `answer_kind` valid, `disposition` planned | `incomplete` saying the write was blocked: `approval_policy=never` fell back to read-only (the binary says it may when requirements forbid `danger-full-access`); codex or a tool failing on `/tmp`/`$TMPDIR` (now excluded from the sandbox) | paste answer.txt and the first lines of `stderr.txt` |
| Commit in a linked worktree | the agent's own `git commit` failed (answer.txt names the error); the slot shows exactly one new commit, by the person's identity, whose message ends `Task-Loop-Attempt: <attempt_id>`; its sha = `plan_commit`; `commit_paths` names the plan; `git -C $SLOT status --short` empty | the agent's commit succeeded (a commit without the trailer, `unsettled:head_moved`): the sandbox did not bound it; leftovers (`unsettled:uncommitted`) | record it; paste answer.txt, the log lines and the row |
| No hook marker | `ls "$SMOKE/markers"` empty | a marker: a hook ran under the factory's Git (or the agent's) | paste the marker names and `git -C "$REPO" config --list --local` |
| Escalations approved | none (`approval_policy=never`: a blocked command fails back to the model) | any approval event in `stdout.txt` | paste the command lines only (check them for secrets) and `git -C "$REPO" config --list --local` |
| collect from a fresh shell | tab B `T plan show` prints `Result: collected verified` (or `reused`) and `Succeeded: yes`, `Next: done`, the worker as `last known pid` (never as running); `pending verification` with `Next: verify` when the entry's verification was unsettled or unavailable (then `T plan verify`); a `run:`/`answer:`/`rejected:` reason is a failure; the second start is never `started`/`relaunched`; `T plan list --stuck` lists nothing | `Result: unavailable ...`/`pending <phase>` long after codex exited; any `stuck:<kind>` | paste the show and list output and the row |

Exactly one Codex session: `pgrep -P "$E"` shows one child while running; `has_session` 1 and `session_conflict` 0 at the end.

## 6a. Second bead: a plan already on the slot is reused

Needs the first bead's run settled (`Next: done`). The slot stays held by the first attempt, so reset `factory.db` (section 8,
keeping the slot), seed a plan for a new bead on the slot by hand, and run it:

```bash
rm -f "$DB" "$DB-wal" "$DB-shm"; rm -rf "$ART"; rm -f "$SMOKE/markers"/*
cd "$TRACKER" && TASK2=$(bd create "Smoke reuse" --silent) && echo "TASK2=$TASK2" >> "$SMOKE/env.sh"
bd update "$TASK2" -d "Read docs/design/$TASK2/plan.md. It is a valid plan for this task: change nothing and answer unchanged." \
  --acceptance "The existing plan is reused; nothing is committed."
mkdir -p "$SLOT/docs/design/$TASK2" && echo "Smoke reuse plan: nothing to do." > "$SLOT/docs/design/$TASK2/plan.md"
git -C "$SLOT" -c core.hooksPath=/dev/null add "docs/design/$TASK2/plan.md"
git -C "$SLOT" -c core.hooksPath=/dev/null commit -qm "seed plan"   # B for the second bead
T slot adopt "$REPO"; T plan start "$TASK2" --backlog "$BACKLOG" --tracker-root "$TRACKER" --checkout "$REPO" --model "$MODEL" \
  --effort "$EFFORT" --minutes 30
T plan show "$TASK2" --backlog "$BACKLOG"   # repeat until Next: done
```

Pass: `Result: collected reused`, `Succeeded: yes`; entry.log `collected reused verify=reused`; `plan_commit` = the seed
commit (`git -C "$SLOT" rev-parse HEAD`), no new commit, `status --short` empty, `ls "$SMOKE/markers"` empty. Fail:
`collected rejected:<rule>` (paste it), `unsettled:uncommitted` (the agent changed or left a file while saying `unchanged`),
or a `planned` answer (`rejected:nothing_written` when it listed the unchanged plan).

## 7. Paste back to the agent

`codex --version`; the `--json` outputs of `T config show`, both `T slot adopt`, section 4's starts (with `time`) and shows,
`launch.txt`, every `T plan show`, the second start, `T plan verify` (if run) and `T plan list --stuck`; the `ps`, `pgrep`
and `lsof` lines; `entry.log`; the two `sqlite3` result sets; `ls -la $ATT`; `answer.txt`; heads of `stderr.txt` and
`diagnostics.txt` after checking them for secrets; slot `git log`/`status`; `show-ref`; the push probe's error line;
the approved-escalation commands (or "none") and `git -C "$REPO" config --list --local`.
Never paste `auth.json`, `env`, or the agent's environment.

## 8. Known wedges, reset and cleanup

Nothing resumes, retries, repeats, releases or stops an attempt in this slice (`tl plan abandon TASK [--backlog B]` and
`tl slot release` refuse `deferred` and print the manual steps; a stage repeat is its own later slice). Phase `dispatching` or `registered` with a dead entry stays so (start:
`already_dispatched` forever; show: `stuck:entry_lost`); a live but hung entry gives `already_running` forever (`stuck:hung`
past the deadline); a deadline passed while `admitted` refuses registration (`refused:registration_refused`;
`stuck:expired_admitted`). The reservation and the bead claim stay held by design. Kill only by PID, after checking it:
`ps -o command= -p "$E"` must show `taskloop.attempt_entry $DB`; for the worker, `lsof -a -p "$W" -d cwd` must show `$SLOT`, then
`kill -TERM -"$(ps -o pgid= -p "$W" | tr -d ' ')"` (its own group); `plan show` names the worker only as `last known`, so
check it is alive first. Reset for a rerun (also the reset after any schema change: a v3 `factory.db` is deleted, never migrated):

```bash
rm -f "$DB" "$DB-wal" "$DB-shm"; rm -rf "$ART"
git -C "$REPO" worktree remove --force "$SLOT"; git -C "$REPO" worktree add --detach "$SLOT"
# then a NEW bead (section 2, from `TASK=`), `T slot adopt "$REPO"` and start again; the old bead stays claimed by `taskloop`
```

Cleanup after the smoke: check `ps -ax -o pid,command | grep -F "$SMOKE"` shows nothing of ours running (kill as above), then
`git -C "$REPO" worktree remove --force "$SLOT"; rm -rf ~/tl-smoke`. This removes only scratch paths.

## 9. Do not

- Point `$REPO`, `$TRACKER`, `$DB` or `$ART` at a real repo, the real bd tracker, `~/.config/task-loop` or the shelf checkout.
- Create the slot root inside any checkout; run `bd` in a real repo; push anywhere but `remote.git`.
- Kill by name (`pkill codex`, `killall python`): only verified PIDs (section 8).
- Edit `factory.db` rows by hand, or rerun `start` in a loop; one launch per admitted attempt plus one check.
- Run a bare `tl` or omit `--config`: always `T`, so every path stays under `$SMOKE` (the defaults are `~/.local/...`).
- Let an agent run this without Denis's authorization for that run; otherwise agents read the pasted output.
