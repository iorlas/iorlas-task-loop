# Header
tl-8bh9.14.159.2.5; base e99f39cf88e70f8bb40f2876325f2b17aa4bc963
Depth: small; one terminology behaviour, factory commit owner.
Missing decision: no; unlanded dependency: none stated.
Evidence: 6 model calls. Size: 51 files incl. artifacts; 1 behaviour; 45 implement calls.

## Outcome and non-goals
Operation/result/storage/dashboard renames are delivered. Finish prose/test names; preserve behaviour and ordinary verification.

## Settled decisions
- Apply .159.1 map's one-to-one rows and exclusions to prose and test identifiers.
- Test modules become test_commit.py and test_commit_leftovers.py.
- Retain the CLI alias rejection assertion and literal command.

## Open decisions
- None.

## Change map
- Source paths: src/taskloop/; prose only.
- factory_commit.py: settle, leftovers.
- attempt_result.py: judged, _report documentation.
- admit_chain.py: RepeatRequest.listing.
- attempt.py: module documentation.
- cli_composition.py: wiring docstrings.
- repeat.py: StepRepeat prose.
- exit_codes.py: result documentation.
- attempt_types.py: Admission.number, NotApplicable prose.
- factory_schema.py: repeat_listing prose.
- composition.py: open_factory_commit documentation.
- attempt_write_store.py: end_commit documentation.
- attempt_loads.py: latest_plan documentation.
- publish_store.py: publication fence documentation.
- Test paths: tests/steps/; mapped prose/identifier renames.
- test_verifier.py: module/test names.
- test_verifier_leftovers.py: module/import.
- test_plan_content.py: helper import.
- test_drain_fences.py: helper import.
- test_commit_paths.py: credential fixture path.
- test_resume_plan.py: prose; case label to verdict.
- test_operations.py: test identifiers and prose.
- test_repeat_dispatch.py: test identifiers and prose.
- test_attempt_entry.py: test identifiers and prose.
- test_slot_lock.py: test identifiers.
- test_hold_status.py: test identifiers and prose.
- test_repeat.py: test identifiers and prose.
- test_answer_repair.py: test identifier and feedback fixture.
- test_answer_repair_routing.py: test identifier.
- test_answer_contract.py: test identifier.
- test_publish.py: test identifier and prose.
- test_restart.py: test identifier.
- test_advance.py: prose.
- test_round_holds.py: prose.
- test_checks_round.py: prose.
- test_check_repeat.py: prose.
- test_check_operations.py: test identifier and prose.
- test_round_land.py: prose.
- test_merge_advance.py: prose.
- test_slot_release.py: prose.
- test_round.py: prose.
- test_rounds.py: prose.
- test_admit_chain.py: prose.
- conftest.py: fixture prose.
- refusal_inventory.py: producer description.
- real/test_prepare_real.py: prose.
- real/test_publish_real.py: prose.
- ../cli/test_cli.py: alias test name.
- ../cli/test_step_cli.py: test identifier.

## Read list
- docs/design/tl-8bh9.14.159.1/naming-map.md:15-190: mechanical rename rows and exclusions.
- tests/steps/test_verifier.py:1-24: producer.
- tests/steps/test_verifier_leftovers.py:1-12: importer.
- tests/steps/test_plan_content.py:1-15: importer.
- tests/steps/test_drain_fences.py:15-24: importer.
- tests/steps/test_commit_paths.py:144-157: fixture path.
- tests/steps/test_resume_plan.py:124-145: case label.
- tests/cli/test_cli.py:49-64: alias rejection.

## Contract
Intent: consistent names. Effect: text/test renames and four helper references above. Result: identical verdicts/effects; no schema change.

## Work packages
1. Apply mapped edits, imports, fixture path and paired case label. Closes A.
2. Run focused tests, then just check and just test once each, last. Closes A.

## Acceptance behaviours
A. Names follow the map; behaviour and alias rejection persist. `rg -nw 'test_verifier|test_verifier_leftovers|pending:verification|not_verified|VerifyResult|VerifyRefused|VerifyUnavailable|Verified|Verifier|verify_task|open_verifier|open_verify' src/taskloop tests/steps tests/cli` returns no matches; other verification words satisfy exclusions.
