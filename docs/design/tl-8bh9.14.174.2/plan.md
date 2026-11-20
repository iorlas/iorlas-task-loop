# Header
tl-8bh9.14.174.2 | Base: e752ae5d6944787089e270cceaa50faf7207d55e
Depth: small; one Git reuse predicate.
Decision/dependency: settled; .174.1 landed.
Evidence budget: 6 model calls.
Size: 9 files incl. tests/artifacts; 1 behaviour; 40 implement calls.

## Outcome and non-goals
Decide whether a committed plan's cited code remains valid. task_content.py already supplies durable content evidence; its comparison and admission/resume integration belong to .174.3. No scheduling or factory.db changes.

## Settled decisions
- A2 uses the supplied Worktree.diff include/cap contract; no dependency upgrade.
- Store prepared_commit and cited_paths in committed plan-metadata.json beside plan.md.
- Missing metadata requires planning; do not reconstruct it from prose or Git history.
- Metadata describes the source commit used to prepare the plan.
- A newer saved-work commit prevents reuse even when cited paths are unchanged.

## Open decisions
- None.

## Change map
- src/taskloop/plan_reuse.py (new): PlanMetadata and evaluate; use steps.PLAN.artifact, Checkouts and wip.
- src/taskloop/plan_step.py: input_text/feedback require metadata and inclusion in planned paths.
- src/taskloop/wip.py: add a range check for saved-work trailers, retaining is_saved semantics.
- tests/steps/test_plan_reuse.py (new): semantic Git fakes cover evaluate.
- tests/steps/test_steps.py: plan input and feedback expose the metadata contract.
- tests/steps/test_wip_merge.py: saved work beneath ordinary/merge commits prevents reuse.
- docs/design/tl-8bh9.14.174.2/plan-metadata.json (new during implementation): committed metadata.
- src/taskloop/steps.py: consult PLAN/StepKind.artifact registration.
- src/taskloop/verdict.py: consult _artifact, existing StepKind.artifact caller.
- src/taskloop/factory_commit.py: consult settle, existing wip.needs_review caller.

## Read list
- src/taskloop/plan_step.py:125-272 — input, feedback and artifact producer/validator.
- src/taskloop/plan_content.py:12-86 — existing content validation.
- src/taskloop/steps.py:28-53 — artifact registration and callable contract.
- src/taskloop/verdict.py:17-47 — artifact consumers.
- src/taskloop/wip.py:88-119 — typed trailers and merge-aware review.
- src/taskloop/factory_commit.py:87-111 — existing saved-work consumer.
- src/taskloop/task_content.py:35-65 — delivered digest boundary.
- src/taskloop/input_context.py:1-75 — source commit supplied to the producer.
- tests/steps/test_steps.py:1-50 — existing step tests.
- tests/steps/test_wip_merge.py:1-80 — existing saved-work scenarios.
- docs/shelf-digest.json:1-1 — released facts; A2 supplies the diff signature.

## Contract
Frozen pydantic PlanMetadata: prepared_commit (full commit identifier), nonempty unique cited_paths (literal repo-relative files/folders; no traversal or pathspec magic). Produce from source commit and consulted files; reuse retains metadata.

evaluate takes Git ports, worktree and committed plan location. Validate metadata/artifact, commit availability and newer Task-Loop-Wip trailers; then call wt.diff(prepared_commit, 'HEAD', include=cited_paths, cap=0) once. Empty changes permits reuse; any change requires planning. ReuseDecision and ReuseReason enums distinguish reuse, planning and unavailable Git, with explanations. No agent, Git write or DB effect. .174.3 connects admission callers.

## Work packages
1. Implement metadata/producer in plan_reuse.py and plan_step.py, and history check in wip.py. Closes A2.
2. Cover A2 in mapped tests; run just check and just test once each, last, using prescribed tail commands.

## Acceptance behaviours
- A2: valid committed evidence with unchanged citations and no newer saved work reuses after one scoped patch-free diff and zero model calls; changed/deleted citations, newer saved work or invalid evidence prevents reuse, while unrelated changes permit it and Git failure stays explicit.
