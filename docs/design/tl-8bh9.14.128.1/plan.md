# Depth
Medium: this part has two behaviours, continuing a saved session through the harness and keeping ordinary retries fresh. No owner decision is missing and no dependency is explicitly unlanded. Evidence budget: 12 model calls total. Assessment uses the supplied task text alone; the parent task's larger scope is excluded.

## Size
Estimated changed files: 4, including this plan, `src/taskloop/agents/launch.py`, `tests/steps/test_agent_launch.py` and `tests/steps/test_repeat.py`. No new source or test files. Estimated model calls for one implement attempt: 24.

Independent behaviours: 2.

- Explicit continuation: given saved reference S, each supported harness prepares its native continuation of S. Acceptance: released-harness contract tests assert the native continuation argument, retained reference S in harness evidence and reported session identity after representative harness events; no fresh session identifier is allocated. Codex is the primary contract, with Claude and OpenCode covered through their existing resume support.
- Fresh ordinary execution and retries: without an explicit continuation request, initial execution and ordinary retries keep using fresh sessions. Acceptance: consecutive ordinary builds allocate distinct identifiers and contain no continuation arguments, and the existing repeated-plan execution test confirms that a previous attempt's session reference is not forwarded to the new launch.

This is one bounded adapter change. No database, recovery operation, scheduling, process lifecycle or restart integration changes belong to this part.

## Evidence and scope
The supplied glossary governs session, harness, agent, attempt, task, slot and worktree; no additional glossary terms are needed.

At source commit `e77b2d21284da5a42d8659d489f7eab8c6581a1d`, `AgentLaunch.build` unconditionally generates `LaunchInputs.session` and never supplies `LaunchInputs.resume`. The only production build callers are `Attempts._launch` and merge resolution; both currently request fresh execution. The existing session latch records and checks native references, and remains the owner of that database interaction.

Installed `any-agent` 0.11.0 already exposes `LaunchInputs.resume`. Codex builds `exec resume` with an explicit reference and accepts that reference in its constructor to initialise evidence. Claude builds `--resume` instead of `--session-id`; OpenCode builds `--session` and initialises evidence from the resume reference. Use these owning APIs without constructing vendor command arguments in factory workflow code. No package upgrade or edits to installed dependency files are proposed.

The parent plan was inspected on `task/tl-8bh9.14.128`; this plan carries only its adapter contract. Parts 2 and 3 will supply durable recovery eligibility and lifecycle consumers. This part does not claim that factory restart already continues work.

## Read list
- `src/taskloop/agents/launch.py:18-46` — existing credentials, launch result and failure contracts.
- `src/taskloop/agents/launch.py:50-118` — access preservation, harness construction and fresh session producer; primary edit.
- `src/taskloop/agents/settings.py:107-129` — validated harness, model and access choices supplied to the adapter.
- `src/taskloop/ids.py:8-24` — owning fresh session identifier port.
- `src/taskloop/attempt.py:216-251` — ordinary launch caller and native reference callback integration.
- `src/taskloop/merge/resolve.py:53-74` — second production caller; preserve its ordinary fresh launch semantics.
- `src/taskloop/session.py:34-88` — existing reference latch and conflict reconciliation; consult without changing storage ownership.
- `tests/steps/test_agent_launch.py:23-64` — released-harness contract setup and deterministic session assertions; extend here.
- `tests/steps/test_agent_launch.py:67-108` — existing Codex access and environment assertions to retain for continuation.
- `tests/steps/test_agent_launch.py:126-159` — explained failures and strict answer decoding regressions.
- `tests/steps/doubles.py:481-500` — existing deterministic identifier fake; reuse without modification.
- `tests/steps/test_repeat.py:148-164` — previous-attempt execution setup for the retry regression.
- `tests/steps/test_repeat.py:259-280` — repeated-plan execution test; extend to assert fresh launch semantics with a saved previous reference.
- `tests/steps/test_attempt.py:52-101` — shared attempt constants, fixture and application construction used by adapter tests.
- `tests/steps/test_attempt.py:123-136` — semantic harness fake with reported session references.
- `pyproject.toml:9-27` — installed harness dependency and shared shelf revision; no dependency edits.
- `.venv/lib/python3.15/site-packages/any_agent/protocol.py:18-44` — released typed launch inputs, especially resume versus session.
- `.venv/lib/python3.15/site-packages/any_agent/harnesses/codex.py:72-125` — explicit continuation construction, evidence initialisation and access flags.
- `.venv/lib/python3.15/site-packages/any_agent/harnesses/codex.py:150-167` — native session event fixture for the Codex identity contract.
- `.venv/lib/python3.15/site-packages/any_agent/harnesses/claude.py:137-149` — native continuation argument supplied by the owning harness.
- `.venv/lib/python3.15/site-packages/any_agent/harnesses/claude.py:198-206` — saved reference initialisation in the released launch API.
- `.venv/lib/python3.15/site-packages/any_agent/harnesses/opencode.py:130-173` — temporary shell naming, native continuation and reference initialisation.

Dependency paths describe the current installed environment; consult the same pinned package files if the implementation environment relocates site-packages. Additional searches should only locate missed direct callers or changed named symbols.

## Implementation
1. Extend `AgentLaunch.build` with an explicit keyword-only `resume: str | None = None` input. `None` selects the existing fresh path. An explicit reference selects continuation, passes that exact reference through `LaunchInputs.resume`, and does not call `Ids.session`. Use the saved reference for the ancillary `session` input on that path, including OpenCode's shell naming. Do not infer continuation from retry inputs, prompt text or files. Reject blank, whitespace-containing or option-like references through the existing explained launch failure path; never turn an invalid continuation into a fresh launch.
2. Initialise `CodexHarness` with the saved reference as well as passing the resume input to its launch specification. Claude and OpenCode already initialise their evidence in `launch_spec`. Preserve credentials, working directory, model, effort, access policy, probe, supplied prompt, answer schema and output destination. Share existing preparation and cleanup between fresh and continued launches. If extracting code to stay below the 80-line function cap is needed, keep that extraction within the adapter.
3. Add contracts in `test_agent_launch.py` using real released harness specification builders and deterministic IDs, without running vendor executables. Assert each native argument targets S and the harness evidence retains S. For Codex, feed a representative `thread.started` event naming S and check the reported reference remains S. Assert preserved access, prompt/schema and output settings on the continuation path, using the harness's actual resume representation of sandbox settings. Include invalid-reference failure explanations and cleanup after launch preparation failures. Do not add workflow outcome vocabulary or new abstractions for this input.
4. Cover the fresh path with two successive ordinary builds and extend the existing repeated-plan test using its semantic harness fake: establish a prior reported session, repeat the attempt, and assert that the new launch has no resume argument and does not reuse the saved reference. Keep the ordinary attempt and merge callers on the default fresh path. Retain existing answer-decoding and access regressions.

## Verification and completion
Run `just check` and `just test` as the supplied focused gates, with the new adapter contracts and repeated-plan regression included. Use pytest functions and owning semantic harness fakes; run no live harness or whole-suite tests. Planning does not run implementation gates. Preserve the declared successor environment and installed dependencies; no baseline imports, PYTHONPATH workaround or dependency edits.

Completion requires all supported harness contracts to target the saved session, ordinary retries to remain fresh, useful explanations for rejected explicit references, and both supplied gates to pass. Record actual validation commands and outcomes in the implementation handoff. Durable recovery, database changes, deadline renewal and restart completion remain outside this part.
