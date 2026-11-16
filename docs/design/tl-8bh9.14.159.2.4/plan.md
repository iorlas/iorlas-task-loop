# Header
Task: tl-8bh9.14.159.2.4
Base: e6f71f91747301d2b4b7037f6540a41fedc7cacc
Depth: small; one dashboard terminology behaviour.
Decision: none missing; no explicitly unlanded dependency.
Evidence: 6 calls.
Size: 21 files including tests/artifacts; 1 behaviour; 35 implement calls.

## Outcome and non-goals
Align dashboard fields, selectors and labels. Backend commit, storage and verdict names are delivered. Exclude other application code, schema and historical pages.

## Settled decisions
- Apply tl-8bh9.14.159.1/naming-map.md dashboard rows without aliases.
- Keep factory commit attached to its owning agent attempt.

## Open decisions
- None.

## Change map
- src/taskloop/dash_verify.py: rename to dash_commit.py; verification -> factory_commit.
- src/taskloop/dash_model.py: FactoryCommit, CommitCheck, Outcome.factory_commit.
- src/taskloop/dash_task.py: COMMIT, _factory_commit, Link.commits; _chain, _history, history, build_body callers.
- src/taskloop/dash/static/ui.js: COMMIT selector and label.
- src/taskloop/dash/static/rail.js: commitTitle, commitButton, factoryCommit attachment and wording.
- src/taskloop/dash/static/drawer.js: COMMIT, commitTitle callers and pane selection.
- src/taskloop/dash/static/navigation.js: selector and Result routing.
- src/taskloop/dash/static/result.js: factoryCommit and body.result.factory_commit.
- src/taskloop/dash/static/words.js: comment.
- tests/steps/test_dash_read.py: build_body callers and assertions.
- tests/steps/test_dash_usage.py: selector fixtures.
- tests/steps/test_dash_operations.py: terminology.
- tests/cli/test_dash_words.py: CHECKS import and terminology.
- tests/dash/test_accessibility_markup.py: assertions.
- tests/dash/operation-rail.test.js: fixtures.
- tests/dash/navigation-codec.test.js: fixtures.
- tests/dash/navigation.test.js: routes and labels.
- tests/dash/rail.test.js: commitTitle caller, marks and repeat links.
- New plan.md and plan-metadata.json: delivery artifacts.

## Read list
- docs/glossary.md:145-171 - meaning.
- docs/design/tl-8bh9.14.159.1/naming-map.md:110-146 - names.
- src/taskloop/dash_verify.py:1-58 - producer.
- src/taskloop/dash_model.py:98-126 - signatures.
- src/taskloop/dash_task.py:228-329 - attachment and dispatch.
- src/taskloop/dash/static/ui.js:18-20 - selector.
- src/taskloop/dash/static/rail.js:18-307 - attachment, marks, selection.
- src/taskloop/dash/static/drawer.js:110-356 - streaming, counts, panes.
- src/taskloop/dash/static/navigation.js:24-53 - routes.
- src/taskloop/dash/static/result.js:89-120 - body consumer.
- tests/steps/test_dash_read.py:738-787 - projections.
- tests/dash/rail.test.js:420-442 - title.
- Other listed files need only single-target dashboard map substitutions: imports, fixtures, local names and prose. Rows dash_verify.py through verified wording apply; verificationButtons corresponds to singular verificationButton -> commitButton. No exemption for cause-dependent rows.

## Contract
Intent: project retained facts. Effect: select commit/N and serialize Outcome.factory_commit with FactoryCommit/CommitCheck. Result: identical checks, verdict, listings and owner numbers; no writes. Preserve led_by, past chains, operation timing and usage.

## Work packages
1. Rename projection and listed consumers/tests together; close A1.
2. Run affected dashboard tests; finish with just check 2>&1 | tail -60 and just test 2>&1 | tail -40 once each, last.

## Acceptance behaviours
A1: Factory commit titles, accessible marks, Result-only commit routes and bodies agree; success, pending, rejection, repeat links, timing and usage keep their meanings.
A1: rg -nwi 'verify|verification|verified|verifying|verifier|verifications' src/taskloop/dash* tests/dash tests/cli/test_dash* tests/steps/test_dash* tests/steps/test_discussion_dashboard.py returns no matches; mapped identifiers are renamed.
