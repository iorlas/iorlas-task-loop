# ADR 01: Delivery and publication

Status: **design** decision record, extracted 2026-11-13. Acceptance and built enforcement are bounded below; historical proposals are not promoted by this record.

## Context and authority

2026-11-09; owner approved the delivery/publication strategy. Source: [recorded decision](../execution-terms.md#delivery-publication-decision), identified by “Owner approved delivery/publication strategy 2026-11-09”.
Extraction follows [this task's plan](plan.md) and the 2026-11-13 [round 4 review](../architecture-review/grilling-record.md#haiku-round-4-stop-yield-is-docs-packaging-and-refinement-no-new-structural-risk), session `local_16bd6c79`. Tests demonstrate behavior, not human agreement.

## Decision

Publication appends completed plan/mutating steps to the task branch without force. Land consolidates the checked change as a final squash and resumes only unfinished actions. Internal results are typed; adapters own interchange quirks.

## Alternatives and rationale

The source distinguishes task publication from delivery and completion. Force-rewriting publication and parsing display phrases would lose that distinction and the typed operation boundary. The accepted contract retains ordinary append-only publication and resumable delivery.

## Consequences and current scope

The successor builds direct push and task close through the shared land operation. PR waiting and other delivery targets in the original strategy remain design. Publishing alone never closes a task.

## Related and superseding records

[Delivery contract](../tl-8bh9.9/delivery-publication.md#owner-approval-and-structured-contracts-2026-11-09); [land plan](../tl-8bh9.14.8/plan.md). ADR 08 narrows the resume rule.

## Enforcement

- [`tests/steps/test_publish.py::test_a_verified_released_plan_is_pushed_from_the_checkout_and_recorded_once`](../../../tests/steps/test_publish.py): verified publication and idempotent recording.
- [`tests/steps/test_land_close.py::test_a_crash_between_the_push_and_the_close_is_finished_by_the_rerun_without_git`](../../../tests/steps/test_land_close.py): close after delivery without repeating Git.
