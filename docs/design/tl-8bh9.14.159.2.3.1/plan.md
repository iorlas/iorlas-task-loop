# Header
Task: tl-8bh9.14.159.2.3.1; base: 9926ea96a57b2447ad73a4ccd4a4709fcc19dd54
Depth: medium
Reason: table, field, kind; names settled; no unlanded dependency.
Evidence budget: 12 calls.
Size: 35 changed files including artifacts; 3 independent behaviours; 70 implement calls.

## Outcome and non-goals
Make persisted factory-commit verdicts and their in-process projection agree with the naming map. Typed result families are already delivered. Leave displayed result/status words, dashboard projection names, pending reasons and publication refusal vocabulary to the sibling result-vocabulary task. No migration, fallback, schema bump or shelf change.

## Settled decisions
- Naming-map rows: table `verification` → `factory_commit`; `StoredExecution.verification` → `StoredExecution.verdict`; stored verdict kind `verified` → `committed`.
- The task explicitly keeps schema 32: replace its digest pin and adjust the pin-policy comment for this authorized change; retain the guard for subsequent DDL changes.
- Preserve stored rejection rules, optional artifact, reuse flag, attempt identity, dispatch token, generation and observation time.

## Open decisions
- None.

## Change map
- `src/taskloop/factory_schema.py`: DDL constraints, publication foreign key.
- `src/taskloop/attempt_types.py`: `StoredExecution.verdict` signature.
- `src/taskloop/attempt_reads.py`: `_verdict_values` encoder.
- `src/taskloop/attempt_loads.py`: `verdict_of`, `latest_plan`, `_execution` projection.
- `src/taskloop/attempt_store.py`: `_plan_row`, `_execution_row` joins.
- `src/taskloop/attempt_write_store.py`: `end_commit`, `verdict` SQL.
- `src/taskloop/admit_store.py`: eligibility SQL.
- `src/taskloop/publish_store.py`: `ROW`, `FENCE` SQL.
- `src/taskloop/publish.py`: `_refusal` raw-kind comparison.
- `src/taskloop/commit.py`: `applicable` field rename.
- `src/taskloop/attempt_result.py`: `_report` field rename.
- `src/taskloop/answer_repair_route.py`: eligibility field rename.
- `src/taskloop/answer_repair_store.py`: `admit` field rename.
- `src/taskloop/hold_event.py`: rejection field rename.
- `src/taskloop/dash_verify.py`: execution field rename.
- `src/taskloop/attempt.py`: consult `_resume`, `_refresh`.
- `src/taskloop/answer_read.py`: consult `read`.
- `src/taskloop/hold_facts.py`: consult `explanation`.
- `src/taskloop/repeat.py`: consult `_words`.
- `src/taskloop/attempt_entry.py`: consult `shown`.
- `src/taskloop/factory_store.py`: consult `_required_tables`.
- `tests/steps/test_factory_schema.py`: digest and constraints.
- `tests/steps/test_attempt_loads.py`: projection and eligibility.
- `tests/steps/test_verifier.py`: stored rows, fencing and reuse.
- `tests/steps/test_resume_plan.py`: three UPDATE targets.
- `tests/rules/test_policy.py`: SQL ownership entries.
- `tests/steps/test_publish.py`: DELETE target and eligibility.
- `tests/steps/test_attempt_answers.py`: field assertion.
- `tests/steps/test_hold_event.py`: replacement keyword.
- `tests/steps/conftest.py`: success INSERT.
- `tests/steps/land_bench.py`: success INSERT.
- `tests/steps/test_slot_lock.py`: count query.
- `tests/steps/test_conflict_recovery.py`: success INSERT.
- `tests/steps/test_check_admit.py`: rejection UPDATE.
- `tests/steps/test_repeat_dispatch.py`: queries and stored-kind assertion.
- `tests/steps/test_repeat.py`: rejection INSERT.
- `tests/steps/test_dash_read.py`: DELETE/INSERT only; retain dashboard fields.
- `tests/steps/test_answer_contract.py`: consult `stored` constructor.
- `tests/steps/test_answer_repair.py`: consult `lost` admission caller.
- `docs/design/tl-8bh9.14.159.2.3.1/plan.md`: new plan, new metadata beside it.

## Read list
- `docs/design/tl-8bh9.14.159.1/naming-map.md:20-84` — fixed field, table and storage-kind rows.
- `docs/glossary.md:145-171` — factory-commit completion boundary.
- `src/taskloop/factory_schema.py:158-174` — verdict constraints and publication foreign key.
- `src/taskloop/attempt_types.py:314-320` — stored field signature.
- `src/taskloop/attempt_reads.py:242-245` — verdict encoder.
- `src/taskloop/attempt_loads.py:76-135` — decoder and latest-plan selector; positional execution construction remains unchanged.
- `src/taskloop/attempt_store.py:47-107` — SQL join producers.
- `src/taskloop/attempt_write_store.py:249-296` — fenced writes and insert-only verdict.
- `src/taskloop/admit_store.py:16-32` — eligibility projections.
- `src/taskloop/publish_store.py:17-28` — raw-kind publication fence.
- `src/taskloop/publish.py:147-156` — raw-kind application guard.
- `src/taskloop/factory_store.py:49-56` — DDL-derived required tables.
- `src/taskloop/attempt.py:122-143` — resume and refresh consumers.
- `src/taskloop/answer_read.py:10-16` — stored-answer reader.
- `src/taskloop/hold_facts.py:71-78` — explanation consumer.
- `src/taskloop/repeat.py:60-61` — result-word caller.
- `src/taskloop/attempt_entry.py:145-152` — result-word caller.
- `tests/steps/test_answer_contract.py:180-183` — positional stored-execution producer.
- `tests/steps/test_answer_repair.py:106-117` — repair admission caller.
- `tests/steps/test_verifier.py:623-684` — existing fenced write and artifact-free reuse cases.
- `tests/steps/test_attempt_loads.py:93-122` — latest-plan fixture and stored projection.
- `tests/steps/test_factory_schema.py:14-36` — digest pin and DDL guard integration point.
- `tests/steps/test_resume_plan.py:124-180` — claim-time and restart evidence mutations.
- `tests/rules/test_policy.py:89-125` — SQL ownership entries.
- `tests/steps/test_publish.py:202-291` — success, reuse and refused-publication cases.

## Contract
Intent: retain one fenced judgment. Effect: rename storage and its codec; keep identity, answer, end-commit and transaction fences. Result: `Committed`, `Rejected` or absent `None` projects through `verdict`; saved judgments require no new Git effects.

Read-list exemptions use the naming-map rows for the stored field, table, kind and joins/guards/foreign key. Apply them only to stored values: display words and dashboard fields stay outside this task. The absence command checks storage references and codec/guard spellings.

## Work packages
1. Storage: schema, codecs, SQL stores/fixtures, publication guard, policy and digest. Close acceptance 1 and storage references in 3.
2. Projection: stored field, mapped consumers and keyword fixtures. Consult positional producers and word callers. Close acceptance 2 and field references in 3.
3. Contracts: extend schema/load/verdict/publication cases and preserve resume race refusals. Close all acceptance lines. After installation, run selected files with the permitted isolated pytest command; finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, using pipefail.

## Acceptance behaviours
1. At schema 32, `factory_commit` accepts valid committed/rejected verdicts and rejects invalid kind/reuse/reason combinations; publication references it, and stale or changed admissions cannot insert or publish.
2. Committed values, optional blobs, reused values, rejections and absent rows round-trip through `StoredExecution.verdict`; latest-plan selection and saved-verdict reads preserve eligibility and avoid new Git effects.
3. Old stored identifiers and codec/guard names are absent: `rg -nw -e '(FROM|JOIN|INTO|UPDATE|TABLE|REFERENCES) verification\b' -e '(execution|stored|collected|found)\.verification\b' -e 'verification: Verdict|verification=' -e 'verdict=.verified.' -e 'kind == .verified.' -e 'return .verified., None' -e 'row\.verdict == .verified.' -e 'row\[6\] != .verified.' src/taskloop tests/steps tests/cli tests/rules` returns no matches.
