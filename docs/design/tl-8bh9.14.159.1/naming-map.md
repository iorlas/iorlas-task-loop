# Factory commit naming map

This is the docs-only naming contract for tl-8bh9.14.159, inventoried at
`7ea3dad1de46e18edc6546711d7034cdc8dc1c0a`. The term is
[factory commit](../../glossary.md#factory-commit); the short operation and command name is `commit`.
Tables describe targets for the parent task, not runtime changes delivered by this note.
There are no command aliases, dual fields, compatibility readers or new retry policies in this design.

Factory commit belongs to its agent attempt. The entry, manual command, repeat and round call the same operation.
It obtains or reconciles the result commit, checks the clean tree, judges the retained chain and stores one verdict.
A valid `keep` answer still needs those checks; saved unfinished work needs its own review commit.
A stored verdict is returned without Git access. A Git commit alone does not establish success.
Release and publication follow the verdict and report their own results; neither can change the verdict.

## Code and command names

Paths in this section are relative to `src/taskloop/`. Importers and identical local-variable, comment and
docstring uses follow their owning row. A success type here means the stored verdict, not just a Git write.

| Old name | Target | Owner / surface |
|---|---|---|
| `verifier.py` | `commit.py` | Application operation; `factory_commit.py` remains its Git boundary |
| `Verifier`, `VerifyHold` | `FactoryCommit`, `CommitHold` | `verifier.py` |
| `verify`, `_verify`, `_verified` | `commit`, `_commit`, `_committed` | `verifier.py` methods |
| `Verify` protocol and its `verify` method | `Commit` protocol and `commit` method | `operations.py` |
| `VerifyResult` | `CommitResult` | `attempt_types.py` |
| `Verified` | `Committed` | `attempt_types.py`; successful verdict with `blob` and `reused` |
| `VerifyRefused` | `CommitRefused` | `attempt_types.py`; reason prevents factory commit |
| `VerifyUnavailable` | `CommitWaiting` or `CommitRefused` by cause | `attempt_types.py`; see result families below |
| `Unsettled` | `Uncommitted`, `CommitRefused` or `CommitWaiting` by cause | `attempt_types.py`; see cause table |
| `StoredExecution.verification` | `StoredExecution.verdict` | `attempt_types.py`; optional stored judgment |
| `verify_task`, `verify_failure`, `VERIFY_KINDS` | `commit_task`, `commit_failure`, `COMMIT_KINDS` | `operations.py` |
| `VerifiedTask` | `CommittedTask` | `operations.py`; verdict plus release and publication words |
| `verifier` parameters / fields | `factory_commit` | `operations.py`, `repeat.py`, `round.py`, composition callers |
| `Settle.verify` | `Settle.commit` | `repeat.py`; repeat's operation port |
| `open_verifier` | `open_factory_commit` | `composition.py`; shared writer and slot custody |
| `open_verify` | `open_commit` | `cli_composition.py`; command composition |
| `_verify`, parser variable `verify` | `_commit`, parser variable `commit` | `cli_step.py` |
| `tl step verify` / dispatch `("step", "verify")` | `tl step commit` / `("step", "commit")` | `cli_step.py` |
| `Next: verify`, action `verify` | `Next: commit`, action `commit` | `attempt_status.py`, `operations.Action` |
| `_verified`, `ports.verifier` | `_committed`, `ports.factory_commit` | `round.py`; shared command operation |
| `verify=` | `commit=` | `attempt_entry.py:shown`, `_step`; `evidence_files.ENTRY_WORDS` comment |
| lock role `verify` | lock role `commit` | `slot_lock.py:Role`, `custody` and holder explanations |
| task status action `verify` / prose “verifying” | `commit` / “completing factory commit” | `task_status.py:SETTLING` |

`applicable`, `leftovers`, `staged`, `_quiet`, `_ready`, `_settle` and `_kept` retain their responsibilities.
In `factory_commit.py`, `settle`, `clean_at`, `refusal`, `leftovers`, `Settled` and `GitQuiet` keep their names;
their cause results follow the table below. Its existing `Committed(sha)` is a Git fact, scoped to that module,
not the successful verdict `attempt_types.Committed(blob, reused)`.
`Rejected`, `NotApplicable`, `Verdict`, `PathExplanation`, `judged` and `succeeded` keep their meanings.
New result families and reason vocabularies must be typed, with one codec at each storage or display boundary.

The renamed `commit_task` preserves the current sequence: factory commit, settled release after either verdict,
and publication after success. Its result retains the release and publication fields, including their failures.
It must not report a publication failure as a failed factory commit or release an unfinished commit as successful.

## Result words, storage and consumers

| Old name / value | Target | Owner / surface |
|---|---|---|
| `verified` success verdict / status | `committed` | `attempt_result.py:judged`, `operations.CommittedTask` |
| `reused` | `reused` | Successful unchanged result; preserve `reused` flag and meaning |
| `rejected:<rule>` | `rejected:<rule>` | Stored terminal rule rejection; not an operational refusal |
| `pending:verification` | `pending:commit` | `attempt_result.py:_report`, `attempt_entry.py:resumed`, `round.py` |
| `not_applicable` / `NotApplicable.what` | unchanged | No eligible answer; never a successful factory commit |
| table `verification` | table `factory_commit` | `factory_schema.py`, `attempt_store.py`, `attempt_loads.py` |
| stored verdict kind `verified` | `committed` | Schema constraints and verdict encoder / decoder |
| `verification` joins, guards and foreign key | `factory_commit` equivalents | Store consumers listed below |
| `not_verified` | `not_committed` | `publish.py`, `step_guide.py`, `round_guide.py` |
| “verified result/commit/plan” | “result/commit/plan accepted by factory commit” | Delivery, advancement and guidance |
| local `verified` result or boolean | `committed` | Entry, status, round and publication consumers |
| “failed verification”, “verification-repeat” | “failed factory commit”, “repeat after factory commit” | Repeat feedback |

Storage retains attempt identity, dispatch token, generation, rule, artifact blob, observation time and reuse flag.
The table and success word rename is a schema change for the parent: drain running attempts and discard the old DB
before the new schema is used, as repository policy requires. This note adds no migration or fallback.
`StoredExecution.verdict` is a judgment; the dashboard's `Outcome.factory_commit` below is a richer projection.

The following groups account for identical uses beyond the owning definitions:

- `attempt_entry.py` calls `FactoryCommit.commit`, formats `commit=`, and rereads a newly stored terminal result.
  `attempt.py` describes the same operation. `attempt_result.py` gates collection and success on the stored verdict;
  `attempt_status.py` probes leftovers only for `Next: commit` and retains release / publish / advance decisions.
- `repeat.py:StepRepeat`, `_words`, `_leftovers`, `_index` and `_record` consume the renamed results and cause families.
  `steps.py`, `plan_step.py:feedback`, `implement_step.py:feedback`, and `step_text.py:unsafe_details` consume file
  listings and per-path explanations. `attempt_types.Admission.number` remains the repeat number, not a new step.
  `admit_chain.RepeatRequest`, `attempt_reads.AttemptRow.repeat_listing` and schema comments describe factory commit
  feedback. Preserve the repeat cap and existing eligible causes (`unsafe`, `ignored`, `uncommitted`).
- `attempt_store.py:_verdict_values`, `end_commit`, `verdict` and `attempt_loads.py:verdict_of`, `latest_plan`,
  `_execution` encode or read the renamed table and success value. `admit_chain.py` and `publish.py` use the same table
  in their fences. `factory_schema.py:published_branch` references it. No SQL reader may retain the old name.
- `answer_repair_route.py` and `answer_repair_store.py` check `execution.verdict` when deciding whether repair is allowed.
  `verdict.py:judge` returns `Committed`; `implement_step.py:artifact` documents its nullable blob.
  Generic rule checking, including `plan_step.py:artifact`, still judges the same rules.
- `composition.py`, `cli_composition.py` and `round.py:RoundPorts` wire the renamed operation, including read-only
  leftovers views. `result_data.py`, `step_render.py` and their result unions dispatch `CommittedTask` and print
  `committed` / `reused`. The structured result retains its existing identity, release and publication fields.
- `round.py` changes its action dispatch and pending-reason comparison, its `_publish` success collection's wording,
  and the relevant `STOPPING_UNKNOWN` classification. `exit_codes.py` and `operations.UNKNOWN_KINDS` must distinguish
  the replacement file / wait / refusal families without treating unknown evidence as success.
- `step_render.py` replaces “Unsettled:” with the cause family's words, retaining the listing.
  `step_guide.py`, `step_refusal_guide.py` and `round_guide.py` change operation keys, commands, success checks and
  explanations. `round_guide.py` recognizes `committed` where it currently recognizes `verified`.
  `hold.py` and `hold_facts.py` change their example `unsettled:worker_alive` to `waiting:worker_alive`.
- Completion prose in `check_admit.py`, `steps.py`, `land_guide.py`, `hold_guide.py`, `attempt_reads.py`, `publish.py`
  and CLI help becomes “accepted by factory commit”. This changes no checks admission, publication or land policy.

## Dashboard and page names

Paths below are relative to `src/taskloop/`; JavaScript files are under `dash/static/`.
Factory commit remains a mark attached to its agent attempt with a Result view and no separate column.
The existing task-wide projection number and `of_step` / `of` identify that attachment; they do not schedule an attempt.

| Old name / wording | Target | Owner / surface |
|---|---|---|
| `dash_verify.py` | `dash_commit.py` | Read-only projection |
| `STEP = "verification"` | `STEP = "commit"` | `dash_commit.py`; synthetic history/body selector |
| function `verification` | function `factory_commit` | Projection producer and `dash_task.py` import |
| `Verification` | `FactoryCommit` | `dash_model.py`; projection type, distinct from the application class |
| `VerifyCheck` | `CommitCheck` | `dash_model.py`; one internal factory check, not a configured check |
| `Outcome.verification` | `Outcome.factory_commit` | Model, serialized body and JavaScript consumer |
| `VERIFICATION`, `_verification` | `COMMIT`, `_factory_commit` | `dash_task.py` selector and projection builder |
| `Link.verifies` | `Link.commits` | `dash_task.py`; attached projection discriminator |
| local `verified` counter | `commits` counter | `dash_task.py:_chain`; projection numbering only |
| `VERIFY`, id `verification` | `COMMIT`, id `commit` | `ui.js:stepInfo`; all rail / drawer consumers |
| label `Verification` | `Factory commit` | `ui.js` |
| `verifyTitle`, “Check of Plan/Implement” | `commitTitle`, “Factory commit of Plan/Implement” | `rail.js`, `drawer.js` |
| `verificationButtons` | `commitButtons` | `rail.js`; mark, reason and navigation |
| local `verification` attachment | `factoryCommit` | `rail.js:project`, `row`, `summary`, selection |
| “Verification of …: … Open Result” | “Factory commit of …: … Open Result” | `rail.js` accessible label |
| “verification outcome was not recorded” | “factory commit outcome was not recorded” | `rail.js:verdict` |
| “Not checked yet” | “Factory commit pending” | `rail.js:verdict`; missing conclusion remains unknown |
| `verification(v)` | `factoryCommit(v)` | `result.js`; render `body.result.factory_commit` |
| “Checked after …” | “Factory commit of …” | `result.js`; keep owning step and attempt number |
| `verification` summary key | `commit` | `words.js`; “Factory commit has no successful verdict” |
| `verified` wording | `committed`: “Factory commit completed” | `words.js`; `rail.js` success recognition |
| `unsettled:*` wording keys | Exact cause-table targets below | `words.js`; preserve explanations |

`dash_task.py:_chain`, `_history`, `history` and `build_body` preserve placement immediately after the owning agent,
repeat `led_by` navigation and past-chain boundaries. `Link.successor` still supplies the repeat's stored listing.
`dash_model.AttemptDetail.led_by`, `run` and `usage` comments adopt factory commit wording; fields keep their roles.
`drawer.js` changes its Result-only tab choice, line-stream exclusion, preceding-agent lookup and pane title together.
`rail.js` changes `lasted`, `project`, `verdict`, `row`, `summary`, history titles, selection and `causeLink` together.
Success comparisons use `committed` / `reused`; the pending-summary comparison uses `commit` rather than `verification`.
Comments and error text such as “A verification belongs to an agent attempt” become “A factory commit belongs …”.

The five displayed internal checks in `dash_commit.CHECKS` retain their order and explanations:

| Existing check / failure selector | Target selector / result |
|---|---|
| Slot is on the task branch at the agent's start / `branch` | `refused:branch` |
| Every listed path is a permitted plain file / `unsafe` | `uncommitted:unsafe` |
| No ignored file under the listed paths / `ignored` | `uncommitted:ignored` |
| Nothing is left uncommitted at the commit / `uncommitted` | `uncommitted:uncommitted` |
| Commit passes the step's rules / `rejected` | `rejected:<rule>` |

These selectors describe internal checks, not commands from the profile. Preserve path lists, failed-check markings
and “Not reached”. A missing verdict or failed observation is pending / unknown, never proof that all checks passed.
The new names alone do not supply new evidence or change the projection's existing inference from a successor.

## Cause mapping

This table exhausts the eleven reasons named by `attempt_types.Unsettled` plus the page-only `rejected` key.
An emitted cause is produced by the agent factory commit path or its repeat guard. “Documented only” means no
producer on that path; “synthetic” means page vocabulary, not an operation result. Suffixes retain their meaning.
Families distinguish files needing attention, a condition preventing the operation, and a wait / unknown observation.

| Old cause | Target cause | Owner / evidence |
|---|---|---|
| `unsettled:unborn` | `refused:unborn` | Emitted: `settle`, `clean_at`, `leftovers`; `SlotState.problem` |
| `unsettled:branch` | `refused:branch` | Emitted: same producers; page also projects it from a successor |
| `unsettled:head_moved` | `refused:head_moved` | Emitted: `_moved`, `clean_at`, `leftovers` |
| `unsettled:dirty` | `uncommitted:dirty` | Documented only in `Unsettled`; see distinction below |
| `unsettled:redirected` | `refused:redirected` | Emitted: `_observed`, `_blocked` |
| `unsettled:worker_alive` | `waiting:worker_alive` | Emitted: `Verifier._quiet`; repeat forwards it |
| `unsettled:superseded` | `refused:superseded` | Emitted: `Verifier._quiet` before Git writes |
| `unsettled:staged` | `uncommitted:staged` | Emitted: `_foreign`; `StepRepeat._index` also guards it |
| `unsettled:uncommitted` | `uncommitted:uncommitted` | Emitted: `clean_at`; page can project it |
| `unsettled:unsafe` | `uncommitted:unsafe` | Emitted: `_review` via `refusal` / `settle`; page can project it |
| `unsettled:ignored` | `uncommitted:ignored` | Emitted: `_review`; page can project it |
| `unsettled:rejected` | `rejected:<rule>` | Synthetic `words.js` key only; no `Unsettled("rejected")` producer |

`unborn` means no commit exists; `branch` means detached HEAD or the wrong branch. `head_moved` is unexpected
history, with any named refs retained for inspection; factory commit must not silently adopt foreign commits.
`redirected` means the slot pointer changed. These are refusals, not ordinary files for a repeat to fix.
`superseded` means reservation ownership changed; the old attempt must not write in its successor's slot.
`worker_alive` means the registered worker is missing or not proved gone, not proof of health: retain custody and wait.

`staged` lists staged paths outside the intended set, or blocks a repeat on its existing index.
`uncommitted` lists tracked / untracked leftovers after the result commit (including a `keep` result).
`unsafe` retains the unsafe paths, adjacent leftovers and each owning explanation without exposing file content.
`ignored` lists ignored paths affecting staging; it does not mean every ignored file anywhere blocks the clean-tree check.
`SlotState.problem` returns `dirty`, but `clean_at` translates that to emitted `uncommitted` plus a listing.
Keep `dirty` as an explicit documentation mapping, not a newly invented producer.

The page's actual rule-rejection producer already emits `rejected:<rule>`. The old `unsettled:rejected` wording key
has no rule payload; remove that obsolete synthetic key rather than invent a rule or turn it into a stored refusal.
All real rule rejections, including `nothing_written`, remain terminal `Rejected` verdicts.

## Refusals, unavailable results and pending work

The old `Unsettled` bucket is split by cause, not mechanically renamed to one family.
The same applies to `VerifyUnavailable`: waiting requires missing evidence or a transient condition, not a false success.
The parent keeps backend diagnostics in their adapters and supplies an explanation for every resulting cause.

| Old result | Target result | Meaning / owner |
|---|---|---|
| `VerifyRefused(reason)` / `refused:<reason>` | `CommitRefused(reason)` / `refused:<reason>` | Preventing condition is retained |
| `unavailable:store`, `observe` | `waiting:store`, `waiting:observe` | DB or process observation unavailable |
| `unavailable:git:<Type>` | `waiting:git:<Type>` | Git evidence unknown; adapter retains diagnostic |
| `unavailable:repo`, `not_listed` | `waiting:repo`, `waiting:not_listed` | Slot / repository evidence unavailable |
| `unavailable:slot_busy`, `lock` | `waiting:slot_busy`, `waiting:lock` | Custody busy or lock cannot be opened |
| `unavailable:validation_pending` | `waiting:validation_pending` | Answer validation unfinished |
| `unavailable:session_pending` | `waiting:session_pending` | Session collection unfinished |
| `unavailable:session_fault` | `refused:session_fault` | Collection fault needs diagnosis; preserve evidence |
| `unavailable:read_only` | `refused:read_only` | Wrong writer wiring, not contention |
| `unavailable:inconsistent` / `defect:inconsistent` | `refused:inconsistent` | Contradictory retained facts; preserve defect diagnostic |
| `pending:verification` / page `pending` | `pending:commit` / page `pending` | No stored verdict; no success implied |

Refusal reasons include `not_captured`, `absent`, `no_base`, `session`, draining and store fencing reasons such as
`stale_reservation`, `changed_admission`, `changed_answer` and `released`. Keep those suffixes and their explanations.
An existing stored verdict takes precedence over fresh Git observation. Pending answer validation and pending
session collection remain separate facts from pending factory commit. `NotApplicable` remains distinct from refusal.
No cause rename grants automatic retries, removes an explicit hold, changes a repeat's eligibility or proves a worker stopped.

## Inventory boundary and exclusions

The active-source inventory searched `src/taskloop` with
`rg -ni 'verif(y|ication|ied|ier)|unsettled' src/taskloop` and grouped identical uses by their owners above.
The glossary's old page labels are reconciled in this task; its as-built command spellings remain evidence for this map.
Historical design notes, mockups and test fixtures are not current operation names. Runtime implementation must update
the affected behavioral fixtures when their owners change; this docs-only task adds no tests mirroring prose.

The following matches intentionally keep their names and meanings:

- Configured checks and validation: `checks.py`, `validate.py`, `check_entry.py`, `check_status.py`, `check_store.py`,
  `check_repeat/repair.py`, `check_release.py`, `setup_store.py`, `environment.py` and `owned_processes.py` use
  `unsettled` for unfinished or surviving commands. Those properties and queries are not factory commit outcomes.
  `step_guide.py` and `land_guide.py` also explain that separate checks / land release vocabulary.
- Release stop proofs: `release_proof.py`, `slot_release.py` and `check_release.py` can independently emit
  `unsettled:worker_alive`, `worker_unknown`, `setup_running`, `check_running` or a recovery running reason.
  The family change above applies to factory commit and its repeat guard, not those owning release operations.
  Shared guidance such as `round_guide.py` must distinguish the operation instead of globally replacing `unsettled`.
- Identity, evidence and safety: “verified pointer”, “verified pid”, “verify identity” and “verified idle” in
  `prepare.py`, `slot_state.py`, `git_views.py`, `slots.py`, `environment.py`, `earlier_input.py`, `checks.py`,
  `inspection_guide.py`, `show_render.py`, `step_refusal_guide.py`, `hold_text.py`, `hold_facts.py`, `drain/`,
  `cli_drain.py`, `cli_composition.py` and the guides retain their ordinary meaning.
  `land_conflict/{preserve,abort,cleanup,handoff,release,execute}.py` validates retained conflict / process evidence,
  not agent factory commit; its `verified` methods and “unsettled setup” diagnostic remain unchanged.
- `shelf_digest/validation.py:_verify` verifies source attribution. `git_views.py` documents Git's `--no-verify` option.
  Neither is an operation rename. `implement_step.py`'s focused verification and final-gate instructions, and plan /
  implement answer validation before checking Git effects, also keep their ordinary validation wording.

These exclusions preserve the distinction between factory commit, configured checks, process observation and delivery.
