# worker-run v3: contract 3

Status: implemented in R21. Owner: delegate (the producer); `contract.json` in the delegate plugin is the source of truth,
and `tests/fixtures/delegate3/` vendors a copy for the tests. No v2 shim on either side.

- Every answer has `contract: 3` and `stop`: null, or `{reason, scope, permanence, retry{kind,at}, ref, resumable, partial, fix}`.
  The answer has no `status`, `next`, `lane_out`, `vendor_prework` or `to_wire_v2`.
- Reasons and their scope/permanence/retry are in `contract.json` `reasons`. `resumable` and `partial` appear on `network` and `killed` stops.
- `denied[]` is `{kind, tool, path, input}`; a `sandbox_limit` entry never counts.
- The consumer: `src/taskloop/adapters/delegate.py` (call, resolve) and `src/taskloop/domain/lanes/policy.py` (stop_of, decide)
  (`decide(stop, ctx)` -> Retry | Wait | WaitNet | NewThread | Reroute | Yield | Fail). Knobs: wait_cap_s 180, net_wait_cap_s 600,
  max_polls 3, poll_s 20, crash_rests (30, 120), bead_retries 1.
- Network: `call_state.py` keys one call on disk per step (`<bead>.call.json`); `netgate.py` probes; a resume sends `NETWORK_RESUME_DELTA`.
