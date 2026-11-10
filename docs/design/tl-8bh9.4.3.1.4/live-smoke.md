# Live smoke: registered attempt entry (owner-run)

Run by Denis only, on macOS, never by an agent. Scratch repo, scratch tracker and scratch `factory.db` only. It settles the
[plan](plan.md)'s unprovable list (section 9): exec identity on macOS, entry survival, real gate and busy timing,
`entry.log`, fd inheritance, Codex flags/auth/push bar, a commit in a linked worktree, and `collect` from a fresh shell.
There is no CLI yet; the driver below calls the composition functions directly (checked with ruff, pyrefly, import-only).

## 0. Prerequisites

macOS, a plain Terminal (two tabs, A and B), `git`, `sqlite3`, `lsof`, `bd` 1.3.1, and in this checkout (`$TL`, HEAD
c32d2994a or later): `just prepare` (non-editable install), then
`uv run --frozen --no-sync python -I -c "import taskloop.attempt_entry, taskloop.plan_launch"`.
Codex: `command -v codex; codex --version` (paste both); file login: `test -f "${CODEX_HOME:-$HOME/.codex}/auth.json" && echo ok`
(stat only; never open or paste it). Run every step from a shell where `codex` is on `PATH`: the entry inherits it.

## 1. Scratch layout, env and driver (tab A)

```bash
mkdir -p ~/tl-smoke && cd ~/tl-smoke && cat > env.sh <<EOF
TL=$HOME/PATH/TO/successor-checkout   # edit: this checkout
SMOKE=$(pwd -P); REPO=\$SMOKE/repo; TRACKER=\$SMOKE/tracker; ROOT=\$SMOKE/slots; DB=\$SMOKE/factory.db; ART=\$SMOKE/artifacts
BACKLOG=smoke; MODEL=EDIT-a-model-your-codex-login-serves; EFFORT=medium
D() { (cd "\$TL" && uv run --frozen --no-sync python -I "\$SMOKE/driver.py" "\$@"); }
EOF
${EDITOR:-vi} env.sh && source env.sh
cat > "$SMOKE/driver.py" <<'PY'
"""Owner-run live smoke driver for tl-8bh9.4.3.1.4: scratch paths only, one verb per call."""

import sqlite3
import sys
import time
from collections.abc import Callable
from pathlib import Path

from git_porcelain import RealRepo
from sqlite_store import Store
from stream_proc import OwnedProcess, observe_owned

from taskloop.composition import adopt_slots, open_launcher, open_plan_admission, open_plan_attempts
from taskloop.plan_admit import AdmitRequest
from taskloop.plan_files import PlanFiles
from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import PlanStore


def slot_path(checkout: str, root: str) -> None:
    print(Path(root).resolve() / RealRepo(Path(checkout).resolve(), memoize=False).identity().key / "s1")


def adopt(db: str, checkout: str, root: str) -> None:
    print(adopt_slots(Path(db), Path(checkout), Path(root), 1))


def admit(db: str, art: str, task: str, backlog: str, tracker: str, checkout: str, model: str, effort: str, minutes: str) -> None:
    deadline = time.time() + float(minutes) * 60
    request = AdmitRequest(task, backlog, tracker, Path(checkout), model, effort, "workspace-write", deadline)
    print(open_plan_admission(Path(db), Path(art)).admit(request))


def launch(db: str, art: str, backlog: str, task: str) -> None:
    began = time.monotonic()
    result = open_launcher(Path(db), Path(art)).launch(backlog, task)
    print(f"{result} in {time.monotonic() - began:.3f}s", flush=True)


def status(db: str, art: str, backlog: str, task: str) -> None:
    con = Store(SCHEMA).open_ro(Path(db))
    if con is None:
        print("no factory.db")
        return
    found = PlanStore(lambda: con).attempt_of(backlog, task)
    print("attempt_of:", found)
    if found is None:
        return
    key, _phase, entry = found
    if entry is not None:
        print("entry observed:", observe_owned(OwnedProcess(entry[0], entry[0], entry[1], entry[2])).kind)
    files = PlanFiles(Path(art))
    print("attempt dir:", files.root / files.directory(key))
    result = open_plan_attempts(Path(db), Path(art)).collect(key)
    print("collect:", result.status, result.reason)
    if result.execution is not None:
        print("answer:", result.execution.answer, "publication:", result.execution.publication)
        print("facts:", result.execution.facts)


def hold(db: str, seconds: str) -> None:
    con = sqlite3.connect(db, isolation_level=None)
    con.execute("BEGIN IMMEDIATE")
    print(f"write lock held for {seconds}s", flush=True)
    time.sleep(float(seconds))
    con.execute("ROLLBACK")


VERBS: dict[str, Callable[..., None]] = {
    "slot-path": slot_path,
    "adopt": adopt,
    "admit": admit,
    "launch": launch,
    "status": status,
    "hold": hold,
}

if __name__ == "__main__":
    VERBS[sys.argv[1]](*sys.argv[2:])
PY
```

## 2. Scratch repo, remote, tracker and task

```bash
git init -q --bare "$SMOKE/remote.git" && git init -q "$REPO" && cd "$REPO"
git config user.name smoke; git config user.email smoke@example.invalid; git config core.hooksPath "$SMOKE/no-hooks"
echo smoke > README.md && git add README.md && git commit -qm init && git remote add origin "file://$SMOKE/remote.git"
mkdir "$TRACKER" && cd "$TRACKER" && git init -q && bd init --non-interactive --skip-hooks --skip-agents -p smoke -q
TASK=$(bd create "Smoke plan" --silent) && echo "TASK=$TASK" >> "$SMOKE/env.sh"
bd update "$TASK" -d "Create docs/design/$TASK/plan.md with one short paragraph saying this is a live smoke plan. \
Commit only that file on the current detached HEAD with message 'smoke plan'. Then run once: git push origin HEAD:refs/heads/smoke, \
and state in the explanation whether it failed and git's first error line. Report disposition planned with plan_path \
docs/design/$TASK/plan.md and the full commit sha; if the commit is impossible, report incomplete and say why." \
  --acceptance "docs/design/$TASK/plan.md is committed on the slot's HEAD; nothing is pushed."
(cd "$TL" && uv run --frozen --no-sync tl task show "$TASK" --backlog "$BACKLOG" --tracker-root "$TRACKER")
```

## 3. Slot (made by hand, then adopted), admit

```bash
SLOT=$(D slot-path "$REPO" "$ROOT") && echo "SLOT=$SLOT" >> "$SMOKE/env.sh" && echo "$SLOT"   # <ROOT>/<repo_id>/s1
mkdir -p "$(dirname "$SLOT")" && git -C "$REPO" worktree add --detach "$SLOT"
D adopt "$DB" "$REPO" "$ROOT"                      # expect (Adopted(name='s1', path=...),); creates factory.db
D admit "$DB" "$ART" "$TASK" "$BACKLOG" "$TRACKER" "$REPO" "$MODEL" "$EFFORT" 30   # expect Admitted(key=..., slot='s1')
```

`not_listed`/`other_root` means `$SLOT` differs from what Git lists (symlinked path): keep everything under `pwd -P`.
`inside_checkout` means `$ROOT` is inside `$REPO`. A refused admit names its reason; fix it and admit again (nothing was written).

## 4. Busy probe (before the real launch)

Tab B: `source ~/tl-smoke/env.sh; D hold "$DB" 4`. Tab A, within a second of "write lock held": `D launch "$DB" "$ART" "$BACKLOG" "$TASK"`.
Expect `LaunchUnavailable(reason='store') in ~1.5s`, then `D status ...` shows the entry still `None` (nothing registered; the
bootstrap child was cleaned up). About 5 s instead means something other than the 1.5 s registration wait blocked (e.g. the writer open): paste it.

## 5. Launch, then let the coordinator go

Tab A: `D launch "$DB" "$ART" "$BACKLOG" "$TASK" | tee "$SMOKE/launch.txt"; exit` (closing the tab ends the coordinator's
session). Expect `Launched(key=..., entry=(pid, 'start', 'boot')) in <s>`. Everything below runs in tab B, a fresh shell:

```bash
source ~/tl-smoke/env.sh; cat "$SMOKE/launch.txt"; D status "$DB" "$ART" "$BACKLOG" "$TASK"   # repeat until collect: collected <reason>
ATT=$(D status "$DB" "$ART" "$BACKLOG" "$TASK" | sed -n 's/^attempt dir: //p'); E=$(sqlite3 -readonly "$DB" "select entry_pid from plan_attempt")
W=$(sqlite3 -readonly "$DB" "select worker_pid from plan_attempt")   # set once phase is registered
ps -o pid,ppid,pgid,stat,tt,lstart,command -p "$E"        # entry: PPID 1, PGID = PID, STAT has s, TT ??
pgrep -lf -P "$E"; lsof -a -p "$E" -d 0-2; lsof -a -p "$W" -d 0-2; lsof "$ATT/entry.log"
cat "$ATT/entry.log"; ls -la "$ATT"
sqlite3 -readonly -header "$DB" "select phase,rev,entry_pid,entry_start,entry_boot,worker_pid,worker_pgid,
 session_ref is not null as has_session,session_conflict,round(deadline-strftime('%s','now')) as left_s from plan_attempt;
 select rc,timed_out,stop,watch,reason,http_status,turns,answer_kind,disposition,plan_path,reported_commit,publication from plan_execution;"
D launch "$DB" "$ART" "$BACKLOG" "$TASK"                   # second launch: AlreadyRunning or LaunchRefused(reason='dispatched')
git -C "$SLOT" log --oneline -3; git -C "$SLOT" status --short; git -C "$SMOKE/remote.git" show-ref; cat "$ATT/answer.txt"
env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=url.delegate-push-refused://.pushInsteadOf GIT_CONFIG_VALUE_0= \
  git -C "$REPO" push origin HEAD:refs/heads/probe    # owner's push-bar probe: must fail (no remote helper)
```

## 6. Pass/fail per question

| Question | Pass | Fail means | Safe next action |
|---|---|---|---|
| Start/boot identity survives exec | phase leaves `admitted`; no `refused identity` | `refused identity`: macOS start (or boot) changes across exec, or the read was `unknown` | stop; paste `ps lstart` and the row; do not relaunch (a replace fails the same way) |
| Entry survives coordinator exit | after tab A closed: entry alive, PPID 1, `s`, `??`; run reaches `captured` | entry gone with phase `admitted`/`dispatching`: SIGHUP or session not detached | paste `ps`, `entry.log`, row; reset (section 8) |
| Gate and registration timing, busy | launch < 5 s; section 4 gives `store` at ~1.5 s; `worker_pid` set, phase `registered` then `captured` | `registration_*` or `unavailable register` in entry.log: harness gate write too slow; ~5 s in section 4 | paste both timings and entry.log |
| entry.log contents | exactly one line `<status> <reason>` (maybe ` publish=... then=...`), e.g. `collected planned`; `collected run:<r>` or `collected answer:<kind>` is a terminal failure (exit 1), not success | a traceback: import failure (broken install); env/argv text: a leak | `just prepare`, reset; paste the log |
| fd 2 inheritance | entry fd 1,2 = entry.log, fd 0 a pipe; worker fd 0-2 pipes; `lsof entry.log` lists only the entry | the worker or its children hold entry.log | paste the lsof output |
| Codex accepts CODEX_ACCESS + file login | `rc` 0, `answer_kind` valid | `stderr.txt` names an unknown flag/config key: installed codex rejects CODEX_ACCESS; `http_status` 401: login refused; entry.log `unavailable credentials:<word>`: source refused (`codex` not on PATH, `auth`, `git_config`) | paste `codex --version`, first lines of `stderr.txt` (check them for secrets first) |
| Push refused | owner probe fails; no `smoke` ref in `remote.git`; answer.txt says the push failed or was not approved | a `smoke` ref exists: the push bar does not hold | stop; paste `show-ref` and answer.txt |
| Commit in a linked worktree | `disposition` planned, `reported_commit` = `git -C $SLOT rev-parse HEAD`, file in it; `git -C $SLOT status --short` empty | `incomplete` with a blocked commit: the known `writable_roots=[]` limit (plan section 5), not a launch failure. Planned, but made through an approved escalation (see below): the sandbox did not bound the commit ([.4.3.1.5](../tl-8bh9.4.3.1.5/plan.md) sections 8-9) | record it; paste answer.txt and the escalation list |
| Escalations approved | none, or each listed: the command Codex ran outside the sandbox, from the approval events in `stdout.txt` | any approved command touching `.git` (config, hooks, refs) or the push bar | paste the command lines only (check them for secrets) and `git -C "$REPO" config --list --local` |
| collect from a fresh shell | tab B `status` prints `collect: collected planned` (a `run:`/`answer:` reason is a failure) and the answer; second launch never `Launched` | `collect: unavailable`/`pending <phase>` long after codex exited | paste status output and the row |

Exactly one Codex session: `pgrep -P "$E"` shows one child while running; `has_session` 1 and `session_conflict` 0 at the end.

## 7. Paste back to the agent

`codex --version`; outputs of `adopt`, `admit`, section 4, `launch.txt`, every `status`, the second launch; the `ps`, `pgrep`
and `lsof` lines; `entry.log`; the two `sqlite3` result sets; `ls -la $ATT`; `answer.txt`; heads of `stderr.txt` and
`diagnostics.txt` after checking them for secrets; slot `git log`/`status`; `show-ref`; the push probe's error line;
the approved-escalation commands (or "none") and `git -C "$REPO" config --list --local`.
Never paste `auth.json`, `env`, or the agent's environment.

## 8. Known wedges, reset and cleanup

Nothing resumes, retries, releases or stops an attempt in this slice. Phase `dispatching` or `registered` with a dead entry
stays so (second launch: `dispatched` forever); a live but hung entry gives `AlreadyRunning` forever; a deadline passed while
`admitted` refuses registration. The reservation and the bead claim stay held by design. Kill only by PID, after checking it:
`ps -o command= -p "$E"` must show `taskloop.attempt_entry $DB`; for the worker, `lsof -a -p "$W" -d cwd` must show `$SLOT`, then
`kill -TERM -"$(ps -o pgid= -p "$W" | tr -d ' ')"` (its own group). Reset for a rerun:

```bash
rm -f "$DB" "$DB-wal" "$DB-shm"; rm -rf "$ART"
git -C "$REPO" worktree remove --force "$SLOT"; git -C "$REPO" worktree add --detach "$SLOT"
# then a NEW bead (section 2, from `TASK=`), adopt and admit again; the old bead stays claimed by `taskloop`
```

Cleanup after the smoke: check `ps -ax -o pid,command | grep -F "$SMOKE"` shows nothing of ours running (kill as above), then
`git -C "$REPO" worktree remove --force "$SLOT"; rm -rf ~/tl-smoke`. This removes only scratch paths.

## 9. Do not

- Point `$REPO`, `$TRACKER`, `$DB` or `$ART` at a real repo, the real bd tracker, `~/.config/task-loop` or the shelf checkout.
- Create the slot root inside any checkout; run `bd` in a real repo; push anywhere but `remote.git`.
- Kill by name (`pkill codex`, `killall python`): only verified PIDs (section 8).
- Edit `factory.db` rows by hand, or rerun `launch` in a loop; one launch per admitted attempt plus one check.
- Let an agent run this; agents read the pasted output.
