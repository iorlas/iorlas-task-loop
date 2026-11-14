# ADR 10: Factory management boundary

Status: **design** decision record, extracted 2026-11-13. Acceptance and built enforcement are bounded below; historical proposals are not promoted by this record.

## Context and authority

2026-11-12; owner decision quoted from the tl-isfa epic brief. Source: [recorded decision](../layers.md#factory-management-decision), identified by “Owner decision (2026-11-12, quoted from the epic's brief)”.
Extraction follows [this task's plan](plan.md) and the 2026-11-13 [round 4 review](../architecture-review/grilling-record.md#haiku-round-4-stop-yield-is-docs-packaging-and-refinement-no-new-structural-risk), session `local_16bd6c79`. Tests demonstrate behavior, not human agreement.

## Decision

Package managers own installs, versions, pins and releases. The factory owns tasks, steps, slots and agents and reports its running package version. Runtime code stays fixed until process restart.

## Alternatives and rationale

The quoted decision removes factory self-install/pin and the start exec shim. Reporting a running version remains useful observation. The layer table and suggested import contracts are proposed judgments, not accepted architecture merely because they neighbor the quote.

## Consequences and current scope

Self-management commands are absent and version reporting is built. The invalid-command contract also guards historical/proposed report, repo register, task create and slot list/release/hold examples. It does not implement those commands or prove every suggested layer rule.

## Related and superseding records

[Layers](../layers.md); [operations version boundary](../tl-8bh9.8/operations.md#version-strategy-removed). Later check-change acceptance in ADR 03 remains in effect.

## Enforcement

- [`tests/cli/test_cli.py::test_version_prints_the_running_package_version`](../../../tests/cli/test_cli.py): running version reporting.
- [`tests/cli/test_cli.py::test_invalid_request`](../../../tests/cli/test_cli.py): absent management and historical/proposed commands exit 2.
- [`tests/rules/test_policy.py::test_nothing_forks_execs_or_spawns`](../../../tests/rules/test_policy.py): process boundary only, not every layer judgment.
