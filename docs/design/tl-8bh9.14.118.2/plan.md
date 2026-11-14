# Depth
Small: dependency alignment is one behaviour in the packaging documentation and dependency declarations, with README agreement and a successful frozen install as its acceptance criterion. No owner decision is missing and no dependency is explicitly unlanded. Evidence budget: 6 model calls.

## Size
Estimated changed files: 3 normally (README.md, mise.toml and this plan), at most 5 if installation exposes a necessary pyproject.toml or uv.lock correction. No new runtime modules or test files are expected. This plan is the only new artifact.

Independent behaviours: 1. Dependency alignment is accepted when README package versions match the direct declarations and frozen resolutions, installation succeeds without rewriting the lockfile, and both required checks pass.

Estimated model calls for one implement attempt: 20, including bounded diagnosis of installation failures and the required checks. This is separate from the planning evidence budget.

## Current evidence
At source commit 7e493ce46744c51decefb70800da927f14e8adbc, README.md links to the dependency declarations and lockfile but has no package-version inventory. The seven direct runtime pins already agree with their lock entries: any-agent 0.11.0, beads-client 0.2.0, git-porcelain 0.21.0, process-lock 0.2.1, pydantic 2.14.3, sqlite-store 0.1.0 and stream-proc 0.9.0. Build and development dependencies are also declared explicitly. The mise.toml introductory comment incorrectly says there are no runtime dependencies.

Existing isolation tests check installed metadata against declarations, portable shelf sources, locked revisions and the shared any-agent/stream-proc commit. No existing task plan or unfinished task commit was found in the inspected branch history; the checkout was clean. Installation and implementation checks have not been run during planning.

## Implementation
1. Add a compact package-dependency inventory beside the README installation instructions. Copy the seven runtime versions from pyproject.toml; distinguish the build requirement hatchling 1.33.0 and development requirements pytest 9.2.0 and pytest-xdist 3.8.0. Keep pyproject.toml as the declaration owner and uv.lock as the frozen resolution owner, with links to both. Explain that stream-proc's package version is 0.9.0 while its shelf source uses any-agent-v0.11.0 so both packages resolve to the same shelf commit.
2. Correct the false no-runtime-dependencies comment in mise.toml by pointing to the package declarations. Preserve the existing tool pins. Preserve the declared Python requirement and the README's Python 3.15 prerequisite.
3. Verify frozen installation before changing declarations. Preserve the existing package pins and source tags unless an actual installation failure demonstrates an inconsistency within this task. If a correction is necessary, change only the affected declaration/source and regenerate the lockfile with uv, then repeat frozen verification. Preserve portable released sources and the shared any-agent/stream-proc revision. A broader API adaptation or dependency upgrade requires reassessing this bounded plan.

No application behaviour, schema, package version, external-tool version policy, onboarding workflow or CI changes are included. Use the supplied glossary meanings for task, plan, attempt and worktree; no new terminology is needed. Existing tests provide dependency contracts; this documentation change does not need tests that merely repeat the version table.

## Read list
- `README.md:152-170` — edit the installation and dependency documentation consumed by new users.
- `pyproject.toml:1-39` — authoritative build, runtime and development declarations, shelf source producers and installed CLI integration.
- `uv.lock:1-25` — frozen Python requirement and any-agent/beads-client resolutions.
- `uv.lock:45-94` — git-porcelain resolution and the consuming project's runtime/development lock metadata.
- `uv.lock:113-137` — process-lock and pydantic frozen versions and related dependency edge.
- `uv.lock:213-221` — sqlite-store and stream-proc resolutions, including the shared shelf revision.
- `mise.toml:1-10` — correct the stale dependency comment while preserving external-tool pins.
- `.python-version:1-1` — confirm the existing Python selection agrees with the documented prerequisite.
- `tests/rules/test_isolation.py:19-90` — existing consumers that verify installed package metadata, source portability and the shared shelf commit.

The existing integration points are the README installation commands, pyproject.toml build/source declarations, uv.lock resolution metadata and the installed-distribution checks above. There are no new implementation files. Additional searches should target a concrete mismatch or failed check only; do not read the justfile or repository profile during this attempt.

## Validation
During implementation:
1. Compare the README inventory with pyproject.toml and direct uv.lock entries, including build/development requirements and the stream-proc source distinction.
2. Run `just install` and an explicit `uv sync --frozen --no-editable` in this worktree. Confirm frozen installation succeeds and does not modify uv.lock; keep the installed distribution local to this worktree, with no baseline editable install or PYTHONPATH dependency.
3. Smoke-check the installed CLI with `uv run --frozen --no-sync python -I -m taskloop --help`.
4. Run the supplied required gates, `just check` and `just test`. Use their configured scope; add no whole-suite or live runs. Existing isolation tests cover metadata/source provenance.
5. Inspect the final diff for agreement and scope. Report check outcomes and any concrete installation blocker; do not claim installation success from static agreement alone.
