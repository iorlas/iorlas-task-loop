# tl-8bh9.14.9: questions and holds, and the rest of the unattended loop (block B7 with B11 and B13, milestone M4)

Design, 2026-11-12, against ffbb689c4 (M1, M2 and M3 smokes passed); revised the same day after an independent review
of 5f775790e (section 23). Docs only: nothing built or run, except two measurements of bd 1.3.1 in scratch trackers
under `~/tl-smoke` (section 5.4), removed afterwards. Read: CLAUDE.md, [glossary](../../glossary.md),
[roadmap](../self-hosting-roadmap.md) (B7, B10, B11, B13, M4, D1-D14, O1-O6, section 6),
[structured questions](../tl-8bh9.6.1/plan.md) and its [balanced design](../tl-8bh9.6.1/balanced-design.md),
[keep-awake inventory](../tl-8bh9.4.6/plan.md), [rounds](../tl-8bh9.4.3.1.14/plan.md) (section 2's owner statement),
[the checks step](../tl-8bh9.14.6/plan.md) (O2's M2 reading), [land and close](../tl-8bh9.14.8/plan.md) and its
[M3 findings](../tl-8bh9.14.8/m3-smoke-findings.md), and `round`, `rounds`, `rounds_lock`, `interrupts`,
`attempt_status`, `check_status`, `land_status`, `operations` (`release_task`), `slot_release`, `selection`, `admit`,
`tracker`, `tracker_client`, `steps`, `factory_schema` (v13), `git_views`, `cli_composition`, the installed
`beads_client` 0.2.0, `git_porcelain` 0.16.0 (`real`, `real_read`, `real_observe`) and `stream_proc` (`hold`).

The owner is away and asked for autonomous decisions. Each one is marked **decided here** (a recommendation, open to
veto); decisions the coordinator made in the review are marked **decided (review)**. Owner decisions D1-D14 are cited
by number. Section 21 lists blocking owner questions: none.

## 1. What changes for the owner

The person labels tasks `auto`, starts `tl step rounds ... --label auto` before going to bed and leaves it. The laptop
does not sleep while rounds run (B11). In the morning:

- tasks that went well wait at `Next: land` (unchanged since M3);
- every task the rounds took and then stopped on is **held**: its label `auto` is gone, the label `held` is on it, and
  it carries one comment from `taskloop` that starts `taskloop hold: <reason>` and says what happened, where the
  evidence is, whether the claim is already returned, and how to answer. `bd list --label held` lists them;
  `tl step list` shows them as `on_hold`, or `hold` while a slot or process still keeps the claim (also in `--stuck`);
- a hold whose slot still has files left (the agent's uncommitted work) keeps the claim until the person removes them;
  its comment names the slot. The factory never removes work (section 12).

To answer a held task the person edits its description or acceptance criteria (the agent reads those, never comments)
and adds the label back (`bd label add <id> auto`). The next round takes it again like a new task and starts it at plan
on its existing `task/<id>` as it is (D3, D4). Nothing else changes: land stays person-run. There is no factory-side
stop: if every attempt fails (a broken login), every task the rounds take that night is held (section 11).

## 2. What a hold is

**Hold** (glossary entry, decided here): a task the factory will not advance until a person acts. The factory has
recorded why in factory.db, removed the approval label the task was taken under, added `held`, abandoned the task's
current attempt (slot parked, claim returned) when the slot allows, and written the reason on the task. A hold is an
abandon plus a tracker note; it is never a new kind of attempt, step or wait.

Words, kept apart from the existing ones: the `Next` words are **`hold`** (the hold is due or not finished: the round
finishes it, or a slot or process keeps the claim) and **`on_hold`** (finished: waiting for the person). The tracker
label is `held`. The release word `held:<reason>` (a slot stays reserved) and the slot custody `hold` in code keep their
meanings; the glossary row "reserved / locked / held" gains one sentence saying that `hold`, `on_hold` and the label
`held` are about a task, not a slot.

Not a hold: a structured question with choices, answer revisions or a local wait (tl-8bh9.6.1, deferred). A held task
has no open question object; its question is the comment, its answer is the edited task text plus the label.

## 3. Which conditions hold the task

**Which tasks (decided here, review finding 9):** only tasks the rounds took. v14 stores the approval label an
ingestion saw on the attempt (`attempt.label`, section 8): a round's admission writes its `--label`; an advance and a
repeat copy it from the attempt they follow; `tl step start` by hand writes NULL. A task whose current agent attempt
has `label` NULL is never held: it was started by a person, who is present and acts on the words as today (the rounds
still advance and report it, as built). Consequence, accepted: a hand-started task that fails overnight is a visible
failed `done` or `stuck:*` in `tl step list`, not a tracker hold.

For a round-taken task, one pure rule, `hold.cause(view) -> str | None`, reads an `AttemptView` and returns the reason
word, or None. The reason is the word `tl step show` already prints; no new vocabulary.

| Condition (as the round sees it) | Hold? | Reason word | Notes |
|---|---|---|---|
| `Next: done`, result not succeeded (plan or implement: `needs_owner`, `incomplete`, `rejected:<rule>`, a run failure or timeout) | yes | `failed:<result reason>` (`failed:answer:needs_owner`, `failed:run:timeout`, `failed:rejected:<rule>`) | the agent's `explanation` goes into the comment |
| `Next: done` of a checks attempt `failed:<reason>` | yes (O2, as the roadmap recommends) | `failed:<reason>` as today (`failed:test:failed`) | each failed check's name and log path go into the comment |
| `Next: release`, result collected and not succeeded | yes | as `done` | the abandon parks the slot first; a dirty slot keeps the claim (section 12) |
| `Next: repeats_exhausted` | yes | `repeats_exhausted:<repeat reason>` | the leftovers that caused it are still in the slot: the hold stays `hold` until the person removes them (section 12) |
| `stuck:expired_admitted`, `stuck:entry_lost`, `stuck:uncollected`, `stuck:conflict`, `stuck:setup_failed`, `stuck:checks_refused` | yes | the word | `entry_lost` mid-write usually leaves files or a live worker (section 12) |
| `stuck:hung` | **no** (D7) | | an entry still runs past its deadline; the abandon's stop proof would refuse anyway. Reported once as today |
| `unknown`, `wait`, `start`, `verify`, `repeat`, `publish` (not refused), `advance` | no | | transient or progressing |
| `land`, `landed` | no | | the person's; a failed land is in front of the person who ran it |
| advance refused `claim_lost` | yes | `claim_lost` | the tracker writes depend on who holds the task now (5.2) |
| advance refused `branch_moved` (plan to implement, implement to check) | yes | `branch_moved` | the comment says to restore or delete `task/<id>` |
| publish refused `branch_moved` | yes | `branch_moved` | today it is retried every round forever |
| advance or admission refusals about the round (`no_free_slot`, `deadline`, `database`, ...) or transient (`changed`, `abandoned`) | no | | |
| admission refusals of a not yet claimed task (`branch_held`, `branch_diverged`, `branch_name`) | **no, decided here** | | nothing is claimed (the start compensates its claim), so nothing is left claimed and silent; the skip line is written once and quieted as today. A hold needs an attempt to abandon |

## 4. Who owns what

| Fact | Owner | How |
|---|---|---|
| The approval label a task was taken under | factory.db `attempt.label` (v14) | written at admission, copied by advance and repeat |
| The hold: which attempt, which cause, the reason word, when, which tracker writes are done | factory.db `task_hold` (section 8) | written by `hold_store` only |
| The slot parked and the claim returned | factory.db `slot_release` (abandoned, claim `unclaimed`/`not_held`) as today | the hold calls the existing abandon (`operations.release_task(abandon=True)`), never a copy of it |
| The reason for the person, the evidence paths, the claim state at writing, how to answer | tracker comment | written once; never read back by the factory |
| Approval to (re)start | tracker label (the stored `attempt.label`) | D3: read only at ingestion |
| "This task waits for a person", for finding it in the tracker | tracker label `held` | added by the hold, removed by the factory after the task is taken again (7.3); never read for control |
| The answer | the task's description and acceptance criteria | the plan agent's input already reads those (`tracker.inspect_task`) |

The factory never derives control state from the comment or from `held`. The only tracker facts it reads for control
are today's (ready set with the label, status, assignee) plus, in the hold itself, status, assignee and whether the
stored label is on the task (5.2).

## 5. The hold operation

### 5.1 Sequence

`hold.hold_task(ports, backlog, task_id, cause_view, reason) -> HoldMove`, the one application operation (the round
calls it; `tl step next` is a round and may run beside `tl step rounds`, which `rounds_lock` allows). Every step is
recorded and fenced, so a rerun or a concurrent caller does only what is missing:

1. **Record** (factory.db): insert the `task_hold` row for the task's current agent attempt A, with the cause's id (A
   itself, or A's latest checks attempt), the reason and `held_at`. Fenced in the write: A is still the task's current
   attempt (`factory_schema.LATER` false), A's `label` is not NULL, the cause is still current (a checks cause: still
   A's latest checks attempt and not abandoned) and no hold row for A exists. A lost race is `refused:changed`.
2. **Read** (tracker): unless `labels` is set, one `Bd.show`; what it says picks step 3 (5.2).
3. **Labels** (tracker): the fence `Bd.update(assignee=a, if_assignee=a)` with the assignee just read,
   `Bd.add_label(task, "held")`, `Bd.remove_label(task, A.label)`; then `labels` (`moved` when the stored label was on
   the task, `absent` when it was not). `held` is added before the approval label goes, so a crash in between leaves
   the task claimed with both labels and the rerun finishes it. Labels are idempotent (5.4), so a concurrent caller
   repeating them changes nothing.
4. **Abandon** (factory.db, slot, tracker claim): `operations.release_task(..., abandon=True)` as `tl step release
   --abandon` runs it (land candidate, then checks attempt, then the agent attempt; parks the slot; the fenced unclaim,
   never forced). Its own rows are the record. A refusal leaves the hold `Next: hold`, retried by the next round;
   section 12 names each refusal and what the person does.
5. **Comment** (tracker, once, after the abandon's outcome is known): written when the abandon is done (the text says
   the claim is returned), or when it was refused for a reason only the person can clear (section 12: the text names
   the slot or process and says the next round returns the claim once it is cleared and that the claim is still
   held). Not written after a transient refusal (`slot_busy`, `unavailable:*`, `worker_unknown`, `setup_unknown`):
   the next round tries again. The text never says the claim was returned before the abandon recorded it. Fence
   against a concurrent caller (review finding 9): a fenced update first sets `commenting_at` (only where
   `commented_at` and `commenting_at` are NULL, or `commenting_at` is older than `COMMENT_LEASE = 120` s, longer than
   one capped bd call, 30 s); the winner calls `Bd.comment`, then sets `commented_at`. A loser does nothing. A crash
   between the comment and `commented_at` can post it twice after the lease, accepted; two live callers cannot.

The hold is **finished** (`on_hold`) when `labels` is set, A's release is abandoned with its claim no longer `kept` or
`unclaiming`, and `commented_at` is set (or `labels` is `closed`/`missing`, which write no comment). Every bd call is
capped at `claim_lease.BD_TIMEOUT_S`; any bd failure is `unavailable:tracker` for this round, retried by the next.

Order, decided here: the label step before the abandon, because the unclaim makes the task ready again: if the claim
were returned first, a crash before the label step would leave an approved task with an abandoned attempt (today's
`abandoned` skip, silent). The comment after the abandon, so it states the claim truthfully (review finding 1).

### 5.2 Who holds the task now

| `Bd.show` says | Labels step | `labels` word | Comment | Abandon's unclaim |
|---|---|---|---|---|
| in progress, assignee `taskloop` | fence on `taskloop`, add `held`, remove `A.label` | `moved` or `absent` | yes | returns the claim |
| open, unassigned (the claim lapsed or was reverted) | fence on `""` (measured), same writes | `moved` or `absent` | yes | `not_held` |
| assigned to another actor | none: never edit another actor's labels | `not_ours` | yes | `not_held` (fence refuses) |
| closed | none | `closed` | no | `not_held`: bd refuses, nothing written (5.4) |
| missing | none | `missing` | no | `not_held` (bd's "no issue found") |
| fence stale (exit 13, `precondition`) | nothing written | not set: retried next round | | |

For a closed or missing task the hold writes nothing to the tracker; the abandon still frees the slot.

### 5.3 The unclaim of a closed or missing task (H1, review finding 8)

Measured (5.4): `bd unclaim --if-assignee taskloop` of a closed task still assigned to `taskloop` exits 1 with "cannot
unclaim closed issue <id>" and writes nothing (it does not reopen the task). `beads_client` classifies that as `other`
and raises, so today's abandon would stay `unclaiming` forever (also a hand abandon of a closed task). H1 maps it in
`tracker_client`'s unclaim, as `GONE` is mapped for the heartbeat: "cannot unclaim closed issue" and `GONE` ("no issue
found matching") return False, which the release records as `not_held`. No hold-specific branch in the abandon.

### 5.4 What bd 1.3.1 and beads-client 0.2.0 support (measured 2026-11-12, two scratch trackers, removed)

- `beads_client.Bd` 0.2.0 already has `comment`, `add_label` (with an `if_assignee` fence by a same-value update),
  `remove_label`, `update(assignee=, if_assignee=)`, `unclaim(if_assignee=)` and `show` (with `labels`). **No shelf
  change is needed for B7.**
- `bd label remove` of an absent label exits 0; `bd label add` of a present one exits 0.
- `bd update --remove-label X --add-label Y --if-assignee A` alone is refused ("label and parent edits are not covered
  by the guard"); with a field update (`--assignee A --if-assignee A`) it applies, and a stale guard (exit 13) writes
  nothing, labels included. beads-client 0.2.0's `update` has no label arguments, so H1 uses the fence update followed
  by the two label calls (the same accepted gap as `land_close`'s close). A later beads-client `update(add_labels=,
  remove_labels=)` would make it one guarded call; not needed for M4.
- `bd unclaim --if-assignee taskloop` of an in-progress task leaves status `open`, no assignee, labels untouched; of a
  closed task it exits 1 ("cannot unclaim closed issue"), status, assignee and labels unchanged.
- `bd update --assignee taskloop --if-assignee taskloop` on a closed task succeeds and changes nothing; `bd label add`
  on a closed task succeeds (so the hold must not reach it: 5.2 writes nothing for closed).
- `bd ready --label auto` lists an open task carrying both `held` and `auto`; `bd list --label held` lists only open
  ones by default. `bd comments add <id> <text>` keeps newlines; `bd comments <id> --json` shows `author: taskloop`.

## 6. The comment

Built by `hold_text.comment(...)`, a pure function of the hold, the cause and the abandon's outcome. Fixed English, at
most 6000 characters, control characters other than newline removed from every quoted part:

```
taskloop hold: <reason>
Step <step>, attempt <number> (<attempt id>), <UTC time>; task branch task/<id> at <X or "not published">.
The agent explained: <explanation, at most 2000 characters, from the stored valid answer>
Failed checks: <name> <conclusion> <log path>   (one line each, at most 10; checks causes only)
Left in the slot: <repeat reason> <paths, at most 20>   (repeats_exhausted only)
Evidence: <attempt directory>
<claim line, by the abandon's outcome:>
  done:        The factory removed `<label>`, added `held` and returned its claim.
  slot_dirty:  The factory removed `<label>` and added `held`, but still holds the claim: slot <path> has files left by
               this attempt. Save what you need, remove them, and the next round returns the claim. The factory never
               removes work.
  worker_alive / setup_running: ... still holds the claim: a process of this attempt still runs (pid <pid>, group
               <pgid>). When it has ended (or after you stop it by that pid), the next round returns the claim.
  slot_branch / slot_redirected / slot_unborn: ... still holds the claim: slot <path> is not where the factory left it
               (<word>). Put it back (`tl step show <id>` says where), and the next round returns the claim.
To answer, edit this task's description or acceptance criteria (the agent reads those, not comments), then run
`bd label add <id> <label>`: the next round starts it again at plan on task/<id> as it is.
<one reason line: branch_moved "Restore task/<id> to contain <X>, or delete it locally and on origin, before adding
the label."; claim_lost "Someone else changed this task's claim; the factory's attempt was abandoned.">
```

The explanation comes from the answer the status read already decodes (the step kind's `decode`, `Answer.explanation`,
at most 2000 characters by its own rule); if the collected result does not carry it today, H2 adds that one field to
the existing read, never a second answer parser. Agent text in a comment is shown to the person only: comments are not
agent input, so a hold cannot feed an agent's words back into the next attempt's input.

## 7. How a person answers

### 7.1 The answer

Edit the description or acceptance criteria (or decide nothing needs to change), then add the label back. To give up:
`bd close <id>` (or leave it). `tl step show <id>` after the hold prints the reason, the tracker writes done, the claim
state, and the same guide.

### 7.2 What re-ingests it (D3, review finding 5)

D3 checks the label only when a round ingests a task; the hold returned the claim, so taking the task again is an
ingestion. Today `selection.order` skips every task whose current attempt is abandoned (`abandoned`), so a person's
own abandon is never taken back by rounds. **Decided here:** a task whose current attempt is `on_hold` with `labels`
`moved` or `absent` is eligible again. The hold removed (`moved`) or found absent (`absent`) the very label the task was
taken under (`attempt.label`, not the round's `--label`), so the label in a later ready read can only be the person's
answer. So eligibility also requires that the round's `--label` equals the stored `attempt.label`: a round under
another label skips the task (`abandoned`) even if the task carries that other label too, since that label was on the
task before the hold and is no answer. A hold whose labels
word is `not_ours`, `closed` or `missing`, and a hand abandon, keep today's `abandoned` skip (`tl step start` is the
person's way back). Admission's `start` then admits a fresh attempt (next `seq`, plan, `label` = the round's) and
claims, as `tl step start` does after an abandon today.

### 7.3 The `held` label afterwards (review finding 4)

Each round, after publication, `hold.clear_holds` reads `hold_store.uncleared()`: hold rows whose attempt is no longer
the task's current (`LATER`) and whose `cleared_at` is NULL and whose `labels` is NULL, `moved` or `absent` (the only
rows that may have added `held`; `not_ours`, `closed` and `missing` added nothing and are never listed). For each:

- the task's current attempt has its own hold row (it was taken again and held again): no tracker call (the new hold
  owns `held` now); set `cleared_at` only;
- else `Bd.remove_label(task, "held")` with no read first (an absent label exits 0; the label is the factory's own, no
  fence), then `cleared_at`;
- a row with `labels` NULL (superseded before its label step finished, `tl step start` by hand in between) gets
  `labels` `superseded` with `labelled_at` in the same write, so `CHECK(cleared_at IS NULL OR labels IS NOT NULL)`
  always holds.

One move line `hold cleared`. A bd failure is retried next round, quiet.

### 7.4 Branch and attempts (D4)

The hold is an abandon, so by D4 the next start begins at plan. Nothing is deleted: the attempts stay in factory.db as
abandoned history, `task/<id>` stays local and on origin, the slot was parked at its D. The new plan attempt resumes the
existing branch as it is (`prepare.branch_refusal` and `take_branch(mode="resume")`, unchanged): the agent finds the
previous plan and implementation, may answer `unchanged`, and an implement attempt continues from the code already on
the branch. Its publication is a fast-forward of origin's `task/<id>`. A failed check therefore costs a plan and an
implement run, not the work. Work that was never committed (left in the slot) is not on the branch: the person saves
what they need before removing it (section 12). A `branch_moved` hold says to fix or delete the branch first.

What is lost against today: a failed checks attempt can no longer be re-run with `tl step start` once a round has held
it. **Decided here, accepted:** a flaky check costs a plan and implement run after the person adds the label back.

## 8. Schema v14

The only factory.db discard of M4 (B11 and B13 need no state):

```sql
-- attempt gains one column (ATTEMPT_ADMITTED and ATTEMPT_LOADED gain `label`):
 label TEXT CHECK(label IS NULL OR length(label) BETWEEN 1 AND 200),  -- the approval label the round ingested it under;
                                                                       -- NULL: started by hand (`tl step start`)

CREATE TABLE task_hold (
 attempt_id TEXT PRIMARY KEY REFERENCES attempt(attempt_id),  -- the task's agent attempt the hold abandons
 cause_id TEXT NOT NULL,             -- that attempt, or its latest checks attempt (no foreign key: two tables)
 reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 200),
 held_at REAL NOT NULL,
 labels TEXT CHECK(labels IS NULL OR labels IN ('moved','absent','not_ours','closed','missing','superseded')),
 labelled_at REAL,
 commenting_at REAL, commented_at REAL,
 cleared_at REAL,
 rev INTEGER NOT NULL DEFAULT 0,
 CHECK((labels IS NULL) = (labelled_at IS NULL)),
 CHECK(commented_at IS NULL OR commenting_at IS NOT NULL),
 CHECK(commented_at IS NULL OR labels IN ('moved','absent','not_ours')),
 CHECK(cleared_at IS NULL OR labels IS NOT NULL)
);
```

Writers: `admit` writes `attempt.label` (fresh admission: the request's label, NULL from `tl step start`),
`admit_chain` copies it on an advance and a repeat. `hold_store.py` is the one writer of `task_hold`: `insert` (fenced
as 5.1 step 1), `labelled` (also fenced on A still current), `commenting` (the lease, 5.1 step 5; never on a cleared
hold), `commented`, `cleared` (and `superseded`), each fenced on `rev`; reads `of_attempts(ids)` (one query for a
listing) and `uncleared()` (7.3; `held_again` counts only a newer hold whose labels are NULL, `moved` or `absent`). As
built (section 24): the comment CHECK reads `commented_at IS NULL OR (labels IS NOT NULL AND labels IN
('moved','absent','not_ours'))`, and every `TrackerHolds` bd call is one try (no lock retry) capped at 30 s, so one call
stays within `COMMENT_LEASE`. `factory_schema` version 14,
`HOLD` column list, docstring line; the policy test's WRITERS map gains `task_hold: hold_store`. Upgrade: land or
abandon in-flight tasks, stop rounds, discard factory.db, adopt the slots again (as for v11-v13).

## 9. The round

All in `round.run_round`, through a new `RoundPorts.holding` port (the store, the tracker holds, the release port, the
clock, the evidence reader). No new lock, process or loop.

1. **Settle**: before the `match`, `cause = hold.cause(each)`; when `cause` is set (and the attempt has a label) or
   `each.next == "hold"`, the move is `hold_task(...)` and nothing else for that attempt. `on_hold`: nothing, no line.
2. **Advance**: a refusal `claim_lost` or `branch_moved` of a labelled attempt is `hold_task(...)` with that reason
   instead of a `skip`.
3. **Admit**: the `attempts` map leaves out an `on_hold` task with `labels` `moved` or `absent` whose stored label is
   the round's `--label` (7.2); `start` passes the round's label to the admission.
4. **Publish**: a refusal `branch_moved` of a labelled attempt is `hold_task(...)`.
5. **Clear**: `clear_holds(...)` (7.3), after publish, skipped on a graceful stop.

Move lines (fixed words): `<task> <step> hold held <reason> <attempt>` when this call finished the hold;
`hold pending <missing step> <attempt>` with the refusal word (`held:slot_dirty`, `unsettled:worker_alive`,
`unavailable:tracker`, ...) as detail; `hold cleared`. The quiet key includes the refusal word, so a pending hold's
line is written again whenever its cause changes and otherwise once. Once finished the task is `on_hold`: no tracker
call and no line in later rounds (it is not in the ready read until the person adds the label). A pending hold costs one
release attempt (and at most one bd call) per round, as a pending publication does today. Per-task hold words never
stop admission or back the rounds off.

`round.py` is 361 lines; the additions are about 25. If it passes 400, `_verified` and `_publish` move to a new
`round_publish.py` (no behavior change).

## 10. `tl step` words, show, list, JSON

- `attempt_status`: `Next` gains `hold` and `on_hold`; `AttemptView.hold: HoldRow | None`. The hold row is looked up
  by the view's **agent** attempt: for the swapped checks view (section 9 of tl-8bh9.14.6) that is
  `checks.row.after_attempt_id`, not the checks attempt id the view shows (review finding 7). The row decides the word
  after every other rule (a done or stuck word becomes `hold` once the row exists and `on_hold` once finished, 5.1),
  except `unknown`, which stays `unknown`. `list_attempts` reads all hold rows once.
- `tl step list --stuck` lists `hold` too (review finding 1b): a hold not finished needs the person when its refusal is
  section 12's person-cleared kind, and costs a look otherwise. `on_hold` is not listed (the tracker is its finder).
- `tl step show`: `Hold: <reason> at <UTC time> (cause <id>)`, `Hold tracker: <label> removed|absent, held added,
  commented|not yet` and `Hold claim: returned|kept: <refusal word>` with section 12's action for that word, then the
  guide.
- `step_guide`: `hold` is not a "wait for the round" guide: it names what keeps the hold open (the refusal word from
  the release attempt the status read sees) and the person's action from section 12, then "the next round finishes it;
  `tl step next` does it now". `on_hold`: section 7.1's answer with the stored label, plus the reason line for
  `branch_moved` and `claim_lost`.
- **Decided here:** no `--held` flag; the tracker's `bd list --label held` is the finder M4 names.
- `result_data.as_data`: a `hold` object (`reason`, `cause`, `label`, `held_at`, `labels`, `labelled_at`,
  `commented_at`, `cleared_at`) or null; the attempt's `label`.

## 11. Unattended safety limits

Already bounded, no change: one task per slot; each attempt's deadline (`--minutes`); at most 3 attempts per step
(`ATTEMPTS`); a failed or stuck task never re-run by a round (after B7 it is held, and only a person's label brings it
back); `stuck:checks_refused` after two refusals; land only by the person. So one ingestion costs at most
3 plan + 3 implement agent runs and two checks relaunches.

**Nothing new (decided (review), finding 3).** The owner, 2026-11-10 ([.4.3.1.14](../tl-8bh9.4.3.1.14/plan.md) section
2): "no extra monitoring or redundancy until a real case; no stuck detection and no factory-side stopping"; and the
owner principle of 2026-10-29 (bd memory `owner-principle-2026-10-29-no-extra-monitoring`): let the system fail fast,
no extra monitoring or indicator systems. So the rounds keep taking tasks while attempts fail.

**Deferred until a real case: a global-failure stop.** A broken login, an expired account or a model name the provider
refuses fails every attempt fast, and one night would then hold every `auto` task the rounds reach (each with its
reason, each answered by adding the label back). A stop after N holds in a row was drafted and removed: it trips
falsely on N task-specific failures in a row (three bad tasks label-removed and the loop stopped for nothing), and it
misses the global failure whenever any in-flight task advances between the failures (a success resets it). A real
case should first show which signal names a global failure (for example the provider's error class on the execution
row) before any stop is designed. Not added either: a maximum of claimed tasks, a per-task cost or time cap beyond the
deadline and repeat cap, and the time-since-last-command column (B10, M5).

## 12. Abandon refusals, dirty slots and recovery after a reboot (D6, review finding 1)

**Decided (review):** a hold neither preserves nor resets what an attempt left in its slot. The release never resets
work, and no side-ref feature is added now. So a hold whose abandon is refused stays `Next: hold`, claimed by
`taskloop`, until the person clears the cause; its comment (written once the refusal is known to be the person's,
5.1 step 5) says so. Every refusal the abandon can give a hold, and what the person does:

| Abandon refusal | Typical cause | Comment written? | The person |
|---|---|---|---|
| `held:slot_dirty` | uncommitted agent work: `repeats_exhausted` leftovers, a failed implement whose settled release was held, `stuck:entry_lost` mid-write | yes, names the slot | saves what they need, then empties the slot's changes (`git -C <slot> status`; restore tracked files, remove untracked ones); the next round parks the slot and returns the claim |
| `held:slot_branch` | the slot was switched to another branch | yes | `tl step show` names the expected branch or park point; put the slot back |
| `held:slot_redirected`, `held:slot_unborn` | the slot's `.git` pointer or HEAD changed | yes | inspect; restore the pointer, or remove the slot and `tl slot adopt` again |
| `unavailable:slot_busy` | another factory process holds the slot's custody lock | no (transient) | nothing: retried next round |
| `unsettled:worker_alive` | the agent (or its group) outlived its dead entry | yes, names pid and group | waits, or stops that process by its pid (never by name); retried next round |
| `unsettled:worker_unknown`, `unavailable:setup_unknown` | a process could not be observed | no (transient) | nothing; if it persists, `tl step show` names the identity to check |
| `unsettled:setup_running` | a setup command still runs | yes, names pid | waits, or stops it by pid |
| `refused:landing`, `refused:landed` | a land candidate holds its slot or may be on origin (not expected for any section 3 cause) | yes | finishes or withdraws the land (`tl step land`), as the guide says |
| `unavailable:store`, `unavailable:git`, `unavailable:tracker` | transient | no | nothing |

**Accepted limit, and a non-blocking owner question (veto-able):** a hold that keeps the claim for leftovers needs a
person before the slot is free again; with a common cause (an implement attempt that left files) this takes a slot out
of the overnight loop until morning. A leftovers-preserving hold (commit the slot's changes to a side ref such as
`refs/taskloop/held/<attempt>`, then park) would free it unattended; **deferred**, Q1 in section 21.

**After a reboot:** no service. The person starts rounds again. Admitted attempts relaunch with a renewed deadline (as
built). An agent attempt whose entry died is `stuck:entry_lost` and, if the rounds took it, is held by the first round;
mid-write it usually stops at `held:slot_dirty` (or `unsettled:worker_alive` while an orphaned agent still runs), with
the comment naming the slot. A checks attempt relaunches or concludes as built. `tl step release --abandon` stays the
person's tool; B9 (session resume) stays deferred.

## 13. Keep-awake (B11, tl-8bh9.14.10)

Lifetime-scoped while `tl step rounds` runs (accepted 2026-11-09), one small module `keep_awake.py` (pure argv choice
plus a spawn port) and its wiring in `cli_composition.open_rounds`:

| Platform | Command (one helper child, its own session) | Ends when |
|---|---|---|
| macOS | `caffeinate -i -w <rounds pid>` | rounds exits (also on `kill -9`: `-w` waits for the pid) |
| Linux with `systemd-inhibit` on `PATH` | `systemd-inhibit --what=sleep:idle --who=taskloop --why="tl step rounds <backlog>" --mode=block tail --pid=<rounds pid> -f /dev/null` | rounds exits (`tail --pid` polls each second) |
| anything else | none | |

Spawn and signals (review finding 2):

- `stream_proc.popen_held` (composition only) opens a `TermHold` that swaps the SIGINT and SIGTERM handlers for a
  noting one and leaves them swapped until the caller calls `hold.replay()` (stream-proc 0.6.0 `hold.py`). So
  `open_rounds` spawns the helper **before** `interrupts.installed`, and the first statement inside the `try` whose
  `finally` runs `stream_proc.stop_tree(helper)` is `hold.replay()`: the previous handlers come back (a Ctrl-C during
  the spawn is replayed then, as Python's default `KeyboardInterrupt`, and the `finally` stops the helper), and only
  then does `interrupts.installed` put the rounds handler in place. Order: spawn, `try:` replay, `installed(...)`,
  rounds; `finally:` `stop_tree`.
- stdin, stdout and stderr go to one `/dev/null` file opened with `open(os.devnull, "r+b")` and closed after the spawn
  (never `subprocess.DEVNULL`: the policy bans the `subprocess` import); `start_new_session=True`, so the terminal's
  Ctrl-C reaches only rounds.
- `stop_tree` runs on the graceful end, a whole-round refusal and the abrupt `KeyboardInterrupt` (second Ctrl-C). A
  `kill -9` of rounds leaves the helper to end by itself (`-w`, `tail --pid`).
- **The one-signal-owner rule.** `interrupts.py` stays the only factory module that imports `signal`, so the
  import-linter contract `one-signal-owner` and the policy AST test are unchanged. The shelf's transient `TermHold`
  swap around one spawn is the shelf's own, as it already is for every `popen_registered` launch. Proposed note for
  CLAUDE.md and AGENTS.md (mirrored, **not edited now**; made with K1): after "The only signal use is `interrupts.py`'s
  SIGINT handler while `tl step rounds` runs (sets a flag, signals no process), enforced by the import-linter contract
  `one-signal-owner` and the policy AST test." add: "The shelf's own process API may hold SIGINT and SIGTERM for the
  duration of one spawn (`stream_proc.TermHold`) and replays them; that is the shelf's, not a factory signal use."
- Best effort: a missing tool is `rounds keep_awake unavailable:<why>` in the log and one stderr line; rounds run
  anyway. Started: `rounds keep_awake started pid=<n>`. The factory does not check that the inhibitor took effect.
- **Unobserved**: macOS (no Mac in this plan's evidence; `-i` prevents idle sleep only, so a closed lid on battery still
  sleeps); Linux without a logind session (OrbStack, SSH without polkit): `systemd-inhibit` exits at once and the
  effect is none. The smoke observes it (`systemd-inhibit --list`; `pmset -g assertions`).

## 14. Git read timeout (B13, tl-8bh9.14.3, review finding 6)

A FIFO or a stuck file system can hang a local Git read; the goal is "not forever", not a tight bound.

- **Shelf API (git-porcelain 0.18.0, as built, G1):** `RealRepo(..., read_timeout: float | None = None)`. One classifier,
  `real_reads.is_read(args)`, names the read-only commands (`status`, `diff`, `ls-files`, `ls-tree`, `rev-parse`,
  `rev-list`, `merge-base`, `cat-file`, `log`, `cherry`, `grep`, `for-each-ref`, `check-ignore`, `worktree list`); the one
  runner gives such a call `timeout=read_timeout` and `GIT_OPTIONAL_LOCKS=0` (so no bounded call takes the index lock),
  unless the call passes its own timeout. Chosen over a per-call-site flag: one list owns the fact, and a new write
  command is unbounded until someone lists it. Not bounded: every call that writes the index, refs or files (commit,
  checkout, worktree add, update-ref, add, reset), the temporary-index tree build (`read-tree`, `add -A`, `write-tree`),
  `config` and `symbolic-ref` (both write when given a value), and remote calls (`remote_timeout`). A timeout is the
  existing `GitTimeout` (a `GitUnavailable`) naming the command and the seconds. `FakeRepo` gained nothing: the factory
  fakes a `GitTimeout` itself.
- **The hang G1's test must reproduce:** a FIFO with no writer at `$GIT_DIR/info/exclude`, then `status` (Git opens the
  exclude file while listing untracked files, and `open` of a writerless FIFO blocks). The test first shows the hang
  without a bound (it runs the read in the shelf's own supervised runner with a short wall limit and expects that
  limit to fire), then shows `GitTimeout` with `read_timeout=2`. If Git turns out to skip non-regular exclude files,
  G1 uses the next reader that opens a path it does not stat first (`core.excludesFile` or a FIFO `.gitattributes`
  read by `check-attr`) and says which in its commit; the test must hang without the bound before it counts.
- **Factory (G2), as built:** machine config key `git_read_seconds` (default **600**, at least 30; no flag), pinned
  git-porcelain 0.18.0. `git_views` builds every `RealRepo` (`checkouts`, `remotes`, `inspect_checkout`) with
  `read_timeout=READS.seconds`; `cli_step.run` sets it once from the loaded config (`use_read_seconds`). An attempt's
  entry process (`attempt_entry`, `check_entry`) loads no machine config and keeps the default 600: only the round and the
  commands the person runs read the key. No new word: a timeout is `unavailable:git` with the shelf's message as
  detail (`admit`, `check_admit`, `land`, `slots` already map `GitUnavailable`; `slot adopt` reports `git_unavailable`),
  an unknown the round backs off from and retries. The real-Git test
  (`tests/steps/real/test_git_read_timeout_real.py`) puts a FIFO at the repository's `info/exclude`, bounds reads at 2 s
  and shows `slot adopt` ends `git_unavailable` instead of hanging, then adopts once the FIFO is gone. The cold-read
  measurement the plan asked for was not taken: 600 stays the default.
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
| H1 | Schema v14, the label on the attempt, the hold store, the tracker's hold writes, the comment | `factory_schema` v14 (`attempt.label`, `task_hold`, `HOLD`); `admit` writes the label (`AdmitRequest.label`, NULL from `tl step start`), `admit_chain` copies it; `hold_store.py`; `tracker_client.TrackerHolds` (`labels` per 5.2, `comment`, `clear`, each bd call capped) and the unclaim mapping of 5.3; `hold_text.py` (section 6, by abandon outcome); WRITERS policy entry | about +370 (`hold_store` 160, `hold_text` 100, `tracker_client` +75, schema +20, admission +15) | about +520 (`test_hold_store` every CHECK and fence incl. the comment lease, `test_tracker_holds` with `beads_client.testing.Script`, unclaim of closed and missing, `test_hold_text` per outcome, label written and copied) | B6 built |
| H2 | The hold operation and its words | `hold.py` (`cause` with the label rule, `hold_task` 5.1 (it checks right before the label step that A is still current; `HoldStore.labelled` fences it again, `changed`), `clear_holds` 7.3); `attempt_status` (`hold`, `on_hold`, `AttemptView.hold` looked up by the agent attempt, `--stuck` includes `hold`); `show_render`/`step_render` `Hold:` lines; `step_guide` guides naming section 12's action per refusal; `result_data`; `operations.Action` gains `hold`; the answer's `explanation` on the collected result if missing; glossary | about +310 (`hold` 210, status +30, render +25, guide +35, data +10) | about +560 (`test_hold`: section 3 incl. NULL label; every partial rerun; each 5.2 row; each section 12 refusal and whether it comments; two concurrent callers comment once; the swapped checks view's lookup; status words) | H1 |
| H3 | The round applies it | `round` (9.1-9.5), the round's label into admission, `RoundPorts.holding` and its wiring in `cli_composition`; `round.py` split if over 400 | about +60 | about +330 (`test_round_holds`: each cause held once and quiet after; a pending hold's line again only when its refusal changes; re-ingestion of `moved` and `absent`, the `abandoned` skip kept for others and for hand abandons; a differing round label; hand-started tasks never held; clear incl. re-hold and `superseded`) | H2 |
| K1 | Keep-awake (tl-8bh9.14.10) | `keep_awake.py` (argv by platform, `Awake` with `stop`); `open_rounds` order (spawn, replay, `installed`, `stop_tree` in `finally`); two log words; the mirrored CLAUDE.md/AGENTS.md note of section 13 | about +100 | about +170 (argv per platform, missing tool, replay before `installed`, stop on each exit path with a fake spawn port) | none |
| G1 (done: shelf PR 81, git-porcelain-v0.18.0) | git-porcelain `read_timeout` (shelf repository) | section 14's API per call with `GIT_OPTIONAL_LOCKS=0`, on the unreleased 0.17.0 branch; the hang test | shelf about +60 | shelf about +120 | none; **owner release** |
| G2 (done, tl-isfa.5) | Pin and use the read timeout (tl-8bh9.14.3) | pin git-porcelain 0.17.0 (also unblocks M3's multi-URL guard, tl-8bh9.14.8 section 27.1 item 4, which may land in the same commit); `machine_config` key `git_read_seconds`; `git_views` passes it; the measurement in the commit message | about +25 (+15 with the guard) | about +60 (config bounds; a fake `GitTimeout` read is `unavailable:git` with its detail) | G1 released |
| S | M4 live smoke | runbook `live-smoke.md` here, the run, `m4-smoke-findings.md` | none | none | H3, K1, G2 |

H1 to H3 are B7. K1 and G1/G2 are independent of them and of each other; they can be built first.

## 16. Tests

Focused pytest functions and classes on semantic fakes, as the existing step tests do; no subprocess, no live runs.
Each slice's table cell above names its tests; across them:

- `hold.cause`: every row of section 3, including the `no` rows and a NULL `attempt.label`.
- `hold_task`: the full sequence; a crash after each step (the rerun does only what is missing); each 5.2 row (closed
  and missing write nothing and end `not_held`); a stale fence (`labels` unset, retried); each section 12 refusal
  (comment written or not, claim line text, `Next: hold`); a lost insert race (`refused:changed`, no tracker call);
  two callers racing to the comment (one `Bd.comment`); a lease older than `COMMENT_LEASE` retaken.
- `hold_store`: every CHECK with its NULL case; the insert fence; `uncleared()` never lists `not_ours`/`closed`/
  `missing`.
- `TrackerHolds`: argv and order through `beads_client.testing.Script` (fence before labels, `held` before the
  stored label), exit 13 to `precondition`, timeouts to `unavailable`; unclaim "cannot unclaim closed issue" and "no
  issue found matching" to False.
- `hold_text`: caps (explanation 2000, 10 checks, 20 paths, 6000 total), control characters removed, one claim line
  per outcome, never "returned" before the abandon recorded it.
- Round, keep-awake, G2: as in section 15.

## 17. Live smoke outline (S; owner- or authorized-agent-run)

Scratch repository, bare remote and tracker under `~/tl-smoke/m4`, a runner worktree at the commit under test, two
slots, removed afterwards; nothing pushed anywhere else.

1. Tasks, all `auto`: A asks for something only the owner can decide (expect `needs_owner`); B adds a test that fails
   the profile's required `test` check; C a small clean change; D one whose `task/<id>` the person moves on origin
   between implement and the check advance; E one whose entry gets `kill -9` during implement; F one the person starts
   by hand with `tl step start` and that fails (expect no hold); G one the person closes (`bd close G --force`)
   while its plan attempt runs.
2. `tl step rounds ... --label auto` for at least two hours (the overnight shape, shortened). Expect: C at `land`;
   A, B, D held once each (one `hold held` line each, then silence; comment says the claim is returned; `held`, no
   `auto`, open and unassigned). E: `Next: hold` with `held:slot_dirty`, `unsettled:worker_alive` or
   `unsettled:worker_unknown` (any is accepted), in `tl step list --stuck`, claimed by `taskloop`; its comment (for
   the first two) names the slot or the pid and says the claim is still held. F: a failed `done`, no hold, no tracker
   write. G: held with `labels` `closed`, no comment, no label written, the slot parked, the claim `not_held`, the task
   still closed.
3. Dirty slot: clear E's cause (save and remove the files, or wait for or stop the worker by pid). Expect the next round
   to park the slot, return the claim and finish the hold (`on_hold`); no second comment.
4. Answer A: edit its description, `bd label add A auto`. Expect the next round to start A at plan (attempt seq
   advanced, on the same `task/A`), `held` removed (`hold cleared`), and A to reach `land`.
5. Label rule: stop rounds; take a new task H under label `auto` and let it fail; restart the rounds with
   `--label auto2` before H's hold runs (H also carries `auto2`). Expect H's hold to remove `auto` (the label it was
   taken under) and keep `auto2`, and the `auto2` rounds to skip H (`abandoned`: their label is not H's stored one).
   Then `bd label add H auto` and rounds under `--label auto`: H is taken again at plan.
6. Keep-awake: while rounds run, `systemd-inhibit --list` (or `pmset -g assertions`) shows `taskloop`; after one Ctrl-C
   (graceful), after Ctrl-C twice (abrupt) and after `kill -9` of rounds it is gone within two seconds, and the
   terminal shows no traceback from the helper. On a host without logind: `keep_awake unavailable` and the rounds
   unaffected.
7. Git read timeout: with G2 pinned and `git_read_seconds = 30`, a FIFO at a slot's `$GIT_DIR/info/exclude` (G1's
   case) makes that slot's status read end after 30 s as `unavailable:git`; the next round proceeds once it is removed.
8. Land C and A by hand as in M3; `bd list --label held` lists exactly the held, unanswered tasks at the end.

## 18. Changes to existing behavior

- A failed checks attempt of a round-taken task is held and abandoned, so `tl step start` no longer re-runs it after a
  round has seen it (7.4). M2's "visible failed `done`, claim kept" becomes a hold.
- `stuck:*` (except `stuck:hung`) and `repeats_exhausted` of a round-taken task are no longer only reported: the round
  holds them.
- Advance `claim_lost`/`branch_moved` and publish `branch_moved` of a round-taken task stop being retried every round.
- Tasks started by hand (`tl step start`, `attempt.label` NULL) are never held; rounds still advance and report them.
  A re-ingested task's new attempt carries the round's label; a held task the person restarts by hand does not.
- A hand `tl step release --abandon` of a closed task no longer stays `unclaiming` forever (5.3).
- `tl step next` beside `tl step rounds` may run the same hold; the fences (insert, label fence, comment lease, the
  abandon's own) make it do each step once.
- `tl step list --stuck` also lists `hold`.
- The roadmap's M4 "still by hand: reboot recovery (`--abandon`)" shrinks to clearing what section 12 names.

## 19. Risks

| Risk | Mitigation |
|---|---|
| A broken login holds every `auto` task the rounds reach in one night | accepted (no factory-side stopping, section 11); each hold names its reason; the person adds the labels back after fixing the login |
| A hold kept by leftovers takes a slot out of the loop until the person acts | accepted limit (section 12); Q1 asks whether a leftovers-preserving hold is wanted |
| Each section 12 refusal | its own row: comment or not, and the person's action |
| The label steps are not one atomic write (fence, then two label calls) | the same accepted gap as the land's close; the window is the factory's own claim; a later beads-client `update(add_labels=, remove_labels=)` makes it one guarded call (measured to work in bd 1.3.1) |
| A crash between the comment and `commented_at` | a second comment after `COMMENT_LEASE`, accepted; concurrent callers cannot both comment |
| The person adds the label back within seconds of a crashed label step, and the rerun removes it | accepted: the hold's comment comes after, so the person sees why; documented in the guide |
| A held task restarts at plan and the plan agent answers `unchanged` without reading the edit | the plan input carries the edited description; acceptance names the change; the person reads the next result |
| Agent text in the tracker | capped, control characters removed, never fed back to an agent |
| `stuck:hung` holds a slot all night | D7; reported once; the person abandons by hand in the morning |
| Keep-awake silently ineffective (no logind, battery lid close on macOS) | best effort, logged; the smoke observes it per machine |
| The keep-awake spawn holds SIGINT for its duration | replayed before the rounds handler is installed (section 13); smoke step 6 |
| A Git read in an uninterruptible file-system call still hangs | named residual (section 14) |
| The schema discard loses landed history | as every earlier discard; land or abandon first |

## 20. Decisions made here (owner may veto)

1. A hold is an abandon plus a tracker note: label removed, `held` added, claim returned when the slot allows, one
   comment written after the abandon's outcome is known (O5's recommendation, made concrete).
2. Section 3's table: what holds and what does not (`stuck:hung` and admission branch refusals do not).
3. Only round-taken tasks are held (`attempt.label` not NULL); hand-started ones are not.
4. The label removed is the one the task was taken under, stored on the attempt (v14), not the round's `--label`.
5. factory.db owns the hold record (`task_hold`); the tracker owns the reason text and the labels; nothing reads the
   comment or `held` for control.
6. Labels before the abandon, the comment after it; `held` added before the approval label goes; a comment lease
   against concurrent callers.
7. 5.2's table: the factory edits labels only of a task it holds or that is unassigned, never another actor's, and
   writes nothing for a closed or missing task; the unclaim maps bd's closed and missing refusals to `not_held`.
8. Re-ingestion: an `on_hold` task with `labels` `moved` or `absent` is eligible when its stored label is back and is
   the round's label; every other abandon keeps the `abandoned` skip.
9. The factory removes `held` after the task is taken again (`clear_holds`), with no read first.
10. Failed checks are held too, at the cost of a plan and implement run on restart (7.4).
11. `Next` words `hold` and `on_hold`; tracker label `held`; `hold` in `--stuck`; no `--held` flag.
12. Keep-awake: `caffeinate -i -w` and `systemd-inhibit ... tail --pid`, best effort, spawned before the rounds handler
    with the shelf's hold replayed first.
13. Git read timeout: per call with `GIT_OPTIONAL_LOCKS=0`, machine config `git_read_seconds` (600 s), folded into the
    unreleased git-porcelain 0.17.0.
14. B10 is not part of M4.

Decided (review): no circuit breaker (section 11); holds neither preserve nor reset leftovers (section 12).

## 21. Owner questions

**Blocking:** none.

**Non-blocking, veto-able (Q1):** should a hold that finds leftovers in the slot commit them to a side ref (for example
`refs/taskloop/held/<attempt>`) and then park the slot, so it frees the slot and returns the claim unattended?
Recommendation: not now (decided (review)); revisit if the M4 smoke or real nights show slots kept until morning.

**Owner action (done):** the shelf's git-porcelain 0.18.0 (with `remote_urls` in 0.17.0 and `read_timeout`) was merged and tagged.

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

## 23. Review of 5f775790e and what changed

| # | Finding | Disposition |
|---|---|---|
| 1 | A hold whose abandon meets a dirty slot (or a live or unobservable worker) never finishes unattended | taken: section 12 (every refusal and the person's action; accepted limit; Q1), 5.1 step 5 (comment after the abandon, state-dependent, never claiming a return early), 10 (`hold` in `--stuck`, a guide naming the action) |
| 2 | `popen_held` leaves the handlers swapped until `replay()` | taken: section 13 (spawn before `installed`, `replay()` first in the `try`, `/dev/null` opened natively, the one-signal-owner note proposed for CLAUDE.md and AGENTS.md, smoke step 6) |
| 3 | The circuit breaker contradicts the owner's "no factory-side stopping" | taken: removed from section 11, the slices, the smoke and the risks; kept as a deferred note with its false-trip and miss problems |
| 4 | `clear_holds` against the v14 CHECK; re-hold race; needless read | taken: 7.3 (`uncleared()` by `labels`, `superseded`, re-hold skip, no `Bd.show`) |
| 5 | The hold removed the round's label, not the one the task was taken under | taken: `attempt.label` (v14), `moved`/`absent` (5.1, 7.2), smoke step 5 |
| 6 | Optional locks, per-call classification, a larger configurable bound, a test that really hangs | taken: section 14 |
| 7 | The swapped checks view's hold lookup | taken: section 10 (`checks.row.after_attempt_id`) |
| 8 | Unclaim of a closed task | measured (5.4): bd refuses and writes nothing, so the task is not reopened; the abandon would stay `unclaiming`: taken as 5.3's mapping, and the hold writes nothing for a closed or missing task (5.2) |
| 9 | Hand-started tasks held; a concurrent `tl step next` comments twice | taken: section 3 (round-taken only, by `attempt.label`) and the comment lease (5.1 step 5); section 18 lists both |
| 10 | Smoke: E's words, breaker steps, missing cases | taken: section 17 (E accepts all three words; dirty-slot, label-rule and closed-task steps; breaker steps gone) |

## 24. As built: H1 (tl-8bh9.14.9.1)

Schema v14, the label on the attempt, `hold_store.py`, `tracker_client.TrackerHolds` with the unclaim mapping of 5.3,
`hold_text.py` and the policy entries; nothing of H2 or H3 (no `hold.py`, no round behavior, no `Next` words: nothing
holds a task yet). Code lines by the policy counter: `hold_store` 104 (new), `hold_text` 118 (new), `tracker_client`
147 (+57), `factory_schema` 226 (+17), `admit` 284 (+1), `admit_chain` 261 (+0), `operations` 366 (+0);
`test_hold_store` 217 (new), `test_tracker_holds` 109 (new), `test_hold_text` 87 (new), `test_slot_release` 404 (+19),
`test_admit` 468 (+10), `test_admit_chain` 312 (+19), `test_policy` 189 (+3).

- **DDL** as section 8 (its inline SQL comments left out), with one repair (deviation 1). v13 and every other version
  are refused `schema` (`test_operations`' foreign list now holds 13 and 15; `test_land_store`, `test_check_store` and
  `test_hold_store` assert v14 and refuse v13). `ATTEMPT_ADMITTED` gains `label`; `HOLD` is the hold's column list.
- **The label**: `AdmitRequest.label` (no default); the admission stores it; `admit_chain` copies it on a repeat (the
  previous attempt's) and an advance (the task's current attempt's). `operations.start` passes None for every fresh
  admission, `tl step start` and the round's alike: H3 passes the round's (section 9.3).
- **`hold_store`**: `HoldInsert`, `HoldRow` (joined with A: backlog, task, tracker root, `label`), `Uncleared` (`row`,
  `held_again`: the task's current attempt has its own hold); `HoldStore` with `insert` (fenced as 5.1 step 1:
  `unlabelled` for a NULL label, else `changed` when A is not current with its cause or already held; cause A is
  current while `factory_schema.SUCCESSOR` is false, a checks cause while it is A's latest, not abandoned, and no later
  attempt of the task exists), `labelled(attempt, rev, word, now)` (once), `commenting(attempt, rev, now)` (the lease:
  `labels` `moved`/`absent`/`not_ours`, no `commented_at`, no lease or one older than `COMMENT_LEASE` = 120 s; None when
  not taken), `commented(attempt, rev, now)` (under a lease), `cleared(attempt, rev, now)` (A not current, labels NULL,
  `moved` or `absent`; NULL becomes `superseded` with `labelled_at` in the same write); reads `of_attempts(ids)` and
  `uncleared()` (oldest hold first). Every write after the insert is fenced on `rev` and its phase, bumps `rev`, returns
  the row as written, and is `StoreRefused("changed")` off its fence (the lease: None).
- **`tracker_client`**: `TrackerHolds(labels, comment, clear)` built by `tracker_holds(run, client)`, each bd call
  capped at `BD_TIMEOUT_S`. `labels(root, task, stored_label) -> HoldAnswer[LabelStep]`: one `Bd.show`; `missing`,
  `closed` (whoever is assigned) and `not_ours` (an assignee other than `taskloop` and none) write nothing; else
  `Bd.add_label(task, "held", if_assignee=<the assignee read>)` (the same-value fenced update, then the add) and
  `Bd.remove_label(task, stored_label)`, word `moved` when the label was on the task, `absent` otherwise. A stale fence
  is `precondition`, bd's "no issue found matching" `missing`, any other failure `unavailable` with bd's error kind.
  `comment` and `clear` (`Bd.remove_label(task, "held")`, no read) answer `done`, `missing` or `unavailable`. The
  claims' `unclaim` returns False (recorded `not_held` by the release) for bd's "cannot unclaim closed issue" and
  "no issue found matching"; every other failure still raises (the abandon stays `unclaiming` and is retried).
- **`hold_text.comment(facts, outcome)`** as section 6, with `HoldFacts` (the hold, the cause's facts and the label word),
  outcome `Returned(claim)` or `Kept(word, slot, pid, pgid)`. Every quoted part one printable line of at most 300
  characters (check names 100, conclusions and repeat reasons 40, the label 200); the explanation keeps its newlines,
  at most 2000 characters; 10 checks and 20 paths, then `and <n> more`; at most 6000 in all, the details shortened
  (`[shortened]`) before the claim line and the answer.
- **Policy**: `WRITERS` gains `CREATE TABLE task_hold` (`factory_schema.py`) and `INSERT`/`UPDATE task_hold`
  (`hold_store.py`); `.importlinter`'s `rounds-never-land` also covers `hold_store` and `hold_text`.

**Deviations (decided here, open to veto).**

1. `CHECK(commented_at IS NULL OR labels IN ('moved','absent','not_ours'))` accepted a comment with `labels` NULL (a
   NULL `IN` is not false); built as `commented_at IS NULL OR (labels IS NOT NULL AND labels IN (...))`, the
   `land_candidate` spelling. Its test covers the NULL case.
2. `ATTEMPT_LOADED` does not gain `label`: it is the entry's fenced `Admission` read, which never uses the label. H2
   reads the label through the hold row (joined) and adds it to the status read where `attempt_status` needs it.
3. The comment's claim line (section 6) is composed from the label word and the abandon's outcome, so it never states
   a label write or a claim return that did not happen: `moved` "removed `<label>` and added `held`", `absent` "added
   `held` (`<label>` was not on the task)", `not_ours` "changed no label"; `Returned("unclaimed")` "and returned its
   claim", `Returned("not_held")` "the claim was no longer the factory's". A `not_ours` hold is answered by `tl step
   start` (7.2 keeps its `abandoned` skip), not by re-adding the label. `refused:landing`/`landed` (section 12, "comment
   yes", no text in section 6) say a land holds the slot or may be on origin and name `tl step land <id>`.
   `claim_lost`'s line is "Someone else changed this task's claim while the factory worked on it." (true whether the
   abandon finished or not).
4. `HoldStore.insert` refuses a NULL label as `unlabelled`, not `changed`: it is no race, and H2's `cause` never asks.
5. The round's admissions still store NULL until H3 (above); this keeps H1 free of round behavior.

**Review repairs of af1f04233 (2026-11-12).**

1. Every `TrackerHolds` bd call is one try (`lock_retries=0`, as the heartbeat): with bd's three lock retries a call
   could take about 121 s and outlast `COMMENT_LEASE`, so two callers could comment. A locked tracker is
   `unavailable`, retried by the next round.
2. Every line of the agent's explanation is quoted (`> `) under its own `The agent explained:` line, so an explanation
   cannot forge a header, a claim line or an answer.
3. `absent` is worded "`<label>` is no longer on the task": the word comes from this call's read, which after a crash or
   a race may follow the factory's own removal.
4. `uncleared()`'s `held_again` counts only a newer hold whose labels are NULL, `moved` or `absent`; a newer `not_ours`,
   `closed` or `missing` hold wrote no label, so the old `held` is still removed.
5. `commenting` refuses a cleared hold; `labelled` is fenced on A still being current (`changed` otherwise: the row is
   superseded by `cleared`).
6. **Accepted residual:** the unclaim's `GONE` mapping ("no issue found matching") also matches a stored tracker root
   that now resolves to another or re-initialised tracker; the abandon then records `not_held` and the real claim
   stays behind with no retry (before: `unclaiming`, retried). Accepted as for the heartbeat, which already maps `GONE`
   to `lost`.
7. The comment names an unknown slot "its slot" and an unknown pid "pid unknown: `tl step show <id>` names it";
   `TrackerHolds.labels` refuses an empty label or one starting with `-` (bd would read it as a flag) as `bad_label`
   before any bd call.

**Unverified.** The bd texts are as measured in section 5.4 (not re-measured): the unclaim mapping matches both on
bd's JSON `error` and on stderr. No live bd run in H1.

## 25. As built: H2 (tl-8bh9.14.9.2)

The hold operation, its words in the status and its text; nothing of H3 (the round does not call `hold_task` or
`clear_holds`, admission still stores a NULL label, `selection` is unchanged), K1 or G1/G2. Code lines by the policy
counter: `hold` 134 (new), `hold_facts` 63 (new), `hold_guide` 67 (new), `hold_status` 40 (new), `attempt_status` 230
(+20), `attempt_reads` 206 (+10), `result_data` 139 (+7), `step_guide` 194 (+3), `step_render` 132 (+3), `show_render`
103 (+1), `operations` 366 (+0: `Action` gains `hold` in place), `cli_step` 195 (+0: the `--stuck` help), `hold_text`
121 (+0); `test_hold` 293 (new), `test_hold_status` 170 (new), `test_step_cli` 592 (+0: the JSON key set).

- **`hold_status`** (pure): `cause(view)`, section 3 over the view's own word: `done` or `release` with a collected,
  not succeeded result is `failed:<reason>` (a checks attempt's reason already reads `failed:<reason>`, not doubled);
  `repeats_exhausted:<repeat reason>`; every `stuck:*` but `stuck:hung`; None for a NULL `label` and for a view whose
  release is already an abandon (`ReleaseRow.abandoned`: a person's, or a hold's under way). `finished(row, release)`
  (5.1), `hold_next` and `reingests(word, row, label)` (7.2: `on_hold`, `labels` `moved`/`absent`, stored label equal
  to the round's), the rule H3 puts in the admission's `attempts` map.
- **`attempt_status`**: `AttemptView` gains `label`, `hold` and `hold_due`; `Next` gains `hold` and `on_hold`.
  `with_hold` applies after every other rule except `unknown`: a hold row gives `hold` or `on_hold`; with no row, a
  labelled view with a cause is `hold` with `hold_due` (due: the next round records it). The hold is read once per
  show or listing (`HoldStore.of_attempts`) by `agent_attempt(view)`: the view's own attempt, or a checks view's
  `checks.row.after` (the plan's `after_attempt_id`); an unreadable hold table is `unknown`. `--stuck` lists `hold`,
  never `on_hold`. `AttemptRow` gains `label` and `end_commit` (one query); `AttemptReads.slot_path(attempt id)` reads
  an agent or a checks attempt's slot path for the comment.
- **`hold.hold_task(ports, view, reason=None)`** (5.1): re-reads the hold of A first (a round snapshot may be stale);
  no hold: `HoldStore.insert` with the reason (default `view.hold_due`; none: `refused:no_cause`), cause the view's
  attempt (a checks view: the checks attempt); a refused insert is `refused:changed`/`refused:unlabelled`, nothing
  else done. Labels: A still the task's current attempt (`attempt_of`), else `refused:changed` with no tracker call;
  `TrackerHolds.labels`; the five words are recorded by `labelled`; `precondition` and `unavailable` are pending
  `unavailable:tracker` (detail `precondition...` or bd's kind), `bad_label` pending `refused:bad_label`. Abandon: A
  must still be current again (else `refused:changed`: the abandon acts on the task's current attempt), then
  `operations.release_task(abandon=True)`. Its outcome (`hold_facts.outcome`): `Returned(claim)` for `unclaimed` or
  `not_held`; `Kept` for section 12's person-cleared words, naming the slot path (the checks attempt's when the checks
  release refused) and the process (`worker_alive`: A's registered agent; `setup_running`: the latest setup run's
  unsettled command; `check_running`: an unsettled check's command); `Pending` otherwise (no comment). Comment (labels
  `moved`/`absent`/`not_ours`, none yet): under the lease (`commenting`; lost: pending `comment` `refused:leased`),
  text by `hold_text.comment(facts, outcome)`, then `commented`. Result `HoldMove(task, A, step, reason, word,
  missing, refusal, detail)`: `held` when this call finished it; `pending` with the first missing step (`labels`,
  `abandon`, `comment`) and the refusal word (`held:slot_dirty`, `unsettled:worker_alive`, `refused:landing`,
  `unavailable:tracker`, `unavailable:store`, ...); `refused`.
- **`hold_facts.facts`** (as repaired: review repair 1 below): the cause as the view shows it, A's X (`end_commit`) and publication, a checks view's failed
  checks (every latest-block result not `passed`; `undefined` has no log), a `repeats_exhausted` hold's leftovers from
  the view, the cause's evidence directory, and the explanation: the stored valid answer's file read through
  `EvidenceFiles` (digest-checked) and decoded by the step kind's own `decode` via `any_agent.decode_answer` (no new
  column and no second parser; an unreadable file is no explanation).
- **`hold.clear_holds(store, tracker, clock)`** (7.3): each `uncleared()` row; `held_again`: only `cleared` (no
  tracker call); else `TrackerHolds.clear` with no read (`done` or `missing`), then `cleared` (`superseded` for a NULL
  label step); `unavailable` leaves the row for the next round. Returns one `Cleared(task, A, word)` per row.
- **Show, list, JSON, guides**: `tl step show` adds `Hold: <reason> at <UTC> (cause <id>)`, `Hold tracker: <labels
  words>, commented|not commented yet|no comment` and `Hold claim: returned|not held|kept: the abandon has not
  finished`, or `Hold: due <reason>`; the `hold` guide (`hold_guide.HOLD`) names every section 12 refusal with its
  action and the transient ones; `on_hold`'s guide has the task id and stored label filled in, the `branch_moved` and
  `claim_lost` lines, and the `not_ours` and closed/missing variants; an `on_hold` view no longer gets the abandoned or
  `UNCLAIMING` text. `tl step list` prints `hold: <guide>` once (no discard steps unless a `stuck:*` row is listed).
  JSON: `label`, `hold` (`reason`, `cause`, `label`, `held_at`, `labels`, `labelled_at`, `commented_at`,
  `cleared_at`) or null, and `hold_due`.
- **Policy**: `.importlinter` lists `hold`, `hold_status`, `hold_facts` (and `hold_guide` for the entry contract) in
  `rounds-never-land` and `cli-never-imports-the-attempt-entry`.

**Deviations (decided here, open to veto).**

1. `Next: hold` also covers a due hold (a labelled view with a cause and no row), so `tl step list --stuck` shows it
   and H3's settle needs only `each.next == "hold"` with `each.hold_due` (or the recorded `hold.reason`) as the reason;
   `cause` still reads the view's own word, before `with_hold` replaces it.
2. A view whose release is already an abandon (a person's half-done `tl step release --abandon`) has no cause: the
   person's abandon is not turned into a hold.
3. The abandon is fenced on A still being the task's current attempt (as the label step is): `release_task` abandons
   whatever attempt is current, so a stale snapshot must not abandon a task taken again meanwhile.
4. `check_running` (a check command still running after its checks entry died) is added to `hold_text.KeptWord` and
   comments now like `setup_running`; section 12 does not list it.
5. A comment answered `missing` (the task deleted after the label step) is recorded as commented: a deleted task can
   take no comment, and the hold would otherwise never finish. An `unclaiming` claim (`AlreadyReleased`) is
   `Pending` (`release:unclaiming`).
6. The reason of an agent's failed result is `failed:<result reason>` as the result prints it: a valid `needs_owner`
   answer is `failed:needs_owner` (section 3's example `failed:answer:needs_owner` names the invalid-answer words
   `answer:<kind>`).
7. `tl step show` cannot know an abandon's refusal word without attempting it, so `Hold claim:` says `kept: the abandon
   has not finished` and the guide lists every section 12 word with its action (the round's `hold pending` line names
   the word).

**Review repairs of 88a0ab5be (2026-11-12).**

1. The comment's cause facts come from the stored hold, not from the caller's view: `hold_facts.facts(files, reader,
   row, labels, A's row, leftovers)` loads a checks cause by `row.cause_id` (`CheckStore.of_attempt(A)`, its latest
   block's results from the store) for the step `check`, its number and id, the failed checks and its evidence
   directory, with no explanation; an agent cause is A with the explanation of A's stored execution (`attempt.collect`).
   A comment retried after the abandon (the view is then A's agent view) therefore still describes the checks attempt.
   Only the `repeats_exhausted` leftovers come from the caller's view, when that view is A's own.
2. `hold_text.Kept` carries `claim`: `ours` (the label step read `taskloop` as assignee), `not_ours` (another actor,
   or none: the claim had lapsed; also forced by the `not_ours` labels word) or `unknown` (the label step ran in an
   earlier call; nothing stores the assignee). Only `ours` says "still holds the claim ... the next round returns the
   claim"; the others say "keeps the attempt's slot ... the next round frees the slot" (`unknown`: "and returns the
   claim if it is still the factory's"). `TrackerHolds.labels` returns the assignee it read as the `detail` of `moved`
   and `absent`.
3. `clear_holds` reads the task's current hold again right before each tracker call (`HoldStore.current_hold`, a new
   read): `moved`/`absent` owns `held` (only `cleared_at`); a hold whose label step has not finished leaves the row for
   a later round (`pending:held_again`, detail the new hold's attempt), since it may yet end `not_ours`; none, or one
   that wrote no label (`not_ours`, `closed`, `missing`), removes `held`. `Uncleared.held_again` is no longer used by
   it.
4. The transient slot lock word is `unavailable:slot_busy` (as `release_task` reports it), in section 12's table and the
   `hold` guide.
5. `tl step list --stuck` probes the leftovers of every labelled attempt (`row.label` not NULL), so a due
   `repeats_exhausted` hold is listed; a hand-started attempt is still never probed.

**Unverified.** No round runs a hold until H3; no live bd or Git run in H2 (tracker and abandon are semantic fakes).

## 26. As built: H3 (tl-8bh9.14.9.3)

The round applies holds; nothing of K1 or G1/G2, and no breaker or any other stop of the rounds (section 11). Code lines
by the policy counter: `round` 285 (+29; under 400, so no `round_publish.py` split), `operations` 367 (+1),
`cli_composition` 235 (+5), `cli_step` 197 (+2), `step_guide` 195 (+1); `test_round_holds` 204 (new), `round_bench` 193
(+43), `test_checks_round` 337 (+7), `test_round` 544 (+4), `doubles` 313 (+9), `test_step_cli` 594 (+2).

- **`RoundPorts.holding`**: `hold.HoldPorts` (the hold store, the attempt reader, `TrackerHolds`, the agent attempt's and
  the checks attempt's release ports, the clock, the evidence reader), placed before `ready`. `cli_composition.open_next`
  wires it for `tl step next` and every `tl step rounds` round: `HoldStore` on the round's shared writer,
  `tracker_holds()`, the same `open_releaser` the round uses and `open_checks_releaser` (as `tl step release
  --abandon`), `time.time`, the artifacts root.
- **Settle (9.1)**: `Next: hold` (due, or recorded and not finished: H2's deviation 1) is `hold.hold_task(holding, view)`
  and nothing else for that attempt; `on_hold` writes nothing and calls nothing. Section 3's rule is `attempt_status`'s
  (a NULL `label` never gets `hold`), so a hand-started task's failure is reported as before.
- **Advance (9.2)**: a refusal `claim_lost` or `branch_moved` (kind `refused`, not a stop, nothing admitted) of a view
  whose `label` is set is `hold_task(..., reason)` instead of the `skip`; a hand-started task keeps the `skip`.
- **Admit (9.3)**: the `attempts` map passed to `selection.order` leaves out every view for which
  `hold_status.reingests(view.next, view.hold, round label)` holds (`on_hold`, `labels` `moved`/`absent`, stored label
  equal to the round's); every other abandon keeps the `abandoned` skip. `StartRequest.label` (default None) carries the
  round's label (`round._request`) into a fresh admission's `AdmitRequest.label`; `tl step start` passes None; an advance
  and a repeat copy their attempt's (H1).
- **Publish (9.4)**: `publish_task` refused `branch_moved` of a labelled view is `hold_task(..., "branch_moved")`.
- **Clear (9.5)**: after publication, unless the round was stopped gracefully (its stopped word `interrupted`, or
  `stopping` asked true), `hold.clear_holds`; one move per row it returns.
- **Move lines** (action `hold`, the step of the view, the hold's agent attempt A): `held <reason>`, `pending <missing
  step> <refusal>` (for example `pending abandon held:slot_dirty`, `pending labels unavailable:tracker`), `refused
  <refusal>` (a lost race, `refused:changed`); `cleared` and `clearing <word>` (no step: the row's task and A). Quiet as
  every move: an unchanged line is written once; a changed refusal is a new key and is written again. A finished hold is
  `on_hold` from the next round on and costs no tracker call and no line. No hold word is a stop word: admission,
  advances and the back-off are untouched.
- **Help**: `tl step next` and `tl step rounds` say the round holds the tasks it took that stopped (`bd list --label
  held`) and removes `held` once a held task is taken again.
- **Changed behavior in existing tests** (section 18): a round-taken task's failed checks, `stuck:checks_refused`,
  `failed:expired` and a failed checks attempt whose release a lingering check holds are held now
  (`test_checks_round`); `tl step start` after such a hold begins at plan with a NULL label. The bench `Tracker`'s
  unclaim is fenced (False for another actor's, a closed or a missing task), as bd's.

**Deviations (decided here, open to veto).**

1. Section 9 names the refusal of a pending hold "as detail"; the move's `detail` is never logged, and the quiet key must
   change with the refusal, so the refusal is part of the logged word (`hold pending <missing> <refusal>`), which is also
   what H2's deviation 7 points the person at. The `HoldMove.detail` stays the move's (unlogged) detail.
2. 7.3 says a failed clear is "retried next round, quiet". A failed clear (`unavailable:tracker`, `unavailable:store`,
   `refused:changed`, `pending:held_again`) is a move `hold clearing <word>`, written once while unchanged (the quiet
   set), so a persistent tracker failure is visible once; a failed read of all holds (no task) writes no line.
3. Settle acts on `Next: hold` alone, not `cause(view)` again: `attempt_status` already turns a labelled view with a
   cause into `hold` (H2's deviation 1), so the round has one source of the rule.

**Tests** (`test_round_holds`, the rounds bench with real factory.db, admission, verify, release, publish and the hold
operation, a semantic tracker with the hold writes): a failed plan held once (labels, abandon, one comment with the
quoted explanation), then no tracker call and no line; a held task never stops another task or ingestion through one
slot, claimed work still before new work; the round's label stored on its admissions and advances, None by hand; a
hand-started failure reported, never held; a bd outage at the label step pending and written once, a changed refusal
(the comment) written again, the claim returned before the comment, one comment after the lease; a dirty slot keeping
the hold (`pending abandon held:slot_dirty`, one comment naming the slot, the claim kept) while another slot's task
starts, finished once the file is gone; `claim_lost` and `branch_moved` advances and a `branch_moved` publication held;
the person's answer taking the task again at plan (next seq, label stored, base the planned commit on `task/tl-1`) and
`hold cleared` once; a round under another label skipping it (`abandoned`) though the task carries that label; an
`absent` hold re-ingested; a re-hold owning `held` (no tracker call for the old row); a `superseded` hold after a person's
abandon and start by hand; a person's own abandon keeping the skip. Mutations of each round change (the re-ingestion
filter, the label guard, the stored label, the clear, the publish and advance holds, the pending word, the `hold` and
`on_hold` cases) each fail a test.

**Unverified.** No live bd, Git or agent run (the M4 smoke, S); the graceful-stop skip of the clear has no test of its
own; the composition wiring of `holding` is exercised by the gates' import and type checks only.

## 27. As built: K1 (tl-8bh9.14.10)

Keep-awake for the life of `tl step rounds` (section 13); nothing of G1/G2 or the smoke. Code lines by the policy
counter: `keep_awake` 63 (new), `composition` 153 (+7), `cli_composition` 240 (+5); `test_keep_awake` 125 (new),
`real/test_keep_awake_real` 22 (new). `.importlinter`: `taskloop.keep_awake` joins the source lists of
`cli-never-imports-the-attempt-entry` and `rounds-never-land`; `one-signal-owner` and the policy AST test are unchanged.

- **`keep_awake.py`** (no process API, no `signal`): `command(host, pid, backlog)` is section 13's table by
  `sys.platform` (`darwin`; any `linux*`), each tool resolved on `PATH` (`Host.which`, real `shutil.which`) and put in
  the argv as its absolute path; `awake(host, pid, backlog, log, clock, say)` is the context manager: spawn
  (`Host.spawn`), then `try:` `Helper.replay()` first, the `started` line, the block; `finally:` `Helper.stop()`.
  Without a helper: one log line `rounds keep_awake unavailable:<why>`, one stderr line `Keep-awake unavailable
  (<detail>); the rounds run anyway`, and the block runs. A log write failure is ignored (the rounds' own `Log: not
  written` covers it).
- **`composition.keep_awake_spawn`**: `open(os.devnull, "r+b")` for stdin, stdout and stderr, closed after the spawn;
  `stream_proc.popen_held(argv, ..., start_new_session=True)`; `Helper(pid, hold.replay, lambda: stop_tree(child))`.
  A failed `Popen` raises OSError after the shelf's hold already replayed (its `__exit__`). `keep_awake_host()` is
  `Host(sys.platform, shutil.which, keep_awake_spawn)`.
- **`cli_composition.open_rounds`**: after the inputs, the database guard and the rounds lock (a refused rounds starts
  nothing), `with awake(...), install(_say) as interrupts:`: spawn, replay, the SIGINT handler, the rounds; on the way
  out the handler is restored, then the helper stopped, then the lock released. `open_rounds` gained `host` (default
  this machine) and `install` (default `interrupts.installed`) so the order is tested without a process or a handler.
  `RoundsPorts.log` and `.pid` are the same values `awake` uses.
- **One-signal-owner.** The factory still imports `signal` only in `interrupts.py` and sends no signal: the transient
  `TermHold` swap is inside `stream_proc` (an external package, whose own `signal` import the contract does not
  trace, as for every `popen_registered` launch), and the helper's SIGTERM/SIGKILL is `stop_tree`'s. The CLAUDE.md and
  AGENTS.md note of section 13 is **not made** in K1 (the coordinator kept those files unedited); the exact proposed
  edit, the same in both files (line 47 today), replaces

  ```
    signal use is `interrupts.py`'s SIGINT handler while `tl step rounds` runs (sets a flag, signals no process), enforced
    by the import-linter contract `one-signal-owner` and the policy AST test.
  ```

  with

  ```
    signal use is `interrupts.py`'s SIGINT handler while `tl step rounds` runs (sets a flag, signals no process), enforced
    by the import-linter contract `one-signal-owner` and the policy AST test. The shelf's own process API may hold SIGINT
    and SIGTERM for the duration of one spawn (`stream_proc.TermHold`) and replays them; that is the shelf's, not a
    factory signal use.
  ```

**Deviations (decided here, open to veto).**

1. The unavailable reasons are three fixed words: `platform` (no table row), `missing` (a tool not on `PATH`; on Linux
   `tail` is checked too, since `systemd-inhibit` without it would exit at once), `start` (the spawn's OSError). The
   tool names and the error go to the stderr line only (log words are fixed).
2. The argv carries each tool's absolute path from `PATH` instead of its bare name, so the checked tool is the one run.
3. The CLAUDE.md/AGENTS.md note is proposed above, not edited (section 13 said "made with K1").

**Observed on this machine (OrbStack Linux guest, uid 501).** `systemd-inhibit` and `tail` are on `PATH` and logind lists
a `manager-early` session, but `systemd-inhibit --what=sleep:idle ... --mode=block` prints `Failed to inhibit: Access
denied` and exits at once: the helper is a zombie half a second after the spawn, `stop_tree` returns `()` in 8 ms and
reaps it. So rounds log `keep_awake started pid=<n>` and the effect is none (section 13's accepted limit: the factory
does not check). OrbStack also puts a `caffeinate` on `PATH` (`/opt/orbstack-guest/bin/caffeinate`, a link to
`macctl`, which forwards to the macOS host and takes `-i -w pid`); K1 does not use it on Linux (the table is by
`sys.platform`), and whether its `-w` would watch a guest pid was not tried.

**Tests.** `test_keep_awake` (a semantic `Host` whose spawn records argv, replay and stop, and a recorded `install` in
place of the real handler, over a real factory.db and rounds lock): the argv per platform (macOS, Linux, FreeBSD and
Windows unavailable) carrying the rounds pid; each missing tool; the order spawn, replay, install, rounds, restore, stop
on a normal end, on an exception and on Ctrl-C twice (a graceful press then `KeyboardInterrupt`); a Ctrl-C held during
the spawn (replay raising `KeyboardInterrupt`) stopping the helper with no handler installed and the lock released;
each unavailable reason logged once with one stderr line and the rounds run; a refused rounds starting nothing; only
`open_rounds` naming `awake` and only the two composition modules importing `keep_awake` (so `tl step next` and every
other command start none). `real/test_keep_awake_real` (Linux with both tools, skipped elsewhere): the real
`systemd-inhibit ... tail --pid=<pytest pid>` through `keep_awake_spawn`, alive or unreaped inside the block, gone after
it, one `started` line.

**Unverified.** macOS entirely (`caffeinate`, `pmset -g assertions`); a Linux host where the inhibitor is granted (no
`taskloop` row in `systemd-inhibit --list` was ever seen); a real Ctrl-C during the spawn (only the fake replay); a
third Ctrl-C during `stop_tree`'s grace (up to 5 s, then 2 s of proof) interrupts the stop, and the helper then ends by
itself within about a second (`-w`, `tail --pid`), not observed. Smoke step 6 (M4) is not run.

**Review repairs of ebaa8ae33 (2026-11-12).** Code lines by the policy counter after them: `hold` 175 (+23),
`hold_store` 120 (+9), `operations` 372 (+5), `attempt_status` 233 (+3), `step_guide` 198 (+3), `step_render` 133 (+1),
`cli_composition` 241 (+1); `test_hold` 416 (+53), `test_round_holds` 236 (+32), `test_checks_round` 357 (+20),
`test_step_cli` 604 (+10), `round_bench` 195 (+2), `test_policy` 190 (+1).

1. **An unfinished hold could abandon work restarted after it was recorded** (reproduced: checks fail, bd down at the
   label step, `tl step start` re-runs the checks, which pass, then the hold abandoned them). Both parts:
   (a) `operations.start` refuses `refused:held` while the task's current agent attempt has a hold row and its abandon is
   not recorded (a relaunch, repeat, advance or checks re-run would be abandoned by it); the guide says to let the round
   finish it (`tl step next`) or `tl step release --abandon` first. Once the abandon is recorded the hold can no longer
   touch a new attempt (its fences require A current), so a start is allowed again, also before the comment is written.
   (b) Before the label step and the abandon, `hold_task` fences the cause again on the task's status read now
   (`HoldPorts.status` = `attempt_status.current_view`, the view before any hold word): while an abandon of A is under
   way it finishes; else the current view must still be the stored cause (A, or A's latest checks attempt) and still a
   hold cause (`hold_status.cause`; `claim_lost`/`branch_moved`: the view still `advance` or `publish`). Otherwise the
   hold is **retired**: `held` removed first when its label step added it (`moved`/`absent`; a tracker failure is
   `pending retire unavailable:tracker`), then the row deleted (`HoldStore.retire`, fenced on `rev`, never a cleared
   row; policy `WRITERS` gains `DELETE FROM task_hold`), move `hold refused refused:retired`. Deleting, not a new
   label word, keeps one hold per agent attempt possible later (the primary key) and needs no schema change. The
   approval label is not added back: a claimed task advances without it (D3).
2. **A failed comment kept its own lease**, so later rounds alternated `refused:leased` and `unavailable:tracker`. A
   comment call answering `unavailable` (one capped try) now gives the lease back (`HoldStore.uncommenting`); the next
   round retries at once.
3. **`clear_holds` crossed backlogs**: `HoldStore.uncleared(backlog)` filters on A's backlog; the round passes its own.
4. **`tl step next` printed no guide for a hold**: a `hold pending ...` move prints `hold: <the hold guide>`.
5. **Tests**: the reproduced case over the checks rig (start refused `held`; a re-run raced in beside the hold passes and
   the hold retires, nothing abandoned, no label written); the relaunch variant refused `held` while pending and allowed
   once finished; unit tests of the fence (a still-standing cause, `stuck:hung`, an abandon under way, a round-passed
   cause) and of the retire (with and without a label step, a tracker failure); the lease given back and retried at once
   within the old lease window; `clear_holds` of another backlog lists nothing; the `tl step next` guide; a hand-started
   publication refused `branch_moved` logged, never held; a graceful stop skipping the clear; one round over an empty
   factory.db through the real `open_next` wiring. Each repair, reverted alone, fails a test.

**Unverified after the repairs.** As before: no live bd, Git or agent run. The retire leaves the approval label removed
when the label step had run (by design); a race between the fresh status read and the label step within one call
remains (milliseconds; the start refusal (a) closes the person's path once the row exists).
