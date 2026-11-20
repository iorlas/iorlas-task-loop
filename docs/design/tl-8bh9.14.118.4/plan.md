# Depth
Small: one behaviour in the package metadata owner—replace version `0` with a meaningful version that installed metadata reports correctly. No missing owner decision or explicitly unlanded dependency is identified. Evidence budget: 6 model calls total.

## Size
Estimated changed files: 4, including this plan, `pyproject.toml`, `uv.lock` and `tests/rules/test_isolation.py`. Independent behaviours: 1. Estimated model calls for one implement attempt: 12.

Acceptance criterion for the behaviour: after installing the current package, the declared version, the root package's locked version and `importlib.metadata.version("iorlas-task-loop")` all equal `0.1.0`; both `tl version` output formats report that installed version. `just check` and `just test` pass.

## Read list
- `pyproject.toml:1-36` — build backend, authoritative package version, dependencies and wheel configuration.
- `uv.lock:59-94` — root package version and dependency records that must remain consistent.
- `src/taskloop/cli.py:108-112` — existing installed-metadata reader and plain/JSON output producer.
- `src/taskloop/cli.py:149-153` — version command registration and argument parsing.
- `src/taskloop/__main__.py:1-5` — installed module entry point calling the CLI.
- `tests/cli/test_cli.py:81-86` — existing acceptance coverage for both version output formats.
- `tests/rules/test_isolation.py:1-38` — installed-distribution provenance test and imports; integration point for the version regression assertion.
- `README.md:152-169` — supported installation, isolated invocation and required check workflow.

## Implementation
Use the static version `0.1.0` for the successor's initial meaningful package version. The task does not prescribe a release numbering policy; this bounded choice makes no stable-API promise and requires no new version machinery.

1. Change only the project version in `pyproject.toml` from `0` to `0.1.0`. Keep it the single authoritative declaration consumed by the existing build backend.
2. Refresh `uv.lock` so the `iorlas-task-loop` package record carries `0.1.0`. Preserve dependency versions, Git revisions and lock schema; inspect the diff for unintended dependency changes.
3. Extend `test_noneditable_install_matches_current_source` in `tests/rules/test_isolation.py` to compare the declared version, root lock record and installed distribution version, and reject the placeholder `0`. Use its existing TOML and metadata readers. This checks the installed artifact rather than merely repeating a constant assignment. Keep the existing CLI test for plain and JSON output using that metadata.

No new implementation files are planned. This plan is the only new artifact. The CLI already reads installed metadata and needs no runtime change. Dependency alignment, tool pinning and first-task onboarding remain in their separate tasks.

## Verification
After the version and lock changes, run `just install` to rebuild and install the current successor package into this worktree's declared environment. Run the focused existing tests through that installed environment:

```bash
uv run --frozen --no-sync python -I -m pytest tests/rules/test_isolation.py::test_noneditable_install_matches_current_source tests/cli/test_cli.py::test_version_prints_the_running_package_version
uv run --frozen --no-sync python -I -m taskloop version
uv run --frozen --no-sync python -I -m taskloop version --json
```

The module commands must print `0.1.0` and `{"version": "0.1.0"}` respectively. Complete the required `just check` and `just test` gates through the factory's checks step; do not add separate whole-suite or live test runs. A stale installed wheel must fail the metadata comparison, so reinstall after any subsequent package metadata edit. No implementation checks were run during planning.
