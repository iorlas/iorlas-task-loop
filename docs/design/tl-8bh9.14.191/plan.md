# Header
Task: tl-8bh9.14.191
Base: 7976bd5a7ac17d707f103677272357c8cc67fc37
Depth: medium; prompts, validation, measurement; 12 evidence calls.
Size: at most 45 files, 3 behaviours, 60 implement calls.
No missing owner decision or explicitly unlanded dependency.

## Outcome and non-goals
Make plans compact, immutable and sufficient to locate changes. Enforce plan refusals and implement path protection; measure ten plans before tuning caps. No historical rewrites, scheduler, migration or telemetry pipeline.

## Settled decisions
- Use the specified section order/allowances; change map/contract may consume spare space within the total cap. Cite supplied task decision numbers.
- Header replaces .190's Depth/Size headings with depth/budget and .179 estimates. Retain early assessment/split thresholds and .174 holds/reruns.
- Caps mean UTF-8 bytes: small 4,000, medium 8,000, large 12,000; equality passes.
- Prompt content prohibitions; mechanically enforce headings/caps, without semantic prose classification.
- Unresolved decisions require needs_owner. Over-cap work requires a split with acceptance/dependencies per part.
- Preserve implement's existing edit prohibition; add decoder enforcement and commit-message handoff.

## Open decisions
None.

## Change map
Source paths below are under src/taskloop/; read-only entries identify callers/readers.

- plan_step.py — DEPTH_ASSESSMENT/_closing_words/input_text/feedback: template/caps; artifact/_content/ARTIFACT_RULES: validation.
- implement_step.py — decode: reject plan paths; _closing_words/repeat_instructions: immutable plan, commit handoff.
- attempt_types.py — Rule/Rejected: depth/refusal enums, unchanged result shape.
- hold_cause.py — RULES: removal advice; replace one-MiB plan_size explanation.
- steps.py — PLAN/IMPLEMENT/RULES: read-only registry consumers.
- attempt.py — step.decode: read-only answer collection caller.
- hold_facts.py — found.decode: read-only answer reread caller.
- verdict.py — judge/_artifact: read-only completion/reuse callers.
- attempt_loads.py — verdict_of/_execution: rule decoding and token reader.
- attempt_store.py — _verdict_values: reason encoding edge.
- evidence_files.py — EvidenceFiles.events_path/activity_after: read-only evidence.
- activity_file.py — ActivityPage/follow: read-only structured activity paging.

Test paths below are under tests/steps/; successful plan fixtures need explicit depth, never implicit fake rewriting.

- test_steps.py — prompt cases: template/depth/Size/repeats/immutability.
- test_answer_contract.py — implement/unfinished cases: reject all plan paths.
- test_verifier.py — PLANNED/CASES/trailer_commit: fixtures, caps, headings, reuse.
- test_hold_text.py — cause cases: removal advice.
- refusal_inventory.py — typed_reasons/REVIEWED_DYNAMIC: include enum values.
- doubles.py — shared valid plan text: explicit-depth fixture.
- test_repeat.py — captured: use valid fixture.
- test_repeat_dispatch.py — Agent/reused bytes: distinct valid revisions.
- test_attempt_entry.py — Entry written inputs: valid fixture.
- test_admit_chain.py — execute writers: valid fixture.
- test_merge_advance.py — path writers: include depth.
- test_conflict_recovery.py — plan writer: include depth.
- test_slot_release.py — executed: valid fixture.
- test_slot_lock.py — captured: valid fixture.
- test_publish.py — run/remote: consistent valid fixtures.
- test_round_holds.py — retained bytes assertion: match producer.
- test_input_context.py — captured: valid fixture if artifact-verified.
- real/test_release_real.py — plan writer: fixture depth only.
- real/test_repeat_real.py — revisions: fixture depth only.
- real/test_publish_real.py — plan writer: fixture depth only.
- real/test_prepare_real.py — plan writer: update if artifact-verified.
- real/test_commit_real.py — plan writer: update if artifact-verified.

## Contract
Header field: `Depth: small|medium|large`, optionally followed by a semicolon/explanation. A stdlib enum owns values/caps; pydantic v2 validates the edge. Missing, duplicate or unknown depth refuses completion.

Retain path/mode/UTF-8/nonempty checks. artifact checks total bytes for planned and unchanged separately from StepRules.file_cap. Match forbidden ATX/setext headings case-insensitively, ignoring fences/closing hashes: As built, Status, Progress, including `Status: implemented` and `Implementation progress`. Ordinary prose passes.

New format refusals are enum members in Rule/steps.RULES; retain plan_size for byte excess. Encode at _verdict_values; decode at verdict_of. No stored fields/phases/schema keys change. Coverage fails for missing explanations. Prose says to remove headings/content, supply one depth, or remove duplication/split; no CLI instructions or machine codes.

Implement decode rejects any supplied path ending in the component plan.md, case-insensitively, for every disposition, including deletions/other tasks. Check before discarding unfinished paths; retain other structural rules and invalid-answer outcome.

Intent/effect/result: plan answer -> commit/reuse verification -> Verified/Rejected; implement answer -> decode before commit intent -> Answer/invalid answer. Observation -> owning readers -> task comments, never scheduling state. No new external action path.

## Work packages
1. Update plan/implement prompt symbols and test_steps.py: template/allowances, Header depth/Size, prohibitions/caps and handoff. Closes A1-A3.
2. Add artifact checks/refusals/explanations; update mapped fixtures/census. Exercise commit/reuse and stored decoding. Closes A4-A6.
3. Update implement decode and test_answer_contract.py for plan protection, unfinished answers and repeat/check feedback. Closes A7.
4. At first use, comment the protocol on this task through the owning tracker operation when available. Select the first ten distinct accepted new-template plans in acceptance order; freeze each commit/blob and include every associated implement attempt. Record task/attempt IDs, depth, exact plan bytes, model/harness, per-attempt input/cached/output tokens, and tool calls reading files absent from the change map. Normalize paths; count each call once even for compound reads. Inspect structured activity/session evidence through owning readers; missing/truncated evidence is unknown, never zero. Do not sum cumulative session tokens again. Add figures and depth-grouped summaries as comments, noting missing pointers and cap refusals. Compare cautiously with the supplied audit. After ten plans and their attempts finish, adjust the shared caps and boundary/prompt expectations from observed size and missing-context evidence; explain any retained cap. This empirical acceptance remains outstanding until actual samples exist. Closes A8.

## Acceptance behaviours
A1. First/repeated inputs specify ordered sections, allowances and prohibitions without conflicting Depth/Size headings.
A2. Open decisions remain unanswered and require needs_owner; over-cap work returns a concrete split without a successful oversized plan.
A3. Change maps name producer/caller symbols; packages identify acceptance lines.
A4. Every depth passes its exact byte cap and refuses one extra byte, including multibyte text and reused plans; invalid depth cannot bypass the cap.
A5. Forbidden headings and their syntax/case/status variants refuse completion with removal advice; ordinary prose and fenced examples pass.
A6. Every refusal survives stored-verdict decoding and has a nonempty words-only explanation; general file safety checks remain separate.
A7. Every implement disposition rejects plan.md paths; initial/repeated/check-feedback text keeps plans immutable and uses the commit message for handoff.
A8. Comments contain ten plan measurements, associated implement evidence, unknowns and summaries, then measured cap adjustments or justified retention.
