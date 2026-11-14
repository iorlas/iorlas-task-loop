# Header
tl-8bh9.14.180.1 | Base eb074c8f977bbff8093124ce2379a792cae46fbe
Depth: medium; 3 behaviours in task text. Owner decision missing: no. Dependency unlanded: none explicit. Evidence: 12 model calls. Size: 16 changed files including tests/plan, 3 behaviours, 65 implement model calls.

## Outcome and non-goals
Typed settings, captured policies and the factory Codex override hook exist. Threshold validation, persistence and propagation remain. The parent owns experimentation; this change neither enables 100000 globally nor runs an experiment.

## Settled decisions
- Omitted/null means harness defaults. A supplied threshold is a strict positive integer token count; reject booleans, strings, floats and nonpositive values.
- Add `compaction_token_limit` to per-step machine settings and `AgentSetting`. Existing model/effort flags preserve it; no new CLI flag.
- A supplied threshold requires Codex; reject unsupported harness combinations before admission.
- Admission captures the value; repeat copies it; advancement selects the next step's settings.
- Store compaction separately from access policy. Add a nullable attempt column and bump schema 26 to 27 with a new DDL pin. Drain entries before discarding the older database; no migration.
- The existing factory-owned `config()` hook emits `model_auto_compact_token_limit` as a per-launch override; unset uses model defaults ([configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)). No new shelf API is proposed.

## Open decisions
- None.

## Change map
- `src/taskloop/agents/settings.py`: `AgentSetting`, `apply`, `decode_setting` validate, preserve and restore the threshold.
- `src/taskloop/agents/config.py`: `StepInput`, `_setting`, `resolve_agents`, `display` resolve the field and its provenance.
- `src/taskloop/agents/launch.py`: `FactoryCodexAccess.config`, `codex_access`, `AgentLaunch.build` carry a per-instance override.
- `src/taskloop/factory_schema.py`: `SCHEMA`, `ATTEMPT_ADMITTED`, `ATTEMPT_LOADED` add nullable positive integer storage and schema 27.
- `src/taskloop/admit.py`: admission's `insert_attempt` producer captures the selected value.
- `src/taskloop/admit_chain.py`: `PREVIOUS`, repeat admission and advancement's `insert_attempt` producer copy or select the value.
- `src/taskloop/attempt_reads.py`: `stored_setting`, listing projection and its decoder call restore the value.
- `src/taskloop/attempt_loads.py`: `retained_on` and registered admission's `stored_setting` calls restore the value; update indexes together.
- `src/taskloop/attempt.py`: consult `Attempt._launch`, the ordinary `AgentLaunch.build` consumer.
- `src/taskloop/merge/resolve.py`: consult resolution's `AgentLaunch.build` consumer; preserve default launches.
- `src/taskloop/machine_config.py`: consult `Effective.agents`.
- `src/taskloop/cli_step.py`: consult `_overrides`.
- `src/taskloop/round.py`: consult admission settings/overrides.
- `tests/steps/test_agent_settings.py`: extend validation, `apply` and both `decode_setting` callers.
- `tests/steps/test_agent_launch.py`: extend offline launch-spec coverage for threshold isolation.
- `tests/steps/test_admit.py`: cover initial capture with configured and absent values.
- `tests/steps/test_admit_chain.py`: cover repeat inheritance and next-step selection.
- `tests/steps/test_attempt.py`: cover persisted settings through reopened execution and retained inputs.
- `tests/steps/test_factory_schema.py`: append schema 27's DDL pin and storage assertions.
- `tests/cli/test_config.py`: cover display provenance and invalid input.
- `tests/steps/test_schema_words.py`: consult incompatible-version refusal coverage.

## Read list
- `src/taskloop/agents/settings.py:107-174` — models, overrides and codec.
- `src/taskloop/agents/config.py:20-116` — input, resolution and display.
- `src/taskloop/agents/launch.py:50-122` — override hook and launch consumer.
- `src/taskloop/factory_schema.py:45-120` — version and attempt constraints.
- `src/taskloop/factory_schema.py:264-274` — admitted/loaded projections.
- `src/taskloop/admit.py:264-320` — initial settings producer.
- `src/taskloop/admit_chain.py:60-68`, `src/taskloop/admit_chain.py:135-165`, `src/taskloop/admit_chain.py:335-365` — repeat projection and both producers.
- `src/taskloop/attempt_reads.py:104-124`, `src/taskloop/attempt_reads.py:300-329` — decoder and listing consumer.
- `src/taskloop/attempt_loads.py:58-69`, `src/taskloop/attempt_loads.py:125-165` — retained/admission consumers.
- `src/taskloop/attempt.py:218-228` — launch consumer.
- `src/taskloop/merge/resolve.py:46-64` — second launch consumer.
- `src/taskloop/machine_config.py:30-45` — effective settings container.
- `src/taskloop/cli_step.py:170-182` — flag producer.
- `src/taskloop/round.py:90-115` — admission settings inputs.
- `tests/steps/test_agent_settings.py:24-93` — validation and codec integration.
- `tests/steps/test_agent_launch.py:208-253` — existing launch-spec matrix.
- `tests/steps/test_admit.py:1-100` — admission fixtures.
- `tests/steps/test_admit_chain.py:271-291` — repeat integration.
- `tests/steps/test_attempt.py:65-180` — persisted execution fixtures.
- `tests/steps/test_factory_schema.py:14-29` — version guard.
- `tests/cli/test_config.py:222-247` — display and invalid configuration.
- `tests/steps/test_schema_words.py:33-90` — incompatible database refusal.

## Contract
Intent: `StepInput.compaction_token_limit` and `AgentSetting.compaction_token_limit` are optional strict positive integers, default null. Non-Codex settings require null. Restored settings pass the same validation. `apply` retains the field when applying existing overrides; display reports configured/default provenance.

Effect: admission writes `attempt.compaction_token_limit` with the other captured choices. SQL permits null or an integer greater than zero. Repeat preserves the captured value despite subsequent machine configuration changes; advancement captures the next step's choice. Registered admission, retained inputs and listing reconstruction feed the single setting decoder. Append projections where practical and update dependent positional indexes deliberately.

Result: `AgentLaunch.build` passes the captured threshold into the factory-owned Codex access adapter. Its `config()` emits exactly one `-c model_auto_compact_token_limit=N` for a supplied value, for both fresh and resumed launches. Unset emits none. The adapter owns this vendor key; no user configuration is rewritten and no class/global state carries a previous attempt's value. Existing sandbox and access overrides remain effective.

## Work packages
1. Settings/config and settings/CLI tests: close A1.
2. Schema, admissions, readers and admission/chain/attempt/schema tests: close A2 with reopened storage and next-step selection.
3. Codex adapter and launch tests: close A3 with distinct thresholds followed by an unset launch, fresh/resumed sessions and existing sandbox modes.
4. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each and last; retain exit statuses. No live invocation.

## Acceptance behaviours
- A1: Omitted/null and positive integer thresholds resolve; booleans, numeric strings, floats, nonpositive values and unsupported harness combinations fail before admission. Existing flags preserve the value and settings display identifies its source.
- A2: Admission, reopened execution, retained inputs and listings agree on the captured value. Repeat retains it after machine settings change; advancement uses the next step's selection. Incompatible databases remain refused under schema 27.
- A3: Fresh/resumed Codex launches receive exactly their captured override; unset launches receive none. Consecutive attempts do not contaminate each other or rewrite user configuration, and existing access overrides remain effective.
