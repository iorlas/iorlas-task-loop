# ADR 03: Profile-change approval

Status: **design** decision record, extracted 2026-11-13. Acceptance and built enforcement are bounded below; historical proposals are not promoted by this record.

## Context and authority

2026-11-09; owner rejected a replacement database grant and removed the former approval mechanism. Source: [recorded decision](../execution-terms.md#profile-change-approval-decision), identified by “Owner decision, 2026-11-09: remove the whole profile-change-specific approval mechanism”.
Extraction follows [this task's plan](plan.md) and the 2026-11-13 [round 4 review](../architecture-review/grilling-record.md#haiku-round-4-stop-yield-is-docs-packaging-and-refinement-no-new-structural-risk), session `local_16bd6c79`. Tests demonstrate behavior, not human agreement.

## Decision

Retire the old profile-change authorization records, audit-log delivery gate and replacement grant proposal. Configuration is ordinary versioned task content, with source snapshots selected by the owning operation.

## Alternatives and rationale

The configuration review records the proposed DB grant and the owner's rejection. Moving that authorization into another store would preserve the mechanism the owner removed.

## Consequences and current scope

The later built land contract qualifies the original blanket wording: changes to checks/configuration require explicit acceptance through --accept-gate-changes where land_gate requires it. That flag remains supported. This record does not approve all profile edits for automatic delivery.

## Related and superseding records

[Original configuration review](../tl-8bh9.1/configuration-review.md#profile-approval-is-removed-not-moved); later [land decision 30.1 (.42, .43)](../tl-8bh9.14.8/plan.md#301-decision-a-change-of-the-gate-is-refused-unless-accepted-42-43), arising from [trial 5](../self-hosting-trial-5.md), and [land_gate.py](../../../src/taskloop/land_gate.py) supersede the blanket no-special-flag claim. The task numbers do not have separate plan files in this tree.

## Enforcement

- [`tests/steps/test_land_gate.py::test_a_land_that_changes_a_check_argv_is_refused_and_a_land_changing_nothing_of_it_lands_as_before`](../../../tests/steps/test_land_gate.py): the later acceptance boundary, not the earlier blanket statement.
