# Depth
Large: the supplied code map names more than 60 files; the task is one cohesive behaviour, generated early-stop instructions with contract coverage. No owner decision is missing and no dependency is explicitly unlanded. Evidence budget: 20 model calls, total, separate from implementation Size. This classification alone does not require a split.

## Size
Estimated changed files: 3 including this new plan artifact, `src/taskloop/plan_step.py` and `tests/steps/test_steps.py`; implementation edits the latter two. Independent behaviours: 1. Estimated model calls for one implement attempt: 30.

Acceptance criterion: initial and retry plan inputs state the ordered depth thresholds, bounded evidence budgets and exactly three early refusal causes before exploration; they permit cohesive large work when no cause applies and require bounded assessment of existing implementations and overlapping tasks before proposing remaining work. Contract tests verify those instructions through the public step interface. These estimates remain below 60 files, 3 behaviours and 100 implementation calls.

## Outcome and scope
Task: tl-8bh9.14.185.1.2. Source commit: e4f1eecf9928d85e8abe8aa4723f557486ef2258.

Complete the early-stop instruction contract already substantially implemented by `plan_step.DEPTH_ASSESSMENT`. Preserve its existing depth and refusal wording where correct. Add explicit post-assessment guidance to inspect bounded evidence of existing implementations and supplied overlapping-task information, identify the remaining gap and avoid duplicating delivered work. An overlap or terse description alone does not establish a missing decision or an unlanded dependency. Use supplied discussion rather than requiring tracker access.

The supplied glossary defines the task, step, attempt, plan, factory and worktree meanings used here; no missing term requires another glossary read. No new terminology, runtime state, schema or adapter is needed.

## Existing implementation and overlapping tasks
`DEPTH_ASSESSMENT` already supplies the thresholds, precedence, budgets, three early causes, refusal payload instructions and cohesive-schema continuation. `input_text` places it before task/context; `feedback` also prefixes it before the repair frame. Existing tests cover initial inputs, numerical boundaries, refusal wording and decoder acceptance without an artifact. Extend this coverage instead of adding another instruction owner or classifier.

The independent sibling tasks cover answer rules (.185.1.1), Read list generation (.185.1.3) and code map generation (.185.1.4). They are not prerequisites. Keep their concerns out of this implementation, and preserve the currently implemented Header/Change map template and its tests. AGENTS.md stays unchanged. This plan's required Depth, Size and Read list sections do not request changing the generated template.

## Implementation
1. Refine `plan_step.DEPTH_ASSESSMENT` only where guidance is missing. Keep assessment based solely on supplied text, before all exploration, with at most the optional identifier file-count search. Place existing-code and overlap inspection after planning is permitted. Make clear that a large classification alone is not an early refusal; preserve the three actual causes and later contradiction/infeasibility and Size checks.
2. Extend the existing instruction contract tests through `PLAN.input_text`/`task_text` and `PLAN.feedback`, parameterizing routes where useful. Check ordering against task prose, factory context and retry repair content, rather than testing only a private constant. Cover the existing 3/4-behaviour and 60/61-file boundaries, large precedence, 6/12/20 total evidence budgets, no budget-only refusal, exactly three early causes and refusal payload/saved-work rules. Assert continuation for cohesive large work, small-task planning, terse wording and mere task references. Add focused assertions for the new post-assessment existing-implementation/overlap guidance. Retain current decoder coverage without changing the answer schema.
3. Run the required gates once each, last: `just check 2>&1 | tail -60`, then `just test 2>&1 | tail -40`. Preserve each command's exit status with shell pipefail. No live tests. Report both outcomes and the test file changed.

No new runtime or test files are expected. This plan is the only new artifact; its integration point is the existing task-specific plan path used by the plan and implement steps. Keep source/test file and function sizes within repository caps. No implementation checks are needed during this planning attempt.

## Read list
- `src/taskloop/plan_step.py:33-70` — warning and owning depth/refusal instruction producer to refine.
- `src/taskloop/plan_step.py:73-97` — existing template and size caps to preserve while limiting scope.
- `src/taskloop/plan_step.py:152-170` — initial input composition and assessment-before-reading order.
- `src/taskloop/plan_step.py:178-200` — later Size refusals and saved-work instructions to keep consistent.
- `src/taskloop/plan_step.py:204-231` — retry repair instructions and assessment prefix caller.
- `src/taskloop/steps.py:28-52` — public step interface and registration of initial/retry producers.
- `src/taskloop/admit.py:119-124` — initial admission caller through `task_text`.
- `src/taskloop/repeat.py:118-136` — retry caller retaining attempt-one input and refreshing discussion.
- `src/taskloop/step_text.py:23-45` — shared retry frame and saved-work guidance consulted for ordering tests.
- `src/taskloop/input_context.py:15-24` — supplied-context orientation and tracker-read restrictions.
- `src/taskloop/input_context.py:43-55` — context renderer used to verify ordering against glossary/code map.
- `src/taskloop/implement_step.py:127-148` — existing scope reassessment and already-implemented handling; consult only.
- `tests/steps/test_steps.py:1-19` — public-interface imports and semantic task/context fixtures.
- `tests/steps/test_steps.py:134-231` — extend existing depth, budget, ordering, refusal and Size contract tests.
- `tests/steps/test_steps.py:280-326` — reuse retry pattern and preserve overlapping orientation/template contracts.
- `tests/steps/test_answer_contract.py:79-98` — existing early-refusal decoder coverage; consult only.

## Completion
The generated initial and retry inputs satisfy the single acceptance criterion and both required gates pass. No tracker mutation, publication, dependency task or owner decision is required by this plan.
