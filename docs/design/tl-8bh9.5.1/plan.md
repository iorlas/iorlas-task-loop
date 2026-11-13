# Check execution: remove repetition before choosing a cache

Status: **design**. Historical accepted validation direction; `tl check` and related command examples below
belong to that baseline/proposal, not the current parser. The successor implements
[the checks step](../tl-8bh9.14.6/plan.md); current commands are in the [README](../../../README.md).

Task: tl-8bh9.5.1. Design review, 2026-11-08. Owner accepted the proposed execution cuts with "ok" after the review
summary: remove routine pre-checking, keep focused debugging and mandatory/new-candidate validation. The visual
precheck cut is conditional on retaining actual capture prerequisites. No source changes made. The general cache
deletion hypothesis was initially subject to assessment. On 2026-11-09, after source review and Astra consultation,
the owner approved historical-cache/carry and request-machinery removal; the authoritative contract is in
[candidate checks](candidate-checks.md). Keep current-workflow completion and repository-owned affected testing.

## Purpose

Establish where checks actually execute, remove unnecessary repetition, and then decide whether a generic pass cache
is justified. Preserve workflow-controlled validation and meaningful evidence. An affected-test selector, a successful-test
ledger, a current-candidate execution result and a general reusable-pass cache are separate mechanisms.

## Evidence scope

Read the glossary review worktree. The checked briefing, planning probe, visual judge, land gate, stack gate, test runner
and justfile matched the primary checkout byte for byte on 2026-11-08. The local profile declares only suite = just gate,
with run=gate. Generic support for repeated stage checks therefore does not prove that every repository runs them.
No Unity project checkout was found directly under /home/iorlas/Workspaces. No Unity execution was attempted.

Available local logs are primarily standalone checks and stack-land histories, not representative full Unity task
histories. CheckStart/CheckEnd records also represent cached/skipped outcomes; counting them does not count subprocesses.
This review has not established actual Unity repetition counts or wall-time savings.

## Execution map

| Entry | Observed mechanism | Assessment |
|---|---|---|
| Planning | work/plan/probe.py executes up to three registered stage checks named by acceptance text on the base; otherwise looks up programs. | A distinct early probe, potentially expensive. Candidate for lookup-only planning by default. |
| Implementation agent | work/write/briefing.py tells writers to run fast checks before finishing and says the engine reruns them. | Blanket pre-validation is a duplication candidate. Keep focused debugging as needed. |
| Visual feedback | work/look/judge.py can run static checks before rendering, then proceed to normal checks. | Additional early validation. Inspect whether capture/build commands already establish the needed prerequisite. |
| Mandatory checks | work/write/check_round.py and app/checks/step.py execute configured stage checks plus planned acceptance checks. | Intended workflow-controlled validation; reconcile stage rounds with the agreed task-step design. |
| Requested checks | CheckRound calls StageChecks.requested for opted-in IDs as a separate informational block. | Distinct optional path; assess retirement after project tools cover actual execution needs. |
| Review agent | review prompts receive recorded results; generic non-writer briefing also permits running tests or lint. | Evidence reading is intended; routine suite execution is unnecessary. Targeted investigation needs a concrete reason. |
| Failed check diagnosis | gate/base.py can check the untouched base to distinguish pre-existing failures. | Conditional diagnosis, not another normal success-path check. Assess cost separately. |
| Land | land/gate.py checks evidence and can execute gate checks; integration/fix paths can revalidate. | Necessary for unassessed integration candidates; not every call is a command run or duplicate. |
| Stack delivery | land/stackgate.py asks authorization for evidence, attempts base-change proof, and invokes tl check when still unproven. | Evidence lookup is distinct from execution. Inspect the proof/promotion mechanism after reducing other runs. |
| Person invokes tl check | Explicit standalone entry point uses the shared checker. | Keep an intentional human command; do not conflate it with automatic duplicate validation. |

## Proposed smaller execution policy

One mandatory checks step validates a candidate against the repository's required commands. Implementation uses
focused commands when they help debugging; its prompt does not require it to duplicate the formal check suite.
Review consumes recorded evidence, examines acceptance and code, and does not routinely repeat the suite.

Planning ordinarily inspects requirements and capabilities without executing build/test suites on the base.
Retain an early execution probe only if a concrete use case warrants its cost. Visual capture should not implicitly
run an unrelated static suite; any needed build/capture prerequisite belongs to the actual command's requirements.

When code, integration inputs or validation policy change, assess the new candidate. Do not erase legitimate checks
after an implementation fix or merge merely because their command names appeared earlier. Conversely, entering land
or observing the same current-candidate result should not itself demand another execution.

Keep a result recording what the current candidate was checked against. That delivery evidence is needed even if
the generic cross-attempt pass cache is removed. Do not rebuild the current general cache under another name merely
to retain a current-candidate completion record.

## Test-specific mechanisms

Boundary accepted by the owner with "yes!" on 2026-11-08: the factory owns command execution, limits, output retention and result
attribution. Repository tooling owns affected-test selection and framework-specific diagnostics. Current factory
code includes C# compiler-error extraction from editor logs (gate/executor.py _project_log) and Gherkin test counting
from diffs (work/write/matchers.py). These have purposes, but neither is essential to generic check execution.
Prefer repo commands emitting their useful diagnostics and reviewers inspecting relevant diffs over adding factory
knowledge of every language/framework. Do not replace removed heuristics with a richer generic report framework.

dev/affected.py selects tests using the diff and dependency graph. Its separate ledger can skip test files whose
dependencies remain unchanged after success. dev/runtests.py enables the ledger only through TL_GREEN_LEDGER;
land/stackgate.py supplies it. Rule tests are not dropped by ledger reuse. Release explicitly disables the ledger.

Assess these mechanisms on their own merits. Candidate design: retain affected/incremental tests, run other checks
normally, and remove generic check-result reuse if it no longer saves enough work. No decision to delete the cache,
its base-change proof, or correctness checks has yet been made.

## Verification and implementation boundaries

Use representative existing Unity task logs and session transcripts to attribute real command executions to callers,
code/input context, result and duration. Separate agent debugging, mandatory validation, actual retries, cached results,
planned omissions and repeated display. Existing evidence is sufficient for the investigation; no monitoring service
or new runtime tracing subsystem is proposed. If available evidence cannot establish frequency, report that limit.

After the owner selects the cuts, implement them with focused tests of execution order and completion invariants,
then run the repository gates. Reinspect retained pass validity through the single authorization owner, including
executor identity, external state, generated inputs and dependencies. Coordinate with deferred project-tool work
tl-8bh9.4.1 and existing gate-location task tl-wxcg instead of implementing overlapping runners.

This document records the review and proposed implementation shape; task status and follow-up ownership remain in
the task tracker. Architecture vocabulary is defined in [the glossary](../../glossary.md) and explained in
[execution terms](../execution-terms.md).
