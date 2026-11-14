# Header
Task: tl-8bh9.14.174. Base: c20fb48baf8a3c5fe1be81d866340df313037fb7.
Depth: medium
Reason: three linked behaviours. No missing decision or unlanded dependency.
Evidence budget: 12 calls. Size: 34 changed files, 3 behaviours, 90 model calls per implement attempt.

## Outcome and non-goals
Resume an answered factory hold at implement using durable plan evidence and cheap Git checks. Reuse discussion, claims, reservations and restart paths. No shelf change or model verification call. A discarded DB requires planning.

## Settled decisions
- Apply Decision and ADDENDUM together.
- Use released Worktree.diff(prepared_commit, H, include=cited_paths, cap=0); empty changes passes.
- Preserve input_digest as the complete input artifact hash; store task_digest separately.
- Preserve answer/approval rules and local-then-origin task-branch precedence.

## Open decisions
- None.

## Change map
- src/taskloop/task_content.py (new): TaskContent and digest codec, integrated through Discussion.capture.
- src/taskloop/discussion.py: capture returns rendered input and canonical digest; collect retains its text interface.
- src/taskloop/tracker_discussion.py: read supplies provenance for generated operational comments.
- src/taskloop/hold_text.py: comment marks generated hold commentary explicitly.
- src/taskloop/plan_metadata.py (new): PlanMetadata parses the Contract TOML fence for plan_reuse.
- src/taskloop/plan_step.py: TEMPLATE requires prepared_commit and complete cited_paths in Contract.
- src/taskloop/plan_reuse.py (new): typed eligibility decision consumed by AttemptAdmission.
- src/taskloop/plan_reuse_git.py (new): adapter checks task tip, plan blob, ancestry, cited paths and WIP trailers.
- src/taskloop/attempt_loads.py: AttemptLoads reads plan evidence/source link; consult RetainedInputs.
- src/taskloop/factory_schema.py: SCHEMA/columns add evidence; increment version 28.
- src/taskloop/admit_rows.py: insert_attempt defaults nullable evidence for ordinary producers.
- src/taskloop/admit_chain.py: ChainAdmission copies digest; consult NextAdmission producers.
- src/taskloop/admit.py: AdmitRequest/AttemptAdmission select step/settings; _commit fences reuse.
- src/taskloop/operations.py: _current/_answered_hold/_admit carry eligible hold context and step settings.
- src/taskloop/attempt_types.py: Admission carries source-plan link for exact-tip entry checks.
- src/taskloop/prepare.py: _take/_state_refusal require checked H exactly on reuse.
- src/taskloop/composition.py: open_discussion/open_admission wire reuse; consult chain/check-repeat wiring.
- tests/steps/test_admit.py: update request producers and selection/settings/race coverage.
- tests/steps/round_bench.py: Factory wires reuse ports and metadata fixtures.
- tests/steps/test_round_holds.py: replace unconditional return-to-plan expectation.
- tests/steps/test_factory_schema.py: update pin and evidence constraints.
- tests/steps/test_task_content.py (new): digest behaviours through Discussion integration.
- tests/steps/test_plan_reuse.py (new): eligibility through decision and owning Git fakes.
- tests/steps/test_plan_reuse_restart.py (new): repeated holds/restart through Factory.

## Read list
- src/taskloop/task.py:36-54 — task projection.
- src/taskloop/discussion.py:24-105 — sources and framing.
- src/taskloop/tracker_discussion.py:1-32 — source producer.
- src/taskloop/hold_text.py:99-125 — generated commentary.
- src/taskloop/plan_step.py:76-132 — template integration.
- src/taskloop/attempt_loads.py:1-71 — owning reads/retained input.
- src/taskloop/attempt_types.py:109-135 — Admission.
- src/taskloop/factory_schema.py:103-144 — attempt/verification constraints.
- src/taskloop/admit_rows.py:12-35 — shared insert boundary.
- src/taskloop/admit_chain.py:121-168 — repeat producer.
- src/taskloop/admit_chain.py:220-375 — advance input/insert callers.
- src/taskloop/check_repeat/store.py:99-110 — third insert producer.
- src/taskloop/check_repeat/repair.py:52-77 — refreshed discussion/retained input caller.
- src/taskloop/admit.py:120-198 — input/preparation.
- src/taskloop/admit.py:267-317 — transaction/insert producer.
- src/taskloop/operations.py:375-492 — abandon/answer/admission callers.
- src/taskloop/prepare.py:189-263 — branch and entry checks.
- src/taskloop/composition.py:225-270 — integration points.
- src/taskloop/wip.py:24-39 — trailer identity.
- src/taskloop/evidence_files.py:273-279 — input artifact producer.
- tests/steps/test_admit.py:107-145 — admission/request producers.
- tests/steps/test_admit.py:406-436 — other request producer.
- tests/steps/test_round_holds.py:402-429 — resume expectation.
- tests/steps/round_bench.py:143-210 — factory wiring.
- tests/steps/test_factory_schema.py:22-34 — schema pin.

## Contract
TaskContent is a frozen pydantic model: task identity/title, requirements, acceptance and ordered substantive discussion/linked answers. SHA-256 its canonical encoding. Exclude status/labels/claims and adapter-classified generated hold comments, never all comments by an actor. Exclude supervisor operations only inside complete `<!-- taskloop-supervisor-operation -->` / `<!-- /taskloop-supervisor-operation -->` pairs; preserve unmarked/malformed text and relayed decisions. Capture once for digest/prompt; overflow fails without truncation.

Store nullable task_digest on plan attempts; plan repeats copy it, other producers default NULL. Reused implement admissions store source_plan_attempt_id and after_commit=H. Latest scoped plan must be verified planned/unchanged with equal digest, end commit contained by H and identical regular plan blob; never bypass a later failed plan.

PlanMetadata strictly parses this Contract TOML fence: full commit ID, bounded nonempty literal relative paths, no duplicates/traversal/pathspec magic. Require prepared_commit ancestor of H, empty scoped diff and no new WIP trailer. Deletion/rename/binary/mode changes invalidate; uncited-only changes pass. Missing metadata prevents reuse. Use typed owning Git APIs.

Intent: answered finished hold/settled abandon; manual abandon alone is ineligible. Effect: capture/check H outside transactions; under admission lock recheck attempt, hold/source and reservations, then persist selection. Result: implement attempt 1, fresh generation/seq and implement settings/overrides, or plan. cleared_at is written later. Entry requires exact H or refuses normally. Restart keeps selection. Drain before schema upgrade/discard; no history/prompt reconstruction.

```toml
prepared_commit = "c20fb48baf8a3c5fe1be81d866340df313037fb7"
cited_paths = ["src/taskloop", "tests/steps"]
```

## Work packages
1. task_content/discussion/tracker_discussion/hold_text, schema, admit_rows/admit_chain, attempt_loads and test_task_content.py: close A1; update schema pin and consult all insert producers.
2. plan_metadata/plan_step/plan_reuse/plan_reuse_git and test_plan_reuse.py: close A2.
3. admit/operations/attempt_types/prepare/composition and admission/round/restart tests: close A3. Finally run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each with pipeline exit status preserved.

## Acceptance behaviours
A1: Requirements/acceptance/discussion/linked answers or a new replan request change digest; generated hold output/marked supervisor operations do not. Plan repeats retain digest.
A2: Verified committed evidence, equal digest, valid metadata, unchanged citations and no new WIP permit reuse; each invalidation selects plan. Unavailability launches nothing. Success uses one scoped diff and zero model calls.
A3: Twice resume an unchanged 14.155-like implement hold directly at implement with correct settings and no plan attempt/start event; changed content plans. Races/ref movement/restart preserve one fenced selection; fresh/manual-abandon/discarded-DB cases plan.
