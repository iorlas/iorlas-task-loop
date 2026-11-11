# M3 live smoke: land and close with `tl step land` (owner-run, after L5)

**Status: not run.** Milestone M3 of the [roadmap](../self-hosting-roadmap.md) is reached when this run passes: tasks of
**this repository**, taken through plan, implement and the check step by `tl step rounds` from a runner worktree, are
landed by the person's `tl step land TASK` on a scratch bare remote: one squash commit S onto origin's `main` at O,
validated when its tree is not X's, pushed never forced from the person's checkout, and the task closed in the scratch
tracker (design: [plan.md](plan.md) sections 1, 3-14, 21; as built: sections 25-29). Linux only. Run by Denis, or by an
agent Denis authorized for that one run. Scratch remote, scratch tracker, scratch factory.db only: nothing reaches the
real `origin`, the real tracker or `~/.local/state/task-loop`. Never open or paste `auth.json` (stat it only). Kill
nothing by name: every pid below is checked first (`ps -o command=`, `lsof -d cwd`).

The layout is the [M2 runbook](../tl-8bh9.14.6/live-smoke.md)'s (read it and the [M2
findings](../tl-8bh9.14.6/m2-smoke-findings.md)) with a new folder `$M3`, a new factory.db (schema **v13**), **two
slots**, a second scratch clone `$M3/other` that plays "someone else" pushing to origin's `main`, and the shell
function `TL`. Every `tl step land` runs in the person's own shell (never one carrying an agent's push bar), with
`--checkout "$M3/repo"`; `LAND` below is that command.

## 0. Runner, layout and machine config

```bash
M3=$HOME/tl-smoke/m3; mkdir -p "$M3" && cd "$M3"
SRC=$HOME/PATH/TO/a-checkout-of-this-repository             # edit
SHA=<the L5 commit or a later one>                           # edit: the successor commit under test
G() { git --no-optional-locks -c core.hooksPath=/dev/null "$@"; }
G -C "$SRC" cat-file -e "$SHA:docs/design/tl-8bh9.14.8/live-smoke.md" && G -C "$SRC" merge-base --is-ancestor 1f0912818 "$SHA" \
  && echo "SHA has L5"
mise settings add trusted_config_paths "$M3"                 # before any `just` under $M3 (M1 finding 1)
G -C "$SRC" worktree add --detach "$M3/runner" "$SHA"       # the runner: the factory version under test, never edited
(cd "$M3/runner" && just install)
TL() { "$M3/runner/.venv/bin/tl" --config "$M3/config.toml" "$@"; }
G clone -q --bare "$SRC" "$M3/remote.git"                    # scratch origin
G -C "$M3/remote.git" update-ref refs/heads/main "$SHA"
G -C "$M3/remote.git" for-each-ref --format='%(refname)' 'refs/heads/task/*' | while read -r ref; do
  G -C "$M3/remote.git" update-ref -d "$ref"; done
G clone -q --branch main "$M3/remote.git" "$M3/repo"         # the person's checkout
G clone -q --branch main "$M3/remote.git" "$M3/other"        # someone else's clone, for hand pushes to main
mkdir -p "$M3/state" "$M3/artifacts" "$M3/slots"
printf 'db = "%s"\nartifacts = "%s"\nslots_root = "%s"\nslot_count = 2\n' \
  "$M3/state/factory.db" "$M3/artifacts" "$M3/slots" > "$M3/config.toml"
TL config show                                               # every value under $M3; slot_count 2
env | grep -c '^UV_OFFLINE=\|^GIT_CONFIG_' || true           # 0: this shell is the person's, no push bar
LAND() { TL step land "$1" --backlog m3 --checkout "$M3/repo" --minutes 30 "${@:2}"; }
PERSON() {  # the person's checkout as Git sees it: HEAD, local main, the index file's digest
  G -C "$M3/repo" rev-parse HEAD refs/heads/main; sha256sum "$(G -C "$M3/repo" rev-parse --absolute-git-dir)/index"; }
```

The prerequisites of M1 section 0 apply unchanged (factory.db new, db and slots not nested, `.t/<slot>` at most 64
bytes, mise trust, `codex` and `bd` on `PATH`, network for `setup`). `sqlite3` reads factory.db read-only
(`sqlite3 -readonly "$M3/state/factory.db" ...`); nothing edits it.

## 1. The smoke profile and the tasks

M2's `P base` profile (copy the `P` function from the M2 runbook section 1, with `$M2` read as `$M3`): checks `check`,
`test`, `report`, `slow` (`sleep 60` on the host), required `check`, `test`. Every block, the land's validation
included, runs every check of the profile at S, so a validation takes about 90 s and `slow` gives a minute to act.

```bash
P base
TL slot adopt "$M3/repo"      # then make the two worktrees it names, as in M2 section 2, and adopt again: s1, s2 adopted
mkdir "$M3/tracker" && cd "$M3/tracker" && git init -q && bd init --non-interactive --skip-hooks --skip-agents -p m3 -q
for name in A B C D E F G H; do  # each a small test-only task of this repository, as in M2 section 2
  id=$(bd create "Test one module's words ($name)" --silent); echo "$name=$id" >> "$M3/tasks"
  bd update "$id" -d "Add tests/steps/test_m3_$name.py with pytest functions for one small pure function of \
src/taskloop/round_log.py or step_guide.py of your choice. Change no source file." --acceptance "The new test file passes; \
just check and just test pass."
  bd label add "$id" auto
done
. "$M3/tasks"
cd "$M3" && TL step rounds --backlog m3 --tracker-root "$M3/tracker" --checkout "$M3/repo" --label auto \
  --model <model> --effort <effort> --minutes 90       # tab A; tab B: tail -f "$M3/artifacts/rounds.log"
```

Wait until `TL step list` shows every task `check ... collected passed ... land` (no `done` row for a passed check;
rounds write nothing for `land`). All eight were cut from the same `main`. **Stop the rounds (Ctrl-C once)** before
section 2, and keep them stopped unless a step says otherwise.

## 2. The summary changes nothing

```bash
PERSON > "$M3/person.before"; G -C "$M3/remote.git" rev-parse main > "$M3/main.0"
LAND "$A" --summary
```

- `Checks: <c> passed at X <X> (main at <O>)`, `Check: check passed`, `Check: test passed`, `Required at origin main
  <O>: same`, `Origin main: <O>; same tree as X, no checks`, `Message:` then `  Test ... (<A>)`, a blank line, `Squashed
  from task/<A> at <X>:` with the branch's subjects, a blank line, `Task: <A>`, `Checked: <c> passed at <X>` (`Plan:` when
  the plan file exists at X), then `Diff: git diff <base>..<X>` and `Nothing was recorded, reserved, pushed or closed`.
- Exit 0. `sqlite3 -readonly "$M3/state/factory.db" 'select count(*) from land_candidate'` is 0;
  `G -C "$M3/remote.git" rev-parse main` equals `main.0`; `bd show "$A"`: `in_progress`, `taskloop`; `PERSON` equals
  `person.before`.
- `LAND "$A" --summary --json | python3 -m json.tool`: `"status": "summary"`, `"state": "same_tree"`, `"again": false`.

## 3. The same tree lands with no slot

```bash
LAND "$A"; echo "exit $?"
S=$(G -C "$M3/remote.git" rev-parse main); X=$(sqlite3 -readonly "$M3/state/factory.db" \
  "select a.end_commit from attempt a join checks_attempt c on c.after_attempt_id=a.attempt_id join land_candidate l on \
l.checks_attempt_id=c.attempt_id where a.task_id='$A'")
```

- Output: `pushed: <A> (backlog m3) on origin main; S pushed to origin's main by this land`, `Candidate 1 (<id>): S <S>
  onto origin main at <O>; same tree as X, no checks`, `Pushed: origin main at <S>`, `Closed: closed`, `Tracker: closed
  locally, not synced (bd dolt push shares it)`, `Next: ...git pull --ff-only...`; exit 0. No `Land check:` and no slot
  used (`TL slot`-wise: `sqlite3 ... 'select slot from land_candidate'` is NULL).
- Origin's `main` is S: `G -C "$M3/remote.git" rev-parse "$S^@"` prints exactly one parent, `main.0` (O);
  `G -C "$M3/remote.git" rev-parse "$S^{tree}" "$X^{tree}"` print the same tree; `G -C "$M3/remote.git" log -1
  --format='%an <%ae>%n%cn <%ce>%n%B' "$S"` shows the person as author and committer and section 9's message, no
  co-author trailer.
- `bd show "$A"`: `closed`, reason `Landed <S> on main (task/<A> at <X>)`. `TL step show "$A" --backlog m3` ends with
  `Land: candidate 1 ...; same tree as X, no checks`, `Land required: check, test (origin main at <O>; same as the
  checks)`, `Land result: same_tree`, `Pushed: origin main at <S>, <time>`, `Closed: <time> (closed)`, the `Tracker:`
  line, `Next: landed` and its guide. `TL step list`: `landed`.
- **The person's checkout is untouched**: `PERSON` equals `person.before` (HEAD, `refs/heads/main` and the index file;
  not `git status`, which reports the checkout behind the fetched origin). The land only moved
  `refs/remotes/origin/main` in it.
- Rerun `LAND "$A"`: `already_landed: ... landed before this call: nothing called`, exit 0; origin's `main` and
  `bd show "$A"` unchanged.

Do **not** `git pull` in `$M3/repo` yet: the next sections need tasks whose O is the old `main`.

## 4. Refusals before anything is written, then a moved `main` validates S in a slot

First, against B (`Next: land`), each refusal changes nothing (`land_candidate` rows, origin's `main`, `bd show "$B"`):

- The push bar: `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=url.delegate-push-refused://.pushInsteadOf GIT_CONFIG_VALUE_0= LAND
  "$B"`: `refused:push_barred`, exit 1.
- A push URL elsewhere: `G clone -q --bare "$M3/remote.git" "$M3/elsewhere.git"`, `G -C "$M3/repo" config
  remote.origin.pushurl "$M3/elsewhere.git"`; `LAND "$B"`: `refused:push_url`, exit 1, nothing pushed to either remote.
  Then `G -C "$M3/repo" config --unset remote.origin.pushurl`.
- **BLOCKED until git-porcelain 0.17.0 is released and pinned (plan section 27.1 item 4): do not run.** The multi-URL push
  guard: with a second push URL (`G -C "$M3/repo" config remote.origin.pushurl "$M3/remote.git"`, then `G -C "$M3/repo"
  config --add remote.origin.pushurl "$M3/elsewhere.git"`), or a second `url`, the land must refuse `push_url` with
  nothing pushed to either remote. Today only the first URL is compared, so this residual stands (section 15); run this
  step only at a runner whose `uv.lock` pins git-porcelain 0.17.0 or later and whose `land_push.same_url` reads
  `remote_urls`, and unset both values afterwards.

Then the land:

```bash
LAND "$B"          # tab A
TL step show "$B" --backlog m3   # tab B, while it runs (about 90 s)
```

- While it runs: `Land: candidate 1 (...) onto origin main at <S_A>: <S_B>; merged onto a moved main, checks run again`,
  `Land slot: s1, held` (or s2), `Land process: running (pid <tl pid>, started ...)`, `Land check:` lines
  (`unfinished, process group <pgid>` for the running one), `Land result: pending`, `Next: land`.
- Then the land prints `pushed: ...`, `Candidate 1 (...): S <S_B> onto origin main at <S_A>; checks passed on S`,
  `Pushed:`, `Closed: closed`, the `Tracker:` line; exit 0. `TL step show "$B"`: `Land slot: s1, released <time>, parked
  at <D>`, each `Land check: <name> passed, exit 0, ...; log <dir>/check-1-<name>.log`, `Land result: passed`,
  `Next: landed`. The slot is clean at D: `G -C <slot> status --porcelain=v1 --ignored=no` empty, `rev-parse HEAD` is D.
- Origin's `main` is S_B, its one parent S_A, its tree holds both tasks' files. Same tree (section 3) against moved
  `main` (here) is the rule that decides whether the checks run again; record both durations.

## 5. Interrupts: Ctrl-C, then `kill -9` of the verified land process

Task C (its O is the old `main`, so it validates):

1. `LAND "$C"`; when `TL step show "$C"` shows `Land check: slow unfinished, process group <pgid>`, press Ctrl-C in the
   land's shell. The land ends (Python's `KeyboardInterrupt`; `stream_proc` stops the check's tree): `ps -o pid= -g
   <pgid>` prints nothing. `TL step show "$C"`: `Land result: pending`, `Land process: gone (pid ...)`, `Next: land`.
2. `LAND "$C"` again: the reconcile marks block 1's unfinished check `interrupted` and the block repeats whole
   (`check-2-*.log`); before `slow` ends, take the land process's pid from `TL step show "$C"` (`Land process: running
   (pid <N>, ...)`), verify it (`ps -o command= -p <N>` shows `.../runner/.venv/bin/tl --config ... step land <C> ...`),
   then `kill -9 <N>`. The check keeps running in its own session (`ps -o pid=,sid=,command= -g <pgid>` lists it).
3. `LAND "$C"` while it runs: `tl step land: unavailable:checks:running` with the `checks` guide, exit 3; nothing reset
   (`Land result: pending`). Once `slow` ended (`ps -g <pgid>` empty), `LAND "$C"`: block 3 runs whole, then
   `pushed:`, `Closed: closed`. `TL step show "$C"`: the land process is the last one's pid.

## 6. `target_moved`: someone pushes to `main` during the validation

Task D. Start `LAND "$D"`; while its block runs (`Land check: slow unfinished`), in another shell push a commit to origin's
`main` from the other clone:

```bash
G -C "$M3/other" pull -q --ff-only && echo m3 > "$M3/other/m3-moved.txt" && G -C "$M3/other" add m3-moved.txt \
  && G -C "$M3/other" commit -qm "someone else lands" && G -C "$M3/other" push -q origin main
```

- The land answers `tl step land: unavailable:target_moved` (exit 3), nothing pushed: origin's `main` is the hand
  commit. `TL step show "$D"`: `Land superseded: moved`, `Next: land`.
- `LAND "$D"`: candidate 2 onto the new `main`, validated (its tree differs), pushed and closed; `TL step show "$D"`:
  `Land: candidate 2 ...`.

## 7. `remote_rejected`, the `landing` abandon refusal, `--withdraw`, and a lost answer

Install a scratch `pre-receive` hook on the bare remote that refuses `main` (the land's own Git runs with hooks off; this
hook runs on the remote side):

```bash
cat > "$M3/remote.git/hooks/pre-receive" <<'EOF'
#!/bin/sh
while read -r old new ref; do [ "$ref" = refs/heads/main ] && { echo "main is protected (m3 smoke)"; exit 1; }; done; exit 0
EOF
chmod +x "$M3/remote.git/hooks/pre-receive"
```

1. `LAND "$E"`: validates, then `tl step land: refused:remote_rejected` with the `remote_rejected` guide, exit 1
   (if it reads `unavailable:git`, record it as a finding: the remote refusal was classified as a local hook's).
   `TL step show "$E"`: `Land result: passed`, no `Pushed:`, `Next: land`.
2. `TL step release "$E" --backlog m3 --abandon`: `refused:landing` with its guide; nothing changed (`bd show "$E"`
   still `in_progress`, `TL step show` unchanged).
3. `LAND "$E" --withdraw`: `withdrawn: <E> ...; candidate 1 (...) superseded, S <S> was not on origin's main`, exit 0;
   `Land superseded: withdrawn`. Now `TL step release "$E" --backlog m3 --abandon` goes through (no land candidate holds
   a slot: the checks attempt, then the implement attempt with `claim unclaimed`); `bd show "$E"`: `open`.
4. **Lost answer.** `LAND "$F"`: `refused:remote_rejected` as in 1. Remove the hook (`rm
   "$M3/remote.git/hooks/pre-receive"`), then push S by hand as if the land's push had reached origin but its answer
   was lost: `S_F=$(sqlite3 -readonly "$M3/state/factory.db" "select l.commit_sha from land_candidate l join
   checks_attempt c on c.attempt_id=l.checks_attempt_id join attempt a on a.attempt_id=c.after_attempt_id where
   a.task_id='$F'")`, `G -C "$M3/repo" push -q origin "$S_F:refs/heads/main"`. Then `LAND "$F"`: `already_pushed: ...
   origin's main was found to hold S: recorded, not pushed again`, `Closed: closed`; the remote's reflog (or `G -C
   "$M3/remote.git" rev-parse main`) shows no second update.

## 8. A hand land is `no_change`; `--no-change` records it

Task G: land its change by hand from the other clone, as M2's hand land did:

```bash
G -C "$M3/other" pull -q --ff-only && G -C "$M3/other" fetch -q origin "task/$G" \
  && G -C "$M3/other" merge -q --squash FETCH_HEAD && G -C "$M3/other" commit -qm "hand land $G" \
  && G -C "$M3/other" push -q origin main
```

- `LAND "$G"`: `refused:no_change` with its guide, exit 1, nothing recorded.
- `LAND "$G" --no-change`: `no_change: ... origin's main already held X's changes: recorded with no push`, `Closed:
  closed`; `bd show "$G"`: reason `Already on main at <O>`; origin's `main` unchanged by the land. `LAND "$G"` again:
  `already_landed`.

## 9. A conflict is refused with its path, nothing recorded

Task H: read the path its X adds (`G -C "$M3/repo" diff --name-only <O>..<X_H>`; one new test file), then commit a
different file at that same path to origin's `main` from the other clone (`pull --ff-only`, write it, commit, push).
`LAND "$H"`: `refused:conflict` naming that path (`1 paths: ...`), exit 1; `sqlite3 ... "select count(*) from
land_candidate l join checks_attempt c on c.attempt_id=l.checks_attempt_id join attempt a on
a.attempt_id=c.after_attempt_id where a.task_id='$H'"` is 0. Then abandon it (`TL step release "$H" --backlog m3
--abandon`): no candidate, so it goes through.

## 10. Refusals after a land

- `TL step release "$A" --backlog m3 --abandon`: `refused:landed` with its guide; nothing changed.
- `LAND "$A" --summary --withdraw`: usage error, exit 2.

## 11. Afterwards

- `G -C "$M3/repo" pull --ff-only`: the person's `main` fast-forwards to origin's; their checkout was never written by a
  land before this.
- `TL step list`: A, B, C, D, F, G `landed`; E and H abandoned (`start`). Rounds started again write nothing for the
  landed tasks and never re-admit the abandoned ones (`implement skip abandoned` once).
- Nothing ran `bd dolt push`: the scratch tracker has no remote.

## 12. Paste back

`TL config show`; both `TL slot adopt`; `TL profile show --at HEAD`; the whole `rounds.log`; each `LAND` command's output
and exit code; `TL step show` of each task after its land; `TL step list` at the end; `bd show` for every task;
`PERSON` before and after section 3; the `git log -1 --format=...` of every S on origin; the slot's `status
--porcelain=v1 --ignored=no` and HEAD after each validation; the `ps` lines of section 5. Record the findings in
`docs/design/tl-8bh9.14.8/m3-smoke-findings.md`, as for M1 and M2, then remove `$M3` (restore mise's trusted paths).
