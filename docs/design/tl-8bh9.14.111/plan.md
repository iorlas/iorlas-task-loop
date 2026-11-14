# Operator guidance and evidence paths

Task: `tl-8bh9.14.111`. Status: proposed for owner review; implementation waits for the owner's yes.

## Result

Every refusal that an implemented command can present has a reason-specific guide explaining what happened,
what remains held or unchanged when relevant, and what the person can do next. A test detects an added refusal
without guidance. `tl step show` exposes the selected attempt's `events.jsonl` path in human and JSON output.
The decision about a doctor or bug-report command is recorded below.

This is a presentation and diagnostic-discovery change. Scheduling, retry eligibility, hold decisions, claims,
reservations, land policy, exit codes and persisted state keep their existing owners and behavior.

## Current evidence

Inspected at `99655d38` on 2026-11-14 in the assigned task worktree. No existing plan or task-specific unfinished
commit was found. The live tracker did not resolve this task ID; the supplied task description is the planning input.
The architecture review's retained `docs/design/architecture-review/grilling-record.md` corroborates the operator
census (roughly twenty refusal kinds without next actions, no doctor). That historical count is not a completeness
boundary: implementation must inventory the current code.

- `step_guide.py` has the general and checks-specific guides. `step_render._guides` silently omits unknown reasons;
  the round and end renderers also filter on membership. An unrelated guide for the failure kind is not coverage
  for its reason. Some tests currently accept word-only errors, including `refused:label` and `refused:database`.
- `land_render.failed_lines` looks in `LAND_GUIDE` before the general guide and silently drops missing entries.
  `CANDIDATE_RELEASE`, `CHECKS_GUIDE` and hold guidance contain necessary contextual differences.
- Refusals also reach users through configuration, slot adoption, repository/task inspection, profile inspection
  and drain. Some contain useful detail already; others expose only exception text. Configuration and profile
  reasons such as `missing` and `unknown_key` have different meanings and must retain their context.
- `operations.Failed` accepts a free-form reason; upstream results use a mixture of typed vocabularies and strings.
  Enumerating the existing guide dictionary alone cannot prove completeness.
- `EvidenceFiles.events_path(key)` already owns path resolution without creating a file. `Shown` carries the
  selected directory and entry-log path; `step_render` prints those and `result_data` serializes them. Neither
  exposes the events path. `show_task` can select the latest checks attempt instead of the agent attempt.
- `cli.py` registers no doctor or bug-report command. Existing read-only inspections already expose configuration,
  repository, profile, task and attempt facts. Land summary fetches origin and makes Git objects, so it is not a
  substitute for a passive diagnostic report.

## Doctor / bug-report decision

Proposed decision: defer both dedicated commands in this task. Choose complete local guidance, discoverable evidence
and a short manual diagnostic procedure using implemented inspection commands. The acceptance criterion asks for a
recorded decision, rather than requiring a new command.

The alternatives are a read-only doctor that aggregates existing inspections, or a bug-report command that collects
evidence into an artifact. A doctor needs an agreed definition of health and a scope when configuration, repository,
tracker or database is unavailable. A collected report also needs an agreed content and redaction policy: config,
origins, agent input and transcripts can contain private data. Neither contract follows from this task's census.
Adding either now would expand the task beyond closing the demonstrated guidance gaps.

Owner approval of this plan accepts that deferral. Document the decision and the implemented diagnostic procedure
in the README during implementation. Do not register placeholder commands, collect a report automatically, probe
credentials, run checks, contact a remote or change factory state to diagnose a refusal. A later command proposal
must reuse owning reads and specify its inputs, output, partial failures and side effects before implementation.

## Refusal guidance

1. Inventory public refusal producers and their presentation routes before editing prose. Cover start, admission,
   launch, verification, repeat, checks, release, publication, next/rounds, land and candidate release, pending holds,
   config, slot adoption, repo/task/profile inspection and drain. Include unavailable/uncertain/unsettled results
   presented alongside refusals, compound reasons and refusals nested in round moves, release/publication results
   or slot rows. Argparse syntax errors retain argparse's usage diagnostics; arbitrary exception messages are detail,
   not an open-ended vocabulary of refusal kinds.
2. Build the inventory from owning result/reason types and producer sites, not from the guides. Trace forwarded
   reasons to their owner. Initial examples needing attention include `database`, `schema`, `backlog`, `label`,
   `tracker_root`, `choices`, `checkout`, `input`, `claimed_elsewhere`, `constraint`, `deadline`, `expired`,
   `registration_refused`, `dispatched`, `observe`, `store`, `log`, `launch`, and the newer drain reasons. This list
   is illustrative, not a frozen copy of the old census. Do not expose private internal reasons that never reach a user.
3. Add concise entries through the existing owning presentation modules. Each reason gets an explanation and a
   useful next action or an explicit statement that it must wait or needs an owner decision. Shared prose is allowed
   where the meaning and remedy really match. Preserve checks/land/candidate-release overrides and deduplicate
   repeated guidance. Resolve by typed command/result context so a config error cannot receive a profile remedy.
   New closed vocabularies, if needed, use enums or classes, with string conversion only in their presentation codec.
4. Retain backend-specific explanations inside adapters. Render their supplied detail plus generic factory guidance;
   do not infer causes or remedies from exception wording, log text or backend commands. Missing explanations fail
   a test. Do not remove useful existing diagnostics merely because a guide was added.
5. Remove omission paths that let a known reason disappear, including the detail-substring shortcut in
   `step_render._step_lines`. Structured results determine the guide; a detail mentioning a command must not suppress
   it. A generic catch-all or a guide only for `refused`/`unavailable` does not satisfy reason coverage. Preserve
   printable-text handling and current stdout/stderr and exit-code contracts.
6. CLI guidance may name a supported inspection or recovery command with the required context. Factory-generated
   round/hold/automatic-land messages state the situation and the decision in words; they must not ask the owner to
   operate the factory through a CLI command. Never recommend a blind retry of explicitly held work, deletion of
   evidence/worktrees, force pushes, row edits or unverified process termination. A schema refusal must preserve the
   existing owning upgrade explanation, not prescribe blind deletion or attempt a compatibility reader.

## Events path

Carry an explicit `Path` from `EvidenceFiles.events_path` into the status result and expose it as `Events: <path>`
in human `tl step show` output and `events_path` in its JSON object, beside `directory` and `entry_log`. Reuse the
same selected `AttemptKey` used for the shown attempt's evidence. Agent repeats and the latest checks attempt must
resolve to their own paths, never a previous attempt's or the implement attempt's path by accident. Candidate logs
keep their existing separately identified paths.

The path is a location, not a claim that activity was recorded. Return it before launch and when the file is missing,
empty, truncated or unreadable. Resolving/printing it creates no directory or file and does not read its content.
Do not derive it from a log line or add it to factory.db. Respect custom artifacts roots and existing key/path safety.
No schema upgrade, new evidence writer or activity-format change is needed.

## Implementation and verification

Keep edits with the existing owners: `step_guide`, `land_guide`, `hold_guide`, the corresponding renderers and the
affected inspection renderers; `attempt_status`, `result_data` and the existing evidence path API for `events_path`.
Split presentation code only if needed for the source caps, without creating a generic service or duplicate catalog.
Add the diagnostic procedure and doctor decision to the README. No baseline imports, new dependency or new glossary
term is needed. This planning change commits only this file.

- Add a focused coverage contract independent of the guide tables. Enumerate finite owning reason types and source
  producers; for string-typed forwarding paths, explicitly account for their upstream domains with parametrized
  result cases. A small AST policy census can cover literal producer branches that have no finite reason type;
  unresolved dynamic producers must require an explicit coverage case, not be silently skipped. Check every public
  reason in its applicable context. Demonstrate that a new producer reason or a removed guide makes the test fail.
- Exercise actual human rendering, not merely dictionary membership. With empty and arbitrary details, every known
  refusal must still get its reason's explanation/action. Include nested round refusals and end results, slot rows,
  config/profile collisions, checks/land overrides, candidate release and pending holds. Check that automatic factory
  messages express decisions without CLI instructions. Preserve machine-readable refusal fields and exit codes;
  this task adds only the show-result `events_path` field to that structured contract.
- Add focused status/CLI tests for agent attempt, repeat and latest checks selection; custom artifacts root; a path
  containing spaces; and absent/unreadable events. Assert the human path equals the JSON path and the owning path
  resolver's result, and that inspection creates no evidence or control state. Keep content reads out of this change.
- Use existing semantic fakes and pytest functions. Keep new refusal tests in focused files rather than expanding
  `tests/cli/test_step_cli.py`, which is already near the 800-line test-file cap. Respect 400 source/80 function caps;
  avoid broad imports into a presentation test and do not add `Any`, casts or ignore escapes.
- After implementation run the repository's required focused gates, `just check` and `just test`, as defined by the
  inspected justfile. These install the successor's declared package; use no baseline editable install or PYTHONPATH.
  Run no whole-suite/live test command beyond the repository's focused gates. Any targeted CLI smoke uses
  `uv run --frozen --no-sync python -I -m taskloop ...` after `just install`.

Completion requires the independent completeness test, behavioral guidance assertions, correct read-only events
paths in both output modes, the recorded doctor deferral and documented diagnostic procedure. A plan or a passing
dictionary-membership test alone is not implementation completion.

## As built

Implemented the approved doctor/bug-report deferral and manual inspection procedure in the README. No command
was added. Show results now carry the selected attempt's owning `events_path`, printed in human and JSON output
without reading or creating events; repeat and latest-checks selection keep their own locations.

Guidance is resolved by result context, including config/profile collisions, checks and candidate release.
Round refusals, nested release/publication failures, slot rows and pending holds retain reason guidance. Automatic
round and hold text describes the situation and decision without factory CLI instructions. Producer/finite-type
coverage is independent of the presentation tables, and dynamic forwarding expressions require explicit review.
The new focused tests cover refusal rendering and mutations, inspection contexts, and read-only events discovery.
A pre-existing dashboard assertion referenced `Run.summary`; it now checks the existing `Run.access` field so the
required gates can validate the intended full-access wording.
