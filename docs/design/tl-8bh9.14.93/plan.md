# Header
Task: tl-8bh9.14.93
Base: 639692cb4c8d2f6a7c58147299df197d0c869536
Depth: small; one admission effect-boundary invariant.+Owner decision missing: none. Dependency unlanded: none stated.
Evidence budget: 6 model calls.
Size: 6 changed files; 1 behaviour (A1); 45 implement model calls.

## Outcome and non-goals
Record the audit and guard effect boundaries. Admission already has database-only rechecks and drain claim intent; audit evidence and broader tests remain. Exclude SQL extraction, layout and schema changes.

## Settled decisions
- Cover fresh, repeat, advance and checks admission as paths of the same invariant.
- Keep existing database rechecks and atomic reservation/attempt writes.
- Reuse claim intent and reconciliation.
- Treat `ResumePlans.unchanged` as a database recheck; Git selection belongs before the write transaction.

## Open decisions
- None.

## Change map
- `docs/design/tl-8bh9.14.93/plan.md`: retain implementation contract.
- `docs/design/tl-8bh9.14.93/plan-metadata.json`: retain inputs.
- `docs/design/tl-8bh9.14.93/audit.md` (new): record transactions, indirect calls and findings; integrate `composition.py` constructors and `Launcher.launch`.
- `tests/steps/test_admit.py`: extend `Tracker` and Git doubles with transaction guards, including plan reuse and refusals.
- `tests/steps/test_admit_chain.py`: guard `advancing` and repeat Git/tracker doubles; retain race assertions.
- `tests/steps/test_check_admit.py`: guard Git/profile/tracker reads, including its `NextAdmission` producer.
- `src/taskloop/admit.py`: audit `AttemptAdmission._commit`.
- `src/taskloop/admit_chain.py`: audit `ChainAdmission._takeover`, `NextAdmission._advance`.
- `src/taskloop/check_admit.py`: audit `ChecksAdmission._commit`.
- `src/taskloop/resume_plan.py`: audit `ResumePlans.unchanged`.
- `src/taskloop/composition.py`: consult `open_admission`, `open_chain`, `open_advance`, `open_checks_admission` callers; no runtime edits identified.

## Read list
- `src/taskloop/admit.py:121-336` — preparation, claim and commit.
- `src/taskloop/admit_chain.py:71-340` — repeat and advance boundaries.
- `src/taskloop/check_admit.py:114-236` — checks preparation and commit.
- `src/taskloop/admit_store.py:1-144` — reservation and insertion ownership.
- `src/taskloop/resume_plan.py:31-64` — database recheck versus Git selection.
- `src/taskloop/drain/store.py:55-132` — claim intent and completion.
- `src/taskloop/drain/reconcile.py:1-35` — unfinished claim observation.
- `src/taskloop/launch.py:150-268` — launch authorization and external start.
- `src/taskloop/claim_lease.py:1-100` — tracker effect boundary.
- `src/taskloop/composition.py:256-308` — all four runtime constructors.
- `tests/steps/test_admit.py:55-170` — claim guard and admission helper.
- `tests/steps/test_admit_chain.py:90-115` — advance producer.
- `tests/steps/test_admit_chain.py:210-365` — race and repeat callers.
- `tests/steps/test_check_admit.py:1-235` — checks fixtures and advance caller.

## Contract
No new typed names, states or fields. Intent: existing claim authorization commits before mutation. Effect: Git/profile/discussion/tracker calls and process start run outside write transactions. Result: database rechecks, reservation and attempt recording remain atomic; drain completion or uncertainty is recorded separately. Audit indirect calls. External test ports reject active write transactions.

## Work packages
1. Trace admissions and launch; record findings in `audit.md` (A1).
2. Guard ports in the three test files; cover success, refusal and races (A1). Finish with `just check 2>&1 | tail -60`, then `just test 2>&1 | tail -40`, once each.

## Acceptance behaviours
A1. Admissions perform Git, tracker and spawn effects outside write transactions, preserving race refusals and atomic reservation/attempt recording; the audit identifies boundaries and their checks.
