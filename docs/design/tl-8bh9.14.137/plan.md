# Repair an invalid agent answer in the same session

Task: tl-8bh9.14.137. Proposed 2026-11-14 against `99655d38`.
This is a plan for owner review. Implement only after the owner's yes. No runtime change is made here.

## Problem and scope

An implement answer with `disposition: incomplete` and 96 paths satisfies the JSON schema but violates the
decoder's rule: only `implemented` may list paths. Today `implement_step.decode` raises only
`ValueError("Invalid implement answer")`; `Attempts._validate` turns every non-JSON rejection into
`schema_invalid`. The task holds without giving the agent a chance to fix its answer. Plan answers containing
prose instead of JSON lose their work in the same way.

Give an invalid answer exactly one repair execution in its existing agent session before an answer-related
hold. Send the exact typed failure, its explanation in words, and the current step's complete answer contract.
If the repaired answer remains invalid, hold with its specific broken rule. One repair is the acceptance
requirement; do not add a second repair, a configurable budget, or a whole-step restart.

The motivating evidence is the owner's description and
[the second self-hosting reflection](../self-hosting-real-run-2.md), especially failure scenario 3. The owner's
2026-11-14 analysis attributes 10.84M tokens to two rejected implement answers and another 2.53M to two plan
JSON failures. These are reported observations, not measurements made by this planning turn.

## Current boundaries and prerequisite

- Both `plan_step.py` and `implement_step.py` own their pure answer decoding, bounds and cross-field rules;
  `steps.py` is their only importer. Strict schemas intentionally omit those cross-field constraints.
- `attempt.py` captures execution facts and evidence before decoding. `AttemptStore.answer` is write-once;
  replacing the first execution's answer or worker would break that model.
- `agents/launch.py` creates a new session for every launch. `session.py` registers native session references;
  registration and collecting stored results are not agent-session continuation.
- `repeat.py` and `admit_chain.py` currently repeat only Git leftovers with a fresh session. Their admission
  requires a valid committing/keeping answer, so an invalid answer cannot simply enter that route.
- `attempt_result.py`, `hold_cause.py`, the database codec and dashboard words currently lose or generalize the
  broken rule. The database is schema 20 at this revision.

Session continuation is the prerequisite owned by **tl-8bh9.14.128**. Consume its explicit resume operation,
opaque stored session reference, launch reconciliation and harness capability result; do not invent a parallel
resume implementation or construct backend command lines in factory code. Recheck that task's implemented
interface before coding this integration. If it is not available, implementation waits for it; this task must
not silently start a fresh conversation. The local tracker used for this planning turn could not resolve
`.137`, `.128` or `.173`, so their additional tracker discussion was unavailable.

The [accepted execution model](../execution-terms.md#attemptsession-cardinality) and glossary count a new harness
execution as a new attempt, even in the same session. The repair therefore has its own attempt, worker, evidence,
timing and usage. It remains in the same task, step, session and reserved slot. A factory restart collecting an
existing execution does not create an attempt or replenish the repair allowance.

## Typed failures and names proposed for approval

Replace the misleading `schema_invalid` classification with **`contract_invalid` plus a typed rule**. Serialize
the terminal reason as `answer:contract_invalid:<rule>` so the reason itself names the violation. For example,
`answer:contract_invalid:paths_disposition` means: “Only `implemented` may list paths; `incomplete` must return
`paths: []`.” Keep `json_invalid` and `missing` as distinct answer failures with their exact explanations.

Alternatives considered: retaining `schema_invalid` continues to misdescribe cross-field failures;
`rule_invalid` alone still omits which rule and describes structural failures poorly. The proposed classification
and rule identifiers are code vocabulary for owner approval with this plan, not new glossary entities.

Use an enum for the answer classification and an enum for the closed set of contract rules. Initial rules cover
object shape/keys, disposition, paths type and bounds, allowed/duplicate paths, paths versus disposition,
message versus disposition and message bounds, explanation type/length, and the plan's expected path and its
presence in a `planned` answer's paths. Give each rule a stable field location and nonempty explanation; shared
rules have one owner, and step-specific rules remain with their step. Choose deterministic validation order,
reporting the paths/disposition violation before other cross-field failures in the motivating answer.

Use a pydantic v2 model for the persisted/interchanged failure: typed classification and rule, field location,
expected condition and actual offending value or bounded description. In-process decoding raises or returns a
typed rejection carrying that model. Keep strict JSON parsing at the owning agent boundary and preserve the
typed rejection through its callback/result instead of discarding it in the current `InvalidAnswer` mapping.
Do not parse exception text, display words, transcripts or logs to recover a rule. Unexpected decoder faults
remain implementation failures, not repairable agent answers. JSON syntax errors retain their parser location
and explanation as data, without embedding an unbounded copy of the answer in the repair prompt.

Do not relax any accepted-answer constraint or add a second validation implementation. The step exposes its
schema and complete rule text through `StepKind`; initial instructions and repair instructions use that same
source. Coordinate the explicit paths/disposition wording with tl-8bh9.14.173 rather than maintaining two copies.

## One repair before holding

1. Capture the first execution and validate its answer as today, retaining the typed failure and original answer
   evidence. A cleanly completed execution with missing JSON, invalid JSON or a contract violation is eligible.
   Valid answers, including valid `incomplete` and `needs_owner`, follow their existing handling without a repair.
   A process failure, timeout, unknown execution state or decoder bug does not become an answer repair.
2. Before the normal hold decision, the shared application operation checks the complete session registration,
   current reservation/claim, stopped-worker proof, remaining deadline, continuation capability and unused repair
   allowance. Unknown liveness or launch state waits for reconciliation. No competing worker may start. A missing,
   conflicting or unresumable session or an expired deadline prevents repair; any resulting hold names the answer
   failure and explains the particular reason continuation could not be made.
3. Admit a single successor attempt through the continuation admission supplied by `.128`, atomically transferring
   the reservation and recording the source attempt, source failure, repair input reference and allowance consumed.
   Copy the admitted model, effort, access policy, tracker root and original deadline. Keep the slot's dirty work
   and the step's original base and commit history; run neither setup nor task-branch preparation again.
4. Resume the recorded session with the repair prompt below. Preserve both executions' evidence separately. Do not
   overwrite the original answer, invent a successful answer, or commit any files on the strength of invalid paths.
5. Validate the new answer with the same decoder. A valid committing/keeping answer proceeds through the normal
   commit and verification operations; valid `incomplete` or `needs_owner` follows the normal hold for that
   disposition. A still-invalid answer holds once with the latest typed failure, specific rule and the fact that
   the one repair was used. Further rounds and restarts cannot retry that refusal.

The prompt says, in substance, with values filled from typed data:

> Your previous answer broke the answer contract. Rule: `paths_disposition` at `paths`.
> Only `implemented` may list paths. You answered `incomplete` with 96 paths; that disposition requires `paths: []`.
> This is your one repair turn in the same session. Return one corrected JSON answer for the work already done.
> Keep the disposition truthful: list files and a commit message only if the work satisfies `implemented`.
> [The step's current schema, all decoder rules and task-specific bounds follow.]

For invalid JSON the same frame includes the exact parse error/location and the instruction to return JSON
without surrounding prose. Include the full applicable contract, not just its JSON schema: required fields,
dispositions, null/empty values, path scope and limits, commit-message rules, explanation limits and plan-path
requirements. Do not tell an incomplete agent to claim completion or remove useful work merely to pass decoding.
The original requirements remain in the session; this turn corrects its answer, without authorizing broader work.

## Durable state, integration and recovery

Keep this policy in one bounded answer-repair use case, invoked by the shared continuation/hold decision used by
CLI starts and rounds. Read-only collection and dashboard reads never launch agents. Keep SQL in the owning
attempt/admission stores. Store the typed failure, immutable source/successor relation and one-repair limit in
factory.db; files contain only evidence and the digest-addressed prompt. Do not derive the budget from event files
or from a counter that resets on restart. A repair execution is another numbered attempt, but its one-repair
allowance must not accidentally spend or reset the existing Git-leftover repeat allowance. Returning to the
ordinary verifier must preserve every earlier commit and its paths; invalid-answer attempts add no commit to that
chain. A repair cannot evade the original base, path rules or whole-step commit-chain checks.

Follow the transactional outbox rule: record the continuation intent under a short fenced transaction, perform
the external launch outside it, and record the observed result under a second transaction. Use `.128`'s owning
launch reconciliation to adopt an execution after an ambiguous acknowledgement; never infer “not launched” from
missing output. On intact-database restart, finish pending admission, dispatch, capture or validation before
considering another action. Concurrent callers must resolve to the same successor; holding or abandoning fences
stale writers. Preserve the current drain behavior at admission and launch.

Likely integration files are `attempt.py`, `steps.py`, both step decoders, the owning attempt/admission stores and
row codecs, continuation composition from `.128`, `attempt_result.py`, `hold_cause.py`, and dashboard presentation.
Put the new use case, typed models and prompt formatting together in a feature folder; do not grow `attempt.py`
past its caps or introduce a general retry service. Existing modules consume the typed result through narrow ports.
The agent adapter retains backend-specific capability errors and supplies the generic explanation to the factory.

Replace every active `schema_invalid` writer/reader and presentation expectation in one cut; do not reinterpret
old rows through a compatibility reader or retain a legacy alias. Updating the stored vocabulary and continuation
state requires a schema-version increment from the then-current version. Drain old attempts before upgrading and
discard the old factory database only through its authorized owning operation, as repository policy requires.
The new version then supports intact-database recovery. This repair does not hot-swap contracts or code in running
processes: future contracts benefit from the same mechanism after a normal approved upgrade and restart.

Hold text, CLI results and dashboard details show the same typed rule explanation and whether repair was used or
could not run. The factory's message states what happened and its decision in words; it does not ask the owner to
run a CLI command. Keep original and repaired evidence reachable without using evidence files as control state.

## Focused acceptance and verification

Use pytest behavior tests and owning semantic fakes, without live agents or direct process APIs:

- The exact regression: an `incomplete` implement answer with 96 paths is structurally valid JSON, rejected with
  the typed paths/disposition rule and explicit explanation. It is never called a schema violation.
- A corrected answer after one continuation uses exactly the original native session and admitted settings,
  keeps work already in the slot, and reaches normal verification/commit behavior. Cover both plan and implement.
- A second invalid answer, including a different broken rule, holds with that latest rule after exactly two
  executions total. Repeated rounds/starts and restart cannot add a third execution or duplicate the hold.
- Prose/invalid JSON and missing answers get the same bounded repair; the prompt contains the exact failure and
  the complete current step contract. Valid answers use one execution; valid `incomplete`/`needs_owner`, process
  failures, timeouts and unexpected decoder faults do not spuriously request repair.
- Unavailable/conflicting sessions, unsupported continuation, deadline expiry, stale reservations, claim loss,
  drain and unknown/active workers do not start a fresh or competing session. Explain a refused repair and keep
  unobservable states pending for reconciliation.
- Crash/reopen tests cover intent before launch, launch with lost acknowledgement, captured answer before
  validation, and validation before successor/hold completion. Assert one successor and one consumed allowance,
  preserved evidence and separately attributed usage. Include two callers racing to request repair.
- A repaired committing answer still encounters the existing unsafe/ignored/uncommitted and commit-chain rules;
  repair does not weaken those checks or reset their repeat cap. Every contract rule has a nonempty explanation,
  with focused representative failures rather than a test for every private helper.
- Store/result/presentation contracts round-trip the new typed failure, remove active `schema_invalid` wording,
  and show the same specific rule in CLI/hold/dashboard. Collection and dashboard reads perform no launch.

Extend the existing focused contracts in `tests/steps/test_answer_contract.py`, `test_attempt.py`,
`test_agent_launch.py`, session/admission/repeat tests and `test_hold_text.py`; add focused repair-use-case tests.
Include `tests/cli/test_dash_words.py` where the public labels change. Tests import only the relevant slice and
small shared types; do not bring back baseline test bootstraps or launch real harnesses.

For implementation, read the then-current justfile, run `just install`, and run the changed focused pytest files
through `uv run --frozen --no-sync python -I -m pytest`. Run the required `just check` and `just test` gates. The
current `just test` recipe selects all CLI/steps/rules tests: supply a focused `PYTEST_ADDOPTS='-k <behavior selection>'`
for that gate, covering the acceptance tests above and relevant existing regressions, and report the exact
selection. Do not run an unfiltered whole-suite or live test gate as an agent.
Respect Python 3.15+, source/function/test-file caps, import boundaries and no new type escapes. No runtime tests
are needed for this plan-only change.

Completion requires an approved plan, the `.128` prerequisite, the typed rule rename throughout active consumers,
one durable same-session repair, a rule-specific hold after an invalid repair, and passing focused gates. A plan
commit alone does not implement or complete this task.
