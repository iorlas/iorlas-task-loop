# Reduce repeated implement reads

## Purpose and completion

Give the implement attempt the plan author's reading locations and a factory-produced map of real paths. Require every accepted plan artifact to contain a Read list, and put bounded reading instructions in implement input, including retries. The source reviewed is `5e7dced42b84267ba50c42c27d80d1c112da3484`.

Software acceptance: a missing Read list rejects both `planned` and `unchanged` plan artifacts; plan input requests at most 25 entries with ranges and reasons; implement input contains the reading rules; CODE MAP names committed paths and explains this repository's layout. Performance acceptance remains an observation of subsequent attempts, as described below.

## Current producers and change map

`plan_step.input_text` and `_closing_words` produce plan directions. `plan_step.artifact` reads the immutable plan blob and `_content` currently checks only UTF-8, nonempty content and size. This artifact path is shared by newly committed plans and reused plans; JSON decoding cannot validate a section in a separate file.

`implement_step.input_text` and `_closing_words` produce implement directions. Ordinary repeats and failed-check feedback embed the original complete input. Put the new reading instructions in that original input so both paths retain them.

`input_context.read` builds committed profile/glossary context through `GitProfileFiles`; `InputContext.render` supplies its delimited block to both steps. Initial admission (`admit.py:171`), step advancement (`admit_chain.py:238`) and dispatch refresh (`attempt.py:189-199`) already call this reader. Dispatch uses the prepared commit and pinned Git directory, and saves launched input. Extend this existing route for CODE MAP; those callers and the composition roots should need no change.

`GitProfileFiles` already uses the owning shelf's `Repo.tree` and its structured `files` keys. Use those keys for the committed equivalent of `git ls-files src tests docs/design`; no new command runner is needed. `steps.RULES` combines artifact rules and `attempt_loads` decodes stored rejections through that registry. `hold_cause.RULES` supplies their explanations.

The plan/change-map work mentioned in task .191 is separate. This task supplies the Read list, its presence check, implement reading instructions and CODE MAP; it does not add another change-map validator.

## Changes

1. **Plan directions and artifact validation.** Require the literal heading `## Read list`, followed by a Markdown bullet list. Each entry names the existing file location as `path:first-last` and a short reason, covering every file the implement step must edit or consult, including producers and callers. Ask for no more than 25 entries and for narrow, useful ranges. New files are explicitly identified as new in the implementation narrative; their existing integration points belong in the list. Allow additional targeted searches when a caller was missed or the source changes.

   Extend `_content` with a small deterministic line scan for the exact heading and a following nonempty bullet list, skipping blank lines and ignoring fenced code. Do not infer requirements from prose, use regular expressions over the plan, add a Markdown dependency, or validate the correctness of paths/ranges/reasons. The 25-entry limit is a prompt instruction, not an additional rejection policy. Keep the existing encoding/empty/size checks and their precedence. A heading mentioned in prose or a fence, a wrong heading, a bare heading, or a heading followed only by a new section does not satisfy the presence check.

   Add an enum-backed `PlanContentRule.READ_LIST` with serialized value `plan_read_list` to the shared rule type/registry, rather than adding a new string-literal vocabulary. Include it in `ARTIFACT_RULES` and the existing rejection codecs and explanation table. Preserve existing stored rule values and database schema. Do not migrate unrelated legacy vocabularies. Both `planned` and `unchanged` use the new check; a preexisting plan missing the section must be rewritten rather than silently grandfathered. `needs_owner` and `incomplete` still require no plan.

2. **Implement directions.** After reading the committed plan, read its Read list by the stated line ranges before exploring other files. Search with `rg -n`, then inspect only needed ranges. Do not `cat` a file over 300 lines. Before considering `cat` for a file over 150 lines, run `rg -n '^def |^class '` and use range reads; an empty symbol search is still followed by relevant ranges. Do not batch whole-file dumps. Do not read a file again within the session unless it changed since the last read; then read only the changed range. This includes verification after an edit. Keep enough location information from the first read to edit without reopening the same unchanged content. Searching for an omitted caller remains allowed. These are input directions, not shell interception or transcript-derived control state.

3. **Committed CODE MAP.** Add a narrow input-files protocol extending the existing blob-read port with a typed path listing operation. Implement that operation on `GitProfileFiles` using `Repo.tree(commit).files`, preserving the adapter's unavailable/no-commit distinctions and pinned repository view. Keep the general profile port unchanged. Return native typed values and turn listing failure into an explanatory `InputError`; never fall back to a working-tree listing.

   Extend `InputContext` with the committed path names, update its construction sites in tests, and render one `CODE MAP` within the existing context block. Include a deterministic sorted list of repository-relative tracked names under `src/`, `tests/` and `docs/design/`, one path per line, without contents, modes, object ids or directory-walk output. Preserve directory prefixes: basenames alone would recreate the guessed-path problem. Include the complete matching list, without inventing paths or silently truncating it. At the reviewed commit it is 568 names, approximately 22.6 KB of path text.

   Explain the observed layout concisely: source modules here are primarily `src/taskloop/*.py`, with feature subfolders including `agents/`, `drain/`, `check_repeat/` and `dash/`; tests are in `tests/steps`, `tests/cli` and `tests/rules`. Shared test helpers such as `doubles.py` are in `tests/steps`; the committed pytest configuration uses importlib mode and `pythonpath = ["tests/steps"]`. Scope these taskloop-specific hints to this repository's matching paths/configuration; do not present them as facts about arbitrary registered repos. If configuration must be inspected to establish a hint, read its committed blob through the same port. Other repositories still receive their actual tracked path list without fabricated taskloop paths. No new configuration option or dependency is necessary.

   Refresh the map together with checks and glossary whenever the prepared source changes. Verify the existing context replacement still produces exactly one map on ordinary repeats and failed-check retries and that retained launched input contains what the agent actually received.

4. **Affected test fixtures.** Positive lifecycle tests currently write miniature plans such as `# Plan\n`; the new rule will correctly reject them. Update their plan text to include a minimal Read list while preserving deliberately invalid plan cases and existing differing version contents. Prefer a small shared test value in the existing helper location if it reduces duplication; do not hide automatic plan repair in generic Git fakes, recording helpers or production code. Adjust the exact-size fixture so its total bytes still equal the cap. Update real-test fixture text where necessary without running live tests. Do not rewrite historical design plans.

## Verification

Add focused behavior tests through `PLAN.artifact`/the existing verifier, rather than testing every parsing helper. Cover a valid section, missing/misnamed/empty section, prose/fenced false positives, rejection of an unchanged old plan, and successful replanning of that artifact. Preserve encoding, whitespace and byte-limit cases. Exercise the new rejection's store round trip and its specific human explanation; the explanation must not fall through to an unknown-rule message. `test_verifier.py` is already 829 lines: put new cases in a focused new test module rather than increasing that file, and keep new modules/functions within repository caps.

Extend input contract tests to check the plan format and 25-entry request, all implement reading rules, and their retention through both retry routes. Map tests use semantic fake Git repositories with different committed and dirty paths: assert exact prefix filtering, sorted full paths, exclusion of unrelated/untracked/deleted names, truthful empty results, explained listing failure, source-change refresh and exactly one map. Test the helper-location hint against the committed pytest settings. No process spawning or real agent calls are required.

After the declared environment is installed, run changed behavior test files through the existing isolated pytest invocation, then the required gates `just check` and `just test`, following the implement input's check limits. The plan attempt does not run implementation gates. Fix positive fixture regressions surfaced by those gates without weakening the artifact contract. Preserve existing file/function caps; new source files must stay under 400 lines and functions under 80 lines, and new test files under 800 lines.

## Follow-up measurement

Use the existing owning transcript/evidence readers for the next eight implement attempts after rollout. Report an interim view after six and the final result after eight; do not launch unrelated attempts just to obtain a sample. Record attempt ids, task ids, source version, total source/test reads, repeat file reads within each session, and input tokens using the original evidence's counting method. Keep its upper-bound repeat definition comparable, and separately note reads following changes where evidence supports that distinction. Logs are measurement evidence only, never scheduling/control state.

Acceptance is fewer than 100 repeat file reads across eight attempts and mean input tokens no greater than 6.3544M per implement attempt (at least 6% below 6.76M). Include CODE MAP and any increased plan-input cost in the cost report; the expected plan increase is about 0.1M tokens. Results remain pending until those attempts exist. Record missing evidence and sample differences rather than claiming savings from prompt tests. If the targets fail, report whether missed locations, unchanged rereads or map size account for the result before proposing another change.

## Read list

- `src/taskloop/plan_step.py:27-35`, `src/taskloop/plan_step.py:90-112`, `src/taskloop/plan_step.py:142-168` — plan directions and the shared artifact check.
- `src/taskloop/implement_step.py:113-180` — implement directions and both feedback routes.
- `src/taskloop/input_context.py:1-69` — committed input protocol, construction, rendering and refresh.
- `src/taskloop/git_views.py:100-133`, `src/taskloop/profile.py:88-110` — extend the Git adapter without broadening the general profile port.
- `src/taskloop/attempt_types.py:204-228`, `src/taskloop/steps.py:29-58`, `src/taskloop/attempt_loads.py:40-55`, `src/taskloop/attempt_result.py:44-48` — enum-backed artifact rule, registry and rejection codecs.
- `src/taskloop/hold_cause.py:11-27`, `tests/steps/test_hold_text.py:150-170` — specific rejection explanation and its coverage.
- `src/taskloop/admit.py:160-178`, `src/taskloop/admit_chain.py:229-243`, `src/taskloop/attempt.py:189-199` — existing initial, advanced and refreshed committed-context consumers.
- `pyproject.toml:41-50`, `tests/steps/doubles.py:169-192` — size/test configuration and pinned semantic Git views.
- `tests/steps/test_input_context.py:1-69`, `tests/steps/test_input_context.py:115-216` — input contracts, selected source, dispatch refresh and ordinary retry.
- `tests/steps/test_steps.py:42-61`, `tests/steps/test_steps.py:108-157` — implement and retry input contracts.
- `tests/steps/test_profile.py:240-276` — adapter examples for immutable trees and explained Git failures.
- `tests/steps/test_verifier.py:155-180`, `tests/steps/test_verifier.py:205-255`, `tests/steps/test_verifier.py:409-449`, `tests/steps/test_verifier.py:467-491` — artifact fixtures, size boundary and unreadable-blob behavior.
- `tests/steps/test_repeat.py:146-170`, `tests/steps/test_repeat.py:200-225`, `tests/steps/test_repeat_dispatch.py:145-205` — valid plan fixtures for repeat lifecycles.
- `tests/steps/test_publish.py:158-186`, `tests/steps/test_publish.py:220-405` — new and reused plan publication fixtures.
- `tests/steps/test_attempt_entry.py:175-190`, `tests/steps/test_attempt_entry.py:270-410` — entry lifecycle positive plan fixtures.
- `tests/steps/test_admit_chain.py:105-122`, `tests/steps/test_admit_chain.py:180-195` — advancement fixtures that require an accepted plan.
- `tests/steps/test_slot_release.py:135-150`, `tests/steps/test_slot_release.py:178-195`, `tests/steps/test_slot_lock.py:100-195` — valid plan fixtures for custody and release.
- `tests/steps/round_bench.py:295-307`, `tests/steps/test_round.py:258-275` — round plan producers used by lifecycle checks.
- `tests/steps/test_conflict_recovery.py:125-140`, `tests/steps/test_merge_advance.py:70-85` — retained-plan fixtures during conflict recovery.
- `tests/steps/test_operations.py:425-445`, `tests/steps/test_operations.py:462-480`, `tests/steps/test_operations.py:507-525`, `tests/steps/test_operations.py:719-735`, `tests/steps/test_drain_fences.py:238-255` — operation and drain positive plan fixtures.
- `tests/steps/real/test_commit_real.py:70-85`, `tests/steps/real/test_commit_real.py:105-120`, `tests/steps/real/test_publish_real.py:58-73` — align existing real Git plan fixtures without running live tests.
- `tests/steps/real/test_repeat_real.py:88-112`, `tests/steps/real/test_release_real.py:120-135`, `tests/steps/real/test_prepare_real.py:88-102` — align remaining real lifecycle plan fixtures without running live tests.

Ranges describe the reviewed source, not a requirement to dump every interval at once. Start with the producer ranges needed for the current edit; fixture entries are grouped by the behavior they support. Use targeted `rg -n` if line numbers move or another positive fixture is discovered. New focused test modules belong in `tests/steps/` and have no preexisting range.
