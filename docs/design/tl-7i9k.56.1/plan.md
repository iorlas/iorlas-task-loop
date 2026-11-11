# Retries, cooldowns and pauses

Task: tl-7i9k.56.1. Source review, 2026-11-08. Exact proposed contract for owner review; source remains unchanged.
Previously agreed constraints: bounded repair loops, every actual execution represented as an attempt, agent-owned
structured-output repair, factory workflow/budget ownership, local runtime state in SQLite, and explicit owner input.
The new numerical execution retry/delay policy below is a proposal, not a claim of prior owner approval.

## Structural strategy after Astra consultation

The owner requested further consultation on 2026-11-08. Selected working strategy: one factory-owned retry policy,
one shelf-owned agent interface, with native Python admission at the execution-start seam. This preserves the already
accepted automatic bounded structured-output repair inside the agent interface; it does not move repair prompts into
factory workflow or introduce a retry request/response service.

Before every actual agent execution, including the initial launch and each correction/replacement, the library calls
an injected attempt-admission operation. The factory implementation checks/persists allowance, applicable budget and
execution safety in its existing runtime store, then returns admitted attempt identity, denied, or wait. The library
never launches without admission. Use existing attempt/execution identities; no additional ID hierarchy is requested.
The shared library has no import of factory DB/application code; other consumers can supply their own admission policy.

An admitted immediate format correction can run automatically inside the same public API request. The library owns
validation, correction prompt, session continuation and launch details. A delayed recovery returns a typed wait to the
factory instead of sleeping for minutes and occupying execution capacity. There is no independent library retry
allowance or factory loop multiplying it. Resource unavailability is a wait, not a failed launch.

The library/harness can reconnect to or observe the same actual execution without admitting a replacement. A retry
that starts another execution must pass admission even if the harness calls it automatic. Where native harness
behavior cannot be exposed or controlled, report the actual limitation instead of claiming exact attempt accounting
or unsupported hard budget enforcement.

Expected completion, capacity waits, recoverable failure, cancellation, intervention and unresolved execution return
typed outcomes. An unexpected exception is an implementation failure, not proof of a transient network condition.
An exception after dispatch is not proof that no process started. Preserve execution references and reconcile before
launching another writer. Admission callback failure or uncertain acknowledgment never authorizes a bypass/retry.

Admission records intent, not atomic proof of an external launch. Library lifecycle reporting persists known start,
execution/session reference, usage and outcome during the public call, not only in its final merged return. On crash,
use the admitted identity and existing agent interface to observe/collect the same execution; no raw-log history rebuild.
An unresolved dispatch retains required ownership/fencing until resolved; a confirmed non-launch can release it.
This is an extension of the existing execution-start/reporting seam, not a new supervisor or distributed transaction.

The architecture does not depend on the specific 60/120/240-second proposal. The numerical section below remains
clearly proposed until accepted; implementation must have one finite explicit policy, not silently reuse several
legacy per-layer/per-reason limits. The already accepted three code-repair attempts remain distinct from failed
agent execution. All actual attempts/usage are visible and cumulative budgets persist across both.

## Responsibility and removal map

| Current behavior | Decision already governing it / proposed cut |
|---|---|
| loop.net_first reorders tasks after network returns | Remove under accepted priority contract. Retry readiness never changes ordering. |
| closing_decide reads trace files to count repeated faults | Remove runtime control from logs. Keep required counters in existing execution state; logs remain evidence. |
| Park combines text hash/question count with pause reason, timer and per-reason retry counts | Separate explicit outstanding work questions from local execution waits/counters. No duplicate question service. |
| beadpark requires text changes or --fresh to wake some capped tasks | Replace inferred text-change control with submitted response, released hold or explicit retry authorization. |
| LoopFiles.rest_doc/rests/rest_bead and LoopConfig.rest | Remove after final caller inventory. Current source search in src/packages finds no caller of rest_bead or LoopConfig.rest. Reading old local rest records is not a reason to preserve this feature. |
| Counters.later plus persistent Park.retry_at | One local wait owner; remove independent delay writes. Retain a derived cache only if needed and coherently invalidated. |
| delegate network waits up to 600 s and account polling/waits up to 180 s, then factory retries | Remove hidden long wait/relaunch ladders. Return explicit readiness/failure facts; factory owns when another execution may be admitted. |
| delegate schema re-ask and execution/session handling | Keep behind the one shared agent interface, bounded and counted against supplied allowance. No factory JSON repair prompts. |
| Generic file-first durable-module proposal | Retire that implementation shape. State is already SQLite-backed; no file adapter, fallback or general durable framework is needed. |

## Exact proposed behavior

### 1. Resource or account unavailable before execution

No agent execution starts and no execution-attempt allowance is consumed. Wait for the relevant workspace/tool/account/
provider condition; do not freeze unrelated work. Unity permits constrain Unity commands, not whole epics.
Retain the known provider retry_at if supplied. Readiness uses native status/permit APIs, not a model invocation.
For a timed retry that becomes eligible, normal priority selection applies. Waiting never grants a priority boost.
An existing active execution blocked in a tool call remains the same execution; its actual usage is still charged.

### 2. An actual agent execution fails transiently

Allow at most three automatic re-executions after the initial execution for one logical step occurrence: four actual
executions maximum. Count before dispatch, including failed launches; a factory restart observing the same execution
does not create a new attempt or consume another allowance. Changing account, reason or session does not reset it.

This allowance is for agent execution, not a generic retry wrapper around arbitrary side effects. Ordinary failed
checks follow the repair workflow, not a timed rerun-until-green loop. Git/task-service mutations use their existing
operation-specific proof/idempotence rules; an ambiguous write is inspected before repetition.

Ordinary transient retry delays are 60, 120 and 240 seconds, with no jitter or per-reason delay table. If the provider
supplies a later retry_at, use that later time. Both the delay and required readiness must permit dispatch. Admission
still follows the accepted priority contract. Known permanent/configuration/policy failures are not automatic retries.

The factory persists the allowance/counter and next eligible time through the existing execution-store seam. It passes
the remaining allowance to the shared agent interface; every additional interface-initiated execution consumes it and
is reported as a distinct attempt with session/outcome/usage. There is no extra factory retry allowance around that
interface. Native transport reconnects within the same surviving process are not new executions; supported time/cost
limits still apply. A stopped execution is proved ended before a replacement is launched; uncertain liveness blocks
replacement and reports the actual state.

On allowance exhaustion, stop automatic execution of the affected step and surface one actionable request/failure.
Do not restart planning or switch reason/model to acquire another allowance. Owner-authorized retry grants another
bounded allowance explicitly; task budgets are not reset. Successful step completion ends this execution-retry episode.

### 3. Malformed structured result

The shared agent interface can issue at most one immediate same-session format-correction execution during that
logical step occurrence. It consumes the same three-re-execution allowance; it is not an extra free launch.
If still malformed, return schema_invalid and stop automatic execution for that step. If there is no resumable
session, return that failure instead of pretending continuation is possible. A schema-valid failure, question or
rejection is a valid result and is not corrected into success. Factory never adds a second schema-repair loop.

### 4. Checks, review or integration conflict requires code repair

The existing accepted workflow returns to implementation with bounded evidence references. Allow three automatic
implementation repair executions after the initial implementation, shared across checks/review/land feedback in
the same failure cycle. A change of failure kind or moving between steps does not reset the repair counter.
The cycle ends when repair passes the required checks/review and integration succeeds, or the owner explicitly
authorizes a new bounded repair cycle. A successful intermediate check alone does not reset the cycle.

The execution retry allowance in rule 2 covers infrastructure failures during an operation; this repair counter covers
successful execution producing work that needs correction. A format correction does not count as an implementation
repair merely because it launches another execution. Both consume actual usage and the cumulative task budget.
All task/step/attempt/session links remain inspectable; no hidden retry tier is introduced.

### 5. Owner pause, unanswered question, invalid setup or exhausted budget

No timer automatically restarts this work. Wake only on the relevant explicit response, hold release, corrected
configuration/verified readiness or bounded owner authorization. Saving an unrelated comment or editing task text
does not waive a block or grant execution budget. --fresh means session/planning intent, not bypassing holds or limits.
Machine/account fixes remain local runtime conditions; portable requirements questions/responses remain in the task
service. Clear only the addressed condition, then re-evaluate all remaining eligibility conditions.

An intentional owner stop/park is never classified as a transient killed-worker retry. Code remains preserved.
An internal factory defect is reported without blind model relaunch based on a timer or a new fingerprint. Preserve
the real worker's state if it might still be executing; do not label it ended merely because the coordinator failed.
Normal restart still reattaches the same unfinished execution as rule 7 requires. Other eligible work may continue
where shared state/resources remain safe.

### 6. Broken workspace

Exclude the unsafe workspace until its deterministic health check succeeds or it is explicitly repaired/released.
Never wipe uncommitted work or launch an automatic repair agent as a scheduling side effect. Distinguish a broken
workspace/environment from task code failing setup. Available healthy workspaces are governed by their own safety
and branch/claim checks, not an arbitrary global cooldown for that task.

### 7. Restart and storage

With intact factory.db, retain current step/attempt/session, consumed allowances and pending waits. Reattach or collect
the existing execution before deciding another execution is necessary. Deliberate DB discard loses these local
records and normal workflow starts from portable Git/tasks; no log-based reconstruction. No clock or counter reset
is granted merely by a normal process restart.

Every wait has one explicit scope, reason and wake condition; a timed wait additionally has not_before. Scope is the
actual execution/resource/account or repository-qualified task, never an unqualified task ID assumed globally unique.
Store the minimum state through existing ports, not a second scheduler, event log or task database. One wait store can
record several independent conditions; clearing one must not falsely make all conditions satisfied.

## Source evidence and implementation prerequisites

Read loop NetState, Counters/candidates/Settle, LoopFiles rests, pipeline closing_decide/outcome policy, kernel
ParkStore/beadpark/accountpauses and delegate run_legs/_schema. Existing PauseRule maps distinguish producers and retain
known external stop facts; replacing tables must preserve meaningful classification rather than treat every failure alike.
Do not add another classifier for provider formats in factory: the shared agent interface owns those observations.

ParkStore currently keys rows by bead alone, despite a shared factory configuration. Joint RepoId/store review must
verify and remove any cross-repository ambiguity; this is a source-shape risk, not a reproduced collision.
Existing held STORE child tl-sqd3.26.2 owns overlapping storage work and remains held. Coordinate STEP-ATTEMPTS,
AGENT-CONTRACT, PORTABLE-ASKS and removal of legacy ordering. No new retry framework is requested.

No source tests executed for this design. Eventual fake clock/store/agent tests must verify: no launch while waiting;
exact retry count/delays; reason-switch cannot reset allowance; schema correction consumes allowance; worker survives
restart without double launch; manual stop never auto-retries; failure cycle does not reset between steps; partial wake
does not clear another condition; priority remains unchanged; and invalid state is reported. Use just check / just test.
