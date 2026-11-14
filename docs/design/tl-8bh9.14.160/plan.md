# Per-step agent settings

Status: **design**. Task: `tl-8bh9.14.160`. Prepared 2026-11-14 against
`260d9183`; implementation and required checks remain to be done.

## Scope and evidence

An agent step chooses its harness, model, effort and access policy from machine
configuration. With no overrides, plan uses high effort and implement uses medium.
These defaults are the owner's convention, not an official vendor recommendation.
Explicit command-line flags override the configured choices; rounds need no model
or effort flags. Each attempt retains and displays the actual admitted choice.

The owner's 2026-11-13 scope decision is settled: use released `any-agent==0.9.0`,
including its typed Codex access and sandbox command builder. Accept configured
Claude and OpenCode steps with their typed policies, without sandbox or writable-root
preflight. Do not wait for a shelf release or reopen that decision. Harness priority
lists, routing, fallback, quota scheduling and session resume are separate work.

Read the [foundation plan](../tl-8bh9.8.7/plan.md) and [glossary](../../glossary.md).
The working tree was clean and the task branch had no `Task-Loop-Wip:` commit.
`bd show` for this task and `.149`, and `.149`'s comments, returned no matching task
in the supplied local tracker. No tracker claim or status was changed. The supplied
requirements and `.149`'s retained Git record are available evidence:

- Commit `6a268aeb` (`.149`, including `73640cf1` and `7aef8ad3`) records the typed
  harness stopgap, persisted harness/provider, dashboard header and reasoning line.
  There is no `.149` plan in that commit. `harness_choice.py` still owns both enums
  and `provider_of`; `launchable` returns a harness only for Codex.
- `machine_config.py` owns TOML defaults, strict keys and flag/file/default sources.
  `cli_step.py` requires model/effort for start, next and rounds, and supplies a
  non-optional Codex harness default. `StartRequest` and `NextRequest` carry these
  global values through `operations.py` and `round.py`.
- `admit.py`, `admit_chain.py` and `check_repeat/store.py` admit agent attempts.
  Ordinary repeats copy choices; advance chooses a new step's values. Failed-check
  implement repeats have a separate admission path which must retain the same rule.
- `Admission`, `attempt_loads.py`, `attempt_reads.py` and schema v19 persist/read
  model, effort, sandbox, harness and provider, but no complete typed access policy.
  `Attempts` is concretely typed to `CodexHarness`, uses Codex-only credentials,
  rejects a sandbox other than the fixed one, and constructs launch inputs itself.
- `access.py` owns raw Codex options and the implement folders/shell environment.
  `environment.Preparation.prepare` always passes a Codex probe into setup. Keep
  shared setup, reconciliation, safe cleanup and folder protections while removing
  that unconditional harness assumption.
- The installed 0.9.0 source supplies `Harness`, `LaunchInputs.access_policy`,
  `CodexAccess.sandbox_argv`, `ClaudeAccess` and OpenCode's constructor `Sandbox`.
  Claude settings are JSON content, not a file path at this boundary. OpenCode
  needs a launcher root, uses `write` and `--variant`, and does not consume the
  JSON-schema launch input. Its released shell sandbox uses macOS `sandbox-exec`;
  this task cannot promise OpenCode sandbox enforcement on Linux.

## Configuration contract

Choose the existing machine config, rather than adding repository profile settings
and another precedence layer. Add exactly two entries, `agents.plan` and
`agents.implement`, for the currently built agent steps. Checks and land do not
acquire an agent setting. Do not add a registry or new glossary term.

For example, a machine may explicitly repeat the built-in choices:

```toml
[agents.plan]
harness = "codex"
model = "gpt-6.1-sol"
effort = "high"
[agents.plan.access]
sandbox = "workspace-write"

[agents.implement]
harness = "codex"
model = "gpt-6.1-sol"
effort = "medium"
[agents.implement.access]
sandbox = "workspace-write"
```

Use `gpt-6.1-sol` for the default Codex model of both steps (the retained successor
smoke evidence already uses it). A different harness requires its model to be
named explicitly; never carry a Codex model or policy into another harness by
default. The settings contain one model identifier, including a provider prefix
where the harness needs one. Provider is a derived read-only fact from the existing
`provider_of(harness, model)`, never an independently configurable second truth.
Preserve `Provider.UNKNOWN` for unfamiliar OpenCode model IDs without routing them.

Define frozen pydantic v2 input models with forbidden extra fields and validated
paths/identifiers. The harness discriminates the access variant. Reuse the existing
harness/provider enums and shelf permission/sandbox enums; new closed factory
reasons use enums and one codec. Model and effort identifiers remain validated
vendor-owned text, as the current command accepts, rather than a guessed catalog.
Reject blank/control/flag-shaped identifiers, unknown steps, mismatched policy
fields, invalid modes and malformed policy documents with a key-specific explanation.

The access table has these harness-specific fields:

| Harness | Configuration | Translation inside the agent adapter |
|---|---|---|
| Codex | `sandbox` (default `workspace-write`) | Build a `CodexAccess`; retain the factory's network, approval, temporary-directory, config/rules and output-limit defaults. Apply step folders and shell environment to the effective workspace-write policy. |
| Claude | `settings_file` (required JSON object file), `permission_mode` (default `dontAsk`) | Read and validate settings; pass their captured JSON content and the typed mode as `ClaudeAccess`. |
| OpenCode | `sandbox_file` (optional JSON object with `readable`, `scratch`, `runners`) | Validate fields against a pydantic input model; construct the released `Sandbox`. Absence uses that library's defaults. |

Paths are absolute or home-expanded using the existing explicit home input; reject
relative paths. Reject unreadable files and wrong JSON shapes before admission.
Do not inspect Claude/OpenCode sandbox enforcement, platform support or writable
roots as configuration validation. A supplied typed policy is accepted. In
particular, do not reject a configured OpenCode step just because this host is Linux.
Policy files are trusted machine inputs, not repository instructions. Add no raw
argv/config escape, executable override, credential store or remote catalog lookup.

Omitting an entry supplies its built-in Codex setting; a partial Codex entry merges
field defaults. Changing harness selects that harness's policy defaults and requires
its model (and Claude settings file). Invalid file values still fail if a flag would
override them, matching existing config behavior. `tl config show` prints effective
per-step fields and their flag/file/default sources, with policy paths and a safe
policy summary rather than file contents.

`--harness`, `--model` and `--effort` become optional overrides with parser default
`None` on start, next and rounds. Keep the spellings and explain their precedence.
An explicit flag applies its field to each newly admitted step in that command;
otherwise that step's configuration supplies it. A harness-only override must not
reuse a different harness's model/policy: refuse an incomplete effective choice
before claims/reservations and explain the missing configuration. No access-policy
CLI flags are needed for this task. Existing task selection and deadlines are unchanged.

Resolve a fixed configuration snapshot at command startup, including policy-file
contents. A running rounds process does not reload it. Admission selects the actual
step after deciding whether work is fresh, advancing or repeating. Never resolve
everything to the plan setting in the CLI before the operation knows the step.

## Admission and stored choices

Pass a typed per-step settings value and typed overrides through requests instead
of the current global model/effort/harness tuple. Keep configuration parsing separate
from the operation that chooses a task. Validate configuration before external
effects; persist the selected immutable effective setting with the admission.

| Operation | Choice |
|---|---|
| First plan attempt | Effective plan setting |
| First implement attempt after plan | Effective implement setting, independent of plan's harness |
| Ordinary repeat of a step | Previous attempt's complete setting |
| Implement repeat after failed checks | Previous implement attempt's complete setting |
| Relaunch/reconciliation of an admitted attempt | Already admitted setting from `factory.db` |

Store the effective policy, including captured Claude settings or OpenCode sandbox
values, as validated structured data in `factory.db`; a policy path alone is not
enough. Keep any source path as provenance only. Settings-file edits or deletion
cannot change a relaunched attempt or its repeats. Do not derive choices from logs
or reconstruct them from artifacts. Preserve existing harness/provider/model/effort
columns used by reads, with policy serialization/deserialization through one codec;
remove the universal sandbox assumption and avoid conflicting duplicate mode values.
Database row validation uses pydantic v2. JSON is appropriate at the database/file
boundary, never to call another in-process operation.

Change the schema from the current v19 to the next available version at
implementation time. Apply the established drain-before-upgrade and deliberate
old-database discard contract. No migration, old-row defaults, compatibility reader
or automatic discard. Preserve old-entry schema fencing and intact compatible-DB
restart behavior. Update every fresh/advance/repeat insertion and owning read path
together, including the failed-check repair path.

## Harness launch and setup

Put a small agent launch adapter beside typed settings in one agent feature folder.
It owns harness construction, executable/credential lookup, policy-to-library
translation and harness-specific diagnostics. Keep `provider_of` the sole provider
derivation. Replace concrete Codex annotations and the Codex-only `launchable`
restriction with the released `Harness` protocol. `Attempts` orchestrates this typed
port; it does not assemble vendor flags or import vendor policy types. Wire the
adapter once in `composition.py` and use the same route from the attempt entry.

Generalize machine credentials to the selected executable. Preserve Codex's file
login behavior, environment allow-list and push bar; use Claude's existing local
subscription login and OpenCode's existing local configuration through their released
harnesses. Do not add API-key discovery, authentication probes or account routing.
Credential failures return a generic typed result with an adapter-supplied useful
explanation. Test that each such result has an explanation without leaking secrets.

Both plan and implement agents edit files, so set `LaunchInputs.write=True` for
Claude/OpenCode even for the plan step. The plan's permitted paths remain the
factory's existing answer/commit rules; Claude's read-only permission mode named
`plan` is not selected merely because our step is named plan. Give Claude a fresh
session ID and the step schema; give OpenCode its private per-attempt launcher root
through the existing evidence/file owner, outside the worktree that preparation
resets. Include the structured-answer contract in the prompt for every harness;
OpenCode's lack of schema enforcement does not bypass the shared strict decoder.

Move retained Codex access translation to the adapter using `CodexAccess` and use
its `sandbox_argv` for the existing probe. Preserve the precise default safety
behavior: no network or escalation, ignored user config/rules, excluded `/tmp` and
inherited TMPDIR, no plan extra roots, and implement's three writable folders and
offline shell variables. Test effective semantics, including an empty roots list;
do not assume the shelf's omission of an empty list overrides inherited config.
Validate selected sandbox options coherently rather than attaching workspace-write
fields to other modes. A Codex probe must use the same effective policy as launch.

For implement, retain preparation, setup, claims, liveness reconciliation, safe folder
creation/cleanup and deadline ordering. Pass a probe only for Codex. Claude/OpenCode
skip sandbox and writable-root validation; shared checks that protect the factory's
own folder lifecycle still run. Do not run a Codex executable or reuse its probe for
another harness. Keep the existing Linux setup limitation distinct from a new
non-Codex sandbox preflight, which is expressly out of scope.

Launch and evidence/session capture continue through `any-agent` and the existing
registered execution ports. Decode `RunOutcome.summary.text` through the same strict
decoder and step schema regardless of harness. Preserve cleanup on every failed
launch/preparation/deadline path. Add no factory subprocess/signal/spawn escape,
vendor-output parser, fallback execution or second session owner.

## Reads, tests and delivery

Extend the existing `.149` attempt header/read model with a harness-appropriate
access summary, retaining harness, derived provider, model and effort from admitted
facts. Claude/OpenCode must not display a fictitious Codex sandbox. Do not render
policy JSON, hooks or secrets. Read stored choices for historical attempts, never
current machine settings. Preserve the existing reasoning line and answer contract.
Update CLI help, README/config examples and the design index for delivered behavior.

Implement in bounded changes: typed settings/config and optional flags; admission,
schema and immutable repeats; launch adapter/credentials and setup selection; then
stored-choice presentation and documentation. Keep files under 400 source lines,
functions under 80 and test files under 800; add no `Any`, `cast` or ignore escape,
runtime dependency, baseline import or copied test bootstrap.

Focused behavior/contract tests must prove:

1. Defaults distinguish plan high from implement medium. File fields and individual
   flags have the documented precedence; missing config works without model/effort
   flags. Invalid keys, modes, policies and paths fail before claims/reservations.
2. A round advances from one harness to another using the next step's setting.
   Ordinary repeats and failed-check repeats copy the entire previous policy;
   compatible-DB reopening/relaunch keeps it after configuration files change.
3. All three released harnesses receive their model, effort, writable-step setting
   and typed access correctly. Use library harnesses to build launch specs without
   live execution and semantic execution fakes for orchestration. Claude settings
   content and mode, OpenCode sandbox/root and Codex sandbox/probe agree with inputs.
4. Non-Codex steps need no Codex credentials or probe. Codex still probes and refuses
   failed enforcement. Common implement setup, safe cleanup, registration fencing,
   deadlines and session capture remain covered. Non-Codex sandbox gaps do not turn
   into a startup refusal or a new shelf dependency.
5. The same valid and malformed answers from each harness receive the same step
   decoding and file-rule treatment. Headers show persisted actual choices with a
   useful policy summary. Every adapter failure has a nonempty explanation.
6. Schema mismatches still refuse without modifying existing state; existing
   admission, repair, restart and import-isolation contracts pass after the changes.

Extend the relevant existing CLI, config, admission, attempt, environment, repair
and dashboard tests rather than testing every helper. Keep pure settings tests
dependent only on their feature and small shared types. Read `justfile`, run the
focused affected tests with the installed successor, then run required `just check`
and `just test`. The latter is the repository's focused CLI/steps/rules gate, not a
whole-suite/live run. Use `just install` and
`uv run --frozen --no-sync python -I -m taskloop ...` for executable checks; no
editable baseline/PYTHONPATH or live vendor sessions.

## As built

Not implemented in this planning step. Implementation must replace this paragraph
with changed paths, schema version, focused/full-required-gate results and actual
limitations. Explicitly retain the agreed gap: Claude/OpenCode sandbox and
writable-root enforcement are not preflighted here; OpenCode's released sandbox is
platform-specific. If another released-library limitation prevents a harness path,
finish the Codex path and record the precise remaining gap here as authorized by
the scope decision, without inventing a replacement sandbox or waiting for shelf.
