# Preserve the cause of an agent stopped by a signal

Task: `tl-8bh9.14.166`. Status: proposed implementation plan, 2026-11-14.

## Outcome

When an agent ends because of a signal, persist the factory's known initiating cause and
show it in the hold's cause sentence. Distinguish the factory sending a signal from an
agent observed to have died by a signal whose sender is unknown. Restarting rounds,
adopting slots and reconciling liveness must preserve a live entry and agent.

Investigate the reported 2026-11-13 incidents: task `.120` at 21:37 around a rounds
restart and `.148` at 23:16, about four minutes after `tl slot adopt --count 5` while
rounds were running. The title reports three kills, but the supplied description identifies
two; investigate any third identifiable occurrence without making it a prerequisite for
fixing the behavior. A negative return code alone cannot identify the original sender.

## Current evidence

Revalidated against source commit `f6b6b594d55ea824e686eab6e227c81102623e87`.
The existing plan was committed at `e951881d`, refreshed at `7974cc05`, and then
merged with current main, including the shelf upgrade at `5e7dced4`.
There is no unfinished commit for this task on the branch. An inherited main commit
contains a squashed `Task-Loop-Wip:` message for a different task; it is not this
task's unfinished implementation.

The current source establishes these paths; it does not establish the historical sender:

- `launch.py` launches entries in their own sessions. Its liveness reconciliation returns
  `AlreadyRunning` for a matching entry, refuses unknown observations, and only replaces
  an entry observed gone or replaced. `Attempts._call` sets `RunHooks.unattended=False`.
- `interrupts.py` stops only the rounds process. `rounds.py` stops scheduling; neither
  signals entries. `slots.adopt` inserts missing slot rows after Git validation and leaves
  known slots alone. `owned_processes.py` performs observations, not termination.
- `any-agent==0.11.0` and `stream-proc==0.9.0` are both pinned to shelf commit
  `14bb4512c383c174d8db580d66d1c270aa656dee`, through tag `any-agent-v0.11.0`.
  The installed packages' provenance matches the lockfile. In `any_agent.supervisor`, deadline
  expiry sets `timed_out` and calls `_stop`; watchers and policy can also stop an agent.
  `_wait` handles entry SIGTERM/SIGHUP by raising `SystemExit`, stopping the agent's tree,
  then re-raising. Parent disappearance stops an agent only with unattended supervision.
  `any_agent.procs.kill_tree` delegates to `stream_proc.stop_tree_report`, which sends
  SIGTERM first and escalates to SIGKILL when needed.
- `RunHooks.before_stop` receives `StopIntent` with the exact worker identity, reason,
  first requested signal and triggering entry signal. A refusal propagates and forbids
  both the stop and exception-cleanup retry. `after_stop` receives that intent and the
  report, including on exceptional exits. The supervisor serializes stop initiators;
  the first wins. Entry SIGTERM/SIGHUP, Ctrl-C, parent loss and other caller exits have
  distinct attribution. `RunHooks.stops` retains the reports in memory.
  `any_agent.procs.stop` now copies actual attempted/delivered SIGTERM/SIGKILL flags
  from `stream_proc.StopReport`, with false defaults and no elapsed-time inference.
  Delivery means a kernel signal call succeeded, not proof that the signal caused the
  observed exit. These APIs supply the previously missing shelf prerequisite; the
  factory does not yet connect either stop callback to durable state.
- `RunOutcome` has several separate reason fields. `execution_facts` projects only part
  of that information; neither `Attempts._call` nor `EvidenceFiles.capture` persists
  the hook's stop reports. An interrupted supervisor can raise before normal capture.
- `attempt_entry.main` then prints `failed terminated_by_signal`, without storing a
  structured cause. `hold_facts` reads execution facts and entry evidence, but
  `hold_cause.RUN['killed']` supplies only “The agent process was killed by a signal.”
  `hold_text` recognizes one entry-log marker for display; this is insufficient for
  durable attribution and must not become a workflow-control input.

## Implementation

1. **Establish the signal paths and the incident evidence.** Read retained attempt data
   through the owning readers, including registered entry/agent identities, deadlines,
   execution facts and evidence timestamps. Inspect the runtime revision used for each
   identifiable incident rather than assuming current HEAD ran then. Follow all signal
   paths through the pinned shelf code, including Git-command timeout cleanup and
   registered-start cleanup: those libraries also run during adoption and reconciliation.
   Record a proven causal chain, or explicitly state what was not retained. Do not infer
   a sender from proximity to an adopt or restart, parse logs to drive state transitions,
   or operate on the historical processes/worktrees. Retain the findings in this directory.

2. **Connect the released stop hooks at the signal owner.** Use the pinned shelf's
   `before_stop(StopIntent)` and `after_stop(StopIntent, StopReport)` callbacks; do not
   duplicate process supervision, signal handling or stop serialization in the factory.
   The current release already supplies identity-bearing intent, propagating callbacks,
   first-initiator serialization, distinct exceptional-exit causes and actual signal-call
   facts. No further shelf release or dependency update is a planned prerequisite.
   Verify these contracts at the adapter boundary, including a refused intent leaving
   the worker alive without a second cleanup stop. If investigation exposes an additional
   library defect, fix it at its owner and update both pins together only as needed.

   Persist the initiating condition and exact owned target before the tree stop, then
   the actual report and survivors afterward, on exceptional exits as well as normal
   returns. Cover deadline, watchdog/turn/policy stops, entry interruption, parent loss
   when enabled, and exceptional cleanup. Preserve the triggering entry signal separately
   from the signal sent to the agent. Copy attempted/delivered flags unchanged; neither
   grace time nor an intent proves delivery. Keep the stored first initiating cause
   aligned with the library's first-initiator rule.

   Translate library types inside the factory's agent adapter into generic typed values.
   Use stdlib enums for cause, initiating operation and record phase, and pydantic v2 for
   validated boundary records, with one codec per vocabulary. Carry attempt key, entry and
   agent boot/start identities, timestamps, cause, requested signal, observed signal result
   and available stop proof. Do not add a public product term or a new stop command.

3. **Persist across interrupted capture.** Add a bounded agent-stop use case and its own
   store under `src/taskloop/agents/`, with a dedicated `agent_stop` table whose SQL stays
   in that store. Wire it from composition and `Attempts._call`, using the already
   registered identities and attempt key. This record owns attribution; execution/status
   projections reference it rather than maintaining a second authoritative cause.

   Follow the outbox rule: commit stop intent in a short transaction, perform the owned
   library action outside the transaction, then record the report in another short
   transaction. Fence writes against stale dispatch/reservation generations and mismatched
   process identities. Keep the first initiating cause stable when concurrent watchers or
   repeated cleanup report the same stop; retain later escalation as a result, not a new
   explanation for why termination began. Bound callback writes and define failure behavior:
   a stop without a committed intent must not be issued; failure to record intent or prove
   completion leaves the attempt/reservation unresolved and surfaces the storage failure.

   Reconciliation observes identities and adopts completed effects. An intent alone does
   not prove a signal was sent. If its target still lives, keep it reserved and unresolved;
   reconciliation must not replay a kill, launch another agent, park the slot or manufacture
   a successful stop. An unknown liveness observation also preserves custody. An entry
   interrupted after its agent stops must leave readable cause data even if no normal
   `RunOutcome` or execution row was captured. A missing sender remains unknown; do not
   build a backup, log reader or history-reconstruction fallback for factory state.

4. **Make every relevant hold explain the stored cause.** Pass the typed attribution
   through `hold_facts`/`HoldFacts` to `hold_cause` and `hold_text`, including an entry-lost
   hold when interruption prevented execution capture. Bind it to the hold's stored
   `cause_id`, not a task's later attempt or current slot occupant. Keep ordinary result
   classification semantics, including deadline timeout versus a signal-only failure;
   attribution supplements the reason rather than encoding new colon-separated reasons.

   Example cause sentences: “The factory stopped the agent with SIGTERM because its
   attempt deadline expired”; “The entry received SIGTERM; its supervisor stopped the
   agent with SIGTERM. The sender of the entry signal is unknown”; and “The agent ended
   with SIGTERM; the factory has no recorded sender or stop cause.” An unconfirmed intent
   must say the stop was requested, not that it happened. Preserve SIGKILL escalation when
   known. Every emitted cause has an explanation tested at the adapter boundary. Reuse
   this projection for CLI/dashboard reads and tracker hold discussion; add no competing
   dashboard state. Keep arbitrary diagnostic text bounded and printable.

5. **Fix any unsafe lifecycle path discovered.** Adoption, rounds stop/restart and
   reconciliation have no authority to terminate live agents. If the trace finds such a
   path, remove that effect and correct ownership/cleanup at its owning library; merely
   labeling the kill is insufficient. In particular, cleanup for a short Git command or
   failed new launch must never target a surviving entry, another attempt, or an adopted
   slot's agent. Record a slot-operation/reconciliation origin if a concrete initiating
   call is observed, while treating that action as a defect. Do not introduce those
   destructive operations just to populate a list of cause values.

## Verification and delivery

Use focused pytest behavior/contract tests and owning shelf semantic fakes. Cover:

- Deadline SIGTERM (including an eventual SIGKILL), watchdog/turn stop and a signal-only
  failure with unknown sender; confirm initiating cause and observed signal stay distinct.
- Entry SIGTERM and SIGHUP during agent execution, including exception propagation before
  ordinary capture; reopen intact factory.db and produce the correct hold without logs.
- Crash after intent and after action, failed/busy writes, duplicate/racing callbacks,
  stale generations, PID reuse/other boot, unknown observations and surviving descendants.
  Confirm no signal action runs inside a write transaction and no recovery kill occurs.
  At the shelf boundary, a refused intent must cause neither the original stop nor an
  exception-cleanup stop. Test actual attempted/delivered flags independently of elapsed
  grace, including ESRCH/EPERM and an error before any signal call. Cover distinct entry
  SIGTERM, SIGHUP, Ctrl-C and exceptional caller exits rather than accepting `caller`
  as their only attribution.
- A live registered entry and agent surviving graceful/abrupt rounds stop and restart,
  repeated reconciliation, and `slot adopt --count 5` while other attempts run. Preserve
  their identities, claims, reservations, session and working files; launch no duplicate.
  Exercise known-slot adoption and adoption of an additional clean slot. Put any real
  process-ownership regression at the owning shelf layer, not in factory subprocess tests.
- A held attempt's cause remaining correct after slot reuse, and identical attribution
  in tracker text and CLI/dashboard projections. Check neutral text when no sender is
  known and prevent stale intent from being presented as a confirmed delivered signal.

Extend the relevant attempt-entry, restart, launch, slots, rounds, hold/store/text/status
tests; create small feature-local tests for the new stop use case. Do not add one test per
private helper or copy baseline runners. Retain 400/80/800 line caps, import isolation,
`one-signal-owner`, and the ban on factory subprocess or new signal-handling code.

A schema change requires draining running attempts before upgrade, preventing old
entry processes from writing the new schema, and discarding the old factory database.
Use the existing drain/version-refusal machinery; add no migration or compatibility
reader. Draining/upgrading a live installation is not part of this planning step.

For implementation, run `just install`, then focused tests through
`uv run --frozen --no-sync python -I -m pytest ...`. Finish implementation with passing
`just check` and `just test` (the declared focused successor gates), without adding
whole-suite/live testing. Completion requires the incident findings, durable attribution,
the lifecycle safety regression tests, and both passing gates. This plan alone claims
none of those implementation results.
