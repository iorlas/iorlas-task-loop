# Header
Task: tl-8bh9.14.171.2.2
Base: b8e8afc1fc18b9c6b09ea86017e1efbbfc8ca724
Depth: medium; entry, environment and forwarding migration.
Decision: none missing. Dependency: part 1 landed.
Evidence: 12 model calls maximum.
Size: 19 changed files, 1 behaviour, about 40 implement model calls.

## Outcome and non-goals
Complete the typed claim path from lease renewal through setup and entry decisions to display. The enum, codec, heartbeat results and KeepAlive state already exist. Remaining work replaces the separate string renewal vocabulary, consumer comparisons and string-returning callbacks. Preserve lease timing, refusal order, release, recovery fencing and displayed claim spellings. No schema, tracker adapter behaviour or shelf changes.

## Settled decisions
- Reuse claim.ClaimWord and encode_claim; do not introduce another vocabulary or codec.
- Delete environment.Renewal; Renew returns ClaimWord. Forwarding signatures retain Renew.
- renewal maps FAULT to UNRENEWED, retaining the existing three-outcome renewal contract.
- Branch on enum members; encode only where claim text enters an output line.
- Existing heartbeat and KeepAlive enum work needs no reimplementation.

## Open decisions
- None.

## Change map
- src/taskloop/claim.py — ClaimWord, encode_claim: reuse existing vocabulary and output codec.
- src/taskloop/tracker_client.py — beat_of, heartbeat_for: consult existing typed producers; preserve.
- src/taskloop/claim_lease.py — renewal: return enum members and preserve FAULT normalization.
- src/taskloop/environment.py — Renew, Preparation._finish: delete Renewal, type the callback with ClaimWord and compare LOST by member.
- src/taskloop/attempt_entry.py — _claimed: compare LOST/HELD members and encode claim output.
- src/taskloop/check_entry.py — _claimed, _ended: carry ClaimWord through conclusion and encode each output path.
- src/taskloop/land_check.py — _ended: compare LOST by member before reconcile or validate.
- src/taskloop/attempt.py — Attempts.execute, _start, _prepared: consult forwarding and optional-port refusal.
- src/taskloop/validate.py — validate, _at, _environment: consult forwarding into Preparation.
- src/taskloop/merge/prepare.py — SourcePreparation.prepare: consult forwarding into merge setup.
- src/taskloop/land_conflict/execute.py — Ports.renew, execute: consult typed port and setup forwarding.
- src/taskloop/land_conflict/composition.py — conflict_handoff.execution: consult renewal wiring into ExecutionPorts.
- tests/steps/test_environment.py — Entry.renew, held, ChecksSlot.prepare: enum callbacks, defaults and refusal inputs.
- tests/steps/real/test_environment_real.py — held: enum callback; preserve existing test scope.
- tests/steps/test_attempt_answers.py — test_unfinished_answers_with_paths_are_collected_without_commit_or_repeat: enum callback.
- tests/steps/test_admit_chain.py — execute: enum callback.
- tests/steps/test_prepare.py — execute: enum callback.
- tests/steps/round_bench.py — attempts.execute caller: enum callback.
- tests/steps/test_input_context.py — prior.execute, attempts.execute callers: enum callbacks.
- tests/steps/test_validate.py — Bench.__call__: enum callback.
- tests/steps/land_bench.py — with_conflict_execution: enum callback into ExecutionPorts.
- tests/steps/land_conflict_bench.py — execution_case: enum callback into Ports.
- tests/steps/test_claim_lease.py — renewal fault case: assert enum identity for normalized result.
- tests/steps/test_attempt_entry.py — renewal parametrization: enum results; retain string expectations for printed output.
- tests/steps/test_check_entry.py — Bench, claim-loss cases: consult existing enum heartbeat fixtures and output/refusal assertions.
- docs/design/tl-8bh9.14.171.2.2/plan.md — new: implementation scope and acceptance.
- docs/design/tl-8bh9.14.171.2.2/plan-metadata.json — new: prepared commit and consulted paths for plan reuse.

## Read list
- src/taskloop/claim.py:1-20 — enum and codec.
- src/taskloop/tracker_client.py:153-220 — heartbeat producer and error mapping.
- src/taskloop/claim_lease.py:82-117 — enum result and renewal normalization.
- src/taskloop/environment.py:35-48; src/taskloop/environment.py:194-245 — port definition, setup and refusal.
- src/taskloop/attempt_entry.py:320-345 — initial/recovery decisions and output.
- src/taskloop/check_entry.py:127-158 — validation, conclusion and output branches.
- src/taskloop/land_check.py:180-189 — renewal before land validation.
- src/taskloop/attempt.py:95-103; src/taskloop/attempt.py:224-246 — entry port and setup forwarding.
- src/taskloop/validate.py:132-158 — validation setup forwarding.
- src/taskloop/merge/prepare.py:28-58 — optional renewal and merge setup.
- src/taskloop/land_conflict/execute.py:32-95 — Ports and setup forwarding.
- src/taskloop/land_conflict/composition.py:42-53 — renewal wiring.
- tests/steps/test_environment.py:60-100; tests/steps/test_environment.py:185-205; tests/steps/test_environment.py:479-580 — callbacks, loss, unrenewed and checks setup.
- tests/steps/real/test_environment_real.py:20-41 — callback type and value.
- tests/steps/test_attempt_answers.py:63-83 — execute callback.
- tests/steps/test_admit_chain.py:59-77 — execute helper.
- tests/steps/test_prepare.py:109-120 — execute helper.
- tests/steps/round_bench.py:197-208 — execute caller.
- tests/steps/test_input_context.py:260-285 — both execute callers.
- tests/steps/test_validate.py:57-70 — validation callback.
- tests/steps/land_bench.py:255-266 — conflict port callback.
- tests/steps/land_conflict_bench.py:129-138 — conflict port callback.
- tests/steps/test_claim_lease.py:163-171 — normalized fault assertion.
- tests/steps/test_attempt_entry.py:388-410; tests/steps/test_attempt_entry.py:482-495 — printed text and renewal assertions.
- tests/steps/test_check_entry.py:185-212 — claim-loss behaviour and printed results.

## Contract
Intent: one renewal callback requests a beat; Renew is Callable[[], ClaimWord]. Remove Renewal rather than retaining an alias. Forwarders pass the callback without conversion or display-text inspection.

Effect: renewal invokes KeepAlive.renew once and obtains its enum word. HELD and LOST remain themselves; UNRENEWED and FAULT return UNRENEWED. KeepAlive.word retains its full four-member result. No new IO, stored fields or state transitions.

Result: environment refuses LOST after setup; entry refuses initial LOST and recovery without HELD; checks and land reconcile before concluding an initial LOST. Later losses remain recorded in output. ClaimWord reaches check_entry._ended without weakening to str. Every claim display branch uses encode_claim; surrounding refusal reasons, exit codes and output text remain byte-for-byte compatible.

## Work packages
1. Update environment.py and claim_lease.py; migrate callback inputs in all listed test helpers and tests. Keep forwarding callers on Renew and confirm their integration. Closes A1.
2. Update attempt_entry.py, check_entry.py and land_check.py; adapt enum assertions in test_attempt_entry.py and test_claim_lease.py. Extend existing focused cases only where needed to distinguish enum identity from StrEnum/string equality and cover refusal/output paths. Closes A1.
3. Review the targeted caller inventory for remaining claim-string logic. Run focused changed behaviour tests if needed, then run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last. No live tests. Closes A1.

## Acceptance behaviours
A1. Claim results remain enum-valued through renewal, setup, forwarding and entry decisions: fault normalizes to UNRENEWED, LOST refuses at the same boundary, ordinary unrenewed setup continues, recovery still requires HELD, and every printed claim outcome retains its exact text.
