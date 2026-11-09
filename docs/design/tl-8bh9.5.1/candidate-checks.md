# One check pipeline, candidate-bound evidence

> STORE scope update, 2026-11-09: Denis accepted the identity/lifecycle contract and lifted its design hold for
> [reconciled STORE slices](../tl-sqd3.26/plan.md) only. Earlier blanket-hold statements below describe prior review history.
> Explicit dependencies still gate affected actions; historical migration/compatibility scope and unrelated holds remain excluded.

Follow-on review 2026-11-09 under tl-8bh9.5.1. Owner authorized an Astra sanity pass for each new topic. This document
records the assessment and its subsequent owner approval. Earlier proposal/pending wording below preserves the review history;
the following decision is authoritative.
No source, task priority, check command or configuration changed; no live or full test suite executed.

## Owner decision, 2026-11-09

Denis approved the proposed check-pipeline simplifications and the discussion roadmap: remove historical successful-check
caching and carry-forward/closure proofs, agent run_checks/requestable/request-feedback machinery, separate stage/gate/both
selection and unnecessary routine prechecks. One shared validation operation owns the mandatory configured check set.
Keep ordinary focused debugging, current-workflow completed validation evidence, repository-owned affected-test selection
and existing incremental tooling. This does not approve enabling or expanding the optional repository successful-test ledger.

Remove automatic base-red replay/pass exemptions and the unchanged-input exemption for unavailable required checks.
Required failure blocks delivery; missing capacity is a typed wait. Preserve actual capture/build prerequisites.
Keep checks -> acceptance/code review -> land. A changed candidate/integration context needs validation; simply advancing
steps does not repeat completed validation. Intact-DB restart reconciles running commands before continuation/relaunch;
an incomplete block may repeat after confirmed stop. Discarded DB/new PC repeats normal validation.

No generic cache replacement is planned. Revisit successful-check caching only if real use demonstrates a concrete need.
This approval settles design scope; no source changes have been made and implementation tasks remain open.

## Retained workflow

Keep implement -> mandatory checks -> acceptance/code review -> land. Preparing integration before every check was
considered during consultation and withdrawn as an unnecessary default workflow change. One shared validation
operation serves the checks step, standalone CLI and necessary integration revalidation.

When land produces a different integration candidate, validate the new candidate and relevant review implications
before delivery. Entering land alone does not require rerunning an unchanged candidate's completed checks. Repairs
or conflict resolution change the candidate and require their normal checks/review. No evidence from another or
unverified candidate counts as completion.

Use a short conditional target update/push against the expected target revision after validation; do not hold a
global integration lock across long checks or review. If target changes, refresh the merge-only candidate and run
the necessary validation. No speculative merge queue is introduced. Target movement alone does not consume the
three semantic-repair attempts; actual conflict/code repair does. Active refresh/check/review work consumes the
cumulative task time allowance, so target contention cannot produce unbounded work. Stop at exhaustion with the
real contention reason/evidence; do not add another unlimited retry loop or independent retry counter.

## Proposed check-model cuts

- Remove run=stage|gate|both. One configured mandatory check set applies at formal candidate validation; caller/input
  context differs without creating a second independently selected registry or timeout policy.
- Remove the agent run_checks/requestable/request-feedback protocol and its admission/cap/state/prompt branches.
  Ordinary focused debugging stays available through normal tools; mandatory checks do not depend on an agent request.
- Planning inspects requirements/capabilities without routinely running build/test suites. Writer prompts stop
  requiring a full duplicate check run; review reads evidence and investigates only for a concrete reason. Dedicated
  visual prechecks belong to already approved visual-only workflow removal, preserving actual tool prerequisites.
- Repository tooling owns affected-test selection, compilation/test diagnostics and needed clean-build behavior.
  Remove C#/Gherkin counting/parsing, command-name queued/build guessing and lock-text-derived scheduler policy.
- Keep a small ordered command specification: identity, argv, necessary environment/setup, explicit prepared/fresh
  workspace, resource needs and optional narrower timeout. Preserve genuinely needed dependencies by declared order;
  do not recreate a general CI/build DAG, report DSL or check-request framework.

Task-specific validation normally enters as committed project tests discovered by the repository suite. Where needed,
use an explicit repository-owned command through normal check configuration. Do not execute commands extracted from
acceptance prose or Markdown plans. Review determines whether acceptance has been demonstrated; missing proof becomes
ordinary bounded repair or a necessary owner decision, not another hidden check-request protocol.

## Exact proposed outcome routing

| Result | Next behavior |
|---|---|
| Required checks passed for current candidate | Review that candidate and evidence. |
| Completed command fails | Return output/evidence to implementation under shared semantic-repair allowance. |
| Command timeout | Preserve typed timeout; diagnose via existing bounded repair if task time/repair allowance remain, otherwise stop with actual exhaustion. Do not claim timeout proves code innocence. |
| Known unavailable capacity before command starts | Typed wait, no semantic repair consumption or false pass. |
| Owner cancellation | Preserve cancellation/code and apply owner hold/stop policy. |
| Launch failure, unresolved completion or missing required evidence | Unverified; no delivery. Do not launch duplicate workers or infer success. |
| Validation command changes tracked files | Candidate no longer validated; formatting/generation that changes tracked content completes before candidate validation. |
| New profile, repair or integration inputs | Assess the resulting candidate with its exact profile and workspace context. |

Current CheckRound treats a timeout as certainly not a code issue; deadlock/infinite-loop cases disprove that statement.
Keep timeout distinct from ordinary nonzero exit without inventing a separate timeout repair budget.

## Earlier cache decision, superseded by owner approval above

Astra initially proposed deleting generic cross-run pass caching in the successor. That was challenged because the
owner approved reducing duplicate invocation sites and inspecting the remaining benefit, not blanket cache deletion.
At that point retention/removal remained undecided. The subsequent owner decision above now approves removal.

Always retain candidate-bound completed validation evidence: actual candidate/target context, resolved check/profile,
workspace mode/provenance and outcomes. This serves current workflow completion; it is not a general reusable pass
for unrelated runs or uncertain recovered environments. Repository-owned incremental caches are separate. Do not
rebuild generic pass caching under another name just to retain the current candidate's completion record.

## Evidence and implementation boundaries

Read runner/specs/plan/authorization/attempts and CheckRound/WriteRound/briefing. Current source has separate stage/gate
registry selection, requested informational checks, test-count diagnostics and red/round counters. Existing just check
and just test remain the required verification commands; no full-suite substitute. Execution/routing tests use shared
library fakes, with real mechanisms tested by owning libraries. Nested deadline/termination capabilities have not been
fully verified and must not be claimed as already implemented.

Coordinate PROFILE-SURFACE, timeout consolidation, agent admission, semantic repair and native Git ownership. STORE,
MQUEUE and future review modes remain held. These are recommended implementation cuts awaiting owner selection.

## Follow-up assessment: recommend retiring historical pass reuse

Review 2026-11-09, following the owner's explicit request to assess duplicate execution and caching with Astra.
At assessment time this was a new recommendation awaiting owner selection; earlier approval to remove repeated invocation sites did
not approve cache deletion. Read the source again in this review worktree; no representative Unity run histories
or measured savings were obtained. Entry-point counts and CheckStart/CheckEnd counts are not subprocess counts.

### Where work can repeat

| Site | Source and behavior | Recommendation |
|---|---|---|
| Planning | `packages/work/src/tlwork/plan/probe.py`, AcProbe: up to three registered stage checks named in acceptance run on the base, subject to runner reuse. Arbitrary acceptance commands are only looked up. | Remove routine build/test execution during planning. Capability inspection remains. |
| Writer | `packages/work/src/tlwork/write/briefing.py`, where: explicitly requires fast checks before completion and says the engine reruns every check. | Remove blanket requirement; retain focused debugging through ordinary tools. Agent-reported checks do not complete the mandatory checks step. |
| Visual loop | `packages/work/src/tlwork/look/judge.py`, look_step: static checks before rendering, followed by normal checks. | Remove with agreed dedicated visual-loop retirement; preserve real build/capture prerequisites. |
| Mandatory validation | `packages/work/src/tlwork/write/check_round.py`, go: stage checks plus planned acceptance checks, followed by a separate requested-check block. | One mandatory configured set. Remove informational request protocol and its state/schema/prompt branches. |
| Review | Generic non-writer briefing permits tests/lint. Permission is not evidence of an actual repeated command. | Review reads check evidence; targeted investigation needs a reason. |
| Failure diagnosis | `packages/gate/src/tlgate/base.py`, BaseCheck: on failure may execute the command on a clean base to classify an existing failure. | Distinct diagnostic, not routine duplication. Recommend removing automatic base replay and pass exemption; evidence can guide focused diagnosis, but a required failure still blocks delivery. This additional cut is proposed. |
| Land / stack delivery | `packages/land/src/tlland/gate.py` and stackgate.py: resolve evidence, then execute when unproven; stack delivery can carry a pass across a base move. | Share validation operation and current completion record. Same completed candidate does not rerun merely because delivery starts; changed integration inputs require validation. |

The repository profile currently declares only suite = `just gate`, run=gate. It does not configure the same suite
as both a stage check and gate check. Therefore generic support for repetition does not establish that this repository
runs its full suite at every entry point. Its `just gate` intentionally composes static checks and affected tests;
those two checks are not duplicate executions of one another.

### What the historical cache costs

`packages/gate/src/tlgate/cache.py` builds keys from command/config, whole tree or declared subsets, ignored files
under declared globs, toolchain pins, selected tests, environment, executor mode and producer receipts. It keeps up to
eight records per check and can republish an old pass under the current tree/base. `authorization.py` resolves those
records for delivery. `packages/land/src/tlland/carry.py` can create a scratch merge and run closure commands on both
versions to justify copying a pass across a base change. StackGate also accepts ledger-assisted evidence.

These mechanisms have safeguards; this review does not demonstrate a production false pass. They nevertheless
require the generic factory to know enough about arbitrary command dependencies to justify historical reuse. A
whole-tree key does not describe arbitrary ignored build state, external services or actual installed tool versions;
subset correctness depends on complete input declarations. More key fields do not make unknown dependencies known.
The historical eight-record pool also should not be the owner of an active workflow's completion: concurrent unrelated
checks can evict receipts and cause unnecessary reruns. This is an ownership/cost concern, not evidence of unsafe delivery.

Recommendation: remove generic cross-operation/cross-candidate pass lookup, input-subset cache settings and key
machinery used only for that lookup, historical promotion/carry and closure-proof commands. Remove dependent green
lookup/promotion paths or replace their actual current-workflow use with its authoritative completion state. Do not
remove normal execution specification, check outcome evidence or repository resource/setup requirements just because
the cache currently shares their types. Map consumers before deletion; no compatibility implementation is retained.

### Small retained completion contract

- A validation operation belongs to the current task workflow and exact candidate/check configuration. Its state is
  pending, running or completed with outcomes and output references. Completion is not discovered by searching past tasks.
- The workflow advancing from completed checks through review to land uses that result while candidate, relevant
  integration context and validation configuration remain unchanged. Clean slot release, detaching HEAD or review in another slot does not invalidate completed
  validation. Known relevant validation-input changes invalidate it; repository checks remain responsible for their declared external dependencies.
- Normal restart with intact DB resumes the same operation. Reconcile an active command before launching anything else.
  If the whole checks block completed, continue to review/delivery after candidate/context identity checks; it
  does not require continued occupation of the original slot. If interrupted, establish that
  its owned command stopped, then repeat the incomplete block. Repeating a completed prefix is acceptable; do not build
  a per-command artifact/dependency restoration framework merely to avoid it. Unknown liveness retains fencing.
- A new candidate, changed required policy/relevant inputs, or unestablished completion identity requires validation.
  Ordinary clean slot release/reuse is not such a change. An explicit `tl check` executes checks by
  default; it does not silently search historical passes. Multiple callers of the same active workflow join/read its
  existing operation rather than launch duplicates. Independent explicit invocations are intentional work.
- Discarded DB or a new PC may repeat checks. No receipt migration or log reconstruction is required.

Repository-owned affected-test selection remains. The separate `dev/affected.py` successful-test ledger is optional,
enabled by TL_GREEN_LEDGER in StackGate, and leaves rule tests running. Keep its ownership separate; this factory-cache
recommendation does not approve deleting or expanding that repository-specific optimization. Other mandatory checks
run normally on each candidate validation. No new cache service, monitoring system or benchmark framework is proposed.

Astra supports the smaller contract. Cost tradeoff: a real candidate change and an interrupted checks block can repeat
expensive work. That is accepted as a recommendation to assess against measured workload, not a demonstrated speedup
or an owner-approved implementation decision. Existing task tl-8bh9.5.1 owns this assessment and implementation scope.

### Adjacent exemption to remove with the proposed model

Astra identified and this review verified `packages/land/src/tlland/gate.py`, deferred/passed_over: an unverified
resource-deferred check can be passed over when inputs_changed is false. This is a separate unchanged-input exemption,
not a stored successful result. Recommend removing it with generic dependency inference; otherwise the smaller model
would retain a second way to authorize unverified work. Required unavailable capacity produces typed wait. Any explicit
repository-owned applicability decision must remain visible as such, never presented as a check that ran and passed.


Lifecycle consistency clarification, 2026-11-09: completed check evidence attaches to the exact candidate/workflow, not
to continued reservation of its directory. Clean release/detach/another slot does not cause routine duplicate checking.
Retained custody is required for safe continuation of an interrupted execution, not for the lifetime of a completed
result. Revalidate only changed required context/inputs or unestablished completion. This corrects earlier overbroad
custody wording without restoring historical pass caching. See [identity/store lifecycle](../tl-8bh9.1/identity-store-contract.md).
