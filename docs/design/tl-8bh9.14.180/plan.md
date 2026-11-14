# Depth
Medium: three behaviours configure compaction per attempt, measure the 4-versus-4
trial, and apply the adoption rule. No owner decision is missing and no dependency
is explicitly identified as unlanded. The supervisor must run the trial after the
other token optimizations have landed. Evidence budget: 12 model calls total.

## Size
Estimated changed files: 8, including three source files, three test files, this
plan and a new measurement report. Estimate: 70 model calls for one implement
attempt, including offline verification and report analysis. The eight measured
implement attempts are separate supervisor executions, not nested work performed
by this implementing agent. No schema version change or shelf change is needed.

Three independently testable behaviours:

1. Attempt configuration: an admitted Codex implement attempt with a threshold of
   100000 launches with that override; an unset control omits it. The stored policy
   survives decoding and repeats, and the plan-step setting remains independent.
2. Trial measurement: a report contains four treatment and four control initial
   implement attempts, all required measurements, evidence references and the
   complete associated retry chains. Missing evidence is explicit and prevents a
   claim that the experiment is complete.
3. Adoption: the report computes median input tokens per landed implement step
   and adopts only when treatment reduces that median by at least 10% and has no
   more failed answers. A failing or unevaluable comparison leaves the threshold
   unset outside the recorded trial.

## Evidence and supported setting
The checkout is source commit `58bea2a81143889b616d8873b112a8eaaa46eb1c`.
There was no saved task plan or task-specific work-in-progress history to reuse.
The supplied glossary definitions apply: an attempt is one execution try, a step
is one bounded operation, and land includes integration and confirmed completion.
No additional glossary terms are needed.

The [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
documents `model_auto_compact_token_limit` as the automatic history-compaction
threshold; omission uses model defaults. The [CLI reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
documents repeatable `-c key=value` overrides for noninteractive execution.
Therefore the documented per-attempt threshold prerequisite is satisfied in the
documented interface. Recheck it against the executable used for the trial and
record its version. If that harness version does not support this documented
override, record the finding and stop the experiment without a substitute.

The pinned any-agent v0.11.0 is shelf commit
`14bb4512c383c174d8db580d66d1c270aa656dee`. Its `CodexAccess.config()` supplies
per-launch overrides, already extended by `FactoryCodexAccess`. The factory
captures `CodexPolicy` in its existing policy JSON and passes the admitted
`AgentSetting` to `AgentLaunch.build`. This gives the threshold the same owner
and lifetime as the attempt's other launch settings.

## Implementation
Add an optional, strictly positive integer `model_auto_compact_token_limit` to
the existing Codex input and stored Codex policy. Reject booleans, fractional
values, zero and negative values. Default to absent. Carry it through resolution,
configuration provenance and display using the existing configuration boundary.
Use the vendor's documented key inside the Codex adapter; introduce no new
factory vocabulary or experiment scheduler.

Extend `FactoryCodexAccess` to receive this immutable optional value and append
the documented override when present. Preserve the existing access flags,
factory context limits and credential isolation. Exercise both sandbox modes
and the existing resumed-launch path. Do not change the model context window or
set a post-compaction target: the simulated 35K result is not a guaranteed
configuration outcome. Do not write the person's Codex configuration.

Use explicit invocation-specific factory machine configuration through the
existing `--config FILE` mechanism. The supervisor supplies identical effective
settings except for `agents.implement.access.model_auto_compact_token_limit =
100000` in treatment. Control omits the field, and neither arm changes plan
settings. Select the file before admitting the particular implement attempt;
do not switch a running rounds process or rely on reloading configuration.
Existing admitted attempts retain their captured setting. Do not install a
global factory default while gathering the trial.

The new `docs/design/tl-8bh9.14.180/measurement.md` is the experiment artifact.
It integrates existing attempt/status readers, execution facts, activity readers
and the supervisor's harness evidence. No new database tables, telemetry service,
raw SQL consumer, process launcher or shelf changes are part of this work.
The implementing agent can prepare the protocol and verify configuration
offline; it must not populate observed-result rows with simulated values.

## Supervisor trial and measurements
After the other token optimizations have landed, record their common source
revision and select eight ordinary tasks with usable bounded plans, excluding
the largest tasks. Record task sizes, model, effort, harness version and effective
settings before outcomes are known. Allocate four attempts to each arm in
advance, balancing ordinary task sizes and interleaving the arms to reduce time
effects. Keep other settings fixed. Do not silently replace failed samples or
rerun a task under the other arm after it has already been implemented.

For each of the eight initial implement attempts, record task, step, attempt and
session identities, arm, source revision, captured threshold, and references to
the owning evidence. Include a row per associated implement retry and a total
per implement step. Record:

- Total input tokens, including cached input, with cached input also shown
  separately where available. Include summary/compaction requests and all retry
  attempts; record separately any measured cost the ordinary usage total omits.
- Model requests and replies, including compaction requests when observable.
  Verify what the installed harness reports: `ExecutionFacts.turns` is forwarded
  from the harness and must not be assumed to count model requests. Use the
  supervisor's owning harness/session reader when it does not. Do not repair
  unrelated turn telemetry or count tool events as model calls.
- Repeat file reads: count later explicit reads of a path already read in that
  attempt, deduplicating the start/end records of one tool invocation. Record
  path/range evidence and separately identify post-compaction rereads when the
  compaction boundary is visible. Searches without file contents are not reads.
- `failed_check` repeat counts from typed attempt relationships, rather than
  searching rendered error text. Preserve other repeat causes separately.
- Answer validity for every implement attempt from the validated answer result,
  with invalid, absent and failed executions visible; and whether the task
  actually landed through the normal land operation. A published branch alone
  is not proof of land.

Read persisted usage and outcomes through owning readers and file evidence
through `EvidenceFiles` and the supervisor's existing harness readers. Activity
files are capped and normalized; they are not guaranteed to contain every
request or read. Missing/truncated evidence is unknown, never zero. Resolve it
from the owning session evidence before completing the report; if unavailable,
report an inconclusive experiment and retain the unset default. Observational
analysis of evidence must not become factory workflow control based on logs.

For each landed implement step, sum input tokens across its initial attempt,
all implement retries and measured compaction overhead. Do not include plan or
check-agent tokens in this implement-step metric. Calculate each arm's median
over its landed implement steps, naming the denominator and all non-landed
samples. Also show total arm input tokens, landing counts and failed-answer
counts across all assigned samples so failures cannot disappear through the
landed-only denominator. If an arm has no landed steps, its median is undefined.

Compute saving as `1 - treatment_median / control_median`, using unrounded
values and a positive control median. Adopt only when all eight samples are
fully measured, the comparison is defined, saving is at least 0.10 and treatment
has no more failed answers than control. Count invalid/absent answers and failed
agent executions explicitly; do not relabel them as missing samples. Report
repeat reads, model calls and failed-check repeats alongside the decision.
If eligible, the supervisor records adoption of 100000 for factory Codex
implement launches in the owning factory configuration. Otherwise it records
rejection or an inconclusive result and removes temporary trial configuration
through its owning operation. Never edit `~/.codex` or change planning defaults.

The task is complete only when the supervisor has run and documented the eight
real attempts and the resulting decision, or documented the specified unsupported
harness stop condition. Offline support and a report template alone do not meet
the experiment acceptance criterion. Live supervisor execution is distinct from
the repository's automated tests; this plan attempt runs no live experiment.

## Verification
Extend the existing settings tests to cover strict threshold validation,
independent step settings, configuration provenance/display, and policy-codec
roundtripping. Extend launch contract tests to assert the exact per-attempt
override, omission for control, preservation across resume and isolation between
launches. Cover the TOML configuration boundary in the existing CLI config tests.
Use semantic fakes and inspect launch specifications without launching a model.
Review the report's arithmetic against its rows, including the exact 10% boundary,
failed-answer comparison, retry totals and unknown measurements.

Run focused tests only as needed using the permitted isolated pytest command.
At the end of an implement attempt, run each required gate once, last:

```sh
just check 2>&1 | tail -60
just test 2>&1 | tail -40
```

## Read list
- `src/taskloop/agents/settings.py:25-32` — extend the Codex-owned typed policy.
- `src/taskloop/agents/settings.py:148-174` — per-step selection, overrides and persisted policy codec.
- `src/taskloop/agents/config.py:20-116` — input validation, resolution, provenance and display.
- `src/taskloop/agents/launch.py:50-118` — per-launch Codex configuration and its caller.
- `src/taskloop/machine_config.py:159-185` — existing TOML-to-settings integration.
- `src/taskloop/cli_composition.py:72-88` — explicit invocation configuration file loading.
- `src/taskloop/cli.py:121-129` — existing global configuration option.
- `src/taskloop/cli_step.py:61-74` — individual attempt admission and status command boundaries.
- `src/taskloop/attempt.py:218-239` — launch from the admitted immutable setting.
- `src/taskloop/attempt_loads.py:44-76` — retained implement settings used by later attempts.
- `src/taskloop/attempt_reads.py:50-78` — stored policy, repeat cause and attempt relationships.
- `src/taskloop/attempt_reads.py:273-282` — enumerate complete attempt evidence without hiding earlier attempts.
- `src/taskloop/attempt_types.py:180-199` — execution usage fact structure.
- `src/taskloop/attempt_types.py:384-409` — harness producer of usage and turn facts.
- `src/taskloop/attempt_result.py:8-37` — validated answer and failed execution interpretation.
- `src/taskloop/dash_usage.py:11-30` — existing usage projection and missing-value semantics.
- `src/taskloop/evidence_files.py:253-302` — activity and final execution artifact ownership and caps.
- `src/taskloop/activity_file.py:14-46` — typed activity records and invocation deduplication.
- `src/taskloop/land_status.py:1-80` — owning land status evidence for confirmed delivery.
- `tests/steps/test_agent_settings.py:24-81` — configuration, codec and validation test integration.
- `tests/steps/test_agent_launch.py:126-171` — launch, access and resume contract test integration.
- `tests/cli/test_config.py:1-70` — factory TOML configuration boundary test integration.
- `uv.lock:10-20` — verify the installed harness dependency pin before the trial.
