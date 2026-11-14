# Header
Task: tl-8bh9.14.186.1.3
Base: 942f9a56359ca1c2e4a66d771fade4fd450e3853
Depth: medium
Reason: 3 behaviours; no missing decision or unlanded dependency.
Evidence budget: 12 model calls.
Size: 10 changed files including tests/plan; 3 independent behaviours; 55 implement model calls.

## Outcome and non-goals
Add documentation collection and a generation command to delivered identity reconciliation, immutable reads and signatures. Exclude fetching, installed-package inspection, source execution, tracker integration, automatic regeneration and a checked-in digest.

## Settled decisions
- Keep documentation separate from canonical declarations, which intentionally discard docstrings.
- Retain whole documents/docstrings, including qualifications, examples and warnings.
- Cover tracked README files, package Markdown/reStructuredText, text files under package docs, module docstrings and public declaration/member docstrings. Enumerate the pinned tree; absent docs differ from unreadable files.
- Record package, immutable commit, relative path and inclusive source lines; declaration docs also name public/defining symbols. Include overloads, members and aliased definitions.
- Emit canonical UTF-8 JSON with sorted records/keys, fixed indentation, LF and one final newline. Preserve text values; exclude timestamps and host paths.
- Expose `python -m taskloop.shelf_digest --checkout PATH --at REV --shelf PATH`; require shelf path; default checkout/revision to `.`/`HEAD`. No tracker configuration is needed.
- Finish collection and serialization before stdout. Failures explain themselves on stderr and exit nonzero.

## Open decisions
- None.

## Change map
- `src/taskloop/shelf_digest/documentation.py` (new): `Documentation`, `DocumentationFailure`, `extract_documentation`; use `CommittedSource` and `Signature` provenance.
- `src/taskloop/shelf_digest/generate.py` (new): `Digest`, `generate_digest`; compose source, identity, signature and documentation operations.
- `src/taskloop/shelf_digest/render.py` (new): JSON edge models and canonical `render_digest`.
- `src/taskloop/shelf_digest/cli.py` (new): `main`; compose `GitViews.checkouts`, generation/rendering and stream handling.
- `src/taskloop/shelf_digest/__main__.py` (new): invoke `cli.main`, following `taskloop.__main__`.
- `README.md`: document module invocation, inputs, coverage, canonical output and failure channels.
- `tests/steps/test_shelf_digest_documentation.py` (new): committed-tree fixtures using existing `Tree`/`FakeRepo` patterns.
- `tests/steps/test_shelf_digest_generate.py` (new): six-package, canonical output and late-failure fixtures.
- `tests/cli/test_shelf_digest_cli.py` (new): stream/exit tests with injected Git views.
- `docs/design/tl-8bh9.14.186.1.3/plan.md`: maintain this implementation contract.
- `src/taskloop/shelf_digest/source.py`: consult `CommittedSource.entries/read`, `open_source`; production callers: `_validate_package`, `extract_signatures`; test callers below.
- `src/taskloop/shelf_digest/identities.py`: consult `PackageIdentity`, `Identities`, `extract_identities`, `_validate_package`; producer for generation; test callers below.
- `src/taskloop/shelf_digest/signatures.py`: consult `_collect`, `_signature`, `extract_signatures`; producer: `PackageExports`; `canonical_declaration` caller: `_signature`; test callers below.
- `src/taskloop/shelf_digest/exports.py`: consult `PackageExports._parse`, binding producer for signatures.
- `src/taskloop/shelf_digest/models.py`: consult `Signature` and failures consumed by declarations, exports and signatures.
- `src/taskloop/shelf_digest/declarations.py`: consult `canonical_declaration`, consumed by signatures.
- `tests/steps/test_shelf_digest_identities.py`: consult `Inputs.extract` and direct `open_source`/`extract_identities` failure callers.
- `tests/steps/test_shelf_digest_signatures.py`: consult `extract` and direct `extract_signatures` pin, ordering and failure callers.
- `tests/steps/test_shelf_digest_source.py`: consult `test_open_resolves_once_and_explains_missing_or_unavailable_commits`.
- `tests/steps/real/test_shelf_digest_source_real.py`: consult all `open_source` commit-stability, file-mode and unavailable-object callers; read only.

## Read list
- `src/taskloop/shelf_digest/source.py:10-82` — read failures, regular-file checks and immutable source resolution.
- `src/taskloop/shelf_digest/identities.py:14-41` — package inventory and identity results.
- `src/taskloop/shelf_digest/identities.py:192-230` — identity producer.
- `src/taskloop/shelf_digest/signatures.py:14-66` — signatures and aliases.
- `src/taskloop/shelf_digest/models.py:10-49` — signature kinds and extraction failures.
- `src/taskloop/shelf_digest/exports.py:13-33` — parsed module and binding structures.
- `src/taskloop/shelf_digest/exports.py:58-94` — module discovery and parsing boundaries.
- `src/taskloop/shelf_digest/declarations.py:42-76` — public members and erased docs.
- `src/taskloop/git_views.py:26-49` — CLI Git composition.
- `src/taskloop/__main__.py:1-5` — module invocation convention.
- `src/taskloop/cli.py:113-159` — existing command registration.
- `pyproject.toml:8-47` — package inclusion, interpreter and declared dependencies.
- `README.md:1-38` — placement and style of command documentation.
- `tests/steps/test_shelf_digest_identities.py:22-85` — identity fixtures.
- `tests/steps/test_shelf_digest_signatures.py:20-83` — alias fixtures.
- `tests/steps/test_shelf_digest_signatures.py:254-307` — ordering/failure callers.
- `tests/steps/test_shelf_digest_source.py:71-95` — source-opening failure callers.
- `tests/steps/real/test_shelf_digest_source_real.py:18-44` — commit stability caller; read only.
- `tests/cli/test_profile_cli.py:1-40` — CLI fixture and stream-capture conventions.

## Contract
Intent: `generate_digest(taskloop_repo, revision, shelf_repo)` resolves the source once, reconciles six identities and collects at locked commits. Reuse typed failures; `DocumentationFailure` explains invalid text or extraction failure. Return no partial collection.

Effect: Git views and `CommittedSource` read objects. Static Python parsing respects encodings. Retain module, class, method, nested public class and overload docstrings and alias associations. Deduplicate documents by package/path. Absent docstrings are allowed; listed documents must be readable regular files and decode successfully.

Result: immutable `Digest` contains source commit, identities, signatures and documentation. Pydantic v2 JSON models share one serializer. Sort by package, path, range and public symbol. Buffer rendering before stdout; argument, Git, identity, signature, documentation and rendering failures explain themselves on stderr with nonzero exit. Success emits once and exits zero.

## Work packages
1. Add `documentation.py` and documentation tests: acceptance 1, including overloads, aliases, absent docs and invalid text.
2. Add `generate.py`, `render.py` and generation tests: acceptance 2 with six-package fixtures, reordered trees and changed pins.
3. Add `cli.py`, `__main__.py`, CLI tests and README usage: acceptance 3, including late failure. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
1. Committed documents and public API docstrings retain complete qualifications, examples and warnings, with exact package/commit/path/range provenance and correct alias/member associations.
2. Identical committed inputs generate byte-identical complete JSON despite enumeration order; changed documentation or pins change the appropriate content/provenance without consulting checkout text.
3. The module command emits one complete digest on success; invalid arguments, missing objects, reconciliation/extraction failures and rendering failures exit nonzero with an explanation and empty stdout, including failure in the final package.
