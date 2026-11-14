# Size tasks before admitting implement

Task: `tl-8bh9.14.179`. Source: `614fa5b4cbadee30fc0bed29f0b9000262dfd4a1`.

## Size

Medium assessment; 12 evidence commands. Estimated change:
5 files including this plan, of which 4 are implementation/test files; 3 independent behaviours;
approximately 40 model calls for one implement attempt, including focused and final verification.

The three independently testable acceptance criteria are:

1. Plan input requires a Size section and sends any estimate above 60 files, 3 independent behaviours,
   or 100 model calls to `needs_owner`, with a named split, acceptance criteria and dependencies.
2. Implement input reassesses scope immediately after reading the plan and stops at the first coherent
   part if the work needs more than about 60 model calls or touches more than 60 files. It answers
   `needs_owner` with the proposed split and leaves `plan.md` untouched.
3. A split explanation follows the existing hold operation: the parent remains held, the explanation
   reaches the tracker in words, and neither implement nor automatic creation of parts follows.

The ten-plan review is rollout evidence. This task fits one implement attempt.

## Current code and decisions

`src/taskloop/plan_step.py` owns plan input and currently allows success without assessing scope.
Its artifact rule checks encoding, emptiness and bytes, not estimated work. Implement input lives in
`src/taskloop/implement_step.py`: it permits 96 paths, "As built" content and reporting a missing
`apply_patch` tool in the plan. Those last two instructions conflict with the correction.

`steps.next_step` advances only completed steps. The round holds `needs_owner` and quotes its
explanation. Existing tests cover saved work and waiting. Feedback retains the original input.

Use these existing contracts: the agent estimates and answers `needs_owner`; the factory applies it.
Do not add a Markdown parser, answer fields, schema migration, execution counters or another admission
operation. Prompt tests establish delivery of the policy, not estimate accuracy or agent compliance;
the ten-plan review measures that limitation. Never derive control state from logs or token counts.

The correction overrides the stale final acceptance sentence: implement must not edit `plan.md` or
add status, progress or "As built" sections. Separate .190/.191 work owns general evidence budgets
and plan byte caps; do not implement those systems here.

## Changes

### Planning policy

Update the closing words in `src/taskloop/plan_step.py`, before allowing either successful disposition:

- Require `## Size`: estimated changed files (including tests/artifacts), independent behaviours and
  model calls for one implement attempt. Each behaviour has an independently testable acceptance
  criterion; file count alone is insufficient.
- Treat an existing plan without this assessment as needing revision, not eligible for `unchanged`.
  Reassess an existing Size section against current requirements and code before reusing it.
- If any estimate exceeds 60 files, 3 independent behaviours or 100 model calls, answer `needs_owner`,
  not `planned` or `unchanged`. Explicitly state that equality is allowed (60/3/100), and that 61 files,
  4 behaviours or 101 calls each suffice for refusal. Low file count cannot excuse another excess.
- Put the reason and split in `explanation`, within its existing 2000-character limit. Each part has
  a name, acceptance criterion and dependencies (explicitly none where appropriate). The owner or
  orchestrator creates parts in the tracker; the agent neither creates them nor requests a CLI command.
- On refusal, write no new successful plan and offer no commit: use `paths: []`, `message: null`,
  expected or null `plan_path`. Preserve existing saved work; a draft is not approval to implement.

Keep existing infeasible-task refusals, saved-work handling, answer schema, dispositions and artifact
safety rules. Do not rewrite historical plans across the repository.

### Implement policy

Update `src/taskloop/implement_step.py` immediately after the instruction to read the committed plan:

- Reassess the work at that cheap point, before broad exploration or editing. If it needs more than
  about 60 model calls or touches more than 60 files, stop after the first coherent part, commit
  nothing extra, and answer `needs_owner` with the proposed split. If the excess is evident before
  editing, answer then; do not begin a part just to have something to save. If discovered during work,
  stop at the first coherent boundary, without proceeding into another work package.
- Explain completed/remaining scope and named parts with acceptance criteria and dependencies. Partial
  work is unfinished: use `needs_owner`, `paths: []`, `message: null`; the hold saves it. Agents still
  make no Git writes, create no parts and prescribe no owner CLI command.
- Keep the planning limit of 100 estimated calls distinct from this earlier implement reassessment
  at about 60 calls. These are scope instructions, not new harness call quotas. The 60-file decision
  is an earlier stop within the existing 96-path safety ceiling; do not change that shared ceiling.
- Prohibit editing `plan.md`, including status, progress and "As built". Report a missing editing tool
  in `explanation` only. Other plan-folder artifacts retain their existing rules; add no audit artifact.

Preserve required verification instructions, unfinished answers, check evidence and saved-work
semantics. New attempts receive the revised input; already admitted attempts keep their saved input.

### Tests and factory hold

In `tests/steps/test_steps.py`, use public `task_text`/`steps` boundaries. Add prompt contracts for
Size fields, independent acceptance criteria, strict OR limits and their boundary examples, split
contents and owner/orchestrator responsibility. These assert delivered policy, not arithmetic on
a fake agent's preselected answer. Cover implement's distinct 60-call/60-file early stop, unfinished
answers and plan immutability; update tool-gap assertions. Verify ordinary and failed-check feedback
preserve the complete revised input.

In `tests/steps/test_round_holds.py`, script an over-limit `needs_owner` answer with a named split.
Assert the parent is held once, its tracker comment retains the explanation/decision without a CLI
request, later rounds start no implement and no child is created. Exercise implement's early-stop
answer with a coherent partial edit: it remains saved unfinished work, without checks or delivery.
Reuse existing hold coverage; no production hold/tracker changes are expected.

Retain repository line caps. No dependencies, new vocabulary or state ownership are needed.

## Verification and rollout evidence

Run `just install`, then each changed test file through
`uv run --frozen --no-sync python -I -m pytest -q <file> --tb=short`.
Required gates: `just check` and `just test`, following admitted input's output/run limits. Report
results in the answer. No implementation checks are needed for this planning-only change.

After rollout, the owner/orchestrator checks the next ten plan results using the new input, including
reused/refused plans. Record task/attempt, Size presence, file/behaviour/call estimates, exceeded
limits, disposition and split quality. Check equality is allowed, any excess produces `needs_owner`,
the hold explains the decision without a CLI request, and refused parents never enter implement.
Missing Size/estimates is noncompliance, not zero. Identify unavailable evidence explicitly.

Write measurements as a comment on `tl-8bh9.14.179` through the owning tracker operation, never into
`plan.md`. This attempt has no tracker access or future results; carry the observation obligation in
the implementation handoff. Contract tests do not complete that observation. Compare savings only
with landed-task measurements; 10% is an estimate and 31% the sample's potential saving.
