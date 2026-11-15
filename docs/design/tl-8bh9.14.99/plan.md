# Header
Task: tl-8bh9.14.99
Base: 74641862ca9f7cc6a2754ada170dc29b0d15459f
Depth: medium; two enforcement behaviours
Decisions settled; dependencies landed. Evidence ceiling: 12 model calls.
Size: 9 changed files including artifacts; 2 independent behaviours; 45 implement model calls.

## Outcome and non-goals
The native import gate enforces folder privacy and store-only SQLite imports across the current tree. Repository checks detect stale coverage and permissions. Exact exception ceilings only shrink. Exclude application relocation, runtime changes, new dependencies and pytest invocation of native lint tooling.

## Settled decisions
- Enforcement (1): Python feature folders define private modules through two folder levels; `api.py` is public. Flat modules and static-only folders do not create slices. Initializers cannot re-export internals; nested folders have independent boundaries.
- Enforcement (2): literal `store.py` owns direct SQLite imports, including connection annotations. Suffixed stores remain exact migration exceptions. Indirect callers through stores remain permitted.
- The supervisor's tooling decision places native contracts in `.importlinter`; retain the existing pinned gate integration.
- Ratchets use exact edges and strict unmatched-ignore errors. Protected contracts use `unmatched_ignore_imports_alerting`; forbidden contracts use `unmatched_ignore_alerting`.
- Completed SQL extraction remains delivered. The current census still has 34 direct noncanonical SQLite importers; audit their exact edges rather than treating completed extraction as proof that imports disappeared.
- Generation derives coverage from the current tree and preserves reviewed exceptions; it never approves violations automatically.

## Open decisions
- None.

## Change map
- `.importlinter` — root options and generated folder/SQLite sections: retain existing contracts, include type-only imports, rebuild module lists including `taskloop.shelf_request`, reconcile exact exception edges.
- `tools/generate_import_contracts.py` — new; `modules`, `slices`, `section`, `generate`, `main` produce deterministic configuration for `.importlinter`; consumers are the two new rule modules below and its command entry.
- `tests/rules/test_slice_contracts.py` — new; generator `generate/modules/slices` callers check tree freshness, nested boundaries, initializer bypasses and exception preservation; integrates with `.importlinter` and the generator.
- `tests/rules/test_sqlite_contracts.py` — new; generator `generate/modules` callers check complete non-store coverage, import forms, exact Ruff grants and retained bans; integrates with `.importlinter`, `ruff.toml` and the generator.
- `tests/rules/test_ratchet.py` — `APPROVED_EXCEPTIONS`, `assert_exception_ceiling`, `assert_strict_exceptions`: add audited slice/SQLite ceilings and contract-specific strictness. Consult callers `test_exception_lists_do_not_grow`, `test_unapproved_or_wildcard_exception_fails`, `test_exception_cannot_move_to_another_contract`, `test_unknown_exception_bearing_contract_fails`, `test_exception_and_ceiling_can_shrink_together`, `test_exception_lists_are_explicit_and_strict`, `test_relaxed_or_implicit_unmatched_handling_fails`, `test_inherited_unmatched_handling_fails`.
- `ruff.toml` — `lint.flake8-tidy-imports.banned-api` and `lint.per-file-ignores`: ban SQLite; grant exact source permissions for stores/exceptions plus test fixtures; preserve other banned APIs with AST checks.
- `docs/design/tl-8bh9.14.99/adr-enforcement.md` — new; record boundaries, exact exception maintenance and generation integration with the existing ratchet.
- `docs/design/tl-8bh9.14.99/plan.md` — implementation scope and acceptance.
- `docs/design/tl-8bh9.14.99/plan-metadata.json` — preparation commit and consulted paths.

## Read list
- `.importlinter:1-18` — native root options and existing contract format; integration point for new generator and rules.
- `.importlinter:123-162` — retained exception-bearing contracts and protected-contract integration.
- `.importlinter:164-185` — preserve the domain contract while appending generated sections.
- `ruff.toml:8-16` — existing banned imports and exact-permission integration for SQLite rules.
- `tests/rules/test_ratchet.py:8-68` — exception ceiling codec, fixture and strictness checks to extend.
- `tests/rules/test_ratchet.py:70-129` — all existing mutation-check callers to preserve and extend.
- `tests/rules/test_policy.py:32-55` — static policy and banned-process constraint retained by new rules.
- `tests/rules/test_attempt_sql_ownership.py:11-40` — delivered SQL ownership enforcement to preserve.
- `src/taskloop/shelf_request.py:1-24` — current flat module that must enter complete coverage without becoming a slice.

## Contract
Intent: enumerate `src/taskloop` Python files, treating initializers as their package module. Effect: `modules(Path) -> dict[str, Path]` and `slices(Path, dict[str, Path]) -> dict[str, list[str]]` derive deterministic coverage. Result: each folder's private modules have a protected native contract with exact allowed importers; `api.py` remains public. Parent importers cannot gain child internals implicitly.

Intent: refresh enforcement after module changes. Effect: `generate(Path, str) -> str` replaces its block, preserves unrelated configuration and reviewed exceptions, and prints through the tool entry. Result: committed configuration equals fresh output. Adding a flat module, nested module, initializer or slice makes stale coverage fail. Independently verify membership of all 228 current modules.

Intent: restrict SQLite mechanisms. Effect: native forbidden sources include every module except literal stores with package expansion disabled and type-only imports included. Result: direct `sqlite3`, aliased imports and `Connection` imports require ownership or an exact reviewed exception; indirect store callers need no exception. No runtime types, database fields or states change.

Intent: permit only existing violations. Effect: reconcile configuration edges, paired ceilings and Ruff grants; remove resolved entries together. Result: stale, wildcard, moved or newly invented exceptions fail. Ruff's TID251 permissions cannot exempt another banned API because AST checks cover exempt files. Tests read files/AST and exercise the pure generator; native graph enforcement remains in the gate.

## Work packages
1. In the generator, `.importlinter` and slice rules, retain the available enforcement implementation and regenerate against the current folder tree. Independently verify full module membership, nested privacy, initialization and deterministic refresh. Closes A1.
2. In `.importlinter`, `ruff.toml`, SQLite rules and ratchet rules, reconcile current direct import edges and exact grants; retain the remaining slice ceiling without expansion. Record the maintenance contract in the ADR. Closes A2 and the exception aspect of A1.
3. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each with pipeline failure propagation, covering both new rule modules and native contracts. Confirm the final diff stays scoped.

## Acceptance behaviours
A1. Every current Python module contributes to the appropriate generated coverage, including flat `shelf_request`; adding a module makes stale configuration fail. External access to private folder modules fails except for exact reviewed edges, while public APIs remain accessible, nested privacy holds and initializers cannot bypass it.
A2. Every non-store direct SQLite import, including aliases and type-only connection imports, is forbidden except for an exact surviving edge. Indirect store use remains valid. Removing an exception removes its ceiling and Ruff grant; stale or expanded permissions fail, and another banned API stays forbidden in SQLite-exempt files.
