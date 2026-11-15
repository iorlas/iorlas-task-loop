# Header
Task: tl-8bh9.14.146.1.1
Base: cd64b25ec06d8255e15670a51b0aee06d3889bc9
Depth: small; one message behaviour in one module.
Owner decision: none. Unlanded dependency: none stated.
Evidence budget: 6 model calls.
Size: 2 changed files, 1 independent behaviour, 16 implement model calls.

## Outcome and non-goals
Admission refusals explain the land situation and decision in words. Refusal selection and propagation already work; two messages and a test still require commands. Broader message changes belong to sibling tasks.

## Settled decisions
- Delivered code needs task closure completed; checks cannot rerun.
- An outstanding candidate needs delivery completed or withdrawal chosen; checks cannot rerun meanwhile.
- Update the existing admission regression instead of adding a message abstraction.

## Open decisions
- None.

## Change map
- `src/taskloop/check_admit.py`: edit `LAND_GUIDE`; consult `next_number`, `ChecksAdmission._previous`, `_commit` and `admit_checks` to preserve both refusal paths.
- `tests/steps/test_check_admit.py`: update `test_a_re_run_is_refused_while_a_land_candidate_of_the_task_is_delivered_or_pushable`; consult the advance test's `admit_checks` call. Check prose and preserve state assertions.
- `src/taskloop/operations.py`: consult `_admit` and `ChecksAdmit.admit_checks`; preserve propagation into `Failed`.
- `src/taskloop/composition.py`: consult `open_checks_admission`; retain wiring.
- `tests/steps/doubles.py`: consult `ChecksBench.admission`, `ChecksBench.admit` and `NoChecks.admit_checks`; retain test integration.
- `tests/steps/test_checks_round.py`: consult `starting` and the `ChecksRequest` admission callback; retain round integration.
- `tests/steps/test_check_repeat.py`: consult the `ChecksRequest` admission call; retain repeat integration.
- `tests/steps/round_bench.py`: consult `NoRequired.admit_checks`; retain fake.
- `src/taskloop/admit.py`: consult `AdmitRefused`; retain its result contract.

## Read list
- `src/taskloop/check_admit.py:62-111` — message producer and refusal selection.
- `src/taskloop/check_admit.py:133-162` — admission and preflight propagation.
- `src/taskloop/check_admit.py:216-237` — refusal under the write lock.
- `tests/steps/test_check_admit.py:27-43` — fixture and direct caller.
- `tests/steps/test_check_admit.py:151-175` — delivered, outstanding and withdrawn regression cases.
- `src/taskloop/operations.py:472-494` — production caller and detail propagation.
- `src/taskloop/composition.py:301-307` — constructor integration.
- `tests/steps/doubles.py:214-218` — alternate admission fake.
- `tests/steps/doubles.py:435-449` — admission bench callers and stored-state reader.
- `tests/steps/test_checks_round.py:81-86` — round constructor caller.
- `tests/steps/test_checks_round.py:473-481` — round admission callback.
- `tests/steps/test_check_repeat.py:228-239` — repeat admission caller.
- `tests/steps/round_bench.py:305-309` — no-required-check fake.
- `src/taskloop/admit.py:49-78` — refusal vocabulary and result declaration.

## Contract
Intent: request another checks attempt. Effect: existing candidate fences refuse it before writes. Result: unchanged `AdmitRefused` reasons, with prose in `detail`. No typed names, states, stored fields or effect boundaries change.

## Work packages
1. Edit `LAND_GUIDE` in `check_admit.py` and its regression in `test_check_admit.py`; close A1. Assert each branch's distinct meaning, no command syntax, the same refusal reason and no stored-state change; retain withdrawal allowing admission. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, last.

## Acceptance behaviours
A1. Delivered and outstanding land candidates block checks with prose describing their situation and closure or completion/withdrawal decision, without CLI commands; withdrawal still permits checks admission and refusals leave stored state intact.
