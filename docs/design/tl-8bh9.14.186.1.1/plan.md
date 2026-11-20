# Depth

Medium: three independently testable behaviours—extracting pinned identities, explaining manifest mismatches and missing objects, and verifying immutable regular-file reads. No owner decision is missing and no dependency is explicitly unlanded. Evidence-gathering ceiling: 12 model calls, total for this planning attempt. The supplied glossary definitions apply; no missing term required a glossary read.

## Size

Estimated changed files: 8, including this plan, three new source files, three new test files and one import-contract edit. Estimated model calls for one implement attempt: 50, including focused verification and the two final gates. Three independent behaviours:

1. Pinned identities: given a task-loop source commit and its committed project/lock manifests, return exactly the six shelf identities with package name, version, repository URL, requested tag, package subdirectory and full resolved commit. Acceptance: semantic fixtures and the current manifest data produce the six correct records, including stream-proc at any-agent's commit with its own version.
2. Explained failures: reconcile project declarations, lock records and each package's pinned manifest; explain inconsistent or unavailable inputs. Acceptance: fixtures for mismatched name/version/source, duplicate or absent records, malformed input, missing commits/files and failed object reads return typed failures with nonempty explanations identifying the relevant package, path and expected/observed facts when available.
3. Immutable regular-file reads: read source only from resolved committed trees and accept regular-file modes. Acceptance: hermetic repository tests demonstrate that subsequent working-tree edits and ref changes cannot affect an opened source; unit cases accept 100644/100755 and reject symlinks, submodules and other non-regular entries, distinguishing absent paths from unreadable listed objects.

These estimates fit one bounded implement attempt. Public signature extraction and the documentation/generation command belong to the other owner-created children; this task supplies their identity and source-reading operations. No database/schema change or shelf modification is needed.

## Read list

- `pyproject.toml:5-50` — dependency versions, six source declarations, package inclusion and test discovery.
- `uv.lock:14-25` — any-agent and beads-client locked identities.
- `uv.lock:45-88` — git-porcelain pin and task-loop dependency/source metadata.
- `uv.lock:114-117` — process-lock pin.
- `uv.lock:213-221` — sqlite-store and stream-proc pins.
- `src/taskloop/git_views.py:25-49` — existing bounded, hardened Git view construction for callers.
- `src/taskloop/git_views.py:101-147` — existing commit/tree regular-file and missing-object semantics; consult, do not couple the digest to profile outcomes.
- `tests/steps/real/test_profile_real.py:1-66` — hermetic Git setup and regular-file integration-test pattern.
- `tests/rules/test_isolation.py:45-94` — existing consumers of the six pins and the shared any-agent/stream-proc commit constraint.
- `tests/rules/test_policy.py:13-59` — caps and restrictions on imports and typing escapes.
- `.importlinter:123-133` — broad urllib restriction; add only a parsing-specific exception for the new identity module.
- `pyrefly.toml:1-20` — strict edge-model typing and source/test search paths.
- `ruff.toml:1-16` — lint limits and process-import prohibition.
- `/home/iorlas/Workspaces/shelf/packages/git-porcelain/src/git_porcelain/api.py:261-263` — Repo.tree public contract, read only at c6384f0bf870a430b7bffe826f9f42b6138d7d44 via git show.
- `/home/iorlas/Workspaces/shelf/packages/git-porcelain/src/git_porcelain/api_results.py:218-244` — public Tree identity, entry modes and byte reads, at the same pinned commit via git show.
- `/home/iorlas/Workspaces/shelf/packages/git-porcelain/src/git_porcelain/real_read.py:128-152` — verify the owning Git implementation pins its resolved object before listing/reading, at the same pinned commit via git show.
- `/home/iorlas/Workspaces/shelf/packages/git-porcelain/src/git_porcelain/errors.py:17-64` — adapter exception translation, at the same pinned commit via git show.
- `/home/iorlas/Workspaces/shelf/packages/any-agent/pyproject.toml:1-18` — pinned package identity at 14bb4512c383c174d8db580d66d1c270aa656dee via git show.
- `/home/iorlas/Workspaces/shelf/packages/stream-proc/pyproject.toml:1-15` — own version under any-agent's tag, at 14bb4512c383c174d8db580d66d1c270aa656dee via git show.
- `/home/iorlas/Workspaces/shelf/packages/beads-client/pyproject.toml:1-16` — package manifest at af5189bc5a04dd1b068a62575a95c4fd99771369 via git show.
- `/home/iorlas/Workspaces/shelf/packages/git-porcelain/pyproject.toml:1-16` — package manifest at c6384f0bf870a430b7bffe826f9f42b6138d7d44 via git show.
- `/home/iorlas/Workspaces/shelf/packages/process-lock/pyproject.toml:1-15` — package manifest at d3d611ca15e07bacbf39727d14174f06bdc59e2a via git show.
- `/home/iorlas/Workspaces/shelf/packages/sqlite-store/pyproject.toml:1-16` — package manifest at 18d3164893f95dc82e391a7226652d286d9c4663 via git show.

Shelf paths identify existing files, but implementation must consult the specified immutable revisions, never shelf's working-tree contents. Additional reads should be targeted searches for changed declarations or missed callers.

## Implementation

Create the feature folder `src/taskloop/shelf_digest/` with these new files:

- `__init__.py`: package description only.
- `source.py`: the digest's narrow committed-source reader and typed read results. Accept the owning shelf Repo interface; resolve the requested task-loop revision once to a commit, retain its resolved Tree, and use each locked full shelf commit for package reads. Expose immutable identity, entry listing and regular-file byte reads needed by identity extraction and the later signature task. Translate backend failures here, with generic outcomes and adapter-supplied explanations. Reuse the regular-file semantics demonstrated in git_views without importing profile-specific models or changing their callers.
- `identities.py`: the typed identity extraction operation. Decode UTF-8 and TOML with native Python and validate TOML boundary shapes with pydantic v2 models. Parse lock Git URLs structurally using urllib.parse, including percent-encoded subdirectories; add the single direct-import exception to `.importlinter`. This imports no HTTP client and enables no network action. Keep known closed outcomes as enums/classes with one edge representation and no new glossary vocabulary.

The operation takes explicit task-loop source and shelf repository inputs. The future generation entry point will construct real views through the existing GitViews API; this part is called directly by tests and introduces no CLI wiring. Preserve the small import closure: source reading depends on the Git API, identity extraction on source reading and edge validation, and neither on factory scheduling, tracker clients or database stores.

Read `pyproject.toml` and `uv.lock` from the same resolved task-loop commit. Select the six shelf declarations, reconcile their exact dependency versions and source selectors against the unique locked package records and task-loop lock metadata, and require full immutable commit fragments. Do not derive a package version from its tag: stream-proc is version 0.9.0 under any-agent-v0.11.0. Preserve the existing shared-commit constraint. Reject ambiguous/missing declarations and malformed or unsupported source values with contextual explanations. Validate package-relative paths before reading them.

For each identity, read `<subdirectory>/pyproject.toml` at its locked shelf commit and compare its project name/version with the task-loop declaration and lock. Derive identity data from these committed inputs rather than installed distributions, the digest tool's own import environment, mutable refs, shelf checkout files or hardcoded version/SHA tables. The six current manifest objects were available during planning and their names/versions agree; failure fixtures must exercise disagreement rather than changing real dependency pins.

Resolve commits before further reads; an absent commit differs from an absent path, a non-regular tree entry and an object that was listed but cannot be read. Accept modes 100644 and 100755. Do not follow committed symlinks or gitlinks or use a filesystem fallback. A complete success contains all six validated identities; failures expose no partially successful identity collection. Missing objects are explained without fetching or modifying shelf. Git command names and exception types remain inside the adapter, not the identity result vocabulary.

Add three new test files:

- `tests/steps/test_shelf_digest_identities.py`: semantic fixtures for complete extraction and project/lock/package-manifest disagreement. Include reordering, percent-encoded paths, the shared any-agent/stream-proc pin, malformed TOML/source fields, duplicate/missing records and an alternate valid pinned version proving values are derived. Keep fixtures local to the slice; do not copy the baseline test bootstrap or add installed-package discovery.
- `tests/steps/test_shelf_digest_source.py`: semantic source fakes for read outcomes, mode checks and explanation coverage, including a listed object that becomes unreadable and infrastructure failure. Assert observable results rather than private helper calls.
- `tests/steps/real/test_shelf_digest_source_real.py`: hermetic temporary Git repositories through git_porcelain.testing, following the existing profile test's setup. Commit project/lock/package inputs, open the pinned sources, then modify checkout contents and move a ref; verify results still describe the original committed inputs. Include executable regular files and non-regular entries. No network, personal repositories, direct subprocess calls or live tests.

Only the new files, `.importlinter`, and this plan are expected to change. Existing pin producers and installed-metadata callers remain as evidenced integration contracts. Keep source files at most 400 lines, functions at most 80, test files at most 800, and use no Any/cast/ignore escape. Do not add package/signature extraction, rendered digest artifacts, a CLI command, runtime fallback, state storage or unused general-purpose Git abstractions.

## Verification and completion

During implementation, use the project interpreter and installed package after `just install`. If focused verification is needed, run only the permitted form, selecting one new test file at a time: `uv run --frozen --no-sync python -I -m pytest -q <file> --tb=short | tail -40`. Do not invoke ruff or pytest directly.

Once implementation, tests and review are complete, run these required gates exactly once each, last, and retain their actual exit status with shell pipefail:

1. `just check 2>&1 | tail -60`
2. `just test 2>&1 | tail -40`

Completion requires all three acceptance criteria and both gates to pass. Report focused results and gate outcomes; no publication or merge is authorized by this plan. Planning itself does not run implementation gates.
