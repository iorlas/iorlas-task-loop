# ADR 07: Execution state ownership

Status: **design** decision record, extracted 2026-11-13. Acceptance and built enforcement are bounded below; historical proposals are not promoted by this record.

## Context and authority

2026-11-06; Denis chose SQLite, reconciled by the 2026-11-09 identity/store decision. Source: [recorded decision](../sqlite-store-plan.md#execution-store-decision), identified by “Owner decision (Denis, 2026-11-06): SQLite for all, as soon as possible”.
Extraction follows [this task's plan](plan.md) and the 2026-11-13 [round 4 review](../architecture-review/grilling-record.md#haiku-round-4-stop-yield-is-docs-packaging-and-refinement-no-new-structural-risk), session `local_16bd6c79`. Tests demonstrate behavior, not human agreement.

## Decision

factory.db owns local execution state and reservations. The task tracker owns requirements and task data; Git owns code, plans and selected design artifacts. Logs/transcripts remain files behind readers, never control-state fallback.

## Alternatives and rationale

The old SQLite proposal included migration, dual reads, import/export and rollback. The later reconciled STORE contract supersedes those mechanisms: no compatibility reader, history reconstruction or file fallback. Deliberate discard permits reevaluation, not automatic data loss on restart.

## Consequences and current scope

Compatible intact-DB restart retains unfinished progress and session references after liveness reconciliation. A missing/unreadable DB is not silently initialized by a read/restart path. Tracker data protection remains the tracker maintenance owner's responsibility; exports remain protected until verified recovery.

## Related and superseding records

[Reconciled STORE](../tl-sqd3.26/plan.md); [identity/store contract](../tl-8bh9.1/identity-store-contract.md); [glossary ownership](../../glossary.md#storage-ownership). These supersede the old migration scope, without lifting unrelated holds.

## Enforcement

- [`tests/rules/test_policy.py::test_every_sql_write_has_its_one_owner`](../../../tests/rules/test_policy.py): one SQL writer per table.
- [`tests/steps/test_restart.py::test_compatible_restart_keeps_progress_sessions_and_reservation_and_reconciles_the_same_attempt`](../../../tests/steps/test_restart.py): intact compatible restart and reconciliation.
- [`tests/cli/test_factory_restart.py::test_missing_or_unreadable_database_is_never_initialized`](../../../tests/cli/test_factory_restart.py): missing/unreadable DB refusal.
