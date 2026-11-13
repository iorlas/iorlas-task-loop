# Feed failed checks back to the next implement attempt

Task: `tl-8bh9.14.138`. Prepared 2026-11-13 against `cab64dc1`.
Status: proposed; implementation must wait for the owner's yes. This change writes only the plan.

## Problem and current code

The owner observed `tl-8bh9.14.132` repeat the failing list-column assertion in
`tests/cli/test_check_cli.py`. The reflection in [self-hosting-real-run-2.md](../self-hosting-real-run-2.md)
records both missing check feedback and an unsafe-path message which does not identify its path
(also requested by `.135` item 7).

`implement_step.feedback` currently understands only uncommitted, unsafe and ignored paths. Its shared
frame in `step_text.feedback` labels all feedback as file names from Git status. `StepRepeat` obtains an
`Unsettled` result from the verifier and `ChainAdmission.admit_repeat` transfers that still-held slot's
reservation. These paths cannot accept a failed factory check: by then the implement attempt is verified,
released and published, and the checks attempt has its own reservation, often in another detached slot.
`check_status.route` presently reruns checks on the same commit for an explicit start; rounds hold failed
checks through `hold_status.cause`. Merely adding prompt text would leave the acceptance criterion unmet.

The bounded change therefore includes the failed-check-to-implement transition and its feedback. It
retains the existing three-attempt implement limit, counting path repeats and check-driven repeats
together. It adds no new step, scheduler, dependency, task-tracker state or public glossary term.

## Required behavior

1. When a required, defined check finishes with a nonzero exit (`failed`), make the next implement
   attempt eligible once the checks entry and commands are proven stopped and its slot is released.
   Select the first failed required check in the stored required order from the latest completed result
   block. Read structured results, never split the displayed `failed:<name>:<reason>` string.
2. The repeat's complete prompt contains a clearly labelled **Failed check** section with that check's
   name, the exact argv used at the checked commit, and a bounded tail of its merged output. Explain
   that the factory's check failed, ask the agent to fix the reported failure and run the checks, and
   retain the original implement task and plan instructions. Already committed files need not be
   listed again; the answer lists the new changes. An unchanged answer still goes through fresh checks.
3. Admit implement attempt N+1 from the previous implement attempt's checked commit X, with its
   original task claim, label, harness/provider and model choices. Preserve the implement chain and
   task-wide ordering. Use a fresh session, as existing repeats do. On completion, use the normal
   verify, release, publish and checks operations on its resulting commit; old passes are not reused.
4. At the existing implement cap (`ATTEMPTS = 3`), keep the failed checks and use the existing final
   failure/hold handling. A path repeat also consumes this budget; a checks rerun or coordinator
   restart never replenishes it. Explicitly held or abandoned work stays held or abandoned.
5. Preserve other check behavior: optional failures alone do not trigger repair; `main_moved` keeps
   its existing bounded checks-rerun policy. Setup/profile failures, missing or undefined checks,
   timeout, interrupted, lingering and dirty results retain their existing handling. In particular,
   do not treat an infrastructure failure or an unsettled command as an ordinary failed test.
6. An unsafe-path repeat names the actual first unsafe path in its explanatory text, safely escaped,
   while retaining the existing bounded listing of that path and any leftovers. It must identify a
   nearby unsafe Git file too, rather than assuming the unsafe entry was one of the answer's paths.

This deliberately handles an actual failed check, the observed case. It does not create a general
answer-repair turn, change sandbox/environment policy, or retry a land candidate's failed validation.

## Typed and bounded evidence

Introduce a small immutable typed failed-check value, validated with Pydantic v2 at the persisted-input
boundary. It carries the source checks attempt key, block, checked commit, check name, argv, result and
output tail with explicit truncation/availability information. Use stdlib enums/classes for new closed
values and one storage/display codec for each; do not add a free-form reason string to route workflow.
Keep source identity distinct from explanatory text. The pure implement renderer receives this value
through `steps`, respecting the existing rule that only `steps` imports `implement_step`.

The owning check reader supplies the latest completed result block and the required order. Resolve the
command through the existing profile reader at `ChecksRow.commit`, not current `main` or the worktree.
Verify its argv digest against the selected `ResultRow.argv_digest` (and the stored profile digest).
Use the profile's existing content, name and argv limits. A missing/mismatched profile is an explicit
unavailable/refused result and launches no attempt; do not guess a command from log headers.

Extend `EvidenceFiles` with a bounded check-output reader using the check key, block and name. Seek
from the end and read at most 16 KiB, then retain at most the last 100 lines, including an unterminated
last line. Decode invalid UTF-8 with replacement, escape terminal controls, and mark a cut prefix.
The file reader returns typed availability and truncation information. Missing/unreadable output is
shown explicitly in the feedback alongside the known name and command; it is never fabricated as
successful or silently presented as empty output. Empty output has its own explicit explanation.

Render argv losslessly as an argument list rather than reconstructing shell quoting. Put output in a
separate nonce-delimited block, labelled command output supplied as evidence, not instructions. Escape
control characters and marker-like lines so output cannot close the block. Bound rendered tail data
to 64 KiB after escaping; the exact command remains bounded by the 64 KiB profile input limit. Do not
apply the short filename-display truncation to check output or command arguments.

Only one failing check's output is included per repeat, deterministically selected as above. Preserve
all result rows and full retained logs behind their owning readers. Logs never decide whether to
repeat, which check failed, which command ran, or whether a process stopped. The immutable admitted
input captures the feedback once, so an admitted attempt's restart does not rebuild a different prompt.

## Application transition and storage

Implement one check-driven repeat operation shared by explicit `tl step start` and rounds. Keep the
current dirty-slot path-repeat operation intact; do not pass a failed check off as `Unsettled` or take
over a checks slot using the path-repeat admission's assumptions.

Use a feature folder for the new use case and its owning store operations. Existing attempt and check
stores expose typed reads/writes; SQL and connections remain inside store modules. Add only the source
link and constraints needed to associate the new attempt with the failed checks attempt. Retain the
existing `previous_attempt_id` chain and increment the implement attempt number. Express check-driven
repeat provenance with an enum/class and validate it through a single codec; do not store output tails
as a second check-log store. Include the source checks link in existing attempt reads so status and
reconciliation can distinguish this admission from a path-repeat takeover.

Before admission, confirm the previous implement attempt is still current, verified, released with
its claim kept and published at X; the latest checks attempt is failed and released without abandon;
the tracker claim is still ours; no active hold or delivered/active land candidate applies; and the
implement attempt is below its cap. The chosen failure must belong to that checks attempt's latest
completed block. A failed check does not remove the approval label or return the claim while a repeat
can proceed. A stopped checks attempt still needing release follows the existing release operation first.

Reserve an observed free, clean slot using the normal slot/branch checks, rather than retaining or
reclaiming the previous implement slot. Record the source link, immutable input reference, copied
choices, number N+1, sequence, start commit X and reservation in one short fenced transaction. Recheck
current attempt, latest checks identity/block, release, hold, cap and successor uniqueness under that
transaction. Concurrent starts adopt the same winner; stale callers cannot create another attempt.
No free slot is transient and must not prematurely hold the task.

Preparation must distinguish this clean-slot admission from a path repeat's inherited dirty slot.
Take the task branch at X through the existing Git port, require the expected commit (refuse a moved
branch), and run the implement setup before launching the agent. Do not inherit the checks slot's
environment. Adjust the current `after_commit` constraint/start facts and setup-selection rules as
needed for this admission while preserving chain verification from implement attempt 1's base.
Never reset the task branch backwards or discard work to make it fit.

Admission records the intent before launch; Git preparation and launch run outside write transactions
through existing owning ports, followed by fenced results. After a crash, reconcile the reserved
attempt, branch and registered process, adopt work already done and launch only if necessary. A crash
after checks release but before admission leaves an eligible failed check for reevaluation. A crash
after admission resumes that attempt and its stored prompt, without consuming another retry.

Have status, start routing, rounds and hold selection use the same typed eligibility decision. Before
release, show the existing release action; afterwards expose repeat when eligible and suppress a due
hold. At exhaustion or for an ineligible failure, retain existing final handling. Read-only status and
dashboard consumers only describe the decision; they perform no repair actions. Never infer the
implement budget from the checks view's number, which is numbered per checks attempt.

This requires a schema change: increment the factory schema version, drain running attempts before
upgrade, refuse an older database, and discard the old local database only through its authorized
owning operation. No migration, compatibility reader, log reconstruction or file fallback. Implementation
must not perform a live discard or restart as part of tests.

## Files and verification

Expected implementation seams are a check-repeat feature/use-case with store operations,
`check_store`, the attempt store/read models, `factory_schema`, `evidence_files`, `steps`,
`implement_step`, preparation/setup selection, `operations`, `attempt_status`, hold eligibility,
`round` and the existing composition roots. Keep modules below 400 lines, functions below 80 and tests
below 800. Split the new use case by ownership rather than enlarging already full orchestration modules.
Update the existing repeat/check behavior documentation during implementation; do not add new glossary terms.

Use pytest behavior tests with the existing semantic Git/process/agent fakes and real temporary SQLite:

- A normal implement attempt completes and publishes; a required check fails with output containing
  the observed `tests/cli/test_check_cli.py` list-column assertion. Through the application start path,
  release checks and admit/dispatch the next implement attempt. Inspect the actual agent prompt for
  the failed-check section, name, exact argv, assertion tail, original task and plan reference. Prove
  this is a new implement attempt on X, and that its subsequent successful checks permit normal progress.
- Through rounds, the same eligible failure repeats without a tracker hold; repeated failure at the
  shared cap holds once. Include a prior path repeat so check failure cannot reset the budget.
- Two competing starts and crash points before/after admission produce one successor and one stored
  input; restart continues it. A released old check, abandoned task, existing hold, changed branch or
  unsettled command cannot launch a competing implement attempt.
- The command comes from the checked commit even after `main`/worktree profile changes. Multiple
  failures choose the first required failure, not display order or a similarly named optional check.
- Oversized, invalid UTF-8, control/marker-bearing and unterminated output remains bounded and safe;
  only the tail is read. Missing output is labelled unavailable and empty output is labelled empty.
- An unsafe path appears by name in explanatory text, including a nearby Git file and a path with
  control characters. Keep existing uncommitted/ignored feedback and plan-step behavior covered.
- Existing main-moved reruns, passed checks, infrastructure failures, manual starts and explicit holds
  retain their specified behavior. Status/dashboard reads remain side-effect free.

Place new coverage in focused modules such as `tests/steps/test_check_repeat.py` and
`tests/steps/test_implement_feedback.py`; adjust affected existing routing/round/CLI expectations.
Do not grow the old repeat test modules past their caps or test every private helper.

Read the justfile, run `just install`, then run the focused new modules and affected repeat/check/hold
tests through `uv run --frozen --no-sync python -I -m pytest -q <selected modules>`. Finish with the
required `just check` and `just test` gates (the declared successor CLI/steps/rules suite), with no
whole-repository or live factory run. Planning itself needs no runtime tests.

Acceptance is demonstrated by the dispatched repeat prompt carrying the failing check's name,
command and bounded output tail, and by the unsafe-path text naming its path. A renderer-only test
without the failed-check-to-repeat application path is insufficient.
