# Header
tl-8bh9.14.186.1.2; base a8a0a7ac290fa1b3adba66a8d30c43401754ba37.
Depth: small; one extraction behaviour/feature. No missing decision; part 1 landed. Evidence budget: 6 model calls.
Size: 6 changed files, 1 independent behaviour, 55 implement model calls.

## Outcome and non-goals
Add extraction to existing identities/immutable reads. Part 3 owns documentation generation and CLI wiring.

## Settled decisions
- Use existing identities/source ports; never execute source.
- Follow static exports and package-local re-exports; exclude incidental external imports.
- Separate public/defining names; sort results.
- Explain unresolved explicit exports.

## Open decisions
- None.

## Change map
- src/taskloop/shelf_digest/models.py (new): Signature, SignatureKind, SignatureFailure.
- src/taskloop/shelf_digest/declarations.py (new): AST signatures using models.
- src/taskloop/shelf_digest/exports.py (new): binding resolution over CommittedSource.
- src/taskloop/shelf_digest/signatures.py (new): extract_signatures composes Identities/open_source.
- tests/steps/test_shelf_digest_signatures.py (new): extract_signatures fixtures.
- src/taskloop/shelf_digest/identities.py: Identities, extract_identities; producer/source caller.
- src/taskloop/shelf_digest/source.py: CommittedSource, open_source; producer.
- tests/steps/test_shelf_digest_source.py: source callers/fixtures.
- tests/steps/test_shelf_digest_identities.py: objects, Inputs.extract and identity callers.
- tests/steps/real/test_shelf_digest_source_real.py: open_source consumers.
- tests/rules/test_policy.py: identity allowlist reference.
- docs/design/tl-8bh9.14.186.1.2/plan.md: revised plan.

## Read list
- src/taskloop/shelf_digest/source.py:9-82 — source port.
- src/taskloop/shelf_digest/identities.py:28-41 — inputs.
- src/taskloop/shelf_digest/identities.py:196-230 — producer/source caller.
- tests/steps/test_shelf_digest_source.py:16-41 — Tree fixtures.
- tests/steps/test_shelf_digest_identities.py:26-79 — commit fixtures and producer caller.
- tests/steps/test_shelf_digest_identities.py:160-176 — producer caller.
- tests/steps/test_shelf_digest_identities.py:217-226 — missing-input caller.
- tests/steps/real/test_shelf_digest_source_real.py:21-85 — source consumers.
- tests/rules/test_policy.py:392-392 — allowlist reference.

## Contract
Intent: extract_signatures accepts Identities and the repository port used by open_source.
Effect: CommittedSource reads exact commits; index package modules and resolve AST bindings. No stored state.
Result: ordered Signature records or explained failure, never partial success. Records retain identity, commit, public/defining names, path/range, kind and canonical declaration. Failure enums cover decode/parse, unresolved/unsupported exports; retain ReadFailure causes.
Resolve relative/absolute imports, assignment aliases, star re-exports and exported submodules. Respect static __all__; otherwise use nonprivate local declarations and explicit package-local re-exports. Cache locally; detect cycles.
Retain function parameters/defaults/annotations, async/overloads, type parameters, class bases/fields/methods, constants and both alias declaration forms; omit bodies/docstrings.

## Work packages
1. models.py, declarations.py: records/formatting; closes A3.
2. exports.py, signatures.py: resolution; closes A1, A2, A4.
3. New test file: independent expected records for A1–A4. Run just check and just test once each, last.

## Acceptance behaviours
A1: Aliases, chains and exported submodules resolve correctly; private/unrelated names stay absent.
A2: Cycles terminate, retaining reachable declarations; unresolved cycles, dynamic exports and invalid source return explained failures.
A3: Declaration forms retain signature semantics without executing source.
A4: Repeated/reordered inputs produce equal ordered records; changed pins update affected signatures/provenance; body-only edits preserve signature text.
