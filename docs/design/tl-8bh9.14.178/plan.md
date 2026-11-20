# Bound implement-agent check runs and output

Task: `tl-8bh9.14.178`. Prepared 2026-11-14 against `99655d38`.
This is an implementation plan; the later ten-attempt observation remains required acceptance evidence.

## Current behavior and scope

`src/taskloop/implement_step.py` owns the implement input. Its `ENVIRONMENT` tells the agent to run every command
under the profile's `checks`, allows focused work without a limit on full runs, and says only the later factory
checks count. `_closing_words` inserts it before the commit and explanation rules. The current repository profile
requires `just check` and `just test`; both recipes rebuild the installed package through `install`.
`just test` runs `tests/cli`, `tests/steps` and `tests/rules`; `just check` runs lint, types and import rules.

`tests/steps/test_steps.py` asserts the old paragraph verbatim and expressly forbids repository commands in it.
That generic-command restriction and the comment above `ENVIRONMENT` must change deliberately: the owner now
requires the concrete just/uv commands below. Do not add profile detection, alternate instructions or a fallback.

Ordinary repeats include the original input through `step_text.feedback`. Failed-check repeats include it through
`implement_step.failed_check_feedback`; `check_repeat/repair.py` retrieves the first input in the chain.
The new policy therefore belongs in the existing input owner, not in the scheduler or launcher.
Newly admitted attempts receive it; existing attempts whose input was already saved retain their saved input.

The managed task worktree is clean, there is no existing task plan, and `main..HEAD` contains no commits or saved
unfinished work. No source implementation is included in this planning change.

## Input text decision

Replace the instruction to run every configured check with one coherent policy in `ENVIRONMENT`:

- While working, run only focused test files for the code changed. Run lint/type validation through `just check`
  at most twice during that work, using `just check 2>&1 | tail -60`; these optional working runs are additional
  to the one required final run. Do not run a full `just test` while working.
- The only direct pytest invocation permitted is
  `uv run --frozen --no-sync python -I -m pytest -q <file> --tb=short | tail -40`, replacing `<file>` with a focused
  test file for the change. Do not invoke ruff or pyrefly directly, or use another direct pytest command.
- After finishing edits and focused verification, run `just check 2>&1 | tail -60` once and then
  `just test 2>&1 | tail -40` once, as the last validation before the answer. Run the latter once in the foreground
  with sufficient command wait time; never start it in the background or poll a running `just test`.
- Do not rerun either successful final command. If a command fails, fix the reported failure, use focused
  verification as needed, and rerun the failed command; failure does not justify repeating the successful one.
  This is the explicit exception to the normal run limits.
- Enable pipeline failure propagation in the command shell (`set -o pipefail`) so `tail` cannot conceal a failed
  check or test. Report the underlying command's result, not just `tail`'s status.
- State explicitly that these factory instructions take precedence over AGENTS.md's
  "Do not run whole-suite/live tests as an agent" for the two required final checks, once each, with the stated
  failure exception. This narrow exception does not authorize other whole-suite or live tests.
- Give the existing ruff constraints: line length at most 140 (`E501`), at most six returns per function
  (`PLR0911`), and no function-local imports (`PLC0415`). These are reminders, not changes to lint policy.
- Require the result of each final command in `explanation`.

Preserve the surrounding facts: setup has already run, there is no network, temporary files belong in `$TMPDIR`
and it is emptied after the step, and the factory runs checks independently afterward with only those results
counting. Preserve the existing explanation requirement verbatim, including naming every command and how it
ended and every added test file. Keep the existing answer schema, dispositions, path rules, saved-work warning,
and incomplete/needs_owner explanation rules.

The final full checks occur once per implement attempt, including one answering `unchanged`; a later factory
failed-check repeat is another attempt with its own allowance. The plan step receives no new check instruction.

## Implementation and contract verification

1. Edit `src/taskloop/implement_step.py`: replace `ENVIRONMENT` and its now-inaccurate generic-command comment.
   Keep this a text-only behavior change without new parsing, counters or enforcement infrastructure.
2. Update the existing admitted-input test in `tests/steps/test_steps.py`. Replace its obsolete generic-command
   assertions with assertions for the required commands, working-run limit, final ordering, failure-only reruns,
   precedence over AGENTS.md, bounded output, foreground/no-poll rule, failure propagation and lint reminders.
   Assert the old "run every command" instruction is absent. Retain task/plan ordering, scope, setup/offline,
   scratch, independent factory checks, saved-work and complete explanation-contract assertions.
   Prefer semantic paragraph/command assertions over another duplicated copy of the entire paragraph.
3. Extend the repeat contracts in `tests/steps/test_steps.py` and `tests/steps/test_implement_feedback.py` using a
   real rendered implement input as the original task text. Assert ordinary and failed-check repeats retain
   that same policy, including its limits and required final checks, alongside their existing evidence framing.
   Use `task_text`, `IMPLEMENT`/`kind` and the public `steps.failed_check_feedback` boundary; do not import the
   private step module through a forbidden test dependency.

Do not change AGENTS.md, the justfile, check argv/timeouts, launcher output limits, check execution, result
authority, retry policy, database schema or factory state. No dependencies or new glossary terms are needed.
Historical designs describing the old instruction are not a reason to preserve the superseded input wording.

For implementation verification, rebuild the successor with `just install` before focused tests so the isolated
Python invocation tests the changed installed package. Run the focused files above with the specified uv/pytest
command, one file at a time. Use the new bounded-output commands and run limits for the final `just check` and
`just test`; report their actual results in the implement answer. This documentation-only plan needs no gates.

## Acceptance after rollout

The prompt contract tests establish the intended instructions, not their effectiveness across real agents.
Observe the first ten subsequent implement attempts admitted with the new input, retaining their attempt IDs
and the input/code revision. Include attempts that fail or repeat rather than selecting only landed tasks.

Use existing owning transcript/artifact readers for a manual audit of actual executed commands; factory checks
are separate and do not count as agent runs. Count invocations, including tailed pipelines and commands sharing
a tool call, rather than counting tool calls. Record per attempt: full `just check` and `just test` counts,
failure-justified reruns, focused test runs, final results and any polling violation. Report the median full-test
suite (`just test`) runs; acceptance requires at most one. Report `just check` counts separately against its
two-working-plus-one-final allowance, so permitted lint/type work is not mislabeled a full test-suite run.

Read failed-check repeat facts through existing typed attempt/status readers (`repeat_reason=failed_check`),
not by inferring workflow state from transcript text. Compare the number of failed-check repeats originating
from these ten attempts with the same measure for the immediately preceding ten implement attempts; report
the IDs and both counts. Acceptance requires no increase. An unavailable baseline or fewer than ten later
attempts leaves this observation pending, never a claimed pass. Store the eventual report under this task's
design directory; do not build a telemetry subsystem or mutate factory state for this audit.

The main risk is more factory failed-check repeats after fewer pre-answer runs. The owner estimates a 3–4%
token saving per landed task and about a third of a long attempt's wall time; those are hypotheses to observe.
The corrected launcher limit is about 3,000 tokens per tool result: the 44,218-token check and 21,938-token pytest
examples are original output sizes. The measured 5.15M-token/10% share stands; tailing is expected to save about
2,000 context tokens per run, not 8,000. Do not use the superseded output-cost estimate as acceptance evidence.
