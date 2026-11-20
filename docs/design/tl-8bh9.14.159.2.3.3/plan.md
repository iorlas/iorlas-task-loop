# Header
Task: tl-8bh9.14.159.2.3.3
Base: f3ac438680def33dab3ef3bcfc905703bdf36d88
Depth: medium; help, guidance, docs.
Decision/dependency: none missing/unlanded.
Evidence budget: 12 model calls.
Size: 48 changed files; 3 behaviours; 75 implement model calls.

## Outcome and non-goals
Align help, guidance and current docs. Result encodings are delivered. Preserve eligibility, evidence, operation ordering and release/publication decisions. Exclude dashboard models, historical material and ordinary identity/tool validation wording.

## Settled decisions
- Use the glossary factory commit entry and naming map's fixed names and exclusions.
- Keep the existing `tl step commit` command, without aliases.

## Open decisions
- None.

## Change map
- src/taskloop/cli_step.py:commit parser; revise help.
- src/taskloop/step_guide.py:GUIDE, PUBLISH; rename action key and factory commit prose, including rule explanations.
- src/taskloop/step_refusal_guide.py:REFUSALS; rename completion prose.
- src/taskloop/round_guide.py:automatic_guide; rename action key and pending/publication prose.
- src/taskloop/attempt_status.py:Next, _stopped, view; emit `commit` and retain the matching leftovers probe.
- src/taskloop/round.py:_move, _committed; consume `commit` and emit it for every completion result.
- src/taskloop/operations.py:Action; mapped action name and operation descriptions only.
- src/taskloop/task_status.py:SETTLING; recognize the renamed action.
- src/taskloop/slot_lock.py:Role, custody; rename the completion lock role and description.
- src/taskloop/attempt_entry.py:shown, _step; rename the completion log label and its descriptions.
- src/taskloop/evidence_files.py:ENTRY_WORDS; align the log-label comment.
- src/taskloop/cli.py:main; consult parser integration.
- src/taskloop/step_render.py:human, _guides, _rows_lines; consult status/round/refusal rendering.
- src/taskloop/hold_guide.py:pending_guide; consult forwarding.
- src/taskloop/land_render.py:failed_lines; consult forwarding.
- README.md:command overview; replace the obsolete command spelling.
- docs/glossary.md:Factory commit, settle, advance; reconcile current result/action wording with committed and commit.
- tests/cli/test_cli.py:help; assert new wording and no alias.
- tests/cli/test_step_cli.py:Shown fixtures, status/round assertions; expect commit and the revised prose.
- tests/cli/test_answer_repair_cli.py:next_words assertion; expect commit after collection.
- tests/cli/test_refusal_guidance.py:assert forwarded completion explanations.
- tests/cli/test_check_cli.py:CHECKS_GUIDE assertions; consult identity-language preservation.
- tests/cli/test_land_cli.py:GUIDE consumer; consult land override preservation.
- tests/steps/test_step_message_words.py:assert renamed guidance and remedies.
- tests/steps/test_guide_words.py:automatic/hold forwarding; consult prose constraints.
- tests/steps/test_hold.py:action fixtures; mapped rename.
- tests/steps/test_killed_rounds.py:action expectations; mapped rename.
- tests/steps/test_advance.py:action expectations; mapped rename.
- tests/steps/test_round_holds.py:action fixtures; mapped rename.
- tests/steps/test_operations.py:action and completion wording; mapped rename.
- tests/steps/test_repeat_dispatch.py:entry label expectations; mapped rename.
- tests/steps/test_attempt_entry.py:entry label expectations; mapped rename.
- tests/steps/test_resume_plan.py:action expectations; mapped rename.
- tests/steps/test_pending_commit.py:next action expectations; mapped rename.
- tests/steps/test_hold_status.py:action fixtures; mapped rename.
- tests/steps/test_checks_round.py:action expectations; mapped rename.
- tests/steps/killed_rounds_bench.py:completion action fixture; mapped rename.
- tests/steps/test_prepare_main.py:action expectations; mapped rename.
- tests/steps/test_check_repeat.py:action expectations; mapped rename.
- tests/steps/test_restart.py:action expectations; mapped rename.
- tests/steps/test_recovery_status.py:next action expectation; mapped rename.
- tests/steps/public_surface_fixtures.py:action fixture; mapped rename.
- tests/steps/test_answer_repair_routing.py:action expectation; mapped rename.
- tests/steps/test_hold_text.py:action fixture; mapped rename.
- tests/steps/test_slot_lock.py:role fixture; mapped rename.
- tests/steps/test_publish.py:entry label assertion; mapped rename.
- tests/steps/test_round_reader.py:action fixtures; mapped rename.
- tests/steps/test_task_status.py:settling action fixture; mapped rename.
- docs/design/tl-8bh9.14.159.2.3.3/plan.md:implementation acceptance record.
- docs/design/tl-8bh9.14.159.2.3.3/plan-metadata.json:prepared commit and consulted paths.

## Read list
- docs/design/tl-8bh9.14.159.1/naming-map.md:18-85 — names and one-target rows.
- docs/glossary.md:145-199 — factory commit and current action descriptions.
- README.md:30-40 — implemented command overview.
- src/taskloop/cli_step.py:73-95 — completion parser help.
- src/taskloop/step_guide.py:10-118 — shared publication and action guidance.
- src/taskloop/step_guide.py:179-231 — rule explanations and guide lookup.
- src/taskloop/step_refusal_guide.py:1-123 — completion refusals.
- src/taskloop/round_guide.py:1-85 — automatic guidance routing.
- src/taskloop/attempt_status.py:140-155 — action production.
- src/taskloop/attempt_status.py:216-228 — leftovers probe guard.
- src/taskloop/round.py:245-260 — completion dispatch.
- src/taskloop/round.py:347-359 — completion result actions.
- src/taskloop/operations.py:238-238 — shared action type.
- src/taskloop/cli.py:115-155 — parser integration.
- src/taskloop/step_render.py:44-164 — shared guidance consumers.
- src/taskloop/hold_guide.py:42-78 — automatic guidance caller.
- src/taskloop/land_render.py:46-75 — refusal guide caller.
- tests/cli/test_cli.py:13-49 — help coverage integration.
- tests/cli/test_step_cli.py:166-262 — rendered action/refusal assertions.
- tests/cli/test_refusal_guidance.py:23-89 — public reason forwarding.
- tests/cli/test_check_cli.py:160-175 — retained identity explanation.
- tests/cli/test_land_cli.py:1-40 — shared GUIDE integration.
- tests/steps/test_step_message_words.py:16-57 — prose/remedy assertions.
- tests/steps/test_guide_words.py:13-46 — automatic and hold integration.

Exemptions: naming-map rows `Next: verify`/action `verify`, task status action, lock role, `verify=` and “verified result/commit/plan”, including fixtures/comments. Guards remain listed above. Required empty search: `rg -nw 'verify|verification' src/taskloop/{attempt_status,task_status,operations,slot_lock,round,attempt_entry,evidence_files}.py`.

## Contract
Intent: complete the captured answer. Effect: status emits `commit`, round consumes it; custody and verdict/release/publication ordering persist. Result: action/log labels change; committed, reused, pending:commit, rejected and not_committed retain their meanings. No schema or policy changes; checks/land guide overrides persist.

## Work packages
1. cli_step and CLI help assertions: A1.
2. Listed producers, guides and fixtures: A2; cover pending completion, refusal and publication.
3. README/glossary: A3. Run focused CLI/guidance tests using the approved isolated pytest invocation, then `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last; retain actual exit statuses.

## Acceptance behaviours
A1: Help names factory commit and its judgment/release/publication sequence; no obsolete command alias.
A2: Next: commit and round dispatch preserve completion decisions; refusal/publication remedies persist; entry uses commit=.
A3: Current docs use commit/committed, distinguishing verdict, reuse, rejection and publication.
`rg -nw 'verify|verification'` finds no old operation wording in help, guidance values or current docs passages, applying the map's exclusions.
The Read list mapped-source search returns no matches.
