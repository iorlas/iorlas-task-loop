# Default backlog for step show and expose list hold causes

Task: `tl-8bh9.14.132`. Prepared 2026-11-13 from the owner's run feedback and the current successor source.
This is an implementation plan; implementation and verification remain to be done.

## Current behavior and scope

`cli_step.register` requires `step show --backlog`. Its handler already delegates to the read-only application
operation `attempt_status.show_attempt` through `cli_composition.open_reads`. `step list` delegates to
`list_attempts` and renders typed `AttemptView` values in `step_render._rows_lines`.

There is no separate backlog registry. A caller supplies a logical backlog when admitting work, and the owning
attempt store retains that identity in `factory.db`. `machine_config` currently has no backlog key. For this
change, the sole available backlog means the sole distinct configured identity retained in that database,
including ended attempts; it does not mean the sole backlog containing the requested task.

Hold diagnostics already reach both read operations: `AttemptView.hold.reason` is the recorded reason and
`hold_due` is the reason before a hold is recorded. `HoldRow.cause_id` identifies the causing attempt, not the
diagnostic text. JSON already exposes `hold.reason` and `hold_due`.

Implement the two CLI improvements within these existing operations and renderers. Other commands retain their
current backlog requirements; `step list` continues listing all backlogs. Hold transitions, scheduling, `--stuck`
selection, tracker behavior and the factory schema retain their existing semantics. No new dependency or glossary
term is needed.

## Required behavior

### Backlog selection

Make only `tl step show TASK [--backlog KEY]` accept an omitted flag. Resolve its backlog in this order:

1. An explicit `--backlog KEY` selects that identity.
2. Otherwise, a machine-config `backlog = "KEY"` selects that identity.
3. Otherwise, exactly one distinct backlog in the selected `factory.db` selects that identity.
4. With zero or multiple identities, return the existing typed `Failed` shape, `refused:backlog`, exit 1. Explain
   that `--backlog KEY` or the machine-config `backlog` is needed; for ambiguity, show the available keys in sorted
   order. Do not choose by task-id uniqueness, task prefix, current directory, Git metadata or tracker discovery.

An explicit or configured selection with no attempt for TASK keeps the existing `refused:absent` result naming
the selected backlog. Do not fall through to another backlog. Read failures keep the existing unavailable/store
result and exit policy. A missing database keeps the existing read-only refusal and creates no state.

Add the optional TOML key `backlog` to the existing machine-config owner. Its built-in value is unset, with source
`default`; a supplied value must be a nonempty string identifying the logical backlog, using the existing task-scope
validation. Reject invalid values through the existing config refusal path, even if a command supplies an override.
Keep this file default distinct from the explicit show flag: the read operation receives both typed inputs and owns
their precedence. `config show` reports the setting and source, with JSON null and human `unset` when absent.

### Hold cause column

Add a tab-separated `hold cause` column immediately after `next` in the human `tl step list` header and every row:

| Typed data | Column value |
|---|---|
| A recorded hold | `view.hold.reason` |
| No recorded hold, but a hold is due | `view.hold_due` |
| Neither | `-` |

Use the recorded reason even when the view's result has since changed. Preserve complete existing reason words,
such as `failed:needs_owner`, `failed:main_moved`, `failed:test:failed`, `claim_lost` or `branch_moved`; the owner's
examples do not introduce a new reason vocabulary or require collapsing check failures to `checks_failed`.
Both pending `hold` and completed `on_hold` rows show their reason. The trailing `last command` column remains.
The existing structured list shape already carries the cause and needs no duplicate JSON field.

## Implementation

1. In `machine_config.py`, extend the existing typed effective settings, defaults, accepted keys and resolution
   with the optional backlog setting. Extend the settings pair types for strings and None. In `result_data.py`
   and `step_render.py`, serialize and display the unset config value deliberately rather than stringifying None.
2. In the owning attempt reader (`attempt_reads.py`, exposed by `AttemptStore`), add a read-only distinct-backlog
   query returning `tuple[str, ...]`, ordered by key and scoped to the same adapter as `attempts()`. Keep SQL and
   connections inside the store. This reads the authoritative database directly and needs no schema change.
3. Extend `attempt_status.show_attempt` to accept an optional requested backlog and a typed optional configured
   default. Select the backlog there before reading the task's attempts, returning `Shown | Failed` as today.
   Enumerate backlogs only when neither input supplies a selection. Reuse the existing backlog refusal vocabulary;
   return explanations as result data, never infer outcomes from rendered text.
4. In `cli_step.py`, make the show parser flag optional, document the precedence in its help, and pass both inputs
   into `show_attempt`. Keep the handler limited to composition, invocation and rendering.
5. In `step_render.py`, add the column using the existing hold fields. Adjust the small number of existing exact
   header/row assertions affected by the column. Update CLI usage documentation and the existing glossary flag row
   during implementation so they describe show's exception to the explicit-backlog rule and the new config key.

Preserve the read-only path: no tracker calls, claim changes, Git writes, agent or entry-process launches,
configuration writes or database initialization. Use existing typed results and ports, with no display/log parsing, JSON roundtrip,
baseline import, fallback, new Any/cast/ignore, or competing store. Keep source files below 400 lines, functions
below 80 lines and test files below 800 lines; `attempt_status.py` currently has 364 lines.

## Focused verification

Add a focused CLI module, `tests/cli/test_step_status_cli.py`; `test_step_cli.py` is already close to the 800-line
limit. Use the existing temporary database and semantic port patterns, with an isolated HOME and config. Cover
observable behavior through `cli.main`, including real read-only composition rather than only mocking the returned
`Shown` value:

- Show without `--backlog` succeeds with one distinct backlog in both human and JSON modes. Multiple attempts in
  that backlog still count as one; the output identifies the selected backlog.
- With multiple backlogs, a machine-config default selects one; an explicit flag overrides it. A selected scope
  lacking TASK returns absent rather than selecting another scope that contains it.
- An empty database and multiple backlogs without a default refuse with actionable diagnostics in human and JSON
  modes. Include a task present in only one of two backlogs to prove selection is scope-based.
- List renders the header and reason for recorded pending and completed holds, an unrecorded due hold, and `-`
  for an unheld task. Include an owner-decision reason, `main_moved` and a check failure, and a recorded reason
  different from the current result. Assert the cause independently of the `next` and result columns.
- List JSON still exposes the existing `hold.reason`/`hold_due` fields, and `--stuck` retains its existing membership
  rules while included held rows show the new column. Missing-database and read-only behavior remain covered.

Extend `tests/cli/test_config.py` for the optional default, valid/invalid values and config-show representations.
Update only affected existing expectations in `tests/cli/test_step_cli.py` and
`tests/steps/test_hold_status.py`; add focused operation coverage there only where the CLI cases leave a behavior
unverified. Tests are pytest functions and test public behavior rather than every helper.

Read the justfile before executing gates. After `just install`, run the focused CLI/config/hold tests with
`uv run --frozen --no-sync python -I -m pytest -q tests/cli/test_step_status_cli.py tests/cli/test_config.py tests/cli/test_step_cli.py tests/steps/test_hold_status.py`,
then the required `just check` and `just test` gates. The current `just test` recipe is the declared focused
successor suite (`tests/cli tests/steps tests/rules`); do not add baseline, whole-repository or live tests.

Completion requires both owner acceptance cases, deterministic selection/refusal coverage, passing required gates,
and updated usage text. Planning alone does not assert those gates passed.
