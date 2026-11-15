# Header
Task: tl-8bh9.14.171.2.1; base: 74641862ca9f7cc6a2754ada170dc29b0d15459f
Depth: medium; codec and two producer modules.
Owner decisions: settled; unlanded dependencies: none.
Evidence budget: 12 model calls.
Size: 14 changed files, 3 behaviours, about 40 implement model calls.

## Outcome and non-goals
Make the claim producer boundary return shared enum members with exact text conversion. Preserve heartbeat classification, lease timing, renewal mapping and entry output. Consumer vocabulary migration belongs to tl-8bh9.14.171.2.2; leave environment.Renewal and downstream string comparisons in that scope. No storage or shelf changes.

## Settled decisions
- ClaimWord is a stdlib StrEnum in new src/taskloop/claim.py, replacing the claim_lease Literal of that name.
- HELD, LOST, UNRENEWED and FAULT retain lowercase values; encode_claim/decode_claim own exact text conversion.
- Beat remains a type alias restricted to the first three enum members; a tracker heartbeat never produces FAULT.
- KeepAlive records exceptions as FAULT; renewal maps FAULT to the existing UNRENEWED port spelling.

## Open decisions
- None.

## Change map
- src/taskloop/claim.py (new): ClaimWord, decode_claim, encode_claim; integrate through claim_lease and tracker_client.
- src/taskloop/claim_lease.py: Beat, Heartbeat, KeepAlive.renew/word and renewal use the shared enum; preserve scheduling and port mapping.
- src/taskloop/tracker_client.py: beat_of and tracker_claims.heartbeat_for return members without changing adapter error classification.
- tests/steps/test_claim.py (new): exercise the codec through the new claim module.
- tests/steps/test_claim_lease.py: Beats and lease scenarios use members and identity assertions; cover precedence and timing.
- tests/steps/test_admit.py: tracker heartbeat results assert member identity; retain bounded-call assertions.
- tests/steps/test_attempt_entry.py: Entry.heartbeat_for, scripted beats and renewal cases produce members.
- tests/steps/test_check_entry.py: Bench.heartbeat_for and scripted beats produce members.
- tests/steps/test_recovery_entry.py: run_entry and beat callbacks use enum inputs; preserve refusal assertions.
- tests/steps/land_bench.py: LandBench.beats/heartbeat_for produce members.
- tests/steps/real/test_land_real.py: heartbeat_for returns HELD; preserve the real-test fixture contract.
- tests/steps/test_land_resume.py: initial lost-claim case supplies LOST to LandBench.
- src/taskloop/attempt_entry.py: enter/_claimed/main consult only; preserve comparisons and claim text.
- src/taskloop/check_entry.py: enter/_claimed/main consult only; preserve refusal and result text.
- src/taskloop/land_check.py: LandPorts/_run consult only; preserve validation renewal and loss refusal.
- src/taskloop/land_conflict/composition.py: conflict_handoff/land_ports consult only; preserve heartbeat forwarding.
- src/taskloop/composition.py: open_admission/SlotRelease wiring consult only; preserve claim/unclaim callers.
- src/taskloop/drain/composition.py: _return_claim consult only; unclaim caller remains unaffected.
- src/taskloop/environment.py: Renewal/Renew consult only; retain the current renewal port.
- .importlinter: inspect existing dependency contracts for the new leaf module; no new dependency direction.
- docs/design/tl-8bh9.14.171.2.1/plan.md: implementation contract.
- docs/design/tl-8bh9.14.171.2.1/plan-metadata.json: preparation evidence.

## Read list
- src/taskloop/claim_lease.py:14-116 — producer types, lease state, timing and renewal mapping.
- src/taskloop/tracker_client.py:12-22 — imports for the enum producer.
- src/taskloop/tracker_client.py:123-224 — claims port, error mapping and bound heartbeat.
- src/taskloop/attempt_entry.py:271-338 — heartbeat construction, initial refusal and printed word.
- src/taskloop/check_entry.py:98-142 — heartbeat construction, refusal and conclusion text.
- src/taskloop/land_check.py:174-189 — validation renewal and loss handling.
- src/taskloop/land_conflict/composition.py:33-61 — handoff and land heartbeat forwarding.
- src/taskloop/composition.py:203-212 — SlotRelease unclaim wiring.
- src/taskloop/composition.py:256-274 — open_admission claim/unclaim wiring.
- src/taskloop/drain/composition.py:38-46 — unclaim caller outside lease producers.
- src/taskloop/environment.py:35-45 — unchanged renewal port types.
- tests/steps/test_claim_lease.py:8-134 — fake heartbeat producer, timing and fault mapping.
- tests/steps/test_admit.py:505-549 — tracker reply mapping and heartbeat call bounds.
- tests/steps/test_attempt_entry.py:24-170 — imports, Entry defaults and heartbeat callback.
- tests/steps/test_attempt_entry.py:290-489 — lost claim, run outcomes and post-setup renewal inputs.
- tests/steps/test_check_entry.py:26-110 — Bench defaults and heartbeat callback.
- tests/steps/test_check_entry.py:189-211 — initial, post-setup and later claim loss.
- tests/steps/test_check_entry.py:407-420 — interrupted results on lost claim.
- tests/steps/test_recovery_entry.py:18-55 — callback annotations and run_entry wiring.
- tests/steps/test_recovery_entry.py:90-126 — recovery heartbeat producers.
- tests/steps/land_bench.py:132-145 — typed heartbeat script default.
- tests/steps/land_bench.py:190-198 — LandBench heartbeat callback.
- tests/steps/real/test_land_real.py:24-65 — imports and heartbeat fixture.
- tests/steps/test_land_resume.py:136-145 — lost claim validation refusal.
- .importlinter:1-115 — existing dependency directions at producer integration points.

## Contract
Intent: one claim vocabulary. Effect: ClaimWord owns four values; decode_claim(str) returns ClaimWord or raises ValueError; encode_claim(ClaimWord) returns its value. Result: exact round trips preserve identity.

Intent: typed tracker observations. Effect: Beat is Literal[ClaimWord.HELD, ClaimWord.LOST, ClaimWord.UNRENEWED]; Heartbeat/HeartbeatFor use it. Success returns HELD; existing lost-error cases return LOST, other failures UNRENEWED. Result: timeout, root binding and zero lock retries stay intact.

Intent: preserve lease judgments. Effect: KeepAlive compares members and word() returns ClaimWord. LOST outranks FAULT; both outrank HELD/UNRENEWED. Any observed lapse remains decisive, with renewal judged from call start and elapsed time checked at call end and final observation. Result: lost/fault stops background renewing; neither changes the running step's result. Thread start/stop/join and constants stay intact.

Intent: retain the renewal boundary. Effect: renewal(alive) renews once, maps HELD/LOST to their Renewal strings and other results to unrenewed. Result: stable caller behavior; no stored fields change.

## Work packages
1. Add claim.py/test_claim.py; replace claim_lease's ClaimWord declaration and Beat alias. Closes A1.
2. Update tracker_client/test_admit and claim_lease/test_claim_lease for enum production, comparisons and renewal mapping. Closes A2/A3.
3. Update fixtures in test_attempt_entry, test_check_entry, test_recovery_entry, land_bench, real/test_land_real and test_land_resume. Verify focused codec, lease, tracker and caller behavior through the installed package, plus import contracts. Closes A2/A3 across callers. Finish with pipefail enabled: `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, last.

## Acceptance behaviours
A1. All four exact claim spellings round-trip with member identity; unknown, empty, padded and case-changed spellings fail decoding.
A2. Tracker heartbeat success, lost-claim replies and unavailable replies yield the corresponding enum members while preserving call bounds and classification.
A3. KeepAlive returns members with unchanged lease timing, lapse persistence, LOST-before-FAULT precedence and stop behavior; renewal mapping, initial refusal and printed claim text remain exact across entries, recovery and land validation.
