# Header
Task: tl-8bh9.14.169
Base: c746f0c33774f858dd2fda5e2e39d30c6c145ae1
Depth: medium; three behaviours
Decisions missing: none. Unlanded dependencies: none stated.
Evidence budget: 12 model calls.
Size: 9 files incl. tests/plan; 3 independent behaviours; 45 implement model calls.

## Outcome and non-goals
Carry a validated bind address to the dashboard listener and report its exposure. Port selection, read-only handlers and lifecycle already exist; address selection and disclosure remain. Supplied discussion establishes independent scheduling, with no overlapping implementation. Exclude authentication, proxy deployment, profile configuration and factory state changes.

## Settled decisions
- Accept IPv4 and IPv6 address literals using stdlib `ipaddress`; reject hostnames without DNS resolution.
- Keep 127.0.0.1 as the default and retain port 0, dashboard disabling and startup-failure continuation.
- Keep the loopback Host-header restriction, adding the selected loopback literal's correctly formatted authority when needed. For explicit non-loopback binding, accept proxy-forwarded Host names: the operator supplies the authenticated proxy boundary.
- The startup notice identifies the actual listener and describes the dashboard as read-only and unauthenticated. Non-loopback notices and the guide state that exposure is the operator's explicit choice and requires a proxy with sign-in.
- Use the existing dashboard startup failure result and reason; expand its explanation to address as well as port failures.

## Open decisions
- None.

## Change map
- `src/taskloop/cli_step.py`: `register`, `_dash_request`, `_rounds`; parse the address beside the port, propagate the typed value and format the listener/disclosure notice, including IPv6 brackets.
- `src/taskloop/dash_composition.py`: `DashRequest`, `serving`; add the typed host field, pass it to `DashServer`, retain cleanup and include the requested address in bind failures; `_ports` consumes the same request and needs no read-path change.
- `src/taskloop/dash_server.py`: `DashServer.__init__`, `address`, `_handler`; bind the selected literal with the appropriate socket family, retain the address result, and distinguish loopback Host restrictions from explicit proxy exposure. Update loopback-only documentation.
- `src/taskloop/step_refusal_guide.py`: `REFUSALS` entry for `dashboard_port`; cover unavailable addresses as well as occupied ports.
- `tests/cli/test_cli_flags.py`: `Dashboard.serving`, dashboard selection/output tests and interruption assertions; update request expectations, exercise validation, address propagation and notices in human/JSON modes.
- `tests/cli/test_dash_composition.py`: `request`, `test_selected_delivery_uses_the_registered_checkout_and_shared_land_reader`, busy-port setup and `serving` callers; update request/server construction and verify selected-address forwarding, failure detail and cleanup.
- `tests/cli/test_dash_server.py`: `served`, `get`, `Stream`, endpoint and Host-header tests; adapt constructor consumers and cover address families, loopback rejection and forwarded Host access. Consult all fixture consumers.
- `README.md`: rounds dashboard guide; document address syntax, wildcard example, operator choice, sign-in proxy boundary and unchanged JSON notice routing.
- `docs/design/tl-8bh9.14.169/plan.md` (new): implementation plan; integration points are the existing CLI, request and server listed above.

## Read list
- `src/taskloop/cli_step.py:30-43` — constants and parser helper placement.
- `src/taskloop/cli_step.py:96-105` — dashboard argument registration and help.
- `src/taskloop/cli_step.py:191-224` — request producer, serving caller and startup output.
- `src/taskloop/dash_composition.py:26-37` — request fields and read-port producer integration.
- `src/taskloop/dash_composition.py:76-92` — server construction, failure result and lifetime.
- `src/taskloop/dash_server.py:1-24` — existing server imports and scope documentation.
- `src/taskloop/dash_server.py:219-302` — Host gate, stream handling, listener creation and shutdown.
- `src/taskloop/step_refusal_guide.py:135-140` — existing bind-failure guidance.
- `tests/cli/test_cli_flags.py:78-151` — serving fake, request expectations, output routing and interruption.
- `tests/cli/test_dash_composition.py:23-85` — request producers, constructor caller and serving consumers.
- `tests/cli/test_dash_server.py:88-159` — stream consumer, server fixture, HTTP helper and loopback security assertions.
- `tests/cli/test_dash_server.py:171-284` — endpoint/stream fixture consumers whose behaviour must remain intact.
- `tests/cli/test_dash_server.py:298-323` — remaining feed, tracker and attempt endpoint consumers.
- `README.md:104-108` — operator guide and JSON output contract.
- `docs/design/factory-on-sol/design.md:93-106` — proxy context; deployment choices remain outside this task.

## Contract
Intent: `register` converts `--dash-host`, including its default, to `IPv4Address | IPv6Address`. Names, URLs, CIDR networks and host:port combinations fail before rounds or dashboard effects. `DashRequest.host` carries the validated address; update its producers explicitly.

Effect: `serving` supplies host and port to `DashServer`. Select AF_INET or AF_INET6 from the address type, bind without name lookup and report the allocated port through the existing `tuple[str, int]`. Retain extraction of the first two socket address fields for IPv6. No process or tracker effects are added.

Result: success retains the existing address tuple and teardown. An OS bind failure yields the existing `Failed` result with requested host, port and OS explanation; rounds proceed without a dashboard. `None` still creates no server. Loopback requests require an allowed local authority; explicit non-loopback operation allows the proxy's public Host header for both ordinary GET and events. No authentication or write endpoints are introduced.

Rendering uses the actual allocated port and brackets IPv6 literals. Exposure classification uses the selected address's loopback property; wildcard addresses count as non-loopback. Dashboard notices continue to use stderr under `--json`, leaving stdout record shapes intact.

## Work packages
1. Address selection and listener: edit `cli_step.py`, `dash_composition.py`, `dash_server.py` and their three test files. Close A1 and A2 with parser rejection before side effects, typed propagation, listener-family assertions using a fake listener for non-loopback addresses, and existing local HTTP/stream coverage. Update every request/server producer listed in the change map.
2. Operator output and guidance: edit `cli_step.py`, `step_refusal_guide.py`, `README.md` and the CLI/composition tests. Close A3 with exact listener formatting, exposure disclosure, JSON routing and address-specific startup-failure coverage.
3. For focused tests, install first and use the permitted isolated pytest command for the three CLI test files. Run final gates once each, last: `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, preserving pipeline failure status. No live services are required.

## Acceptance behaviours
A1. Omission selects 127.0.0.1; valid IPv4/IPv6 literals reach the request unchanged in meaning, while names and malformed address input fail before execution opens rounds or a listener.
A2. The listener binds the chosen literal and address family with the selected or allocated port; loopback keeps rejecting foreign Host authorities, explicit non-loopback accepts forwarded proxy authorities for page/API/events, disabling creates no server, and bind failure permits rounds to continue with cleanup intact.
A3. Startup reports the actual host and port with valid IPv6 formatting and read-only/unauthenticated disclosure; non-loopback output and the guide explain explicit operator exposure behind a proxy with sign-in; JSON stdout remains unchanged and failure details identify the requested address.
