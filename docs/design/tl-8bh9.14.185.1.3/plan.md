# Depth
Depth: large; the supplied code map names more than 60 files, while Read list generation is one cohesive behavior. No owner decision is missing and no dependency is explicitly unlanded. Evidence budget: 20 model calls, total. The supplied glossary excerpt covers the terms needed here.

## Size
Estimated changed files: 4, including this plan, two existing source modules and one existing test module. Independent behaviours: 1. Estimated model calls for one implement attempt: 30, including focused verification and the final gates.

Acceptance criterion: generated plan inputs require a bounded, reasoned Read list covering implementation edits and consultations, producers and callers; generated implementation inputs use that list, and both contracts survive the existing retry routes.

## Outcome and non-goals
Make the generated step inputs describe and consume an actionable `## Read list`. Keep the existing symbol-based Change map as the description of changes, with the Read list supplying the source ranges to consult. This task changes generated instructions and their contract coverage. It does not add an artifact parser, change answer schemas, modify AGENTS.md, or implement the independent answer-rules, early-stop or code-map tasks.

## Settled decisions
- Add the literal `## Read list` heading to the plan template after Change map and before Contract. Require a nonempty Markdown bullet list of at most 25 entries, each naming an existing file as `path:first-last` with a short reason and a narrow, useful range.
- Require coverage of every file implementation must edit or consult, including producers and callers. New files are identified as new in the implementation narrative; the Read list names their existing integration points rather than inventing ranges in nonexistent files.
- Permit targeted searches for omitted callers or source that changed after planning. Require revision of an existing plan lacking the Read list before answering `planned` or `unchanged`.
- Preserve the symbol-based Change map and existing artifact validation. Its parser currently requires Change map, not Read list; the task asks generated inputs to specify the requirement. No new runtime rejection vocabulary is needed.
- The parent discussion split this task from independent siblings tl-8bh9.14.185.1.1, .1.2 and .1.4. Reconcile overlapping edits in plan_step.py and test_steps.py with their current contents at implementation time; retain their answer, depth, Size and code-map contracts. None is an implementation prerequisite.

## Open decisions
None.

## Read list
- `src/taskloop/plan_step.py:73-97` — edit TEMPLATE to add the required section and its bounded entry format while retaining Change map.
- `src/taskloop/plan_step.py:152-200` — inspect the initial input producer and edit closing instructions to require the section when assessing plan reuse.
- `src/taskloop/plan_step.py:204-231` — confirm repeated plan inputs preserve the original template and Read list directions.
- `src/taskloop/implement_step.py:127-163` — edit implementation reading instructions to consult the Read list first and retain targeted discovery for omissions or changed source.
- `src/taskloop/implement_step.py:185-208` — confirm ordinary-repeat and failed-check framing preserve the implementation reading contract.
- `tests/steps/test_steps.py:1-19` — reuse existing pytest imports and task/context fixtures for public input-contract tests.
- `tests/steps/test_steps.py:309-346` — update the template assertions and cover Read list requirements and implementation reading across retry routes.
- `src/taskloop/steps.py:21-62` — consult the public step bindings and failed-check caller used by the contract tests.
- `src/taskloop/admit.py:119-124` — consult the admission caller of each step's input producer.
- `src/taskloop/repeat.py:118-136` — consult the caller that wraps the original input in ordinary repeat feedback.
- `src/taskloop/check_repeat/repair.py:61-70` — consult the caller that refreshes context and builds failed-check implementation input.
- `src/taskloop/step_text.py:19-40` — consult the shared feedback frame retaining the original input.
- `src/taskloop/input_context.py:113-123` — confirm context refresh replaces only the delimited context block, preserving generated instructions.
- `src/taskloop/plan_content.py:57-86` — consult existing artifact validation so Change map remains valid and no new parser requirement is introduced.
- `tests/steps/test_plan_content.py:24-40` — consult structural Change map coverage, including its existing acceptance of 26 entries, which is distinct from the new Read list instruction limit.

## Change map
- `src/taskloop/plan_step.py` — TEMPLATE and _closing_words: specify the Read list contract and revision of plans missing it.
- `src/taskloop/implement_step.py` — _closing_words: direct initial reads through the Read list, preserving the existing scoped discovery and reread rules.
- `tests/steps/test_steps.py` — revise the fixed-template contract and implementation-reading test; add focused assertions for Read list generation on initial and repeated inputs.
- `docs/design/tl-8bh9.14.185.1.3/plan.md` — new planning artifact; integration points are the existing plan-step path convention and template producer. No new source or test file is proposed.

## Contract
No typed inputs, result schemas, stored fields or external effects change. The plan input producer adds a required heading and clear range/reason/coverage instructions. The implementation input producer consumes that section. Existing StepKind bindings, admission, ordinary repeats and failed-check repair continue to carry those words through their current public interfaces.

## Work packages
1. Update the existing plan template and reuse instructions. Retain Change map and the other template constraints; add the Read list contract without duplicating answer rules, depth policy or code-map generation. This closes the plan-production portion of the single acceptance criterion.
2. Update implementation reading directions and focused public contract tests. Parameterize plan assertions over initial/repeated inputs and implementation assertions over initial/repeat/failed-check routes. Assert the literal heading, nonempty list, 25-entry ceiling, existing `path:first-last` ranges, reasons, producer/caller coverage, new-file integration guidance, revision requirement and allowed targeted searches. Replace only the obsolete assertion forbidding Read list; preserve independent Size assertions unless current sibling changes require their existing intended form. This closes the consumer and retry portions of the same criterion.
3. Review the diff for overlapping task instructions and source caps. Run any necessary focused test first using the permitted isolated pytest invocation. Then run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last, recording both gate outcomes. No live tests.

## Acceptance behaviours
Generated plan inputs require the exact Read list heading, a nonempty list with at most 25 existing-file range/reason entries, all required producers/callers and existing integration points for new files; a missing section requires plan revision. Initial and retry implementation inputs direct the agent to those ranges and permit targeted searches for omissions or changed source. Focused public input-contract coverage verifies this behavior while the existing Change map, answer, depth, Size and code-map behavior remains intact.
