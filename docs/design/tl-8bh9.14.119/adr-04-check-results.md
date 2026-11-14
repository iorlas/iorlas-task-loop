# ADR 04: Check results belong to their attempt

Status: **design** decision record, extracted 2026-11-13. Acceptance and built enforcement are bounded below; historical proposals are not promoted by this record.

## Context and authority

2026-11-09; owner accepted the reviewed check-pipeline simplifications. Source: [recorded decision](../execution-terms.md#check-results-decision), identified by “Owner decision 2026-11-09: accepted the Astra-reviewed discussion roadmap and check-pipeline simplifications”.
Extraction follows [this task's plan](plan.md) and the 2026-11-13 [round 4 review](../architecture-review/grilling-record.md#haiku-round-4-stop-yield-is-docs-packaging-and-refinement-no-new-structural-risk), session `local_16bd6c79`. Tests demonstrate behavior, not human agreement.

## Decision

Remove historical pass-cache/carry proofs and automatic base-red or unchanged-input exemptions. Required failures block; a new checks attempt runs its commands. Repository-owned affected testing remains available.

## Alternatives and rationale

The candidate-checks review weighs repeated validation against the identity/proof machinery of historical pass reuse. The owner chose the smaller completion contract and deferred successful-check caching until demonstrated need.

## Consequences and current scope

The checks step is built. Current-attempt result rows and continuation of unfinished land are required state, not a cross-attempt pass cache. ADR 08 protects that continuation; this decision does not require rerunning finished land validation.

## Related and superseding records

[Candidate checks](../tl-8bh9.5.1/candidate-checks.md#owner-decision-2026-11-09); [ADR 08](adr-08-land-resume.md) qualifies continuation.

## Enforcement

- [`tests/steps/test_checks.py::test_every_check_runs_in_order_after_its_identity_is_committed`](../../../tests/steps/test_checks.py): ordered actual execution and recorded identities.
- [`tests/steps/test_checks.py::test_the_conclusion_reads_the_required_names_and_any_stopping_result`](../../../tests/steps/test_checks.py): required failures decide the conclusion.
- [`tests/steps/test_checks.py::test_a_new_checks_attempt_runs_commands_despite_a_previous_pass`](../../../tests/steps/test_checks.py): a fresh attempt executes despite stored previous passes.
