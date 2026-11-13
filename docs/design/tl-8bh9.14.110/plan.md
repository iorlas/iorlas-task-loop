# Single-tenant assumptions: configuration and adapter boundaries

Status: proposed, 2026-11-13. Planning only; implementation waits for the owner's yes.
Task: tl-8bh9.14.110. This document proposes the choices below; it does not report delivery.

## Evidence and current scope

The task cites the 16 read-only architecture censuses in session `local_16bd6c79` (Haiku,
2026-11-13, key claims spot-checked). Its scratchpad was not available here. The checked-in
[grilling record](../architecture-review/grilling-record.md), especially its settled tracker
decisions and rounds 23–25, supplies subsequent owner decisions. The original counts are
historical evidence, not acceptance thresholds. Recheck call sites before implementing.

Current source confirms these coupled assumptions:

| Concern | Evidence in this checkout |
|---|---|
| Remote and task branch | `publish.REMOTE`, `prepare.HEADS/REMOTES/name`, and `land_push.REMOTE/MAIN/TRACKING/FETCHED` independently spell `origin`, `task/` and `main`. Collision checks and recovery messages repeat them. |
| Actor | `tracker.ACTOR = taskloop`; admission, advance, checks, round ordering, heartbeat, holds, close and unclaim use it. |
| Commit identity | `git_views.IDENTITY` supplies `task-loop <task-loop@localhost>` to pinned slot views. Land deliberately uses the person's identity instead (`land_summary`, remote-capable views). |
| Profile path and target | `profile.PROFILE_PATH = .task-loop.json`; parsing already accepts a branch-valued `target`, but `check_admit.TARGET` and `named` reject anything except `main`. Land fetches and pushes `main` independently. |
| Tracker details | `task.TaskScope` restricts the adapter to `Literal["beads"]`; `factory_schema` has `CHECK(adapter='beads')`; queries and presentation modules repeat the backend. `land_close` prints backend commands. |
| Harness details | `harness_choice` now has typed choices, provider display and `launchable`; admission/CLI already carry a harness selection. Only Codex can launch. `attempt` still names `CodexHarness`, credentials/access/probes expose its details, and schema defaults name it. |

Correction to the task's shorthand: `land_close` mentions `bd dolt push` in text; it does
not execute it. Preserve owner-managed tracker synchronization. Existing typed harness
selection must be carried forward rather than implementing the audit's older constant anew.

Read the [foundation](../tl-8bh9.8.7/plan.md) and [glossary](../../glossary.md).
Carry bounded behavior from current code, with no baseline runtime imports or fallback.

## Proposed disposition of every assumption

| Assumption | Proposed owner, default and limit |
|---|---|
| Remote `origin` | Configurable repository binding, default `origin`. One remote per task; never discover a replacement or silently use another. Its configured fetch/push URLs remain trusted as the owner set them; do not persist or print URLs. |
| Prefix `task/` | Configurable branch prefix, default `task/`, resolved once for a new task. The version-control slice alone constructs full task refs and detects collisions. |
| Actor `taskloop` | Configurable tracker binding, default `taskloop`. This is an account/claim fact, not the approval label or the task's identity. |
| Slot commit identity | Configurable name and email, default `task-loop` / `task-loop@localhost`. Keep explicit environment enforcement over agent-modified repository config. |
| Land commit identity | Deliberate: continue using the person's configured identity for author and committer. A slot identity override does not change it. |
| Profile filename | Deliberate: keep `.task-loop.json`, one reader and one path constant. It is a repository convention and avoids needing a profile to locate itself. No search, alias, second filename or working-tree fallback. Machine config's existing `--config FILE` remains separate. |
| Land target `main` | Configurable through the existing Git profile `target`, default `main`. Checks and all land modes must honor it, including reconciliation and summaries. |
| `main` as the branch supplying policy | Deliberate for this slice: retain `main` as the policy source and the local start for a new task branch. Changing the land target does not implicitly change either. Automatic-land permission still comes from the profile fetched from the selected remote's `main`, never from task changes or local preferences. With the default binding this is exactly origin's `main`. |
| Beads support | Deliberate: the local Beads adapter remains the only production claim store. Keep the adapter identity column and backlog scoping. Remove backend-specific constraints and wording from consumers; no second backend, remote tracker sync, source import or plugin loader is introduced. |
| Codex support | Deliberate: only the existing Codex adapter is enabled initially. Selection, enablement, model, effort and priority belong to configuration per step. Generic attempt logic must not construct it or know its CLI, credential format, sandbox keys or answer-schema dialect. |

These are reviewable proposals, including the retained conventions. The owner can approve
this plan without authorizing another backend or a new public domain term. Do not treat
the fixed profile path or `main` policy source as accidental restrictions after this work.

## Configuration contract

Use the accepted shared-repository, machine and repository-local tiers, with a small
allow-list of preference keys. Extend the existing config/profile owners, not a parallel
settings service. Proposed keys are `remote`, `branch_prefix`, `tracker_actor`,
`commit_identity` (`name`, `email`), and per-step `agents` entries (harness, model, effort,
enabled, priority). These names and the proposed local filename `.task-loop.local.json`
are part of this proposal, pending the same owner approval.

For preferences, precedence is defaults < shared committed profile < machine binding
override < repository-local preference < an existing explicit command-line override.
Repository preferences are keyed by the existing canonical repo binding; actor overrides
are keyed by tracker adapter/backlog binding. Do not key identity by origin URL or task ID.
Retain existing flag precedence for model/effort/harness. Add no flag for every new key.
Absent configuration preserves defaults; malformed or unsupported supplied configuration
refuses before claims, branch writes or launches, even if a higher tier overrides it.

Shared preferences are read from the immutable local `main` profile when starting a new
task; machine and local files are read at composition. Resolve the remote before fetching
its policy branch: do not attempt to discover a remote by fetching a profile from itself.
Subsequent remote profile reads supply acceptance policy, not a new remote or prefix.
No task commit can redirect transport, replace the actor or modify factory identity.
The repository-local file is read only from the primary checkout, never from a slot; it
must be excluded from task commit paths. Use explicit reader ports for these inputs.

`setup`, `checks`, `required`, `target` and `land` remain Git-profile-only facts. Reject
them in machine/local preference tables. `setup` and checks still come from the commit
under test; the selected target's immutable profile supplies required checks. A profile
show command's explicit refs are inspection inputs, not overrides for execution policy.
Do not migrate JSON/TOML formats or the CLI framework as part of this task.

Validate config edges with pydantic v2, strict unknown-key handling, and explicit typed
internal inputs. Use stdlib enums/classes for closed vocabularies with one codec each.
Remote/prefix/actor/name/email are validated values, not new execution vocabulary. Reject
blank/control-containing values, invalid full refs, escaping or ambiguous prefixes, and
incomplete identities. Normalize a prefix once to the documented trailing-slash form;
validate the complete prefix-plus-task-id ref through the owning version-control API.
Check directory/file ref collisions for both local and advertised remote refs.

Effective config inspection shows values and provenance, without credentials or remote
URLs. Dashboard and CLI consume the same resolved bindings. The new local tier belongs
to this bounded preference resolution only; do not add workflow, scheduling or permission
policy to it. Reuse an owning tier implementation if another task supplies it first.

## Target selection and the one land operation

Checks admission first reads the profile at the pinned local `main` commit, selects its
`target`, and resolves that local branch to an immutable commit. Read required names and
argv digests from that selected target commit. Its profile must declare the same target;
a mismatch refuses rather than following another redirect. Validate required names against
both relevant profiles as today. Store the target branch as well as its observed commit.
A task's own `target` value cannot choose where it lands or weaken required checks.

Land resolves the selected remote from the recorded binding, fetches its `main` profile,
and reads `target` there. It must agree with the checks attempt's recorded target before
making a new candidate. Fetch that exact target branch into its matching remote-tracking
ref and use that commit for required checks and squash construction. Require its profile
to declare the same target. Pin the policy and target observations used for the operation;
do not recursively follow profiles or consult the remote's symbolic default branch.
Policy/target disagreement, a missing branch or an invalid profile produces a typed
refusal with an explanation, before candidate push or tracker close.

Carry the selected remote and target through fetch, advertisement, squash, push,
already-delivered detection, moved-target retry, no-change, withdraw, summary, close reason,
release fencing, gate-change comparison, and dashboard reads. Updating `TARGET` alone is
insufficient. A candidate records its destination; an observed delivery always reconciles
against that recorded destination, even if current preferences or policy later change.
For an undelivered candidate, a changed policy target prevents a new push; never repurpose
that candidate for another branch. Required checks changed at the same target still use
the existing revalidation and gate-acceptance rules.

Keep `land.land` shared by the CLI and round, with the dashboard using owning reads.
`land: manual` stays the default; `auto` is read from fetched remote `main` and lands at
most one task per round. Keep typed task-change refusal holds so they are not retried
every round. Owner messages state the situation and decision in words; do not ask the
owner to run a CLI command. Dashboard reads may report last observed policy as today,
but do not fetch, authorize delivery or infer successful delivery from cached refs.

## Backend boundaries and retained state

The version-control slice owns remote/ref derivation and identity policy; its Git adapter
uses the owning shelf API and structured results. Do not move wrappers merely to justify
subprocesses. Include publication, branch preparation, trailers and squash text consumers,
and the slot naming read of origin metadata; changing a remote never relocates adopted slots.

The task-tracker slice exports neutral task/claim/close/hold results. Move `beads_client`
types, error classification, backend commands, close recovery details and synchronization
explanation into its adapter. Every result supplies a nonempty adapter explanation;
consumers compose situation/decision text without testing backend names or parsing details.
Preserve fenced claim, renewal, unclaim and close using the configured actor at every site.
This includes lapsed-claim pickup and round ordering, not just client construction.

Keep adapter identity in task scope, every store query and uniqueness/fence condition.
Its validated class/codec replaces `Literal["beads"]`, repeated query constants and the
single-value schema CHECK; no default backend identity is synthesized while reading rows.
Wire the sole production adapter explicitly, with its identifier spelling owned there.
Move dependency/product names out of generic CLI/dashboard/hold/land text. Adapter-specific
explanations may describe backend limitations; land still records delivered-but-not-closed
and resumes close alone, and the factory still performs no tracker remote synchronization.

Use the existing `any_agent.Harness` port and typed access requirements. The harness adapter
owns credential lookup, preflight/probe, sandbox flag translation, schema dialect, session
and transcript interpretation. Generic attempts receive the chosen harness/access result;
remove Codex-specific return types, failure kinds and defaults from those consumers.
Configuration decoding and display names belong at adapter edges. Preserve provider,
session, usage and evidence facts already supported by `harness_choice` and storage.
Unknown, disabled or unsupported choices refuse explicitly. Resolve configured eligible
entries by priority before launch; never switch harnesses or accounts inside a running
attempt after an error. This work enables no additional harness or license-selection service.

At initial admission record the effective remote name, full task branch, actor and slot
commit identity with the task's execution facts. Repeats, advances, entry-process relaunch,
publish, release, hold and land use those recorded values. Record the selected target and
chosen agent settings at their owning attempt/candidate boundaries. Entry processes receive
validated structured inputs; they do not reload mutable preferences. New configuration
affects new work; changing an actor never adopts or releases another actor's claim.

Store only execution inputs and pending intents in factory.db, through each slice's store.
Required external actions retain the transactional outbox rule: record intent in a short
transaction, act outside it, then record the observed result. Reconcile claims, refs and
delivery after interruption; do not derive control state from logs or add compensation.
For schema changes drain attempts first, prevent old entry writers, and discard the old
database under the owning upgrade operation. No migration reader, backup/restore, history
reconstruction, fallback or deletion of worktrees/evidence/tracker exports belongs here.

## Bounded implementation sequence after approval

1. Recheck the inventory and overlapping config/VCS/tracker/harness work. Agree the proposed
   fields, precedence and deliberate limits with the owner before source changes. Keep one
   writer per managed worktree and use Beads tasks for implementation tracking.
2. Add preference validation/resolution and typed persisted inputs with focused defaults,
   override and restart contracts. Coordinate the single schema cut with all affected slices.
3. Route preparation/publication and all claim lifecycle consumers through the configured
   bindings; preserve existing ownership, collision, non-force and recovery behavior.
4. Make checks and every land mode target-aware, including policy selection, reconciliation,
   summary and round/dashboard use of the same operation and readers.
5. Confine tracker and harness product details to adapters, replacing generic schema/query
   assumptions. Reuse existing owners; do not create empty abstractions or wholesale packages.
6. Update current README/config examples and relevant glossary behavior descriptions to
   distinguish defaults, deliberate conventions and configurable values; preserve historical
   evidence as historical. Enforce boundaries with focused contracts and review the inventory.

## Acceptance and verification

Use semantic owning fakes and pytest behavior contracts, not tests of every helper. Extend
the existing config/profile, prepare/publish, admission/claim/hold, checks, harness/access,
land/resume/summary and CLI tests in small modules within their caps. Required scenarios:

- Defaults preserve existing behavior. Two independent repo/tracker bindings in one config
  use different remotes, prefixes, actors and identities without leakage; matching task IDs
  in different scopes cannot collide. Invalid values fail before any external mutation.
- With `upstream`, `work/` and `release/stable`, all reads/refspecs/pushes and displayed facts
  use those values. Same-named `origin`, `task/` and `main` delivery refs are decoys. `main`
  still supplies the deliberate policy and task-start roles. Prefix collisions still refuse.
- Slot commits retain the configured enforced identity despite agent config edits; squash
  commits keep the person's identity. Changed preferences across intact-DB restart do not
  redirect publication, close, unclaim or an unfinished candidate. Missing recorded bindings
  refuse safely instead of choosing defaults.
- Non-main checks and land cover required-name/argv changes, gate changes, moved target,
  conflict, remote rejection, delivered-before-record, close-before-record, summary,
  withdraw and no-change. Task profile/local preferences cannot override acceptance policy;
  a changed declared target cannot redirect an existing candidate. A delivered candidate
  finishes its outstanding close even after preferences change.
- Configured actor fencing covers claim, renew, repeat/advance, holds, close and release;
  another actor is never treated as ours. Neutral tracker results always carry explanations,
  including locally closed but unsynchronized delivery, without executing a sync.
- Configured harness selection and priority reach generic launch ports. Disabled/unknown
  choices never launch; a neutral semantic harness fake exercises the consumer without
  Codex assumptions. Adapter tests protect existing sandbox boundaries, credentials, schema,
  usage and session handling; no live agent or login probe is required by the focused gates.
- Import/AST contracts reject backend imports, product-specific result branches and repeated
  default identities outside owning adapter/config edges. Inventory remaining occurrences
  by ownership rather than requiring historical docs or adapter explanations to lose names.

Use the existing real-Git temp-repository contracts only for changed transport/ref/identity
behavior; no live tracker, remote service, whole-repository or baseline suite. Tests import
their slice and small shared types; use owning shelf fakes rather than a second fake backend.

Read `justfile`, run `just install`, then focused affected tests using
`uv run --frozen --no-sync python -I -m pytest ...`. Invoke executable checks with
`uv run --frozen --no-sync python -I -m taskloop ...`. Finish with required `just check`
and `just test` (the declared `tests/cli tests/steps tests/rules` gate), Python 3.15+,
no baseline editable installation or PYTHONPATH. Keep 400 source lines/file, 80/function
and 800/test file; introduce no Any/cast/ignore escape or factory process/signal escape.

Completion requires observable configured behavior plus an explicit record/test of every
deliberate limit in the disposition table. This planning change runs no implementation
gates and does not claim the task or foundation's later factory work is implemented.
