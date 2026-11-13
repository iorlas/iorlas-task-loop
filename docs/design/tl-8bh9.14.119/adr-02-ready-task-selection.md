# ADR 02: Ready-task selection

Status: **design** decision record, extracted 2026-11-13. Acceptance and built enforcement are bounded below; historical proposals are not promoted by this record.

## Context and authority

2026-11-08 scheduling decision; subsequent manual-queue/epic-order approval has no separate date in the source. Source: [recorded decision](../execution-terms.md#ready-task-selection-decision), identified by “Owner subsequently approved manual-queue/epic-order removal”.
Extraction follows [this task's plan](plan.md) and the 2026-11-13 [round 4 review](../architecture-review/grilling-record.md#haiku-round-4-stop-yield-is-docs-packaging-and-refinement-no-new-structural-risk), session `local_16bd6c79`. Tests demonstrate behavior, not human agreement.

## Decision

Select automation-approved ready work without a manual queue, configured epic order or area exclusion. Eligibility precedes the hierarchical ordering defined by ADR 09.

## Alternatives and rationale

The selection review considered the extra manual queue, epic-order and area policies. The owner removed them in favor of explicit task approval, satisfied dependencies and priority. Independent children may run together.

## Consequences and current scope

Selection is built. Claims, dependencies, holds, slot availability and the current in-flight bound still constrain admission; removing an extra queue does not grant eligibility or preempt active attempts.

## Related and superseding records

[Selection review](../tl-8bh9.3/selection-review.md#owner-approved-model); [ADR 09](adr-09-hierarchical-priority.md) owns the comparator, not eligibility.

## Enforcement

- [`tests/steps/test_selection.py::test_eligibility_skips_attempted_abandoned_and_another_actors_task_but_keeps_the_factorys`](../../../tests/steps/test_selection.py): eligibility and claim ownership.
- [`tests/steps/test_round_bound.py::test_a_backlog_starts_only_up_to_the_default_bound_not_every_ready_task`](../../../tests/steps/test_round_bound.py): bounded admission.
