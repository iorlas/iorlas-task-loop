# Curated replacement and cutover

> STORE scope update, 2026-11-09: Denis accepted the identity/lifecycle contract and lifted its design hold for
> [reconciled STORE slices](../tl-sqd3.26/plan.md) only. Earlier blanket-hold statements below describe prior review history.
> Explicit dependencies still gate affected actions; historical migration/compatibility scope and unrelated holds remain excluded.

Task: tl-8bh9.8.2. Working strategy selected after the owner's requested Astra consultation, 2026-11-08.
Design only. No replacement source tree, worktree, branch, release route or runtime was created or changed.

## Strategy

Build one successor in an isolated managed worktree/branch from a minimal build/test skeleton. Bring over only code
that serves agreed retained behavior, concern by concern through bounded tasks. Reuse proven shelf mechanisms and
behavioral contracts; redesign their composition where the current application mixes ownership or duplicates policy.
This is a controlled reduction of the existing product, not a mandate to invent it again or copy old packages wholesale.

When implementation begins, record the exact reference baseline commit and account for relevant uncommitted work.
Git retains the old source for comparison. The old release may remain usable during construction, but the successor
never imports the baseline tree, routes unsupported requests into it, or ships both versions behind a flag.
Keep one maintained successor, not an indefinitely supported parallel implementation or a legacy folder in the new tree.

## Admission of code into the successor

Each task names the retained user/agent behavior, its owning application operation, the existing source/contract it
reuses, and the obsolete owner it removes. Complete a reachable vertical slice, including relevant failure behavior
and fake-backed verification. A disconnected controller or happy-path stub does not complete the promised operation.
An initial build/test foundation task is explicitly a foundation, not a claim that the whole product already works.

CLI, dashboard and agent consumers reuse the same application operations. Presentation and transport stay at their
edges. Shared libraries own generic Git/process/agent mechanisms and fakes; native Python is preferred even there.
Do not copy the old central kernel, all fixtures or an entire package merely because one useful function imports it.
Move the minimal retained contract with its actual owner and remove dependency cycles rather than add a facade.

Preserve tests for retained behavior and meaningful failure cases. Retire tests that enforce removed features or
old private composition. Do not require the old test suite unchanged or recreate old behavior solely to make it pass.
Keep required architecture/gate checks applicable to the new tree, including shared fakes and no factory subprocess.
Library changes remain owned/validated in shelf and enter through normal package/vendor tooling, not hand-edited copies.

## Removal and completion rules

Once a behavior has its retained owner in the successor, the superseded owner and its production callers are absent
in that same change. No legacy imports, fallback readers, disabled obsolete branches or unfinished stubs on a route
declared complete. Do not retain an unused abstraction for a speculative future feature.

Before cutover, demonstrate the agreed product workflow end to end, not every historical feature:

- Explicit automation approval/dependencies/holds/claims, accepted priority ordering, slot/workspace/resource safety.
- Plan -> implement -> checks -> review -> land, with feedback/conflict returning to implementation under bounded policy.
- Task-associated questions/responses, actual attempts/sessions/usage, and retained artifacts/conversations.
- Selected attempt's recent ten actions followed by live updates, with full retained history accessible.
- Normal intact-DB restart, including same unfinished worker/session and unresolved dispatch/liveness.
- Unavailable capacity and owner waits without hidden launches; deterministic task/step completion and unsettled effects.
- Deliberate runtime-DB discard/new PC starts normal workflow from Git/work tasks, without history reconstruction.

Required just check and just test pass on the successor. Do not run full/live suites as an agent.
Cutover replaces the maintained production tree/entry points directly; no temporary runtime compatibility bridge.
The former implementation remains in Git history, not as inactive source shipped with the successor.
Cutover does not require implementing parked features, including review modes, FILEVERB or speculative merge queue.
Correction, 2026-11-09: STORE ownership is now accepted for the corrected slices in ../tl-sqd3.26/plan.md.
Their explicit prerequisites still apply; old migration/compatibility work and unrelated held features are excluded.

## What to do with code left behind

Use the baseline to account for old concerns: retained/transferred, deliberately removed, or a worthwhile deferred idea.
The concern map is design evidence linked to tasks, not another task-status database or an evergreen TODO checklist.
Do not automatically create a task for every leftover helper. Git already preserves the implementation.

For an idea worth retaining, reuse or create a held/deferred task containing concrete user benefit, why it is deferred,
an observable revisit trigger, and the relevant baseline/design reference. Use a spike for a specific unresolved question.
No copied dormant code is needed. No promise that the old mechanism or API will be adopted when the idea is revisited.

Never delete user worktrees, uncommitted work, existing tasks or retained evidence merely to make the new source tree
look clean. Code retirement and user-data retention are separate decisions.

## Self-attack and limits

Risk: a clean tree turns into a broad rewrite that reproduces bugs and never reaches delivery. Countermeasure: reuse
tested mechanisms and complete bounded behavioral slices, with the finite agreed cutover list above.
Risk: two implementations survive indefinitely. Countermeasure: no baseline runtime dependency and same-change
removal of competing ownership inside the successor; old source is a frozen reference only.
Risk: copying tests imports the whole old graph. Countermeasure: preserve behavior/assertions and shared-library
contracts, not fixture architecture. Risk: every discarded module becomes backlog clutter. Capture justified ideas only.

Astra challenged this strategy together with retry consolidation. The companion
[retry plan](../tl-7i9k.56.1/plan.md) records one factory admission policy with library-owned execution/format repair.
This document is implementation strategy, not a claim of source changes or complete architectural acceptance.


## Foundation and final reconciliation

The design scope is recorded here; tl-8bh9.8.7 owns the later minimal source foundation.
[Final coverage](../tl-8bh9/coverage.md) maps successor obligations, remaining evidence gaps and integration order.
No source construction took place during this review.
