# Header
tl-8bh9.14.174.1 @ 145b2b682718090cfe1b34888d5d70a1bbcb48f6
Depth: medium; digest and persistence
Owner decision: none missing. Unlanded dependency: none.
Evidence budget: 12 model calls.
Size: 17 changed files including tests/plan; 2 behaviours; 55 implement model calls.

## Outcome and non-goals
Give each newly admitted plan attempt durable evidence of the task content it received. Keep the existing discussion framing, hold annotations and full-input file digest; neither is a substitute for content evidence. Structured discussion collection and immutable admitted input already exist; content canonicalization and database persistence are the gaps.
Exclude Git plan validation, skip-rerun decisions, admission routing and resume selection: those belong to the later split tasks. No shelf API change is needed here.

## Settled decisions
- Use the same task/discussion reads for input and digest.
- Include title, requirements, acceptance, source identities/titles/relationships and retained comment author/time/text.
- Exclude generated hold notifications and local hold metadata from hashing; retain them in the prompt.
- Normalize CRLF/CR to LF; preserve other whitespace/Unicode. Sort sources and relationship sets; preserve comment order/duplicates.
- One SHA-256 codec: canonical UTF-8 JSON, sorted keys, fixed separators, no ASCII escaping.
- Persist immutable evidence atomically with each plan admission, including repeats.
- Bump schema 28 to 29, append the DDL pin; use the existing drained-upgrade lifecycle.

## Open decisions
- None.

## Change map
- `src/taskloop/task_content.py` (new): `TaskContent`, `TaskContentDigest`, `digest`; codec called by discussion collection.
- `src/taskloop/task_content_store.py` (new): `TaskContentStore`; insert/read evidence through admission rows.
- `src/taskloop/discussion.py`: `DiscussionComment`, `DiscussionSnapshot`, collector aliases, `collect`, `for_task`, `empty`; return text plus digest.
- `src/taskloop/tracker_discussion.py`: `read_discussion`; classify generated notifications.
- `src/taskloop/admit.py`: `admit`, `_Prepared`, `_commit`, `task_text`; carry evidence and consume snapshot text.
- `src/taskloop/admit_rows.py`: `insert_attempt`; delegate evidence writes inside admission transaction.
- `src/taskloop/admit_chain.py`: `RepeatRequest`, `_takeover_open`, `admit_next`; carry repeat evidence, adapt advance caller.
- `src/taskloop/repeat.py`: `_input`, `repeat`; pass fresh evidence with feedback.
- `src/taskloop/check_repeat/repair.py`: `repair`; adapt implement-only refresh caller.
- `src/taskloop/factory_schema.py`: `SCHEMA`, validation; table, constraints, version and required-table list.
- `src/taskloop/tracker_client.py`: `tracker_discussion` (consult); source producer/actor binding.
- `src/taskloop/composition.py`: `open_discussion`, admission/repeat wiring (consult).
- `src/taskloop/check_repeat/store.py`: `CheckRepeatStore` (consult); implement-only insertion caller.
- `tests/steps/test_task_content.py` (new): canonicalization/filtering cases.
- `tests/steps/test_task_content_store.py` (new): durable reads, validation, rollback.
- `tests/steps/test_discussion.py`: snapshot/admission/advance/repeat assertions.
- `tests/steps/test_admit.py`: failure atomicity fixtures/assertions.
- `tests/steps/test_repeat.py`: request fixtures and repeat evidence assertions.
- `tests/steps/test_factory_schema.py`: DDL pin, constraints, required-table assertions.
- `docs/design/tl-8bh9.14.174.1/plan.md`: bounded implementation contract.

## Read list
- `src/taskloop/task.py:14-61` — task identity and content inputs.
- `src/taskloop/discussion.py:1-105` — typed source collection, limits and rendering.
- `src/taskloop/tracker_discussion.py:1-32` — source/comment producer and direct-link scope.
- `src/taskloop/tracker.py:71-89` — task requirements and acceptance producer.
- `src/taskloop/tracker.py:152-157` — authoritative comment order.
- `src/taskloop/tracker_client.py:35-44` — native task/discussion adapter.
- `src/taskloop/hold_text.py:105-128` — generated hold notification marker.
- `src/taskloop/admit.py:113-178` — input assembly and collector caller.
- `src/taskloop/admit.py:267-326` — admission transaction and row writer.
- `src/taskloop/admit_rows.py:1-34` — shared attempt insertion boundary.
- `src/taskloop/admit_chain.py:65-170` — repeat request and takeover insertion.
- `src/taskloop/admit_chain.py:215-265` — advance collection caller.
- `src/taskloop/admit_chain.py:323-372` — advance admission writer.
- `src/taskloop/repeat.py:75-98` — repeat request producer.
- `src/taskloop/repeat.py:115-146` — discussion refresh and input feedback.
- `src/taskloop/check_repeat/repair.py:35-72` — refresh caller for failed checks.
- `src/taskloop/check_repeat/store.py:90-118` — implement-only row producer.
- `src/taskloop/composition.py:225-280` — collector and admission integration points.
- `src/taskloop/factory_schema.py:45-55` — schema version contract.
- `src/taskloop/factory_schema.py:320-386` — current-schema validation integration.
- `tests/steps/test_discussion.py:130-231` — semantic admission and repeat fixtures.
- `tests/steps/test_admit.py:1-120` — admission fixtures and refusal assertions.
- `tests/steps/test_repeat.py:1-120` — repeat fixtures and request callers.
- `tests/steps/test_factory_schema.py:1-90` — DDL pin and read-only schema checks.

## Contract
Intent: frozen pydantic v2 `TaskContent` holds normalized content; `TaskContentDigest` validates lowercase 64-character SHA-256. `DiscussionSnapshot` carries text plus digest, computed before rendering.

At the tracker edge, mark generated only comments by the configured factory actor starting with the exact hold-notification marker. Preserve all other comments, including unknown timestamps and owner quotations. Hash neither classification flags nor generated comments. Exclude hold annotations, status, assignee, labels, settings, Git state and factory guidance.

Effect: add `task_content(attempt_id PRIMARY KEY REFERENCES attempt, digest TEXT NOT NULL)` with digest validation. Its store owns SQL. Insert once within attempt/reservation admission; rollback removes both. Reject overwrite. Typed reads return saved evidence or explicit absence, never reconstruction.

Result: initial/repeated plan admissions require fresh evidence; implement advances/repairs consume text only. Refuse a plan repeat without a structured collector. Explicit empty discussion still hashes the supplied task. Collection/encoding failure refuses before claim/insertion. Reopened reads preserve evidence despite later tracker edits. No scheduling change.

## Work packages
1. Add `task_content.py`; update discussion/adapter and all mapped text consumers. Add canonicalization/discussion tests. Closes A1.
2. Add `task_content_store.py` and schema/pin; thread evidence through admission rows and repeat requests. Add store/admission/repeat tests. Closes A2.
3. Check caller integration/caps. Run focused affected tests as needed; finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each with pipeline failure propagation.

## Acceptance behaviours
A1. Equal normalized task content and filtered discussion yield the same digest across source/relationship ordering and line-ending variations; changes to requirements, acceptance, title or retained own/linked comments change it. Generated hold notifications and local hold metadata do not change it; owner prose quoting notifications does.
A2. Initial and repeated plan admissions persist their own collected digest atomically with the attempt; reopen returns it unchanged after tracker edits, failed admission leaves no evidence row, invalid/overwriting writes fail, and implement advances/check repairs preserve their existing discussion input without manufacturing plan evidence.
