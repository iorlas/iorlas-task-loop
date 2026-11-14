# Header
Task: tl-8bh9.14.137.3; base: 0a5fc0785ac09d65a21716e2577794095dc216d8
Depth: medium; routing and terminal holds, 2 behaviours.
Owner decisions: none missing; dependencies landed. Evidence budget: 12 model calls.
Size: 14 changed files including tests/plan, 2 behaviours, 55 implement calls.

## Outcome and non-goals
Route answer failures through existing same-session repair before terminal handling. A rejected repair exposes its own broken rule. Preserve round-owned holds and manual-start terminal reports. Decoding, durable admission, continuation, storage and dashboard features are outside scope.

## Settled decisions
- The predecessor's AnswerRepair.admit owns the successor, stop proof, original deadline and same-session context.
- Admission.repair distinguishes a repair from its original attempt; attempt number and Git-repeat caps do not decide repair eligibility.
- AnswerFailureData owns the broken rule and explanation; diagnostics and display text are not control inputs.
- A repair refusal retains terminal handling; an unavailable operation defers it. Existing hold/release and current-attempt fences remain authoritative.

## Open decisions
- None.

## Change map
- `src/taskloop/answer_repair_route.py` (new): AnswerRepairRouting.route; integrate through StartPorts.answer_repair, operations._start and round._settle; use AnswerRepair.admit and the ordinary launcher.
- `src/taskloop/operations.py`: StartPorts and _start delegate captured answer failures before StepRepeat.repeat; retain current-attempt, hold and release checks.
- `src/taskloop/cli_composition.py`: _starting wires open_answer_repair into the shared routing operation for both open_start and open_next.
- `src/taskloop/round.py`: _settle consults the shared route before terminal hold/release/report; _resume remains the existing entry/Git-repeat caller.
- `src/taskloop/hold_facts.py`: facts/explanation carry the latest captured AnswerFailureData into the hold's explanation without rereading an invalid answer as valid.
- `src/taskloop/hold_cause.py`: _answer explains the terminal answer rejection using the supplied rule explanation rather than only directing the reader to diagnostics.
- `tests/steps/round_bench.py`: Factory.starting supplies the real routing operation with semantic process observations and its existing launcher.
- `tests/steps/test_answer_repair_routing.py` (new): exercise shared routing and round outcomes using test_answer_repair and round_bench integration points.
- `tests/cli/test_answer_repair_cli.py` (new): exercise cli_step._start through open_start/start with the real routing decision and a counted launcher.
- `tests/steps/test_hold_text.py`: verify the latest broken rule reaches the rendered terminal hold.
- `docs/design/tl-8bh9.14.137.3/plan.md` (new): this implementation contract.
- Consult callers: cli_step._start and round._admit/_advance -> start; round._settle -> _resume/_held/_released; composition.open_answer_repair -> AnswerRepair; test_operations constructs StartPorts; hold.hold_task -> hold_facts.facts; attempt_status.show_attempt -> hold_facts.explanation.

## Read list
- `src/taskloop/answer_repair.py:17-66` — existing admission operation and stop proof.
- `src/taskloop/answer_repair_models.py:10-22` — frozen context and outcomes.
- `src/taskloop/answer_repair_store.py:20-90` — result, successor adoption and refusal boundaries.
- `src/taskloop/answer_failures.py:8-31` — typed rule and explanation producer.
- `src/taskloop/hold.py:20-35` — hold operation's facts-reader integration imports.
- `src/taskloop/attempt_result.py:47-97` — terminal report and failure explanation producer.
- `src/taskloop/operations.py:131-169` — StartPorts and existing protocols.
- `src/taskloop/operations.py:325-403` — start routing and hold/release fences.
- `src/taskloop/cli_step.py:169-175` — CLI start consumer.
- `src/taskloop/cli_composition.py:128-190` — CLI/round shared composition.
- `src/taskloop/composition.py:282-286` — existing repair composition integration point.
- `src/taskloop/round.py:226-312` — terminal actions, snapshot checks and repeat caller.
- `src/taskloop/round.py:368-450` — advance/ingestion start callers.
- `src/taskloop/repeat.py:75-110` — existing captured-attempt fallthrough.
- `src/taskloop/hold_status.py:49-77` — existing terminal hold policy.
- `src/taskloop/attempt_status.py:392-400` — persisted/due hold precedence.
- `src/taskloop/hold_facts.py:72-79` — explanation consumer used by status.
- `src/taskloop/hold_facts.py:107-138` — durable hold facts assembly.
- `src/taskloop/hold_cause.py:105-120` — answer cause wording.
- `tests/steps/test_answer_repair.py:45-77` — captured invalid-answer setup and admission helpers.
- `tests/steps/round_bench.py:147-225` — round launcher, start wiring and observations.
- `tests/steps/test_round_holds.py:34-72` — round/hold fixture integration.
- `tests/steps/test_operations.py:640-670` — existing captured-start caller expectations.
- `tests/cli/test_step_cli.py:1-68` — CLI composition seams and response contract.
- `tests/steps/test_hold_text.py:10-47` — existing comment assertion pattern.

## Contract
Intent: inject a typed routing operation through StartPorts, taking task identity, AttemptKey and launch inputs. Read execution/admission through their owner; distinguish first rejection from repair using typed failure and Admission.repair. Transport failure, timeout, stop and unresolved sessions retain existing handling.

Effect: call AnswerRepair.admit for the first eligible rejection. ADMITTED/EXISTING launches the saved successor through the ordinary launcher. Launch failure leaves it for normal reconciliation/relaunch, without holding/releasing the original. Retain the original deadline and continuation context. Concurrent callers adopt one successor; dispatch ownership prevents duplicate execution.

Result: Started/Failed or an explicit no-routing result; new closed reasons use enums. UNAVAILABLE defers terminal effects. REFUSED retains its explanation and allows terminal handling only against the current attempt. Admission.repair forbids another repair; its latest rule supplies the hold explanation. Respect existing holds, abandonments and releases; fence stale snapshots.

No stored fields change. Put helpers in the new module; orchestration receives delegations. Allow necessary extraction within Size. Status keeps its vocabulary; execution routes repair before acting on a terminal snapshot.

## Work packages
1. Add shared routing and wire operations._start plus cli_composition._starting. Use new focused tests through CLI and the existing captured-answer fixture. Closes A1.
2. Delegate from round._settle before terminal effects; wire Factory.starting. Test successor launch/relaunch, refusal, unavailable admission and stale snapshots with semantic fakes. Closes A1 and A2.
3. Supply the latest typed failure in hold_facts and update answer-cause wording. Verify the final comment and repeated-round stability. Closes A2. Finish the implement attempt with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, last; no live execution.

## Acceptance behaviours
A1: CLI and rounds launch one same-session repair before terminal handling; a valid correction follows normal verification. Concurrent calls/restart adopt that successor. Unavailable admission/launch causes no premature hold/release. Execution failures keep existing handling.
A2: An invalid repair causes no third invocation. Rounds hold once with its latest rule/explanation, including a changed rule; CLI reports that failure. Later rounds leave it held; stale snapshots cannot hold a successor. Git repeats and valid owner-decision answers retain existing behaviour.
