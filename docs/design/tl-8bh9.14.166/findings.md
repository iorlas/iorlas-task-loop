# Signal attribution findings

Implementation inspection: 2026-11-14, source `ea7bbc650d38afcbfadb7b086018abfdaecad773`.

## Reported incidents

The supplied report identifies `.120` at 2026-11-13 21:37 UTC and `.148` at
23:16 UTC with return code -15. It does not identify the third occurrence.
That return code identifies SIGTERM, but does not identify its sender.

The retained current database at `~/.local/state/task-loop/factory.db` was read
read-only through `Store.open_ro`, `AttemptStore.attempts` and
`AttemptStore.collect`, using the source's original v21 schema before the v22
schema change. It contained 27 attempts, for `.165`, `.166`, `.172`, `.174`,
`.176`, `.177`, `.179`, `.183`, `.184` and `.190`. Neither incident's task was
present, and none of its captured executions had a negative return code.
`EvidenceFiles.round_tail` showed current 2026-11-14 rounds, not the incident
rounds. The older `~/.config/task-loop/factory.db` was refused by the owning
reader as schema v3. An `old-v20` directory also exists; no compatibility
reader, archive restoration or state reconstruction was introduced.

Consequently the incident attempt keys, registered process identities, admission
deadlines, execution timestamps and runtime revisions could not be recovered
from the compatible retained state. The incident runtime cannot be assumed to
be this branch's runtime. No historical process or worktree was operated on.
There is no proven historical sender, nor a third identifiable occurrence in
the inspected state. Proximity to adoption or a rounds restart is not evidence
that either sent a signal. This remains an evidence limit, not an attribution.

## Current signal paths

`launch.Launcher` uses registered start with a new session. A matching admitted
entry returns `AlreadyRunning`; an unknown observation refuses replacement.
A dispatched attempt is never relaunched. `interrupts` only stops rounds;
`rounds` ends scheduling. `slots.adopt` reads Git only for missing slot rows
and inserts those rows. It skips known slots, including reserved dirty slots.
`owned_processes` observes exact boot/start identities and process groups.
These paths contain no agent stop action. The lifecycle regression exercises
both rounds stop modes, intact-database reopen, repeated rounds and adoption
of five slots while an entry and agent remain registered and live.

The lockfile pins any-agent 0.11.0 and stream-proc 0.9.0 to shelf
`14bb4512c383c174d8db580d66d1c270aa656dee`. The installed code exposes the
identity-bearing `StopIntent` and the before/after callbacks described by the
plan. The supervisor serializes initiators. Before-callback refusal records
its refusal and prevents both the original action and exceptional cleanup.
The after callback runs after its report is retained, including entry signal
and caller exits. `caller_cause` distinguishes entry SIGTERM/SIGHUP,
KeyboardInterrupt, parent loss and other exceptional exits. The factory uses
`unattended=False`, so rounds parent disappearance is not a stop condition.
These contracts were inspected at the owning shelf code; factory tests use
semantic execution and callback boundaries, without spawning or signalling
processes.

Supervisor deadline, watchdog, answer/stall, policy, account, network and entry
exit conditions call the shelf tree stop. Its report copies actual attempted
and delivered signal-call flags; delivery means the kernel accepted a call,
not proof that this call caused the observed return code. Grace duration does
not establish delivery. The initial signal requested for an agent remains
separate from the signal received by its entry. Escalation remains a result
of the first initiating condition.

Git-porcelain 0.21.0 at `c6384f0bf870a430b7bffe826f9f42b6138d7d44`
runs timed Git reads in a new session and times out only that newly created
Git process group, with SIGKILL. Untimed writes use the ordinary command
runner. Stream-proc registered-start cleanup owns only its newly created
child; it never looks up an existing entry or slot agent to stop. Its
uncertain-start result preserves custody after permission may have escaped.
No current adoption/reconciliation cleanup path was found targeting a live
registered agent. No dependency change or new lifecycle stop operation was
needed.

## As built

`agents.stop` translates shelf callbacks into validated generic records;
`agents.stop_store` alone owns `agent_stop`. Bounded registration connections
also bound callback writes. Every write fences the dispatch token, reservation
generation, entry boot/start identity and registered agent's full identity.
Intent commits before the supervisor may act. Report commits afterward; a
callback failure propagates and leaves custody unresolved. A conflicting
initiator cannot replace the first cause.

Release's existing entry/agent/group proof preserves custody for live or
unknown observations. Once proven gone, reconciliation adopts that observed
effect in its own short transaction, without replaying a stop or inventing
signal delivery. Missing reports remain explicitly unconfirmed even after a
gone observation. Reported survivors are observed by boot/start identity even
when they left the original process group; a missing survivor identity keeps
custody unresolved. Process-proof functions were extracted to `release_proof`
to keep the release module within its file cap.

Hold discussion, CLI lines, JSON and the dashboard reuse `stop_text`. Holds
read the record by their stored cause id. Tests reopen an interrupted attempt
without entry logs or execution capture, then reuse its slot and verify the
original hold still names the original stop. Existing run classification
(including timeout) remains unchanged. The v22 schema uses the existing
incompatible-version refusal and drain-before-discard contract; this work
does not upgrade, drain or discard a live installation.
