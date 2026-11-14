# Header

Task: tl-8bh9.14.194; base: f7f1c8af200724872f57c45b3100df9b9b14b76d.
Depth: medium; three behaviours. No missing decision or explicitly unlanded dependency. Evidence budget: 12 model calls.
Size: 26 changed files including tests/plan; 3 independent behaviours; 90 implement model calls.

## Outcome and non-goals

Complete origin-main admission's release and test integration. Fetch, source selection, advance fallback, park destination and moved-origin coverage already exist; retain them and close fixture/policy gaps. Exclude schema upgrades, supervisor changes, new adapters and land algorithm changes.

## Settled decisions

- Use the glossary's “remote-tracking ref” for refs/remotes/origin/main; MAIN retains its local meaning.
- Refresh before input, claim or reservation with land's bounded refspec/timeout.
- Select local task work, remote-tracking task work, then fetched origin main.
- Retain continued merge/reconciliation and repeat-leftover bypass.
- Separate observed HEAD from recorded park destination; later origin moves cannot change it.
- Repair fixture prerequisites while preserving original assertions.

## Open decisions

- None.

## Change map

- src/taskloop/prepare.py — refreshed_sources, branch_refusal, _take: retain refresh/selection/fences; fix demonstrated gaps.
- src/taskloop/admit.py — Admission.admit, branched, Free, unheld: retain admission and distinct observed/park commits.
- src/taskloop/admit_chain.py — _free, _advance, _containing: verify caller, reservation and previous-commit fallback.
- src/taskloop/check_repeat/store.py — CheckRepeatStore.free/admit: verify repair caller/reservation.
- src/taskloop/check_admit.py — heads, reservation caller: retain checks-specific Free producer.
- src/taskloop/land_check.py — _reserved: consult heads/unheld consumer.
- src/taskloop/land_push.py — fetched: consult bounded-fetch precedent.
- src/taskloop/merge/prepare.py — SourcePreparation: consult preparation caller/base fences.
- src/taskloop/merge/start.py — _target, attachment: preserve merge/resume.
- src/taskloop/slot_release.py — park, release caller: preserve destination/retry semantics.
- tests/steps/doubles.py — main_at: consult local-main semantics; repair dependent test setup.
- tests/steps/conftest.py — repo, slot: consult origin/slot producers.
- tests/steps/test_prepare_main.py — branch_refusal, moved-origin cases: complete acceptance coverage.
- tests/steps/test_prepare.py — branch_refusal cases: preserve selection protections.
- tests/steps/test_merge_prepare.py — branch_refusal caller, preparation cases: preserve merge/resume coverage.
- tests/steps/test_plan_content.py — reuse cases calling main_at: seed selected history; retain validation.
- tests/steps/test_publish.py — remote, run: align retained-plan/ignore-rule prerequisites.
- tests/steps/test_advance.py — refresh/fallback cases: align origin setup; retain previous-commit fences.
- tests/steps/test_slot_release.py — executed, release cases: align setup; retain destination assertions.
- tests/steps/test_check_repeat.py — repair cases: preserve refresh/reservation/interruption coverage.
- tests/steps/real/test_prepare_real.py — preparation case: retain offline moved-origin proof.
- tests/steps/real/test_release_real.py — Repository: supply local origin.
- tests/rules/test_policy.py — Git-writer assertion: admit prepare.py's fetch owner explicitly.

## Read list

- src/taskloop/prepare.py:107-224 — selection/refresh/recheck.
- src/taskloop/admit.py:152-178 — admission/input caller.
- src/taskloop/admit.py:265-400 — reservation and park producer/consumer.
- src/taskloop/admit_chain.py:302-398 — advance/containment.
- src/taskloop/check_repeat/store.py:61-110 — repair caller/reservation.
- src/taskloop/check_admit.py:225-279 — checks reservation/Free producer.
- src/taskloop/land_check.py:105-125 — candidate reservation.
- src/taskloop/land_push.py:80-85 — fetch precedent.
- src/taskloop/merge/prepare.py:27-83 — preparation/base fence.
- src/taskloop/merge/start.py:117-158 — attach/refresh/ancestry.
- src/taskloop/slot_release.py:104-155 — park/preservation.
- src/taskloop/slot_release.py:310-355 — release caller.
- tests/steps/doubles.py:54-60 — local-main helper.
- tests/steps/conftest.py:40-65 — origin/slot fixtures.
- tests/steps/test_prepare_main.py:101-185 — moved-origin/failure contracts.
- tests/steps/test_prepare.py:145-196 — selection safety.
- tests/steps/test_merge_prepare.py:19-136 — continued merge/resume.
- tests/steps/test_plan_content.py:77-136 — retained-plan fixtures.
- tests/steps/test_publish.py:82-146 — origin/execution fixtures.
- tests/steps/test_advance.py:40-95 — advance/moved-origin proof.
- tests/steps/test_slot_release.py:127-212 — setup/interrupted release.
- tests/steps/test_check_repeat.py:270-342 — repair admission/interruption.
- tests/steps/real/test_prepare_real.py:55-114 — offline preparation.
- tests/steps/real/test_release_real.py:74-110 — missing-origin fixture.
- tests/rules/test_policy.py:209-226 — Git ownership assertion.

## Contract

Intent: refresh/select source. Effect: bounded fetch updates origin's remote-tracking main outside write transactions. Result: Free.head remains observed HEAD; Free.source selects input/history; Free.park_commit captures origin main. Raised or structured fetch failure is unavailable with explanation; missing origin main refuses the target before input, claim or reservation. No local-main fallback.

Intent: admit/advance/repair. Effect: existing reservation transaction stores the park commit in slot_head. Result: unheld consumers agree; checks/land candidates retain observed destinations through check_admit.heads. No new stored field, schema version or outcome vocabulary.

Intent: prepare retained work. Effect: existing merge intent records source/target before mutation; resume observes effects. Result: both histories and previous published work survive; repeat leftovers stay intact.

Intent: release. Effect: under custody validate pointer, cleanliness, branch and stop proof; park outside the write transaction, then record completion. Result: task commits survive; retries converge without fetching. The person's main, HEAD, index and files remain untouched.

## Work packages

1. Audit listed producers/consumers; preserve implemented refresh/source/park behaviour and fix demonstrated preparation/admission gaps. Closes A1 and admission portions of A2/A3.
2. Repair listed fixtures by placing retained plans, ignore rules and other prerequisites on origin or retained task history. Supply local origin for offline release tests; update the exact Git-writer assertion. Preserve schema refusals and test purposes. Closes remaining A2/A3 integration.
3. Complete semantic-fake/offline proofs below. Search narrowly for newly exposed callers before editing. Finish with one run each, last, preserving failure status: just check 2>&1 | tail -60, then just test 2>&1 | tail -40. Closes A1-A3.

## Acceptance behaviours

A1. With checkout main/tracking main at A and fake origin alone at B, admission fetches B, selects B for input and creates its task branch there; refresh failure creates no input, claim or reservation. Works without local main.
A2. Local or remote-only retained work survives preparation and contains refreshed origin main; advance preserves its previous published commit and repair follows shared admission. Unrelated, foreign or held work stays protected.
A3. Release leaves the slot clean/detached at its recorded admission origin tip, retaining results; interrupted retries converge despite later origin movement, and next admission refreshes again. Across A1-A3, the person's main ref, HEAD, staged and unstaged files remain unchanged.
