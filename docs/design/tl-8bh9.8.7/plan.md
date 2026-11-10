# Minimal successor foundation

Task: tl-8bh9.8.7. Prepared 2026-11-09 after the owner requested autonomous implementation cycles.
This is a reviewed implementation specification, not a delivery receipt.

Update, 2026-11-09: the owner authorized local Git operations. The separate successor worktree/branch and exact
baseline are now recorded in [implementation provenance](implementation.md); the earlier authority restriction
below describes preparation history. No remote publication is authorized by that local permission.

## Execution model

One coordinator selects a bounded task and retains the decisions/context. One implementing agent owns source
writes; a different reviewer checks acceptance and code. Checks are deterministic required operations. Repair
returns concrete failures and evidence paths under the accepted finite retry policy. Delivery and task closure
remain separate required effects. Additional agents may read/review independent concerns; do not create another
scheduler, task database, orchestration service or mini-factory as a bootstrap prerequisite.

The first CLI task flow will later execute subsequent factory tasks through this same cycle. Foundation alone
is not a working task factory and must never be presented as one.

## Boundary before source construction

Use the accepted isolated managed successor worktree/branch, with the exact reference baseline recorded when
implementation starts. Preserve and account for the uncommitted review documents/instruction edits in the current
review worktree. Carry their relevant design/constraints deliberately; do not modify the person's main checkout.
Do not create a nested successor directory or silently repurpose the frozen review tree to evade this boundary.

The injected bd prime context currently says: "Git authority: no git operations in this context" and
"Git workflow: stealth mode (no git ops)". Therefore successor worktree provisioning, baseline Git inspection
and unchanged Git-based affected-selection tools cannot run yet. This is an authority prerequisite, not evidence
that the source task is complete. No Git metadata manipulation is an alternative.

Once local Git authority is available, inspect attached worktrees and reuse a suitable isolated successor if one
exists; otherwise provision a managed worktree using the normal tool. Prefer the codex/ branch prefix. Record
actual baseline/provenance rather than inventing a revision from the earlier adapter source hashes. Recheck
relevant source differences before carry-over; the audit's file/line evidence is not a fetched-main guarantee.

## First source shape

Keep the production namespace `src/taskloop/`. The minimal shape is package initialization, executable entry,
CLI parsing and an explicit composition entry point. Collapse unnecessary modules rather than add empty layers.
No new kernel, generic operation interface, plugin registry, scheduler, STORE schema or placeholder task flow.

Provide real CLI help and deterministic nonzero rejection of invalid/unsupported commands with useful stderr.
Do not register plan/implement/check/review/land commands until each has real behavior and completion criteria.
Exception (owner, 2026-11-10, [.4.3.1.6](../tl-8bh9.4.3.1.6/plan.md) section 2), for that surface only: `tl plan
start/show/list/verify` (and the `abandon` placeholder) are registered before the plan step is complete; root and
`tl plan` help say "attempt only: no task branch, publication or release"; `tl plan` alone still exits 2. Since
[.4.3.1.12](../tl-8bh9.4.3.1.12/plan.md) the wording is "plan step only: publishes task/<id>; no merge or land".
`tl plan next` ([.4.3.1.13](../tl-8bh9.4.3.1.13/plan.md), one scheduling round for the plan step) joins the registered
plan surface under the same exception and wording.
`tl plan rounds` ([.4.3.1.14](../tl-8bh9.4.3.1.14/plan.md), rounds one after another in a foreground process until
Ctrl-C) joins it under the same exception and wording.
The foundation is explicitly the exception that establishes build/executable boundaries before the first full slice.

Retain Python 3.15 and existing tool pins/policies. Add no runtime dependency or semantic fake before an actual
application operation needs its mechanism. Shared Git/process/agent/task fakes must come from their owning
libraries when introduced; do not copy competing local fakes into the successor.

## Build and test boundary

Provide `just check` and `just test` for the successor, with retained lint/type/import rules and 400/80/800 caps.
Use its own declared environment and source root. Old editable installs/PYTHONPATH cannot make missing successor
imports appear to work. Do not copy baseline test/bootstrap/runners merely to retain familiar command spelling.

Current coupling, source-checked during planning:

- `tests/conftest.py` eagerly imports baseline modules, adapters/kernel and declares legacy STORE parts.
- `packages/testkit` depends on tlkernel; do not pull that graph into a minimal foundation. Coordinate shared kit
  extraction through tl-z6np / shelf-69pz only for mechanisms actually needed.
- `dev/runtests.py` loads kernel scratch code by file path and imports vendored process machinery.
- `dev/affected.py` and changed-file/static ratchets invoke Git, so their unchanged invocation violates current
  session authority. Reuse policy and independent helpers, not old orchestration wholesale.

Focused verification proves CLI help/invalid syntax, executable wiring, production-module import provenance,
source isolation, declared dependencies and applicable static caps. Use in-process checks for parsing/presentation;
one real-layer launcher check proves actual entry wiring. No process fake is required just to test an executable.
Introduce architecture rules for real boundaries, not empty future layers. No agent whole-suite/live run.

## Completion

The isolated successor has an executable truthful CLI, independently runnable focused gates and no baseline
runtime dependency/fallback. Baseline/provenance and transferred review changes are accounted for. An independent
reviewer checks both observable behavior and import/test isolation. Delivery is subject to actual Git authority;
source/task completion is not claimed from this plan alone.

Next implementation concerns remain bounded owners from the coverage map: identity/binding, task claim/admission,
slot custody, actual attempt and committed plan, code publication, checks/review and resumable settlement. Add only
the STORE fields and shared APIs needed for that complete first task flow, not the whole backlog first.
