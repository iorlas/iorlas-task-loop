# Depth
Medium: three behaviours cover verifying reported usage, carrying attempt usage and step/task totals in the read model, and displaying them beside duration. No owner decision is missing; the supplied supervisor decision confirms tl-8bh9.14.150 landed at d86605ef. Evidence budget: 12 model calls total.

## Size
Estimated changed files: 10, including this plan, tests and new modules. Estimated model calls for one implement attempt: 45 (including focused validation and required gates).

Three independently testable behaviours:

1. Attempt usage: the read model projects stored input as fresh input (`in - cached`), cached input, output and reported turns. Acceptance: a stored `(546541, 496768, 2375)` produces `(49773, 496768, 2375)`; reported turns remain unchanged, missing counts remain absent, and an explicit reported zero remains zero.
2. Step and task totals: aggregate each execution exactly once across retries and restarted history. Acceptance: two attempts of one step and an attempt of another yield the exact step and task sums; verification rows do not duplicate their agent's usage, and missing/partial reports do not become zero or appear to be complete totals.
3. Dashboard presentation: use one formatter for attempt headers, rail row hover/step totals and task totals. Acceptance: all four fields appear beside attempt duration with existing harness/provider/model/effort context, rail hover exposes attempt usage and the step sum, the task view shows the task sum, and absent usage reads `not reported`.

These fit one implement attempt. No additional task split or owner decision is required.

## Evidence and usage contract
The checkout at source commit 6f703455 has no saved task plan or local changes. The supplied glossary definitions apply: an attempt is one execution try, a step groups those tries, and a session is the harness conversation. Tool calls and model requests must not be renamed or counted as attempts or harness turns.

The declared dependency is any-agent 0.11.0 from shelf's any-agent-v0.11.0 tag. Inspection of its installed source establishes:

- Codex consumes `turn.completed.usage` directly. Its adapter writes the same values into `tokens` and `cumulative` and increments turns for that completion event. Thus `t_* == c_*` and `turns == 1` are expected for one completed harness turn containing many tool calls; they do not demonstrate one model request. Its summary documents raw cumulative usage for resumed threads, requiring subtraction of an earlier total by a resuming caller.
- Claude normalizes total input to fresh input plus cache reads plus cache writes, cached to cache reads, and output to reported output. It uses the result's aggregate usage and `num_turns`; when the result is absent it can aggregate request usage while turns remain absent.
- OpenCode sums each step's fresh input, cache reads and cache writes, sums output plus reasoning, and increments turns for steps reporting tokens. Its reported turns therefore have different granularity from Codex's.

Factory `AgentLaunch.build` supplies a new session and no resume input. The dashboard can therefore project the stored attempt `tokens` once without subtracting another execution or summing `cumulative` into it. Show turns as **reported turns**, with a brief harness-dependent explanation in hover text; do not invent model-request counts. No new harness adapter or dependency upgrade is needed. If inspection during implementation finds a changed producer or a newly resumed launch, reassess this assumption before showing its totals.

`ExecutionFacts` already preserves nullable token and turn counts. `AttemptStore` stores them, and `AttemptLoads._execution` already reads them into the execution returned to dashboard collection. Add no SQL, schema version, log reader, transcript reconstruction or factory state fallback.

## Implementation
Add a small immutable typed usage value to `dash_model.py`, following the dashboard's existing in-process read-model representation and `asdict` serialization. Counts are optional integers. Keep enough coverage information on aggregates to distinguish complete sums, sums of reported values only, and no report. A missing execution or missing field stays unknown; zero is valid only when explicitly reported. Fresh input requires both total input and cached input. Negative or internally inconsistent counts must not produce negative displayed usage: treat affected fields as unavailable and mark coverage incomplete.

Add new `src/taskloop/dash_usage.py` for the dashboard's projection and aggregation operation. It consumes typed `ExecutionFacts` and typed dashboard values, without harness names, backend JSON or IO. In `dash_task._agent`, obtain facts from the already collected `result.execution` and attach projected usage. In `build_task`, compute step and task aggregates from the actual agent attempt entries, including past/restarted chains and retries. Synthetic verification rows and non-agent checks contribute neither usage nor a missing-agent count. Avoid counting one execution both as an agent entry and as its verification. Do not restrict totals to the current chain. An empty task has no reported usage.

Expose step totals and a task total on `TaskDetail`, keyed by the existing step identity; do not add a new closed vocabulary. Sum each metric's known values, retain null when none is reported, and include missing/partial attempt coverage so a subtotal cannot look complete. The browser consumes these server totals rather than reimplementing aggregation. `dash_server._json` already serializes the dataclass tree; verify that contract without adding another endpoint.

Add new `src/taskloop/dash/static/usage.js` as the shared presentation helper. Show exact, grouped integer counts with explicit fresh input, cached input, output and reported turns labels. Use `not reported` for absent fields and whole absent reports; qualify totals that cover only reported values. Keep the existing duration and harness/provider/model/effort/access text in the selected attempt pane. `drawer.js` owns this header in the landed code; `lines.js` renders individual activity rows and needs no edit.

Pass server step totals from `drawer.js` into `rail.js`; preserve the landed rail's selection, retry and collapsed-history behaviour. Append attempt usage and the step total to row hover text without replacing existing gap/repeat explanations. Make the step sum visible in the rail as well, keeping attempt duration readable. The same step total may appear in hovers for its retries; it must not be summed again in the browser.

Pass the task total into `taskView` from `drawer.js`. Render its usage summary independently of tracker loading/error/absent states, since factory.db owns it. Show the total in the drawer's task context so it remains available while inspecting attempts. Reuse existing layout classes; no CSS build artifact is expected. Usage refresh follows the existing task-detail reload when an attempt concludes; do not derive live control state or counters from activity files. An unfinished attempt with no persisted report says `not reported`.

Add new `tests/steps/test_dash_usage.py` for focused read-model contracts using the existing dashboard fixtures and semantic tracker/process fakes. Extend `tests/dash/rail.test.js` with presentation contracts using its existing browser fixture. The ten expected changed files are this plan, dash_model.py, dash_task.py, new dash_usage.py, drawer.js, rail.js, taskview.js, new usage.js, new test_dash_usage.py and rail.test.js. Keep the repository's file/function caps; use the new module to keep dash_task.py below 400 lines.

## Validation
Read-model tests must cover full usage; null execution; partial metrics; reported zero; cached input unavailable or inconsistent; independent missing turns; multiple attempts/steps; retry and restart history; and exclusion of synthetic verification rows and non-agent checks. Assert public `build_task` results and their serialized shape, rather than testing each arithmetic helper. Test incomplete aggregates and no-attempt tasks explicitly. Use the existing agent-completion contract proving Codex tool activity can end with turns=1 and tokens=(29,13,7); the shelf producer findings above explain its meaning without live harness runs.

Browser contracts must check header/rail/task output, missing text, partial-total wording, preservation of gap/repeat hover explanations and existing rail selection/disclosure behaviour. Use the existing browser contract setup if available; record any unavailable browser execution explicitly. Do not introduce another runner or dependency for it.

Run focused pytest coverage for the new usage read-model tests, existing dashboard reads and agent completion with the declared successor environment. Then run the required `just check` and `just test` gates. Do not run whole-suite or live harness tests beyond those required focused gates. Record outcomes and any concrete remaining limitation in the implementation handoff. Cost in money remains deferred as requested.

## Read list
- `pyproject.toml:5-27` — declared Python environment and pinned shelf dependency.
- `src/taskloop/agents/launch.py:79-118` — fresh session producer; no resumed-thread accounting.
- `src/taskloop/attempt_types.py:179-193` — typed nullable execution facts.
- `src/taskloop/attempt_types.py:375-407` — normalized harness-result projection.
- `src/taskloop/attempt_store.py:40-56` — token/cumulative/turn columns written from facts.
- `src/taskloop/attempt_loads.py:118-145` — existing owning read of usage facts.
- `.venv/lib/python3.15/site-packages/any_agent/harnesses/codex.py:149-258` — pinned dependency's completion parsing, equal token/cumulative values and reported-turn semantics; consult only.
- `.venv/lib/python3.15/site-packages/any_agent/harnesses/claude.py:62-76` — inclusive input and cached-input normalization; consult only.
- `.venv/lib/python3.15/site-packages/any_agent/harnesses/claude.py:282-320` — aggregate result usage, missing result and reported turns; consult only.
- `.venv/lib/python3.15/site-packages/any_agent/harnesses/opencode.py:246-262` — step accumulation and reported-turn granularity; consult only.
- `.venv/lib/python3.15/site-packages/any_agent/harnesses/opencode.py:331-353` — terminal normalized usage result; consult only.
- `src/taskloop/dash_model.py:147-203` — attempt and task detail integration points for usage values and totals.
- `src/taskloop/dash_task.py:100-131` — attempt collection and existing run context.
- `src/taskloop/dash_task.py:232-290` — history collection and task aggregate integration.
- `src/taskloop/dash_server.py:156-159` — JSON serialization caller for the read model.
- `src/taskloop/dash/static/drawer.js:143-205` — task header, task-view caller and rail caller.
- `src/taskloop/dash/static/drawer.js:247-294` — selected attempt duration/run header and detail refresh.
- `src/taskloop/dash/static/rail.js:113-139` — attempt row duration and hover integration.
- `src/taskloop/dash/static/rail.js:199-222` — rail entry point and step-total integration.
- `src/taskloop/dash/static/taskview.js:31-62` — task total integration, including tracker-unavailable paths.
- `tests/steps/test_dash_read.py:1-58` — read-model fixtures, tracker fake and StatusPorts setup for the new tests.
- `tests/steps/conftest.py:102-143` — registered/checking execution fixtures for integration coverage.
- `tests/steps/test_agent_completion.py:49-117` — existing multi-activity Codex completion/usage contract.
- `tests/dash/rail.test.js:1-39` — existing browser contract imports, fixture and assertions to extend.
- `tests/dash/rail.html:1-13` — existing browser contract integration point.
