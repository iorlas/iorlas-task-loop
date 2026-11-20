# Header
Task: tl-8bh9.14.186.2.3; base: 29d4433dfbef492ac63654b766357cb87ddc0dc3
Depth: medium; three behaviours.
Decisions: settled; no explicitly unlanded dependency.
Evidence budget: 12 model calls.
Size: 4 changed files, 3 independent behaviours, 35 implement model calls.

## Outcome and non-goals
Installed capture, extraction, validation and bounded rendering already exist. Connect the CLI to that path and save reproducible output with regression coverage. Package upgrades, new fields, extractor redesign and factory integration are outside this change.

## Settled decisions
- Use `generate_installed_digest` with `InstalledDistributions`; remove the CLI's required `--shelf` argument. Retain `--checkout` and `--at` and their defaults.
- Read authorized pinned sources through installed capture, without fallback.
- Keep the existing identity and fact vocabularies and canonical encoding. Retain the renderer's complete-output bound of 2,500 UTF-8 bytes.
- Generate and reproduce at an explicit task-loop commit, recorded in the artifact.
- The six facts remain `timeout`, `suspend`, `started`, `summary`, `usage` and `park`, established by `CONTRACTS` and `validate_facts`.
- Reuse existing fixture distributions for CLI tests; artifact tests inspect repository files without external actions.

## Open decisions
- None.

## Change map
- `src/taskloop/shelf_digest/cli.py` — edit `main`: compose `generate_installed_digest` and `InstalledDistributions`, remove shelf-path parsing, preserve buffered success and explained failure.
- `tests/cli/test_shelf_digest_cli.py` — edit `wired` and CLI cases: inject `installed_case` distributions; cover defaults, explicit revision, module entry, rejected arguments, identity/source/contract/bound failures and empty stdout on failure.
- `docs/shelf-digest.json` — new generated artifact; integration points are `cli.main`, `generate_installed_digest` and `render_digest`.
- `tests/steps/test_shelf_digest_artifact.py` — new offline artifact checks; integrate with manifest identity fields, `FactName`, `CONTRACTS` and the canonical encoding/bound in `render_digest`.
- `src/taskloop/shelf_digest/__main__.py` — consult module entry caller of `cli.main`.
- `src/taskloop/shelf_digest/generate.py` — consult both generators and `_extract`, producing CLI and test results.
- `src/taskloop/shelf_digest/installed.py` — consult `InstalledDistributions`, `_validate`, `capture_installed_sources`; callers: installed generation and capture tests.
- `src/taskloop/shelf_digest/identities.py` — consult `PACKAGES`, `PackageIdentity`, `reconcile_manifests`, producing manifest identities.
- `src/taskloop/shelf_digest/facts.py` — consult `FactName`, `CONTRACTS`, `collect_facts`, producing facts for extraction and validation.
- `src/taskloop/shelf_digest/validation.py` — consult `validate_facts`, called by `_extract` and bounded-fact tests.
- `src/taskloop/shelf_digest/render.py` — consult `render_digest`, called by the CLI, generation tests and bounded tests.
- `tests/steps/shelf_digest_fixtures.py` — consult producers `complete_case`, `installed_case`, `MemoryDistributions`.
- `tests/steps/test_shelf_digest_generate.py` — consult callers of both generators and renderer.
- `tests/steps/test_shelf_digest_installed.py` — consult direct capture callers and installed-adapter failure coverage.
- `tests/steps/test_shelf_digest_bounded.py` — consult generation, validation and rendering callers for fact preservation, stale evidence and determinism.
- `src/taskloop/git_views.py` — consult `GitViews.checkouts`, the CLI's task-loop Git port.
- `pyproject.toml` — consult pinned versions and source selectors.
- `uv.lock` — consult locked identities and the shared any-agent/stream-proc commit.

## Read list
- `src/taskloop/shelf_digest/cli.py:1-36` — existing CLI composition and output boundary.
- `tests/cli/test_shelf_digest_cli.py:1-136` — CLI callers, wiring and failure coverage to update.
- `src/taskloop/shelf_digest/__main__.py:1-5` — executable module integration.
- `src/taskloop/shelf_digest/generate.py:17-74` — installed generation, extraction and result union.
- `src/taskloop/shelf_digest/installed.py:111-142` — metadata adapter and complete identity comparison.
- `src/taskloop/shelf_digest/installed.py:168-190` — validate all identities before immutable capture.
- `src/taskloop/shelf_digest/identities.py:14-43` — six names and identity fields.
- `src/taskloop/shelf_digest/identities.py:150-228` — reconciliation and manifest reader.
- `src/taskloop/shelf_digest/facts.py:12-38` — fact names and failure vocabulary.
- `src/taskloop/shelf_digest/facts.py:65-118` — source-backed required contracts.
- `src/taskloop/shelf_digest/validation.py:1-49` — evidence and contract validation.
- `src/taskloop/shelf_digest/render.py:10-52` — artifact structure, stable ordering and bound.
- `tests/steps/shelf_digest_fixtures.py:94-146` — installed fixture adapter and producer.
- `tests/steps/test_shelf_digest_generate.py:82-136` — existing installed generation guarantees.
- `tests/steps/test_shelf_digest_installed.py:14-93` — capture failures and snapshot guarantees.
- `tests/steps/test_shelf_digest_bounded.py:18-105` — required facts, attribution and contradictory evidence.
- `src/taskloop/git_views.py:26-49` — bounded checkout port.
- `pyproject.toml:6-30` — declared package identities and selectors.
- `uv.lock:15-25` — any-agent and beads-client identities.
- `uv.lock:46-85` — git-porcelain and task-loop dependency metadata.
- `uv.lock:115-117` — process-lock identity.
- `uv.lock:214-221` — sqlite-store and stream-proc identities.

## Contract
Intent: `cli.main(argv) -> int` selects checkout/revision and constructs `InstalledDistributions`. No new public model, state, stored field or outcome.

Effect: reconcile committed manifests, validate six installed identities, capture source, establish and validate facts, then render in memory before stdout. Generation/read/render failures explain on stderr, return nonzero and leave stdout empty.

Result: preserve the existing artifact fields. Compare each decoded identity's name, version, URL, tag, subdirectory and commit with manifests, including stream-proc's own version and shared any-agent commit. Preserve every fact's text and evidence indices. Save generated bytes.

## Work packages
1. CLI integration — change `cli.py` and its CLI tests to use installed fixtures and the installed generator. Close acceptance 1, including identity mismatches, late failures and module entry.
2. Artifact delivery — after `just install`, run `uv run --frozen --no-sync python -I -m taskloop.shelf_digest --checkout . --at <resolved-commit>`. Generate twice, compare bytes and save `docs/shelf-digest.json`. Add offline checks for six decoded identities against manifest pins, exact fact text/set, references, canonical JSON and bound. Existing generation validates source evidence. Close acceptances 2–3. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, retaining command failure status.

## Acceptance behaviours
1. The CLI succeeds from matching installed distributions with default or explicit checkout/revision; missing or mismatched identities and extraction/render failures return an explanation and no JSON bytes.
2. The saved artifact contains exactly the six manifest identities and all six required facts with valid source attribution; existing source validation rejects stale or contradictory evidence before output.
3. Repeated generation at one revision produces identical canonical bytes, including the final newline, within the existing complete-output bound; the committed artifact matches those bytes.
