# Registered-start prerequisite delivery

Status: **evidence**. Historical delivery record for a **built** owning-library prerequisite. The inspection-only
factory limitation below describes that checkpoint; later successor slices consume the mechanism. See the current
[README](../../../README.md) for factory capabilities.

Task: tl-8bh9.4.4.1. Owning library task: shelf-4426. Delivered 2026-11-09.

[Shelf PR 71](https://github.com/yoselabs/shelf/pull/71) was squash-merged as
`824040758e5dd44c751483adcfc3f542059338b7`. Its tree is
`36aa1c24ac16ee4c8311a0fdd320eb8f411125d1`, exactly the independently reviewed and Linux/native-Mac-verified
candidate `5f77a6f97036146555f8c15f1b2103f5ad2fc11e`. The merge retains the current upstream subscription-login
safeguards. The owner explicitly authorized publication, merge and both releases.

Both annotated release tags were published atomically and verified remotely to peel to that merge commit:

- [stream-proc-v0.5.0](https://github.com/yoselabs/shelf/tree/stream-proc-v0.5.0/packages/stream-proc), tag object
  `3556652e42d02d286adfaffc411fbd1738d972dd`.
- [any-agent-v0.2.0](https://github.com/yoselabs/shelf/tree/any-agent-v0.2.0/packages/any-agent), tag object
  `d985e9071e53add4b23ab70855d4437495f07361`.

Native macOS 26.6.2 arm64, Python 3.12.13: locked normal gate passed with 124 tests; locked full gate passed with
4,966 tests, 11 skips and 90.98% coverage. Registered-spawn tests, native boot identity, process-group changes,
all five libproc tests and subscription-login safeguards passed. Strict typing reported zero errors; checkout clean.
The 221-second full gate exceeded an advisory timing budget, not a correctness limit. Skips were unavailable
GGUF models and platform-specific tests. Linux normal/full gates also passed: full JUnit 4,964 passed, 10 skipped,
90.85% coverage. Independent exact-tree integration review approved, including 50 focused tests.

The existing any-agent supervisor consumes the registered-start mechanism. The factory inspection-only runtime
does not yet consume agent execution, so no unused dependency pins were added. This delivery closes only the
registered-start prerequisite. Attempt-process/result persistence, semantic execution fakes, truthful whole-workload
stop proof and factory.db custody remain required under their existing owners before a plan command is registered.
The separate process-lock acquisition defect is shelf-7c34; anyllm cancellation/cleanup remains shelf-rf1y.
