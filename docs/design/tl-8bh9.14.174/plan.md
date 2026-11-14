+++
prepared_commit = "fadd771c8bc23f38e2be75f114e0bd8be945b782"
cited_paths = [
  "src/taskloop/admit.py",
  "src/taskloop/admit_rows.py",
  "src/taskloop/admit_chain.py",
  "src/taskloop/operations.py",
  "src/taskloop/task.py",
  "src/taskloop/tracker.py",
  "src/taskloop/tracker_client.py",
  "src/taskloop/plan_step.py",
  "src/taskloop/implement_step.py",
  "src/taskloop/prepare.py",
  "src/taskloop/attempt_reads.py",
  "src/taskloop/factory_schema.py",
  "src/taskloop/check_repeat/store.py",
  "src/taskloop/round.py",
  "src/taskloop/hold_status.py",
  "src/taskloop/hold.py",
  "src/taskloop/wip.py",
  "src/taskloop/evidence_files.py",
  "tests/steps/test_admit.py",
  "tests/steps/test_round_holds.py",
  "tests/steps/round_bench.py",
  "pyproject.toml",
  "uv.lock",
  "justfile",
]
+++

# Reuse a committed plan after a hold

Task: `tl-8bh9.14.174`. Prepared 2026-11-14 against the commit above.
This is an implementation specification, including the owner's cheap-check
addendum. Reuse requires every condition below; equal task text alone is
insufficient. Expected savings of 2.9% describe the reported sample, not a new
performance guarantee.

## Current behavior and branch assessment

`operations._current` returns to fresh admission after a settled abandon.
`AttemptAdmission._prepare` renders `FIRST` and `_commit` always stores that
step, currently plan. `operations._admit` also selects plan agent settings
before admission. Consequently answering an implement hold creates another
plan attempt even when a verified plan remains on the branch.

`input_digest` is the SHA-256 of the entire input artifact, including the
step's instructions and repeat feedback. Preserve its artifact-integrity
meaning. `TaskInspection` and `tracker.inspect_task` currently include title,
description and acceptance but omit discussion; hashing today's input cannot
meet the discussion requirement. Discussion already has owning readers in
`tracker_client` and `tracker`; reuse those rather than read tracker files.

The branch is at the prepared commit, with no task-specific commits or WIP
for `.174`. The inherited WIP trailer inside squash `78696b90` belongs to
`.160`; its settings changes are existing inputs, not unfinished work for this
task. Preserve them. No source changes are part of this planning step.

## Task content and durable evidence

Add one canonical task-content projection and SHA-256 codec shared by admission
and prompt construction. Include title, complete requirements and acceptance,
task design/notes carrying requirements, and ordered substantive discussion
including questions and linked answers. Include dependency information given
to the agent without volatile execution/status fields. The agent must see the
same content whose digest is stored. Fetch discussion through the tracker
adapter; this task supplies the required bounded input plumbing even if the
separate comments task has not landed. Do not silently truncate content for
hashing or give the agent less substantive text than the digest represents.

Exclude labels, status, assignee, leases, timestamps, factory hold comments
and explicitly marked supervisor operational annotations. Changing these
must not invalidate a plan. Preserve human decisions, including decisions
relayed by the supervisor. An owner request for another plan is recorded as
substantive tracker discussion and therefore invalidates reuse; no model
classification of requests or new CLI command is needed.

Use explicit provenance at the tracker boundary for exclusions. Introduce and
document exact paired markers for supervisor-only operational paragraphs,
`<!-- taskloop-supervisor-operation -->` and
`<!-- /taskloop-supervisor-operation -->`; remove only well-formed complete
marked regions from canonical content. Requeue annotations use this convention;
requirements and owner answers stay outside it. Keep exclusions in one codec,
with the factory's known generated hold-comment format handled by its adapter.
Do not drop all comments by an actor, paragraphs containing 'supervisor', or
unmarked text. Unrecognized historical prose is substantive, conservatively
causing planning once rather than risking an ignored requirement.

Store a separate `task_digest` with each agent attempt in factory.db. Admission
hashes its typed content snapshot before rendering instructions; a repeat
copies its source digest, because it sees the original input plus feedback.
Advance and check-driven repeat writers must supply the correct snapshot or
copy it with their original-input semantics. Never reinterpret `input_digest`
or reconstruct digests from logs, old prompts or Git after database discard.
Use pydantic v2 for new boundary models and stdlib enums with one codec for
any new closed decision vocabulary.

## Plan metadata and deterministic Git check

Require newly prepared/revised plans to open with a bounded TOML block between
exact `+++` lines, as this plan does. Its `prepared_commit` is a full commit ID
the agent inspected; `cited_paths` lists repository-relative technical input
files/directories on which its decisions depend. It includes prose citations
that inform implementation, but excludes the plan's own output files. Update
the plan prompt to require complete citations and the inspected commit. Keep
the answer schema unchanged. Parse only this structured block with `tomllib`
and a strict pydantic model, never regex over plan prose. Reject unsafe paths,
Git pathspec magic, traversal, duplicate/oversized entries and invalid revisions.
Require a nonempty, bounded citation list. Directory citations cover descendants.

A plan without usable metadata can still be verified as an ordinary plan, but
is ineligible for automatic reuse. Never guess metadata from an older plan's
English introduction or manufacture it through a model verification call.

For reuse, resolve the task branch using the existing local-then-origin
remote-tracking precedence and pin its tip H; HEAD means the task branch's
prospective HEAD, not the parked slot or the person's checkout. Require:

1. This is reingestion after a finished factory hold and settled abandon, with
   the existing answer/approval checks satisfied. Ordinary fresh tasks and
   hand abandons retain their existing start behavior. Do not require
   `cleared_at`: `round._cleared` runs after replacement admission.
2. The latest plan attempt for this task/backlog/repository has a verified
   successful `planned` or `unchanged` answer and its stored task digest equals
   the current content digest. Never fall back past a later failed plan.
3. H contains that plan attempt's end commit and the committed plan at H has
   the same blob as its verification. Missing, replaced, symlinked or otherwise
   invalid plans cannot be reused. A WIP-only plan is not a successful result.
4. The metadata's prepared commit exists and is an ancestor of H. One bounded
   path-scoped Git statistics read between it and H reports no change under
   the cited paths, including binary, mode, addition, removal and rename effects.
5. History reachable from H but not the prepared commit contains no commit
   with the existing `Task-Loop-Wip:` trailer. Previously inspected WIP commits
   reachable from the prepared commit do not invalidate reuse.

Check the digest before Git work. Uncited changes alone do not invalidate
reuse, but any new WIP does. A complete negative result selects plan with an
explanation; an unavailable tracker/Git/store read reports the existing typed
unavailability and launches nothing. Missing evidence never means unchanged.

The pinned shelf `Repo.history(..., not_on=...)` supplies the history check.
Its current `Repo.diff(..., exclude=..., cap=0)` lacks positive path selection
and still computes statistics for the whole repository. Add the narrowly
needed path-scoped statistics operation to owning shelf Git real/fake APIs,
then pin its released version here through the normal shelf workflow. The
adapter implements the requested single `git diff --stat <commit>..H -- <cited
paths>` check with typed results; no patch generation, display-text parsing,
factory subprocess escape or generic command runner. A native Git-object
implementation is acceptable inside that owner if it provides the same
bounded change semantics. Treat the shelf release as a concrete prerequisite,
not as an already available API or permission for unrelated dependency work.

## Admission, launch and restart

Put the selection in one small plan-reuse use case, with its own evidence
reader/store and narrow tracker/Git ports. CLI start and rounds call it through
the existing shared admission operation. SQL stays with owning stores.
Return a typed decision carrying the source plan attempt, digest, plan blob,
checked H and an explanation; no synthetic plan attempt or model call.

Refactor admission to choose the step before rendering its prompt and resolving
agent settings. A reusable plan admits implement attempt 1 with the next task
`seq`, a fresh reservation generation and the implement harness/model/access
settings plus current overrides. Store `after_commit=H` and a nullable source
plan-attempt link for this admission. Preserve the original plan attempt and
all held attempts. Update all attempt insert/load paths and invariants together;
the existing first-implement `after_commit` constraint must continue to hold.

Under the admission write lock recheck the current abandoned attempt, finished
hold, source plan evidence and reservation fences. Git/tracker reads and effects
stay outside write transactions. Existing claim intent/action/result handling
remains authoritative. At entry, under slot ownership, verify that the branch
actually taken is exactly checked H before launching implement; ancestry alone
does not validate newly added descendants. Ref movement refuses with the
existing generic explanation and normal release/hold handling, without launching
an agent or discarding changes. A later admission makes a fresh decision.

Persist the digest and source-plan link atomically with admission. Relaunch of
that admitted attempt and intact-DB restart use its recorded step and choices;
they must never create another plan. Schema changes increment the current
version (21 here); drain old attempts before the owning discard/upgrade. No
migration, backup, compatibility reader or Git-history state reconstruction.
A deliberately discarded DB has no trusted digest evidence and plans normally.

## Focused verification and completion

Add pytest behavior tests using owning shelf semantic fakes and existing
admission/round benches. Split new tests to preserve 400/80/800 line caps.

- Reproduce a verified plan, implement `schema_invalid` hold, answer/reapprove,
  and resume: equal content with unchanged citations and no new WIP launches
  implement directly. Repeat a second hold/answer with no saved changes; the
  plan-attempt count remains one and round moves contain no `plan start`.
- Change requirements, acceptance, human discussion, linked answers or an
  explicit owner replan request: the next admitted step is plan. Labels,
  generated hold comments and marked operational supervisor paragraphs alone
  leave the digest equal; substantive supervisor-relayed decisions change it.
- A new WIP forces plan even for uncited edits; a revised successful plan
  prepared against that WIP permits reuse on the next unchanged resume.
  Cover cited changes, directories, binary/mode/deletion/rename changes,
  uncited-only changes, changed plan blobs, missing/invalid metadata, missing
  or unrelated prepared commits, and a later unsuccessful plan.
- Assert zero plan-agent calls on reuse, one path-scoped statistics operation,
  correct implement settings/input/after_commit, no duplicate admission in a
  race, unfinished holds still blocked, and branch movement before entry
  launches nothing. Cold DB, manual abandon and ordinary first admission plan.
- Reopen an intact database after reuse admission and after an interrupted
  entry: continue the same implement attempt without another plan or claim.
  Cover claim/reservation race fences and rejection by older schema readers.

Read the justfile, run `just install` and `just check`, then the relevant
installed-package pytest selections from `just test` via
`uv run --frozen --no-sync python -I -m pytest -q <focused files>`.
`just test` currently selects all CLI/steps/rules tests; the prohibition on
agent whole-suite/live runs takes precedence. Record the focused selection and
leave the full aggregate gate to its authorized runner. Verify shelf real/fake
contracts in its owning change. This docs-only planning step runs no code gates.

Completion is the observed hold/answer sequence admitting implement with no
intervening plan attempt when every check passes, and admitting plan when any
invalidation is present. The implement agent still reads the committed plan and
may answer `needs_owner` if repository changes make it unsuitable. No new
scheduler, dashboard control or glossary term is required.
