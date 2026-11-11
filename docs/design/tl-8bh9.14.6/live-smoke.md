# M2 live smoke: the check step in the rounds (owner-run, after S6e)

**Status: passed 2026-11-11** at `4e004864c`, with three runbook corrections ([findings](m2-smoke-findings.md)).
Milestone M2 of the [roadmap](../self-hosting-roadmap.md) is reached when this run passes: a
`tl step rounds` loop from a runner worktree takes a small task of **this repository** through plan, implement and the
**check step**, which runs the profile's checks on the implement commit X on the host and shows each check's result
(design: [plan.md](plan.md) sections 1, 6, 7, 9, 17; the S6e as-built section says what the round does). Linux only.
Run by Denis, or by an agent Denis authorized for that one run. Scratch remote, scratch tracker and scratch factory.db
only: nothing reaches the real `origin`, the real tracker or `~/.local/state/task-loop`. Never open or paste
`auth.json` (stat it only). Kill nothing by name: every pid below is checked first (`ps -o command=`, `lsof -d cwd`).

The layout is the [M1 runbook](../tl-8bh9.4.3.1.16.2/live-smoke.md)'s ("M1 end-to-end smoke" sections 0 and 1, read
them and the [M1 findings](../tl-8bh9.4.3.1.16.2/m1-smoke-findings.md)) with a new folder `$M2`, a new factory.db
(schema **v12**) and three changes: the shell function for `tl` is `TL` (the glossary's T is a remote tip), the scratch
`main` carries a smoke profile (section 1), and three tasks run one after another (sections 2 to 6).

## 0. Runner, layout and machine config

The factory under test and the code the tasks change are the S6e commit or later. Since PR #722 the repository's
`main` holds the successor, so `SRC` may be any checkout whose object store holds `SHA`; the commit check stays.

```bash
M2=$HOME/tl-smoke/m2; mkdir -p "$M2" && cd "$M2"
SRC=$HOME/PATH/TO/a-checkout-of-this-repository             # edit
SHA=<the S6e commit eba237919 or a later one>                # edit: the successor commit under test
G() { git --no-optional-locks -c core.hooksPath=/dev/null "$@"; }
G -C "$SRC" cat-file -e "$SHA^{commit}" && G -C "$SRC" merge-base --is-ancestor eba237919 "$SHA" && echo "SHA has S6e"
mise settings add trusted_config_paths "$M2"                 # before any `just` under $M2 (M1 finding 1)
G -C "$SRC" worktree add --detach "$M2/runner" "$SHA"       # the runner: the factory version under test, never edited
(cd "$M2/runner" && just install)
TL() { "$M2/runner/.venv/bin/tl" --config "$M2/config.toml" "$@"; }
G clone -q --bare "$SRC" "$M2/remote.git"                    # scratch origin
G -C "$M2/remote.git" update-ref refs/heads/main "$SHA"
G -C "$M2/remote.git" for-each-ref --format='%(refname)' 'refs/heads/task/*' | while read -r ref; do
  G -C "$M2/remote.git" update-ref -d "$ref"; done
G clone -q --branch main "$M2/remote.git" "$M2/repo"
mkdir -p "$M2/state" "$M2/artifacts" "$M2/slots"
printf 'db = "%s"\nartifacts = "%s"\nslots_root = "%s"\nslot_count = 1\n' \
  "$M2/state/factory.db" "$M2/artifacts" "$M2/slots" > "$M2/config.toml"
TL config show                                               # every value under $M2; round_seconds 60 (default)
env | grep -c '^UV_OFFLINE=' || true                         # 0: the smoke checks below rely on it being unset here
```

The prerequisites of M1 section 0 apply unchanged (factory.db new, db and slots not nested, `.t/<slot>` at most 64
bytes, mise trust, `codex` and `bd` on `PATH`, network for `setup`).

## 1. The smoke profile on the scratch `main`

The required names come from the local `main` of `$M2/repo` at each checks admission; the commands from the profile at
X. X descends from the free slot's HEAD (D), not from `main`: the plan attempt cuts `task/<id>` from D, and the factory
never fetches or moves a free slot (`prepare.py`; M2 finding 1). So each variant is committed to the local `main`,
pushed to the scratch origin **and** the free slot is detached at the new `main` (`P` does all three once `$SLOT` is
set) **before** its task is created, and the next variant only after the previous task's checks concluded and
released. Every smoke check except `offline-only` is guarded by `test -n "$UV_OFFLINE" ||`: the implement agent's
sandbox shell has `UV_OFFLINE=1` and passes it at once, while the check step on the host (no `UV_OFFLINE`) runs the real
command. `offline-only` is the reverse: it passes in the sandbox and fails on the host, a deterministic failing required
check the agent cannot see.

```bash
P() {  # P base|failing|orphan: main's profile, committed and pushed to the scratch origin
  python3 - "$1" "$M2/repo/.task-loop.json" <<'EOF'
import json, sys
variant, path = sys.argv[1], sys.argv[2]
def guard(cmd): return ["sh", "-c", 'test -n "$UV_OFFLINE" || { ' + cmd + '; }']
checks = [{"name": "check", "argv": ["just", "check"], "timeout": 1800},
          {"name": "test", "argv": ["just", "test"], "timeout": 1800},
          {"name": "report", "argv": guard("echo m2 > m2-report.txt"), "timeout": 30},
          {"name": "slow", "argv": guard("sleep 60"), "timeout": 300}]
required = ["check", "test"]
if variant == "failing":
    checks.append({"name": "offline-only", "argv": ["sh", "-c", 'test -n "$UV_OFFLINE"'], "timeout": 30})
    required.append("offline-only")
if variant == "orphan":
    checks.append({"name": "orphan", "argv": guard("sleep 600 & true"), "timeout": 30})
with open(path, "w") as out:
    json.dump({"setup": [["just", "bootstrap"]], "checks": checks, "required": required, "target": "main"}, out, indent=2)
EOF
  G -C "$M2/repo" commit -qam "smoke profile: $1" && G -C "$M2/repo" push -q origin main &&
    { [ -z "${SLOT:-}" ] || G -C "$SLOT" checkout -q --detach main; }   # the free slot at the new main
}
P base
TL profile show --checkout "$M2/repo" --at HEAD    # setup just bootstrap; checks check, test, report, slow; required check, test
```

## 2. Slot, tracker, the first task: plan, implement, checks pass, `Next: done`

```bash
TL slot adopt "$M2/repo"; SLOT=PASTE-the-path-it-printed
mkdir -p "$(dirname "$SLOT")" && G -C "$M2/repo" worktree add --detach "$SLOT" && TL slot adopt "$M2/repo"
mkdir "$M2/tracker" && cd "$M2/tracker" && git init -q && bd init --non-interactive --skip-hooks --skip-agents -p m2 -q
A=$(bd create "Test the round log words" --silent)
bd update "$A" -d "Add tests/steps/test_round_log.py with pytest functions for src/taskloop/round_log.py: fixed keeps a \
valid word and turns an invalid one into 'invalid'; ident does the same for ids; stamped prints the UTC time, the backlog \
and the words. Change no source file." --acceptance "The new test file exists and passes; just check and just test pass."
bd label add "$A" auto
# tab A, from $M2:
TL step rounds --backlog m2 --tracker-root "$M2/tracker" --checkout "$M2/repo" --label auto \
  --model <model> --effort <effort> --minutes 90
# tab B:
tail -f "$M2/artifacts/rounds.log"
```

Expect in `rounds.log`, in order (an identical line is never repeated; `verify` lines may be absent when the entry
verified and published first, M1 finding 2):

```
<t> m2 <A> plan start started <a1>
<t> m2 <A> implement advance started <a2>
<t> m2 <A> check advance started <c1>
<t> m2 <A> check report running <c1>          # while the block runs (setup, check, test, report, slow)
<t> m2 round moves=0                           # once the checks passed: a pass writes nothing
```

No `check report failed:*`, `skip`, `refused:*` or `stuck:*` line. While the block runs, in tab B:

```bash
TL step show "$A" --backlog m2      # Step: check; Attempt: <c1> (run 1); Earlier: <a2> advanced; Entry: running (pid ...);
                                    # Check: lines passed or `unfinished, process group <pgid>`
ps -o pid,pgid,sid,command -g <pgid>                         # the running check: its sid is its own pid, not the entry's
lsof -a -p <pid> -d cwd                                      # the slot
```

After the block, `TL step show "$A" --backlog m2` includes these lines (others, such as `Task:` and `Entry:`, between):

```
Step: check
Attempt: <c1> (run 1)
Earlier: <a2> advanced
Slot: s1
Phase: concluded
Commit: <X>
Required: check, test (main at <target>)
Profile: <digest> at X
Setup: run 1 passed at <X>; log <dir>/setup-1.log
Check: check passed, exit 0, <n> s; log <dir>/check-1-check.log
Check: test passed, exit 0, <n> s; log <dir>/check-1-test.log
Check: report passed, exit 0, 0 s; log <dir>/check-1-report.log (not required)
Check: slow passed, exit 0, 60 s; log <dir>/check-1-slow.log (not required)
Result: collected passed
Succeeded: yes
Released: <time>, slot parked at <D>; claim kept
Next: done
```

- `check-1-check.log` ends `exit 0` after `All checks passed!`; `check-1-test.log` after `N passed`.
- `check-1-report.log` lists `untracked: m2-report.txt`, and still the slot was released: `G -C "$SLOT" status
  --porcelain=v1 --ignored=no` is empty, `G -C "$SLOT" rev-parse HEAD` is D, `ls -A "$(dirname "$SLOT")/.t/s1"` empty.
- `TL step list`: one row, step `check`, attempt `1`, `concluded`, `collected passed`, `done`. `bd show "$A"`:
  `in_progress`, `taskloop` (M2 lands by hand; the claim stays).

## 3. Interrupted rounds during a block, and the restart

Optional but recommended (covers "an intact factory.db continues"). Cut a second task like A on the same profile
(`A2=$(bd create "Test the round log ident words" --silent)`, a description limited to `ident`, label `auto`), and when
`rounds.log` shows `<A2> check report running` and `TL step show` shows `Check: slow unfinished`:

1. Ctrl-C once in tab A: `Rounds stopped: interrupted.`; the checks entry keeps running (`ps -o command= -p <entry
   pid>` shows `taskloop.check_entry`). Start the same `TL step rounds` again: `check report running` until the block
   ends, then quiet; the result is block 1's, `Next: done`; one checks attempt (`Attempt: ... (run 1)`).
2. Harder variant (optional): Ctrl-C the rounds, then stop the checks entry by the pid `TL step show` prints after
   verifying it (`ps -o command= -p <pid>` shows `taskloop.check_entry`; `kill -TERM <pid>`). `slow` keeps running in its
   own session. Restart rounds. Expect `<A2> check relaunch relaunched <c>`; the entry log (`<dir>/entry.log`) says
   `unavailable checks:running` while `slow` lives; `TL step show` adds `Refused: checks:running (1 in a row)`. After
   `slow` ends, the next relaunch marks block 1's `slow` `interrupted` and runs block 2 whole; the result is block 2's
   (`check-2-*.log`). If two relaunches met `slow` still running, the row reads `stuck:checks_refused` (`check report
   stuck:checks_refused` once) and rounds stop relaunching: `TL step start "$A2" ...` relaunches it by hand (either
   outcome is correct; record which).

## 4. A failing required check: a visible failed `done`, never re-run by rounds

After A (and A2) concluded: `P failing`, then cut task B (`B=$(bd create "Test the exit code words" --silent)`, a
description asking for `tests/steps/test_exit_codes.py` covering `src/taskloop/exit_codes.py`, no source change, label
`auto`). Expect:

```
<t> m2 <B> check advance started <c>
<t> m2 <B> check report failed:offline-only:failed <c>    # exactly once, however many rounds follow
```

- `TL step show "$B"`: `Required: check, test, offline-only (...)`, `Check: offline-only failed, exit 1, ...`,
  `Result: collected failed:offline-only:failed`, `Succeeded: no`, `Released: ...; claim kept`, `Next: done`.
- Leave the rounds running for three more rounds: no second checks attempt (`Attempt: ... (run 1)` stays), no new
  `rounds.log` line for B, `bd show "$B"` still `in_progress` for `taskloop`.
- Re-run by hand: `TL step start "$B" --backlog m2 --tracker-root "$M2/tracker" --checkout "$M2/repo" --model <m>
  --effort <e> --minutes 90`: `Attempt: <c'> (run 2)`, `Earlier: <c> re-run` then `<b2> advanced`; still
  `failed:offline-only:failed` (the host has no `UV_OFFLINE`).

## 5. Abandon after the checks

`TL step release "$B" --backlog m2 --abandon`: the checks attempt's lines first, then the implement attempt's release
with `claim unclaimed`; `bd show "$B"`: `open`, no assignee. Rounds then write `<B> implement skip abandoned <b2>` once
and never advance or re-admit it (`TL step list` shows `Next: start`). `TL step start "$B" ...` by hand would admit it
afresh at plan (D4): do not, unless testing that.

## 6. A check that leaves a background process: `lingering`

`P orphan` (main's required names are `check`, `test` again), then cut task C (`C=$(bd create "Test the checks guide
words" --silent)`, asking for tests of `step_guide.guide` with `checks=True` and `False`, label `auto`). `orphan` is
`sh -c 'sleep 600 & true'`: the command exits 0 at once and leaves the backgrounded `sleep` alive in its process
group, so the result is `lingering` (S6b: a process left after any end). A **timeout** does not give `lingering`: the
stop (`stream_proc.tree.stop_tree`) signals the group and every descendant it noted beforehand, `setsid` ones included,
so `sh -c 'sleep 600 & sleep 600'` and `sh -c 'setsid sleep 600 & sleep 600'` with a 5 s timeout both end `orphan
timed_out` with nothing left, and the block goes on (M2 finding 3):

- `TL step show "$C"`: `Check: orphan lingering, ..., process group <pgid> (not required)`, `Result: collected
  failed:orphan:lingering`, no `Released:` line, `Next: release`; the entry log ends `... release=held:check_running`;
  `rounds.log` has `<C> check report release <c>` once.
- The person stops the survivor: `ps -o pid=,lstart=,command= -g <pgid>` lists the `sleep 600` process; `lsof -a -p
  <pid> -d cwd` (or `readlink /proc/<pid>/cwd`) shows the slot; `kill -TERM <each verified pid>`. Then `TL step
  release "$C" --backlog m2`: `released`; `Next: done` with the failed result; the slot is clean at D.
- Revert the profile afterwards: `P base`.

## 7. Paste back

`TL config show`; both `TL slot adopt`; `TL profile show` for each variant; the whole `rounds.log`; `TL step show` and
`TL step list` after each section; the last line of each checks attempt's `entry.log`; the head and tail of each
`check-*.log` named above; `bd show` for A, B, C; the slot's `status --porcelain=v1 --ignored=no` after each release.
Record the findings in `docs/design/tl-8bh9.14.6/m2-smoke-findings.md`, as for M1.
