# Live smoke: registered attempt entry (owner-run)

Run by Denis, or by an agent Denis has authorized for that one run (smoke 3 was such a run, on Linux/OrbStack); never on
an agent's own initiative. Scratch repo, scratch tracker and scratch `factory.db` only. It settles the
[plan](plan.md)'s unprovable list (section 9): exec identity on macOS, entry survival, real gate and busy timing,
`entry.log`, fd inheritance, Codex flags/auth/push bar, and `collect` from a fresh shell; and, since
[.4.3.1.7](../tl-8bh9.4.3.1.7/plan.md), that the factory commits the paths the agent lists (no hook runs), that a
still-valid plan is reused on the agent's `unchanged`, and (Run C, owner-run) that the sandbox refuses a Git write and a
`/tmp` write.

**Status (2026-11-10).** Smoke runs 3 and 4 passed on Linux (OrbStack, aarch64, codex-cli 0.167.0). Not observed yet: the `worker_alive` and `uncommitted` verify states (they appear only when
the worker outlives the run or the agent leaves files; both runs were fast and tidy); the sandbox actually refusing a
Git write or a `/tmp` write (no run attempted one: the factory's prompt forbids Git writes, see Run C); macOS (exec
identity, Seatbelt, `lsof`/`ps` formats).

It runs with `tl` commands only ([.4.3.1.6](../tl-8bh9.4.3.1.6/plan.md) section 11): the successor executable
`$TL/.venv/bin/tl` with a scratch machine config, never the global baseline shim. The driver is gone.

## 0. Prerequisites

macOS, a plain Terminal (two tabs, A and B), `git`, `bd` 1.3.1, `python3`; optionally `sqlite3` and `lsof`; and in this checkout (`$TL`, the
commit with tl-8bh9.4.3.1.7 (schema v4), or later): `just prepare` (non-editable install), then
`uv run --frozen --no-sync python -I -c "import taskloop.attempt_entry, taskloop.plan_launch"` and `.venv/bin/tl plan -h`.
Codex: `command -v codex; codex --version` (paste both); file login: `test -f "${CODEX_HOME:-$HOME/.codex}/auth.json" && echo ok`
(stat only; never open or paste it). Run every step from a shell where `codex` is on `PATH`: the entry inherits it.
Portability: `sqlite3` and `lsof` are optional (macOS ships both; run 4's Linux host had neither). Without `sqlite3`,
every query below runs as `python3 "$SMOKE/q.py" "$DB" "<sql>" ["<sql>" ...]` (a read-only helper written in section 1),
and section 4's lock holder as the Python one-liner given there. Without `lsof`, on Linux: `ls -l /proc/<pid>/fd/0
/proc/<pid>/fd/1 /proc/<pid>/fd/2` for a process's fds, `readlink /proc/<pid>/cwd` for its cwd, and
`ls -l /proc/[0-9]*/fd 2>/dev/null | grep -F "$ATT/entry.log"` for who holds `entry.log`. `ps -o tt` prints `?` for no
terminal on Linux and `??` on macOS; `ps -o lstart` and `pgrep -lf` also print differently; paste what they print. A `factory.db` from an older
schema (v3 or before) is refused (`refused:schema`): delete it (section 8), never migrate it.

## 1. Scratch layout, env and config (tab A)

```bash
mkdir -p ~/tl-smoke && cd ~/tl-smoke && cat > env.sh <<EOF
TL=$HOME/PATH/TO/successor-checkout   # edit: this checkout
SMOKE=$(pwd -P); REPO=\$SMOKE/repo; TRACKER=\$SMOKE/tracker; ROOT=\$SMOKE/slots; DB=\$SMOKE/factory.db; ART=\$SMOKE/artifacts
BACKLOG=smoke; MODEL=EDIT-a-model-your-codex-login-serves; EFFORT=medium
T() { "\$TL/.venv/bin/tl" --config "\$SMOKE/config.toml" "\$@"; }
G() { git --no-optional-locks -c core.hooksPath=/dev/null "\$@"; }   # every owner Git command: no hook, no index write
EOF
cat > q.py <<'EOF'
"""Read-only sqlite query helper for hosts without the sqlite3 CLI: q.py DB SQL [SQL ...]."""
import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
for sql in sys.argv[2:]:
    cur = con.execute(sql)
    print("|".join(d[0] for d in cur.description or ()))
    for row in cur:
        print("|".join(str(v) for v in row))
EOF
${EDITOR:-vi} env.sh && source env.sh
# Every later append names "$SMOKE/env.sh" in full: never `echo ... >> env.sh` with the cwd in $REPO or a slot, which
# leaves a stray env.sh there (an uncommitted leftover the next verify reports, or a file an agent may list).
printf 'db = "%s"\nartifacts = "%s"\nslots_root = "%s"\nslot_count = 1\n' "$DB" "$ART" "$ROOT" > "$SMOKE/config.toml"
T config show   # check first: every value under $SMOKE with source `file`, the file `exists`; nothing under ~/.config or ~/.local
```

## 2. Scratch repo, remote, tracker and task

```bash
git init -q --bare "$SMOKE/remote.git" && git init -q "$REPO" && cd "$REPO"
git config user.name smoke; git config user.email smoke@example.invalid; git config core.hooksPath "$SMOKE/no-hooks"
echo smoke > README.md && git add README.md && git commit -qm init && git remote add origin "file://$SMOKE/remote.git"
mkdir "$TRACKER" && cd "$TRACKER" && git init -q && bd init --non-interactive --skip-hooks --skip-agents -p smoke -q
TASK=$(bd create "Smoke plan" --silent) && echo "TASK=$TASK" >> "$SMOKE/env.sh"
bd update "$TASK" -d "Write docs/design/$TASK/plan.md with one short paragraph saying this is a live smoke plan. \
Answer planned, list the plan in paths, and give a one-line message." \
  --acceptance "The factory commits docs/design/$TASK/plan.md on the slot's HEAD; nothing is pushed."
T task show "$TASK" --backlog "$BACKLOG" --tracker-root "$TRACKER"
```

The bead asks for no Git write: the factory appends fixed closing words to every admitted input
(`plan_admit.task_text`) that forbid `git add`/`commit`/`push`, so a bead asking for them contradicts the prompt and
its result proves nothing. Whether the sandbox refuses a Git write is Run C (section 6b), an owner-run probe.

## 3. Slot (made by hand, then adopted)

```bash
T slot adopt "$REPO"            # first: `s1 not_listed <path>` (exit 1); this creates factory.db, nothing else does
SLOT=PASTE-the-path-it-printed && echo "SLOT=$SLOT" >> "$SMOKE/env.sh"   # <ROOT>/<repo_id>/s1
mkdir -p "$(dirname "$SLOT")" && G -C "$REPO" worktree add --detach "$SLOT"
T slot adopt "$REPO"            # expect `s1 adopted <path>` (exit 0)
# Only now the marker hooks: from here a hook that runs leaves a marker, and the factory's Git must leave none. Every
# owner Git command below goes through G (no hooks, no optional index write), so a marker is never the owner's.
mkdir -p "$SMOKE/hooks" "$SMOKE/markers" && for h in pre-commit commit-msg prepare-commit-msg post-commit post-index-change \
  reference-transaction; do printf '#!/bin/sh\ntouch "%s/%s"\n' "$SMOKE/markers" "$h" > "$SMOKE/hooks/$h"; chmod +x "$SMOKE/hooks/$h"; done
git -C "$REPO" config core.hooksPath "$SMOKE/hooks"; ls "$SMOKE/markers"   # must list nothing before the launch
```

A marker that exists before the launch is the owner's (a plain `git` run after the hooks were set, e.g. `git status`,
which may refresh the index and fire `post-index-change`): note it, `rm "$SMOKE/markers"/*`, and use `G` from then on.

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

Tab B: `source ~/tl-smoke/env.sh; (echo 'BEGIN IMMEDIATE;'; sleep 4; echo 'ROLLBACK;') | sqlite3 "$DB"` (without the CLI:
`python3 -c 'import sqlite3,sys,time; c=sqlite3.connect(sys.argv[1],isolation_level=None); c.execute("BEGIN IMMEDIATE");
time.sleep(4); c.execute("ROLLBACK")' "$DB"`). Tab A, within a
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
# without sqlite3: E=$(python3 "$SMOKE/q.py" "$DB" "select entry_pid from plan_attempt" | tail -1), W likewise
ps -o pid,ppid,pgid,stat,tt,lstart,command -p "$E"        # entry: PPID 1, PGID = PID, STAT has s, TT ?? (macOS) or ? (Linux)
pgrep -lf -P "$E"; lsof -a -p "$E" -d 0-2; lsof -a -p "$W" -d 0-2; lsof "$ATT/entry.log"   # no lsof: /proc, section 0
cat "$ATT/entry.log"; ls -la "$ATT"
sqlite3 -readonly -header "$DB" "select phase,rev,entry_pid,entry_start,entry_boot,worker_pid,worker_pgid,
 session_ref is not null as has_session,session_conflict,round(deadline-strftime('%s','now')) as left_s from plan_attempt;
 select rc,timed_out,stop,watch,reason,http_status,turns,answer_kind,disposition,plan_path,commit_paths,commit_message,publication
 from plan_execution; select plan_commit from plan_attempt;"
T "${START[@]}"                             # second start: already_dispatched while the agent runs (dispatching/registered,
                                            # no entry pid); already_running only while the entry itself still runs before
                                            # dispatch or after capture (verifying); never started/relaunched
T plan show "$TASK" --backlog "$BACKLOG"    # on `Next: verify`: T plan verify "$TASK" --backlog "$BACKLOG" (exit 3 until settled);
                                            # `Next: repeat` lists what the stage left: remove it and verify, or
                                            # re-run the start to repeat the step (section 6c)
T plan list --stuck                         # once done: no row; a row names stuck:<kind> and prints its manual step
ls "$SMOKE/markers"   # first, before any owner Git command
G -C "$SLOT" log --format='%H %an%n%B' -2; G -C "$SLOT" status --short; G -C "$SMOKE/remote.git" show-ref
cat "$ATT/answer.txt"
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=url.delegate-push-refused://.pushInsteadOf GIT_CONFIG_VALUE_0= \
  G -C "$REPO" push origin HEAD:refs/heads/probe    # owner's push-bar probe: must fail (no remote helper)
```

## 6. Pass/fail per question

| Question | Pass | Fail means | Safe next action |
|---|---|---|---|
| Start/boot identity survives exec | phase leaves `admitted`; no `refused identity` | `refused identity`: macOS start (or boot) changes across exec, or the read was `unknown` | stop; paste `ps lstart` and the row; do not relaunch (a replace fails the same way) |
| Entry survives coordinator exit | after tab A closed: entry alive, PPID 1, `s`, `??`; run reaches `captured` | entry gone with phase `admitted`/`dispatching`: SIGHUP or session not detached | paste `ps`, `entry.log`, row; reset (section 8) |
| Gate and registration timing, busy | launch < 5 s; section 4 gives `store` at ~1.5 s; `worker_pid` set, phase `registered` then `captured` | `registration_*` or `unavailable register` in entry.log: harness gate write too slow; ~5 s in section 4 | paste both timings and entry.log |
| entry.log contents | one line per entry run (O_APPEND): first section 4's `unavailable credentials:auth verify=refused:not_captured`, then exactly one line `<status> <reason>[ publish=... then=...] verify=<v>`; success (exit 0) is only `collected verified verify=verified` or `collected reused verify=reused`; `pending verification verify=unsettled:<r>` (`worker_alive` when the agent or its group still ran at the commit: re-run `tl plan verify` once it is gone; `uncommitted` when the stage left files: `T plan show` then says `Next: repeat` with the listing, section 6c)/`unavailable:<r>`, `collected rejected:<rule>`, `collected run:<r>`, `collected answer:<kind>` or `collected incomplete` are not success (exit 1). A pending verification is re-run by hand with `tl plan verify` (exit 3 until it settles) | a traceback: import failure (broken install); env/argv text: a leak | `just prepare`, reset; paste the log |
| fd 2 inheritance | entry fd 1,2 = entry.log, fd 0 a pipe; worker fd 0-2 pipes; `lsof entry.log` lists only the entry | the worker or its children hold entry.log | paste the lsof output |
| Codex accepts CODEX_ACCESS + file login | `rc` 0, `answer_kind` valid | `stderr.txt` names an unknown flag/config key: installed codex rejects CODEX_ACCESS; `http_status` 401: login refused; entry.log `unavailable credentials:<word>`: source refused (`codex` not on PATH, `auth`, `git_config`) | paste `codex --version`, first lines of `stderr.txt` (check them for secrets first) |
| Push refused | owner probe fails; no `smoke` or `probe` ref in `remote.git` | a ref exists: the push bar does not hold | stop; paste `show-ref` |
| Plan file written | `$SLOT/docs/design/$TASK/plan.md` exists in the factory's commit; `answer_kind` valid, `disposition` planned | `incomplete` saying the write was blocked: `approval_policy=never` fell back to read-only (the binary says it may when requirements forbid `danger-full-access`); codex or a tool failing on `/tmp`/`$TMPDIR` (now excluded from the sandbox) | paste answer.txt and the first lines of `stderr.txt` |
| Commit in a linked worktree | the slot shows exactly one new commit, by the person's identity, whose message ends `Task-Loop-Attempt: <attempt_id>`; its sha = `plan_commit`; `commit_paths` names the plan; `G -C $SLOT status --short` empty | the agent's commit succeeded (a commit without the trailer, `unsettled:head_moved`): the sandbox did not bound it; leftovers (`unsettled:uncommitted`) | record it; paste answer.txt, the log lines and the row |
| No hook marker | `ls "$SMOKE/markers"` empty (it was empty before the launch, section 3) | a marker that appeared after the launch: a hook ran under the factory's Git (or the agent's) | paste the marker names and `G -C "$REPO" config --list --local` |
| Escalations approved | none (`approval_policy=never`: a blocked command fails back to the model) | any approval event in `stdout.txt` | paste the command lines only (check them for secrets) and `G -C "$REPO" config --list --local` |
| collect from a fresh shell | tab B `T plan show` prints `Result: collected verified` (or `reused`) and `Succeeded: yes`, `Next: done`, the worker as `last known pid` (never as running); `pending verification` with `Next: verify` when the entry's verification was unsettled or unavailable (then `T plan verify`); a `run:`/`answer:`/`rejected:` reason is a failure; the second start is never `started`/`relaunched`; `T plan list --stuck` lists nothing | `Result: unavailable ...`/`pending <phase>` long after codex exited; any `stuck:<kind>` | paste the show and list output and the row |

Exactly one Codex session: `pgrep -P "$E"` shows one child while running; `has_session` 1 and `session_conflict` 0 at the end.

## 6a. Second bead: a plan already on the slot is reused

Needs the first bead's run (Run A) settled (`Next: done`) and its evidence pasted. The slot stays held by Run A's
attempt, so move Run A's `factory.db` and artifacts aside (kept as evidence, never deleted), keep the slot, seed a plan
for a new bead on the slot by hand, and run it:

```bash
mkdir "$SMOKE/runA" && for f in "$DB" "$DB-wal" "$DB-shm" "$ART" "$SMOKE/markers"; do [ -e "$f" ] && mv "$f" "$SMOKE/runA/"; done
mkdir "$SMOKE/markers"
cd "$TRACKER" && TASK2=$(bd create "Smoke reuse" --silent) && echo "TASK2=$TASK2" >> "$SMOKE/env.sh"
bd update "$TASK2" -d "Read docs/design/$TASK2/plan.md. It is a valid plan for this task: change nothing and answer unchanged." \
  --acceptance "The existing plan is reused; nothing is committed."
mkdir -p "$SLOT/docs/design/$TASK2" && echo "Smoke reuse plan: nothing to do." > "$SLOT/docs/design/$TASK2/plan.md"
G -C "$SLOT" add "docs/design/$TASK2/plan.md"
G -C "$SLOT" commit -qm "seed plan"   # B for the second bead; no hook, so no marker
T slot adopt "$REPO"; T plan start "$TASK2" --backlog "$BACKLOG" --tracker-root "$TRACKER" --checkout "$REPO" --model "$MODEL" \
  --effort "$EFFORT" --minutes 30
T plan show "$TASK2" --backlog "$BACKLOG"   # repeat until Next: done
```

Pass: `Result: collected reused`, `Succeeded: yes`; entry.log `collected reused verify=reused`; `plan_commit` = the seed
commit (`G -C "$SLOT" rev-parse HEAD`), no new commit, `status --short` empty, `ls "$SMOKE/markers"` empty. Fail:
`collected rejected:<rule>` (paste it), `unsettled:uncommitted` (the agent changed or left a file while saying `unchanged`),
or a `planned` answer (`rejected:nothing_written` when it listed the unchanged plan).

## 6b. Run C: sandbox probe (optional, owner-run)

No bead can ask the agent to try a Git write or a `/tmp` write: `plan_admit.task_text` always appends the closing words
that forbid Git writes, and there is no prompt override in the factory. So the sandbox is probed by the owner running the
same codex with the exact access flags the factory passes (`plan.CODEX_ACCESS`, after `-s workspace-write`, as
any_agent's Codex harness builds the argv), in a throwaway worktree (never `$SLOT`), with the push bar's environment:

```bash
G -C "$REPO" worktree add --detach "$SMOKE/probe" && cd "$SMOKE/probe" && rm -f "$SMOKE/markers"/*
eval "ACCESS=($("$TL/.venv/bin/python" -I -c 'import shlex; from taskloop.plan import CODEX_ACCESS; print(shlex.join(CODEX_ACCESS))'))"
printf '%s\n' "${ACCESS[@]}"   # paste: must match plan.py
echo "Run each once and report every command's exit code and first error line: echo x > probe.txt; git add probe.txt; \
git commit -m probe; touch /tmp/tl-smoke-probe; touch \"\${TMPDIR:-/tmp}/tl-smoke-probe2\"; git push origin HEAD:refs/heads/runc" |
  env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=url.delegate-push-refused://.pushInsteadOf GIT_CONFIG_VALUE_0= \
  codex exec -m "$MODEL" -c model_reasoning_effort="\"$EFFORT\"" -s workspace-write "${ACCESS[@]}" --json - > "$SMOKE/runC.jsonl"
ls "$SMOKE/markers"; G -C "$SMOKE/probe" log --oneline -2; G -C "$SMOKE/probe" status --short
ls -l /tmp/tl-smoke-probe "${TMPDIR:-/tmp}/tl-smoke-probe2"; G -C "$SMOKE/remote.git" show-ref
```

Pass: `probe.txt` written (the workspace is writable); `git add`/`git commit` fail (the linked worktree's index and
objects live in `$REPO/.git`, outside the writable root) and the probe worktree's HEAD is unchanged; both `/tmp` files
absent (the `exclude_*` keys hold); no `runc` ref; no approval event in `runC.jsonl`; no marker. Fail: a commit or a
`/tmp` file exists (the sandbox does not bound that write: stop, paste `runC.jsonl` command lines and `codex --version`);
codex rejecting a config key (paste its first error line). This uses the owner's own codex config only through the same
`--ignore-user-config`; it is not the factory path (no entry, no `factory.db`), so it says nothing about the factory's
commit. Cleanup: `G -C "$REPO" worktree remove --force "$SMOKE/probe"; rm -f /tmp/tl-smoke-probe "${TMPDIR:-/tmp}/tl-smoke-probe2"`.

## 6c. Run D: a repeat (optional, owner-run; tl-8bh9.4.3.1.8)

A bead that only MENTIONS scratch notes, so a first answer may leave a stray file without any Git write being asked for;
it never tells the agent to keep the notes, so an agent that follows the repeat's feedback removes them. The factory's
closing words already say "remove any other file you created": a compliant agent may leave nothing to repeat (then Run
D proves nothing: `Next: done` on attempt 1; try once more with a new bead, never edit rows). Move the previous run
aside as in 6a (evidence kept), then:

```bash
mkdir "$SMOKE/runB" && for f in "$DB" "$DB-wal" "$DB-shm" "$ART" "$SMOKE/markers"; do [ -e "$f" ] && mv "$f" "$SMOKE/runB/"; done
mkdir "$SMOKE/markers"
cd "$TRACKER" && TASK3=$(bd create "Smoke repeat" --silent) && echo "TASK3=$TASK3" >> "$SMOKE/env.sh"
bd update "$TASK3" -d "Write docs/design/$TASK3/plan.md with one short paragraph. You may jot scratch notes in \
docs/design/$TASK3/notes.md while you work. Answer planned and list the plan in paths." \
  --acceptance "The plan is committed on the slot."
T slot adopt "$REPO"; S3=(plan start "$TASK3" --backlog "$BACKLOG" --tracker-root "$TRACKER" --checkout "$REPO" \
  --model "$MODEL" --effort "$EFFORT" --minutes 30)
T "${S3[@]}"; T plan show "$TASK3" --backlog "$BACKLOG"   # repeat until Next: repeat (or done: see above)
G -C "$SLOT" diff --cached --name-only    # must be empty: a staged file refuses the repeat (unsettled:staged, nothing spent)
T "${S3[@]}" --json                         # status "repeated", number 2: attempt 1's choices stand
T plan show "$TASK3" --backlog "$BACKLOG"   # Attempt: <id> (2 of at most 3; repeats <id1>, uncommitted); Earlier: <id1> repeated
cat "$(T plan show "$TASK3" --backlog "$BACKLOG" --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["directory"])')/input.txt"
T plan show "$TASK3" --backlog "$BACKLOG"   # repeat until Next: done (or repeat / repeats_exhausted); `Last entry result:`
                                            # says why an admitted attempt's entry gave up (e.g. `refused slot_staged ...`)
G -C "$SLOT" log --format='%H %s%n%b' -3; G -C "$SLOT" status --short; ls "$SMOKE/markers"
```

| What the agent does on a repeat | Result | Meaning |
|---|---|---|
| removes the notes, answers `unchanged` (X1 committed) | `collected verified`, no new commit | pass: the step ends at X1 |
| attempt 1 committed nothing (`unsafe`/`ignored`), lists every file again with `planned` | `collected verified`, one commit | pass |
| lists the notes too, answers `planned` | `collected verified`, X2 on X1 | pass: two commits, each with its own trailer |
| keeps the notes again | `Next: repeat`, then `repeats_exhausted` at attempt 3 | dead end by design: tidy the slot, `tl plan verify` |
| answers `planned` with nothing new | `collected rejected:nothing_written` | terminal: paste its `answer.txt` |
| the owner staged a file | the start refuses `unsettled:staged` (exit 3), nothing admitted | unstage, start again |

Pass: the second start prints `repeated` with number 2 (`number` is null on `started`/`relaunched`/`already_*`);
attempt 2's `input.txt` holds the fixed words, the notes file between `BEGIN SLOT STATUS <nonce>` and `END SLOT STATUS
<nonce>`, the instructions and the task; at most one factory commit per attempt, each with its own `Task-Loop-Attempt:`
trailer; `status --short` empty at the end; no marker. Fail: a second start that relaunched attempt 1, any commit
without a trailer. The exit code of `tl plan start` is 0 for `already_dispatched` even when its `Result:` is
`rejected:<rule>`: read the result word.

## 7. Paste back to the agent

`codex --version`; the `--json` outputs of `T config show`, both `T slot adopt`, section 4's starts (with `time`) and shows,
`launch.txt`, every `T plan show`, the second start, `T plan verify` (if run) and `T plan list --stuck`; the `ps`, `pgrep`
and `lsof` lines; `entry.log`; the two `sqlite3` result sets; `ls -la $ATT`; `answer.txt`; heads of `stderr.txt` and
`diagnostics.txt` after checking them for secrets; slot `git log`/`status`; `show-ref`; the push probe's error line;
the approved-escalation commands (or "none") and `G -C "$REPO" config --list --local`; for Run C, the `ACCESS`
listing, the command lines and exit codes from `runC.jsonl` (checked for secrets) and its `ls`/`log`/`show-ref` output.
Never paste `auth.json`, `env`, or the agent's environment.

## 8. Known wedges, reset and cleanup

Moving a run's files aside (6a, 6c) keeps the slot; a slot or probe directory moved or deleted by hand leaves a stale
`git worktree list` registration in `$REPO`: harmless (`G -C "$REPO" worktree prune` clears it; never prune a live slot).

Nothing resumes, retries, releases or stops an attempt (`tl plan abandon TASK [--backlog B]` and `tl slot release`
refuse `deferred` and print the manual steps); only Git leftovers are repeated, by re-running `tl plan start` (6c). Phase `dispatching` or `registered` with a dead entry stays so (start:
`already_dispatched` forever; show: `stuck:entry_lost`); a live but hung entry gives `already_dispatched` while the
attempt is `dispatching`/`registered` and `already_running` once it is `captured` (`stuck:hung` past the deadline); a deadline passed while `admitted` refuses registration (`refused:registration_refused`;
`stuck:expired_admitted`). The reservation and the bead claim stay held by design. Kill only by PID, after checking it:
`ps -o command= -p "$E"` must show `taskloop.attempt_entry $DB`; for the worker, `lsof -a -p "$W" -d cwd` (Linux without
lsof: `readlink /proc/$W/cwd`) must show `$SLOT`, then
`kill -TERM -"$(ps -o pgid= -p "$W" | tr -d ' ')"` (its own group); `plan show` names the worker only as `last known`, so
check it is alive first. Reset for a rerun (also the reset after any schema change: a v3 `factory.db` is deleted, never migrated):

```bash
rm -f "$DB" "$DB-wal" "$DB-shm"; rm -rf "$ART"   # or move them aside as in section 6a when the run is evidence
G -C "$REPO" worktree remove --force "$SLOT"; G -C "$REPO" worktree add --detach "$SLOT"
# then a NEW bead (section 2, from `TASK=`), `T slot adopt "$REPO"` and start again; the old bead stays claimed by `taskloop`
```

Cleanup after the smoke: check `ps -ax -o pid,command | grep -F "$SMOKE"` shows nothing of ours running (kill as above), then
`G -C "$REPO" worktree remove --force "$SLOT"; rm -rf ~/tl-smoke`. This removes only scratch paths.

## 9. Do not

- Point `$REPO`, `$TRACKER`, `$DB` or `$ART` at a real repo, the real bd tracker, `~/.config/task-loop` or the shelf checkout.
- Create the slot root inside any checkout; run `bd` in a real repo; push anywhere but `remote.git`.
- Kill by name (`pkill codex`, `killall python`): only verified PIDs (section 8).
- Edit `factory.db` rows by hand, or rerun `start` in a loop; one launch per admitted attempt plus one check.
- Run a bare `tl` or omit `--config`: always `T`, so every path stays under `$SMOKE` (the defaults are `~/.local/...`).
- Let an agent run this without Denis's authorization for that run; otherwise agents read the pasted output.
