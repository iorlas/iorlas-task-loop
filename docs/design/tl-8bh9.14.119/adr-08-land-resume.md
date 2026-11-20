# ADR 08: Resume only unfinished land actions

Status: **design** decision record, extracted 2026-11-13. Acceptance and built enforcement are bounded below; historical proposals are not promoted by this record.

## Context and authority

2026-11-11 land design; built through L0–L5 and M3, with subsequent owner decisions recorded in its source plan. Source: [recorded decision](../tl-8bh9.14.8/plan.md#land-resume-decision), identified by “The latest land candidate”.
Extraction follows [this task's plan](plan.md) and the 2026-11-13 [round 4 review](../architecture-review/grilling-record.md#haiku-round-4-stop-yield-is-docs-packaging-and-refinement-no-new-structural-risk), session `local_16bd6c79`. Tests demonstrate behavior, not human agreement.

## Decision

The latest land candidate decides continuation. Retry a held release first, including before close or already-landed responses. A delivered candidate goes directly to tracker close; a closed candidate returns already landed without Git/tracker actions.

## Alternatives and rationale

The plan records this as the land use-case contract under autonomous design authority, open to owner veto, not a separately dated owner quote at the cited paragraph. Restarting validation and push from scratch would repeat finished effects; candidate state instead identifies unfinished actions. Do not infer additional owner approval from this extraction.

## Consequences and current scope

The shared land application operation and its reconciled continuation are built. Finished validation/publication is not repeated merely because the caller reruns land. ADR 04's deletion of historical pass reuse does not delete this current-workflow state.

## Related and superseding records

[Land contract](../tl-8bh9.14.8/plan.md#land-resume-decision); [ADR 04](adr-04-check-results.md) separates fresh attempts from continuation.

## Enforcement

- [`tests/steps/test_land_resume.py::test_a_held_release_is_retried_first_by_every_rerun_and_the_land_still_pushes`](../../../tests/steps/test_land_resume.py): release precedes continuation.
- [`tests/steps/test_land_resume.py::test_a_crash_after_the_validation_before_the_push_pushes_on_the_rerun_without_checking_again`](../../../tests/steps/test_land_resume.py): finished validation is retained.
- [`tests/steps/test_land_close.py::test_a_closed_land_is_already_landed_with_no_git_or_tracker_call`](../../../tests/steps/test_land_close.py): closed candidates do no external work.
