# Require patch edits and bounded verification output

Task: tl-8bh9.14.182. Prepared 2026-11-14 against `99655d38`.

## Outcome and evidence

The implement input tells agents to edit through `apply_patch`, use the project
interpreter, and verify Python edits immediately with bounded output. This is a
prompt change with focused contract coverage, not a new execution policy engine.

The owner's corrected evidence is authoritative: attempt
`d0f95466088c4da48324cfbcaaa7579d` used 41 Python heredoc edit scripts in 78 calls.
Broken replacements caused repairs and repeated type checking. The 50,149- and
19,089-token results were original output sizes; the agent saw approximately
3,000 tokens from each because `tool_output_token_limit=3000`. Do not repeat the
superseded 70K-token cost claim. Expected savings are an estimate of 2–3% per
landed task, chiefly from fewer edit scripts and repair cycles.

## Current code and tool availability

- `src/taskloop/implement_step.py` owns the initial implement input through
  `input_text`, `_closing_words`, and `ENVIRONMENT`. It currently describes setup,
  profile checks and temporary files, but says nothing about patch edits or the
  Python interpreter.
- `feedback` and `failed_check_feedback` include the original task input. Keep
  that ownership so ordinary repeats and failed-check repairs retain the rules.
  `repeat_instructions` currently recommends `git show HEAD:<path> > <path>`
  for restoration; that is also a file edit and must follow the new patch rule.
- `tests/steps/test_steps.py` currently asserts that the input names no repository
  command, including `just` and `pytest`. The owner's explicit command guidance
  changes that contract; update its assertions and explanatory docstring together.
- `.task-loop.json` requires `just check` and `just test`; `justfile` installs the
  successor package before those focused gates. `.venv/bin/python --version`
  reports Python 3.15.0 in this worktree. Bare `python3` refers to the host's 3.12
  in the reported attempts and must not be recommended for project scripts.
- `apply_patch` is exposed in this session's tool list. The supplied plan
  transcript `01a1d8dd-c432-73a0-96d1-d44502d31b09` also demonstrates it. The
  current shared launch in `src/taskloop/agents/launch.py` and pinned
  `any_agent.harnesses.codex.CodexHarness.launch_spec` has no step-specific tool
  filter removing it. Preserve the existing 3,000-token Codex output limit.

The implementation agent must first inspect its actual offered tools and record
whether `apply_patch` is present in this plan's implementation evidence. Planning
tool availability and launch inspection are evidence, not a claim that a later
implementation session has already been observed. If that session lacks
`apply_patch`, report the gap here and in the implementation explanation; retain
the heredoc editing style with the output rule below, as the owner explicitly
permits. Do not install tools, change launch permissions or invent a replacement
patch mechanism to hide the gap. Interpreter guidance still applies.

There are no task-branch commits beyond `main` and no unfinished commit for this
task to retain or repair. The local `bd show tl-8bh9.14.182` returned not found;
the supplied task text provides the requirements. Preserve existing task claims.

## Implementation

1. Extend the implement input in `implement_step.py`, keeping one copy of the
   instruction text alongside its existing environment guidance. Require:
   - “Make every file edit with `apply_patch`, never with a Python or sed script.”
     This includes additions, deletions and repair edits; shell redirection must
     not become another way to rewrite repository files.
   - “After an edit that touched a Python file, run nothing but the focused test
     or `just check 2>&1 | tail -60`.” Make clear that this is the next command
     after the edit, before additional inspection or unrelated commands. A
     focused test also bounds combined stdout/stderr to its last 60 lines.
   - “If a result is longer than 60 lines, you ran the wrong command.” Bound
     agent-visible command output rather than relying only on token truncation.
   - “The project interpreter is `.venv/bin/python`; use
     `uv run --frozen --no-sync python -I` for scripts. Bare `python3` is the host's
     Python 3.12, not the project's Python 3.15.” Scripts here are execution or
     inspection scripts, never an exception to the edit rule when the patch tool
     is available.
   Include the explicit missing-tool exception described above, conditional on
   actual absence, without suggesting heredocs as an ordinary alternative.
2. Preserve the obligation to run all profile checks before answering. Immediate
   verification after each Python edit supplements those final checks. Preserve
   offline setup, temporary-file boundaries, answer format and commit ownership.
   The requested repository command/interpreter advice deliberately replaces
   the earlier test's prohibition on naming repository commands; add no new
   profile field or repository-detection mechanism for this bounded change.
   Update `repeat_instructions` to read original content with `git show` and
   restore it with `apply_patch`, removing its conflicting redirection advice.
3. Update the existing public-input contract test in
   `tests/steps/test_steps.py` to check the editing rule, immediate verification,
   60-line limit, interpreter command and conditional missing-tool behavior.
   Keep assertions for the task/plan reference, scope, profile checks, offline
   environment and answer instructions. Assert the required meanings instead
   of snapshotting every sentence or importing a private text constant.
4. Exercise ordinary repeat input and failed-check repair input with a real
   complete implement input, using the existing step APIs and fixtures in
   `tests/steps/test_steps.py` and `tests/steps/test_implement_feedback.py`.
   Verify the rules survive both wrappers. Retain failed-check evidence framing
   and its existing bounds. Check that repeat restoration advice uses the patch
   tool and no longer instructs shell redirection. Do not create tests for every
   helper or launch a live agent to test prompt text.

Expected source/test scope is those three files. Record tool availability and
validation in this plan when implementing. No dependency, database, scheduler,
profile schema, harness or transcript-reader change is needed.

## Verification

Read `justfile` before running gates. Make all implementation edits through
`apply_patch` when offered. After each patch touching Python, the next command
must be the focused tests or the bounded `just check` command. Use shell
`pipefail` so `tail` cannot make a failing check look successful. For example:

```sh
set -o pipefail
uv run --frozen --no-sync python -I -m pytest -q tests/steps/test_steps.py tests/steps/test_implement_feedback.py 2>&1 | tail -60
```

The factory setup already installs the package. When reinstalling after source
edits is necessary, choose `just check` as the immediate verification command;
its `install` prerequisite rebuilds the installed successor before checking it.
Run the focused tests against that rebuilt package, not a stale installation.
Complete both required focused gates, preserving each command's exit status:

```sh
set -o pipefail
just check 2>&1 | tail -60
just test 2>&1 | tail -60
```

Do not run the whole suite or live tests. A documentation-only planning change
needs diff/whitespace review, not execution of the implementation gates.

## Acceptance and later observation

Automated completion proves the actual implement input includes all required
guidance and preserves it through both repeat paths, with the focused tests and
both required gates passing. The implementation explanation records the actual
tool availability and commands with their results.

After deployment, inspect the first six later implement attempts, including
repair repeats, through the existing owning transcript reader. For each attempt
record its identifier, Python heredoc calls that actually edit files, and the
largest agent-visible tool result following an edit. Count edit scripts, not
read-only Python scripts; distinguish original output size from delivered
truncated output. The owner's observation target is fewer than three heredoc
edit scripts in every attempt and no tool result over 8K tokens following an
edit. Report any missing-tool exception, missing evidence or failure explicitly.
Do not manufacture six live attempts, infer compliance from prompt assertions,
or claim the estimated savings as measured. This later observation does not
justify adding workflow control derived from logs or new persistent state.

## As built — 2026-11-14

The implementation session's actual offered tools include callable
`tools.apply_patch`; every implementation edit used it. No missing-tool exception
was needed. `.venv/bin/python --version` reported Python 3.15.0. The task branch
contained only the plan commit beyond `99655d38`, with no unfinished task commit.
`bd show tl-8bh9.14.182` again reported not found; no task claims were changed.

The implement input now carries patch-only edits, the conditional missing-tool
exception, immediate verification with combined output limited to 60 lines and
pipefail, and project interpreter guidance. Repeat restoration reads with
`git show` and edits with `apply_patch`. Public-input tests cover those rules;
ordinary repeats (both recorded and unrecorded) and failed-check repair inputs
preserve the complete original implement input and existing evidence framing.
No test files were added.

Validation used `set -o pipefail` and combined output piped through `tail -60`:

- `just check` initially failed on an existing assertion in
  `tests/steps/test_dash_read.py` that used nonexistent `Run.summary`. Corrected
  that assertion to the model's existing `Run.access` field. The next `just check`
  passed lint, types and all nine import contracts.
- `uv run --frozen --no-sync python -I -m pytest -q tests/steps/test_steps.py tests/steps/test_implement_feedback.py`
  passed all 21 focused tests against the rebuilt installed package.
- `just test` passed all 3,420 tests in the required focused directories.
- `git diff --check` passed.

The six later implement attempts have not been observed in this session. Their
heredoc counts and delivered output sizes remain a later observation; no measured
token savings are claimed.
