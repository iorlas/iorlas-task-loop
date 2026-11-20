# Depth
Small: one dashboard presentation behaviour labels factory faults and shows their explanations distinctly from agent asks. No owner decision is missing; the previous-part dependency is not explicitly unlanded. Evidence budget: 6 model calls total. Bounded inspection confirms the previous part landed in source commit a9bdeff4a8e15e24581134379df40a0147f6398a.

## Size
Estimated changed files: 9 including this plan, Python read-model/producer files, JavaScript rendering files and tests. One independent behaviour: factory-fault presentation. Independently testable acceptance: mixed fault/agent-ask fixtures show `Factory problem: ...` and a nonempty fault explanation, while agent asks retain their question and owner-attention treatment. Estimate for one implement attempt: 45 model calls, including focused verification and required gates. No schema upgrade or generated artifact is needed.

## Intent
The existing board gives current agent asks a `Needs you` callout with their question, but other holds get only `Held` and a cause code translated by the browser where known. The drawer also renders a generic hold callout. Present factory holds with `Factory problem: <readable cause>` and the owning explanation in both places. Preserve the existing ask classification, ordering, count and question handling from tl-8bh9.14.152.1.

Use the supplied meanings of task, plan, step, attempt, session, slot, land, ask, factory and worktree. This is display work within the dashboard; it introduces no glossary term, workflow transition or new state owner. Health freshness and stopped-round land-card messaging belong to later parts. If rounds state becomes necessary, use only the owning rounds.log reader; this change needs no additional rounds read.

## Read list
- `src/taskloop/dash_model.py:24-49` — Card payload and Board integration; append an optional explanation without breaking existing constructors.
- `src/taskloop/dash_board.py:1-34` — Imports and existing column classification.
- `src/taskloop/dash_board.py:83-114` — Current ask discriminator and shared card producer, including stop precedence.
- `src/taskloop/hold_cause.py:53-101` — Owning Cause model and structured reason explanations.
- `src/taskloop/hold_cause.py:106-151` — Land/owner causes and the public explanation lookup with fallback behaviour.
- `src/taskloop/task_status.py:101-135` — Status ownership and held-task precedence; consult rather than duplicate it.
- `src/taskloop/task_status.py:137-162` — Existing status prose is generic hold wording, not a detailed explanation.
- `src/taskloop/dash_task.py:271-291` — Task detail calls the same card producer as the board.
- `src/taskloop/dash_server.py:118-130` — Card comparison and event serialization propagate added presentation fields.
- `src/taskloop/dash_server.py:154-160` — Dataclass serialization for snapshot/detail responses.
- `src/taskloop/dash/static/words.js:5-68` — Existing readable cause codec and raw-code fallback.
- `src/taskloop/dash/static/ui.js:1-70` — Existing text-safe element/callout primitives and shared rendering integration point.
- `src/taskloop/dash/static/app.js:18-21` — Existing ask predicate.
- `src/taskloop/dash/static/app.js:57-91` — Board hold/ask callout rendering.
- `src/taskloop/dash/static/app.js:100-145` — Board rerendering, ask priority and count integration.
- `src/taskloop/dash/static/drawer.js:5-38` — Imports, detail loading and change signature integration.
- `src/taskloop/dash/static/drawer.js:163-195` — Drawer hold callout consumer.
- `src/taskloop/dash/static/drawer.js:284-300` — Refresh behaviour when presentation data changes.
- `tests/steps/test_dash_read.py:1-153` — Existing semantic fixtures for questions, factory holds, stale evidence and stop precedence.
- `tests/cli/test_dash_server.py:182-191` — Snapshot and question-only stream contract test to extend for explanations.
- `tests/dash/owner-attention.html:1-25` — Browser fixture page and DOM integration points.
- `tests/dash/owner-attention.test.js:1-88` — Mixed-card fixture and board update/layout assertions to extend.
- `tests/cli/test_dash_words.py:10-52` — Existing wording contracts to consult when reusing the cause codec.

## Change map
- `src/taskloop/dash_model.py`, `Card`: append an optional `hold_explanation` field, preserving existing positional constructors. It is presentation data derived from existing owning reads, not new durable state or a new outcome vocabulary.
- `src/taskloop/dash_board.py`, `card_of`: populate the explanation for a current non-ask hold through the existing `hold_cause.cause` lookup. Pass existing deadline/stop/return-code facts where applicable, retaining stop-specific explanation precedence. Use only the cause prose, not its repair instructions. For an unknown cause, provide explicit generic explanatory text retaining the recorded cause; never reuse a stale agent question as the explanation. Keep `_ask` as the authority for whether a card is an agent ask. No log parsing or additional evidence/state reader.
- `src/taskloop/dash/static/ui.js`: add a small shared hold-callout renderer using existing callout/element primitives and the words codec. Current agent asks use `Needs you` and their question, including the existing unavailable-question explanation. Other current holds use `Factory problem: <readable cause>` plus `hold_explanation`; absent explanation data has an explicit fallback retaining the cause. Keep raw codes available as hover text. Render explanation/question text with textContent, preserving line breaks safely.
- `src/taskloop/dash/static/app.js`, `fillCard`: consume the shared renderer in place of the existing ask/hold branches. Preserve ask-first ordering, counts and non-held card presentation.
- `src/taskloop/dash/static/drawer.js`: consume the same renderer for held-task notices and include the explanation in its change signature so explanation-only updates refresh an open drawer. A current agent ask must never receive the factory-problem label.
- `tests/steps/test_dash_read.py`: extend existing factory-hold fixtures to assert a nonempty owning explanation on both board and detail, with ask/question fields false/empty; retain checks, stopped attempts, missing evidence and stale-question coverage. Cover unknown causes without requiring a new cause vocabulary.
- `tests/cli/test_dash_server.py`: extend the existing snapshot/event test to prove explanations survive JSON serialization and explanation-only changes produce task events.
- `tests/dash/owner-attention.test.js`: extend the existing browser fixture for mixed asks and faults, board and drawer labels, visible explanations, escaped HTML-shaped multiline text, and explanation-only updates. Preserve existing count/priority/layout tests. Reuse its existing HTML integration page; no new file or dependency is planned.

## Verification
Use focused pytest function tests for the changed read and serialization contracts, then run the existing browser fixture with its documented browser harness and verify its reported assertions, including both board layouts and the open drawer. Do not substitute source-text assertions for rendered wording. Do not add a browser package merely for this task; if the implement environment cannot execute the fixture, report that specific validation gap.

Run `just check` and `just test` as the supplied required gates. Do not invoke whole-suite/live tests beyond those prescribed focused gates or read the justfile for this attempt. If runtime inspection is needed, use the installed successor environment and the prescribed isolated invocation after `just install`; no baseline imports or PYTHONPATH workaround.

Completion requires the one acceptance criterion in Size, successful required gates, and no changed control state, schema, tracker data or rounds-state path. Keep source files within 400 lines, functions within 80 and test files within 800; extract only the small shared renderer needed by the two consumers. This plan is the only new file; implementation edits the existing integration points above.
