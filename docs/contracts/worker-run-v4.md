# worker-run v4: contract 4

Owner: delegate (the producer), released in 0.56.0; `contract.json` in the delegate plugin is the source of truth,
and `tests/fixtures/delegate4/` vendors that release's schema for the tests. The engine speaks contract 4 only.

- Every answer has `contract: 4` and `stop`: null, or `{reason, scope, permanence, retry{kind,at}, ref, resumable, partial, fix}`.
  The answer has no `status`, `next`, `lane_out`, `vendor_prework` or `to_wire_v2`.
- Reasons and their scope/permanence/retry are in `contract.json` `reasons`. `resumable` and `partial` appear on `network` and `killed` stops.
- `denied[]` is `{kind, tool, path, input}`; a `sandbox_limit` entry never counts.
- The consumer: `src/taskloop/adapters/delegate.py` (call, resolve) and `src/taskloop/domain/lanes/policy.py` (stop_of, decide)
  (`decide(stop, ctx)` -> Retry | Wait | WaitNet | NewThread | Reroute | Yield | Fail). Knobs: wait_cap_s 180, net_wait_cap_s 600,
  max_polls 3, poll_s 20, crash_rests (30, 120), bead_retries 1.
- Network: `call_state.py` keys one call on disk per step (`<bead>.call.json`); `netgate.py` probes; a resume sends `NETWORK_RESUME_DELTA`.

The handshake (`route.py contract --json`) returns `{contract: 4, capabilities: ["writer_exec_allow"], reasons, run_args}`.
Contract skew is refused. The optional request field `writer_exec_allow` defaults to `[]`; its CLI form is
`--writer-exec-allow '<JSON list of argv lists>'`. The engine sends compact JSON only for a nonempty grant, on writer-role
calls only. An empty grant sends no flag. The grant is part of the worker request fingerprint used for recovery.

The profile key `engine.writer_exec_allow` must be a list of nonempty lists of nonempty strings. Task-loop validates
only this shape; delegate validates binaries against its `host.json`. A nonempty grant requires the handshake capability
`writer_exec_allow`, profile `engine.writer_family` exactly `["openai"]`, and an effective bead pin of `["openai"]`.
Admission refuses any other configuration before a worker is called; task-loop never pins a family implicitly.
Delegate honors a nonempty grant only for a Codex (openai) write step and refuses other runners or reading steps with
`bad_request`. The answer format otherwise matches the previous contract.

A granted argv runs writer-written code on the host with network until NETISO (tl-7i9k.59) lands.
