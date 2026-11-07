# Review 2: data flow

Static review, 2026-11-01. Scope: repository documentation and repository code only. No runtime state, credential files, delegate checkout, network, git commands, or tests were accessed. References below name this checkout's source lines, not the historical monolithic engine mentioned in design notes. Findings describe reachable code paths; they are not claims that these failures were reproduced on a running installation.

The principal defect is that there is no single durable task transition. Beads, git, checkpoints, manifests, worker-call records, parks, and JSONL receipts advance separately. Several consumers treat an absent record as permission to start over; several producers mark an effect complete even after an external write failed. Atomic replacement of one JSON document does not reconcile those decisions.

## Authorities and storage

`C` below means `$XDG_CONFIG_HOME/task-loop`, otherwise `~/.config/task-loop` (`packages/kernel/src/tlkernel/paths.py:10`). These locations are descriptions from code; the review did not open the actual config directory. `K` is a repository key, `B` a full bead ID, and `R` an opaque run ID. Do not assume every key uses the same algorithm: the loop uses a checkout-path key, while the slot environment derives its state key from origin (`src/taskloop/app/run/bead_env.py:12`).

```text
C/
|-- runs/R/
|   |-- manifest.json                 run identity, owner PID, heartbeat, terminal state
|   |-- owner-request.json/.lock      pending owner park/stop/notes
|   |-- plan.json, brief.md           exported plan and task brief
|   |-- handoff.json                  exported round history
|   |-- done.json                     memo of previously consumed worker answers
|   |-- pause.json, reexec.json       counters across network pause / exec
|   |-- prepare.stamp                 prerequisite input fingerprint
|   |-- plan-note-<sha256>            producer-warning deduplication
|   |-- engine-checks.json            latest stage check results
|   |-- engine-checks.r<N>.json        numbered check rounds
|   |-- checks/                      command logs and retained check evidence
|   |-- <node>-<N>.raw.json           delegate envelope
|   `-- <node>-<N>.json, replan.md    interpreted answer / planner feedback
|-- engine/R.jsonl                   typed engine events
|-- engine/R.stderr                  captured process diagnostics
|-- engine/R.live/                   per-call worker live event files
|-- checkpoints/B.json               plan, stage cursor, writer, close effects
|-- checkpoints/B.call.json          current worker-call state
|-- reexec/B.json                    pointer describing a version handover
|-- pauses/B.json                    pointer to a network-paused run
|-- parks/B.json                     question count or durable retry/owner wake
|-- landed/B.json                    local fact that a SHA reached a base
|-- asks/B.json, asks/.<sweep>        current ask and sweep markers
|-- ask-ledger.jsonl                 ask transitions
|-- decisions/K/ADR-<N>.json          decisions in force / retired decisions
|-- decisions/K/uses.jsonl            decision use records
|-- results/K/<check-id-hash>/<digest>.json
|-- results/K/base-red/<digest>.json  untouched-base results
|-- check-durations/K.json           learned durations
|-- loop/K.<PID>.json                one loop's published state and carry
|-- loop/K.command.json              stop command with PID/start targets
|-- loop/K.jsonl                     bead verdicts received by loops
|-- loop/K-rest.json                 shared bead cooldowns
|-- loop/K/
|   |-- <B>-<timestamp>.log/.outcome.json
|   |-- loop-<PID>.log, exits.jsonl, died-<PID>.json
|   `-- loop.pid, factory.log         detached factory process records
|-- slots/K/<sequence>.json, seq     slot-wait tickets and sequence hint
|-- slots/<path-hash>.setup          successful slot input hash
|-- slot-state/<origin-key>/<slot>/  persistent temp/build/package scratch
|-- worktrees/K/<path-key>.json      recorded worktree ownership / kind
|-- artifacts/B/                    files copied out of disposable worktrees
|-- locks/<what>-<identity>.lock     OS lock files; holder hints beside them
|-- snapshots/K.<name>.json          typed snapshots
|-- sessions/<session>.json          session index
|-- shared/K.json                   cross-bead notes / flakes
|-- handoff/K.md                    bounded session-compaction handoff
|-- factory.db                      index-owned bd projection in bead; marker and health in kv
|-- repos.json, host.json            registered repositories / host resources
|-- pinned.json, bad-versions.json   owner version override / refused installs
|-- releases/last.json, suite-green.json, suite-*.log
|-- events.jsonl, traces.jsonl, usage-history.jsonl
|-- reflect-digest.json, reflect-view.json
|-- dash.pid, dash.json
`-- githooks/

repository main checkout             .task-loop.json, bd's local Dolt database
slot or worktree/
|-- .git                             link to its gitdir; refs/config are shared
`-- .task/
    |-- engine.lock, engine.take     process-owner record / admission mutex
    |-- checks/                      check scratch
    `-- B/brief.md, evidence/, artifacts/
```

Path evidence: `packages/kernel/src/tlkernel/paths.py:22`, `:93`, `:101`, `:122`, `:133`, `:145`, `:161`, `:182`, `:195`, `:233`, `:243`, `:264`. Additional filenames come from `packages/kernel/src/tlkernel/runlayout.py:105`, `src/taskloop/app/run/engine.py:350`, `src/taskloop/stores/call_state.py:83`, `src/taskloop/app/loop/run.py:64`, and the factory layout documented in README.md. The release clone mentioned in AGENTS.md is outside this review's task-execution path.

| Authority | Stored fact versus derived view | Cache / staleness boundary |
| --- | --- | --- |
| bd local Dolt database, reached through `Beads` | Task text/status/assignee, dependencies, lease, slot metadata and generations are stored. Ready order, area ownership and lint decisions are derived. JSONL exports are not the task authority. | Queue entries, parent lookups, brief snapshots and dashboard bead lists are copies; a person's edits or another claim can invalidate them. |
| git object database and refs | Task commits and remote acceptance are facts. “Already landed” is partly derived from HEAD's subject suffix and ancestry (`app/land/push.py:51`). | `origin/main` is a mutable local observation shared by worktrees. A fetch elsewhere changes it without taking this run's engine lock. |
| `runs/R/manifest.json` | Recorded run lifecycle, independently of bd task status. A directory without a readable manifest is omitted (`contracts/locator.py:66`). | Locator caches by mtime/size (`contracts/locator.py:89`); dashboard liveness also consults PID. It cannot make a multi-file snapshot. |
| `checkpoints/B.json` | Resumable plan/cursor and completed close-effect keys. | It is bead-scoped, not run-scoped; `.get()` treats incompatible/torn records as missing (`app/run/state.py:118`, `contracts/stores.py:104`). |
| `B.call.json`, `done.json` | In-flight envelope pointer and consumed-answer memo, respectively. | Reattachment matches coordinates and a full-prompt hash, not a committed tree/config identity (`app/run/worker_call.py:197`). |
| Results store | Stored successful check evidence and planned skips; gate decisions are derived from keys. | Input globs, toolchain and environment participate in `RunMemo.key`; exported green lookup has a smaller predicate (`app/checks/cache.py:112`, `:218`). |
| Park and ask stores | Retry time, reason, question count, answer and consumption are stored independently of bd. | No shared transaction with bd open/block/unclaim or loop carry. A stale/foreign record can disappear through `.get()`. |
| Engine/events/traces/loop JSONL | Observations and receipts, not an atomic transition journal for the other authorities. | Typed readers skip undecodable records (`contracts/stores.py:155`). Rotation readers operate on the current file (`contracts/rotating.py:1`); “append-only” does not mean an unbounded query history. |

### Crash model used below

Every arrow below can be interrupted by `kill -9`. For `JsonStore.write`, a process kill before rename leaves the previous document (or no document); after rename the new whole document is visible. Writes use `fsync=False` (`packages/kernel/src/tlkernel/stores.py:115`); this is not a power-loss durability guarantee. The vendored implementation is at `skills/task-loop/_vendor/atomic_io/__init__.py:21`.

There is no transaction across two JSON documents, across JSON and bd, or across a git push and a receipt. Effect keys are written **after** calling the effect (`src/taskloop/domain/interpret.py:35`). A crash in that gap repeats the effect; a function returning after merely warning about failure nevertheless gets a completed key. Plain `write_text` exports such as plan/brief and the setup marker can be partial (`app/run/engine.py:353`, `app/plan/briefs.py:43`, `app/slots/reset.py:144`).

Engine JSONL uses append through the vendored append primitive (`contracts/rotating.py:17`, `skills/task-loop/_vendor/jsonl_log/_append.py:16`). A kill can leave unmatched start/end pairs. A log row before a mutation proves intent, and a row after a mutation leaves a mutation-to-log crash gap. Neither order supplies an exactly-once external operation.

## Normal execution, hop by hop

```text
bd task text + dependencies + labels
       |
       v
H1 pick/rank ---- cached queue / parents / area view
       |
       v
H2 slot ticket -> slot claim/marks -> loop engine.lock -> task claim
       |
       v
H3 preserve WIP -> fetch -> checkout task/B -> clean -> setup marker
       |
       v
H4 run-task admission -> engine.lock takeover -> claim generation
       |                   -> run manifest -> reset -> exported brief
       v
H5 plan answer -> draft checkpoint -> lint/send-back -> accepted checkpoint
       |
       v
H6 write round -> worker files + envelope + call state + answer memo
       |
       v
H7 engine checks -> logs + pass cache + numbered/latest CheckRun
       |
       v
H8 review -> accept / write again / replan / owner ask
       | accepted stage: WIP commit/push -> next-stage checkpoint
       +-------------------------------> H6
       v
H9 verify -> squash/commit -> fetch/rebase -> gate -> locked push
       |
       v
H10 bd land provenance -> landed/B.json -> cleanup receipts -> bd sync
       |
       v
H11 stored close outcome -> save branch -> close JSONL -> model reflection
       |
       v
H12 file follow-ups -> Reflect comment -> bd close/block/open
       |
       v
H13 detach/cleanup -> slot release -> checkpoint removal -> manifest end
       |
       v
outcome file -> loop verdict row -> counters/cooldowns -> next pick
       |
       `-- chores (daily): traces -> reflection digest -> new/commented beads
```

The requested conceptual sequence “land → cleanup → close/follow-ups → reflect” is not the actual order. Cleanup receipts precede close, actual cleanup runs late, the model reflection is inside `RecordRun` before follow-up filing, and the Reflect **comment** follows filing. See `src/taskloop/domain/effects.py:150` and `src/taskloop/app/run/closer_record.py:78`.

### H1 — bead → pick

**Truth/copies:** `rank_ready` reads bd ready plus a separate all-open query, computes the pick set, open-child umbrellas, lint and area exclusions, and caches parent lookups in the `QueueRule` (`src/taskloop/app/loop/queue.py:75`, `:137`, `:224`). Loop queue rows and first-seen times are derived and then published to `loop/K.PID.json` (`app/loop/loop.py:246`).

**Kill/idempotency:** A kill between the two bd reads changes no bead; restart recomputes selection. A kill after publishing queue rows leaves an obsolete queue, not a claim. The two bd reads are not one revision: a child or queue label can change between them. A person's edit after selection is not covered by the later atomic claim.

**Races/logs/cause:** Concurrent loops can rank the same bead; task claiming arbitrates later. Lint refusal can mutate labels/comments through `Refuser`. Ordinary rank changes have no per-transition JSONL row: the queue snapshot is overwritten. `BdFailure` during enumeration becomes `ready=[]` (`queue.py:234`), so the original infrastructure error does not reach the queue snapshot; no runtime diagnosis is inferred from an empty queue alone.

### H2 — pick → slot → claim

**Truth/copies:** The waiter's ticket is stored under `slots/K`; priority and sequence derive order. Slot availability comes from bd status/hold plus the engine-lock record. Under the slot-take lock, `Slot.take_locked` claims the slot and then writes holder metadata/generation (`src/taskloop/app/slots/pool.py:47`). The loop starts a lease heartbeat, writes a loop-owned engine lock, and under the area lock rechecks area occupancy before claiming the task (`app/loop/loop.py:320`, `app/loop/take.py:61`).

**Kill/idempotency:** Ticket creation uses a temporary file and exclusive hard link; a kill before link leaves a disposable temp, after link leaves a ticket whose process liveness is rechecked (`stores/files.py:45`, `:65`). A kill after slot claim but before holder marks leaves bd claimed without full marks. A kill after task claim but before `lease.add`/run startup leaves an in-progress task without a run manifest. Lease reconciliation, not a run terminal record, must recover these gaps.

**Races/logs/cause:** Slot take is serialized within the local take-lock scope; task claim and area bookkeeping are still distinct writes. Same-session actors can reclaim their own bead, so the generation protocol matters (F05). `slot_take` follows marks; `claim` follows bd claim and metadata, followed by provenance (`app/track/verbs.py:25`). A kill between the bd mutation and event leaves silent ownership. The outer loop's final slot release does not pass a generation (`app/loop/loop.py:341`), whereas run-task's owned-slot release does (`app/run/entry.py:347`).

### H3 — claim → slot reset/setup

**Truth/copies:** Working files and git commits hold prior work; bd slot marks do not prove checkout contents. Reset checks busy/hold, recreates a missing tree, aborts rebase if necessary, commits dirty work where it stands, fetches, selects an existing task branch or creates it, cleans, and runs setup (`src/taskloop/app/slots/reset.py:39`, `:62`, `:77`).

**Kill/idempotency:** A kill after a WIP commit preserves that commit; after checkout but before setup leaves the right branch with incomplete setup. A successful setup followed by a kill before marker publication runs setup again. The setup command therefore must tolerate repetition, but the contract does not enforce that. The setup hash includes matching input paths/content, not the setup argv (`reset.py:115`, `:133`); retaining the same inputs while changing the setup recipe can leave old setup accepted. This cache limitation also affects the split-config finding F10.

**Races/logs/cause:** Busy check and later git changes are not one critical section with engine admission; `engine.take` covers lock takeover, not this whole mutation sequence. Reset's branch freeing checks other engines, but the engine's separate freeing path and land cleanup do not (F04). Setup uses `capture=False`; the typed `slot_setup` event retains exit/time, while failure becomes only `setup exited N` (`app/wire/slots.py:129`, `app/slots/reset.py:140`). WIP/READY lines are console observations, not typed phase receipts. The loop retries `slot_broken` once before judging it (`app/loop/take.py:37`).

### H4 — setup → engine admission/reset

**Truth/copies:** run-task reloads config, resolves its worktree, takes over `.task/engine.lock`, rechecks park/admission (`app/asks/admission.py`), claims again, bumps the bead generation, creates/adopts a manifest, then starts the engine (`src/taskloop/app/run/entry.py:189`, `:313`, `:375`). The engine lock stores process start identity as well as PID; the manifest stores PID/host/heartbeat as a different liveness record.

**Kill/idempotency:** Killing between claim, generation update and manifest creation leaves different subsets of these facts. Killing during manifest directory creation can leave an invisible run directory (`contracts/locator.py:122`). Run reset fetches and checks out again, preserves same-branch dirty work as WIP, clears scratch except evidence, and rewrites the two brief copies (`app/land/tree.py:67`). A kill between the brief copies leaves disagreement; these files are not an atomic pair.

**Races/logs/cause:** Engine admission check/write is under `engine.take` (`app/slots/engine_lock.py:115`), but fence validation is separate from the protected mutations (F05). A person editing bd can race brief export's show/comments reads. Manifest creation/heartbeat and checkpoint changes have no matching transactional JSONL row. `run_start` is delayed until after resume selection; earlier startup failures may only have a claim event, console log, and manifest (`app/run/records.py:55`). A refused engine lock is reported as `TAKEN`, and a missing run outcome becomes a synthesized failure in `app/loop/verdict.py:71`.

### H5 — reset/resume → plan

**Truth/copies:** bd text/comments are exported into a brief and `BriefSnap`; old engine prose is filtered, oldest comments are bounded, and the hash drives resume/amend decisions (`src/taskloop/app/plan/briefs.py:23`). The planner consumes this snapshot, repo rules, decisions and shared notes. The model answer is not yet an accepted execution contract.

**Kill/idempotency:** Planner `ask` checkpoints a plan that merely “fits” **before** finding invalid commands/anchors; a kill can make that draft the next executable plan (F06). Accepted plans are exported and checkpointed separately (`app/plan/planner.py:193`). A kill after export but before checkpoint can leave the dashboard showing a plan not adopted by recovery. A kill before export can leave an adopted draft without its display copy.

**Races/logs/cause:** Person changes to acceptance/comments can occur after export. Resume compares brief/head/branch and promised files (`app/run/resume.py:42`); it does not rerun the entire plan send-back contract for a kept checkpoint. Planner send-backs have `step_end`/`transition` and Note rows. A zero-stage plan uses `NOOP`/owner ask rather than unconditional completion in `planner.py:164`; do not use the obsolete design note's “empty plan closes done” as current-code evidence. F06 concerns bypassing validation, not a claim that the historical empty-plan branch remains unchanged.

### H6 — plan/stage → write call

**Truth/copies:** The checkpoint holds stage/write coordinates and writer reference; working files hold the actual edits. Before a normal write, `StageLoop.round` saves the checkpoint and checks for a version hop (`src/taskloop/app/write/stage_loop.py:40`). `WorkerCall` matches a consumed-answer memo or current call state, emits step/call starts, stores `calling`, and invokes delegate (`app/run/worker_call.py:197`, `:233`).

**Kill/idempotency:** Killing before spawn leaves a repeatable calling intent. Killing after worker edits but before the envelope is stored leaves edits without an adopted answer; restart can ask the writer again. Calling-state session identity is initially only `resume_of`; a fresh call's new ref is not stored by this path until returned/stop handling. Raw answer publication precedes a separate returned-state publication; a kill between them leaves an unreferenced answer. Consumption precedes memo publication (F12). These gaps make “resume the step” weaker than exactly-once model/tool effects.

**Races/logs/cause:** A surviving writer/route process is represented in the engine lock; another actor must respect that record before entering the tree. A person running `tl check` does not acquire that engine lock. Request details and failure cause are mapped at the delegate boundary described below. `call_start`, `call_end`, `vendor_error`, `retry_decision`, `kill`, and `transition` rows describe attempts; checkpoint/call-phase changes themselves are silent.

### H7 — write → checks

**Truth/copies:** After fixes, the checker computes a worktree tree hash/base, forms command/input/environment/toolchain keys, executes registered and plan checks, then publishes each successful cache record (`src/taskloop/app/checks/runner.py:64`, `:80`; `app/checks/executor.py:186`). Pass cache entries are derived evidence, not task state. Check durations, input inventories and ignored-file hashes are memoized for the block (`app/checks/cache.py:30`).

**Kill/idempotency:** A kill after command success but before cache publication reruns the command. After publication but before CheckRun/log completion, restart may reuse a pass without a completed step pair. The numbered CheckRun, JSONL checks row and latest CheckRun are separate writes (`app/checks/runner.py:144`, `app/write/check_round.py:25`). A command's external side effects are not undone by rerunning. Red attempts can overwrite their log on another attempt; the returned result retains the last attempt's diagnostics (`app/checks/attempts.py:38`).

**Races/logs/cause:** `tl check` creates a standalone stage run and executes in the selected worktree without taking its engine lock (`app/launch/check.py:62`). Resource leases limit configured resources, not all filesystem writers. A check, writer, person, or main-checkout fetch can mutate files/base while the block runs. There is no final tree revalidation before `memo.remember` (`app/checks/executor.py:200`); gate pass publication has a related identity defect (F02). `check_start/end`, command rows and a Checks row are logged. Failure classification, last-log tails and diagnostic extraction rewrite output; full logs are only available if saved before the crash.

### H8 — checks → review → next write/stage

**Truth/copies:** `CheckRun`, diff, plan cases, writer summary and review answer are inputs. Triage derives blockers/deferred work, updates unchecked items, and accumulates follow-ups in memory (`src/taskloop/app/write/review_round.py:115`). Acceptance adds the stage index/goal, commits/pushes WIP, then stores the next cursor (`app/run/run_once.py:161`).

**Kill/idempotency:** A kill after review but before the cursor is saved can repeat review/write. A kill after WIP push but before cursor publication can restore the previous cursor against a newer HEAD and trigger amendment. Pending follow-ups are missing from the state saved at this boundary (F03). Follow-up triage even logs “filed as a follow-up bead” when it has only appended an in-memory item (`review_round.py:125`).

**Races/logs/cause:** Another land can advance the base between stages; the engine fetches/rebases before later stages (`app/run/run_once.py:182`). A person's edits can change the tree after review; the next cursor saves HEAD, not an immutable reviewed worktree snapshot. Reviews and red checks have transitions, but accepted-list/checkpoint writes have no independent commit receipt. `replan.md` and bounded handoff history are derived summaries, not the full sequence of accepted external effects.

### H9 — accepted stages → verify/gate/push

**Truth/copies:** Verification resolves unchecked items; land compares git contents and prior-land evidence, builds the task commit, fetches/rebases, runs gate checks, and serializes push through the repo land lock (`src/taskloop/app/run/run_once.py:95`, `app/land/lander.py:94`, `:125`). The remote's accepted commit is the delivery fact, not a successful command start.

**Kill/idempotency:** A kill during squash/rebase leaves git recovery state; later reset/save logic can abort an unfinished rebase. A kill after remote acceptance but before response/`landed_sha`/receipt is an uncertain push. `Landed.already` fetches, checks HEAD's bead-suffixed subject and ancestry, and may recover that fact (`app/land/push.py:45`). It is a heuristic over git, not a receipt written atomically with the remote. The gate token currently names values reread after execution (F02).

**Races/logs/cause:** The land lock serializes cooperating landers and releases; it does not serialize every fetch, `tl check`, person edit, or engine reset. A generation check precedes push but does not atomically authorize the remote update (F05). Push rejection/network errors are classified from text (`app/land/push.py:84`). `gate_start/end`, `land_try`, lock/unlock, command and transition rows are observations; a kill can leave remote delivery without any land receipt.

### H10 — push → landed receipt / bd synchronization

**Truth/copies:** After releasing the land lock, `Sync` applies `RecordLand`, then `BdSync` (`src/taskloop/app/land/record.py:44`). RecordLand writes a bd land event/provenance, `landed/B.json`, and JSONL cleanup retry inputs (`app/run/engine.py:357`). These copies can disagree during a crash.

**Kill/idempotency:** A kill after bd provenance but before landed JSON repeats receipt work. A kill after landed JSON but before cleanup inputs leaves no logged cleanup obligation for that attempt. A kill after each effect but before its checkpoint key repeats that effect. Dolt sync is a separate external operation; failure is raised, then the engine's close conversion discards it (F07).

**Races/logs/cause:** Another run can move refs between receipt and cleanup. Cleanup retains expected local/remote OIDs, but that is not process ownership (F04). bd synchronization can observe other task updates; it does not include follow-ups and close that have not happened yet. `land`, `land_receipt`, and `land_cleanup` record different facts; `bd sync` is principally a Note in the engine path, not an independently completed durable task transition.

### H11 — outcome → close journal / model reflection

**Truth/copies:** Closer chooses outcome/disposition, attempts to store `EndRec`, then interprets effects. EndRec holds the close's outcome and pending follow-up list, but only if a checkpoint already exists (`src/taskloop/app/run/closer.py:98`, `app/run/state.py:172`, `:204`). Close effects are keyed by bead/run/effect kind.

**Kill/idempotency:** Early startup/planning failures with no checkpoint have no durable EndRec/effect journal. A kill after any effect and before its key replays that effect; a kill after a failed effect returns can instead suppress its retry. `RecordRun` appends Close, invokes the model reflection, and writes the trace before task settlement. A Close row is therefore not evidence that bd close succeeded (F07).

**Races/logs/cause:** Lease heartbeat is stopped before closer effects (`app/run/run_once.py:235`); process ownership and fence checks must carry the remainder. Reflection ignores SIGTERM with the close and uses a separate direct delegate call, without normal worker-call reattachment (`app/run/reflect.py:35`). Killing there can repeat reflection/trace publication. Reflection input is clipped transition/warning history and session rows, not every original cause. It cannot recover follow-ups already dropped at a hop (F03).

### H12 — close → follow-ups / Reflect comment / bd settlement

**Truth/copies:** `FileNotes` files accumulated follow-ups, persists filed/refused results into the checkpoint, then Reflect comments on the source bead and settlement closes/blocks/opens it (`src/taskloop/app/run/closer_notes.py:60`, `:117`; `app/run/closer_settle.py:53`). `FollowKey` is local bookkeeping, not a create idempotency key in bd.

**Kill/idempotency:** A kill between create and `keep_filed` duplicates ordinary follow-ups (F08). A refused create is retained as `unfiled` but the FileNotes effect still completes; finished tasks subsequently drop the checkpoint (F09). A kill after source close but before the remaining effects leaves a closed task that ready selection will not naturally revisit; an explicit rerun/reconciliation path is needed to finish the close. A refused source close returns a warning and can still lose its checkpoint (F07).

**Races/logs/cause:** Person closure/assignee edits can race settlement. The application generation read and bd `if_assignee` are separate, and the latter distinguishes actors rather than generations. Follow-up create failure uses full-output lint extraction but keeps bounded error text (`adapters/bd.py:109`). Reflect and warning comments are prose, not pending operations. `close`/`block` events occur after successful bd changes (`app/track/verbs.py:68`, `:95`); `Said`/Close/trace can precede or outlive those changes.

### H13 — settlement → cleanup/release → loop's next pick

**Truth/copies:** The late ReleaseSlot effect detaches unfinished branches and retries logged land cleanup; entry/loop finally blocks release the engine lock and slot lease. Finished close drops the checkpoint; `RunOnce.settle` then writes manifest terminal state, and track.outcome_line writes the outcome file for the parent (`src/taskloop/app/run/closer_branch.py:83`, `app/run/run_once.py:210`, `app/track/outcome_line.py:44`). The loop publishes a verdict row and separately updates counters/cooldowns.

**Kill/idempotency:** A kill after cleanup but before its result row makes the next attempt inspect refs again. A kill after checkpoint deletion but before manifest end/outcome leaves completed work without the parent's verdict; missing-outcome handling can report failure despite a closed bead. A kill after slot-mark clearing but before unclaim leaves a claimed slot missing holder marks (`app/slots/pool.py:100`). A kill after outcome but before loop row/counter publication loses queue accounting. No one atomic operation ties these endpoints together.

**Races/logs/cause:** Cleanup can switch a live slot without its ownership lock (F04). Lease stop only sets an event; it does not join an already executing heartbeat (`app/slots/lease.py:35`, `:46`). The dashboard can observe terminal manifests with older bd state, or a closed bead with a live manifest. Cleanup exceptions are broadly suppressed in ReleaseSlot (`closer_branch.py:86`), and outer slot-release failure is suppressed (`app/loop/loop.py:341`). Only logged cleanup retry outcomes expose those operations; there is no typed checkpoint-delete or manifest-end JSONL row. Loop verdict detail is clipped to 300 characters and console detail to 160 (`app/loop/loop.py:345`).

### H14 — completed traces → reflection digest → follow-on work

**Truth/copies:** This is separate from the per-run model reflection and Reflect comment. Loop chores may start a daily detached digest (`src/taskloop/app/launch/loop.py:149`); it reads reflection items from traces, derives recurring cause clusters, routes them to a registered owner repository, and files a bead or comments on an existing one. `reflect-digest.json` stores cluster-to-bead/run memory; `reflect-view.json` is a view location, not a task completion authority (`src/taskloop/app/report/reflect.py:58`, `:96`, `:160`; `contracts/paths.py:217`).

**Kill/idempotency:** The digest lock serializes manual/daily digest processes. It creates/comments externally before saving state after each cluster (`app/report/reflect.py:180`, `:195`, `:208`); a kill between those operations requires title-similarity lookup or may repeat the comment. Reading only currently available trace lines cannot regenerate omitted original causes or missing per-run reflections. The digest is downstream of close: it cannot serve as an acknowledgment that the source task's follow-ups were delivered (F03/F09).

**Races/logs/cause:** A person can close/edit a matched bead between lookup and update, independently of the digest lock. Cause ownership is inferred from registered repositories and trace contents; it is not a captured task claim. The inspected digest path writes bd and digest state rather than the original run's close-effect keys. The per-run trace/Reflect prose and the later digest state are separate records; there is no JSONL transaction joining cluster creation to source completion.

## Delegate boundary: request, answer and cause loss

```text
plan/check registry + duration history + writer-family labels
     -> worker_request.request
     -> RunRequest {role, cwd, resume, family, timeout, idle, engine_only}
     -> temporary brief/schema + route.py run argv
     -> delegate process [implementation outside review scope]
     -> final stdout line parsed as JSON + captured stdout/stderr trace
     -> DelegateResult.stop/data -> policy action
     -> call/checkpoint/park/outcome records -> loop verdict
```

The request builder is `src/taskloop/app/run/worker_request.py:19`; argv construction is exclusively `packages/kernel/src/tlkernel/delegate.py:52`. Engine-only recipes are bare configured `just` recipes for write calls. A pinned family plus such recipes automatically enables `--engine-only-advisory` (`worker_request.py:38`); that is a different enforcement mode from the unconditional guard wording in `docs/dev/integrations.md`. Read-only calls do not receive those recipes. The outside delegate's enforcement cannot be established from these files.

Delegate is resolved again before each call; a refused new installation keeps the previously resolved route (`src/taskloop/app/run/delegation.py:11`). There is no task-long immutable route artifact in the manifest; each later subprocess opens the selected installed path. For the same major contract, minor fields/defaults can change between writer and reviewer. `contract: 3`, stop scope/permanence/retry and schema validation are the local contract, not proof that delegate accepted a durable exactly-once call. `RunRequest.call_id` exists, but `worker_request.request` does not fill it; call intent is local.

| Transformation | Evidence | Information no longer present downstream |
| --- | --- | --- |
| Parse only final stdout line | `src/taskloop/adapters/delegate.py:132`, `:207` | A valid JSON answer followed by another line becomes `no_answer`; a malformed envelope becomes synthesized contract failure. Raw stdout/stderr exists in `Answer.trace` for this call, not universally in the terminal record. |
| Synthesize engine timeout | `src/taskloop/adapters/delegate.py:197` | Replaces the worker's stop with engine wording when no usable answer returns. The root cause may only be earlier stderr/live activity. |
| Reviewer timeout → overrun | `src/taskloop/app/run/worker_call.py:287` | Rewrites reason/scope/say to a lane overrun. `ans.raw` remains the original envelope while `ans.res` has changed semantics. |
| Stop → VendorError | `src/taskloop/app/run/worker_call.py:305` | Uses `first_error` or `say`, at most 300 chars, not the complete nested stop/text/trace. |
| Special pinned write diagnostics | `src/taskloop/app/run/worker_request.py:51` | Full argv/raw stop/say/text/first_error/trace is retained only for write stops in `pin.STOP_REASONS`, not every stop. |
| Stop → human reason | `src/taskloop/domain/lanes/says.py:71`, `app/run/lane_acts.py:180` | `said` shrinks to 200 chars; `fix` is separately rendered. A generic leading line can crowd out detailed later cause. |
| Command → tail / CmdEnd | `src/taskloop/app/run/shell.py:47` | Returned tail is last 15 lines; failing CmdEnd keeps last 600 chars. Unsaved full output is not recoverable from that row. |
| Check → result / prompt | `src/taskloop/app/checks/executor.py:218`, `app/checks/evidence.py:60` | Result tail is 1500 chars; compact failed prompt uses a 600-char diagnostic budget. Full saved logs are a separate artifact. |
| bd failure → typed error | `src/taskloop/adapters/bd.py:109` | Missing sections are extracted before clipping, from combined stderr/JSON error/stdout; retained error text is first 500 chars, later follow-up warning first 200 (`app/land/record.py:67`). The historical first-line-only lint parser is not the current implementation. |
| Final close → logs/reports | `src/taskloop/app/run/closer_record.py:76`, `app/run/records.py:113`, `contracts/locator.py:171` | Transition detail often keeps first line/200 chars; Close/trace 500; manifest reason 300; loop reason 300. No terminal record is a complete causal chain. |

## Exceptional flows

Each table entry uses the same per-file kill rule described above. “Replay” means reapplying the operation; it is not an assertion that its external effects are idempotent.

### Lost run

```text
engine killed -> heartbeat stops -> stale live manifest
             -> is_lost(local host, >=300 s, PID gone)
             -> manifest LOST

separately: expired bd lease + no observed running bead
             -> release claim/slot -> ready selection -> resume checkpoint
```

| Hop | Truth / cache / derived state | Kill, replay, race, log and cause |
| --- | --- | --- |
| Process disappears → stale observation | Manifest last heartbeat/PID plus engine lock; running-bead map also reads slot metadata (`contracts/runlife.py:49`, `app/run/running.py:19`). | Dashboard derives lost without writing; loop startup/doctor/report/wait/request gate can persist lost. `is_lost` uses PID existence rather than the engine lock's start identity, so PID reuse can preserve a stale live view. No checkpoint or task status changes merely because the manifest is lost. |
| Observation → LOST write | `RunLocator.mark_lost` rereads the manifest and overwrites terminal state (`contracts/locator.py:173`). | No CAS links the earlier liveness decision to this write: a take-up/heartbeat can race the read/replace. Kill before write leaves live; after write leaves lost. This is a manifest write, not an engine Close/trace. |
| Lease expiry → reclaim | bd leases and live-bead map, independently of lost manifests (`app/reconcile/leases.py:11`). | Kill after one released claim leaves the rest for a later sweep. No run/branch rollback is implied. Loop says released lines; it does not synthesize the dead worker's answer or original error. |
| Reclaim → resume | Existing branch/checkpoint/call state; new run ID unless pause/reexec/dead-close adoption applies (`app/run/engine.py:149`). | A live orphan worker can keep the tree busy even with expired bd lease; a lost manifest alone is insufficient authority to reset it. Resume may amend against newer HEAD. The lost PID diagnosis cannot reconstruct why the process died. F03, F05, F08, F12 cover unsafe recovery consequences. |

### Pause

```text
typed worker stop / owner request / network push failure
      -> policy Yield / Blocked kind
      -> [network only: counters + pause pointer]
      -> EndRec + parks/B.json + close effects
      -> bd open/unassigned or owner ask/hold
      -> loop timer / network probe / owner answer
      -> gate -> resume
```

| Hop | Truth / cache / derived state | Kill, replay, race, log and cause |
| --- | --- | --- |
| Stop → policy | Delegate stop facts and local counters; `LaneActs` derives retry/wait/yield (`app/run/lane_acts.py:99`). | Kill before a durable result can lose the typed cause. RetryDecision and transitions are logged, but local per-call counters are not a durable pause sequence. |
| Yield → park and release | `Closer.pause` stores a reason/wake for transient reasons and NOOP; owner input/ask/hold uses separate records (`app/run/closer.py:135`, `app/asks/parks.py:45`). | Kill before park but after earlier outcome writes leaves no wake; after park but before unclaim leaves the bead held. Known transient reasons use exponential delay/jitter; needs-owner parks have no timer (`domain/lanes/pauses.py:23`). Unknown reasons default to needs-owner, but `parks.paused` does not itself create every such owner ask. |
| Network → same-run pointer | `runs/R/pause.json` counters then `pauses/B.json` pointer (`app/run/reload.py:58`). | Kill between files loses adoption, not the task checkpoint. Pointer read is followed by delete before validation/adoption (`app/release/reexec.py:37`), so a kill there loses that handoff. |
| Wake → next attempt | Durable park, loop carry `later`, role cache/network state and bd readiness (`app/loop/settle.py:123`, `app/loop/loop.py:255`). | Same-run network adoption defeats pause attempt counting/new retry time (F11). Role/net counters have different restart lifetimes. A terminal pause Close can precede successful bd release. Owner park additionally relies on hold metadata; releasing hold is its explicit wake (`app/asks/parks.py:27`). |
| Repeated slot failure → slot set aside | `Counters.slot_quick` is process memory; after the configured count, `aside` calls slot hold for `slot_aside_min`, default 720 minutes (`app/loop/settle.py:42`, `contracts/config.py:134`). | The path corresponding to incident (8) depends on a typed `slot_broken` verdict and reset-recovery result, not duration alone (`app/loop/verdict.py:49`, `app/loop/settle.py:60`). Kill before hold loses the streak; after hold but before `slot_aside` event leaves bd hold without that event. Expiry/release follows slot metadata (`app/slots/pool.py:175`). Setup failure text is only an exit number at this boundary, so the task log, not the 12-hour hold text, is needed to identify its infrastructure cause. |

### Retry

```text
within worker call: stop -> Retry/Wait/NewThread/Reroute -> call again
within stage: red checks/review -> feedback -> write again -> replan if capped
across runs: failed/paused close -> ready/owner wake -> resume/amend/retry
```

| Hop | Truth / cache / derived state | Kill, replay, race, log and cause |
| --- | --- | --- |
| In-call retry | Raw stop, mutable `Call.counts`, writer/session ref, calling record (`app/run/worker_call.py:69`, `app/run/lane_acts.py:139`). | A kill resets some in-memory retry charges. A replayed external writer can repeat tools; new-thread reroute is not rollback. RetryDecision/Wait/Transition record the route taken, with bounded text. |
| Check retry | Last command log/output/signature, check retry settings; untouched-base results can be reused (`app/checks/attempts.py:38`). | Kill between attempts can lose previous signature/attempt count. Earlier attempt output can be replaced by the next log write. Resource leases release on process death; output outside the tracked tree can remain stale. |
| Stage retry/replan | Checkpoint cursor plus brief/head comparison; replan.md and handoff are derived feedback (`app/write/check_round.py:72`, `app/run/resume.py:42`). | Normal stage-loop writes save the cursor before each write; accepted-stage advancement saves after WIP push. A kill in either interval changes what work repeats. Draft plan acceptance and pending follow-ups are not fully recovered (F03, F06). |
| New run | New/adopted manifest, current profile, existing branch/call/checkpoint. | Fault cooldown is shared via `loop/K-rest.json`; other counters live only in carry. Two processes sharing an actor need more than `if_assignee` to serialize (F05). A retry's `run_start.started_because` is derived, not an external transaction ID (`app/run/records.py:39`). |

### Version hop

```text
checkpoint at safe point
 -> end current step as moved
 -> runs/R/reexec.json counters
 -> reexec/B.json note
 -> reload JSONL/event + TL_REEXEC environment
 -> execve(uv run --script newer/tl.py)
 -> uv retains predecessor PID; new Python child
 -> explicit predecessor lock handoff -> same R, next attempt
 -> checkpoint resume with newly loaded config/code
```

| Hop | Truth / cache / derived state | Kill, replay, race, log and cause |
| --- | --- | --- |
| Discover → handover | Installed target/pin/refused-version list; current checkpoint; two counter/pointer files (`app/run/reload.py:68`, `:90`). | Kill between files leaves a half-handover. A kill after note/reload event but before exec looks like a move attempt even though the new code never ran. `e.moved` only avoids close after a successful exec; real exec does not return. |
| Exec → takeover | `TL_REEXEC` carries old PID/bead/run/owned slot; engine_busy grants the explicit predecessor handoff (`app/slots/engine_lock.py:90`). | Do not equate the Python PID with uv's retained PID. The historical incident (2) must be judged against this explicit handoff, not the stale “pid stays” loop comment. Kill before child adoption leaves old ownership until liveness/lease recovery; workers are tracked separately. |
| Takeover → resume | New manifest attempt, new claim generation, counters and bead checkpoint. | New process reloads config and omitted in-memory pending follow-ups vanish (F03/F10). Checkpoint `.get()` can silently drop another schema version; counter `.get()` can silently reset accounting (`app/run/reload.py:44`). No multi-version migration is established by recording the code version. |
| Failed new image → fallback | Loop outcome absence, reexec note age and old path (`app/loop/run.py:79`). | Fallback only applies to a nonzero/missing outcome soon after exec, not every semantic failure. It consumes the reload note through read/delete. A report with a fault can bypass this fallback. `reload_fallback` and bad-version state record the fallback decision; they do not restore lost process-only data. |

### Loop crash/restart

```text
loop killed
  |-- child/worker may continue -> engine heartbeat + lock still own slot
  `-- loop state/carry remains -> later live() archives died-PID state
new loop -> prune/reconcile lost manifests -> fresh refresh/queue
         -> release_dead leases -> current branches/checkpoints -> next task
```

| Hop | Truth / cache / derived state | Kill, replay, race, log and cause |
| --- | --- | --- |
| Parent dies → child ownership | Child engine manifest, engine lock and slot heartbeat; the dead parent's queue/counters are stale (`app/loop/run.py:40`, `app/slots/lease.py:17`). | Python exception cleanup stops children; SIGKILL does not run that finally block. Restart must inspect child/worker ownership rather than presume the slot is free. There may be no loop exit row at all. |
| New loop → state selection | New PID/state and newly created `Counters`; inheritance occurs through explicit handover JSON, not automatic replay of died files (`app/loop/loop.py:58`, `app/loop/core.py:39`). | Carries are snapshots, not a replayable queue journal. `live()` moves dead loop state to `died-PID.json` (`app/loop/files.py:49`). Kill between observation and rename/publication leaves stale display; logs can show no received child verdict. |
| Recovery → queue | `runlife.reconcile` at loop startup; per-pass lease sweep, bd and parks. | Already closed beads are absent from normal ready picking, so incomplete terminal side effects are not automatically resumed just by restarting the loop. Files of unknown versions can be omitted. F07/F09 are cases where terminal records wrongly end the recoverable obligation. |

### Plugin update mid-run

```text
installer changes installed target / cache availability
  |-- current Python keeps imported code
  |-- each delegate call resolves its installation again
  `-- task-loop safe point discovers target -> version-hop flow
between beads: refresh profile -> maybe_move -> pick
```

| Hop | Truth / cache / derived state | Kill, replay, race, log and cause |
| --- | --- | --- |
| Installation changes → running process | Imported task-loop code is process-local; route and later executable/schema paths are external installed files. | No run-owned immutable copy is created. If the old delegate path disappears while a new contract is refused, `Delegation.route` retains a path that may no longer exist (`app/run/delegation.py:15`); the next subprocess can become synthesized no_answer. Resolution is noted, but installation replacement itself is not a task transition. |
| Next call → changed delegate | Fresh resolved route/contract; writer ref/call memo/checkpoint from prior calls. | Same major contract does not prove unchanged resume semantics or guard capability. Killing between resolve and spawn opens another path-availability window. Full diagnostics are selectively retained; generic summaries can hide the actual contract/guard cause. |
| Next tl safe point → new engine | Explicit reexec flow above. | Pending follow-ups disappear (F03), effective policy can change (F10), and incompatible state is read as absence. The loop calls `refresh` before `maybe_move` (`app/loop/loop.py:208`), so a newly incompatible profile can stop the old loop before it takes the installed upgrade. `profile_ahead` exit is not a bead failure, but it also does not carry out the update. |

## Process races and dashboard observations

```text
                         bd task/slot state
                        /        |        \
              loop pick/claim  run-task   person / dashboard commands
                  |              |
                  +------ engine.lock / generation checks
                                 |
                       slot files + shared git refs <--- person tl check
                                 ^                 <--- main fast-forward/fetch
                                 |
                       land lock + push/land-stack
                                 |
                     receipts / checkpoints / manifests
                                 |
                    dashboard caches and independent reads
```

| Actors | Shared facts and missing serialization | Observable consequence / finding |
| --- | --- | --- |
| Two loops | Ticket/take lock and bd claim arbitrate some ownership; queue/profile snapshots and child verdict accounting differ. | The loser can have a stale queue/parent map. Interrupted claims and slot marks need lease recovery; no manifest necessarily exists yet. |
| Loop versus manual run-task | Engine lock and area lock, then separate bd claim/generation. | Explicit loop/reexec takeover is distinct from a new hand run. Failed-open/stale fence reads and clean-tree detachment weaken the ownership proof (F04/F05). |
| Live run versus person `tl check` | Same slot files/build outputs and shared refs; standalone check creates its own manifest but no engine lock. | Check cache can describe the tree seen before concurrent changes; GatePass can be minted for different values (F02). Resource limits only cover resources declared in configuration. |
| Live run versus `land-stack` | Land lock covers forge merge, not engine ownership of a checkout; stack cleanup runs after merge. | Cleanup can detach a live clean slot or remove a clean ad-hoc worktree (F04). Expected branch OID is not an engine-owner token. |
| Loop/run versus main fast-forward | Shared `.git` refs/config and main checkout profile; engine's loaded config differs from later slot/profile loads. | A single task can use one check registry and another slot path/setup policy (F10). Reexec also rereads the profile. |
| Dashboard versus all writers | Manifests/logs/asks/parks/bd list fetched independently, with different TTLs. | A displayed closed bead/live run or free slot/old queue need not represent any single instant. It must not be used as a transaction receipt. |

Dashboard details: bead reads use last-touched marker plus cached responses, return old rows when listing fails, and refresh the cache timestamp even on failure (`src/taskloop_dash/readers/beads.py:35`, `:58`). Worlds adds a five-second typed-bead TTL, reads slots/loop states separately, and reads ledger/ADRs/landings with independent TTLs (`src/taskloop_dash/readers/world.py:35`, `:65`, `:137`). Run logs are cached by file metadata and joined to the current manifest each read (`readers/runlogs.py:18`). Thus staleness is not a bounded coherent snapshot during bd failure.

“Read-only dashboard” is a query-path description, not the entire service's capability: the API documentation lists POST verbs, and bead caching writes under C/cache. Owner verbs go through Intake/Ports and can change asks/holds/request files while the engine reads them. A dashboard observation does not acquire engine ownership or perform lost-run reconciliation; `runlife.shown` derives liveness for display. Undecodable bead rows are silently omitted (`readers/world.py:40`).

The error/visibility gaps in these observations are recorded here as data provenance limits, not used to claim a dashboard-originated instance of any historical incident.

## Findings

### F01 — P1: malformed/unreadable committed profile becomes a default policy

**Evidence:** `src/taskloop/app/wire/slots.py:42` resolves a commit and returns `{}` on JSON parse or git-show error at line 48; working-tree fallback also returns `{}` on errors at line 52. `packages/kernel/src/tlkernel/config.py:164` supplies a default push command and line 181 defaults checks to an empty list. `src/taskloop/app/land/gate.py:108` allows a pass when the resulting config has no gate checks.

**Failure:** A committed malformed `.task-loop.json`, or a failed read of an existing profile, becomes “no configured checks” instead of a refusal. The engine can run and land using defaults, with the configuration error erased before strict typed validation sees it.

**Fix:** Distinguish a genuinely absent profile from failed read/parse and stop admission with the original path/commit/error for the latter. Persist the successfully decoded profile identity with the run.

**Past incident prevented:** none; this is an additional fail-open policy path, not evidence that incident (3) had this cause.

### F02 — P1: gate issues evidence for the tree/base observed after execution

**Evidence:** `src/taskloop/app/checks/runner.py:89` captures the check block's tree/base before execution. `src/taskloop/app/checks/executor.py:200` stores passes under pre-execution keys without a final tree comparison. `src/taskloop/app/land/gate.py:147` returns `self.issue()` after green results; line 117 rereads current HEAD tree/base. `src/taskloop/app/land/push.py:64` compares the push only with that newly minted token.

**Failure:** A standalone check, person, or cleanup changes HEAD/files while gate commands run; or another worktree fetch advances the shared base. Green results for the old inputs can be paired with a token naming the new HEAD/base, so the pusher's equality check accepts a commit/base pair the gate did not judge. The land lock does not serialize those other writers.

**Fix:** Return a gate result carrying the exact captured tree, base and config digest, and mint the token from those values only after rechecking current worktree/HEAD/base equality. Reject and rerun the gate if any captured identity moved.

**Past incident prevented:** none; incident (10) concerns config changes, whereas this is check-evidence identity under concurrent mutation.

### F03 — P1: version hops discard pending follow-ups before close

**Evidence:** `src/taskloop/app/run/fields.py:37` initializes `e.leftovers=[]`. Plans add to it at `src/taskloop/app/plan/planner.py:62`; reviews add at `src/taskloop/app/write/review_round.py:125` and line 152. `packages/kernel/src/tlkernel/checkpoint.py:70` has no pending-leftovers field in RunState, and `src/taskloop/app/run/review_glue.py:15` persists only filed/refused review work. `src/taskloop/app/run/reload.py:39` serializes counters without leftovers; `src/taskloop/app/run/resume.py:118` restores the plan without rebuilding `e.leftovers`. They are first saved for close in `src/taskloop/app/run/closer.py:113`.

**Failure:** Accept a stage with planned/review follow-ups, install an update, and exec at the next write/land boundary. The new process retains the plan/cursor but its filing queue is empty; a land-boundary hop can close the task without filing any of those follow-ups. A normal pre-close crash has the same omission.

**Fix:** Persist the pending follow-up queue, with stable keys and origins, in RunState whenever it changes and restore it on every resume. Use that queue as FileNotes' authority rather than rebuilding it opportunistically from model answers.

**Past incident prevented:** (9) normal plugin update breaks run state. Incident (5)'s lint rejection is a different loss mechanism, covered by F09.

### F04 — P1: cleanup and engine branch freeing mutate live clean worktrees

**Evidence:** `src/taskloop/app/land/cleanup.py:34` checks main/branch OID and slot kind but never engine ownership; line 46 detaches a slot and line 50 removes an ad-hoc checkout. `src/taskloop/app/slots/reset.py:158` only tests dirty status and branch before checkout. Stack calls cleanup at `src/taskloop/app/land/stack.py:196`. The engine's independent `src/taskloop/app/land/tree.py:128` also detaches other clean checkouts without a busy check, unlike slot reset's `src/taskloop/app/slots/reset.py:99`.

**Failure:** A person lands a branch that a live engine has cleanly committed and is reviewing/checking. Stack cleanup sees the expected OID and detaches its slot at base, or removes its clean ad-hoc worktree, under the active process. The branch comparison preserves newer commits but supplies no protection while HEAD still equals the landed commit.

**Fix:** Acquire the target checkout's ownership/admission lock and refuse mutation when a foreign live engine or worker owns it, then recheck dirty/branch/OID under that lock. Make all branch-freeing and cleanup paths use that operation.

**Past incident prevented:** (1) LANDBRANCH deleting an occupied worktree; slot classification alone does not prevent the remaining active-checkout mutation.

### F05 — P1: generation fencing fails open and is not an atomic authorization

**Evidence:** `packages/kernel/src/tlkernel/fence.py:15` converts bd failure to `None`; `stale` at line 87 explicitly fences nothing on an outage. `take` at line 74 reads and then unconditionally writes the next generation. `src/taskloop/app/run/state.py:113` checks before returning a document whose write happens afterward, and `src/taskloop/app/land/push.py:68` checks before external push. `src/taskloop/app/track/verbs.py:78` guards close by assignee, not generation.

**Failure:** A stale run can pass fence validation while bd is unavailable, write its checkpoint, or push, even though another holder has taken the task/slot. Two same-actor processes can also read the same generation and both write the same increment; subsequent actor guards cannot distinguish them. A local engine lock covers a worktree, not the bead across different worktrees.

**Fix:** Require readable current ownership for mutations and allocate generations with an atomic compare-and-increment tied to task claim. Serialize per-bead mutation authorization through the protected write, including a durable handover protocol for remote push.

**Past incident prevented:** none; this is a separate stale-owner failure, not a restatement of incident (2)'s PID handoff bug.

### F06 — P1: a crash promotes an unvalidated draft plan to executable state

**Evidence:** `src/taskloop/app/plan/planner.py:43` obtains a plan and lines 44–46 save it as `step="write"` before `sendback.find` at line 47. `fits` at line 57 checks stages/question/count, not executable commands, anchors or all send-back rules. `src/taskloop/app/run/resume.py:118` restores/publishes a kept plan; `src/taskloop/app/run/run_once.py:161` goes to its stages without repeating send-back validation.

**Failure:** Kill the engine after the draft checkpoint and before lint/send-back completes. Restart can write from a plan the interrupted planner was about to reject, bypassing the repository's command/anchor restrictions and spending write/check rounds on invalid instructions.

**Fix:** Store drafts with a non-executable validation state, and advance to a write cursor only after all plan checks pass. Resume must rerun validation for any draft or checkpoint whose validation/config identity is absent.

**Past incident prevented:** none; the current NOOP handling must not be confused with historical incident (6).

### F07 — P2: post-push synchronization and source-close failures are acknowledged as completion

**Evidence:** `src/taskloop/app/land/push.py:156` raises on failed bd sync after land. `src/taskloop/app/run/run_once.py:232` replaces every non-LANDED outcome with LANDED when `e.landed_sha` exists, erasing that detail. Independently, `src/taskloop/app/run/closer_settle.py:72` only warns when bd refuses close; `src/taskloop/domain/interpret.py:43` then marks the effect applied and `src/taskloop/domain/effects.py:153` schedules checkpoint removal for finished outcomes.

**Failure:** A successful push followed by failed Dolt sync or rejected task close can produce a landed Close/trace/outcome and delete its recovery checkpoint. The bead may remain in progress, or its records never reach the remote, while normal selection no longer carries a retryable synchronization/close obligation.

**Fix:** Store code-delivered, bd-synced and bead-closed as separate completion facts, retaining an outbox until each required effect succeeds. Propagate failed settlement as an unapplied effect rather than returning after a warning.

**Past incident prevented:** none.

### F08 — P2: follow-up creation has a create-to-checkpoint duplication window

**Evidence:** `src/taskloop/app/land/record.py:60` creates in bd before recording its FollowKey at lines 63–64. The pre-create lookup at lines 43–49 is only called for the UNCHECKED category (line 57), and matches any source title prefix rather than the exact item. `src/taskloop/domain/interpret.py:43` records the enclosing FileNotes key only after all this returns.

**Failure:** Kill after a normal follow-up is created but before its key is saved. Recovery repeats FileNotes and creates the same follow-up again; the source-title lookup used for the deliberately single unchecked follow-up does not deduplicate ordinary follow-ups.

**Fix:** Give each follow-up a stable external idempotency key stored on the created bead, and resolve that exact key on recovery before creating. Persist each pending item and its resulting bead ID independently of the enclosing FileNotes effect.

**Past incident prevented:** none; incident (5) was a rejected/dropped-create path, addressed separately by F09.

### F09 — P2: refused follow-ups become completed FileNotes and lose their retry record

**Evidence:** `src/taskloop/app/land/record.py:65` collects refused items and saves them to the checkpoint at line 70, then returns normally. `src/taskloop/app/run/closer_notes.py:60` turns that into Notes and returns; `src/taskloop/domain/interpret.py:44` marks FileNotes complete. `src/taskloop/domain/effects.py:153` deletes a finished run's checkpoint after closing the source task.

**Failure:** A temporary bd/lint refusal leaves only a warning/Reflect count and prose containing the unfiled titles after a landed task closes. No durable pending-create queue remains for an automatic retry, even though the engine knew these follow-ups were required.

**Fix:** Keep rejected items in a durable outbox outside the disposable task checkpoint and retry them by stable key until created or explicitly waived. FileNotes must not report completion of required filing merely because it recorded a refusal count.

**Past incident prevented:** (5) dropped follow-ups; preserving the missing-section parser alone does not provide delivery.

### F10 — P2: one task uses incompatible configuration snapshots across selection, slots and reexec

**Evidence:** `src/taskloop/app/wire/slots.py:65` fully decodes the main working-tree profile just to get the base, then reads another profile at the resolved base commit. `profile_slots` at line 78 reads the main working-tree copy again. `src/taskloop/app/run/entry.py:195` reloads config for each new process, including exec, while `packages/kernel/src/tlkernel/checkpoint.py:160` stores no effective profile/commit identity. `src/taskloop/app/loop/loop.py:208` refreshes before attempting the installed-version move.

**Failure:** Fast-forward the main checkout while an engine is active: later slot lookup/setup/release can use a changed slot directory/base/count while the engine still uses its earlier checks/land command. Exec can adopt the old plan/cursor with new checks and limits, or an old loop can reject a new working-tree key before it gets to upgrade, even if only the base hint was needed.

**Fix:** Capture the effective engine and slot profiles plus source commit at admission and pass that snapshot through slot operations and reexec. Treat a new profile as an explicit versioned transition that validates/migrates the saved plan before resuming; read the base hint without decoding unrelated future fields.

**Past incident prevented:** (3) profile newer than running tl; (9) plugin update mid-run; (10) main fast-forward changing configuration under a run.

### F11 — P2: same-run network adoption freezes pause attempts and retry deadlines

**Evidence:** `src/taskloop/app/run/engine.py:153` adopts a network pause and line 160 reuses its run ID. `src/taskloop/domain/lanes/pauses.py:93` returns the existing Park immediately whenever `rec.run == run`, before considering a new reason/not-before/attempt. `src/taskloop/app/loop/settle.py:133` uses that same-run park and returns before normal pause counting, setting `later` to the old retry time at line 139.

**Failure:** Once a network-paused run is resumed, a second network failure under the same run ID can keep the already expired retry time and first attempt count. It bypasses intended exponential rest/pause counting; if the probe looks up while pushes/calls still fail, the loop can keep revisiting the same bead with no increasing durable cooldown. A changed later pause reason can also retain the earlier record.

**Fix:** Identify pause episodes by a monotonic attempt/transition ID rather than run ID, and deduplicate only repeated application of the same episode. Publish a fresh reason/deadline for each later pause, then let loop settlement use that episode.

**Past incident prevented:** none. This is related to (7), but a stale wake episode is a different failure from having no wake rule at all.

### F12 — P2: worker answer is marked consumed before its recovery memo exists

**Evidence:** `src/taskloop/app/run/worker_call.py:416` calls `c.state.consumed()` at line 419 before `done_memo.keep` at line 420 and interpreted node publication at line 437. `src/taskloop/stores/call_state.py:116` only reattaches answers/refs for calling/returned phases. `src/taskloop/app/run/done_memo.py:18` requires an entry in a separate done.json.

**Failure:** Kill between consumed-state publication and memo publication, while the stage checkpoint still points before the call. Restart ignores the saved consumed envelope, misses the memo, and calls the writer/planner again although its files or tools may already have changed the world. The stored phase claims more progress than recovery can actually use.

**Fix:** Publish the recoverable memo before changing the call to consumed, or store both acknowledgments in one atomic record. Recovery should be allowed to reuse a consumed envelope until the corresponding stage cursor has durably advanced.

**Past incident prevented:** none.

## Top 10

Rank is by potential task/data loss first, then admission and recovery cost. Every row points to the evidence, concrete failure and fix above; F08 and F12 remain additional P2 findings.

| Rank | Priority | Finding | Past incident prevented |
| --- | --- | --- | --- |
| 1 | P1 | F01 — corrupt profile silently removes configured gate policy | none |
| 2 | P1 | F02 — gate token certifies a different tree/base from execution | none |
| 3 | P1 | F03 — pending follow-ups vanish on normal version hops | (9) |
| 4 | P1 | F04 — cleanup detaches/removes a live clean checkout | (1) |
| 5 | P1 | F05 — unavailable/non-atomic generation checks authorize stale owners | none |
| 6 | P1 | F06 — restart executes a draft plan that never passed lint | none |
| 7 | P2 | F07 — delivered code masks failed sync/close and drops recovery | none |
| 8 | P2 | F09 — rejected follow-ups have no durable delivery obligation | (5) |
| 9 | P2 | F10 — selection/slots/reexec use different profile revisions | (3), (9), (10) |
| 10 | P2 | F11 — resumed network run reuses an obsolete wake episode | none |
