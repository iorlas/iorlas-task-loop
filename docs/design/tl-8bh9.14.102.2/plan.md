# Header
Task: tl-8bh9.14.102.2; base: a1eca52afedd14c83de6186c24c77bad89580d16
Depth: small; one enforcement rule.
Owner decisions: settled; predecessor landed.
Evidence budget: 6 model calls.
Size: 3 changed files, 1 independent behaviour, about 30 implement model calls.

## Outcome and non-goals
Add an AST check confining direct Pydantic dependencies to explicit edge modules, retaining existing violations in an exact census. No runtime model migration or generated contract changes: no application modules or import edges are added.

## Settled decisions
- The supplied decision selects an AST rule with shrinking known exceptions.
- Initially permit only `agents/settings.py`, `plan_content.py`, `answer_failures.py` and `dash_model.py` under `src/taskloop/`: configuration, plan input, durable answer failures and dashboard interchange. Other current imports enter the census, including edge candidates awaiting review.
- Exact paths grant permission; module names or suffixes grant none.
- Follow the enum census pattern: unexpected sites and stale exceptions fail; removing debt requires removing its entry.

## Open decisions
- None.

## Change map
- `tests/rules/test_pydantic_edges.py` (new): `EDGE_MODULES`, `KNOWN_EXCEPTIONS`, `pydantic_sites`, `assert_pydantic_census`, repository and fixture checks; integrates through rules test discovery. Targeted search found no existing callers of these new symbols.
- `tests/rules/test_enum_values.py`: consult `scan`, `assert_census` and mutation fixtures as the pattern; no edits.
- `src/taskloop/agents/settings.py`, `src/taskloop/plan_content.py`, `src/taskloop/answer_failures.py`, `src/taskloop/dash_model.py`: consult edge model producers to justify permissions; no edits.
- `src/taskloop/clock_jumps.py`: consult `ClockJump` and `ClockJumps` as mixed existing code retained through the census.
- `docs/design/tl-8bh9.14.102.2/plan.md`, `docs/design/tl-8bh9.14.102.2/plan-metadata.json`: planning artifacts counted in Size.

## Read list
- `tests/rules/test_enum_values.py:354-374` — scan and census pattern.
- `tests/rules/test_enum_values.py:476-507` — mutation fixtures.
- `tests/rules/test_policy.py:17-46` — static policy integration.
- `src/taskloop/agents/settings.py:1-47` — configuration boundary.
- `src/taskloop/plan_content.py:1-30` — structured plan input.
- `src/taskloop/answer_failures.py:1-83` — durable failure model and codec.
- `src/taskloop/dash_model.py:238-280` — dashboard interchange.
- `src/taskloop/clock_jumps.py:1-59` — existing mixed producer.
- `pyproject.toml:15-15` — Pydantic dependency.

## Contract
Intent: enforce direct Pydantic API dependencies without importing application code. Effect: parse every Python module below `src/taskloop`; visit Import and ImportFrom at every scope, including aliases and Pydantic submodules. All Pydantic APIs count, not only BaseModel. Result: approved edge imports pass; other imports produce stable keys containing path, enclosing symbol, canonical imported name and occurrence. Line numbers belong only in diagnostics. Compare against the exact initial census; entries exempt import sites, not entire modules. Ordinary consumers of edge models remain permitted. No runtime types, stored fields, state transitions or external effects change.

## Work packages
1. Add the scanner, edge set and initial census in the new rules file, with paired rejection/permission fixtures covering aliases, submodules and nested imports. Closes A.
2. Add census mutation fixtures and repository integration in that file. Run focused tests as needed, then run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last, preserving pipeline failure status. Closes A.

## Acceptance behaviours
A. New Pydantic imports outside approved edges fail; equivalent edge models pass. Exact existing exceptions pass; added, duplicated, moved or stale sites fail. Removing debt and its entry together passes; formatting alone preserves site identity.
