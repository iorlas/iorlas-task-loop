# Header
Task: tl-8bh9.14.98; base: 220beb55af526f716b1d5e0d3f2e6e700e126801
Depth: medium; two behaviours.
Missing owner decision: no; unlanded dependency: none stated.
Evidence budget: 12 model calls total.
Size: 7 changed files, 2 independent behaviours, 45 implement model calls.

## Outcome and non-goals
Close the enforcement gap around existing import exceptions and make the ratchet decision discoverable through an ADR with executable enforcement references. Existing contracts already use import-linter exception lists; the ADR specimen is historical and the live decision records already demonstrate test links. Remaining work is explicit strictness, an approved exception ceiling, and a reusable ADR template.
Exclude new architectural boundaries, moving source modules, migrating all historical decisions, adopting the documentation prototype, and changing legitimate import owners. The later census supplement supplies no additional requirements here.

## Settled decisions
- M4 governs exception handling; use the existing import-linter contracts and native unmatched-ignore failure.
- The task's ADR requirement applies to decisions introduced here; record the ratchet decision once and provide its template.
- Keep the five existing direct exception edges: dashboard HTTP, digest URL parsing, two lock owners, and the signal owner. These include intentional permissions, not five obligations to remove working features.
- Leave historical ADRs and proposed architecture rules in their existing scope.

## Open decisions
- None.

## Change map
- `.importlinter` — contracts `no-runtime-mechanisms`, `process-lock-owners`, `one-signal-owner`: explicitly fail unmatched ignores; retain exact current edges and all other contracts.
- `tests/rules/test_ratchet.py` (new) — `test_exception_lists_do_not_grow`, `test_exception_lists_are_explicit_and_strict`: integrate through pytest's existing rules discovery; check ceilings and strict configuration.
- `docs/design/tl-8bh9.14.98/adr-ratchet.md` (new) — ratchet decision and concrete enforcing pytest nodes/contracts; integrate through the design index.
- `docs/design/tl-8bh9.14.98/adr-template.md` (new) — one decision, its rationale, consequences and required enforcing test reference; integrate through the ratchet ADR and design index.
- `docs/design/INDEX.md` — Decision records and Inventory: link the ADR, template and task artifacts without promoting prototype documents.
- `docs/design/tl-8bh9.14.98/plan.md` — implementation scope and acceptance.
- `docs/design/tl-8bh9.14.98/plan-metadata.json` — preparation commit and consulted paths.
- Consult producers `dash_server` (HTTP), `shelf_digest.identities` (URL parsing), `slot_lock`/`rounds_lock` (locks), and `interrupts` (signals); their imports remain allowed.
- Consult all reference-search consumers: `cli_composition` and `dash_server`/`interrupts` document import contracts; `tests/steps/test_land_gate.py` classifies `.importlinter` as check infrastructure. None needs a source change.

## Read list
- `.importlinter:1-182` — complete existing contracts, exact edges and integration surface.
- `pyproject.toml:38-50` — test discovery and existing development dependencies.
- `tests/rules/test_policy.py:1-61` — static-policy style and source restrictions.
- `docs/design/architecture-review/decision-register.md:10-21` — M4 and distinction between decided and proposed documentation rules.
- `docs/design/architecture-review/grilling-record.md:66-84` — bounded ratchet/ADR decision and historical census limits.
- `docs/design/tl-8bh9.14.119/adr-10-factory-management-boundary.md:1-30` — existing record structure and pytest references.
- `docs/design/architecture-review/docscheck-proto/docs/system/adr/one-owner-per-fact.md:1-9` — historical specimen; avoid treating it as the live template.
- `docs/design/architecture-review/docscheck-proto/ontology/adr.yml:1-12` — specimen schema has no enforcing-test field; no runtime integration.
- `docs/design/INDEX.md:1-25` — existing documentation integration and inventory convention.
- `README.md:341-344` — existing reader route to the decision index.
- `src/taskloop/dash_server.py:1-17` — intentional HTTP import and contract reference.
- `src/taskloop/shelf_digest/identities.py:1-12` — intentional URL parsing import.
- `src/taskloop/slot_lock.py:1-19` — intentional lock owner.
- `src/taskloop/rounds_lock.py:1-16` — second intentional lock owner.
- `src/taskloop/interrupts.py:1-16` — sole signal owner and contract reference.
- `src/taskloop/cli_composition.py:1-7` — documented consumer of the contract boundary.
- `tests/steps/test_land_gate.py:51-59` — existing check-infrastructure classification.

## Contract
No runtime API, database field, state or external action changes.

Intent: constrain exceptions without rebuilding the import checker. Effect: set `unmatched_ignore_alerting = error` on contracts carrying ignores. In the new policy test, parse configuration with stdlib `ConfigParser`; represent the approved ceiling as contract identifier to a set of exact `(importer, imported)` edges. Result: every configured exception must be within its contract's approved ceiling; wildcard edges, unknown exception-bearing contracts, and relaxed unmatched-ignore settings fail. The initial ceiling consists of the five current edges. Removal is permitted; when an exception disappears, remove it from the ceiling in the same change. Never expand an existing ceiling to excuse a regression. A future new contract establishes its own reviewed exact initial census, then follows this rule.

Import-linter remains responsible for real import-graph violations and stale ignores; the pytest policy guards configuration weakening. Do not duplicate its graph traversal. Exercise policy rejection with in-memory altered configuration, including a fresh exception, a wildcard, and warning-only unmatched handling. Confirm that shrinking configuration and ceiling is accepted.

Intent: connect a decision to enforcement. Effect: the template requires one decision and at least one repository-relative pytest node; the completed ADR names the ratchet policy tests and applicable import contracts. Result: a reviewer can follow the ADR to the exact enforcing tests. Verify these links while authoring the documents; no documentation validator, schema or generator is needed.

## Work packages
1. `.importlinter`, new `tests/rules/test_ratchet.py`: retain current permissions, explicitly enable strict unmatched handling and check exact exception ceilings. Cover weakened configuration and permitted removals; closes A1.
2. New `adr-ratchet.md`, new `adr-template.md`, `docs/design/INDEX.md`: document this decision, require an enforcing test in the template, verify the completed record's references, and add navigation/inventory entries; closes A2.
3. Finish artifact consistency, then run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last. The first gate exercises native import contracts; the second discovers the new policy checks. Report both results with the delivery.

## Acceptance behaviours
A1. Existing exact permissions pass; a newly unlisted import, stale ignore, expanded exception ceiling in configuration, wildcard exemption or downgraded unmatched handling fails enforcement. Removing a resolved exception and its approved ceiling entry passes without changing legitimate owners.
A2. A reader reaches one ratchet ADR and its reusable template from the design index; the template requires an enforcing test, and the completed ADR's pytest references resolve to the tests that enforce its decision.
