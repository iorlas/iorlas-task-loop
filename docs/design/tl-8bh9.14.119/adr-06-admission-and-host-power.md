# ADR 06: Admission and host power

Status: **design** decision record, extracted 2026-11-13. Acceptance and built enforcement are bounded below; historical proposals are not promoted by this record.

## Context and authority

2026-11-09; owner removed proactive RAM thresholds, originally retaining keep-awake; later owner-directed deletion in tl-8bh9.14.26–.29. Source: [recorded decision](../execution-terms.md#admission-and-host-power-decision), identified by “Owner accepted 2026-11-09: remove proactive RAM-threshold admission initially”.
Extraction follows [this task's plan](plan.md) and the 2026-11-13 [round 4 review](../architecture-review/grilling-record.md#haiku-round-4-stop-yield-is-docs-packaging-and-refinement-no-new-structural-risk), session `local_16bd6c79`. Tests demonstrate behavior, not human agreement.

## Decision

Do not admit work through proactive RAM thresholds. The current factory does not manage host power. Available slots and in-flight bounds still constrain admission.

## Alternatives and rationale

The original decision retained a lifetime-scoped keep-awake helper. The later trial showed a misleading started message and a defunct child when OrbStack denied inhibition; the owner then directed deletion. Retaining that helper is a superseded alternative, not current authority.

## Consequences and current scope

Keep-awake was built, trialed and removed. The person/host owns power policy. The static contract protects concrete retired dependencies and APIs; it is not proof against every conceivable dynamic host API.

## Related and superseding records

[B11 deletion](../self-hosting-roadmap.md#b11-keep-awake-deleted); [layers section 5](../layers.md#5-flagged-items-all-recommendations-are-proposed) records the deletion, while the rest of the layer judgments remain proposed.

## Enforcement

- [`tests/rules/test_decision_boundaries.py::test_factory_does_not_manage_host_power_or_ram_admission`](../../../tests/rules/test_decision_boundaries.py): concrete removed modules, dependencies, power tools and memory APIs.
- [`tests/steps/test_round_bound.py::test_running_tasks_count_towards_the_bound_and_a_full_one_reads_no_tracker`](../../../tests/steps/test_round_bound.py): the retained in-flight admission bound.
