# Header
Task: tl-8bh9.14.186.2.1
Base: ac34381973c6101e485f53c0907a0bff90430f55
Depth: medium; three behaviours.
Owner decision missing: no. Explicit unlanded dependency: none.
Evidence budget: 12 model calls.
Size: 13 changed files, 3 independent behaviours, 55 model calls per implement attempt.

## Outcome and non-goals
Return the existing Digest from validated installed distributions. Reuse manifest reconciliation and static signature/documentation extraction; add installed metadata validation and captured source inputs.

Bounded facts, stale-evidence validation, token accounting, CLI changes and docs/shelf-digest.json belong to the other split tasks. These contracts need fixtures, not actual shelf API facts.

## Settled decisions
- Reuse committed manifest reconciliation for installed name/version and direct_url.json repository, revision, tag and subdirectory comparisons.
- Capture bytes once in the installed adapter; share extraction logic with explicit Git composition, without fallback.
- Map installed source paths deterministically to the existing package/subdirectory/src layout. Preserve packaged documents and module docstrings; fabricate no README or manifest.

## Open decisions
- None.

## Change map
- `src/taskloop/shelf_digest/source.py` — add Source protocol, opener type and immutable SourceSnapshot beside CommittedSource/open_source.
- `src/taskloop/shelf_digest/identities.py` — expose manifest-only reconciliation; extract_identities retains Git manifest validation.
- `src/taskloop/shelf_digest/installed.py` (new) — metadata models, distribution port/adapter and capture_installed_sources producing SourceSnapshots.
- `src/taskloop/shelf_digest/generate.py` — add generate_installed_digest; share extraction with generate_digest through explicit openers.
- `src/taskloop/shelf_digest/signatures.py` — extract_signatures consumes opener; producers: generate.py and documentation tests.
- `src/taskloop/shelf_digest/exports.py` — PackageExports/_parse consume Source; caller: signatures._collect.
- `src/taskloop/shelf_digest/documentation.py` — extract_documentation/_package_docs consume source port; callers: generate.py and documentation tests.
- `tests/steps/shelf_digest_fixtures.py` — extend complete_case/objects with distribution fixtures and openers.
- `tests/steps/test_shelf_digest_installed.py` (new) — integrate installed.py/generate_installed_digest for rejection and isolation tests.
- `tests/steps/test_shelf_digest_identities.py` — extend Inputs.extract coverage for manifest-only reconciliation.
- `tests/steps/test_shelf_digest_generate.py` — extend generate_digest callers with installed equivalence, ordering and failure cases.
- `tests/steps/test_shelf_digest_signatures.py` — adapt extract and direct callers in pin/body, ordering, missing-commit and later-package cases.
- `tests/steps/test_shelf_digest_documentation.py` — adapt both extractors' callers in complete-text, absent-docs, invalid-document and unreadable-file cases.
- `src/taskloop/shelf_digest/cli.py` — consult main/generate_digest caller; no edit.
- `src/taskloop/shelf_digest/render.py` — consult _Digest/render_digest consumer; no edit.
- `tests/cli/test_shelf_digest_cli.py` — consult wired/main and buffered output; no edit.
- `tests/steps/test_shelf_digest_source.py` — consult CommittedSource/open_source callers; no edit.
- `tests/steps/real/test_shelf_digest_source_real.py` — consult open_source callers; no edit.
- `pyproject.toml` — consult declared identity producer; no edit.
- `uv.lock` — consult locked identity producer; no edit.

## Read list
- `src/taskloop/shelf_digest/source.py:9-82` — reader/Git integration.
- `src/taskloop/shelf_digest/identities.py:14-113` — identity models.
- `src/taskloop/shelf_digest/identities.py:116-240` — reconciliation boundary.
- `src/taskloop/shelf_digest/generate.py:14-37` — new installed operation integration.
- `src/taskloop/shelf_digest/signatures.py:32-66` — source opening.
- `src/taskloop/shelf_digest/exports.py:58-94` — layout and parsing.
- `src/taskloop/shelf_digest/documentation.py:70-147` — document source consumption.
- `tests/steps/shelf_digest_fixtures.py:17-67` — new installed-test integration.
- `tests/steps/test_shelf_digest_identities.py:43-110` — manifest producers.
- `tests/steps/test_shelf_digest_identities.py:113-226` — failure expectations.
- `tests/steps/test_shelf_digest_generate.py:18-78` — generation callers.
- `tests/steps/test_shelf_digest_signatures.py:23-42` — caller helper.
- `tests/steps/test_shelf_digest_signatures.py:255-299` — direct callers.
- `tests/steps/test_shelf_digest_documentation.py:19-101` — both extractors' callers.
- `src/taskloop/shelf_digest/cli.py:15-33` — generation consumer.
- `src/taskloop/shelf_digest/render.py:16-53` — Digest fields.
- `tests/cli/test_shelf_digest_cli.py:16-85` — CLI contract.
- `tests/steps/test_shelf_digest_source.py:16-38` — reader construction.
- `tests/steps/real/test_shelf_digest_source_real.py:21-84` — Git callers.
- `pyproject.toml:11-27` — declared pins.
- `uv.lock:14-25` — locked identity format.

## Contract
Intent: `generate_installed_digest(taskloop_repo, revision, distributions)` reconciles manifests, validates six installed records and calls shared extraction. A distribution port supports fixtures and stdlib metadata without shelf imports.

Effect: installed.py validates strict pydantic metadata and captures regular files once. Missing/duplicate distributions, invalid selectors, disagreements, unsafe paths and unreadable files fail with package/field/path context. Validate paths before reads; exclude bookkeeping. No execution, fetching or writes.

`Source` exposes commit, entries() and read(path). SourceSnapshot owns immutable bytes and sorted entries, without filesystem callbacks or caller-owned mutable containers. Index captures by commit; merge shared-commit prefixes, reject conflicting paths. Both extractors receive the same capture despite later file changes.

Result: retain Digest and its records; reuse IdentityFailure/ReadFailure with enum reasons and explanations. No partial collections, fallback or stored-state change.

## Work packages
1. Separate reconciliation/reader boundaries in identities.py, source.py, signatures.py, exports.py and documentation.py; adapt caller tests/fixtures. Preserve Git assertions. Closes acceptance 3's integration portion.
2. Add installed.py and test_shelf_digest_installed.py; extend identity/fixture tests. Closes acceptance 1, 2 and snapshot isolation in 3.
3. Add shared generation and generate_installed_digest in generate.py; extend generation tests for shared commits, ordering, post-capture mutation and late failure. Closes acceptance 3. After focused tests, run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last, preserving exit status.

## Acceptance behaviours
1. Six matching installed distributions produce the manifest-derived identities, including stream-proc's own version and its source commit shared with any-agent.
2. Missing, duplicate, malformed or disagreeing installed identity metadata returns an explained failure identifying the package and disagreement, with no partial digest.
3. Captured bytes drive the existing signature and documentation extractors deterministically; later file mutation cannot change the capture, and unreadable selected source or a later extraction failure returns no partial digest.
