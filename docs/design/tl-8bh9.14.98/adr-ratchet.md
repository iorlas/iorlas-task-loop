# ADR: Ratchet import-contract exceptions

Status: **built** for the bounded enforcement below, 2026-11-15.

## Context and authority

Owner decision, architecture-review rounds 16–18, session `local_16bd6c79`, 2026-11-13:
new contracts list current violations as known exceptions, and those lists only shrink.
Each decision has an ADR naming its enforcing test. See
[M4](../architecture-review/decision-register.md#1-process-docs-and-enforcement-meta),
the [review record](../architecture-review/grilling-record.md#round-14-18-and-haiku-rounds-1-3)
and the [composition evidence](../architecture-review/composition-map.html).
The [task plan](plan.md) bounds this implementation; historical censuses do not introduce new contracts here.

## Decision

Use import-linter's existing `ignore_imports` lists as exact exception edges, with explicit
`unmatched_ignore_alerting = error` on every exception-bearing contract. A policy test records
the approved ceiling per contract. Existing lists may only shrink; a new contract needs its own
reviewed initial census. Remove a resolved exception and its ceiling entry together. Never expand
an existing ceiling to excuse a regression or use wildcard exceptions.

The initial ceiling contains five direct imports:

| Contract | Importer | Imported module | Current permission |
|---|---|---|---|
| `no-runtime-mechanisms` | `taskloop.dash_server` | `http.server` | Dashboard HTTP server |
| `no-runtime-mechanisms` | `taskloop.shelf_digest.identities` | `urllib.parse` | Shelf URL parsing |
| `process-lock-owners` | `taskloop.slot_lock` | `process_lock` | Slot custody |
| `process-lock-owners` | `taskloop.rounds_lock` | `process_lock` | Rounds lock |
| `one-signal-owner` | `taskloop.interrupts` | `signal` | Rounds signal handlers |

These permissions include intentional owners; recording them does not require deleting their behavior.

## Alternatives and rationale

Keep the existing import checker and its native stale-ignore detection. A second import-graph
walker would duplicate that ownership. Explicit strictness plus exact ceilings closes configuration
weakening without introducing report-only contracts or moving runtime modules.

## Consequences and current scope

An unlisted import or a stale ignore fails import-linter. Growing an existing exception list,
adding an unreviewed exception-bearing contract, using a wildcard, relaxing strictness or leaving
a removed exception in its ceiling fails the policy tests. A resolved exception and its ceiling
may be removed together. Both gates retain the five working permissions.

Use the [ADR template](adr-template.md) for one decision with rationale, consequences and a concrete
repository-relative pytest node. This record does not migrate historical decisions or adopt the
documentation prototype or proposed architecture boundaries.

## Enforcement

- [`tests/rules/test_ratchet.py::test_exception_lists_do_not_grow`](../../../tests/rules/test_ratchet.py)
  checks the exact approved ceiling and rejects spare permissions after removal.
- [`tests/rules/test_ratchet.py::test_exception_lists_are_explicit_and_strict`](../../../tests/rules/test_ratchet.py)
  rejects wildcard edges and requires explicit error handling for unmatched ignores.
- [`tests/rules/test_ratchet.py::test_exception_and_ceiling_can_shrink_together`](../../../tests/rules/test_ratchet.py)
  exercises removal of one exception and removal of a contract's entire exception list.
- [`.importlinter`](../../../.importlinter) contracts `no-runtime-mechanisms`, `process-lock-owners`
  and `one-signal-owner` check the real import graph and reject stale ignores through `just check`.

The policy tests run through `just test`. The template requires an enforcing-test reference for
review; there is no documentation validator or generator in this change.
