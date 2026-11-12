# M4 live smoke: holds and keep-awake in the unattended loop (owner- or authorized-agent-run, after H3 and K1)

**Status: passed 2026-11-12** at `27c632d5d` (step 9 blocked), with five runbook corrections ([findings](m4-smoke-findings.md)).

Milestone M4 of the [roadmap](../self-hosting-roadmap.md): `tl step rounds ... --label auto` left alone holds every
task it took and then stopped on (label removed, `held` added, the claim returned when the slot allows, one comment),
and keeps the machine awake while it runs (design: [plan.md](plan.md) sections 1-13 and 17, as revised by section 23;
as built: sections 24-27). Linux only. Scratch remote, scratch tracker, scratch factory.db (schema **v14**) under
`~/tl-smoke/m4` only: nothing reaches the real `origin`, the real tracker or `~/.local/state/task-loop`. Never open or
paste `auth.json` (`test -f` only). Kill nothing by name: every pid below is verified first (`ps -o pid=,user=,command=
-p <pid>`); a signal goes only to a verified pid this run started. No circuit breaker exists (plan section 11): none is
tested. **Step 9 (Git read timeout, G1/G2) is BLOCKED until git-porcelain 0.17.0 is released and pinned: do not run.**

The layout is the [M3 runbook](../tl-8bh9.14.8/live-smoke.md)'s section 0 (read it, its [findings](../tl-8bh9.14.8/m3-smoke-findings.md)
and the [M2 runbook](../tl-8bh9.14.6/live-smoke.md)) with `$M4`, two slots and a smaller profile. Tasks are tiny file
changes so a plan or implement run costs little; failures are made on purpose through the task text and the profile,
never left to chance.

## 0. Runner, layout and machine config

```bash
M4=$HOME/tl-smoke/m4; mkdir -p "$M4" && cd "$M4"
SRC=$HOME/PATH/TO/a-checkout-of-this-repository             # edit
SHA=<the H3 review repairs commit 27c632d5d or a later one>   # edit
G() { git --no-optional-locks -c core.hooksPath=/dev/null "$@"; }
G -C "$SRC" merge-base --is-ancestor 27c632d5d "$SHA" && G -C "$SRC" merge-base --is-ancestor 52c0acada "$SHA" \
  && echo "SHA has H3 (with its repairs) and K1"
SAVE=<a folder outside $M4 that outlives it>                 # edit: e.g. a scratchpad
sha256sum ~/.config/mise/config.toml | tee "$SAVE/mise.before"   # restored byte for byte at the end
cp -p ~/.config/mise/config.toml "$SAVE/mise.config.toml.orig"
mise settings add trusted_config_paths "$M4"                 # before any `just` under $M4 (M1 finding 1)
G -C "$SRC" worktree add --detach "$M4/runner" "$SHA"       # the runner: the factory under test, never edited
(cd "$M4/runner" && just install)
TL() { "$M4/runner/.venv/bin/tl" --config "$M4/config.toml" "$@"; }
G clone -q --bare "$SRC" "$M4/remote.git"                    # scratch origin
G -C "$M4/remote.git" update-ref refs/heads/main "$SHA"
G -C "$M4/remote.git" for-each-ref --format='%(refname)' 'refs/heads/task/*' | while read -r ref; do
  G -C "$M4/remote.git" update-ref -d "$ref"; done
G clone -q --branch main "$M4/remote.git" "$M4/repo"         # the person's checkout
G clone -q --branch main "$M4/remote.git" "$M4/other"        # someone else's clone (moves a task branch, step 6)
mkdir -p "$M4/state" "$M4/artifacts" "$M4/slots"
printf 'db = "%s"\nartifacts = "%s"\nslots_root = "%s"\nslot_count = 2\n' \
  "$M4/state/factory.db" "$M4/artifacts" "$M4/slots" > "$M4/config.toml"
TL config show                                               # every value under $M4; slot_count 2
env | grep -c '^UV_OFFLINE=\|^GIT_CONFIG_' || true           # 0
test -f ~/.codex/auth.json && echo "codex login present"     # never read it
DB() { python3 -I -c 'import sqlite3,sys; c=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro", uri=True)
[print(*r, sep="|") for r in c.execute(sys.argv[2])]' "$M4/state/factory.db" "$1"; }   # factory.db, read-only
RUN() { TL step rounds --backlog m4 --tracker-root "$M4/tracker" --checkout "$M4/repo" --label "${1:-auto}" \
  --model <model> --effort low --minutes 20; }               # edit <model>; run in its own tab (or background)
SHOW() { TL step show "$1" --backlog m4; }
```

Prerequisites of M1 section 0 apply (factory.db new, db and slots not nested, `.t/<slot>` at most 64 bytes, `codex`
and `bd` on `PATH`). `sqlite3` may be missing: `DB` reads factory.db read-only with Python.

## 1. The smoke profile, the slots and the tracker

One required check, `marker`, fails on the host when the tree holds `m4-fail.txt` and passes in the agent's sandbox
(`UV_OFFLINE=1` there), so a task asking for that file fails its checks deterministically and the agent cannot see it.

```bash
python3 - "$M4/repo/.task-loop.json" <<'EOF'
import json, sys
checks = [{"name": "marker", "argv": ["sh", "-c", 'test -n "$UV_OFFLINE" || ! test -e m4-fail.txt'], "timeout": 30}]
json.dump({"setup": [["just", "bootstrap"]], "checks": checks, "required": ["marker"], "target": "main"},
          open(sys.argv[1], "w"), indent=2)
EOF
G -C "$M4/repo" commit -qam "m4 smoke profile" && G -C "$M4/repo" push -q origin main
TL profile show --checkout "$M4/repo" --at HEAD   # setup just bootstrap; check marker; required marker
TL slot adopt "$M4/repo"     # not_listed .../slots/<repo_id>/s1 and s2 (exit 1); make both worktrees, adopt again:
for s in s1 s2; do P="$M4/slots/<repo_id>/$s"; mkdir -p "$(dirname "$P")" && G -C "$M4/repo" worktree add -q --detach "$P"; done
TL slot adopt "$M4/repo"     # s1, s2 adopted (exit 0)
DB 'pragma user_version'     # 14
mkdir "$M4/tracker" && cd "$M4/tracker" && git init -q && bd init --non-interactive --skip-hooks --skip-agents -p m4 -q
T() {  # T NAME TITLE DESCRIPTION [LABEL...]: create a task, record NAME=id in $M4/tasks
  local id; id=$(cd "$M4/tracker" && bd create "$2" --silent) && (cd "$M4/tracker" && bd update "$id" -d "$3" -q)
  for l in "${@:4}"; do (cd "$M4/tracker" && bd label add "$id" "$l" -q); done; echo "$1=$id" >> "$M4/tasks"; . "$M4/tasks"; }
OWNER="This task cannot be planned: it needs a decision only the repository owner can make (whether the smoke file \
should be named after the moon or after the sun), and nothing in the repository or this text decides it. Do not guess \
and change nothing: answer needs_owner and name the decision."
FILE() { echo "Create the file m4/$1.txt containing the single line '$1'. Change nothing else; no tests are needed."; }
```

## 2. First rounds: a needs_owner plan (A), failed checks (B), a clean task (C)

```bash
T A "M4 owner decision" "$OWNER" auto
T B "M4 failing marker" "Create the file m4-fail.txt (repository root) containing the line 'fail'. Change nothing else." auto
T C "M4 clean file" "$(FILE C)" auto
RUN auto        # tab A (record its pid: `pgrep -n -u "$USER" -f "runner/.venv/bin/tl --config $M4/config.toml step rounds"`
                # is only a hint; verify with ps -o pid=,user=,command=)
tail -f "$M4/artifacts/rounds.log"   # tab B
```

Keep-awake, while these rounds run (step 8 covers the exits):

- `rounds.log` has `rounds keep_awake started pid=<h>` (or `rounds keep_awake unavailable:<why>` and one stderr line).
- `ps -o pid=,ppid=,stat=,command= -p <h>`: `systemd-inhibit ... --who=taskloop ... tail --pid=<rounds pid> -f
  /dev/null`, or a zombie (`Z`) child of rounds when the inhibitor was refused; `systemd-inhibit --list` names
  `taskloop` only on a host whose logind grants it (OrbStack: `Access denied`, plan section 27; record what is seen).

Expect (the order between tasks varies):

- **A**: `A plan start started <a1>`, then `A plan hold held failed:needs_owner <a1>` once, then nothing more for A.
  `SHOW A`: `Next: on_hold`, `Hold: failed:needs_owner at ...`, `Hold tracker: auto removed, held added, commented`,
  `Hold claim: returned`, the `on_hold` guide (edit, then `bd label add <A> auto`). `bd show A`: `OPEN`, no assignee,
  labels `held` (no `auto`); `bd comments A`: one comment by `taskloop` starting `taskloop hold: failed:needs_owner`,
  the quoted explanation, `Evidence:`, the claim line ("removed `auto` and added `held` ... returned its claim") and the
  answer lines. `DB "select attempt_id,reason,labels,commented_at is not null,cleared_at from task_hold"`.
- **B**: plan, implement (adds `m4-fail.txt`), `check advance started`, then `B check hold held failed:marker:failed
  <b2>` once. Comment: `Failed checks: marker failed <log>`; the slot parked, claim returned; `bd show B` open,
  unassigned, `held`, no `auto`; `task/B` on origin holds X (`G -C "$M4/remote.git" log -1 task/<B>`).
- **C**: plan, implement, check, then quiet at `Next: land` (`TL step list`: `check ... collected passed land`).
- **Other tasks unaffected**: a hold never stops another task's advance or an admission (`round moves=` lines go on);
  the slots are reused (`TL step list` shows the next task in a slot after a hold freed it).

## 3. A hand-started failing task is never held (F)

```bash
T F "M4 hand started" "$OWNER"          # no label: rounds never take it
TL step start "$F" --backlog m4 --tracker-root "$M4/tracker" --checkout "$M4/repo" --model <model> --effort low \
  --minutes 20                          # needs a free slot: wait for one if `refused:no_free_slot`
```

- The plan fails `needs_owner`; the running rounds report it once (`F plan report ...`), never `hold`.
- `SHOW F`: `Next: done`, `Result: collected needs_owner` (or the result's own words), no `Hold:` line;
  `DB "select label from attempt where task_id='$F'"` is empty (NULL); no `task_hold` row for F.
- `bd show F`: `IN_PROGRESS`, assignee `taskloop`, no `held` label, no comment (`bd comments F` empty).

## 4. A closed task's hold writes nothing (G)

```bash
T G "M4 closed while planning" "$OWNER" auto
# when rounds.log shows `<G> plan start started`, while the plan runs:
(cd "$M4/tracker" && bd close "$G" --force --reason "m4: closed by the person while planning")
# without --force bd refuses: `assignee is "taskloop", actor is "<you>"; reclaim or use --force`
```

- Once the plan concludes: `G plan hold held failed:needs_owner <g1>` once; `DB`: the hold row `labels` `closed`,
  `commented_at` NULL; `SHOW G`: `Next: on_hold`, `Hold tracker: ... closed ...`, `Hold claim:` returned or not held.
- `bd show G`: `CLOSED` (not reopened), labels exactly as before the hold (`auto`, no `held`), no comment. The slot
  parked (the other task can use it); the release row's claim `not_held` (`DB "select * from slot_release ..."`).

## 5. `kill -9` of an implement entry: a pending hold, `tl step start` refused, the dirty slot cleared (E)

```bash
T E "M4 killed entry" "$(FILE E) Before creating the file, run 'sleep 60' in the shell." auto
# when `SHOW E` reads `Step: implement` and `Entry: running (pid <N> ...)`:
ps -o pid=,user=,command= -p <N>           # .../runner/.venv/... -m taskloop.attempt_entry ... m4 <E> ...: verified
kill -9 <N>
```

- The next rounds see `stuck:entry_lost` and hold E: `E implement hold pending abandon <word> <e2>` with `<word>` one
  of `unsettled:worker_alive` (the agent outlived its entry), `unsettled:worker_unknown`, `held:slot_dirty` (all
  accepted). `TL step list --stuck` lists E with `hold` and the hold guide. `bd show E`: `IN_PROGRESS`, assignee
  `taskloop` (the claim is still held), labels `held` (no `auto`). For `worker_alive`/`slot_dirty` one comment naming
  the pid or the slot and saying the claim is still held; for `worker_unknown` none yet.
- While pending: `TL step start "$E" ...` (as in step 3) answers `refused:held` with its guide; nothing changes.
- The agent may leave nothing (M4 run: the worker ended about a minute after its entry and the slot was clean, so the
  hold went `worker_alive` then `held` with no `slot_dirty`). For the dirty slot, step 5b.
- Clear the cause: wait for the agent (its pid from `SHOW E`, verified; or stop it by that verified pid), then save and
  remove what it left in the slot (`G -C <slot> status --porcelain=v1`; `G -C <slot> checkout -- .` for tracked files,
  remove the untracked ones by path). The pending line changes as the cause changes (written once per word).
- The next round: `E implement hold held stuck:entry_lost <e2>`; `SHOW E` `on_hold`, `Hold claim: returned`; `bd show
  E` open, unassigned; still exactly **one** comment (`bd comments E`); the slot clean at its park point.

### 5b. A dirty slot, made on purpose (E2)

A task like E (`T E2 ...`); while its implement runs (`SHOW E2`: `Entry: running (pid <N>)`, `Worker: ... pid <W>`),
write a leftover into its slot (`echo leftover > <slot>/m4-leftover.txt`, standing in for the agent's uncommitted work),
then `kill -9 <W>` and `kill -9 <N>`, each verified first (`codex exec` and `taskloop.attempt_entry ... m4 <E2>`).
Expect `E2 implement hold pending abandon held:slot_dirty <e>`, one comment naming the slot ("still holds the claim:
slot <path> has files left by this attempt"), `bd show E2` in progress for `taskloop` with `held`. Stop and restart the
rounds here (they continue the pending hold). Remove the file: the next round writes `E2 implement hold held
stuck:entry_lost <e>`, the slot is clean at its park point, still one comment.

## 6. Interrupted rounds continue; a moved task branch is held (D)

Rounds started from a script or an agent's shell: run them as `bash <script>` with `echo $$ > rounds.pid; exec tl ...`
inside (NixOS has no `/bin/bash` for a shebang), and send SIGINT to that verified pid for "Ctrl-C".

```bash
T D "M4 moved branch" "$(FILE D)" auto
# when D's implement runs (`<D> implement advance started`): Ctrl-C once in the rounds' tab (SIGINT to the verified pid)
```

- Rounds print `Rounds stopped: interrupted.`, exit 0; the implement entry keeps running (`SHOW D`: `Entry: running`).
  The keep-awake helper is gone (step 8's check).
- When `SHOW D` says the implement attempt concluded (verified and published by its entry, or waiting for `publish`),
  move the person's **local** `task/<D>` to a commit that does not contain X: `G -C "$M4/repo" branch -f "task/$D"
  main`. The check admission reads the local `task/<id>` first, the remote-tracking one only without it, and asks
  whether it **contains** X: a fast-forward pushed to origin's `task/<D>` (below, as first written) is not
  `branch_moved` there; the land refuses it later (`refused:branch_moved`, "not exactly the checked X"). First-written
  variant, kept for the land refusal:
  `G -C "$M4/other" fetch -q origin "task/$D" && G -C "$M4/other" checkout -q -B "task/$D" FETCH_HEAD && echo moved >
  "$M4/other/m4-moved.txt" && G -C "$M4/other" add m4-moved.txt && G -C "$M4/other" commit -qm "someone moves task/$D"
  && G -C "$M4/other" push -q origin "task/$D"`.
- `RUN auto` again (**rounds restart continuing**): unfinished work continues (pending holds, running attempts); D's
  advance (or publication) is refused `branch_moved` and held: `D ... hold held branch_moved <d2>` once; the comment
  has the line "Restore task/<D> to contain <X>, or delete it ...".

## 7. The label rule (H), then answers re-ingested (B, H)

```bash
T H "M4 label rule" "$OWNER" auto auto2
# when `<H> plan start started`: Ctrl-C the rounds once; wait until `SHOW H` says the plan concluded (needs_owner)
RUN auto2       # a round under another label, before H's hold ran
```

- The `auto2` round holds H under its **stored** label: `H plan hold held failed:needs_owner <h1>`; `bd show H`:
  labels `auto2` and `held`, no `auto`. Later `auto2` rounds do not take H again (`H plan skip abandoned` once, or no
  line), though H carries `auto2`.
- Stop, `(cd "$M4/tracker" && bd label add "$H" auto)`, `RUN auto`: H is taken again at plan (`H plan start started
  <h2>`, `DB "select seq,label from attempt where task_id='$H'"` shows a later seq with label `auto`), `H plan hold
  cleared ...` or the old row `cleared` (a re-hold owns `held`), then H fails again and is held again (`held` stays).
- **Answer B** (after a fix): `(cd "$M4/tracker" && bd update "$B" -d "Remove the file m4-fail.txt if it exists on
  the task branch and create m4/B.txt containing the line 'B'. Change nothing else." && bd label add "$B" auto)`.
  Expect `B plan start started <b3>` (new seq, label `auto`), on the **existing** `task/<B>` (the plan agent finds
  `m4-fail.txt` there; `G -C "$M4/remote.git" log --oneline main..task/<B>` keeps the earlier commits), `hold cleared`
  for B's old row, `bd show B` without `held`, and B reaching `Next: land`.

## 8. Keep-awake exits: Ctrl-C once, Ctrl-C twice, `kill -9`

For each, read the helper pid `<h>` from the latest `rounds keep_awake started pid=<h>` line and the rounds pid `<r>`
(verified), then:

1. Ctrl-C once (SIGINT to `<r>`): `Rounds stopped: interrupted.`, exit 0, no traceback; within two seconds `ps -o
   pid=,stat=,command= -p <h>` prints nothing (and no `systemd-inhibit`/`tail --pid=<r>` process of this run exists).
2. Ctrl-C twice (two SIGINTs to `<r>`, the second while the round still runs): rounds end (exit 130 or the rounds'
   own interrupted line), no traceback from the helper; `<h>` gone within two seconds.
3. `kill -9 <r>`: the helper ends by itself (`tail --pid` polls each second) or, refused at once, is reaped by init;
   `<h>` gone within two seconds. Restarting rounds afterwards continues (the rounds lock is free; nothing stuck).

## 9. Git read timeout (G1/G2): BLOCKED

Needs git-porcelain 0.17.0 released and pinned (plan section 14, 21). Not run.

## 10. Land and the tracker at the end

- `TL step land "$C" --backlog m4 --checkout "$M4/repo" --minutes 20` (and `$B` when it reached `land`), from a
  shell with no push bar: `pushed: ...`, `Closed: closed` (same tree when origin's `main` did not move: no slot).
- `(cd "$M4/tracker" && bd list --label held)` lists exactly the held, unanswered tasks (A, D, E, H; not B, not G,
  closed). `TL step list` at the end; `TL step list --stuck` empty or only what is explained.

## 11. Paste back and cleanup

The whole `rounds.log`, `TL step show` of every task after its hold, `TL step list`, `bd show` and `bd comments` of
each task, the `task_hold` and `attempt (task_id, seq, step, label)` rows, the keep-awake `ps` lines. Record findings
in `docs/design/tl-8bh9.14.9/m4-smoke-findings.md`. Then: stop rounds (verified pid), `G -C "$SRC" worktree remove
--force` for every worktree of `$M4` registered in `$SRC` (the runner) and `G -C "$SRC" worktree prune`, `chmod -R
u+rwX "$M4" && rm -rf "$M4"`, restore `~/.config/mise/config.toml` from `$SAVE` and compare its sha256 with
`$SAVE/mise.before`, and confirm no process with `$M4` in its command line is left.
