# ADR 05: Lightweight skills and hooks

Status: **design** decision record, extracted 2026-11-13. Acceptance and built enforcement are bounded below; historical proposals are not promoted by this record.

## Context and authority

2026-11-09; owner clarified skill purpose; Astra recommended hook retirement. Source: [recorded decision](../execution-terms.md#skills-and-hooks-decision), identified by “Owner clarified lightweight skill purpose 2026-11-09”.
Extraction follows [this task's plan](plan.md) and the 2026-11-13 [round 4 review](../architecture-review/grilling-record.md#haiku-round-4-stop-yield-is-docs-packaging-and-refinement-no-new-structural-risk), session `local_16bd6c79`. Tests demonstrate behavior, not human agreement.

## Decision

Skills give explicitly requested help with setup, maintenance, task authoring, questions and operations. They do not schedule work or own policy/state. Normal factory execution has no chat-skill or managed-hook installation prerequisite.

## Alternatives and rationale

The operations review supersedes its earlier keep-hooks recommendation with Astra's recommendation to retire session hooks and the managed Git-hook overlay. The source distinguishes that recommendation from the owner's accepted skill intent; it does not establish a separate owner approval of every proposed hook deletion.

## Consequences and current scope

Ordinary admission and execution use their owning ports directly. Repository/user Git and LFS hooks and execution-adapter mechanisms remain separate; this task neither removes nor bypasses them. The regression covers a semantic fake environment, not every external harness or installed user hook.

## Related and superseding records

[Operations review](../tl-8bh9.8/operations.md#lightweight-skill-and-hook-retirement-direction-2026-11-09) records the recommendation and its limits.

## Enforcement

- [`tests/steps/test_decision_boundaries.py::test_normal_work_needs_no_skill_or_managed_hook_installation`](../../../tests/steps/test_decision_boundaries.py): admission and agent execution with an empty optional environment, without creating helper/hook directories.
