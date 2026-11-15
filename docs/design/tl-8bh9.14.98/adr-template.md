# ADR: <one decision>

Status: <design or built; date; bound any claim of implemented enforcement>.

## Context and authority

<Name the problem, the owner's decision and its dated source. Separate accepted decisions from proposals.>

## Decision

<State exactly one decision and the scope in which it applies.>

## Alternatives and rationale

<Name the alternatives considered and why this decision was chosen.>

## Consequences and current scope

<Describe resulting behavior, tradeoffs and any remaining unimplemented portions.>

## Related and superseding records

<Link relevant records and describe what, if anything, this decision supersedes.>

## Enforcement

Required: at least one concrete, repository-relative pytest node, naming the test that enforces
this decision, with a link that resolves from the completed ADR and a description of what it proves.
For example: `tests/rules/test_ratchet.py::test_exception_lists_do_not_grow`.
Name any applicable import-linter contract and the gate that runs it as well. Distinguish implemented
enforcement from a proposed test; do not claim built enforcement until the named test exists and passes.

See the completed [ratchet ADR](adr-ratchet.md#enforcement) for test links and bounded enforcement claims.
