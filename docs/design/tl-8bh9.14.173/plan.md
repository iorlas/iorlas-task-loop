# Accept unfinished answers that list paths

Task: tl-8bh9.14.173. Plan prepared 2026-11-14 against 99655d38.

## Decision and scope

Follow the explicit correction of 2026-11-14: keep the structural strict answer schemas unchanged, ignore
`paths` on `incomplete` and `needs_owner`, and put the guidance in both steps' fixed input text. The final
acceptance sentence repeats the withdrawn conditional-schema requirement; the correction supersedes that
part. No composition keywords or new vocabulary are needed.

An unfinished answer must retain its disposition and explanation, have effect `none`, and store empty commit
paths. Ordinary unfinished slot changes remain available through the work-in-progress commit behavior already
implemented by tl-8bh9.14.148. A normal `failed:incomplete` or `failed:needs_owner` hold remains intentional;
the defect is misclassifying that answer as `answer:schema_invalid` and wasting another attempt.

This task changes answer decoding and instructions, with focused regression coverage of collection and held
work preservation. It does not change scheduling, hold policy, task branch ownership, saved-work safety rules,
database schema, dependencies, or historical attempt records. It does not rewrite tl-8bh9.14.155's tracker text
or create per-task supervisor instructions.

## Current implementation

- `src/taskloop/implement_step.py::decode` calls `listed_paths` before inspecting the disposition and requires
  an empty tuple for every disposition except `implemented`.
- `src/taskloop/plan_step.py::decode` has the same restriction except for `planned`, along with its existing
  `plan_path` rule. Both schemas deliberately omit composition and leave cross-field validation to decoding.
- `src/taskloop/attempt.py::_validate` stores the decoded disposition, effect, paths and message, or records
  `schema_invalid` when decoding fails. Correcting the step decoders should suffice for collection.
- Both steps assemble fixed instructions in `_closing_words`; `step_text.SAVED_WORK` already explains how
  to assess a prior commit with a `Task-Loop-Wip:` trailer, but does not tell agents what paths to return now.
- `hold.py`, `slot_release.py`, `hold_store.py` and `wip.py` already save held slot work on the task branch,
  record saved commits, and release the slot. Existing round tests cover saved edits, deletions, new files,
  ignored-file retention and idempotence; verifier tests ensure saved work alone is not a completed result.

There is no existing plan for this task and no task-local unfinished commit ahead of `origin/main` to adopt.

## Implementation

1. Update both step decoders to distinguish unfinished dispositions before applying commit-path validation.
   For `incomplete` and `needs_owner`, accept any structurally valid list of strings, then normalize it to
   `()` in the returned answer. Its entries are unused: do not apply commit eligibility, uniqueness, root,
   exclusion or path-count rules to them, and never read or commit files because they were listed there.
   Continue rejecting non-list values and lists containing non-strings. Preserve the required keys, known
   dispositions, explanation bounds, null message requirement, and the plan step's existing `plan_path`
   rule. Preserve all current validation for `planned`, `implemented` and `unchanged`. Update decoder
   documentation so it no longer promises rejection for unfinished answers that list paths. Leave the raw
   answer evidence intact; only the decoded commit request is empty.

2. Add one sentence to each step's fixed closing words, using that step's successful disposition:
   "Only with `implemented` should `paths` list files; otherwise return `paths: []` and `message: null`, and
   the factory saves unfinished slot work as a work-in-progress commit on the task branch when holding the
   task." The plan step uses `planned` instead of `implemented`. Keep this guidance part of every task's
   generated input, including inputs embedded in repeat and failed-check feedback. Scope the adjacent
   cleanup/uncommitted-file instructions to successful commit answers so they do not tell an unfinished
   agent to remove work the factory should preserve. Retain the existing prior-work guidance. Keep the
   wording in the step modules, or a small shared text constant where it actually removes duplication;
   introduce no instruction framework or additional policy owner.

3. Exercise the existing hold/save path with the newly accepted answers. Reuse its owning APIs and semantic
   fakes; do not introduce another snapshot mechanism, decoder bypass in collection, state reconstructed
   from evidence, or new Git/process escape. Change runtime code beyond the decoders/text only if this
   regression exposes a concrete failure in the existing preservation path.

## Acceptance and focused verification

- Update `tests/steps/test_answer_contract.py`: for both steps and both unfinished dispositions, empty and
  non-empty lists decode to the same disposition, effect `none`, empty paths and null message. Include
  unused strings outside the step's allowed root, duplicates and more than its commit-path cap to establish
  that unused paths cannot trigger commit-path rejection. Replace the existing tests that require rejection
  solely for this case. Keep regressions for malformed list shapes, non-null messages, invalid plan paths,
  invalid dispositions, and unchanged/successful answer restrictions. Retain the structural-schema tests.
- Extend collection coverage in `tests/steps/test_attempt.py` as appropriate for both steps: a successful
  agent execution returning unfinished answers with paths is stored as a valid answer with its original
  disposition, effect `none`, empty commit paths, and a collected reason of `incomplete` or `needs_owner`.
  It must not become `answer:schema_invalid`, request a commit, or trigger an automatic repeat.
- Extend `tests/steps/test_steps.py` to check both generated inputs with ordinary task requirements and no
  supervisor paragraph: they contain the paths/null-message/save guidance and prior-work guidance. Confirm
  repeat and failed-check feedback retain access to this guidance through the embedded fixed task input.
- Extend `tests/steps/test_round_holds.py` using the existing factory fixture. An implement answer of
  `incomplete` with a non-empty paths list and real slot edits is collected as incomplete, then held for
  `failed:incomplete`. The hold saves the actual final slot tree (including an unlisted ordinary new file)
  in a commit on `task/<id>` with the existing typed `Task-Loop-Wip:` trailer and records its full commit ID.
  The slot becomes clean and reusable; there is no `failed:answer:schema_invalid` hold or persistent
  `slot_dirty` blockage caused by this answer. Another round leaves the task held without adding a save or
  launching a repeat. After the normal owner-answer transition, the next admitted attempt starts from the
  saved task branch and receives the fixed prior-work guidance. Cover the plan/needs-owner variants through
  the same fixture where useful, without duplicating the existing exhaustive WIP safety tests.

Run the changed behavior tests first after `just install`, using
`uv run --frozen --no-sync python -I -m pytest -q` with the selected files above. Then run the required
focused gates `just check` and `just test` as defined in the justfile; do not run the whole suite or live
tests. Keep source/function/test caps and existing import boundaries. This planning step changes only this
document; runtime checks belong to implementation.

## As built

Both decoders now accept string lists on unfinished answers and discard their entries before commit-path validation.
The structural schemas are unchanged. Both fixed inputs carry the paths/null-message/save sentence and scope cleanup
to successful commit answers; repeat and failed-check feedback retain that input.

Regression coverage in the four test files above exercises decoding, stored collection and raw evidence, generated
instructions, and holding/resuming both unfinished dispositions for both steps. The existing hold implementation
saves listed and unlisted edits together, records the full saved commit and trailer, releases the slot, and resumes
from that task branch after an owner answer. No runtime hold changes were needed. No new test files were added.

The required gates also exposed an existing dashboard test reading `Run.summary` instead of `Run.access`; its assertion
was corrected without changing dashboard behavior.
