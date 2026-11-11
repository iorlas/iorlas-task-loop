# Live smoke: registered attempt entry (owner-run)

Run by Denis, or by an agent Denis has authorized for that one run (smoke 3 was such a run, on Linux/OrbStack); never on
an agent's own initiative. Scratch repo, scratch tracker and scratch `factory.db` only. It settles the
[plan](plan.md)'s unprovable list (section 9): exec identity on macOS, entry survival, real gate and busy timing,
`entry.log`, fd inheritance, Codex flags/auth/push bar, and `collect` from a fresh shell; and, since
[.4.3.1.7](../tl-8bh9.4.3.1.7/plan.md), that the factory commits the paths the agent lists (no hook runs), that a
still-valid plan is reused on the agent's `unchanged`, and (Run C, owner-run) that the sandbox refuses a Git write and a
`/tmp` write; and, since [.4.3.1.11](../tl-8bh9.4.3.1.11/plan.md), that a step's slot is released and an abandoned task
starts again (Run E, owner-run, not yet run); and, since [.4.3.1.12](../tl-8bh9.4.3.1.12/plan.md), that a verified plan
is published to `origin` (the scratch `remote.git` only), retried by `tl plan publish`, and never forced (Run F,
owner-run); and, since [.4.3.1.13](../tl-8bh9.4.3.1.13/plan.md), that a scheduling round (`tl plan next`) takes approved
ready tasks into the free slot in priority order, never re-admits an abandoned task, and relaunches an entry that exited
before the agent ran (Run G, owner-run); and, since [.4.3.1.14](../tl-8bh9.4.3.1.14/plan.md), that `tl plan rounds` takes
a new task within one interval, fills a freed slot within seconds, stays silent while idle, refuses a second rounds
process for the backlog, and stops gracefully on one Ctrl-C and at once on two without stopping a launched step (Run H,
owner-run, not yet run).

**Status (2026-11-10).** Smoke runs 3 and 4 passed on Linux (OrbStack, aarch64, codex-cli 0.167.0). Not observed yet: the `worker_alive` and `uncommitted` verify states (they appear only when
the worker outlives the run or the agent leaves files; both runs were fast and tidy); the sandbox actually refusing a
Git write or a `/tmp` write (no run attempted one: the factory's prompt forbids Git writes, see Run C); macOS (exec
identity, Seatbelt, `lsof`/`ps` formats).

It runs with `tl` commands only ([.4.3.1.6](../tl-8bh9.4.3.1.6/plan.md) section 11): the successor executable
`$TL/.venv/bin/tl` with a scratch machine config, never the global baseline shim. The driver is gone.

## 0. Prerequisites

macOS, a plain Terminal (two tabs, A and B), `git`, `bd` 1.3.1, `python3`; optionally `sqlite3` and `lsof`; and in this checkout (`$TL`, the
commit with tl-8bh9.4.3.1.7 (schema v4), or later): `just install` (non-editable install), then
`uv run --frozen --no-sync python -I -c "import taskloop.attempt_entry, taskloop.launch"` and `.venv/bin/tl plan -h`.
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
  --acceptance "The factory commits docs/design/$TASK/plan.md on task/$TASK and publishes task/$TASK to origin (the scratch remote.git)."
T task show "$TASK" --backlog "$BACKLOG" --tracker-root "$TRACKER"
```

The bead asks for no Git write: the factory appends fixed closing words to every admitted input
(`admit.task_text`) that forbid `git add`/`commit`/`push`, so a bead asking for them contradicts the prompt and
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
E=$(sqlite3 -readonly "$DB" "select entry_pid from attempt"); W=$(sqlite3 -readonly "$DB" "select worker_pid from attempt")
# without sqlite3: E=$(python3 "$SMOKE/q.py" "$DB" "select entry_pid from attempt" | tail -1), W likewise
ps -o pid,ppid,pgid,stat,tt,lstart,command -p "$E"        # entry: PPID 1, PGID = PID, STAT has s, TT ?? (macOS) or ? (Linux)
pgrep -lf -P "$E"; lsof -a -p "$E" -d 0-2; lsof -a -p "$W" -d 0-2; lsof "$ATT/entry.log"   # no lsof: /proc, section 0
cat "$ATT/entry.log"; ls -la "$ATT"
sqlite3 -readonly -header "$DB" "select phase,rev,entry_pid,entry_start,entry_boot,worker_pid,worker_pgid,
 session_ref is not null as has_session,session_conflict,round(deadline-strftime('%s','now')) as left_s from attempt;
 select rc,timed_out,stop,watch,reason,http_status,turns,answer_kind,disposition,effect,commit_paths,commit_message,session_state
 from execution; select end_commit from attempt;"
T "${START[@]}"                             # second start: already_dispatched while the agent runs (dispatching/registered,
                                            # no entry pid); already_running only while the entry itself still runs before
                                            # dispatch or after capture (verifying); never started/relaunched
T plan show "$TASK" --backlog "$BACKLOG"    # on `Next: verify`: T plan verify "$TASK" --backlog "$BACKLOG" (exit 3 until settled);
                                            # `Next: repeat` lists what the step left: remove it and verify, or
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
| entry.log contents | one line per entry run (O_APPEND): first section 4's `unavailable credentials:auth verify=refused:not_captured`, then exactly one line `<status> <reason>[ publish=... then=...] verify=<v> claim=<w>[ release=<w>][ branch=<w>]` (`release=` only once the result is collected: `released` when the slot was clean (`already_released` when a person's verify/release or a round recorded it first), else `held:<reason>`; `branch=` only for a verified plan, after the slot lock is released: `published` (`already_published` when a person's publish or a round recorded it first), or `refused:<r>`/`unavailable:<r>`, then `T plan publish` retries; `publish=` is a different fact, the capture retry's acceptance of the evidence, facts and session state); success (exit 0) is only `collected verified verify=verified ...` or `collected reused verify=reused ...`; `pending verification verify=unsettled:<r>` (`worker_alive` when the agent or its group still ran at the commit: re-run `tl plan verify` once it is gone; `uncommitted` when the step left files: `T plan show` then says `Next: repeat` with the listing, section 6c)/`unavailable:<r>`, `collected rejected:<rule>`, `collected run:<r>`, `collected answer:<kind>` or `collected incomplete` are not success (exit 1). A pending verification is re-run by hand with `tl plan verify` (exit 3 until it settles) | a traceback: import failure (broken install); env/argv text: a leak | `just install`, reset; paste the log |
| fd 2 inheritance | entry fd 1,2 = entry.log, fd 0 a pipe; worker fd 0-2 pipes; `lsof entry.log` lists only the entry | the worker or its children hold entry.log | paste the lsof output |
| Codex accepts CODEX_ACCESS + file login | `rc` 0, `answer_kind` valid | `stderr.txt` names an unknown flag/config key: installed codex rejects CODEX_ACCESS; `http_status` 401: login refused; entry.log `unavailable credentials:<word>`: source refused (`codex` not on PATH, `auth`, `git_config`) | paste `codex --version`, first lines of `stderr.txt` (check them for secrets first) |
| Push refused | owner probe fails; no `smoke` or `probe` ref in `remote.git` (since .12 the `refs/heads/task/*` refs there are the factory's own publication, not the agent's) | a `smoke` or `probe` ref exists: the push bar does not hold | stop; paste `show-ref` |
| Plan file written | `$SLOT/docs/design/$TASK/plan.md` exists in the factory's commit; `answer_kind` valid, `disposition` planned | `incomplete` saying the write was blocked: `approval_policy=never` fell back to read-only (the binary says it may when requirements forbid `danger-full-access`); codex or a tool failing on `/tmp`/`$TMPDIR` (now excluded from the sandbox) | paste answer.txt and the first lines of `stderr.txt` |
| Commit in a linked worktree | the slot, on `task/$TASK` (`G -C $SLOT branch --show-current`), shows exactly one new commit, by the person's identity, whose message ends `Task-Loop-Attempt: <attempt_id>`; its sha = `end_commit`; `commit_paths` names the plan; `G -C $SLOT status --short` empty | the agent's commit succeeded (a commit without the trailer, `unsettled:head_moved`): the sandbox did not bound it; leftovers (`unsettled:uncommitted`) | record it; paste answer.txt, the log lines and the row |
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
G -C "$SLOT" rev-parse --abbrev-ref HEAD   # HEAD: Run A's entry released the slot, parked at D (task/$TASK keeps X)
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

Pass: `Result: collected reused`, `Succeeded: yes`; entry.log `collected reused verify=reused`; `end_commit` = the seed
commit (`G -C "$SLOT" rev-parse HEAD` in the slot before the run), no new commit, `task/$TASK2` at it, the slot parked
detached at that commit after the release (slice .11), `status --short` empty,
`ls "$SMOKE/markers"` empty. Fail:
`collected rejected:<rule>` (paste it), `unsettled:uncommitted` (the agent changed or left a file while saying `unchanged`),
or a `planned` answer (`rejected:nothing_written` when it listed the unchanged plan).

## 6b. Run C: sandbox probe (optional, owner-run)

No bead can ask the agent to try a Git write or a `/tmp` write: `admit.task_text` always appends the closing words
that forbid Git writes, and there is no prompt override in the factory. So the sandbox is probed by the owner running the
same codex with the exact access flags the factory passes (`attempt.CODEX_ACCESS`, after `-s workspace-write`, as
any_agent's Codex harness builds the argv), in a throwaway worktree (never `$SLOT`), with the push bar's environment:

```bash
G -C "$REPO" worktree add --detach "$SMOKE/probe" && cd "$SMOKE/probe" && rm -f "$SMOKE/markers"/*
eval "ACCESS=($("$TL/.venv/bin/python" -I -c 'import shlex; from taskloop.attempt import CODEX_ACCESS; print(shlex.join(CODEX_ACCESS))'))"
printf '%s\n' "${ACCESS[@]}"   # paste: must match attempt.py
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
G -C "$SLOT" rev-parse --abbrev-ref HEAD   # HEAD (released, parked at D); a slot left held: tidy, then `T plan release`
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

## 6d. Run E: release and abandon, then start again (optional, owner-run; tl-8bh9.4.3.1.11)

Release is automatic when a step ends on a clean slot: the entry parks the slot back at its admission base D (detached)
and keeps the tracker claim (`release=released`). `tl plan release` frees a slot left held once the person tidied it;
`--abandon` also returns the claim and lets `tl plan start` admit a fresh attempt. Move the previous run aside as in 6a
(evidence kept; a factory.db from before schema v9 is refused `schema` and must be moved aside), then:

```bash
mkdir "$SMOKE/runD" && for f in "$DB" "$DB-wal" "$DB-shm" "$ART" "$SMOKE/markers"; do [ -e "$f" ] && mv "$f" "$SMOKE/runD/"; done
mkdir "$SMOKE/markers"
G -C "$SLOT" rev-parse --abbrev-ref HEAD   # must print HEAD (detached); `G -C "$SLOT" switch -q --detach` if a v6 run left it on a branch
cd "$TRACKER" && TASK4=$(bd create "Smoke release" --silent) && echo "TASK4=$TASK4" >> "$SMOKE/env.sh"
bd update "$TASK4" -d "Write docs/design/$TASK4/plan.md with one short paragraph. Answer planned and list the plan in paths." \
  --acceptance "The plan is committed on the task branch."
T slot adopt "$REPO"; S4=(plan start "$TASK4" --backlog "$BACKLOG" --tracker-root "$TRACKER" --checkout "$REPO" \
  --model "$MODEL" --effort "$EFFORT" --minutes 30)
T "${S4[@]}"; T plan show "$TASK4" --backlog "$BACKLOG"   # repeat until Next: done; `Last entry result:` ends release=released branch=published
T plan show "$TASK4" --backlog "$BACKLOG"   # Released: <time>, slot parked at <D>; claim kept
G -C "$SLOT" rev-parse --abbrev-ref HEAD; G -C "$SLOT" rev-parse HEAD; G -C "$REPO" rev-parse "task/$TASK4"   # HEAD, D, X
T plan release "$TASK4" --backlog "$BACKLOG" --json   # already_released, nothing changed (exit 0)
T "${S4[@]}"                                          # already_dispatched, Result: verified; nothing launched
(cd "$TRACKER" && bd show "$TASK4")   # still claimed: assignee taskloop, in_progress
T plan release "$TASK4" --backlog "$BACKLOG" --abandon --json   # released, claim "unclaimed", abandoned (no Git write)
(cd "$TRACKER" && bd show "$TASK4")   # the claim returned: no longer assigned to taskloop
T plan show "$TASK4" --backlog "$BACKLOG"   # Next: start; Released: ...; claim unclaimed; abandoned
T "${S4[@]}"; T plan show "$TASK4" --backlog "$BACKLOG"   # started: a fresh attempt (1 of at most 3); Earlier: <id> abandoned
# the fresh attempt resumes task/$TASK4 at X: the agent reads the committed plan and should answer unchanged (`reused`)
T plan list                                 # one row for $TASK4: the fresh attempt
G -C "$SLOT" status --short; ls "$SMOKE/markers"
```

Optional, the held case (smoke 5 showed the simple form does not reach it): a stray file written while the agent runs
gives `unsettled:uncommitted`, `Next: repeat`, and `T plan release` refuses `not_terminal`; the repeat feedback then makes
the agent delete the listed file, so a held slot belongs to the factory and nobody leaves their own files in it.
`release=held:slot_dirty` needs a file that appears after verification but before the release, or a failed final result
that left files behind: entry.log ends `release=held:slot_dirty`, `T plan show` says `Next: release`, `T plan release`
refuses `slot_dirty` with the listing (exit 1, nothing changed); remove the file and `T plan release` parks it.
Note: `s1.lock` keeps the last holder's record (dead pid) after release; it is informational only.

| Check | Pass | Fail means |
|---|---|---|
| automatic release | entry.log `... claim=held release=released`; slot detached at D; `task/$TASK4` at X; `bd show` still `taskloop` | `release=held:<w>` on a clean slot, or the claim returned |
| second release | `already_released`, exit 0, no Git or bd call | anything changed |
| abandon | `"claim": "unclaimed"`, `"abandoned": true`; bd assignee cleared | `unavailable:tracker` (bd failed; rerun), `not_held` (reverted or another actor's: check `bd show`) |
| start while the claim is still returning | after an `unavailable:tracker` abandon, `T "${S4[@]}"` refuses `release` and show says `Next: release` | a fresh attempt admitted before the claim was returned |
| start again | `started` with a new attempt id; `Earlier: <id> abandoned`; the agent starts on `task/$TASK4` at X | `already_dispatched`, `task_attempted`, or `refused:branch_diverged` (see `.11` section 5) |

## 6e. Run F: publication, a failed publish and its retry, a diverged remote (optional, owner-run; tl-8bh9.4.3.1.12)

A verified plan is pushed to `origin`'s `task/<id>` by the entry once, after its release and outside the slot lock,
never forced, as the person (the shell that ran `tl plan start` supplies the credentials; `remote.git` needs none).
`tl plan publish` is the retry. Pushes run with hooks off, so no `pre-push` hook runs (git-lfs's neither). The push
uploads every ancestor of X that `remote.git` lacks: `$REPO`'s unpushed `main` commit (section 2 never pushes it) goes
to `remote.git` under `task/<id>`; that is expected here, and is why a real repository's base should hold no unpublished
work. Only a `Pushed` result is recorded: a remote that already holds X plus later commits is `refused:remote_ahead`.
Move the previous run's files aside into a new directory (a v7 factory.db is refused `schema`; a reused scratch home
may already hold `runE` or older task variables, so the directory and the variables below are new names), then:

```bash
ASIDE="$SMOKE/before-runF-$(date +%Y%m%d%H%M%S)" && mkdir "$ASIDE" \
  && for f in "$DB" "$DB-wal" "$DB-shm" "$ART" "$SMOKE/markers"; do [ -e "$f" ] && mv "$f" "$ASIDE/"; done
mkdir "$SMOKE/markers"
cd "$TRACKER" && PUB_BASE=$(bd create "Smoke publish baseline" --silent) && PUB_RETRY=$(bd create "Smoke publish retry" --silent) \
  && PUB_DIVERGED=$(bd create "Smoke publish diverged" --silent) \
  && printf 'PUB_BASE=%s\nPUB_RETRY=%s\nPUB_DIVERGED=%s\n' "$PUB_BASE" "$PUB_RETRY" "$PUB_DIVERGED" >> "$SMOKE/env.sh"
for t in "$PUB_BASE" "$PUB_RETRY" "$PUB_DIVERGED"; do bd update "$t" -d "Write docs/design/$t/plan.md with one short paragraph. \
Answer planned and list the plan in paths." --acceptance "The plan is committed on task/$t and published to origin."; done
T slot adopt "$REPO"
start() { T plan start "$1" --backlog "$BACKLOG" --tracker-root "$TRACKER" --checkout "$REPO" --model "$MODEL" --effort "$EFFORT" --minutes 30; }
# F0, the baseline: the entry publishes on its own
start "$PUB_BASE"; T plan show "$PUB_BASE" --backlog "$BACKLOG"   # repeat until: ... release=released branch=published; Next: done
sqlite3 -readonly "$DB" "SELECT end_commit FROM attempt WHERE task_id='$PUB_BASE'"   # X
G -C "$SMOKE/remote.git" rev-parse "task/$PUB_BASE"        # the same X
# F1, a publish that fails, then the retry: origin pointed at a missing path for the run
G -C "$REPO" remote set-url origin "file://$SMOKE/missing.git"
start "$PUB_RETRY"; T plan show "$PUB_RETRY" --backlog "$BACKLOG"   # until: ... release=released branch=unavailable:remote; Next: publish
G -C "$REPO" remote set-url origin "file://$SMOKE/remote.git"
T plan publish "$PUB_RETRY" --backlog "$BACKLOG" --json      # published; commit == remote_head
G -C "$SMOKE/remote.git" show-ref; G -C "$REPO" rev-parse "task/$PUB_RETRY" "refs/remotes/origin/task/$PUB_RETRY"   # all X
G -C "$REPO" remote set-url origin "file://$SMOKE/missing.git"
T plan publish "$PUB_RETRY" --backlog "$BACKLOG" --json      # already_published, exit 0: no network was needed
G -C "$REPO" remote set-url origin "file://$SMOKE/remote.git"
# F2, a remote branch someone else made: a scratch clone pushes an unrelated task/$PUB_DIVERGED first
git clone -q "$SMOKE/remote.git" "$SMOKE/other" && cd "$SMOKE/other" && git switch -q --orphan "task/$PUB_DIVERGED" \
  && git -c user.name=o -c user.email=o@example.invalid commit -q --allow-empty -m other && git push -q origin "task/$PUB_DIVERGED" \
  && cd "$SMOKE"
start "$PUB_DIVERGED"; T plan show "$PUB_DIVERGED" --backlog "$BACKLOG"   # until: ... branch=refused:remote_moved; Next: publish
G -C "$SMOKE/remote.git" rev-parse "task/$PUB_DIVERGED"    # still the other clone's commit: nothing forced
G -C "$REPO" fetch -q origin "task/$PUB_DIVERGED"; T plan publish "$PUB_DIVERGED" --backlog "$BACKLOG"   # refused diverged, exit 1
ls "$SMOKE/markers"   # empty: no hook ran
```

| Check | Pass | Fail means |
|---|---|---|
| F0 baseline | entry.log `... release=released branch=published`; `T plan show` has `Published: task/$PUB_BASE at X on origin, <UTC>` and `Next: done`; `remote.git`'s `task/$PUB_BASE` == the attempt's `end_commit` | another word; a different sha on the remote |
| F1 failure | `branch=unavailable:remote`, `Next: publish`, the slot released, no `task/$PUB_RETRY` in `remote.git` | `branch=published` against a missing path; the release waited on the push |
| F1 retry | `published`; `remote.git`, local branch and tracking ref all at X | a different sha anywhere; a `+` (forced) update |
| already published | `already_published` with origin unreachable | any Git error (it touched the network) |
| F2 | `remote_moved`, then `diverged` after the fetch; `remote.git` keeps the other commit | the remote ref changed |
| agent push | still no `smoke`/`probe` ref | the push bar does not hold |

`Next: publish` after a refusal. The factory stores only a successful publication, so after `refused:remote_moved`,
`refused:diverged` or `refused:remote_ahead` `tl plan show` still says `Next: publish` with the generic guide (the last
word is only in the entry log's `branch=` and in the last `tl plan publish` output, neither a control input). The guide
says that after those three words rerunning does not help: fetch `task/<id>`, compare it with the verified commit, then
merge or move one branch aside by hand; then `tl plan publish` again.

**Observed (smoke 6, Linux/OrbStack, real Codex, 2026-11-10).** F0 baseline: `branch=published`, the `Published:` line,
the remote ref at `end_commit`; F1: `branch=unavailable:remote`, then `published`, then `already_published` with origin
unreachable; F2: `branch=refused:remote_moved`, then `refused:diverged` after the fetch, `remote.git` unchanged; no
marker. Not observed yet: `tl plan verify`'s `Publish:` line; `refused:remote_ahead`, `unavailable:changed`,
`refused:no_remote`, `refused:branch_moved`, `refused:remote_rejected`, `unavailable:git`; a real SSH/HTTPS
authentication failure; an abandon after a publication; macOS.

Cleanup: `rm -rf "$SMOKE/other"` with the rest of `~/tl-smoke`. Section 9 is unchanged: push nowhere but `remote.git`.

## 6f. Run G: scheduling rounds, `tl plan next` (optional, owner-run; tl-8bh9.4.3.1.13)

One round settles the backlog's existing attempts (relaunch an admitted attempt whose entry is not running, verify,
repeat; report the rest), starts approved (`--label auto`) ready tasks in priority order into free slots, then publishes
verified plans. It keeps no state; each round appends one line per move to `$ART/rounds.log`, never read back. With
`slot_count = 1` as configured, each round admits at most one task. Move the previous run aside as Run F does (a new
timestamped directory, `$SMOKE/markers` recreated), then:

```bash
ASIDE="$SMOKE/before-runG-$(date +%Y%m%d%H%M%S)" && mkdir "$ASIDE" \
  && for f in "$DB" "$DB-wal" "$DB-shm" "$ART" "$SMOKE/markers"; do [ -e "$f" ] && mv "$f" "$ASIDE/"; done
mkdir "$SMOKE/markers"
cd "$TRACKER"
G_PARENT=$(bd create "Smoke urgent group" -t epic -p 0 --silent)             # not approved: never planned itself
G_TOP=$(bd create "Smoke P1" -p 1 -l auto --silent)
G_LOW=$(bd create "Smoke P2 alone" -p 2 -l auto --silent)
G_CHILD=$(bd create "Smoke P2 under P0" -p 2 -l auto --parent "$G_PARENT" --silent)
# G3 pre-check: by natural id alone $G_LOW must come first, so only the P0 parent can put $G_CHILD ahead of it
"$TL/.venv/bin/python" -I -c 'import sys; from taskloop.selection import natural as n; sys.exit(n(sys.argv[1]) >= n(sys.argv[2]))' \
  "$G_LOW" "$G_CHILD" && echo "G3 can prove ancestry" || echo "G3 INCONCLUSIVE: $G_LOW sorts after $G_CHILD by id; redo Run G"
G_OFF=$(bd create "Smoke P0 unapproved" -p 0 --silent)                       # no label: never taken
G_WAIT=$(bd create "Smoke P0 blocked" -p 0 -l auto --deps "blocked-by:$G_LOW" --silent)
printf 'G_PARENT=%s\nG_TOP=%s\nG_CHILD=%s\nG_LOW=%s\nG_OFF=%s\nG_WAIT=%s\n' "$G_PARENT" "$G_TOP" "$G_CHILD" "$G_LOW" \
  "$G_OFF" "$G_WAIT" >> "$SMOKE/env.sh"
for t in "$G_TOP" "$G_CHILD" "$G_LOW" "$G_OFF" "$G_WAIT"; do bd update "$t" -d "Write docs/design/$t/plan.md with one short \
paragraph. Answer planned and list the plan in paths." --acceptance "The plan is committed on task/$t and published to origin."; done
T slot adopt "$REPO"
NEXT=(plan next --backlog "$BACKLOG" --tracker-root "$TRACKER" --checkout "$REPO" --label auto --model "$MODEL" --effort "$EFFORT" --minutes 30)
T "${NEXT[@]}" --json        # G1: one move, start $G_TOP started; "stopped": "no_free_slot" ($G_CHILD hit it: no move for
                             #     it, never claimed); nothing else claimed (bd show each)
T "${NEXT[@]}"               # G2, at once: report $G_TOP running; stopped no_free_slot (no move for $G_CHILD); no second entry (ps)
T plan show "$G_TOP" --backlog "$BACKLOG"   # repeat until Next: done (released, published)
T "${NEXT[@]}"               # G3: start $G_CHILD (P2 under a P0 parent beats P2 alone, though $G_LOW's id sorts first);
                             #     stopped no_free_slot, no move for $G_LOW
T plan show "$G_CHILD" --backlog "$BACKLOG" # until Next: done
T "${NEXT[@]}"               # G4: start $G_LOW; no candidate left, so stopped is empty ("stopped": null in JSON, no
                             #     `Stopped:` line); $G_WAIT stays blocked while $G_LOW is open
T plan show "$G_LOW" --backlog "$BACKLOG"   # until Next: done
T plan release "$G_LOW" --backlog "$BACKLOG" --abandon   # G5: abandon a finished attempt; $G_LOW is open again
bd ready -l auto             # lists only $G_LOW (open, unassigned); $G_WAIT is absent: blocked by the open $G_LOW
T "${NEXT[@]}"               # G5: skip $G_LOW abandoned; nothing started; $G_OFF and $G_WAIT never appear
# G6, an entry that exits before the agent: no Codex login for that one round's entry
G_RELAUNCH=$(cd "$TRACKER" && bd create "Smoke relaunch" -p 1 -l auto --silent) && echo "G_RELAUNCH=$G_RELAUNCH" >> "$SMOKE/env.sh"
CODEX_HOME="$SMOKE/no-codex-login" T "${NEXT[@]}"   # start $G_RELAUNCH started; its entry exits `unavailable credentials:auth`
T plan show "$G_RELAUNCH" --backlog "$BACKLOG"      # Phase: admitted, Entry: gone, Next: start
T "${NEXT[@]}"               # relaunch $G_RELAUNCH relaunched (same attempt); the step then runs to Next: done
cat "$ART/rounds.log"        # one line per move of every round above, fixed words, the relaunch naming the attempt
ls "$SMOKE/markers"          # empty: no hook ran
```

| Check | Pass | Fail means |
|---|---|---|
| G1 order | `$G_TOP` first; only it claimed (`bd show`: others open, unassigned) | another task first; a claim on a task left unadmitted |
| G2 idempotent | `report running`, no new entry, no new attempt row | a second launch or admission |
| G3 hierarchy | the pre-check printed `G3 can prove ancestry`, and `$G_CHILD` started before `$G_LOW` | `$G_LOW` first (ancestry ignored); an `INCONCLUSIVE` pre-check proves nothing either way |
| G5 abandon | `skip abandoned`; no new attempt for `$G_LOW` | the round admitted it again |
| approval, blockers | `$G_OFF`, `$G_PARENT` and `$G_WAIT` never in any move | an unapproved or blocked task taken |
| publication | each finished task published to `remote.git` (Run F rules) | a forced or missing push |
| G6 relaunch | first round: `start started`, entry.log `unavailable credentials:auth`; second: `relaunch relaunched` on the same attempt id, then `Next: done`; `rounds.log` holds both rounds | no relaunch; a second attempt row; anything but fixed words in `rounds.log` |

G6 stands in for a reboot or network loss mid-start: the entry is gone while the attempt is `admitted`, which is what the
round decides on. Not covered live: a real reboot, `refused slot_busy` and `refused claim_lost` (tests cover the rule).
An admitted attempt past its deadline (`stuck:expired_admitted`) is only reported by rounds: abandon it, then
`tl plan start`. The exception is an entry registered before a reboot (.4.3.1.14 section 16): see the reboot check at the
end of Run H. Exit codes: 0 for a round whose words are all settled (a per-task
refusal included), 3 when admission stopped on, or a move says, `unavailable:*`, `uncertain:*`, `unsettled:*` or
`unknown` (a verify's `branch=` word and `skip unavailable:ancestry` included; rerun), 1 for a refused round (`label`,
`tracker_root`, `database`) or one stopped on its own refused inputs. A `report claim_leaked` move names a task whose
claim a failed start could not return: `bd unclaim <task> --if-assignee taskloop` by hand.

**Observed (smoke 7, Linux/OrbStack, real Codex, 2026-11-10).** Run G passed: G1 to G6 as written, every move in
`rounds.log` in fixed words, no marker. Real `bd ready` rows carry `parent`, and an ancestor outside the ready set
(the unapproved epic) resolves through `bd show`. Findings fixed in this runbook afterwards: G3 as first written could not
prove the parent tie-break (natural id gave the same order; now the pre-check above), `bd ready -l auto` lists only
`$G_LOW` (G5), and a round with no candidate left has an empty `stopped` (G4). Not observed live yet: a real reboot or
network loss mid-start, `refused slot_busy`, `refused claim_lost`, `stuck:expired_admitted` reached by a round,
`report claim_leaked`, `skip unavailable:ancestry`, a round's `verify` or `repeat` move, a publication refused or
retried by a round, two concurrent rounds, macOS.

**Not run yet.**

## 6g. Run H: rounds by themselves, `tl plan rounds` (optional, owner-run; tl-8bh9.4.3.1.14)

`tl plan rounds` runs rounds one after another in the foreground of the terminal it was started in until Ctrl-C: a round
at once, then a regular round every `--every` seconds (machine config `round_seconds`, default 60, at least 5) and a
round within about 2 s of a slot's reservation row being removed. Admission reads the tracker only when factory.db has an
adopted slot without a reservation row. It writes only `$ART/rounds.log` (a move identical to the previous round's is not
written again; an idle round writes nothing) and one start line and one end line in its terminal. First Ctrl-C: no further
move, `rounds stopped interrupted`, exit 0. Second Ctrl-C: `Stopped at once.`, exit 130. Launched steps keep running
either way (their own session). Start it from the shell where `bd`, `git push` and `codex` work: entries inherit its
environment. It keeps the code it started with: after reinstalling, restart it; never run the gates in `$TL` while it
runs from there. `slot_count = 1`; move the previous run aside as Run G does, then tab B runs the rounds and tab A the rest:

```bash
ASIDE="$SMOKE/before-runH-$(date +%Y%m%d%H%M%S)" && mkdir "$ASIDE" \
  && for f in "$DB" "$DB-wal" "$DB-shm" "$ART" "$SMOKE/markers"; do [ -e "$f" ] && mv "$f" "$ASIDE/"; done
mkdir "$SMOKE/markers"
T slot adopt "$REPO"
ROUNDS=(plan rounds --backlog "$BACKLOG" --tracker-root "$TRACKER" --checkout "$REPO" --label auto --model "$MODEL" \
  --effort "$EFFORT" --minutes 30)
# tab B: a long interval, so a start seconds after a slot frees can only be the wake
T "${ROUNDS[@]}" --every 120          # H1: start line; rounds.log: rounds started every=120, then the first round
# tab A
H_ONE=$(cd "$TRACKER" && bd create "Smoke rounds one" -p 1 -l auto --silent)
H_TWO=$(cd "$TRACKER" && bd create "Smoke rounds two" -p 2 -l auto --silent)
H_LONG=$(cd "$TRACKER" && bd create "Smoke rounds long" -p 3 -l auto --silent)   # a longer step, for H7 to H10
printf 'H_ONE=%s\nH_TWO=%s\nH_LONG=%s\n' "$H_ONE" "$H_TWO" "$H_LONG" >> "$SMOKE/env.sh"
for t in "$H_ONE" "$H_TWO"; do (cd "$TRACKER" && bd update "$t" -d "Write docs/design/$t/plan.md with one short paragraph. \
Answer planned and list the plan in paths." --acceptance "The plan is committed on task/$t and published to origin."); done
(cd "$TRACKER" && bd update "$H_LONG" -d "Write docs/design/$H_LONG/plan.md: five sections (goal, context, steps, risks, \
checks), each with a few careful paragraphs. Answer planned and list the plan in paths." \
  --acceptance "The plan is committed on task/$H_LONG and published to origin.")
tail -f "$ART/rounds.log"            # H2: within 120 s `start started` for $H_ONE; then nothing while it runs
T "${ROUNDS[@]}" --every 120; echo "exit $?"   # H3 (tab C): refused:rounds_running naming tab B's pid, exit 1
T plan next --backlog "$BACKLOG" --tracker-root "$TRACKER" --checkout "$REPO" --label auto --model "$MODEL" \
  --effort "$EFFORT" --minutes 30 --json     # H4: works beside it: report running, stopped no_free_slot
T plan show "$H_ONE" --backlog "$BACKLOG"    # until Released; note its Released time
# H5: $H_TWO's `start started` line within ~5 s of $H_ONE's Released time (the interval is 120 s); likewise $H_LONG's
#   within ~5 s of $H_TWO's Released time
# H7, graceful, while $H_LONG runs: Ctrl-C ONCE in tab B (the process is between rounds): the terminal says
#   "Stopping after the current move; Ctrl-C again to exit at once.", within 2 s `rounds stopped interrupted`; echo $? -> 0;
#   `ps` still shows $H_LONG's entry
T "${ROUNDS[@]}" --every 120          # H8, tab B again: the first round writes `report running` for the running task once
# H9, abrupt, $H_LONG still running: Ctrl-C TWICE quickly in tab B: `Stopped at once.`; echo $? -> 130; rounds.log ends
#   `rounds stopped abrupt` (best effort); `ps` still shows $H_LONG's entry
T "${ROUNDS[@]}" --every 120          # H10: starts normally, no second entry; keep it running
T plan show "$H_LONG" --backlog "$BACKLOG"   # until Next: done
wc -l < "$ART/rounds.log"; sleep 300; wc -l < "$ART/rounds.log"   # H6, last, every task done: no new line while idle
# then Ctrl-C once in tab B to end the run
cd "$TRACKER" && bd list --status in_progress --assignee taskloop; T plan list   # every claimed task has its attempt
ls "$SMOKE/markers"                   # empty: no hook ran
```

Optional **H11, backoff:** with nothing running and tab B's rounds running (`--every 120`), move `$TRACKER/.beads` aside
for 10 minutes: the first line is `rounds wait seconds=120 after=unavailable:tracker`, then `seconds=240` and
`seconds=300`; after moving it back, a `rounds wait seconds=120` line and the next round succeed. With every slot held
the tracker is never read, so run H11 with the slot free.

| Check | Pass | Fail means |
|---|---|---|
| H2 new task | `$H_ONE` started within one interval | the trigger missed a ready task |
| H3 singleton | exit 1, `rounds_running` with a pid | two rounds processes for one backlog |
| H5 wake | `$H_TWO` (and `$H_LONG`) started seconds after the previous release, not up to 120 s later | the slot-freed wake does not work |
| H7 graceful | the notice, `rounds stopped interrupted` within 2 s, exit 0, the entry still running | the stop killed the step, or waited for a full interval |
| H8 restart | one `report running` line (for whichever task runs then); no second entry, no new attempt row | a restart launched again |
| H9 abrupt | exit 130, `Stopped at once.`, the entry still running | a second press waited, or the step died |
| H10 after abrupt | a normal first round, no second entry or attempt row; `bd list` and `tl plan list` agree | the abrupt stop left something a round could not continue |
| H6 quiet | no new line over 5 idle minutes | idle rounds write lines |

Notes. A first Ctrl-C while a move runs waits for that move: a verify finishes its release and publish push first, up to
Git's timeout. While every slot is held no candidate is tried, so a wrong `--checkout` is refused (`refused:checkout`)
only once a slot frees. The wake follows reserved `(repo, slot)` pairs of every backlog, read just before and just after
each round: a release during a round, or the end of a step the round itself started, wakes the next round within 2 s; a
repeat taking over its slot does not wake; another backlog's release wakes one round that finds nothing to do. A
factory.db that exists but cannot be opened now backs off (`rounds wait ... after=unavailable:store`); a missing one ends
the rounds `refused:database`, exit 1. Started with SIGINT ignored (a background job), Ctrl-C stays ignored; run it in the
foreground.

**Observed (first Run H, Linux/OrbStack, 2026-11-10).** H5 failed as first built: the wake baseline was read only before
the round, so a step started by a round that began with the slot free never woke the next round (91 s instead of about
2 s; after a restart, with the slot already held, it woke in 1.1 s). Fixed: the baseline is the union of the reads before
and after the round (plan section 25); H5 is to be rerun. A SIGINT mid-round, sent with `kill -INT` to the process
group (an emulated Ctrl-C), killed the in-flight `bd ready` child within 50 ms, and the round closed
`stopped=interrupted`, exit 0. Exited entries were seen as zombies (`Zs`) of the rounds process and were reaped after its
next `bd` call. Not observed: a real terminal press, and a SIGINT while a claim's `bd` or a push's Git child runs.

Accepted residual: H5 can miss its wake when the 2 s check reads factory.db in the instant between an entry's
reservation removal and its slot-lock release; the next regular round (at most one interval) fills the slot. Not covered
live: a real reboot, that wake race, macOS.

**Reboot renewal (owner-run check, optional; plan section 16).** A reboot cannot be simulated here: the tests stand in
for it with a stored `entry_boot` other than the current boot id (`tests/steps/test_attempt_store.py`, `test_launch.py`,
`test_operations.py`, `test_round.py`). What stays unobserved without a real reboot is the whole path on a real machine. If you
choose to reboot the scratch machine mid-start: before it, `T plan show <task> --backlog "$BACKLOG" --json` for an attempt
still `admitted` with an entry registered (e.g. G6's `unavailable credentials:auth` state), noting `deadline_passed` and
the entry's identity; after the reboot, past the deadline, `cat /proc/sys/kernel/random/boot_id` differs from the stored
`entry_boot` (`sqlite3 "$DB" "SELECT entry_boot, deadline FROM attempt WHERE task_id='<task>'"`), `T plan show`
says `Next: start` (not `stuck:expired_admitted`), and the next round (or `T plan start`) writes `relaunch relaunched`
on the same attempt id, with `deadline` now the relaunch time plus `--minutes` and the new `entry_boot` the current one.
A second relaunch in the same boot never moves the deadline again. Fail means: `stuck:expired_admitted` after a reboot, a
new attempt row, or a deadline renewed by a relaunch without a reboot.

## 7. Paste back to the agent

`codex --version`; the `--json` outputs of `T config show`, both `T slot adopt`, section 4's starts (with `time`) and shows,
`launch.txt`, every `T plan show`, the second start, `T plan verify` (if run) and `T plan list --stuck`; the `ps`, `pgrep`
and `lsof` lines; `entry.log`; the two `sqlite3` result sets; `ls -la $ATT`; `answer.txt`; heads of `stderr.txt` and
`diagnostics.txt` after checking them for secrets; slot `git log`/`status`; `show-ref`; the push probe's error line;
the approved-escalation commands (or "none") and `G -C "$REPO" config --list --local`; for Run C, the `ACCESS`
listing, the command lines and exit codes from `runC.jsonl` (checked for secrets) and its `ls`/`log`/`show-ref` output;
for Run F, every `T plan publish --json` and `T plan show` output, the entry.log lines, and the `show-ref`/`rev-parse` lines;
for Run G, every `T plan next --json` output, `rounds.log`, and `bd show` of each `G_*` task; for Run H, tab B's start and
end lines with their exit codes, `rounds.log`, `T plan show` of `$H_ONE`, `$H_TWO` and `$H_LONG`, H3's and H4's output, and the
`bd list --status in_progress --assignee taskloop` and `T plan list` pair.
Never paste `auth.json`, `env`, or the agent's environment.

## 8. Known wedges, reset and cleanup

Moving a run's files aside (6a, 6c) keeps the slot; a slot or probe directory moved or deleted by hand leaves a stale
`git worktree list` registration in `$REPO`: harmless (`G -C "$REPO" worktree prune` clears it; never prune a live slot).

Nothing resumes, retries or stops an attempt; only Git leftovers are repeated, by re-running `tl plan start` (6c). A
step that ended on a clean slot releases it itself (claim kept); every stuck attempt whose entry and agent are shown
stopped ends with `tl plan release TASK --backlog B --abandon` (6d), which also returns the claim. Phase `dispatching`
with no agent recorded cannot be shown stopped (`unsettled:worker_unknown`): only the reset below remains. Phase
`dispatching` or `registered` with a dead entry otherwise stays so until abandoned (start: `already_dispatched`; show:
`stuck:entry_lost`); a live but hung entry gives `already_dispatched` while the
attempt is `dispatching`/`registered` and `already_running` once it is `captured` (`stuck:hung` past the deadline); a deadline passed while `admitted` refuses registration (`refused:registration_refused`;
`stuck:expired_admitted`). Until released or abandoned, the reservation and the bead claim stay held by design. Kill only by PID, after checking it:
`ps -o command= -p "$E"` must show `taskloop.attempt_entry $DB`; for the worker, `lsof -a -p "$W" -d cwd` (Linux without
lsof: `readlink /proc/$W/cwd`) must show `$SLOT`, then
`kill -TERM -"$(ps -o pgid= -p "$W" | tr -d ' ')"` (its own group); `plan show` names the worker only as `last known`, so
check it is alive first. Reset for a rerun (also the reset after any schema change: an older `factory.db` is moved aside or
deleted, never migrated; a slot an older run left on a task branch is detached by hand, `G -C "$SLOT" switch -q --detach`,
before `T slot adopt`):

```bash
rm -f "$DB" "$DB-wal" "$DB-shm"; rm -rf "$ART"   # or move them aside as in section 6a when the run is evidence
G -C "$REPO" worktree remove --force "$SLOT"; G -C "$REPO" worktree add --detach "$SLOT"
# then a NEW bead (section 2, from `TASK=`), `T slot adopt "$REPO"` and start again; the old bead stays claimed by `taskloop`
```

After an abrupt stop (`tl plan rounds` pressed twice, a closed terminal) or a crash, compare
`bd list --status in_progress --assignee taskloop` in `$TRACKER` with `T plan list`: a stop between a tracker claim's commit
and factory.db's leaves a claim with no attempt; return it with `bd unclaim <task> --if-assignee taskloop`. Stop
`tl plan rounds` (Ctrl-C in its terminal) before any reset or discard.

Cleanup after the smoke: check `ps -ax -o pid,command | grep -F "$SMOKE"` shows nothing of ours running (kill as above), then
`G -C "$REPO" worktree remove --force "$SLOT"; rm -rf ~/tl-smoke`. This removes only scratch paths.

## 9. Do not

- Point `$REPO`, `$TRACKER`, `$DB` or `$ART` at a real repo, the real bd tracker, `~/.config/task-loop` or the shelf checkout.
- Create the slot root inside any checkout; run `bd` in a real repo; push anywhere but `remote.git`.
- Kill by name (`pkill codex`, `killall python`): only verified PIDs (section 8).
- Edit `factory.db` rows by hand, or rerun `start` in a loop; one launch per admitted attempt plus one check.
- Run `tl plan next` against the real tracker, or a backlog whose tasks carry the `auto` label outside this scratch tracker.
- Run `tl plan rounds` against the real tracker or with real paths, under a service manager (systemd's default kills the
  entries in its cgroup), or at boot; never run the gates (`just check`, `just test`) in `$TL` while it runs from there.
- Run a bare `tl` or omit `--config`: always `T`, so every path stays under `$SMOKE` (the defaults are `~/.local/...`).
- Let an agent run this without Denis's authorization for that run; otherwise agents read the pasted output.
