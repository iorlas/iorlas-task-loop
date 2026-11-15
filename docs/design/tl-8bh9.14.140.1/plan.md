# Header
Task: tl-8bh9.14.140.1; base: ca861999263bd031d4f59007c60cdcf726a50fea
Depth: medium; three owning modules.
Decisions: settled; no explicitly unlanded dependency.
Evidence budget: 12 model calls.
Size: ~20 changed files, 3 independent behaviours, ~90 implement calls.

## Outcome and non-goals
Show measured factory work beside attempts. Existing history supplies verification, land events and approximate gaps, but no operation measurements. Numbering (.159-B), check links (.147-B), land events (.146.2), and parent closure remain separate. Supplied overlap establishes no additional prerequisite.

## Settled decisions
- TaskDetail/build_task owns history; dash_board owns board cards.
- EvidenceFiles owns display artifacts; no database schema change.
- Inject monotonic elapsed measurements; wall timestamps locate observations.
- Check-start covers admitted checks-entry launch through its registration/result, including replacements; excludes admission and check commands.
- Cached results add no work rows; actual retries retain separate observations.

## Open decisions
- None.

## Change map
- `src/taskloop/factory_work.py` (new): observations, observer and bounded codec; integrates EvidenceFiles and producers below.
- `src/taskloop/evidence_files.py`: read/write work under directory(key), including checks keys.
- `src/taskloop/verifier.py`: _settle observes settlement when end_commit is absent.
- `src/taskloop/factory_commit.py`: consult settle/Committed, keep and adoption outcomes.
- `src/taskloop/publish.py`: BranchPublish.publish observes actual publication.
- `src/taskloop/launch.py`: Launcher.launch observes actual checks-entry starts.
- `src/taskloop/composition.py`: open_verifier/open_publisher/open_checks_launcher wire observers.
- `src/taskloop/attempt_entry.py`: _verify and BranchPublish construction wire observers.
- `src/taskloop/cli_composition.py`: update open_next/open_verify/open_publish and read-only Verifier callers.
- `src/taskloop/operations.py`: consult _start/_admit/relaunch_checks and publisher callers.
- `src/taskloop/dash_model.py`: TaskDetail gains separate typed work rows.
- `src/taskloop/dash_task.py`: build_task projects evidence into chain/history order.
- `src/taskloop/dash_board.py`: consult card_of/duration_of; no history ownership change.
- `src/taskloop/dash_composition.py`: consult sole build_task integration.
- `src/taskloop/dash/static/drawer.js`: render passes work rows to rail.
- `src/taskloop/dash/static/rail.js`: project/groupRows add operation rows and folded history.
- `tests/dash/test_factory_work.py` (new): producer/read contracts through existing pytest discovery.
- `tests/dash/factory-work.test.js` (new): rail contracts through factory-work.html.
- `tests/dash/factory-work.html` (new): browser fixture following rail.html.
- `tests/dash/rail.test.js`: adjust affected assertions within its file cap.

## Read list
- `src/taskloop/factory_commit.py:44-145` — settlement result and commit/keep/adoption boundaries.
- `src/taskloop/verifier.py:68-110` — constructor, fencing and error handling.
- `src/taskloop/verifier.py:168-195` — settle invocation and verdict persistence.
- `src/taskloop/publish.py:94-145` — publisher dependencies, operation boundary and existing publication path.
- `src/taskloop/launch.py:69-165` — target protocol, launch outcomes and checked target selection.
- `src/taskloop/evidence_files.py:105-143` — owning artifact directory and duration integration pattern.
- `src/taskloop/duration_file.py:1-42` — bounded snapshot validation and atomic-file integration precedent.
- `tests/dash/rail.html:1-14` — integration pattern for the new browser fixture.
- `src/taskloop/dash_duration.py:11-51` — saved duration projection; do not conflate agent elapsed time with work time.
- `src/taskloop/attempt_reads.py:35-77` — attempt/publication identity and chain facts.
- `src/taskloop/composition.py:196-237` — production verifier, publisher and launcher construction.
- `src/taskloop/attempt_entry.py:225-240` — entry verification caller.
- `src/taskloop/attempt_entry.py:300-316` — entry publication caller.
- `src/taskloop/cli_composition.py:115-193` — read-only verification and round composition callers.
- `src/taskloop/cli_composition.py:319-345` — explicit verify/publication composition callers.
- `src/taskloop/operations.py:326-375` — start/advance checks launcher caller.
- `src/taskloop/operations.py:440-495` — checks relaunch and admission boundaries.
- `src/taskloop/dash_model.py:194-246` — AttemptDetail and TaskDetail payload ownership.
- `src/taskloop/dash_task.py:321-349` — task chain, checks, historical membership and TaskDetail construction.
- `src/taskloop/dash_board.py:105-148` — card and agent duration projection.
- `src/taskloop/dash_composition.py:35-51` — task-detail composition integration.
- `src/taskloop/dash/static/drawer.js:211-231` — sole rail consumer and attempt selection.
- `src/taskloop/dash/static/rail.js:36-60` — chain projection and verification attachment.
- `src/taskloop/dash/static/rail.js:112-285` — rows, groups, history and land integration.
- `tests/dash/rail.test.js:1-90` — fixtures and navigation expectations.

## Contract
Add a work-kind enum (commit, publish, start checks), one codec, and a validated observation model: operation identity, owning AttemptKey identity, kind, sequence, start/end wall timestamps, nonnegative measured elapsed milliseconds, and typed completion state. Retries have distinct identities without incrementing attempt numbers. EvidenceFiles stores bounded, atomically replaced, identity-validated artifacts. Timing alone never proves success.

Intent: an owner performs work. Effect: an injected observer records start/terminal evidence around the existing operation outside write transactions. Result: operation results, fencing and reconciliation retain their semantics despite evidence failure. Incomplete evidence stays incomplete after restart; actual retries get new identities. No recovery actions or control state come from artifacts.

Intent: read task detail. Effect: load observations for agent/check keys and join them to related attempts and historical groups. Result: separate TaskDetail work rows with measured duration or explicit unknown/incomplete wording. Started-only evidence cannot imply continuing liveness after restart. Preserve valid siblings when an artifact is corrupt. Tasks without evidence retain their history; elapsed gaps never become operation measurements.

## Work packages
1. Add factory_work.py/EvidenceFiles; wire verifier, publisher, launcher, composition and entry callers. Add tests/dash/test_factory_work.py contracts for each producer and evidence failures. Closes A1–A3 measurement boundaries.
2. Extend dash_model/dash_task, drawer and rail; place commit/publication after their agent and check-start before checks execution, including folded history. Add factory-work browser fixtures and adjust rail assertions. Closes A1–A3 presentation.
3. After installation, run the permitted focused pytest command for the new Python file; exercise factory-work.html and rail.html without live services. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last, preserving gate exit statuses.

## Acceptance behaviours
A1. Commit settlement appears after its agent with measured duration; adopted/kept work is identified truthfully, cached verdicts add no duplicate, and interrupted/missing timing stays incomplete/unknown.
A2. Publication appears after its agent/commit with measured duration and separate retries; cached publication adds no row and evidence failure cannot change publication results.
A3. Checks-entry start/replacement appears before its checks execution with measured duration; already-running adds no row. All kinds preserve order, folded history, attempt routes, verification links, check lines and land events.
