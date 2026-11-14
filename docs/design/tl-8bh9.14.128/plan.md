# Depth
Small: the supplied task requests one behavior in the session lifecycle owner: resume the existing unfinished agent session after restart with intact factory.db. No owner decision is missing for planning and no dependency is explicitly unlanded; tl-8bh9.3.4 is context for the deferred capability. Evidence budget: 6 model calls total. Implementation waits for the owner's yes, as required by the task.

## Size
Estimated changed files: 22, including this plan, up to 14 source modules and 7 focused test files or fixtures. Estimated model calls for one implement attempt: 85.

Independent behaviors: 1. After a rounds process is killed and the factory restarts with intact factory.db, unfinished work with a recorded agent session continues that same session after process liveness reconciliation, retaining its task, step, attempt and slot. Acceptance: a focused restart test records session S, interrupts execution, reconstructs the application against the same database, and observes continuation of S and normal completion without a fresh session or duplicate execution. Crash-boundary, liveness and refusal cases below are safety cases of this behavior.

The text-only Depth assessment remains small; implementation crosses existing scheduling, execution and storage boundaries. The estimate includes those integration changes. No schema version change, drain command, release runner or task-factory completion is included.

## Scope and evidence
The supplied glossary governs task, step, attempt, session, slot, harness and factory; no additional terms are needed.

At source commit 3a710fef99b4558645d292d279eb2d84802103dd:

- `agents/launch.py` always supplies a newly generated session to `LaunchInputs`.
- `attempt.py` only dispatches an admitted attempt. Its existing `_resume` finishes captured results; it does not continue an agent conversation.
- `session.py` records native session references through the registration and result paths. The attempt database already owns session references and process identities.
- `round.py` relaunches admitted entries, but reports other unsupported next actions. Existing round tests expect lost dispatched entries to remain `stuck:entry_lost`.
- `factory_schema.py` treats interpretation changes as possible schema-version changes and states that discard loses execution progress and session references. Recovery must operate on compatible existing database records; it must not require discarding the very database being recovered.
- Appendix R of the architecture review records session resume as deferred. This task authorizes planning that capability; it does not authorize its implementation before the owner's yes.

## Read list
Start implementation with these bounded windows and the named symbols. Follow direct imports only where needed to implement or test recovery; use the committed code map for additional ownership lookup. Do not read the foundation plan, full glossary, unrelated plans or whole test suites.

| File | Initial lines | Purpose |
| --- | --- | --- |
| `src/taskloop/agents/launch.py` | 75-120 | `AgentLaunch.build`, session construction and harness boundary |
| `src/taskloop/attempt.py` | 75-145, 175-285 | Existing dispatch, captured-result completion and execution hooks |
| `src/taskloop/session.py` | 1-120 | Session registration, latch and reconciliation |
| `src/taskloop/attempt_types.py` | 120-205, 270-310 | Persisted attempt, session and execution inputs |
| `src/taskloop/attempt_store.py` | 1-160 | Conditional dispatch and registration writes; locate remaining owning methods by symbol |
| `src/taskloop/attempt_reads.py` | 180-245 | Existing attempt and session reads |
| `src/taskloop/attempt_status.py` | 35-100 | Shared status types; locate next-action calculation before changing it |
| `src/taskloop/round.py` | 205-270 | Existing attempt handling and relaunch fences |
| `src/taskloop/attempt_entry.py` | 160-240 | Entry execution and collection lifecycle |
| `src/taskloop/launch.py` | 120-160, 190-255 | Owned entry launch and identity checks |
| `src/taskloop/factory_schema.py` | 35-120 | Existing schema, revision and process/session fields |
| `src/taskloop/hold_text.py` | 100-115 | Interruption wording affected by continuation |
| `tests/steps/test_round.py` | 190-265 | Existing lost-entry and relaunch expectations |
| `tests/steps/test_attempt.py` | 245-300 | Captured-result recovery regression coverage |
| `tests/steps/test_agent_launch.py` | 1-100 | Harness launch contract test conventions |
| `tests/steps/test_attempt_entry.py` | 490-535 | Bounded entry recovery tests |

Inspect the declared any-agent 0.11.0 interfaces for native continuation through its owning source/documentation, restricted to launch inputs, session reference handling and supported harness continuation. Do not infer that supplying a fresh-run session field resumes a conversation. Keep harness-specific commands and failures inside the adapter. If native continuation is unavailable, report the concrete capability gap and reassess scope before introducing a dependency upgrade.

## Proposed implementation
1. Add a typed recovery operation in the session feature, shared by round execution and existing entry/application consumers. Read the current attempt, captured result, session reference, reservation, claim and owned process identities from their owning ports. Reconcile actual liveness before deciding whether execution may continue. A living entry or worker is observed rather than duplicated; uncertain liveness remains pending with an explanation. A reused pid is not the old process. Collected successful work proceeds through existing collection and verification without another agent call.
2. Recover only unfinished, current, unreleased work with a consistent native session reference and confirmed absence of its previous execution. Preserve task, step, attempt, slot, task branch, worktree changes and pinned attempt settings. Do not repeat preparation that resets the worktree or recreate setup already completed. A normal step retry remains a fresh session. Explicit holds, abandonment, terminal task decisions and released reservations remain authoritative. Missing or conflicting session references produce a typed explanatory outcome; never silently replace the conversation.
3. Record continuation intent with a short conditional store transaction using the existing revision, entry and reservation fences. Perform process launch outside the transaction through the owning launch API; record the observed entry/worker and result in a second short transaction. Reuse existing durable attempt fields and launch reconciliation where their semantics permit. Establish how a crash before spawn, after spawn and before registration is distinguished using observable owned process identity; do not reset dispatch state blindly. Competing rounds must converge on one execution. Keep SQL within the slice's store. If existing fields cannot express a safe compatible transition, stop and identify the concrete schema conflict instead of incrementing a schema version or inventing file-based state.
4. Extend the agent adapter with an explicit native continuation input using the saved session reference. Preserve the attempt's harness/model/access choices and answer contract. Supply bounded continuation instructions explaining the interruption and retained work, without replaying the original assignment as a new session. Session registration must continue to confirm the same native reference. Preserve earlier evidence and make command/event identities distinct across execution continuations through the existing evidence and command readers; evidence is never a source of control state.
5. Route eligible restart recovery through the existing round/entry lifecycle and composition root. Use typed outcomes with explanations; encode any new closed vocabulary once at its boundary. Shared CLI/dashboard status reads reflect the same recovery facts. Update interruption wording only where it would falsely say an eligible session cannot continue. Recovery remains bounded by current scheduling limits; if the old execution deadline expired while the factory was down, acquire a new bounded execution allowance through the current round's existing minutes input and persist it before launching. Never grant an unbounded runtime or revive terminal/held work to renew a deadline.

## Focused verification
Use pytest functions and semantic process/harness fakes through the owning ports. No direct subprocess or signal calls in factory source or tests, and no live harness or whole-suite agent run.

- Restart scenario: start unfinished execution with session S, simulate the rounds process being killed using the owning process fixture, reconcile whether its entry survived, and reconstruct application objects against the intact database. A surviving entry is observed; a confirmed stopped execution continues S. Drive the continued execution through capture and normal verification to completion. Assert session identity, retained slot changes and absence of a fresh-session launch.
- Crash matrix: interruption before continuation spawn, after observable spawn, after registration and after capture; a second restart adopts an existing execution or finishes collection. Assert one live execution, one accepted result and no duplicate delivery action.
- Safety matrix: living worker with dead entry, unknown liveness, pid reuse, missing/conflicting session reference, competing recovery callers, changed reservation, expired deadline, explicit hold and abandonment. Assert bounded behavior, preservation of ownership and an explanation for every refusal or wait.
- Adapter contracts: supported harnesses receive their native continuation input and unchanged session identity; initial execution and normal retries retain their existing fresh-session behavior. Captured-result recovery continues without credentials or agent execution as before.
- Persisted compatibility: an unfinished record created by the pre-change schema is recovered without changing the schema version, discarding factory.db or reconstructing state from logs.

After the owner's yes, implement and run `just check` and the focused `just test` selection supported by the installed project environment. Inspect gate selection before invoking it; do not run a whole-suite or live test target. Run installed application smoke checks only after `just install`, using `uv run --frozen --no-sync python -I -m taskloop ...`. Record exact commands and results in the implementation handoff. Planning does not run implementation gates.

## Completion
The killed-rounds restart scenario passes with the same agent session and compatible intact database. Safety and crash cases pass without duplicate execution or loss of retained work. Focused gates pass, and no drain command, schema upgrade, factory-state fallback, glossary term or new scheduling subsystem is introduced. This saved plan is reviewable design; implementation still requires the owner's yes.
