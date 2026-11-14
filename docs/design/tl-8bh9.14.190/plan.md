# Depth

Medium: two behaviors change, the plan prompt's initial assessment and its documented early-refusal contract. No missing owner decision or required unlanded dependency is named in the task. Evidence-gathering budget: 12 model calls; this plan used six. The references to .175, .179 and .131 supply rules or scope boundaries, not prerequisites to implement another task.

## Size

Estimate four changed files including this plan: `src/taskloop/plan_step.py`, `tests/steps/test_steps.py`, `tests/steps/test_answer_contract.py`, and this artifact. Two independently testable behaviors:

1. The generated plan prompt requires an assessment before exploration, applies every depth rule and budget, and preserves bounded planning and existing size limits.
2. Early owner refusals for the three named causes are accepted with words and no plan or commit request.

Estimate 25–40 model calls for one implement attempt, distinct from the plan evidence budgets of 6/12/20. The subsequent ten-attempt observation is operational validation, not additional runtime behavior. No schema, scheduler, dashboard data model, glossary or dependency change is needed.

## Current evidence

At source `480d41d164e5d80efaf1ae568dc96bb58b36025c`, `plan_step.input_text` renders the warning, task text, factory context and then closing instructions. `_closing_words` starts with reading the existing plan and only then asks for .179's `## Size` assessment. The factory context also contains orientation read instructions, so merely prepending assessment text to `_closing_words` would leave it too late.

`plan_step.decode` already accepts `needs_owner`, a null or expected `plan_path`, empty paths, a null message and an explanation of up to 2,000 characters. Its effect is `none`; no artifact is required by that answer. Preserve this contract rather than introducing a cause field or interpreting explanation prose. Existing answer-contract tests cover its general shape, but not the three task-specific explanations.

`input_context.ORIENTATION` already supplies .175's excerpt-first glossary rules and prohibits redundant orientation reads. .179's implementation-size rules are present at the source commit. Reuse both.

## Prompt change

Put the assessment instructions immediately after the final-answer warning, before task prose, factory context and all existing-plan or orientation read instructions. Keep the warning and current answer schema. The instructions must require the first commentary message to state depth and require assessment from the supplied task text alone, with at most one cheap identifier search returning only a file count and opening nothing. No preliminary source, plan, glossary, tracker or history exploration is needed to decide.

Spell out the rules and precedence in the prompt:

- Large: more than three independent behaviors, a schema version change, an explicitly unlanded task dependency, or more than 60 named files.
- Otherwise medium: two or three behaviors, or changes in two or three owning modules.
- Otherwise small: one behavior in one owning module.
- Give a one-sentence reason, state whether an owner decision is missing or a dependency is unlanded, and state the evidence-gathering budget: small 6, medium 12, large 20 model calls. These are evidence ceilings, not additional calls per search or per file. Finish within the budget using bounded evidence; a budget alone is not an owner-refusal cause.

Require the assessment as the first lines of a successful plan under `# Depth`, followed by the retained `## Size` assessment. Reusing an existing plan requires both current assessments; absence of Depth requires revision. Small tasks still receive short plans. Read the task's existing plan only after the initial assessment permits planning; retain the saved-work and Git restrictions.

Before exploration, answer `needs_owner` for exactly these early causes: large work with independent parts, a missing owner decision, or an explicitly unlanded dependency named in the task. Put the Depth assessment and concrete reason in `explanation`, with no new plan or commit request. For independent parts, propose the split in words using .179's part names, independently testable acceptance criteria and dependencies. For the other causes, identify the decision or dependency and what must resolve it. Preserve the existing 2,000-character limit and existing saved work.

A single cohesive schema change can be large and still receive a bounded plan when none of those causes applies. Do not infer a missing decision from terse wording or treat references to other tasks as proof they are unlanded. Preserve later refusal for actual contradictions or infeasibility and .179's separate size limits; these rules do not invent additional early rejection causes. Planning remains the existing step; .131's separate stage question is untouched.

Require the first commentary depth line so the existing dashboard conversation view exposes it for owner correction. Do not add a stored classification, new stage, glossary entry or dashboard parser.

## Focused verification

Use `kind("plan")` and existing fixtures, respecting the module import boundary.

- In `test_steps.py`, add separate parametrized prompt-contract cases for each large trigger, each medium trigger, the small rule, and all three budgets. Cover precedence and the strict boundaries: three versus four behaviors and 60 versus 61 named files.
- Pin that the assessment block precedes task content, factory orientation instructions and the existing-plan read instruction. Cover first-commentary visibility, Depth persistence, existing-plan revision, the single count-only search, glossary excerpt reuse and continued planning for small work.
- Cover each of the three early refusal causes, required explanations and split details. Preserve the existing .179 tests for Size, independent excesses and implementation reassessment; distinguish evidence budgets from implementation estimates.
- In `test_answer_contract.py`, add one representative prose-only `needs_owner` answer per cause, including Depth in its explanation, null `plan_path`, empty paths and null message. Assert effect `none` and preserved explanation. Also cover the expected plan path without a plan artifact. Keep malformed-answer and length-limit regressions. Do not add semantic parsing of refusal prose or a new classifier solely to test prompt text.

Run the focused tests, then the configured `just check` and `just test` gates under the repository's focused-test policy; do not run whole-suite/live tests. No implementation checks are required for this documentation-only plan attempt.

## Ten-attempt observation

After the prompt change is deployed, measure the next ten consecutive plan attempts, including early refusals, repeats and interrupted attempts. Use existing factory attempt identities and owning evidence readers to associate the persisted records with Codex transcripts; do not add runtime state or derive workflow decisions from logs. Record each attempt's task, assessed depth, outcome, model-call count and input-token total using the same accounting as the supplied baseline. Report missing usage explicitly rather than estimating it or substituting tool-call counts for model calls.

Compare per-attempt counts, ranges and totals with the baseline: ten attempts, 14–29 calls each, 0.34M–1.79M input tokens each, 10.16M total input tokens. Also compare assessment-before-exploration and early-refusal behavior, and separate small/medium planning from large refusals so task mix is visible. Treat the proposed 25–35% per-task and 3–5% overall savings as hypotheses, not pass thresholds or measured results.

Add the measured comparison as a task-tracker comment through its owning operation when ten attempts have occurred. Implementation can be reviewed after focused gates, but the observation acceptance criterion remains pending until that comment exists. This plan attempt has no tracker access and makes no comment or future-result claim.
