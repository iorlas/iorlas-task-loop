# Header
tl-8bh9.14.186.2; base 61cc8e66744c2e70bbddcd5431dd7933b7421f4c.
Depth: medium; identity, facts and bound are 3 behaviours.
No missing decision or unlanded dependency. Evidence: 12 model calls.
Size: 14 files including tests/artifact/plan; 3 behaviours; 70 implement model calls.

## Outcome and non-goals
Add installed input and bounded selection to the existing identity/signature/documentation generator. Deliver the validated artifact. Attempt-input integration and later-attempt observation are outside scope.

## Settled decisions
- Authorized installed input is explicit and read-only, sharing the landed extractors.
- Approximate tokens as ceil(complete UTF-8 JSON bytes / 4); no dependency.
- Store six full identities once; reference them by package.
- Check curated claims against source; never truncate to fit.
- Validate before output; source_commit records the manifest revision, freshness compares identities.

## Open decisions
- None.

## Change map
- src/taskloop/shelf_digest/source.py — PackageSource protocol: commit/entries/read; CommittedSource implements it.
- src/taskloop/shelf_digest/exports.py — PackageExports consumes PackageSource.
- src/taskloop/shelf_digest/identities.py — factor read_identities; extract_identities retains Git manifest validation.
- src/taskloop/shelf_digest/signatures.py — extract_package_signatures; extract_signatures delegates.
- src/taskloop/shelf_digest/documentation.py — extract_package_documentation; extract_documentation delegates.
- src/taskloop/shelf_digest/installed.py (new) — metadata validation/snapshots through PackageSource and read_identities.
- src/taskloop/shelf_digest/generate.py — generate_installed_digest shares extractors; generate_digest remains Git producer.
- src/taskloop/shelf_digest/bounded.py (new) — models, selection, evidence checks, rendering/validation over Digest.
- src/taskloop/shelf_digest/cli.py — main adds explicit installed/bounded selection; render_digest remains full renderer.
- docs/shelf-digest.json (new) — cli.main's validated installed bounded output.
- tests/steps/test_shelf_digest_installed.py (new) — metadata/snapshot contracts using shelf_digest_fixtures.
- tests/steps/test_shelf_digest_bounded.py (new) — fact, freshness and size contracts over generated/saved output.
- tests/cli/test_shelf_digest_cli.py — main's installed/bounded and failure contracts.
- docs/design/tl-8bh9.14.186.2/plan.md — scope and acceptance.
- Consult tests/steps/test_shelf_digest_generate.py — generate_digest/render_digest callers.
- Consult tests/steps/test_shelf_digest_identities.py — extract_identities callers.
- Consult tests/steps/test_shelf_digest_signatures.py — extract_signatures callers.
- Consult tests/steps/test_shelf_digest_documentation.py — extract_signatures/extract_documentation callers.
- Consult tests/steps/test_shelf_digest_source.py — CommittedSource constructors.
- Consult tests/steps/real/test_shelf_digest_source_real.py — CommittedSource/open_source contracts.

## Read list
- src/taskloop/shelf_digest/source.py:15-83 — source records and committed reader.
- src/taskloop/shelf_digest/exports.py:58-94 — source consumer and AST loading.
- src/taskloop/shelf_digest/identities.py:106-230 — reconciliation and extraction boundary.
- src/taskloop/shelf_digest/signatures.py:14-66 — per-package extraction and caller.
- src/taskloop/shelf_digest/documentation.py:97-151 — package documentation and caller.
- src/taskloop/shelf_digest/generate.py:14-37 — Digest and complete-generation producer.
- src/taskloop/shelf_digest/render.py:12-66 — existing edge models and canonical serializer.
- src/taskloop/shelf_digest/cli.py:15-33 — CLI composition and output boundary.
- tests/steps/shelf_digest_fixtures.py:34-67 — reusable six-package fixture construction.
- tests/steps/test_shelf_digest_generate.py:18-78 — generation/render callers and determinism.
- tests/cli/test_shelf_digest_cli.py:16-111 — CLI callers, wiring and failure coverage.
- tests/steps/test_shelf_digest_identities.py:160-176 — identity extraction caller contract.
- tests/steps/test_shelf_digest_signatures.py:260-305 — pin changes and extraction callers.
- tests/steps/test_shelf_digest_documentation.py:43-100 — documentation callers and failure contracts.
- tests/steps/test_shelf_digest_source.py:19-49 — committed-source construction contracts.
- tests/steps/real/test_shelf_digest_source_real.py:24-44 — committed-object reader expectations.
- pyproject.toml:9-27 — six declared versions and source selectors.
- uv.lock:1-226 — six resolved identities and root dependency metadata.
- .venv/lib/python3.15/site-packages/any_agent/supervisor.py:332-448 — timeout, registration, cleanup, finish and run.
- .venv/lib/python3.15/site-packages/any_agent/supervisor.py:141-153 — RunOutcome fields.
- .venv/lib/python3.15/site-packages/any_agent/supervisor.py:200-214 — injected clock consumers.
- .venv/lib/python3.15/site-packages/any_agent/protocol.py:60-92 — usage accumulation and Summary.
- .venv/lib/python3.15/site-packages/any_agent/events.py:58-68 — Tokens and TurnDone usage event.
- .venv/lib/python3.15/site-packages/any_agent/procs.py:51-69 — registration before target execution.
- .venv/lib/python3.15/site-packages/git_porcelain/api.py:353-424 — checkout exclusion and park contracts.

## Contract
Intent: read_identities reconciles manifests. Pydantic models validate six installed METADATA names/versions and direct_url.json URL/revision/subdirectory/commit. Missing, duplicate, mismatched or unreadable inputs fail.

Effect: snapshot regular files beneath repository-local site-packages, rejecting escapes/symlinks. PackageSource exposes immutable bytes, identity commit and extractor-relative paths with installed origins; fabricate no Git objects/manifests.

Result: generate_installed_digest returns Digest or typed explained failure. Strict pydantic BoundedDigest stores source_commit/identities/declarations/facts. Enum-identified facts carry qualified prose, package, relative path, symbol/range and source fingerprint. Check source assertions; unsupported changes or unresolved references fail.

Result: sort records/keys, emit one LF; validate identities, mandatory facts/references and complete-byte size before output. Full rendering stays in render_digest.

## Work packages
1. Add installed.py; factor source/exports/identities/signatures/documentation/generate. Test six matches and bad metadata with synthetic trees. Retain shared callers' contracts. Closes identity acceptance.
2. Add bounded.py/tests selecting qualified source-backed facts/declarations; reject missing claims or changed support. Closes fact acceptance.
3. Wire cli.py/tests; after just install, use uv run --frozen --no-sync python -I -m taskloop.shelf_digest with explicit --installed site-packages and --bounded. Save docs/shelf-digest.json; test repeatability, staleness and size edges. Closes bound acceptance.
4. Run just check 2>&1 | tail -60 and just test 2>&1 | tail -40 once each, last; record actual exit results.

## Acceptance behaviours
- All six artifact identities match pyproject.toml/uv.lock and the installed distributions; mismatches or missing inputs fail before output.
- Qualified facts survive: time.time timeout includes suspend, zero disables it; injected clock serves watchdog/turn logic; started registration precedes exec and failure forbids exec; unattended parent change triggers qualified cleanup; Summary/RunOutcome/finish roles and fields survive; TurnDone carries nullable token usage; park preserves branch/ignored-file safety, exclude affects this checkout and replaces its global excludes-file selection. Missing/stale support fails.
- Repeated generation is byte-identical, the committed artifact validates, and the complete serialized text measures at most 2,500 approximate tokens; exactly 10,000 bytes passes and 10,001 fails without partial output.
