# Header
Task: tl-8bh9.14.102.3
Base: e09a4694e0e9dc80ee80fba238d227fe92651d25
Depth: small; one rule in tests/rules.
Owner decision missing: no. Unlanded dependency: none.
Evidence budget: 6 model calls.
Size: 5 files incl. plan/artifacts; 1 behaviour; 30 implement model calls.

## Outcome and non-goals
Prevent new repeated executable strings through an AST rule and exact shrinking census. Bulk string extraction, other vocabulary rules and public-surface snapshots are outside scope.

## Settled decisions
- Count equal decoded string values within each Python module under src/taskloop, recursively; three occurrences trigger the rule, including short and empty strings.
- Exclude module, class and function docstrings and f-string text fragments; count actual string literals inside formatted expressions. Comments and bytes do not count. Adjacent literal tokens count as one Python literal.
- Constant references add no occurrences; the initializer counts once, across functions too.
- Record existing violating groups by relative path, exact string value and occurrence count. No wildcard exemptions or automatic baseline refresh during checks.
- Existing pytest discovery integrates the rule; no production imports change.

## Open decisions
- None.

## Change map
- `tests/rules/test_repeated_strings.py` (new): `repeated_string_sites`, `assert_string_census`, repository test and examples; integrate with pytest discovery, following `pydantic_sites` and `assert_pydantic_census` without importing them.
- `tests/rules/repeated_string_exceptions.json` (new): path/value/count census for the new repository test; generate from current source and review.
- `pyproject.toml`: consult pytest discovery; no edit expected.
- `tests/rules/test_pydantic_edges.py`: consult `pydantic_sites`, `assert_pydantic_census` and local callers: repository, outside/edge, exact-path, unrelated-name, changed-import, moved-import and formatting/shrink tests; no edit.
- `tests/rules/test_policy.py`: consult docstring exclusion and caps; no edit.
- `docs/design/tl-8bh9.14.102.3/plan.md` (new): implementation scope and acceptance.
- `docs/design/tl-8bh9.14.102.3/plan-metadata.json` (new): preparation commit and consulted paths.

## Read list
- `tests/rules/test_pydantic_edges.py:181-278` — scanner, census assertion and every local caller.
- `tests/rules/test_policy.py:18-65` — docstring treatment and size enforcement.
- `pyproject.toml:46-50` — existing pytest integration.

## Contract
Intent: scan relative paths mapped to source text. Effect: parse without executing code; group eligible literals by module and decoded value. Result: typed path/value/count data and diagnostic locations for groups reaching three.

Validate JSON with a Pydantic v2 adapter for nested path/value/positive-count mappings. New, increased, moved, stale or decreased entries fail; resolved exceptions must shrink or disappear below three. Formatting and quote changes preserve identity. Validation only reads files; no runtime states or external effects change.

## Work packages
1. Add the scanner, assertion and focused examples in the new rule module; closes A1, including scope and literal exclusions.
2. Generate and review the exception JSON against current source; wire the repository test into existing discovery and verify census changes; closes A1 for the existing tree. Run the focused file with the permitted isolated pytest command, then run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
A1: An unexcepted module containing three equal executable string literals fails; two occurrences or one shared constant with repeated references pass. The same rule preserves documented exclusions and rejects new, increased, moved or stale census entries while allowing reviewed shrinkage and formatting-only changes.
