# Collect one already admitted plan attempt

Task: tl-8bh9.4.3.1.1. Status: source proposal reviewed; owning launch prerequisite outstanding, documentation only.
This is the application body consumed by a later surviving attempt-process entry.
It does not provide admission, an attempt-process launcher or a working plan command.

## Source and released prerequisites

The successor currently implements only help, repository inspection and task inspection.
Reuse `RepoId` from `src/taskloop/repo.py` and `TaskReference`/`TaskScope` from
`src/taskloop/task.py`; their values do not authorize execution. Follow the parent
[agent lifecycle](../tl-8bh9.4.3.1/plan.md), [one-shot plan](../tl-8bh9.3.2.1/plan.md)
and [STORE ownership](../tl-sqd3.26/plan.md). STORE .26.3 owns actual attempt/session
facts, .26.4 the specific unfinished dispatch/result actions, .26.5 reservations.
Implement only their rows consumed here, not those owners' entire table families.

Released any-agent0.3.0 was inspected at 9787eb9fba1025c7808fd310894e18e9fa05cb44:
`run`, `RunHooks.started/ref`, `RunOutcome`, `decode_answer` and `testing.FakeRun`
are the actual execution seam. Registered start and lock cleanup are already delivered.
Adopt any-agent at its0.3.0 tag; its inherited stream-proc0.5 resolves at that same
checkpoint. Do not add a redundant stream-proc source pin at its older release
checkpoint: the fresh-consumer check demonstrated uv URL conflict for that combination.

Integration review found a further concrete prerequisite in released0.3.0: Codex fresh launch_spec expects a
caller-built LaunchInputs.cli; empty cli omits exec and ignores its semantic model/effort/sandbox fields.
Factory source must not duplicate vendor argv construction. shelf-evlp owns the bounded repair of the existing
builder and removal of the raw cli override after a caller/removal assessment. Actual production calls to that
semantic builder remain blocked until its owning release is verified. This corrects the proposal's earlier
assumption that0.3.0 could already construct the fresh request described below.

Released sqlite-store0.1.0 was inspected at its exact peeled tag
18d3164893f95dc82e391a7226652d286d9c4663, not shelf development source. Its public
`Schema`, `Store.open_rw/shared_rw/open_ro`, `begin_immediate`, and `cas_update`
are sufficient. `Schema(version=1, ddl=..., steps={}, name="factory",
quarantine_versions=frozenset())` is the sole schema owner. No upgrade steps,
quarantine, old reader, restoration or compatibility import.

## Actual application calls and typed data

Proposed concrete public operation/reader (names remain implementation choices):

```python
@dataclass(frozen=True)
class AttemptKey:
    attempt_id: str
    dispatch_token: str
    reservation_generation: int

class PlanAttempts:
    def execute(self, key: AttemptKey) -> AttemptResult: ...
    def publish(self, pending: PendingPlanResult) -> PublicationResult: ...
    def collect(self, key: AttemptKey) -> CollectionResult: ...
```

The composition constructs this application with the narrow PlanStore owner, input/
evidence file reader-writer, machine-credential callable, injected time and the
existing four-positional-argument execution callable. Real composition injects
any_agent.run; tests inject released any_agent.testing.FakeRun. This is one factory
application implementation, not a second runner facade or lifecycle service.
`publish` is the same concrete result transition used by execute after return;
it lets the surviving entry retry that unfinished DB publication, never the agent.

AttemptKey is a selector/fence, not admission. Execute reads authoritative existing
attempt and reservation rows and their immutable input reference/options. Absent,
not-admitted, unregistered-entry, stale generation, wrong token, changed input or
unavailable/unusable storage refuses before agent/credential IO. A constructed
request or dataclass cannot insert an admitted row. This slice exposes no admission
writer. Tests seed the authoritative prerequisites explicitly with native SQL;
that fixture is not a production path to manufacture authority.

AttemptResult/CollectionResult are explicit typed variants: Refused(reason),
Pending(phase, accepted_facts), Collected(stored_result), Conflict(reason), and
Unavailable(operation). Execute can additionally return PendingPlanResult with its
specific unaccepted result/session input. That value is volatile, not a DB fact or
restart fallback. PublicationResult distinguishes accepted, already_same, conflict
and unavailable; only an accepted transaction acknowledges progress. Expected DB
errors never become missing rows. Unexpected programming faults are not successes.

Identity is the existing attempt + dispatch token + reservation generation. There
is no new ResponseId. Repeated collection returns the same stored terminal data;
it does not launch, parse logs, increment a result revision or create another attempt.

## Minimal schema and ownership

Use three concrete tables, with typed scalar columns, foreign keys, checks and
short conditional SQL. Do not store a generic RunOutcome JSON document.

| Table | Only facts this operation needs |
|---|---|
| reservation | slot key, RepoId, managed checkout path, generation and owning attempt id. Existence means held; this slice never releases/deletes/reassigns it. |
| plan_attempt | attempt id, task adapter/backlog/id, RepoId, slot/generation, dispatch token, immutable input file reference+digest, schema contract version, model/effort/sandbox options, deadline, already registered attempt-entry boot/PID/start identity, dispatch phase/revision, nullable harness boot/PID/start identity and initial pgid metadata, nullable native session ref. |
| plan_execution | unique attempt id + matching dispatch token/generation, captured execution facts, immutable evidence references, answer phase, validated answer summary when available. |

The attempt-entry registration is a prerequisite fact from the future registered
launcher. Its stored identity is not proof of current OS liveness or caller identity;
this slice does not manufacture either or claim physical restart safety. Atomically
consuming the dispatch phase below fences duplicate application calls. No ad hoc
second repository/task identity, event ledger, scheduler or table for future workflows.

Captured execution facts are explicit rc, timeout, stop, watcher category, measured
HTTP status if present, work/answered/stands evidence, existing classification reason,
reported native session, and nullable normalized Summary.res usage fields: tokens/cumulative
with in/cached/out, plus turns when reported. Vendor input_tokens/cached_input_tokens/output_tokens parsing
remains in the existing Codex harness; factory does not read the vendor wire format. Preserve existing classification and
answer-grace facts separately; do not derive a new success flag. Raw vendor/error/
secret-policy strings remain evidence files. Store only the selected existing
classifier category, not its freeform diagnostic detail. Codex cost remains unknown:
Summary.cost's default0 is not measured cost. No invented zero tokens or absent session.

Answer phase is validation_pending, valid, missing, json_invalid or schema_invalid.
A valid summary contains only disposition, expected plan path and reported commit
reference; freeform explanation and parser diagnostic text stay behind the evidence
reader. None establishes Git correctness or plan-step completion. Custody is always
reported unresolved by this slice, independently of result and answer state.

For all writes, one BEGIN IMMEDIATE transaction checks the attempt/token, admitted
input binding, registered entry and joined held reservation generation. Updates use
phase/revision predicates and exact immutable fact comparisons, not blind upserts.
No agent, file, credential, tracker or Git operation occurs inside that transaction.
The matching reservation is checked on every transition, not only the initial read.

## Dispatch, session and terminal transitions

1. Load and validate admission plus held reservation. Resolve/validate the exact
   immutable input through its owning reader before dispatch. Missing bytes or a
   digest/schema mismatch refuses; never search history or alternate files.
2. In one transaction change admitted -> dispatching only if its revision and all
   joined fences still match. This is the only path to the one execution call.
   A second caller sees dispatching/registered and returns pending, or collects an
   existing result. A lost dispatch acknowledgment is unresolved, never permission
   to repeat the agent. No process-liveness inference is made from these phases.
3. Obtain ephemeral machine credentials outside the DB transaction. Construct
   CodexHarness and its nonsealed LaunchInputs from authoritative immutable options,
   input bytes and managed checkout. The factory owns the schema and output path;
   no caller-supplied LaunchSpec can replace the stored admission. Compute positive
   remaining timeout immediately before the call. Expired admission refuses; never
   pass0 (the library's unlimited timeout). Check deadline again behind started's
   gate. Library timeout starts after spawn; do not claim a stronger absolute OS
   deadline guarantee than that API provides.
4. Call `run(harness, spec, remaining, RunHooks(started=register, ref=associate,
   unattended=False))` exactly once. The existing flag True watches this process's
   parent and stops work on coordinator death; explicit False is required here.
   register conditionally stores the complete boot-aware harness identity before
   target exec. Changed generation/DB refusal/conflict raises, keeping exec gated.
   Duplicate identical identity acknowledges already_same; another identity conflicts.
   Initial pgid is metadata, not immutable process identity or whole-group proof.
5. associate immediately attempts one conditional native-session publication while
   execution is live. Identical ref is idempotent; a different ref is a conflict,
   never an overwrite. It is bounded and nonraising into the library output pump:
   expected unavailable/conflict becomes explicit retained publication state. Keep
   the first unaccepted ref plus a conflict flag if another different ref arrives;
   no last-value overwrite, unbounded queue, retry thread or separate service.
6. After run returns, retain the returned raw execution in memory and write immutable
   stdout/stderr/answer/evidence bytes through the file owner. Then capture the typed
   execution facts and evidence references transactionally with answer=validation_pending,
   before invoking the typed PlanAnswer decoder. File failure or DB failure retains
   the actual returned facts as PendingPlanResult, without claiming they are durable.
   Do not erase an accepted worker/session or invent a terminal empty completion.
7. Invoke released decode_answer on the returned answer text with the factory's pure
   PlanAnswer decoder. Publish answer validity/selected summary conditionally against
   the same captured result. Expected malformed/schema-invalid/missing answer is a
   result, never a hidden correction launch. Decoder programming faults propagate
   with the captured result identity available; the DB still says validation_pending.
8. A subsequent execute on an already captured result may finish that explicit
   validation phase by reading its referenced answer bytes and using the same pure
   decoder, with no credential/agent call. This is not reconstruction from logs:
   DB-recorded captured execution and validation_pending authorize that bounded phase.
   Read-only collect returns captured/validation-pending or terminal stored facts;
   it never performs another execution or pretends missing artifacts are empty.

Publication compares the actual immutable facts and evidence references already
stored under that key. Exact re-publication is already_same, including after lost
acknowledgment; differing facts, evidence or answer summary are conflict, not replacement.
Terminal data cannot be rewritten by a stale publisher. Session conflict remains
visible even if the worker later returns an otherwise usable answer. Pending session
must be reconciled before reporting all required lifecycle publication accepted.

## Persistence, callbacks and files

Production connection acquisition uses released Store(schema) with an explicit
factory.db path and its per-thread shared writer. The pump does not reuse the main
thread's SQLite connection. Each ref callback makes one bounded attempt, with no
application retry. Released opens/SQLite busy handling have finite5-second windows;
that latency and existing pump behavior remain limits, not a hard real-time guarantee.
Pending ref/conflict input is held in a small per-execution synchronized value shared
with the caller after return. Unexpected callback faults are surfaced as retained
publication faults, never discarded as an apparently empty completion. No new pump
error-transport mechanism or whole process platform is introduced.

Input references/digests, request options, task/repo binding and schema version are
immutable admitted data. Credential environment is provided only in process by the
machine credential callable when actual execution is needed. Never persist that
environment, arbitrary argv, auth tokens, prompt/answer bytes or RunOutcome objects.
Prompt/input and raw output files are immutable artifacts behind narrow owning
readers; they are not alternative control records. Evidence failure does not clear
control rows or allow recreation of authority. No directory scanning or log parsing.

The file owner uses native Python and explicit paths/references, with separate
read-input, capture-evidence and read-answer operations; tests use real temporary
files. It does not infer completion. The pure PlanAnswer decoder accepts exactly
factory-schema fields: disposition (planned/incomplete/needs_owner), expected plan
path or null, reported full commit reference or null, and bounded explanation.
Planned requires the expected task plan path and a reported commit; Git verification
is deliberately later. Reject extra/wrongly typed fields with ValueError. The same
schema contract is forwarded via LaunchInputs.schema. Explanation is returned as
transient typed data/evidence, not a DB transcript or a stored authoritative plan.

## SQLite mechanics and focused acceptance

In-memory tests create native autocommit sqlite3 connections, enable foreign keys,
execute the SAME Schema.ddl statements in the released public transaction primitive
and set user_version=1. They inject these connections into the same PlanStore SQL.
They do not call Store.open_rw(":memory:") or claim in-memory WAL/opening proof:
released sqlite-store requires on-disk WAL. Public Schema and transactions suffice;
no unreleased sqlite-store helpers or factory fake database are needed. Real-file
open behavior stays in owning-library contracts; a focused factory composition check
can exercise normal opening without duplicating the library's mechanism suite.
Unversioned nonempty, incompatible, corrupt or unavailable storage refuses; no
migration steps, quarantine, deletion, backup restoration or fallback are configured.

Focused application tests seed one admitted/registered attempt and held reservation,
then use released FakeRun and native SQLite/files. Prove no agent call for missing,
stale, unregistered, changed-input, expired or unavailable admission; one winner for
contended dispatch; gate refusal before ref/result; immediate session publication,
duplicates, absent/late session and pending-first-ref/conflicting-ref preservation;
failed execution plus valid JSON; answer-grace/unknown usage; malformed answer with
one invocation; returned facts captured before decoder fault; idempotent/conflicting
result writes; and independent collection with zero execution calls. Native SQL
failures/closed connections exercise unavailable paths, not a helper fake DB.
Reopening an independent reader proves retained DB facts, not physical process restart.

Proposed source homes are a small plan application/typed decoder, its narrow SQL
owner and its file reader-writer, plus explicit composition. Split only to retain
400/80/800 caps; no empty ports/modules. Add tests to focused selection and read the
justfile before required `just check` and `just test`. No factory subprocess/spawn/
signal/wait usage, new Any/cast/ignore, baseline imports or copied test bootstrap.

## Explicit remaining gaps and review boundary

No CLI/admission producer, real task claim, physical attempt launcher, worktree/lock
preparation, Git verification/commit/publication, normal reservation release,
plan-step completion, scheduler or automatic retry is included. The useful result
is a real conditional application execution/publication/collection body, exercised
by an already-authoritative admitted fixture and real SQLite plus the released fake.
The later surviving entry owns actual process lifetime/custody and consumes this
body; this slice cannot advertise coordinator restart safety by itself.

DB loss before publication leaves only explicit volatile pending data while its
process survives. Losing that process leaves unresolved retained DB state; files
cannot reconstruct execution control. Existing ref/pump/drain limitations remain;
return or a dead leader is not descendant-stop proof. Every path retains reservation.
Approval of this proposal authorizes only its bounded source slice, not remote
publication, factory release, another workflow or broad STORE construction.

Known limits accepted after implementation review (not changed): finishing a pending answer validation in `execute`
needs the live reservation, because every transition joins the held reservation generation; only `collect` is
reservation-free. A registration-gate refusal (for example an expired deadline behind `started`) leaves the attempt
in `dispatching`: a lost or refused dispatch is unresolved, never permission to run the agent again.

Further accepted limits: `execute` on any stored non-terminal state (answer validation and a pending or fault session
publication alike) needs the live reservation; a stored pending/fault publication is upgraded only on evidence (a
recorded conflict, a reported session that publishes, or a session already accepted on the attempt), never emptily.
A credentials failure, a files or `launch_spec` failure and a run exception after registration each return a typed
result naming the cause. Since tl-8bh9.4.3.1.4 credentials, files and `launch_spec` resolve before dispatch, and the
deadline is re-checked right before it, so their failure or a deadline crossed meanwhile leaves the attempt `admitted`; a run exception after registration leaves it `registered` with the outcome lost.
The agent is never rerun by this body.
