# tl-8bh9.14.9: questions and holds, and the rest of the unattended loop (block B7 with B11 and B13, milestone M4)

Design, 2026-11-12, against ffbb689c4 (M1, M2 and M3 smokes passed). Docs only: nothing built or run, except one
measurement of bd 1.3.1 in a scratch tracker under `~/tl-smoke` (section 5.3), removed afterwards. Read: CLAUDE.md,
[glossary](../../glossary.md), [roadmap](../self-hosting-roadmap.md) (B7, B10, B11, B13, M4, D1-D14, O1-O6, section 6),
[structured questions](../tl-8bh9.6.1/plan.md) and its [balanced design](../tl-8bh9.6.1/balanced-design.md),
[keep-awake inventory](../tl-8bh9.4.6/plan.md), [the checks step](../tl-8bh9.14.6/plan.md) (O2's M2 reading),
[land and close](../tl-8bh9.14.8/plan.md) and its [M3 findings](../tl-8bh9.14.8/m3-smoke-findings.md), and `round`,
`rounds`, `attempt_status`, `check_status`, `land_status`, `operations` (`release_task`), `slot_release`, `selection`,
`tracker`, `tracker_client`, `steps`, `factory_schema` (v13), `git_views`, `cli_composition`, the installed
`beads_client` 0.2.0, `git_porcelain` 0.16.0 and `stream_proc`.

The owner is away and asked for autonomous decisions. Each one is marked **decided here** (a recommendation, open to
veto). Owner decisions D1-D14 are cited by number. Section 21 lists blocking owner questions: none.

## 1. What changes for the owner

The person labels tasks `auto`, starts `tl step rounds ... --label auto` before going to bed and leaves it. The laptop
does not sleep while rounds run (B11). In the morning:

- tasks that went well wait at `Next: land` (unchanged since M3);
- every task the factory stopped on is **held**: it carries a comment from `taskloop` that starts `taskloop hold:
  <reason>` and says what happened, where the evidence is and how to answer; its label `auto` is gone, the label
  `held` is on it, and its claim is returned (open, unassigned). `bd list --label held` lists them;
  `tl step list` shows them as `on_hold`;
- if three tasks were held in a row with no success between them, rounds stopped by themselves (`rounds stopped
  breaker`), so a broken login or model name holds at most three tasks.

To answer a held task the person edits its description or acceptance criteria (the agent reads those, never comments)
and runs `bd label add <id> auto`. The next round takes it again like a new task and starts it at plan, on its existing
`task/<id>` as it is (D3, D4). Nothing else changes: land stays person-run.

## 2. What a hold is

**Hold** (glossary entry, decided here): a task the factory will not advance until a person acts. The factory has
recorded why in factory.db, written the reason on the task in the tracker, removed the approval label, added `held`,
and abandoned the task's current attempt (slot parked, claim returned). A hold is an abandon plus a tracker note; it is
never a new kind of attempt, step or wait.

Words, kept apart from the existing ones: the `Next` words are **`hold`** (the hold is due or half done: the round
finishes it) and **`on_hold`** (done: waiting for the person). The tracker label is `held`. The release word
`held:<reason>` (a slot stays reserved) and the slot custody `hold` in code keep their meanings; the glossary row
"reserved / locked / held" gains one sentence saying that `on_hold` and the label `held` are about a task, not a slot.

Not a hold: a structured question with choices, answer revisions or a local wait (tl-8bh9.6.1, deferred). A held task
has no open question object; its question is the comment, its answer is the edited task text plus the label.

## 3. Which conditions hold the task

One pure rule, `hold.cause(view) -> str | None`, reads an `AttemptView` and returns the reason word, or None. The reason
is the word `tl step show` already prints; no new vocabulary.

| Condition (as the round sees it) | Hold? | Reason word | Notes |
|---|---|---|---|
| `Next: done`, result not succeeded (plan or implement: `needs_owner`, `incomplete`, `rejected:<rule>`, a run failure or timeout) | yes | `failed:<result reason>` (`failed:answer:needs_owner`, `failed:run:timeout`, `failed:rejected:<rule>`) | the agent's `explanation` goes into the comment |
| `Next: done` of a checks attempt `failed:<reason>` | yes (O2, decided in the roadmap's recommendation) | `failed:<reason>` as today (`failed:test:failed`) | each failed check's name and log path go into the comment |
| `Next: release`, result collected and not succeeded | yes | as `done` | the abandon parks the slot first (section 5) |
| `Next: repeats_exhausted` | yes | `repeats_exhausted:<repeat reason>` | the leftover listing goes into the comment |
| `stuck:expired_admitted`, `stuck:entry_lost`, `stuck:uncollected`, `stuck:conflict`, `stuck:setup_failed`, `stuck:checks_refused` | yes | the word | |
| `stuck:hung` | **no** (D7) | | an entry still runs past its deadline; the abandon's stop proof would refuse anyway. Reported once as today |
| `unknown`, `wait`, `start`, `verify`, `repeat`, `publish` (not refused), `advance` | no | | transient or progressing |
| `land`, `landed` | no | | the person's; a failed land is in front of the person who ran it |
| advance refused `claim_lost` | yes | `claim_lost` | the tracker write depends on who holds the task now (section 5.2) |
| advance refused `branch_moved` (plan to implement, implement to check) | yes | `branch_moved` | the comment says to restore or delete `task/<id>` |
| publish refused `branch_moved` | yes | `branch_moved` | today it is retried every round forever |
| advance or admission refusals about the round (`no_free_slot`, `deadline`, `database`, ...) or transient (`changed`, `abandoned`) | no | | |
| admission refusals of a not yet claimed task (`branch_held`, `branch_diverged`, `branch_name`) | **no, decided here** | | nothing is claimed (the start compensates its claim), so nothing is left claimed and silent; the skip line is written once and quieted as today. A hold needs an attempt to abandon; adding attempt-less holds is not worth a second shape |

## 4. Who owns what

| Fact | Owner | How |
|---|---|---|
| The task's attempt ended in a state the factory will not advance, the reason word, when, which approval label it removed, which tracker writes are done | factory.db (`task_hold`, section 8) | written by `hold_store` only |
| The slot parked and the claim returned | factory.db `slot_release` (abandoned, claim `unclaimed`/`not_held`) as today | the hold calls the existing abandon (`operations.release_task(abandon=True)`), never a copy of it |
| The reason for the person, the evidence paths, how to answer | tracker comment | written once; never read back by the factory |
| Approval to (re)start | tracker label (`auto`, the round's `--label`) | D3: read only at ingestion |
| "This task waits for a person", for finding it in the tracker | tracker label `held` | written by the hold, removed by the factory after the task is taken again (section 7.3); never read for control |
| The answer | the task's description and acceptance criteria | the plan agent's input already reads those (`tracker.inspect_task`) |

The factory never derives control state from the comment or from `held`. The only tracker facts it reads for control
are the ones it reads today (ready set with the label, status, assignee) plus, in the hold itself, status and assignee
to choose the fence (section 5.2).

## 5. The hold operation

### 5.1 Sequence

`hold.hold_task(ports, backlog, task_id, cause_view, reason, label) -> HoldMove`, the one application operation (the
round calls it; `tl step next` is a round). Each step is recorded, so a rerun does only what is missing:

1. **Record** (factory.db): insert the `task_hold` row for the task's current agent attempt A (`attempt_id`), with the
   cause's id (A itself, or A's latest checks attempt), the reason, the approval label and `held_at`. Fenced in the
   write: A is still the task's current attempt (`factory_schema.LATER` false), the cause is still current (for a
   checks cause: still A's latest checks attempt and not abandoned) and no hold row for A exists. A lost race is
   `refused:changed` and nothing else happens this round.
2. **Read** (tracker): unless `labels` is set, one `Bd.show`; what it says picks the rest (5.2).
3. **Comment** (tracker, once): unless `commented_at` is set or the task is closed or missing, `Bd.comment(task,
   text)` (section 6), then `commented_at`. A crash between the two writes the comment again on the rerun: accepted
   (one duplicate comment).
4. **Labels** (tracker): the fence `Bd.update(assignee=a, if_assignee=a)` with the assignee just read,
   `Bd.add_label(task, "held")`, `Bd.remove_label(task, label)`; then `labels`. `held` is added before the approval
   label goes, so a crash in between leaves the task claimed with both labels and the rerun finishes it.
5. **Abandon** (factory.db, slot, tracker claim): `operations.release_task(..., abandon=True)` as `tl step release
   --abandon` runs it (land candidate, then checks attempt, then the agent attempt; parks the slot; the fenced unclaim,
   never forced). Its own rows are the record. A refusal (`held:slot_dirty`, `unsettled`, `refused:landing`) leaves the
   hold due (`Next: hold`) and is retried by the next round, quiet in the log.

The hold is done when the row has `commented_at` (or `labels` is `closed`/`missing`), `labels`, and A's release is
abandoned with its claim no longer `kept` or `unclaiming`. Every bd call is capped at `claim_lease.BD_TIMEOUT_S`; any
failure is `unavailable:tracker` for this round, retried by the next.

Order, decided here: tracker writes before the abandon, because the unclaim makes the task ready again: if the claim
were returned first, a crash before the label step would leave an `auto` task with an abandoned attempt (today's
`abandoned` skip, silent). With the tracker first, a refused abandon (a dirty slot after a lost entry) still leaves
the reason, `held` and no `auto` on a task still claimed by `taskloop`, and `tl step show` says what keeps the claim.

### 5.2 Who holds the task now

| `Bd.show` says | Labels step | `labels` word | Comment |
|---|---|---|---|
| in progress, assignee `taskloop` | fence on `taskloop`, add `held`, remove the label | `moved` | yes |
| open, unassigned (the claim lapsed or was reverted) | fence on `""` (measured: `--assignee '' --if-assignee ''` works), same writes | `moved` | yes |
| assigned to another actor | none: never edit another actor's task labels | `not_ours` | yes |
| closed | none | `closed` | no (the person closed it; the abandon still frees the slot) |
| missing | none | `missing` | no |
| fence stale (exit 13, `precondition`) | nothing written | not set: retried next round | |

### 5.3 What bd 1.3.1 and beads-client 0.2.0 support (measured 2026-11-12, scratch tracker, removed)

- `beads_client.Bd` 0.2.0 already has `comment`, `add_label` (with an `if_assignee` fence by a same-value update),
  `remove_label`, `update(assignee=, if_assignee=)`, `unclaim(if_assignee=)` and `show` (with `labels`). **No shelf
  change is needed for B7.**
- `bd label remove` of an absent label exits 0; `bd label add` of a present one exits 0: both steps are idempotent.
- `bd update --remove-label X --add-label Y --if-assignee A` alone is refused ("label and parent edits are not covered
  by the guard"); with a field update (`--assignee A --if-assignee A`) it applies, and a stale guard (exit 13) writes
  nothing, labels included. beads-client 0.2.0's `update` has no label arguments, so H1 uses the fence update followed
  by the two label calls (the same accepted gap as `land_close`'s close). A later beads-client `update(add_labels=,
  remove_labels=)` would make it one guarded call; not needed for M4 (section 19).
- `bd unclaim --if-assignee taskloop` leaves status `open`, no assignee, labels untouched. `bd ready --label auto`
  lists an open task carrying both `held` and `auto`; `bd list --label held` lists only open ones by default.
- `bd comments add <id> <text>` keeps newlines; `bd comments <id> --json` shows `author: taskloop`.

## 6. The comment

Built by `hold_text.comment(...)`, a pure function. Fixed English, at most 6000 characters, control characters other
than newline removed from every quoted part:

```
taskloop hold: <reason>
Step <step>, attempt <number> (<attempt id>), <UTC time>; task branch task/<id> at <X or "not published">.
The agent explained: <explanation, at most 2000 characters, from the stored valid answer>
Failed checks: <name> <conclusion> <log path>   (one line each, at most 10; checks causes only)
Left in the slot: <repeat reason> <paths, at most 20>   (repeats_exhausted only)
Evidence: <attempt directory>
The factory removed `<label>`, added `held` and returned its claim. To answer, edit this task's description or
acceptance criteria (the agent reads those, not comments), then run `bd label add <id> <label>`: the next round starts
it again at plan on task/<id> as it is.
<one reason line: branch_moved "Restore task/<id> to contain <X>, or delete it locally and on origin, before adding
the label."; claim_lost "Someone else changed this task's claim; the factory's attempt was abandoned.">
```

The explanation comes from the answer the status read already decodes (the step kind's `decode`, `Answer.explanation`,
at most 2000 characters by its own rule); if the collected result does not carry it today, H2 adds that one field to
the existing read, never a second answer parser. Agent text in a comment is shown to the person only: comments are not
agent input, so a hold cannot feed an agent's words back into the next attempt's input.

## 7. How a person answers

### 7.1 The answer

Edit the description or acceptance criteria (or decide nothing needs to change), then `bd label add <id> auto`. To
give up: `bd close <id>` (or leave it). `tl step show <id>` after the hold prints the reason, the tracker writes done,
and the same guide.

### 7.2 What re-ingests it (D3)

D3 checks the label only when a round ingests a task; the hold returned the claim, so taking the task again is an
ingestion. Today `selection.order` skips every task whose current attempt is abandoned (`abandoned`), so a person's
own abandon is never taken back by rounds. **Decided here:** a task whose current attempt is `on_hold` with `labels`
`moved` is eligible again: the hold removed the approval label itself, so the label in today's ready read can only be
the person's answer. A hold whose labels word is `not_ours`, `closed` or `missing`, and a hand abandon, keep today's
`abandoned` skip (`tl step start` is the person's way back). Admission's `start` then admits a fresh attempt (next
`seq`, plan) and claims, exactly as `tl step start` does after an abandon today.

### 7.3 The `held` label afterwards

Each round, after publication, `hold.clear_holds` reads the hold rows whose attempt is no longer current and whose
`cleared_at` is NULL (the task was taken again, by a round or by `tl step start`) and removes `held` (`Bd.show`, then
`remove_label` if present: no fence, the label is the factory's own; a missing or closed task counts as cleared), then
sets `cleared_at`. One move line `hold cleared`. Failure: retried next round, quiet.

### 7.4 Branch and attempts (D4)

The hold is an abandon, so by D4 the next start begins at plan. Nothing is deleted: the attempts stay in factory.db as
abandoned history, `task/<id>` stays local and on origin, the slot was parked at its D. The new plan attempt resumes the
existing branch as it is (`prepare.branch_refusal` and `take_branch(mode="resume")`, unchanged): the agent finds the
previous plan and implementation, may answer `unchanged`, and an implement attempt continues from the code already on
the branch. Its publication is a fast-forward of origin's `task/<id>`. A failed check therefore costs a plan and an
implement run, not the work. A `branch_moved` hold says to fix or delete the branch first; if the person does neither,
the re-admission refuses `branch_diverged`/`branch_moved` again (a skip, or a new hold on advance).

What is lost against today: a failed checks attempt can no longer be re-run with `tl step start` (it is abandoned with
the task). **Decided here, accepted:** a flaky check costs a plan and implement run after the person re-adds `auto`;
re-running checks without a restart needs a hold that keeps the claim, which M4 does not need.

## 8. Schema v14

One table, nothing else: B11, B13 and the breaker need no state, so this is the only factory.db discard of M4.

```sql
CREATE TABLE task_hold (
 attempt_id TEXT PRIMARY KEY REFERENCES attempt(attempt_id),  -- the task's agent attempt the hold abandons
 cause_id TEXT NOT NULL,             -- that attempt, or its latest checks attempt (no foreign key: two tables)
 reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 200),
 label TEXT NOT NULL CHECK(length(label) >= 1),  -- the approval label the hold removes (the round's --label)
 held_at REAL NOT NULL,
 commented_at REAL,
 labels TEXT CHECK(labels IS NULL OR labels IN ('moved','not_ours','closed','missing')), labelled_at REAL,
 cleared_at REAL,
 rev INTEGER NOT NULL DEFAULT 0,
 CHECK((labels IS NULL) = (labelled_at IS NULL)),
 CHECK(cleared_at IS NULL OR labels IS NOT NULL)
);
```

`hold_store.py` is its one writer: `insert` (fenced as 5.1 step 1), `commented`, `labelled`, `cleared`, each fenced on
`rev`; reads `of_attempt(ids)` (one query for a listing) and `uncleared()` (hold rows with a later attempt of the same
task, `LATER` reused). `factory_schema` version 14, `HOLD` column list, docstring line. The policy test's WRITERS map
gains `task_hold: hold_store`. Upgrade: finish (land) or abandon in-flight tasks, stop rounds, discard factory.db, adopt
the slots again (as for v11-v13).

## 9. The round

All in `round.run_round`, through a new `RoundPorts.holding` port (the store, the tracker holds, the release port, the
clock, the evidence reader). No new lock, process or loop.

1. **Settle**: before the `match`, `cause = hold.cause(each)`; when `cause` is set or `each.next == "hold"`, the move is
   `hold_task(...)` and nothing else for that attempt. `on_hold`: nothing, no line (like `start if abandoned` today).
2. **Advance**: a refusal `claim_lost` or `branch_moved` is `hold_task(...)` with that reason instead of a `skip`.
3. **Admit**: the `attempts` map leaves out an `on_hold` task with `labels` `moved` (7.2).
4. **Publish**: a refusal `branch_moved` is `hold_task(...)`.
5. **Clear**: `clear_holds(...)` (7.3), after publish, skipped on a graceful stop.

Move lines (fixed words): `<task> <step> hold held <reason> <attempt>` when this call finished the hold,
`hold pending <what is missing> <attempt>` with the failure word as detail (`unavailable:tracker`, `held:slot_dirty`,
`refused:landing`), `hold cleared`. The existing `quiet` keys keep a repeated pending line out of the log; once done,
the task is `on_hold` and has no move at all, so a held task costs no tracker call and no line in later rounds (it is
not in the ready read until the person adds the label). A pending hold costs one bd call or one release attempt per
round, as a pending publication does today. Per-task hold words never stop admission or back the rounds off.

`round.py` is 361 lines; the additions are about 25. If it passes 400, `_verified` and `_publish` move to a new
`round_publish.py` (no behavior change).

## 10. `tl step` words, show, list, JSON

- `attempt_status`: `Next` gains `hold` and `on_hold`; `AttemptView.hold: HoldRow | None`. The hold row of the view's
  agent attempt decides the word after every other rule (a done or stuck word becomes `hold` once the row exists and
  `on_hold` once it is done, 5.1), except `unknown`, which stays `unknown`. `list_attempts` reads all hold rows once.
- `tl step show`: `Hold: <reason> at <UTC time> (cause <id>)`, `Hold tracker: commented, <label> removed, held added,
  claim returned` (or what is missing, with the last refusal from the release row's state), then the guide.
- `step_guide`: `hold`: "The next round finishes the hold (comment, labels, abandon); `tl step next` does it now. A
  slot the lost attempt left dirty keeps the claim: inspect it and clean it, then rerun." `on_hold`: section 7.1's
  answer, with the label the hold removed, plus the reason line for `branch_moved` and `claim_lost`.
- `tl step list`: the `Next` column shows `hold`/`on_hold`; `--stuck` unchanged (a hold is not stuck: the round owns
  it). **Decided here:** no `--held` flag; the tracker's `bd list --label held` is the finder M4 names.
- `result_data.as_data`: a `hold` object (`reason`, `cause`, `label`, `held_at`, `commented_at`, `labels`,
  `labelled_at`, `cleared_at`) or null.

## 11. Unattended safety limits

Already bounded, no change: one task per slot; each attempt's deadline (`--minutes`); at most 3 attempts per step
(`ATTEMPTS`); a failed or stuck task never re-run by a round (after B7 it is held, and only a person's label brings it
back); `stuck:checks_refused` after two refusals; land only by the person. So one ingestion costs at most
3 plan + 3 implement agent runs and two checks relaunches.

**Decided here, the one new limit: a circuit breaker in `tl step rounds`.** A broken login, an expired account or a
model name the provider refuses fails every attempt fast; without a breaker one night would hold every `auto` task.
`rounds._Breaker` (process memory only, nothing stored): counts `hold held` moves; resets on any `advance started` or
`verify` move whose status is `verified`/`reused` (a passed check step has no move of its own, but every success is
followed by an advance or reaches `land`); task-specific failures between successes (three failed checks, each after an
`advance started`) therefore never trip it, a failure of every new attempt does. At `BREAKER = 3` the rounds end after
that round with `Ended("breaker")`: `rounds stopped breaker` in the log, exit 1, and the message "Three tasks were held
in a row with no success between them: read their reasons (`bd list --label held`), fix the cause, then start rounds
again." Entries already running keep running (rounds never stop them); their results settle when rounds start again.
A restart resets the count.

**Decided here, not added:** a maximum of claimed tasks (slots bound the work in flight; tasks at `land` are the
morning's queue and cost nothing), a per-task cost or time cap beyond the deadline and repeat cap, and the
time-since-last-command column (B10, M5; D7 has no hung detection to feed).

## 12. Recovery after a reboot or a stop (D6)

No service. After a reboot the person starts rounds again. Admitted attempts relaunch with a renewed deadline (as
built). An agent attempt whose entry died is `stuck:entry_lost` and is now held by the first round: comment and labels
at once; the abandon parks the slot when it is clean, else it refuses `held:slot_dirty` and the task stays `Next: hold`
claimed by `taskloop`, with the guide naming the slot. The person inspects and cleans that slot (the factory never
resets work), and the next round finishes the hold. A checks attempt relaunches or concludes as built. `tl step release
--abandon` stays the person's tool; B9 (session resume) stays deferred.

## 13. Keep-awake (B11, tl-8bh9.14.10)

Lifetime-scoped while `tl step rounds` runs (accepted 2026-11-09), one small module `keep_awake.py` (pure argv choice
plus a spawn port) and its wiring in `cli_composition`'s rounds command:

| Platform | Command (one helper child, its own session) | Ends when |
|---|---|---|
| macOS | `caffeinate -i -w <rounds pid>` | rounds exits (also on `kill -9`: `-w` waits for the pid) |
| Linux with `systemd-inhibit` on `PATH` | `systemd-inhibit --what=sleep:idle --who=taskloop --why="tl step rounds <backlog>" --mode=block tail --pid=<rounds pid> -f /dev/null` | rounds exits (`tail --pid` polls each second) |
| anything else | none | |

- Spawned through the shelf process API the factory already uses (`stream_proc.popen_held`, in composition only, stdin,
  stdout and stderr to `/dev/null`, `start_new_session=True` so the person's Ctrl-C reaches only rounds); stopped with
  `stream_proc.stop_tree` in the rounds command's `finally` (graceful end, breaker, abrupt `KeyboardInterrupt`). No
  `subprocess` import, no signal, no wait of the factory's own.
- Best effort: a missing tool is `rounds keep_awake unavailable:<why>` in the log and one stderr line; rounds run
  anyway. Started: `rounds keep_awake started pid=<n>`. The factory does not check that the inhibitor took effect.
- **Unobserved**: macOS (no Mac in this plan's evidence; `-i` prevents idle sleep only, so a closed lid on battery still
  sleeps: the person keeps the lid open or uses clamshell on power); Linux without a logind session (OrbStack, SSH
  without polkit): `systemd-inhibit` exits at once and the effect is none. The smoke observes it (`systemd-inhibit
  --list`; `pmset -g assertions`).

## 14. Git read timeout (B13, tl-8bh9.14.3)

A FIFO or a stuck file system can hang a local Git read; the loop must not hang on it.

- **Shelf API (git-porcelain, decided here):** `RealRepo(..., read_timeout: float | None = None)`. Every read-only
  operation of git-porcelain (status, rev-parse, ls-files, worktree list, merge-base, cat-file, diff listings,
  for-each-ref, config reads) passes `timeout=self.read_timeout` to the one runner; remote calls keep
  `remote_timeout`; writes (commit, checkout, worktree add, update-ref) stay unbounded, because a write killed midway
  leaves `index.lock` and a refusal worse than the hang. A timeout is the existing `GitTimeout` (a `GitUnavailable`),
  whose message names the command and the seconds. `FakeRepo` gains a way to make one read raise `GitTimeout`.
- **Factory (G2):** `git_views` passes `read_timeout=READ_TIMEOUT_S = 120.0` to its three `RealRepo` constructions. No
  new word: a timeout is `unavailable:git` with the shelf's message as detail, an unknown the round backs off from and
  retries, as any Git failure today.
- **Residual:** `subprocess.run`'s timeout kills Git and then waits for it; a Git process blocked in an uninterruptible
  file-system call (a dead NFS mount) cannot be killed until the call returns, so that case still hangs. A FIFO read
  (interruptible) is covered.
- **Release and the owner's grant:** the shelf commit and its tests are local work the autonomous grant covers. Pushing,
  merging and tagging the shelf (a remote publication, CLAUDE.md) is not covered: the M3 work already found the push of
  the git-porcelain 0.17.0 branch (`remote_urls`, local branch `git-porcelain-remote-urls` in
  `/home/iorlas/Workspaces/shelf-wt-l3`) refused by the permission system. **Decided here:** add `read_timeout` to that
  same unreleased 0.17.0 branch, so one owner release brings both the multi-URL push guard and the read timeout; if
  0.17.0 was released meanwhile, it goes in 0.18.0. This is an owner action, not a design question (section 21).

## 15. Slices

Caps: 400 source lines per file, 80 per function, 800 per test file. Estimates are added lines.

| # | Slice | Contents | Source | Tests | Depends on |
|---|---|---|---|---|---|
| H1 | Schema v14, the hold store, the tracker's hold writes, the comment | `factory_schema` v14 (`task_hold`, `HOLD`); `hold_store.py` (insert fenced, commented, labelled, cleared, of_attempt, uncleared); `tracker_client.TrackerHolds` (`comment`, `labels` with 5.2's table, `clear`, each bd call capped); `hold_text.py` (section 6); WRITERS policy entry | about +330 (`hold_store` 150, `hold_text` 90, `tracker_client` +70, schema +20) | about +450 (`test_hold_store`, `test_tracker_holds` with `beads_client.testing.Script`, `test_hold_text`) | B6 built |
| H2 | The hold operation and its words | `hold.py` (`cause`, `hold_task` 5.1, `clear_holds` 7.3); `attempt_status` (`hold`, `on_hold`, `AttemptView.hold`); `show_render`/`step_render` `Hold:` lines; `step_guide` two guides; `result_data`; `operations.Action` gains `hold`; the answer's `explanation` on the collected result if missing; glossary (hold, `hold`/`on_hold`, label `held`) | about +290 (`hold` 200, status +30, render +25, guide +25, data +10) | about +500 (`test_hold` cause table, sequence, every partial rerun, 5.2's rows; status words) | H1 |
| H3 | The round applies it, and the breaker | `round` (9.1-9.5), `RoundPorts.holding` and its wiring in `cli_composition`; `rounds._Breaker` and `Ended("breaker")` with its exit and message; `round.py` split if over 400 | about +90 | about +400 (`test_round_holds`: each cause held once and quiet after, pending retried quietly, re-ingestion of a `moved` hold, `abandoned` skip kept for others, clear; `test_rounds_breaker`) | H2 |
| K1 | Keep-awake (tl-8bh9.14.10) | `keep_awake.py` (argv by platform, `Awake` with `stop`); rounds command wiring; two log words | about +95 | about +150 (argv per platform, missing tool, stop in `finally` with a fake spawn port) | none |
| G1 | git-porcelain `read_timeout` (shelf repository) | section 14's API on the unreleased 0.17.0 branch; shelf tests (a real FIFO case, fake timeout) | shelf about +40 | shelf about +80 | none; **owner release** |
| G2 | Pin and use the read timeout (tl-8bh9.14.3) | `pyproject.toml`/`uv.lock` pin git-porcelain 0.17.0 (also unblocks M3's multi-URL guard: `land_push.same_url` with `remote_urls`, already written in tl-8bh9.14.8 section 27.1 item 4, may land in the same commit); `git_views` passes `read_timeout` | about +10 (+15 with the guard) | about +40 (fake timeout is `unavailable:git` with its detail) | G1 released |
| S | M4 live smoke | runbook `live-smoke.md` here, the run, `m4-smoke-findings.md` | none | none | H3, K1, G2 |

H1 to H3 are B7. K1 and G1/G2 are independent of them and of each other; they can be built first.

## 16. Tests

Focused pytest functions and classes on semantic fakes, as the existing step tests do; no subprocess, no live runs.

- `hold.cause`: every row of section 3's table, including the `no` rows (`stuck:hung`, `unknown`, `land`).
- `hold_task`: the full sequence on fakes; a crash after each step (the rerun does only what is missing, the comment
  at most twice); each 5.2 row; a stale fence (`labels` unset, retried); a refused abandon (`held:slot_dirty`, the
  tracker writes kept, `Next: hold`); a lost race at insert (`refused:changed`, no tracker call).
- `hold_store`: every CHECK with its NULL case; the insert fence (later attempt, later checks attempt, existing row).
- `TrackerHolds`: argv and order through `beads_client.testing.Script` (fence before labels, `held` before the
  approval label), bd exit 13 to `precondition`, timeouts to `unavailable`.
- `hold_text`: caps (explanation 2000, 10 checks, 20 paths, 6000 total), control characters removed, the label and
  task id in the answer line.
- Round: a failed `done` becomes one `hold held` line and nothing in the next round; a pending hold writes its line
  once; an `on_hold` task with `moved` labels and the label in the ready read is started at plan (new `seq`), one with
  `not_ours` is skipped `abandoned`; `clear_holds` after the restart; advance `claim_lost`/`branch_moved` and publish
  `branch_moved` held.
- Breaker: three holds trip it, a success in between resets it, `Ended("breaker")` exit 1.
- Keep-awake: argv per platform, `unavailable` without the tool, `stop` in every exit path.
- G2: a fake `GitTimeout` read is `unavailable:git` with the message.

## 17. Live smoke outline (S; owner- or authorized-agent-run)

Scratch repository, bare remote and tracker under `~/tl-smoke/m4`, a runner worktree at the commit under test, two
slots, removed afterwards; nothing pushed anywhere else.

1. Tasks, all `auto`: A asks for something only the owner can decide (expect `needs_owner`); B adds a test that fails
   the profile's required `test` check; C a small clean change; D one whose `task/<id>` the person moves on origin
   between implement and the check advance; E one interrupted by `kill -9` of its entry during implement (a dirty slot).
2. `tl step rounds ... --label auto` for at least two hours (the overnight shape, shortened). Expect: C at `land`;
   A, B, D held once each (one `hold held` line each, then silence), each with the comment, `held`, no `auto`, open
   and unassigned; E `Next: hold` claimed by `taskloop` with `held:slot_dirty` until the person cleans the slot, then
   held by the next round.
3. Answer A: edit its description, `bd label add A auto`. Expect the next round to start A at plan (attempt seq
   advanced, on the same `task/A`), `held` removed (`hold cleared`), and A to reach `land`.
4. Breaker: stop rounds, set a model name the provider refuses, label three new tasks, start rounds. Expect three holds,
   `rounds stopped breaker`, exit 1, no fourth claim.
5. Keep-awake: while rounds run, `systemd-inhibit --list` (or `pmset -g assertions`) shows `taskloop`; after Ctrl-C
   and after `kill -9` of rounds it is gone within two seconds. On a host without logind: `keep_awake unavailable` and
   the rounds unaffected.
6. Git read timeout: with G2 pinned, one read made to hang (the shelf test's FIFO case in a slot) ends after
   `READ_TIMEOUT_S` as `unavailable:git`, and the next round proceeds once it is removed.
7. Land C and A by hand as in M3; `bd list --label held` lists exactly B, D (and E) at the end.

## 18. Changes to existing behavior

- A failed checks attempt is held and abandoned, so `tl step start` no longer re-runs it after a round has seen it
  (7.4). M2's "visible failed `done`, claim kept" becomes a hold.
- `stuck:*` (except `stuck:hung`) and `repeats_exhausted` are no longer only reported: the round holds them.
- Advance `claim_lost`/`branch_moved` and publish `branch_moved` stop being retried every round.
- The roadmap's M4 "still by hand: reboot recovery (`--abandon`)" shrinks to cleaning a dirty slot (section 12).

## 19. Risks

| Risk | Mitigation |
|---|---|
| A broken login holds many tasks overnight | the breaker (three); the reasons say which failure |
| The label steps are not one atomic write (fence, then two label calls) | the same accepted gap as the land's close; the window is the factory's own claim; a later beads-client `update(add_labels=, remove_labels=)` makes it one guarded call (measured to work in bd 1.3.1) |
| A crash between the comment and its record duplicates the comment | accepted; never more than once per crash |
| The person adds `auto` again within seconds of a crashed label step, and the rerun removes it | accepted: the hold's comment is already there, so the person sees why; documented in the guide |
| A held task restarts at plan and the plan agent answers `unchanged` without reading the edit | the plan input carries the edited description; acceptance names the change; the person reads the next result |
| Agent text in the tracker | capped, control characters removed, never fed back to an agent |
| `stuck:hung` holds a slot all night | D7; reported once; the person abandons by hand in the morning |
| Keep-awake silently ineffective (no logind, battery lid close on macOS) | best effort, logged; the smoke observes it per machine |
| A Git read in an uninterruptible file-system call still hangs | named residual (section 14) |
| The schema discard loses landed history | as every earlier discard; land or abandon first |

## 20. Decisions made here (owner may veto)

1. A hold is an abandon plus a tracker note: comment, approval label removed, `held` added, claim returned (O5's
   recommendation, made concrete).
2. Section 3's table: what holds and what does not (`stuck:hung` and admission branch refusals do not).
3. factory.db owns the hold record (`task_hold`, v14); the tracker owns the reason text and the labels; nothing reads
   the comment or `held` for control.
4. Tracker writes before the abandon; `held` added before the approval label goes.
5. 5.2's table: the factory edits labels only of a task it holds or that is unassigned; never another actor's.
6. Re-ingestion: an `on_hold` task with `labels` `moved` is eligible when its label is back; every other abandon keeps
   the `abandoned` skip.
7. The factory removes `held` after the task is taken again (`clear_holds`).
8. Failed checks are held too, at the cost of a plan and implement run on restart (7.4).
9. `Next` words `hold` and `on_hold`; tracker label `held`; no `--held` flag.
10. One new limit: the breaker at three holds with no success between; no task, cost or time caps beyond today's.
11. Keep-awake: `caffeinate -i -w` and `systemd-inhibit ... tail --pid`, best effort, through `stream_proc`.
12. Git read timeout: `RealRepo(read_timeout=)` on reads only, 120 s, folded into the unreleased git-porcelain 0.17.0.
13. B10 is not part of M4.

## 21. Blocking owner questions

None. One **owner action** (not a question): push, merge and tag the shelf's git-porcelain 0.17.0 (with
`remote_urls` and, after G1, `read_timeout`). Until then G2 and smoke step 6 wait; H1-H3 and K1 do not.

## 22. Tracker entries

| Slice | Id | Depends on |
|---|---|---|
| H1 | tl-8bh9.14.9.1 | (parent tl-8bh9.14.9 depends on tl-8bh9.14.8) |
| H2 | tl-8bh9.14.9.2 | tl-8bh9.14.9.1 |
| H3 | tl-8bh9.14.9.3 | tl-8bh9.14.9.2 |
| S, M4 smoke | tl-8bh9.14.9.4 | tl-8bh9.14.9.3, tl-8bh9.14.10, tl-8bh9.14.3.2 |
| K1 | tl-8bh9.14.10 (one slice, no child) | none |
| G1 | tl-8bh9.14.3.1 | none (owner release) |
| G2 | tl-8bh9.14.3.2 | tl-8bh9.14.3.1 |
