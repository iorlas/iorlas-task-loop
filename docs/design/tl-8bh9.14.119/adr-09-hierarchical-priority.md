# ADR 09: Hierarchical priority

Status: **design** decision record, extracted 2026-11-13. Acceptance and built enforcement are bounded below; historical proposals are not promoted by this record.

## Context and authority

2026-11-08; owner accepted Astra's specificity rule. Source: [recorded decision](../tl-8bh9.3/hierarchical-priority.md#required-ordering-contract), identified by “Owner accepted Astra's rule on 2026-11-08”.
Extraction follows [this task's plan](plan.md) and the 2026-11-13 [round 4 review](../architecture-review/grilling-record.md#haiku-round-4-stop-yield-is-docs-packaging-and-refinement-no-new-structural-risk), session `local_16bd6c79`. Tests demonstrate behavior, not human agreement.

## Decision

Compare own task priority, then nearest ancestor outward. Missing priorities and levels are P2; pad to the deepest candidate chain. Break exact ties by natural task ID. Eligibility remains ADR 02's separate concern.

## Alternatives and rationale

The source rejects root-first ordering, weighted scores and inherited-priority writes: ancestors must never outweigh own priority. Variable-length or common-prefix comparisons can reward short chains or become non-transitive, so the contract requires P2 padding and one total order.

## Consequences and current scope

The comparator is built. Reparenting can change nearest context, and lower-priority work can starve; the accepted rule does not promise structural neutrality or fairness boosts. No extra persisted score or queue is authorized.

## Related and superseding records

[Ordering contract](../tl-8bh9.3/hierarchical-priority.md#required-ordering-contract); [ADR 02](adr-02-ready-task-selection.md) records the overlapping queue-policy removal without redefining ordering.

## Enforcement

- [`tests/steps/test_selection.py::test_every_scenario_of_the_contract`](../../../tests/steps/test_selection.py): specified ordering scenarios.
- [`tests/steps/test_selection.py::test_missing_levels_pad_with_p2_to_the_deepest_chain`](../../../tests/steps/test_selection.py): padding and defaults.
- [`tests/steps/test_selection.py::test_the_non_transitive_trap_gives_one_total_order`](../../../tests/steps/test_selection.py): total order in the adversarial case.
