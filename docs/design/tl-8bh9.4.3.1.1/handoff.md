# Successor factory handover — 2026-11-09

Status: **evidence**. Historical frozen handoff, not an active instruction prompt or current setup runbook.
The original commands and checkpoint limits below are preserved; current capabilities and commands are in the
[README](../../../README.md), and `AGENTS.md` is the current instruction file.

This is the copy-ready instruction prompt for the next agent on **pix**, in a **new worktree**.
Read it fully before acting. It records a frozen WIP checkpoint, not completed delivery.
Tasks remain the backlog and source of current status. This document preserves context and evidence.

## Start here

You are continuing Denis's task-loop redesign and implementation. Work autonomously in bounded cycles:
one source writer, required focused gates, then an independent reviewer. Use subagents for implementation
and independent review, and consult Astra on important design tradeoffs. Do not build a second factory to
bootstrap this work. Continue the existing curated successor rather than copying whole old packages.

The handover branch is `origin/codex/successor-foundation` in `iorlas/iorlas-task-loop`.
The handover commit contains this file; obtain its exact SHA with `git rev-parse HEAD` after checkout.
The previous committed checkpoint was `e5cb6217d274e6a0797e403b37a1d5527d34f75a`.
The coordinator froze all implementation agents before capturing this checkpoint. No background operation
remained. The old worktree must remain intact; do not reset it, delete it or start a competing writer there.

Use the app's managed worktree operation when available. Otherwise, from the existing successor checkout:

```bash
git fetch origin
git worktree add ../factory-continuation -b codex/factory-continuation origin/codex/successor-foundation
cd ../factory-continuation
git status --short
```

Use a different unused directory/branch if these exist. Do not start from main or the old reference tree.
Read `AGENTS.md`, `CLAUDE.md`, `docs/glossary.md`, `docs/design/tl-8bh9.8.7/plan.md`, and
`docs/design/tl-8bh9.4.3.1.1/plan.md` before source work. The last file is the reviewed current specification.

The previous workspace is `/home/iorlas/.codex/worktrees/successor-foundation/iorlas-task-loop`.
The owner authorized local Git operations and explicitly requested this checkpoint's commit and push.
This handover is not authority to merge/release the factory, edit the person's main checkout, change owner
pins, or publish unrelated library work. Earlier task notes saying publication was unauthorized describe
history; the handover branch publication itself is now authorized.

## Goal and current truth

Umbrella epic to monitor: **tl-8bh9**, whole-codebase redesign and autonomous successor implementation.
Denis wants less code, fewer concepts, one owner per fact, and useful retained behavior. Challenge every
adapter by stating the behavior lost if removed and recommending keep/remove/move/merge with evidence.
No consumers need compatibility. Preserve useful future ideas in tasks/design, not dormant runtime code.

This is a curated successor. The reference is `731b7c76ef214ce35229f77814f98b6e1d6d5c0f`, preserved in
Git history and the original review worktree. No baseline runtime imports, fallback readers or wholesale
old test/bootstrap copying. Foundation completion does not mean a working factory exists.

Currently implemented CLI operations are repository inspection and task inspection only:

```bash
.venv/bin/tl repo inspect PATH --json
.venv/bin/tl task show TASK --backlog NAME --tracker-root PATH --json
```

There is **no usable plan CLI or factory execution loop yet**. Global `tl task ...` is the existing task
actor wrapper, distinct from the installed successor executable `.venv/bin/tl`.

Roadmap order:

1. Foundation and scoped repo/task inspection: locally implemented/reviewed, not merged factory delivery.
2. Shared library prerequisites: actually merged and released, listed below.
3. Current task: one already-admitted plan attempt's registration/session/result capture and collection.
4. Finish first usable plan: admission/claim producer, surviving attempt-process launcher, worktree custody,
   plan Git verification, branch publication, and safe cleanup. These are still integration gaps.
5. Implement → mandatory checks → combined review → land, retrying only unfinished delivery effects.
6. Scheduling, portable asks/answers, hold/unhold, dashboard and evidence through shared operations.
7. Remaining retained behavior/removals, glossary and one-reader enforcement, final cutover acceptance.

## Exact frozen implementation state

Current task: **tl-8bh9.4.3.1.1**, under execution contract **tl-8bh9.4.3.1**.
Last observed status: in_progress, assignee `tl-iorlas-task-loop`; umbrella also in_progress.
Do not close either task because of this checkpoint. Read live state before changing it.

This checkpoint includes previously uncommitted drafts:

| File | State at freeze |
|---|---|
| `src/taskloop/plan_types.py` | 177 lines, syntactically complete draft, unvalidated |
| `src/taskloop/plan_files.py` | 74 lines, syntactically complete draft, unvalidated |
| `src/taskloop/plan_store.py` | 223 lines, syntactically complete draft, unvalidated |
| `tests/plan/test_attempt.py` | 155 lines, initial public behavior tests |
| `pyproject.toml`, `uv.lock` | Released any-agent0.4.0 and sqlite-store0.1.0 dependency pins |
| `justfile`, `tests/rules/test_isolation.py` | Focused selection and dependency isolation updates |

**`src/taskloop/plan.py` has not been written.** Application/session latch/publication/collection body and
composition are absent. These drafts have not passed lint, types, caps, gates or independent source review.
The initial test run failed collection with `ModuleNotFoundError: taskloop.plan`.
Evidence on this same host: `/tmp/factory-plan-attempt-red.log`. That red predates the three source drafts.
No later green run exists for this slice. Earlier 88-test green factory evidence belongs to pre-WIP code.
Do not advertise this checkpoint as working or remove the tests just to obtain green.

The implementer successfully ran lock resolution and isolated noneditable installation:
any-agent0.4.0 and inherited stream-proc0.5.0 resolve `5e4a4a21849e631a055eadb4a66e83be298c1892`;
sqlite-store0.1.0 resolves `18d3164893f95dc82e391a7226652d286d9c4663`.
A redundant direct stream-proc source pin at its older monorepo commit conflicts with any-agent's inherited
workspace source. Keep coherent released sources; do not change a library to hide that integration mistake.

Known unfinished draft risks, explicitly reported by the implementing agent:

- ExecutionFacts currently lacks the normalized native-session snapshot; reconcile with the plan.
- Implement first-pending-ref/conflict handling and bounded nonraising callback publication.
- Refresh publication phase and enforce idempotency/conflict rules.
- Capture returned execution evidence before answer decoding can fail.
- Historical collection must not need active reservation, original input or a remaining deadline.
- PlanStore._load currently takes cwd from reservation. Collect captured results before loading current
  admission; assess immutable cwd storage needed for pending validation retry.
- Tests' callable `.execution.calls` access needs the retained FakeRun variable for typing.
- Add meaningful real-SQL failure, fencing, idempotency, conflicting result and live-ref contracts.

## Current bounded contract

Read the full plan rather than extrapolating from these reminders. Proposed public body is
`PlanAttempts.execute/publish/collect`, with concrete PlanStore and PlanFiles. Existing authoritative
admitted attempt, registered entry and matching held reservation generation authorize execution. A caller
request/dataclass cannot manufacture admission. Three narrow tables: reservation, plan_attempt, plan_execution.

Consume dispatch atomically and call existing `any_agent.run` exactly once. Use existing RunHooks.started
for conditional registration before target exec. Ref callbacks execute on an output pump: publish directly
with bounded nonraising behavior, retain first unaccepted ref in the surviving process, and explicitly
report differing-ref conflict. No callback retry thread, generic lifecycle framework or new finished hook.

Set **unattended=False**: True would stop the agent when its coordinator parent changes. The later surviving
attempt process owns the existing ProcessLock through preparation/execution/cleanup; no lock FD transfer API.

Persist immutable execution evidence and typed facts with `validation_pending` before answer validation.
Then use released decode_answer plus factory PlanAnswer decoding. Keep failed execution separate from a
valid answer, unknown usage separate from zero, and answer validity separate from unresolved custody.
Only normalized Summary.res token/turn data is consumed; do not parse vendor wire formats in factory.

Repeated execute may finish already-recorded pending validation without credentials or another agent call.
Independent collect never executes and does not require credentials, original prompt or unexpired budget.
Identical publication is idempotent; conflicting writes refuse. Secret env/raw argv do not enter the DB.
Raw stdout/stderr/answer/transcripts/errors/artifacts remain files behind their owning reader.

Fresh schema initialization is permitted. Missing/corrupt/incompatible/unavailable execution stores refuse;
no migration, quarantine, automatic deletion, backup, history reconstruction or file fallback. Use the actual
released sqlite-store API and native memory SQLite with the same DDL/SQL. No agent/network/Git under SQL
transactions. This slice never releases reservations or claims plan/task completion.

Not in this task: CLI registration, admission producer, physical surviving launcher, worktree preparation,
Git plan verification/publication, automatic cleanup, retry policy engine or scheduler. No test here proves
universal descendant termination or intact-DB coordinator restart. Unknown custody remains reserved.

## Verification and next execution cycle

Inspect drafts first; resume tests-first implementation with one source writer. Read justfile before running.
Python3.15+, own declared environment, noneditable install, no PYTHONPATH/baseline imports.
After writing application code rebuild before direct tests:

```bash
uv run just prepare
uv run --frozen --no-sync python -I -m pytest -q tests/plan
just check
just test
```

Required focused gates are just check and just test. Do not run the old whole suite or live models.
Independent review must check acceptance, code, actual public library calls and boundaries. A previous review
missed the real Codex fresh-launch gap; root caught it and the owning library was repaired/released. Read the
important call sites rather than accepting model summaries. Keep source≤400 lines/file, functions≤80,
test files≤800. No new Any/cast/ignore escapes. Factory source AND tests have no subprocess/spawn/signal/wait.

Task operations go through global `tl task` actor wrapper (bd-backed), never candidate `.venv/bin/tl`.
Read `tl task show tl-8bh9.4.3.1.1 --json` and confirm the actor in your new worktree. Transfer only this known
handoff claim conditionally using `--if-assignee`/`--if-status`; a guard mismatch requires reinspection, not
force. Do not steal unrelated claims. Dolt/cache access may need a sandbox escalation; direct bd prime can
report read-only LOCK in the sandbox. Do not reinterpret that as database corruption or delete anything.
The injected bd prime no-Git statement is superseded by the owner's explicit local Git and handover authority.
Task closure requires actual delivery, not a local checkpoint or a draft plan.

## Released owning libraries — no repeat release needed

| PR | Release | Merged commit |
|---|---|---|
| shelf#66 | git-porcelain-v0.13.0 | e71d37571192d4ad6a7e95d64ad46c3d9210e1e8 |
| shelf#67 | beads-client-v0.1.0 | 3afd60d8896de8496de8d8f9003510956d67f996 |
| shelf#71 | stream-proc-v0.5.0 + any-agent-v0.2.0 | 824040758e5dd44c751483adcfc3f542059338b7 |
| shelf#72 | process-lock-v0.2.1 | d3d611ca15e07bacbf39727d14174f06bdc59e2a |
| shelf#73 | any-agent-v0.3.0 | 9787eb9fba1025c7808fd310894e18e9fa05cb44 |
| shelf#74 | any-agent-v0.4.0 | 5e4a4a21849e631a055eadb4a66e83be298c1892 |

Links: `https://github.com/yoselabs/shelf/pull/<number>`.
Library tasks closed only after delivery: shelf-4426, shelf-7c34, shelf-7a2v, shelf-a884, shelf-evlp;
bounded factory prerequisite tl-8bh9.4.4.1 is also closed. tl-8bh9.4.5 remains open for actual custody.
any-agent0.3 added strict typed decoding and semantic FakeRun; 0.4 moved fresh/resume semantic Codex
construction into the owning harness and removed LaunchInputs.cli. Do not restore raw CLI fallback.
Registered-start API uses a gated bootstrap and identity before target exec; it is not universal stop proof.
Open shelf-rf1y records an anyllm async cancellation/sealed-cwd cleanup race; do not claim it fixed.

Shelf worktree: `/home/iorlas/Workspaces/wt/shelf-git-porcelain-66`; preserve it and its review branch.
Person's main shelf checkout: `/home/iorlas/Workspaces/shelf`; never hand edit it.
Shelf ADR0027 requires native macOS checks on the actual final tree before merge/release. Factory-only
focused work does not require another full shelf native run. Latest #74 native proof covers candidate
16a182af382e98aa89b9bccf8e6292c850ddd6dd, tree ef88a983bc78ea6803bfa1ca6da8c76938f45ac0:
normal124 passed, full5026 passed/11 skipped,91% coverage; Linux full5024/10 skipped,90.87%.
Correct proof saved `/tmp/shelf-evlp-native-proof-from-mac-session.txt`; user once pasted the older #73
proof by mistake, and coordinator retrieved the correct session report. No repeat verification is needed.
Authorized Mac session is “Clarify prompt 11”, thread01a1be4c-2e9b-7ea3-8132-cdf54eb3808d, hostId local.
Read-thread is available by tool discovery; direct session messaging was unavailable. Do not fabricate a
relay or ask for a rerun of an already verified tree. Same-host published consumer probes remain under
`/tmp/shelf-pr72-published-probe`, `/tmp/shelf-pr73-published-probe`, `/tmp/shelf-pr74-published-probe`.

## Accepted design constraints and navigation

- Task tracker owns requirements/dependencies/questions/linked answers/discussion. Git owns code/plans
  and selected design artifacts. factory.db owns local execution state and reservations; slot records do
  not belong in tracker tasks. Logs/transcripts/artifacts are files, not control-state reconstruction.
- Intact-DB restart reconciles liveness and continues unfinished attempts/sessions. Deliberately discarded
  DB/new PC reevaluates Git + synced tasks and repeats ordinary steps as needed. No recovery framework.
- One reader/owner per fact and one application operation shared by CLI/dashboard/agent. Narrow ports;
  owning shelf semantic fakes. Native Python first even inside libraries; subprocess needs a concrete
  external tool/lifecycle reason. No regex over logs/display text for control or JSON for plain Python calls.
- Mandatory candidate checks, one combined acceptance/code review, compact file-backed feedback, bounded
  repairs. No historical successful-check cache or requestable-check DSL. Fresh feedback agent by default.
- Deterministic task branch task/<task-id>, publish checkpoints before step completion. Linked worktrees
  share Git storage. Merge target into task branch, final squash, push target; no rebase/force push.
  Retry only unfinished side effects. Task closure and publication are real separate required effects.
- Scheduling: explicit automation approval, dependencies, holds and claims. Own priority first, ancestor
  priorities nearest-to-root for ties, P2 padding, natural-ID stable tie-break. No areas/manual queue/epic ordering.
- Pause/Continue means hold/unhold and admitted work drains; immediate Stop deferred. Runtime fixed until
  restart. No initial money/token caps; provisional120 active minutes/task with execution/command limits.
- Prepared slots default, fresh worktrees only explicitly needed. No Git memo cache, migrations, planner
  probes, RAM throttling/keep-awake, host check network isolation or automatic reflection/digest task filing.
- Skills are lightweight explicit setup/maintenance/task/ask helpers, no second scheduler/state owner.
  Do not confuse proposed final hook-retirement scope with blanket permission to remove tracker hooks.
- Preserve exports until task-data recovery coverage is verified. No age-based deletion of worktrees,
  evidence or user data; no killing processes by name, no installed-cache hand edits or owner-pin changes.

Read maps as needed: `docs/design/tl-8bh9/coverage.md`; `.8.7/implementation.md`; `.4.6/` adapter
inventory/removal-challenge; `.13/audit.md` and `files.tsv`; `.1/identity-store-contract.md`,
`.1/configuration-review.md`, `.1/timeouts-workspaces.md`; `.2/lifecycle.md`;
`.3/hierarchical-priority.md`; `.5.1/candidate-checks.md`; `.6.1/balanced-design.md`;
`.7/interaction-contract.md`; `.8/operations.md`; `.9/delivery-publication.md`. Here `.N` abbreviates
`docs/design/tl-8bh9.N`, not a literal relative subfolder. Corrected STORE plan: docs/design/tl-sqd3.26/plan.md.
STORE children .3/.4/.5 are open; owner hold was lifted only for corrected responsibilities.

Gap audit compared baseline731b7c76 to fffbc4e99:2570 baseline paths,2357 deleted,15 modified,52 added,
198 unchanged; zero unchanged surviving production Python. This does not mean every old behavior was
reviewed. All38 old adapters have assessments. Additional cuts in the audit remain proposed unless explicitly
approved; do not treat every audit idea as an owner decision. Current tasks preserve implementation ownership.

Explicit holds remain: FILEVERB tl-w7lt.38.9 (“much later”), REPOOWNER tl-sqd3.23, speculative merge queue,
strict/fast visual review modes, immediate Stop and Windows build. No /tmp cleanup timer approved. pix-dataown
and pix-archvert-a are archived only by Denis. /tmp is RAM-backed; preserve other worktrees/evidence.

Next report should name the branch/commit, current task, behavior implemented, focused gates and independent
review result, and remaining integration gaps. Be candid about unfinished work. Continue bounded work without
reopening settled owner decisions or claiming a working factory before the first real workflow exists.
