# Header
Task: tl-8bh9.14.201
Base: 8670a9c4136e38065e59c8719a9f7dd8038d7c30
Depth: small; one template rule in one owning module.
Owner decision: settled; unlanded dependencies: none stated.
Evidence budget: 6 model calls.
Size: 4 changed files, 1 independent behaviour, 25 implement model calls.

## Outcome and non-goals
The template already bounds Read lists and tests exercise initial and repeat prompts. Fill the missing exemption for mechanical renames while preserving coverage of substantive edits. This changes planning instructions and their contract test; it does not perform renames or change runtime validation.

## Settled decisions
- Apply the supplied owner-approved option A.
- Only committed map rows with one target qualify; cause-dependent targets remain in normal scope.
- The required zero-match search is an acceptance line in a plan using the exemption.

## Open decisions
- None.

## Change map
- `src/taskloop/plan_step.py` — `TEMPLATE`: insert the supplied exception immediately after the coverage sentence; add its single-target restriction and acceptance-line requirement. `input_text` exposes the resulting instructions without interface changes.
- `tests/steps/test_steps.py` — add one contract test using `plan_input` to pin the exception, insertion position, map-row/search requirements and limits for initial and repeat prompts.
- `src/taskloop/steps.py` — `PLAN`: consult the existing input and feedback wiring; no edit expected.
- `tests/steps/test_commit_paths.py` — existing `plan_step.feedback` caller: consult its expectations; no edit expected.
- `docs/design/tl-8bh9.14.201/plan.md` — new implementation handoff artifact.
- `docs/design/tl-8bh9.14.201/plan-metadata.json` — new preparation evidence artifact.

## Read list
- `src/taskloop/plan_step.py:79-108` — template and exact Read-list insertion point.
- `src/taskloop/plan_step.py:160-165` — initial prompt producer.
- `tests/steps/test_steps.py:17-31` — shared initial/repeat prompt fixture.
- `tests/steps/test_steps.py:409-442` — existing template and bounded-read contracts.
- `src/taskloop/steps.py:48-50` — registered plan input and feedback consumers.
- `tests/steps/test_commit_paths.py:184-195` — existing feedback caller expectations.

## Contract
Intent: allow omission only of files changed solely by a committed map's one-to-one rename. Effect: generated planning instructions require named map rows and one `rg -nw` command whose zero-match result is an acceptance line; signature, logic and behaviour changes remain listed. Result: initial and repeat prompts expose the same bounded exception. No typed names, stored fields, states or external effects change.

## Work packages
1. Update `TEMPLATE` in `src/taskloop/plan_step.py` with the exact supplied exception and explicit limits. Closes acceptance A.
2. Add one contract test in `tests/steps/test_steps.py` through the existing `plan_input` fixture, checking the Read-list section and placement after the coverage sentence. Closes acceptance A for both prompt routes. Finally run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, retaining their exit results.

## Acceptance behaviours
- A: Initial and repeat planning instructions exempt only files changed solely by single-target rows in a committed naming map, require the row references and one zero-match `rg -nw` acceptance command, and retain normal Read-list coverage for cause-dependent targets and signature, logic or behaviour changes.
