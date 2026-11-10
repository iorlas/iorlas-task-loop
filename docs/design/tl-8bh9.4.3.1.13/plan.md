# Scheduling: the factory takes ready tasks into free slots (`tl plan next`)

Task: tl-8bh9.4.3.1.13 (proposed id; not in the tracker). Design proposal, 2026-11-10, against HEAD a2c7a47ed. Nothing
here is built or run. Commands run: source reads, the policy line counter over HEAD, `bd ready --help` and one read-only
`bd ready --json -n 2` on this repository's tracker (to see the row shape: `priority`, `issue_type`, `labels`, `parent`
are present), and a read of the shelf `beads-client` checkout (`ready` exists on `Bd`, no read fake for it).
Revision 2 (same day) applies the owner's answers (section 15): one-shot rounds now, the trigger an open design for a
later slice (section 5, read-only `bd hooks --help` and `bd events --help` checked); `--label auto`; an attempt whose
entry exited before the agent ran is relaunched, every move written to a round log (sections 4, 6, 7a); the owner
releases beads-client 0.2.0 from [the shelf request](shelf-request.md).

Read: CLAUDE.md, glossary, [.8.7](../tl-8bh9.8.7/plan.md), slices [.2](../tl-8bh9.4.3.1.2/plan.md) to
[.12](../tl-8bh9.4.3.1.12/plan.md), the [live smoke](../tl-8bh9.4.3.1.4/live-smoke.md); the scheduling record:
[execution terms](../execution-terms.md) (owner scheduling decision, 2026-11-08), [selection review](../tl-8bh9.3/selection-review.md),
[hierarchical priority](../tl-8bh9.3/hierarchical-priority.md) (owner-accepted ordering contract), [lifecycle](../tl-8bh9.2/lifecycle.md),
[configuration review](../tl-8bh9.1/configuration-review.md), [handoff](../tl-8bh9.4.3.1.1/handoff.md), tl-8bh9.3.5
(LIFECYCLE-REUSE, `bd show`); source `plan_ops, plan_admit, plan_launch, plan_repeat, plan_release, plan_publish,
plan_reads, plan_data, attempt_entry, claim_lease, tracker, task, composition, cli_composition, cli_plan, machine_config`,
`.importlinter`; installed beads_client 0.1.0 (`client.py`, `records.py`, `reads.py`, `testing.py`).

## 1. Words, and what earlier designs said

| Word | Meaning here |
|---|---|
| **ready** | The task tracker's fact: open, no active blocker, not deferred, not in progress, not hooked (`bd ready`'s documented semantics, bd 1.3.1). The factory never recomputes it. |
| **approved** | The task carries the tracker label `auto`, which permits autonomous execution (owner, Q2). |
| **eligible** | Ready, approved, not assigned to another actor, and with no attempt of this backlog in factory.db (section 3). |
| **round** | One execution of `tl plan next`: settle existing attempts, admit eligible tasks into free slots, publish. Ordinary English, not a new entity. Not called a "pass": the glossary reserves pass for a stored successful check result. |
| **step** | The plan step (glossary). Implement, check, review and land are not scheduled here. |

`stage` survives only in literal code names (`plan_stage`); new prose says step. `loop` is avoided as a factory noun: the
old task-loop "loop" and the baseline `lane` meant a scheduler process, which this slice does not build (section 5).

What the record already settled (not reopened):

| Source | Settled |
|---|---|
| Execution terms, owner 2026-11-08 | "Take highest-priority automation-approved tasks whose dependencies are satisfied and which are not held/already claimed, up to available slots. Independent children of an epic may run concurrently." No areas, no manual queue, no epic order. |
| Hierarchical priority (owner-accepted) | Own priority, then nearest parent outward to the root, P2 for a missing priority or level (padded to the deepest candidate), then natural task ID. "Report and skip a candidate with an invalid/unreadable chain"; no IO inside the comparator; each unique parent fetched once per snapshot. |
| Selection review | "Eligibility must be revalidated at acquisition." "Inability to query the task service must never mean take anything." Approval must not broaden because a list emptied. "No separate scheduling service needed." |
| Lifecycle | "Multiple schedulers using one reservation protocol, not a new daemon." Intact DB: "reconcile and continue the same unfinished step/session". |
| tl-8bh9.3.5 | "Preserve explicit single-step execution and continuous scheduling as drivers of same step operations." |
| .4.3.1 | The attempt "has no task-selection loop"; persistence retry "cannot become an independent scheduler". |
| .6 roadmap | "scheduling, pause and the dashboard remain next". |
| .11 Q4, owner | No stuck detection, no supervisor; a person stops a hung entry by verified pid. Future idea only: the dashboard shows the time since the last command. |
| Handoff | "Skills are lightweight explicit ... helpers, no second scheduler/state owner." |

The older durable-factory research ("pick over `bd ready` ∪ wakes", a durability module with schedule/due/lease/reap)
is superseded by these decisions and is not carried.

## 2. What changes

One new application operation, `plan_next.advance(ports, request) -> Round | Failed`, and its verb `tl plan next`. It
composes the existing operations; it adds no state, no lock, no Git write, no tracker write and no process of its own.
Its only new output besides its result is one append-only log line per move (section 7a), never read back:

1. **Settle** every existing attempt of the backlog by its `Next` word (section 4): verify, repeat, or relaunch an
   admitted attempt whose entry is not running (never launched, or exited before the agent ran), through
   `plan_ops.verify_task` and `plan_ops.start`. Everything else is reported.
2. **Admit** eligible tasks in priority order, one per free slot, through `plan_ops.start` (admit then launch), until the
   slots run out or the candidates do.
3. **Publish** the verified, released, unpublished plans read in step 1, through `plan_ops.publish_task`.

`tl plan start TASK` stays the person's single-task driver over the same operations (tl-8bh9.3.5). The entry, release,
publication, claim and heartbeat behave exactly as built in .9 to .12.

## 3. Ready, approval and eligibility: who owns which fact

| Fact | Owner | How the round gets it |
|---|---|---|
| ready (status, blockers, deferral) | task tracker | one `bd ready -n 0 --label <approval>` per round (`Bd.ready(label)`), the tracker's own blocker-aware query |
| approval | task tracker (label) | the same call's label filter; an empty label is refused, never "all ready tasks" |
| priority, parent | task tracker | the ready rows; a parent not among them by `Bd.show`, once per unique id per round |
| claimed by someone | task tracker | an in-progress task is not ready; an open task with another assignee is skipped `assigned` |
| has an attempt here | factory.db | `PlanReads.attempts()` for the backlog: any attempt, abandoned or not, makes the task ineligible |
| a free slot | factory.db + Git | admission's own observation, unchanged (`no_free_slot`) |

**Eligibility filters, in order, in our code (pure, `selection.py`):** an attempt row for (`beads`, backlog, id) exists ->
`skip attempted`, or `skip abandoned` when its current attempt's release is abandoned; `assignee` set and not `taskloop`
-> `skip assigned` (`taskloop` itself is allowed: bd's claim is idempotent for its holder, so an open task still showing
`taskloop` as assignee is not refused for that alone). A leaked compensation claim is different: the task stays in
progress, so it is not ready and no round sees it again; the round that leaked it records `report claim_leaked` (the
move, its human guide, its JSON and its round-log line) and a person runs `bd unclaim <task> --if-assignee taskloop`
(as-built repair). A missing or cyclic ancestor chain -> `skip ancestry`; an ancestor that could not be read ->
`skip unavailable:ancestry` (transient, exit 3). No issue-type rule:
an epic is planned only if a person approved it with the label, as the review asks ("distinguish true containers from
ordinary executable tasks"; the person does, by labelling).

**Selection order:** the accepted contract exactly: key = (own priority or 2, ancestor priorities nearest-first padded
with 2 to the deepest candidate's depth, natural task id with digit runs compared as numbers). Ancestors come from
`parent`; blockers and related links are not ancestry. The comparator does no IO: the chains are read first, memoized
per round. Within one repository no repository qualifier is needed (a round has one checkout).

**Revalidation at acquisition** is admission's, unchanged: the task is read again (`bd show`), the slot and branch rule
are re-checked, and the claim (`bd update --claim`) is the atomic acquisition: another actor's claim answers
`claimed_elsewhere` and nothing is written. **Residual:** a blocker or label change between the round's `bd ready` and
the claim is not re-read (seconds); the next round sees it, and nothing already admitted is preempted (the contract's
"no automatic preemption"). `bd ready --claim` (select and claim in one tracker call) is not used: it picks by bd's own
order, not the contract's, and would claim before the slot and branch checks.

**Claim races.** Another actor first: `claimed_elsewhere`, skip, next candidate. A person's own `tl plan start` or a
second round on this machine: both are actor `taskloop`, so bd's claim succeeds for both; admission's write fence decides
(`task_attempted`, the loser launches the winner's attempt as existing, or answers `already_running`); the loser's
compensation unclaims only when no attempt exists (`_compensate`, unchanged). **Two factories (two factory.db files,
another machine) scheduling one backlog are unsupported**: they share the actor `taskloop`, so the claim cannot tell
them apart (the recorded direction is one local authority per workspace pool; lifecycle, "no distributed coordinator").

## 4. What a round does with each existing attempt

Input: `plan_ops.attempts_status(reads)` (one row per task, its current attempt; leftovers probed), filtered to the
backlog. The `Next` word is the existing one; the round adds no new state word.

| `Next` (and condition) | Round does | Move |
|---|---|---|
| `start`, current attempt abandoned (`release.abandoned`; checked first: an abandoned attempt may also be `admitted` with no entry) | nothing: never re-admitted by a round | no move here; `skip abandoned` if the task is also a ready candidate (section 3) |
| `wait` (entry running) | nothing | `report running` |
| `start`, phase `admitted`, entry none, gone or a different process (launch failed, never ran, or the entry exited before the agent ran: refused, crashed, reboot, network loss) | `plan_ops.start` (relaunch through the launcher, which replaces the stored entry after observing it not running) | `relaunch <word>` (`relaunched`, or the launcher's refusal) |
| `verify` | `plan_ops.verify_task` (which releases and publishes, as built) | `verify verified release=<w> branch=<w>` or `verify <kind>:<reason>` |
| `repeat` | `plan_ops.start` (the repeat path, budget `ATTEMPTS`) | `repeat <word>` |
| `repeats_exhausted` | nothing | `report repeats_exhausted` |
| `release` (slot held after a final result, or an abandon still `unclaiming`) | nothing: the person tidies and runs `tl plan release` | `report release` |
| `publish` | `plan_ops.publish_task`, in step 3 | `publish <word>` |
| `done`, succeeded | nothing | no move |
| `done`, not succeeded (`rejected:*`, `run:*`, `answer:*`, ...) | nothing; the claim stays held (settled release), so the task is not ready either | `report failed:<reason>` |
| `stuck:*`, `unknown` | nothing | `report <word>` |

**Never silently retried.** A failed result, an exhausted repeat, an abandon and every stuck word are reported every round
and acted on only by a person (`tl plan start`, `tl plan release [--abandon]`). An abandoned task returns to the tracker
open and unassigned, so it is ready again; the round skips it because factory.db holds its abandoned attempt. A person
who wants it planned again runs `tl plan start` for it. A deliberate whole-DB discard makes every task fresh again: that is
the "normal reevaluation" the discard permits (the discard steps already unclaim the factory's tasks).

**Relaunch, and what bounds it (owner, Q3).** An `admitted` attempt has not dispatched: no agent ran, so a relaunch
repeats nothing the step did. The entry's own reasons for exiting before the agent are fixed words in its `entry.log`
(`refused slot_busy`, `refused lock`, `refused claim_lost`, `unavailable store`, `failed <Type>`); the round never reads
them, it relaunches on the factory.db facts alone (phase `admitted`, entry not running, deadline not passed). What
happens each round when the cause persists:

| Cause | Each round | Bounded by (existing fence) |
|---|---|---|
| reboot, network loss, a crash before dispatch | one relaunch, which then runs normally | the first successful relaunch |
| `slot_busy` (another holder of the slot's lock: a concurrency error or a reduced slot count, owner) | one entry process start, one identity read, one non-blocking lock try, one `entry.log` line; nothing else read or written | the deadline, below |
| `claim_lost` (the claim is truly gone: reverted by `bd reclaim`, taken by another actor, or the task closed) | the above plus one `bd heartbeat` call, then `refused claim_lost`; no claim is retaken and nothing is unclaimed | the deadline, below |

**The deadline is the bound.** The attempt's deadline was fixed at admission (`--minutes`). The launcher's registration
fence refuses an expired admitted attempt (`registration_refused`), and its status becomes `stuck:expired_admitted`, which
a round only reports. So a persistent cause costs at most one relaunch per round until the deadline: with rounds by hand,
a few; with `tl plan rounds` ([.4.3.1.14](../tl-8bh9.4.3.1.14/plan.md)) a regular round every 60 s by default, at most
`minutes` relaunches per deadline (the slot-freed wake adds at most one round per step that ends). Noise: one `entry.log` line per relaunch in the
attempt's own log and one round-log line (section 7a), both traceable to the attempt. No detector is added. A truly lost
claim then needs a person: `tl plan release --abandon` (the abandon's fenced unclaim answers `not_held`) and, to plan the
task again, `tl plan start`. Consequence of the same fence: **an outage longer than the deadline is not continued
automatically**; the attempt is `stuck:expired_admitted` (new owner question 5).

**Publication retry.** A verified plan not on `origin` is pushed again every round (non-force, idempotent; .12). Only
success is stored, so after `refused:diverged`, `remote_moved` or `remote_ahead` every round repeats the push and the
same refusal until a person reconciles; the move says so each time. Accepted: the cost is one push per round per such
task, and no failure state is added to factory.db for it. **A held release waits for a person.** A verify move's
`release=unavailable:slot_busy` (or any held release) leaves the attempt `Next: release`, which rounds only report: its
publication waits until a person runs `tl plan release`, after which a round publishes it. Report-only by design; no
code retries the release.

## 5. How a round is triggered

**This slice: one-shot.** `tl plan next` runs one round in the caller's process and exits. Entries are already detached
processes (`plan_launch`), so the round returns as soon as its launches are registered; the steps keep running. A freed
slot is filled by the next round. Pause is: stop running rounds (or remove the approval label); admitted work drains, as
the owner's Pause/Continue decision says. Nothing in factory.db records rounds.

One-shot is also the debugging tool (owner, Q1): one command, one round, every move printed and logged.

**The trigger is decided in [.4.3.1.14](../tl-8bh9.4.3.1.14/plan.md) (`tl plan rounds`: a foreground process started by
hand, a regular round every 60 s, a round seconds after a reservation row is removed, the tracker read only when a slot
is free; no tracker events).** The exploration below is kept as it was written.

**Open design: the trigger (a later slice; nothing here is built).** The owner's ideal is event-driven: a tracker change
notifies the scheduler, no polling; he is between that and a periodic resident loop, and a new approved task must not wait
half an hour. The invariant this slice guarantees for any trigger: **a round is stateless and idempotent, so any trigger
may call `advance` at any time, as often as it likes, concurrently included** (section 6). Checked read-only on bd 1.3.1:

| Option | What bd offers / what it costs | Gaps |
|---|---|---|
| bd hooks | `bd hooks` installs **Git** hooks only (pre-commit, post-merge, pre-push, post-checkout, prepare-commit-msg); no hook on task create/update | not a tracker notification; and the factory runs Git with hooks off |
| bd events journal | `bd events tail --since <seq> --follow --json` streams every committed mutation (create, update, close, claim, label, dependency, comment) as ordered JSON lines; off by default (`bd config set events-journal true`, a tracker config write) | per replica and per branch: changes arriving by `bd dolt pull` or a merge are **not** journaled (re-baseline after a sync); a consumer keeps its own `seq` watermark; retention floors (7 days / 100k rows) can prune past a stalled consumer; still needs one resident follower process |
| foreground `tl plan next --every N` | a loop in the person's terminal; the simplest resident form | a new task waits up to N; a long-running process (version fixed until restart, a stop, one per machine) |
| cheap poll only when a slot is free | before any bd call, a local read of factory.db and the slots; call `bd ready` only when a slot is free | still a loop; the free-slot read is Git work per slot |

Not tracker events, and needed by any choice: **a slot frees when an entry ends** (a factory event, in the entry's
process), and a round can start new work only then. A plausible later shape, recorded only: one resident process that
follows the journal (approval, unblocking, priority changes), runs a round on each relevant record and when an entry it
launched ends, plus a slow safety round for synced changes the journal misses. Its watermark is a log consumer's own
cursor, never control state derived from tracker data in factory.db. The trigger slice decides its process form, its
single-instance rule, where its output goes, and whether enabling the journal is acceptable on the owner's trackers.
**Rejected alternative:** the
entry starting a round when its step ends (self-perpetuating, no daemon). It would hide a scheduler inside the attempt
entry, widen its import closure (`.importlinter` keeps `plan_ops` out of it) and require the round's choices to be stored
per attempt. **Skills** may run `tl plan next` as an explicit helper; they own no selection policy or state, and factory
correctness never depends on one.

## 6. Restart, crash and concurrency

A round keeps no state: every decision is read again from factory.db, process observations, Git and the tracker. Every
action it takes is an existing fenced, idempotent operation. So a rerun after any crash is the recovery:

| Dies or fails | State | Next round |
|---|---|---|
| before an admission's claim | nothing | admits again |
| after admission, before or during the launch | `admitted`, no entry registered, slot and claim held | relaunches (section 4) |
| after the launch registered the entry | the entry runs on its own | `report running` |
| during a verify, release or publish | that operation's own crash table (.8, .11, .12) | runs it again |
| machine restart or network loss, attempt `admitted` (entry registered, gone before the agent) | entry gone | relaunches while the deadline holds; after it, `report stuck:expired_admitted` (question 5) |
| machine restart, attempt `dispatching`/`registered` | agent gone | `report stuck:entry_lost`: continuing it is session resume, out of scope |
| machine restart, attempt `captured` | step ended | verify or repeat |
| machine restart, verified and unpublished | | publish |

**Concurrency.** No round lock (decided). Two rounds, or a round and a person's command, are made safe by the existing
fences: admission's write transaction and claim compensation, the launcher's registration fence, the slot custody lock
taken by verify/repeat/release (a loser answers `unavailable:slot_busy`, reported), and publication's
`AlreadyPublished`. The only waste is a claim taken and compensated when two rounds race for the last slot: at most one
`bd` claim/unclaim pair per concurrent round. A future resident loop decides its own single-instance rule.

**Claim lease and heartbeat (.9), unchanged.** The entry renews during a step; nothing renews between steps, and the round
never renews or re-claims. A claim reverted by someone's `bd reclaim` after a step makes the task open again: the round
skips it `attempted` (factory.db has its attempt); the move names that as "open in the tracker while factory.db holds
its attempt: the claim was returned or lapsed". An admitted attempt whose claim was lost before its entry started is
refused by the entry (`refused claim_lost`) and relaunched by each round until its deadline (section 4: one heartbeat call
and one log line per round, no re-claim, no new detector). Publication does not check the claim (.12).

## 7. The operation and its surfaces

`src/taskloop/plan_next.py`:

```python
@dataclass(frozen=True) class NextRequest: backlog: str; tracker_root: str; checkout: Path; label: str; model: str; effort: str; minutes: int
@dataclass(frozen=True) class Advancing:      # every port is an existing one, plus the tracker's ready read and the round log
    reads: Reads; starting: Starting; verifier: Verify; releaser: Release; publisher: Publish; ready: ReadyRows
    log: Callable[[str], None]               # one fixed-word line per move (section 7a); OSError is caught by the caller's writer
def advance(ports: Advancing, request: NextRequest) -> Round | Failed
```

In `plan_ops.py` (the result union lives there; `plan_next` imports `plan_ops`, never the reverse):

```python
type Action = Literal["start", "relaunch", "repeat", "verify", "publish", "report", "skip"]
@dataclass(frozen=True) class Move:  task_id: str; action: Action; word: str; attempt_id: str = ""; detail: str = ""
@dataclass(frozen=True) class Round: backlog: str; moves: tuple[Move, ...]; stopped: str = ""; logged: bool = True
# stopped: the word that ended admission early; logged: False when a round-log line could not be written
```

`word` reuses the existing words: `Started.status` (`started`, `relaunched`, `repeated`, `already_running`, ...);
`Failed` as `<kind>:<reason>`; `Checked` as `verified`/`reused` plus `release=<w>` and `branch=<w>`;
`plan_publish.word`; the `Next` word for `report`; the section 3 reason for `skip`. Moves are ordered as performed.

**Admission loop.** Per candidate in order, `plan_ops.start(starting, StartRequest(...))`:

| Result | Then |
|---|---|
| `Started` | `start started` (or the race's `already_running`), next candidate |
| `Failed(admitted=True)`, refused (launch refused after admission) | `start refused:<reason>`; the next round relaunches it (no entry registered); next candidate |
| `Failed(admitted=True)`, `unavailable`/`uncertain` (as-built repair) | `start <kind>:<reason>`, then stop: `stopped = "<kind>:<reason>"` (no more attempts that never start) |
| refused `claimed_elsewhere`, `branch_name`, `branch_held`, `branch_diverged`, `release`, or a refusal of an attempt another start made meanwhile (`registration_conflict`, `registration_refused`, ...) | `start refused:<reason>`, next candidate |
| refused `no_free_slot` | stop admitting: `stopped = "no_free_slot"` |
| refused `checkout`, `choices`, `deadline`, `expired`, `constraint`, `schema`, `database`, `input`, `task` | `start refused:<reason>`, then stop: the round's own inputs are wrong; `stopped = "refused:<reason>"` |
| any `unavailable`/`uncertain` | stop: `stopped = "<kind>:<reason>"` |
| any result with `claim_leaked` | also `report claim_leaked`, whatever follows |

The ready read failing (`BdError`) stops before any admission (`stopped = "unavailable:tracker"`, or `refused:tracker`
for `malformed`); settling already ran and publishing still runs. No candidates: `stopped` stays empty.

**Exit:** a whole-round refusal (database, schema, empty label, unusable tracker root) is `Failed`, exit 1 or 3 as
today. A `Round` exits 3 when `stopped` or any move's word is `unavailable:*`, `uncertain:*` or `unknown` (rerunning is
safe), else 0. Per-task refusals do not change the exit (as a held release does not change verify's).

**Surfaces, one operation:**

- **`tl plan next --backlog B --tracker-root DIR --checkout DIR --label L --model M --effort E --minutes N [--db]
  [--artifacts] [--json]`**. Choices are flags, as for `tl plan start` (no new config or profile key). Help: "Run one
  scheduling round for the plan step: settle existing attempts, start approved ready tasks in free slots, publish
  verified plans; plan step only: publishes task/<id>; no merge or land". Human output: one line per move
  (`tl-3  start    started`, `tl-2  report   stuck:hung`), then `Stopped: <word>` when set, and the GUIDE line of each
  distinct reported word. JSON (`plan_data.as_data`): `{"status": "round", "backlog", "moves": [{"task", "action",
  "word", "attempt_id", "detail"}], "stopped": null|word}`; refusals keep the `{"error": ...}` shape.
- **Dashboard (later, out of scope):** calls the same `advance` and renders `as_data`; no dashboard-specific path.
- **`tl plan start/show/list/verify/release/publish`:** unchanged.

## 7a. The round log

Owner, Q3: autonomous continuation must leave a trace. Each move is also one appended line in **`<artifacts>/rounds.log`**
(the machine config's `artifacts` root, beside `attempts/`), written through the existing owner of that tree,
`PlanFiles`: a new `PlanFiles.round_log()` returns the path, made like `entry_log` (the directory created, opened
`O_WRONLY | O_APPEND | O_CREAT | O_CLOEXEC`, mode 0600, as the launcher opens `entry.log`). `cli_composition` binds it to
the `log` port; tests pass a list's `append`.

- **Line:** `<UTC time ISO-8601> <backlog> <task> <action> <word>[ <attempt id>]`, then one closing line per round
  `<time> <backlog> round moves=<n>[ stopped=<word>]`. Fixed words only: the same `WORD` rule as the entry's line; never
  `detail`, paths, environment, Git or bd output.
- **Never read for control.** No operation, `tl plan show` or the round itself reads it; the relaunch decision is
  factory.db's (section 4). It is evidence for a person tracing why an attempt was relaunched: the round-log line names
  the attempt, and that attempt's own `entry.log` holds each relaunched entry's refusal or result line.
- **Failure:** an `OSError` on write never fails or changes the round; `Round.logged` is False and the human output says
  `Log: not written (<artifacts>/rounds.log)`; exit unchanged.
- **Size and retention:** about 100 bytes per move, unbounded, never rotated or deleted by the factory (no age-based
  deletion of evidence). A person may move it aside; the next round creates it again.
- **Not state:** factory.db stays the only local execution state; the log is a file behind its owner, like `entry.log`.
- **Repeated rounds** ([.4.3.1.14](../tl-8bh9.4.3.1.14/plan.md) section 9): `tl plan rounds` passes the previous round's
  moves and stopped word as `quiet`; a move identical to one in the previous round (task, action, word, attempt) is not
  written again, and the closing line only when a move line was written or the stopped word changed, so an idle factory
  writes nothing. Its own lines: `rounds started|wait|stopped ...`. `tl plan next` writes every move as before.

## 8. Tracker read port

`tracker.py` gains the ready read beside `inspect_task` (the one owner of tracker-record mapping):

```python
class ReadyRows(TaskReadClient, ReadyReadClient, Protocol): ...   # both beads-client 0.2.0 protocols; `Bd` and the fake satisfy it
@dataclass(frozen=True) class TaskRow: task_id: str; priority: int | None; parent: str; assignee: str
def ready_rows(client: ReadyRows, label: str) -> tuple[TaskRow, ...]        # BdError -> TaskInspectionError (as inspect_task)
def ancestry(client: ReadyRows, rows: Sequence[TaskRow]) -> Callable[[str], TaskRow | None]   # memoized show; raises on read failure
```

Composition builds `Bd(ACTOR, cwd=<resolved root>)` with the same root rule as `inspect_tracker_task` (one helper,
`_tracker_root`). No write verb is reachable through `ReadyRows`.

**Prerequisite: beads-client 0.2.0, released by the owner** (owner, Q4). CLAUDE.md requires shared task fakes from
their owning library; 0.1.0's `FakeTaskReadClient` has `show` only. The exact change, its contract test, the version and
tag steps and our pin change are in [the shelf request](shelf-request.md): a `ReadyReadClient` protocol, a `ready=`
seed (and `ready_fault=`) on `FakeTaskReadClient` whose `ready(label)` returns the seeded ready records carrying the
label in seeded order (readiness is seeded, never computed: it is the tracker's fact), and `ready_read_contract` run
against both the fake and `Bd`. This slice's code starts after the pin moves to 0.2.0.

## 9. factory.db

**No change; schema stays v8.** Everything a round needs is already stored (attempts, releases, publications,
reservations) or observed. No round table, no last-round time, no candidate cache, no failure counter, no backoff: a
rerun recomputes everything. `tests/rules/test_policy.WRITERS` and `GIT_WRITES` gain nothing.

## 10. Tests

Pytest functions and parametrized tables; no unittest, no subprocess. Factory tests use the in-memory `factory` fixture,
`FakeRepo`/`FakeWorktree`, `FakeSlotFiles`, a fake clock, beads-client 0.2.0's `FakeTaskReadClient` with `ready=`, and
recording stubs for the `Starting`/`Verify`/`Release`/`Publish` ports where the operation under test is the round.

- **`tests/plan/test_selection.py`** (new, ~220 lines, pure): every row of the hierarchical-priority scenario table as
  one parametrized case; P2 for a missing own priority and for missing levels (padding to the deepest chain); the
  non-transitive trap from the contract (A parent P0 id 3, C parent P4 id 1, standalone B id 2) gives one total order;
  natural ids (`t-2` before `t-10`); a cycle and an unreadable or missing parent skip only that candidate (`ancestry`);
  `attempted`, `abandoned`, `assigned` (another actor) skipped, `taskloop` kept; the comparator makes no lookup call
  (a counting lookup: one call per unique missing parent).
- **`tests/plan/test_next.py`** (new, ~420 lines):
  - the section 4 table, one seeded attempt per row: the right operation called once (or none), the move word;
    an `admitted` attempt is relaunched with no entry, with a registered entry observed `gone` and `different_process`,
    and is reported `stuck:expired_admitted` (no launch) once the fake clock passes its deadline: two rounds before, one
    relaunch each; one round after, none;
  - the round log: one line per move plus the closing line, fixed words only (no `detail` text even when the move has
    one); a `log` port raising `OSError` leaves the moves and exit unchanged and `logged=False`; the round never reads it;
  - admission order follows selection; one free slot and three candidates: one `start started`, then
    `stopped=no_free_slot` with the other candidates never claimed (recording claim);
  - `claimed_elsewhere` on the first candidate: the second admitted; `branch_diverged` skipped, next admitted;
  - an abandoned task in the ready rows is skipped, never admitted; a failed collected attempt reported every round;
  - ready read raises `BdError("timeout")`: settling and publishing still ran, `stopped=unavailable:tracker`, exit 3;
  - empty label refused before any read; a second round right after the first makes no new admission (idempotent);
  - the publish step: a `publish` row pushed once (real `PlanPublish` over `FakeRemote`), `already_published` next round;
  - real `PlanAdmission`/`Launcher` stubs only at the process boundary (as `test_ops.py` does), so `start`'s own paths
    are not re-tested here.
- **`tests/cli/test_task.py`**: `ready_rows` mapping (priority `None`, parent, assignee kept; a `BdError` kind mapped as
  `inspect_task` maps it), `ancestry` memoizes (`reads` shows one `show` per parent) (~+60 lines, 86 -> ~150).
- **`tests/cli/test_plan_cli.py`**: `plan next` human lines, exact JSON keys, exit codes (0, 3), required flags, help
  text (412 -> ~470 lines).
- **`test_ops.py`**: `exit_code(Round)` rows only (~+15; 653 -> ~670).
- **`tests/plan/test_attempt.py`** or the existing `PlanFiles` tests: `round_log` creates the directory and appends
  (two writes, two lines; mode 0600) (~+15; 774 -> ~790, else a new `test_files.py`).
- **No new real-layer test**: the round adds no Git, process or tracker write of its own; each operation it calls has
  its real-layer test already. The live run is Run G (section 11).
- **Rules:** `.importlinter`: `taskloop.plan_next` and `taskloop.selection` join the `cli-never-imports-the-attempt-entry`
  sources; `taskloop.plan_next` joins the `entry-never-imports-the-command-surface` forbidden list.

## 11. Smoke runbook additions (owner-run; scratch tracker and `remote.git` only)

In [live-smoke.md](../tl-8bh9.4.3.1.4/live-smoke.md), new **Run G (section 6f)**, with `slot_count = 1` as configured.
Move the previous run aside as Run F does (new timestamped directory, `$SMOKE/markers` recreated), then:

```bash
cd "$TRACKER"
G_PARENT=$(bd create "Smoke urgent group" -t epic -p 0 --silent)             # not approved: never planned itself
G_TOP=$(bd create "Smoke P1" -p 1 -l auto --silent)
G_CHILD=$(bd create "Smoke P2 under P0" -p 2 -l auto --parent "$G_PARENT" --silent)
G_LOW=$(bd create "Smoke P2 alone" -p 2 -l auto --silent)
G_OFF=$(bd create "Smoke P0 unapproved" -p 0 --silent)                       # no label: never taken
G_WAIT=$(bd create "Smoke P0 blocked" -p 0 -l auto --deps "blocked-by:$G_LOW" --silent)
printf 'G_PARENT=%s\nG_TOP=%s\nG_CHILD=%s\nG_LOW=%s\nG_OFF=%s\nG_WAIT=%s\n' "$G_PARENT" "$G_TOP" "$G_CHILD" "$G_LOW" \
  "$G_OFF" "$G_WAIT" >> "$SMOKE/env.sh"
for t in "$G_TOP" "$G_CHILD" "$G_LOW" "$G_OFF" "$G_WAIT"; do bd update "$t" -d "Write docs/design/$t/plan.md with one short \
paragraph. Answer planned and list the plan in paths." --acceptance "The plan is committed on task/$t and published to origin."; done
T slot adopt "$REPO"
NEXT=(plan next --backlog "$BACKLOG" --tracker-root "$TRACKER" --checkout "$REPO" --label auto --model "$MODEL" --effort "$EFFORT" --minutes 30)
T "${NEXT[@]}" --json        # G1: start $G_TOP started; stopped no_free_slot; nothing else claimed (bd show each)
T "${NEXT[@]}"               # G2, at once: report $G_TOP running; stopped no_free_slot; no second entry (ps)
T plan show "$G_TOP" --backlog "$BACKLOG"   # repeat until Next: done (released, published)
T "${NEXT[@]}"               # G3: start $G_CHILD (P2 under a P0 parent beats P2 alone)
T plan show "$G_CHILD" --backlog "$BACKLOG" # until Next: done
T "${NEXT[@]}"               # G4: start $G_LOW ($G_WAIT stays blocked while $G_LOW is open)
T plan show "$G_LOW" --backlog "$BACKLOG"   # until Next: done
T plan release "$G_LOW" --backlog "$BACKLOG" --abandon   # G5: abandon a finished attempt; $G_LOW is open again
bd ready -l auto             # lists $G_LOW (open, unassigned) and $G_WAIT still blocked
T "${NEXT[@]}"               # G5: skip $G_LOW abandoned; nothing started; $G_OFF and $G_WAIT never appear
# G6, an entry that exits before the agent (section 4's trick: no Codex login for that one round's entry)
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
| G3 hierarchy | `$G_CHILD` before `$G_LOW` | `$G_LOW` first (ancestry ignored) |
| G5 abandon | `skip abandoned`; no new attempt for `$G_LOW` | the round admitted it again |
| approval, blockers | `$G_OFF`, `$G_PARENT` and `$G_WAIT` never in any move | an unapproved or blocked task taken |
| publication | each finished task published to `remote.git` (Run F rules) | a forced or missing push |
| G6 relaunch | first round: `start started`, entry.log `unavailable credentials:auth`; second: `relaunch relaunched` on the same attempt id, then `Next: done`; `rounds.log` holds both rounds | no relaunch; a second attempt row; anything but fixed words in `rounds.log` |

G6 stands in for a reboot or network loss mid-start: the entry is gone while the attempt is `admitted`, which is what the
round decides on. Not covered live: a real reboot, `refused slot_busy` and `refused claim_lost` (tests cover the rule).

Section 9 gains: never run `tl plan next` against the real tracker or a backlog without the scratch label. Section 7
gains: every `T plan next --json` output, `rounds.log`, and `bd show` of each `G_*` task.

## 12. Modules and caps

SLOC by the policy counter today -> estimate; caps 400 file, 80 function, 800 test file.

| Module | Change | SLOC |
|---|---|---|
| `selection.py` (new) | eligibility filters, ancestry chains (cycle check), padded key, natural id, `order(...) -> (ordered, skipped)` | ~100 |
| `plan_next.py` (new) | `NextRequest`, `Advancing`, `advance`: `_settle`, `_act(status)`, `_admit`, `_started`, `_publish`, `_logged` (line format, OSError), exit facts | ~205 |
| `plan_files.py` | `round_log()` (directory, append open, as `entry_log`) | 103 lines -> ~+12 |
| `tracker.py` | `ReadyRows`, `TaskRow`, `ready_rows`, `ancestry` | 16 -> ~55 |
| `plan_ops.py` | `Action`, `Move`, `Round`, `Result` union, `exit_code` case | 338 -> ~365 |
| `plan_data.py` | the round shape | 81 -> ~100 |
| `cli_plan.py` | `plan next` verb, rendering, `Log:` line, GUIDE `failed` row | 296 -> ~345 |
| `cli_composition.py` | `open_plan_next` (start ports, verify ports, reads, ready client, round-log writer in one context) | 122 -> ~160 |
| `composition.py` | `tracker_reads(root) -> Bd` sharing the root rule with `inspect_tracker_task` | 246 -> ~255 |
| `.importlinter` | the two contract rows (section 10) | |

`advance` stays a short sequence of the helpers; each helper at most four returns (`PLR0911`), C90 12. No subprocess,
signal, `Any`, `cast` or ignore; no new Git or SQL write; one new dependency version (beads-client 0.2.0, section 8).

## 13. Docs to update with the code

- [.4.3.1.6](../tl-8bh9.4.3.1.6/plan.md) section 0: "scheduling built in .4.3.1.13 (one-shot rounds); pause = no rounds;
  the dashboard remains next".
- [.8.7](../tl-8bh9.8.7/plan.md) line 46-49: `tl plan next` joins the registered plan surface under the same exception.
- [Hierarchical priority](../tl-8bh9.3/hierarchical-priority.md) "Evidence and status" and the
  [selection review](../tl-8bh9.3/selection-review.md) header: "implemented for plan admission in .4.3.1.13; approval is
  the tracker label `auto`".
- [.4.3.1.11](../tl-8bh9.4.3.1.11/plan.md) section 9 and the `stuck:*` guides: an `admitted` attempt whose entry exited
  before the agent is relaunched by rounds until its deadline; `tl plan start` remains the manual equivalent.
- [.4.3.1.12](../tl-8bh9.4.3.1.12/plan.md) section 11 ("a retry scheduler or backoff" out of scope): note that a round
  retries the push each time, with no backoff.
- `cli_plan.HELD`: one sentence that a round never renews a claim and skips a task whose claim lapsed.
- The live smoke (section 11). The glossary needs no change (round is ordinary English; ready, task tracker, slot and
  step already fit). AGENTS.md/CLAUDE.md unchanged.

## 14. Out of scope

Implement, check, review and land steps; merge, PR, task closure; any trigger: a resident loop, a daemon, a bd events
journal follower, notification on tracker changes (section 5's open design); enabling bd's events journal; session
resume (`stuck:entry_lost` stays a person's); stuck detection, stopping processes, supervision, backoff; a round lock;
holds or pause stored by the factory (the tracker's deferred/blocked states and the approval label are the holds);
portable asks and answers; scarce-tool permits; cross-repository pools and several factories on one backlog; a
dashboard page; profile or config keys for model, effort, minutes or label; `bd ready --claim`.

## 15. Owner questions

Answered (owner, 2026-11-10):

1. **Trigger.** One-shot `tl plan next` now (also the debugging tool). The owner's ideal is event-driven (a tracker
   change notifies the scheduler, no polling); he is between that and a periodic resident loop, and a new task must not
   wait half an hour. Recorded as the open design of a later trigger slice (section 5); rounds stay stateless and
   idempotent so any trigger can call them.
2. **Approval.** The label `auto`, as a required `--label auto`; an empty label is refused.
3. **Entry exited before the agent ran: relaunch automatically.** `slot_busy` should not happen except through a
   concurrency error or a reduced slot count; `claim_lost` is not worth special handling yet; reboot or network loss
   mid-start is expected and the factory continues on its own, traceably. Built as: relaunch through the existing
   start/relaunch path, a move and a `rounds.log` line per relaunch (sections 4, 7a), bounded by the deadline.
4. **beads-client 0.2.0.** The owner releases it from [the shelf request](shelf-request.md).

Open:

5. **Decided in [.4.3.1.14](../tl-8bh9.4.3.1.14/plan.md) section 16** (continue it automatically after a reboot, by
   a renewed deadline; a separate follow-up task, not built). The question as asked:
   **After an outage longer than the attempt's deadline, should the factory start the task over by itself?** Each
   attempt gets a deadline when it is admitted (`--minutes`, 30 in the runbook). If the machine is off or offline past
   it, the admitted attempt is expired: the existing registration fence refuses it, `tl plan show` says
   `stuck:expired_admitted`, and a round only reports it; you abandon it and run `tl plan start`. No agent ran, so nothing
   would be lost by starting over. Starting over automatically would mean a round abandons an expired, never-dispatched
   attempt (returning the claim) and admits a fresh one, which contradicts "an abandoned task is never retried by a
   round" unless that rule exempts abandons the round itself made. **Recommendation: keep it reported for now** (one
   command per task after a long outage) and decide with the trigger slice, which sets how long rounds can be apart.
   The alternative that needs no abandon: a round may relaunch an expired never-dispatched attempt with a fresh deadline,
   but the deadline is part of the admitted, fenced choices, so that would be a new fenced write (a schema change).

Decided here, open to veto: the round reuses `start`/`verify_task`/`publish_task` and adds no state; settle, admit, then
publish; any attempt row (abandoned included) makes a task ineligible, so abandoned and exhausted tasks are never retried
by a round; no issue-type rule (the label decides); assigned to `taskloop` is still eligible; ready read through
`bd ready --label`, parents by `show`, memoized; the accepted priority contract implemented exactly; no round lock,
fences suffice; stop admitting on `no_free_slot`, the round's own refusals and any unavailable; publication retried
every round; one factory per backlog; choices as flags; the beads-client 0.2.0 fake as a prerequisite; the verb name
`next` (it performs the `Next` words the factory may perform itself); the round log at `<artifacts>/rounds.log` through
`PlanFiles`, fixed words, never read, never rotated.

## 16. Not verified

Everything above is read, not run. Not checked: `bd ready --label` with `-n 0` on a large backlog (time); whether bd's
ready rows always carry `parent` for every containment level (one row read showed it); `--deps blocked-by:` and
`--parent` spellings in the runbook against bd 1.3.1 beyond `bd create --help`; every line estimate. bd's events journal
was read from `bd events --help` only (not enabled, not tailed); its per-replica and retention behaviour is bd's own text.

## 17. As built (2026-11-10, on 519cab0c8, uncommitted)

Pin first, as [the shelf request](shelf-request.md) says: `beads-client==0.2.0` from the shelf tag `beads-client-v0.2.0`
(commit af5189bc), `uv lock` changed only that entry; `tests/rules/test_isolation.SHARED` names the new tag. Tests use
beads-client's `ReadyReadClient` and `FakeTaskReadClient(ready=, ready_fault=)`; no local ready-set fake.

Built as designed: `selection.py` (filters, chains with cycle check, padded key, natural id, `order`), `plan_next.py`
(`NextRequest`, `Advancing`, `advance`: settle, admit, publish), `tracker.py` (`ReadyRows`, `TaskRow`, `ready_rows`,
`ancestry`), `plan_ops` (`Action`, `Move`, `Round`, the `Result` union, `exit_code`), `plan_data` (the round shape),
`plan_files.round_log`, `cli_plan` (`tl plan next`, rendering, `Log:` line, GUIDE rows, the HELD sentence),
`cli_composition.open_plan_next`, `composition.tracker_reads`, the two `.importlinter` rows, Run G (section 6f of the
live smoke) and the doc notes of section 13. No schema, SQL write or Git write added (`WRITERS`, `GIT_WRITES` unchanged).
SLOC by the policy counter, after the review repairs: `plan_next` 177, `selection` 49, `tracker` 51, `plan_ops` 360,
`plan_data` 87, `cli_plan` 338, `cli_composition` 146, `composition` 249, `plan_files` 84; tests `test_next` 338,
`test_selection` 71, `test_ops` 538, `test_attempt` 622, `test_plan_cli` 411, `test_task` 99. Gates: `just check` clean
(ruff, pyrefly 0 errors, import-linter 5 kept); `just test` 1123 passed. Nothing run live; Run G not run.

Decided while building (open to veto):

- **One owner of the actor.** `ACTOR = "taskloop"` moved from `composition` to `tracker` (composition imports it), so
  selection keeps the factory's own assignee eligible without importing the composition. `composition._tracker_root` is
  the one root rule of `inspect_tracker_task` and `tracker_reads`.
- **The log writer.** `PlanFiles.round_log()` returns the path (root made); `PlanFiles.log_round(line)` appends with the
  launcher's open flags (0600). The round catches `OSError` and `EvidenceError` per line; `logged` is False after any
  failed line. Each move is written as it is performed; ids that are not one plain word (`[A-Za-z0-9._:@+/-]`, at most
  128) and words failing `WORD` are written `invalid`; time is the reads' clock, `%Y-%m-%dT%H:%M:%SZ`.
- **Whole-round refusals.** `refused:label` (empty label, before any read), `refused:tracker_root` (the opener, an
  unusable root), `database`/`schema` (the opener's guard), `unavailable:store` (the attempts read).
- **Exit.** 3 when `stopped` or any word of a move is `unavailable:*`, `uncertain:*`, `unsettled:*` (the existing
  `UNKNOWN_KINDS`) or `unknown`, a verify move's `branch=` word included (as a publish move's) and a transient
  `skip unavailable:ancestry`; 1 when admission stopped on `refused:*` (the round's own inputs, or a malformed ready
  read); else 0. A verify move's `release=` word does not change the exit (as for `tl plan verify`; see "A held release
  waits for a person"); neither does `report claim_leaked`.
- **Stopping moves.** Admission stopped by anything but `no_free_slot` records a `start <kind>:<reason>` move for the
  task it was trying, so the stop is traceable to a task.

Review repairs (same day, before any commit):

- **Settling never admits.** A `relaunch` (`Next: start`) or `repeat` row is resumed on the snapshot's own attempt only
  (`plan_next._resume`: the launcher, or the repeat port, on that attempt's key), never through `start`. An attempt
  abandoned or released between the snapshot and the call is `skip abandoned` (or `relaunch refused:released`); another
  current attempt is `refused:changed`; the action word is always the operation that was called.
- **Races are per task.** A candidate another start admitted after the snapshot is launched as existing by `start`; its
  launcher or repeat refusal is a per-task `start refused:<reason>`, never a round stop.
- **Leaked claims are moves** (`report claim_leaked`, detail naming `bd unclaim <task> --if-assignee taskloop`), in
  every admission path including the `no_free_slot` stop; GUIDE row `claim_leaked`.
- **`input` and `task` stop the round**; an admitted attempt whose launch is `unavailable`/`uncertain` stops admission.
- **The label is stripped once** before the check and the ready read; `selection.natural` uses `isdecimal`.

Smoke 7 (Run G, Linux/OrbStack, real Codex, 2026-11-10): passed. Real `bd ready` rows carry `parent`, and ancestors
outside the ready set resolve through `bd show` (section 16's open point, now observed). Findings, fixed afterwards in
the runbook: G3 could not prove the parent tie-break when natural id gave the same order (a pre-check now requires
`$G_LOW` to sort first by id); `bd ready -l auto` lists only `$G_LOW` (`$G_WAIT` is blocked by it); G1/G4 now say that
a candidate hitting `no_free_slot` gets no move and that `stopped` is empty (JSON `null`) when no candidate is left.
Also afterwards: the `Next: start` guide for `refused claim_lost` follows section 4 (`tl plan release --abandon`, then
`tl plan start`; the .9 hand re-claim as `taskloop` is withdrawn: it could take another actor's task), and `skip
attempted`/`skip abandoned` moves and their round-log lines name the attempt holding the task. Not observed live yet: a
real reboot or network loss mid-start, `refused slot_busy`, `refused claim_lost`, `stuck:expired_admitted` reached by a
round, `report claim_leaked`, `skip unavailable:ancestry`, a round's `verify` or `repeat` move, a publication refused or
retried by a round, two concurrent rounds, macOS.
- **JSON.** The round shape also carries `logged` (the dashboard needs it as the human `Log:` line does).
- **Order of moves.** Settle moves, then every `skip` (selection runs before admission), then `start` moves, then
  `publish` moves, then the closing log line.
- **Publication twice.** A round publishes only rows whose `Next` was `publish` when it started; after a success the
  task is `done`, so the next round makes no publish move at all (`already_published` appears only after a race).
- **Guides.** New GUIDE rows `failed`, `running`, `attempted`, `abandoned_skip` (a `skip abandoned` move; `abandoned`
  keeps its `tl plan show` meaning) and `no_free_slot`; `start` and `stuck:expired_admitted` mention rounds.
- **Settling reads all backlogs' attempts once** (`attempts_status`, leftovers probed for `verify` rows) and keeps this
  backlog's: one read path, no new store query.

Residuals: the live `bd ready --label auto -n 0` row shape (parent on every level), the runbook's `bd create` spellings,
and the relaunch on a real entry exit are unverified until Run G; question 5 stays open (expired attempts are reported).
