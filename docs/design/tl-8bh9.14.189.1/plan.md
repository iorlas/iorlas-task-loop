# Header
Task: tl-8bh9.14.189.1; base: 3d13f3b4b6d8d549924eb8f78baf381748079db3
Depth: medium; two behaviours: timestamp exposure and partial reporting.
Owner decision: none missing; unlanded dependency: none.
Evidence budget: 12 model calls.
Size: 11 changed files, 2 behaviours, 60 implement model calls.

## Outcome and non-goals
Expose setup timing in inspection and a bounded sample report. Ten-future-attempt collection, median assessment, retention and cleanup belong to sibling work. Setup execution, clocks, schema and scheduling stay unchanged.

## Settled decisions
- Existing `setup_run.started_at` and `ended_at` are authoritative.
- Extend `tl step show` human and JSON output and add `tl step setup-times --backlog KEY`, using existing database/configuration flags and JSON output.
- Report ten most recent setup-owning implement attempts at most, one latest run each, ordered by start descending then attempt ID. Include unfinished/unsuccessful runs.
- A duration sample requires a passed conclusion, an end timestamp and a nonnegative finite difference. Other rows expose available timestamps and conclusion but contribute no duration sample.
- Count usable displayed samples, including zero; no median, verdict, waiting or retention action.
- Repeats and answer repairs that retain another attempt's environment add no samples; inspection continues to identify the original setup owner.

## Open decisions
- None.

## Change map
- `src/taskloop/setup_store.py`: `COLUMNS`, `SetupRow`, `_row`; expose timestamps; add `SetupSample` and `SetupStore.samples` query.
- `src/taskloop/setup_timing.py` (new): `SetupTimingReport`, `report`; consume `SetupStore.samples`, derive durations/count, return existing `Failed` on store failure.
- `src/taskloop/cli_step.py`: `register`, `OPERATIONS`; add report handler through `cli_composition.open_reads`.
- `src/taskloop/result_data.py`: `StepResult`, `_step_data`; serialize report and inspection timestamp/duration fields.
- `src/taskloop/show_render.py`: `setup_line`; render persisted start, optional end and eligible elapsed seconds.
- `src/taskloop/step_render.py`: `_step_lines`; render report rows and usable sample count via the new report result.
- `tests/steps/test_setup_store.py`: update `SetupRow` fixtures; verify times and selection.
- `tests/steps/test_setup_timing.py` (new): exercise `setup_timing.report` with partial inputs.
- `tests/cli/test_setup_timing_cli.py` (new): exercise `cli_step` report text/JSON against fixture databases.
- `tests/cli/test_step_cli.py`: update `FAILED_SETUP`, `RUNNING_SETUP`, inspection and repeat expectations.
- `docs/design/tl-8bh9.14.189.1/plan.md`: retain this implementation contract.
- `src/taskloop/environment.py`: consult timestamp producers `Preparation._reconcile`, `_setup`, `_concluded`.
- `src/taskloop/attempt_status.py`: consult `show_attempt`, `_checks_shown`, `SetupShown` for owner association.
- `src/taskloop/hold_facts.py`: consult `SetupStore.latest` consumer; preserve `unsettled`.
- `src/taskloop/check_repeat/repair.py`: consult `SetupStore.latest` consumer; preserve `unsettled`.
- `src/taskloop/slot_release.py`: consult `running` consumer; preserve release observation.
- `src/taskloop/check_release.py`: consult `running` consumer; preserve release observation.
- `src/taskloop/cli_composition.py`: consult `open_reads` composition.
- `src/taskloop/exit_codes.py`: consult `exit_code` success fallback.
- `src/taskloop/factory_schema.py`: consult attempt/setup definitions; no schema change.

## Read list
- `src/taskloop/setup_store.py:35-163` — row decoding, latest/running readers and persisted timestamp writers.
- `src/taskloop/environment.py:247-261` — interrupted-run conclusion producer.
- `src/taskloop/environment.py:295-320` — existing reuse and setup-start boundary.
- `src/taskloop/environment.py:395-397` — normal setup-end timestamp producer.
- `src/taskloop/attempt_status.py:105-126` — setup inspection carrier.
- `src/taskloop/attempt_status.py:270-306` — original attempt selection and setup association.
- `src/taskloop/attempt_status.py:327-338` — checks setup inspection.
- `src/taskloop/cli_step.py:51-80` — parser integration.
- `src/taskloop/cli_step.py:243-255` — read-only handler pattern.
- `src/taskloop/cli_step.py:306-353` — dispatch, JSON/text and result exit handling.
- `src/taskloop/result_data.py:30-39` — result union.
- `src/taskloop/result_data.py:142-170` — inspection and result serialization.
- `src/taskloop/show_render.py:72-77` — setup text.
- `src/taskloop/step_render.py:42-88` — human result dispatch.
- `src/taskloop/cli_composition.py:108-126` — existing read-only connection composition.
- `src/taskloop/exit_codes.py:51-69` — default successful report handling.
- `src/taskloop/factory_schema.py:108-140` — implement/repeat ownership selection.
- `src/taskloop/factory_schema.py:178-187` — persisted timing fields and nullability.
- `src/taskloop/hold_facts.py:58-68` — latest setup's unsettled process consumer.
- `src/taskloop/check_repeat/repair.py:80-88` — retained setup observation.
- `src/taskloop/slot_release.py:120-140` — release setup observation carrier.
- `src/taskloop/check_release.py:270-285` — setup release observation consumer.
- `tests/steps/test_setup_store.py:22-164` — constructors and fenced-store fixtures.
- `tests/cli/test_step_cli.py:70-80` — direct setup fixtures.
- `tests/cli/test_step_cli.py:413-473` — persisted inspection and repeated-owner checks.

## Contract
Intent: expose measurements without workflow effects.
Effect: `SetupRow` gains required `started_at: float`, `ended_at: float | None` decoded from existing columns; update constructors without defaults. Preserve process, conclusion, highest-run selection and fencing. Share duration eligibility between inspection and reporting.
Effect: read-only `SetupStore.samples(backlog)` joins setup to implement owners (`previous_attempt_id IS NULL`), selects each owner's highest run, orders and limits to ten. Return validated pydantic v2 `SetupSample` values: attempt/task/repo IDs, run, timestamps, existing conclusion enum. SQL stays here; checks, land and inherited environments add no samples.
Result: pydantic v2 `SetupTimingReport` holds ordered rows, nullable `duration_seconds` and `sample_count`. Any sample count succeeds immediately without a verdict. Unfinished, failed or backwards-clock rows expose raw times and null duration; human output explains from recorded facts. Never substitute live elapsed time.
Result: inspection JSON adds `started_at`, `ended_at`, `duration_seconds` under `setup`; absent setup stays null and repeats retain the owner's ID. Report JSON excludes tokens; text uses seconds/readable timestamps. Reuse configuration/database failures without creating state or reading logs, tracker, Git or processes.

## Work packages
1. `setup_store.py`, store tests: expose times and bounded reads, preserve fencing/release. Closes A1 and A2 selection.
2. `setup_timing.py`, CLI/render modules and tests listed above: report samples and inspect times; update fixtures. Closes A1-A3.
3. Run focused store/report/inspection tests with the permitted isolated pytest command. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last; both must pass.

## Acceptance behaviours
A1: Store reads and inspection expose persisted timestamps and eligible differences; unfinished runs have no duration and repeats identify their setup owner.
A2: Reports list at most ten distinct implement owners for the backlog, including unusable rows, with exact usable count; checks, land, repeats and older runs cannot inflate it.
A3: Empty, partial and full text/JSON reports make no decision or state change; failed/backwards-clock rows remain visible without sample durations, and absent databases create no files.
