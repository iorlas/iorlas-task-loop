# Depth
Small: one cohesive behaviour pins supported external-tool versions and verifies consistency through existing local checks. No missing owner decision or explicitly unlanded dependency is identified. Evidence budget: 6 model calls total.

## Size
Estimate: 10 changed files across the complete task, including this plan, configuration, documentation, generated CSS, the developer validator and its tests. Most implementation changes already exist; the next implement attempt should primarily verify them, with corrections only where evidence requires them. One independent behaviour; approximately 30 model calls for one implement attempt.

Acceptance criterion: Git 2.56.0, Codex 0.162.1, Python 3.15.0 and Tailwind 4.1.11 have authoritative pins; managed locks, Python selection, documented installation and the CSS compiler agree. Existing local gates pass with these tools and reject missing/failed probes, mismatched executable versions and contradictory declarations. This is one tool-version consistency contract. No schema change or task dependency is required.

## Current evidence
At source commit `006bcd9d25bc77e8d6420af3c61930da6d9a08e5`, the worktree is clean. Commit `d9efd7d0` already supplies pins, build integration, documentation, a validator, tests and regenerated CSS. Task-branch history since the original plan contains no `Task-Loop-Wip:` trailer. Preserve the existing implementation and judge it against current acceptance; its presence does not establish completion.

`mise.toml` owns the four supported versions, with Git a separately installed system prerequisite. `.python-version` selects 3.15.0; package metadata and `uv.lock` retain the separate `>=3.15` compatibility range. The validator checks executable reports, managed lock versions/backends, Python selection and the generated CSS marker. Existing tests cover successful validation and malformed, missing, failed and contradictory inputs. `pyrefly.toml` includes the developer tools directory.

The prior hold reported missing Tailwind. This planning attempt confirms `/home/iorlas/.local/bin/tailwindcss` now reports 4.1.11, matching the supplied owner repair. This establishes availability here, not successful factory checks. No implementation gates were run. The justfile was deliberately not read, as instructed for planning; inspect its gate wiring during implementation.

The supplied glossary suffices: this plan concerns one task and a later implement attempt in its slot. No new term or glossary read is needed. Retain local enforcement and the parent's no-CI decision. Package versioning, dependency alignment and first-task onboarding remain outside this task.

## Implementation
1. Review the existing implementation through the read list. Preserve the pins and single authoritative configuration. Confirm the justfile passes successful version reports to the shared native Python validator, uses the uv-selected project interpreter and checks versions from both required gates, the prek lint path and the CSS build. Confirm probe failures cannot be mistaken for successful version output. Avoid rebuilding an already correct mechanism.
2. Correct only demonstrated gaps in that contract. Keep process execution in build recipes, with safe quoting and bounded probes; factory source and tests acquire no subprocess escape. Keep typed inputs, pydantic v2 configuration validation and useful expected/observed diagnostics. Verification must not silently install or upgrade tools. Preserve the package compatibility range and existing standalone tool backends. Regenerate locks with mise only if a declaration correction requires it.
3. Retain existing public contract tests; extend them only for an uncovered observable failure. Preserve installed-package isolation, file/function caps and typing rules. No new files are anticipated: `tools/check_tool_versions.py` and `tests/rules/test_tool_versions.py` already exist. Their callers/integration points are the justfile, prek's lint entry and pytest discovery. Keep `tools` in pyrefly's project scope.
4. Rebuild CSS only if needed to validate a changed build path, using the pinned compiler and existing input; inspect any artifact diff. Do not change sibling work or unrelated merged features. Do not weaken version validation to obtain a passing gate.

## Read list
- `mise.toml:1-17` — authoritative pins, prerequisite and managed installation producers.
- `mise.lock:31-78` — Codex and Tailwind versions, backends and downloads.
- `mise.lock:139-162` — managed Python lock entry and downloads.
- `.python-version:1-1` — uv interpreter selector.
- `tools/check_tool_versions.py:1-58` — typed declarations and executable formats.
- `tools/check_tool_versions.py:61-111` — validation operation and command-line boundary.
- `tests/rules/test_tool_versions.py:1-106` — existing success and failure contracts.
- `justfile:1-56` — existing build, probe and gate callers; read during implementation.
- `.pre-commit-config.yaml:1-10` — prek caller of the lint gate.
- `README.md:152-180` — installation and local verification instructions.
- `pyrefly.toml:1-6` — developer validator type-check integration.
- `pyproject.toml:5-18` — Python compatibility and declared validation dependency.
- `pyproject.toml:38-50` — pytest discovery and size limits.
- `uv.lock:1-3` — frozen package compatibility range.
- `tests/rules/test_isolation.py:16-38` — installed-package provenance constraints.
- `tests/rules/test_policy.py:13-60` — size, typing and process restrictions.
- `src/taskloop/dash/static/dash.css:1-1` — generated compiler marker.
- `src/taskloop/dash/static/dash.input.css:1-10` — CSS build input and registered sources.

Additional searches must target missed callers or changed declarations. No foundation plan is needed.

## Verification and completion
After `just install`, run `uv run --frozen --no-sync python -I -m pytest tests/rules/test_tool_versions.py`. Exercise the shared check with the actual supported executables, a deliberately wrong reported version and an unavailable executable using temporary inputs or an isolated PATH; leave the host installation intact. Confirm the real build recipes propagate a failed probe, not just the validator's synthetic tests.

Run the required `just check` and `just test` and report their actual results. Use these prescribed gates without adding whole-suite or live-test commands. A repeat requires a change or an unresolved failure. If setup still fails, report the exact failing prerequisite and observed result without changing global setup or weakening acceptance. Completion requires consistent pins and consumers, meaningful rejection coverage, and both gates passing. No tracker mutation, publication or Git write is part of this planning attempt.
