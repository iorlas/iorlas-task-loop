# Skip dashboard socket tests when loopback is denied

Task: `tl-8bh9.14.164`. Status: implemented.

The dashboard tests must report skips with a clear capability reason when the
environment denies loopback sockets. They must continue exercising the real
server when sockets are allowed. This plan changes test support and test wiring.

## Current code

- `tests/cli/test_dash_server.py` starts `DashServer` through its `served`
  fixture. Its eleven socket-dependent cases currently error during setup.
  Three other tests in this module check static assets, safe rendering and the
  in-memory `Hub`; those do not need sockets.
- Two tests in `tests/cli/test_dash_composition.py` also need real sockets: the
  missing/incompatible database response and the occupied-port refusal. The
  no-dashboard test in that module does not.
- `DashServer` creates an IPv4 TCP server bound to `127.0.0.1`.
- There is no existing CLI conftest or shared loopback probe. The separate
  `tests/steps/conftest.py` owns factory fixtures and is not CLI test support.
- The justfile's `test` target installs the current package and runs the focused
  `tests/cli`, `tests/steps` and `tests/rules` checks. `check` installs the package
  and runs lint, types and import contracts.

## Implementation

1. Add one non-autouse, session-scoped `require_loopback` pytest fixture in
   `tests/cli/conftest.py`. This fixture owns both the capability probe and the
   skip decision. On first demand, create an `AF_INET` / `SOCK_STREAM` socket,
   bind it to `("127.0.0.1", 0)`, and close it immediately with a context manager.
   Use an ephemeral port, with no external network, server thread or subprocess.
   Pytest caches the fixture result for the session (per worker under xdist).
2. If creation or binding is denied with `EPERM` or `EACCES`, call `pytest.skip`
   with a reason such as `Loopback TCP sockets unavailable in this environment:`
   followed by the OS error. Let other errors propagate. Inspect the actual
   capability rather than sandbox variables, platform names or agent identity.
   Do not catch errors from the dashboard tests or from `DashServer` itself.
3. Make `served` depend on `require_loopback`, so the probe finishes before any
   server construction. Apply `pytest.mark.usefixtures("require_loopback")` to
   the two socket-dependent composition tests. Do not mark whole modules or
   make the fixture autouse: the four socket-free dashboard cases must run even
   when loopback is denied. Keep all existing dashboard assertions.
4. Add focused pytest behavior coverage in
   `tests/cli/test_loopback_support.py`. Use controlled socket stand-ins and
   in-process pytest sessions to exercise the actual shared fixture: permission
   denial at creation and binding produces skips with the reason, an allowed
   probe lets consumers run, and unrelated socket errors remain errors. Check
   that multiple consumers share one probe, acquired sockets close, and a test
   without the fixture still runs on denial. Pytest's bundled `pytester` support
   may be enabled for this verification; add no dependency or process launcher.
   Keep the probe implementation solely in the CLI conftest.

No production code, factory state, runtime permission handling, command targets
or dependency pins need to change. Do not add per-test exception handling,
global network skips or an alternate socket probe.

## Verification and completion

- After `just install`, run the focused support and dashboard tests using
  `uv run --frozen --no-sync python -I -m pytest -q -rs` with the three CLI test
  files named above. Controlled sessions prove both capability branches without
  requiring host permission changes.
- In a socket-denied environment, the existing dashboard files should show
  thirteen socket-related skips and four passing socket-free cases, with the
  capability reason visible under `-rs`, and no permission-related failures.
  On a capable host those thirteen cases must execute and pass; the controlled
  allowed-probe check alone does not establish real server behavior.
- Run the required `just check` and `just test` targets. Both must pass; do not
  broaden to whole-repository or live tests. Record actual results and identify
  which real socket environment was available rather than claiming both ran.
- Preserve Python 3.15+, installed-package isolation, existing architecture
  contracts and size caps. No new `Any`, casts or ignore escapes.

Completion means the shared capability decision removes the reported sandbox
failures while retaining real dashboard socket coverage wherever it can run.

## As built

The session-scoped `require_loopback` fixture in `tests/cli/conftest.py` owns
the probe and permission-denial skip. The server fixture and the two composition
tests require it; the four socket-free dashboard cases still run independently.
`tests/cli/test_loopback_support.py` uses in-process pytest sessions with controlled
sockets to cover EPERM and EACCES at creation and binding, allowed consumers,
one probe per session, socket cleanup and propagation of unrelated socket errors.

Verification on 2026-11-13 used the socket-denied agent sandbox:

- `just install` passed.
- `uv run --frozen --no-sync python -I -m pytest -q -rs
  tests/cli/test_loopback_support.py tests/cli/test_dash_server.py
  tests/cli/test_dash_composition.py` passed: 11 passed, 13 skipped. Each dashboard
  skip reported `Loopback TCP sockets unavailable in this environment: [Errno 1]
  Operation not permitted`.
- `just check` passed lint, type checks and all nine import contracts.
- `just test` passed: 3215 passed, 13 skipped in 182.28 seconds.

The allowed branch was verified with controlled sockets. Real dashboard sockets
could not run in this environment; their assertions and server behavior are unchanged.
