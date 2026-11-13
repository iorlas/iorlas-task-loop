# Explicit drain command

Task: `tl-8bh9.14.126`. Prepared 2026-11-13 against the current successor.
Status: implemented under the owner's implementation request. The preparation below records the accepted design;
see the As built section for the resulting boundaries. This change authorizes no upgrade or database discard.

## Purpose and current evidence

Provide `tl drain`: stop taking new work, let existing executions finish under their
current runtime, and exit successfully only at a verified idle boundary. The command
provides the boundary for a supervised restart or upgrade; it performs neither.

Read alongside [the foundation](../tl-8bh9.8.7/plan.md),
[the glossary](../../glossary.md), and
[the delivery ruling](../architecture-review/architecture-review-playbook.md#appendix-r---docs-format-delivery-strategy-prototype-2026-11-13)
(Appendices Q and R). The related
[restart plan](../tl-8bh9.14.127/plan.md) owns incompatible-version refusal.

Source inspected for this plan:

- `cli.py` and `cli_step.py` register no drain command. `interrupts.py`'s first
  Ctrl-C stops rounds after their current move. `rounds.py` then exits without waiting
  for surviving entries or workers. Reusing that flag alone cannot implement drain.
- `round.py` can relaunch, repeat, advance, admit, publish and auto-land. Merely
  removing its ready-task admission still creates attempts through other paths.
- `rounds_lock.py` serializes rounds per database/backlog, but one-shot `step start`
  and `step next` bypass that lock. A factory database can contain several backlogs.
- Agent admission, chained admission, checks admission and failed-check repair live
  in `admit.py`, `admit_chain.py`, `check_admit.py` and `check_repeat/store.py`.
  `launch.py` registers surviving entry processes through the shelf's handshake.
  Registration, the entry body and its worker have distinct lifetimes.
- `factory_schema.py` currently declares compatibility version 17. Matching-runtime
  restart retains unfinished state; incompatible startup refuses without discarding
  it. `test_restart.py` and `test_factory_restart.py` cover those contracts. Stored
  session references do not implement deferred conversation continuation
  (`tl-8bh9.3.4`).

The supplied task was not found by `bd show` in this workspace. Do not invent a
replacement task, change claims, or infer implementation approval from that absence.

## Command and observable behavior

`tl drain [--db PATH] [--artifacts PATH] [--json]` uses the existing machine-config
resolution and path precedence. It targets the entire resolved `factory.db`, across
all repositories, slots and backlogs in that database. It requires an existing,
compatible database; it never initializes, upgrades or replaces one. No task label,
tracker root, model, deadline or checkout is required to request a drain.

The request commits a durable admission fence before reporting that draining has
begun. Every work-producing consumer observes that fence, including already-running
rounds, new rounds, one-shot commands and direct application operations. The fence
orders drain against admission and dispatch; a scheduler-loop check is insufficient.
Executions already authorized before the fence finish normally. After the fence,
no fresh task, repeat, next-step attempt, checks rerun or land operation starts.
Existing attempt bodies may finish their own setup, checks and finalization; this
does not authorize another step or a retry attempt.

| Situation | Behavior |
|---|---|
| No executions or unresolved external actions remain | Commit completion and exit 0, including when the factory was already idle |
| An entry, agent, setup process, checks execution or synchronous land is active | Leave it running; observe until its owned work and writes finish |
| A launch or external action crossed the fence with a pre-existing intent | Reconcile its actual outcome before declaring idle; retain its identity and result |
| An admitted attempt never received dispatch authorization | Preserve its attempt and reservation; do not launch it to make drain progress |
| An attempt finished but its entry still runs | Keep waiting; a result or free slot alone does not prove idle |
| A registered owner died but its child may remain | Observe the recorded child identities; do not infer termination from the parent's death |
| Liveness, an external-action outcome or the database cannot be established | Report the uncertainty; never report successful completion |
| Another drain caller arrives | Join the same durable request; do not reset its boundary or create another scheduler |
| The caller is interrupted or crashes | Stop waiting; leave the durable fence and all executions intact; a later invocation continues it |

Idle means there are no surviving execution owners or owned processes that can still
write for work authorized before the fence, and no unresolved external-action
intents. It does not mean that every task is complete, released, published or landed.
Held tasks, safely unlaunched attempts and retained claims/reservations can remain.
Observe all relevant persisted executions, not only each task's latest attempt or
`task_status.in_flight`; historical/lingering processes also prevent completion.

Use native, boot-aware process identities through the existing shelf observation
ports. Unknown identity, permission failures and PID reuse never count as confirmed
termination. Do not signal, kill, abandon, release claims, discard state, or impose
a timeout that stops running work. Existing attempt deadlines continue to apply.

Human output states that new work is blocked, what remains active or uncertain, and
whether idle was verified. JSON exposes the same typed result and identities/counts
through one codec, without parsing log text. Use the existing exit-code vocabulary:
0 for verified completion, 1 for refusal, 3 for an unreliable observation, and 130
for caller interruption. An uncertain/error exit leaves the fence in place. Messages
explain the situation and the owner's restart/discard decision in words; they never
tell the owner to run a recovery CLI command.

## Durable state, restart and concurrency

Put the implementation in the drain feature slice, with one request/wait application
operation shared by the CLI and other consumers. A drain-owned store owns the gate,
its generation and the minimal persisted action/owner records needed for safe
reconciliation. `factory_schema.py` remains the DDL/version owner. Do not store
control flags in artifacts, lock-file metadata, tracker labels or logs.

New closed states and outcomes use stdlib enums/classes, with one storage/output
codec each. Database-edge models use pydantic v2. Ordinary words such as drain do
not introduce a new glossary entity. Keep SQL and connections inside store modules;
expose typed ports to the use cases and composition roots.

Admission and dispatch authorization check the gate in their short committing
transactions. Persist intents before tracker claims, process creation or Git actions;
perform external IO outside write transactions, then record the observed result.
Pending intents remain visible to drain. In particular, close the existing
claim-before-admission gap in the touched fresh-admission path: after a crash or a
drain race, ask the tracker whether the claim is ours and adopt or release the
recorded intent. Do not add another compensation chain. Fence every attempt creator,
including failed-check repair, rather than relying on presentation-layer checks.

Dispatch has a recorded authorization before the registered-start action. A launch
already authorized when drain commits is existing in-flight work, even if the
registration callback arrives later. Drain waits for that handshake to resolve and
the resulting execution to finish. A launcher with no such authorization cannot
spawn after the fence. Preserve the shelf's registered-start guarantee.

Rounds recognize drain separately from their interrupt flag: stop work-producing
moves and exit without reopening admission. The drain operation observes/reconciles
existing work without calling the ordinary round, whose settlement can repeat or
relaunch. Reuse existing finalization operations only where they cannot create work.
Account for synchronous factory operations as well as detached entries; a live land
validation or an unresolved claim/push cannot disappear from the idle calculation.

A completed drain stays fenced after the waiting command exits. A deliberate new
`tl step rounds` invocation under matching code can reopen a completed drain in one
transaction after liveness reconciliation; that explicit restart is the scheduling
authority. It preserves unfinished attempts, session references and reservations.
An invocation that encounters an incomplete drain continues draining rather than
reopening it. One-shot commands never clear the fence implicitly. Earlier rounds
retain their old generation and cannot resume scheduling when a later invocation
reopens admission. Reopening and a concurrent new drain are serialized by the store.
An ordinary restart with no drain request retains the existing reconciliation rules.

## Release boundary and scope

The durable state change requires a compatibility-version bump. There is no schema
migration, old-state reader or automatic discard. The first release containing drain
cannot drain a version-17 database with its new incompatible runtime. For that
bootstrap installation, the supervisor stops admission and verifies all existing
entries, agents, checks and other writers have finished under the matching current
runner, then the owner deliberately discards the database through its owning
operation before initializing the new runtime. Do not claim the not-yet-installed
command provides that first boundary.

For subsequent upgrades, request drain using the pinned matching release before
changing runtime/schema. Completion does not authorize restart, publication, merge
or database deletion. The pinned previous-release runner and its packaging remain
separate delivery work; this task supplies the callable drain capability. Preserve
the established incompatible-version explanation and all evidence/SQLite sidecars.
Do not implement session continuation, automatic upgrade, backup/restore or factory
state reconstruction.

## Bounded implementation and verification

1. After owner approval, add the drain slice's typed operation, store, schema and
   deterministic process/time ports. Implement durable request, reconciliation,
   completion and completed-drain reopening as explicit transitions.
2. Wire transactional admission/dispatch fences and the minimal action ownership
   needed for the idle proof into the existing owners listed above, including land.
   Preserve each slice's table ownership and external-action reconciliation. Do not
   extract a generic scheduler or move unrelated features as part of this work.
3. Integrate rounds exit/restart and root `tl drain` parsing/composition/rendering.
   Add truthful help and update the owning CLI/runtime documentation when implemented.
4. Add focused pytest behavior contracts for the slice, fence integrations and CLI.
   Use semantic shelf fakes and real temporary SQLite stores; no live agents,
   subprocess imports, process signals or sleep-based concurrency tests.

Required evidence includes:

- A running agent and a running checks attempt finish naturally while all new work
  paths stay blocked; drain exits only after their entries and owned processes stop.
  Cover multiple backlogs and an idle factory with held/reserved but unlaunched work.
- Deterministic interleavings put drain before and after admission, tracker claim,
  dispatch authorization, child registration and land validation. No unauthorized
  attempt starts, claim is lost or unresolved action is counted as idle.
- Parent exit with a surviving child, completed result with live entry, stale/PID-reused
  identities and unknown observation never produce false completion. Historical
  executions are covered even when a newer attempt exists.
- Close all connections, reopen the same database with fresh objects, and continue
  an interrupted drain. Concurrent callers share its request. Completion persists;
  deliberate matching-runtime restart preserves existing work and fences old rounds.
- Human/JSON CLI output and exit codes agree. Missing, incompatible and inaccessible
  databases cause no initialization, mutation or false success. Interruption leaves
  processes, worktrees, claims, sessions, evidence and drain intent intact.

Read the then-current justfile before execution. After implementation run `just check`
and `just test`, the declared focused successor gates; add any new focused files to
the gate selection if the vertical slice puts them outside its existing directories.
For individual contracts, after `just install` use
`uv run --frozen --no-sync python -I -m pytest` with explicit focused paths. No whole
repository/live suite, baseline imports, new dependency or typing escape. Retain
400 source lines per file, 80 per function and 800 per test file.

Acceptance is demonstrated by the installed `tl drain` surface plus the behavioral
contracts above: no new work starts after its fence, existing executions finish,
and success means verified idle. The original planning step changed only this document and made no implementation claim.


## As built — 2026-11-13

`tl drain` resolves the existing machine configuration and durably fences the whole compatible database before
printing progress. The drain slice owns request, observation, completion and explicit reopening; one codec renders
human output and JSON Lines. Interrupted waiting preserves the fence. Refusals, uncertain observations and interruption
use exits 1, 3 and 130; exit 0 requires verified idle. No drain operation launches an attempt, signals an execution,
releases an admitted reservation or clears an existing task claim.

Schema 18 adds drain state and external-action records, including boot-aware caller identity, reconciliation revision
and the land's checkout. All attempt creators recheck the fence in their committing transaction. Fresh admission
records its claim intent first and serializes competing pending claims before either can overtake the other. Dispatch
records authorization before registered start; its callback can register across the fence only with that earlier intent.
A synchronous round, land or finalization records its owner before external IO. An existing registered entry can finish
its own capture, verification, publication and release after the fence.

The owning readers collect every retained agent entry, agent, setup process, checks entry and check command, including
historical/concluded rows. Caller death alone never settles a synchronous external action. Claim reconciliation adopts
committed admission or returns only the unmatched recorded claim; delivery reconciliation observes origin and the
tracker without another push, close or land. A reconciler adopts the intent transactionally before external IO, so a
second drain caller cannot count that IO as idle. An outcome that cannot be established remains fenced and reports
uncertainty, including an interrupted synchronous operation without a sufficient observable result.

Explicit rounds startup finishes an incomplete drain and exits. A later explicit startup rechecks a completed boundary
and atomically reopens it. Earlier rounds retain their generation and cannot schedule across that reopening. One-shot
commands cannot reopen it. Matching-runtime unfinished attempts, sessions and reservations remain intact.

The focused contracts added are `tests/steps/test_drain.py`, `tests/steps/test_drain_fences.py`,
`tests/steps/test_drain_observe.py` and `tests/cli/test_drain_cli.py`. They cover natural agent/check completion,
registration and admission races, process uncertainty, historical owners, concurrent reconciliation, interrupted restart,
land delivery reconciliation, and the CLI's output/exit contracts. Existing rounds, claim-concurrency, release-race and
source/isolation policy contracts now include the new slice and its ownership transactions. `just check` and
`just test` remain the required gates; their existing selections include all four new files.

The first schema-18 installation still requires the supervisor's verified previous-runtime boundary and the owner's
deliberate discard. A schema-18 command refuses schema 17. The pinned previous-release runner remains separate delivery
work. This implementation performs no migration, discard, restart or session continuation.
