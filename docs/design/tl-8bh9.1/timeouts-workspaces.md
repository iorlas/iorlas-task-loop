# Time limits and check workspaces

> STORE scope update, 2026-11-09: Denis accepted the identity/lifecycle contract and lifted its design hold for
> [reconciled STORE slices](../tl-sqd3.26/plan.md) only. Earlier blanket-hold statements below describe prior review history.
> Explicit dependencies still gate affected actions; historical migration/compatibility scope and unrelated holds remain excluded.

Review 2026-11-09. Owner accepted the three limit concepts and prepared-slot default with fresh worktrees only when
explicitly required, then requested an initially untuned budget policy and approximately two hours per task.
Selected initial working policy after the requested Astra check is recorded below. Source remains unchanged.

## Accepted decisions and initial working policy

Retain exactly task budget, agent-execution timeout and command timeout as distinct concepts. Prepared committed
task slot is the default check workspace; fresh candidate worktree is used only when explicitly required. Remove
overlapping factory timeout knobs and global gate_tree routing in the owning implementation tasks; this review
does not modify source. Shared-agent liveness handling and workspace/candidate integrity remain required.

Owner does not want spending/token budgets configured before real operating evidence exists. Initial working policy:

- Set a provisional task time allowance of 120 active minutes, following the owner's approximately two-hour suggestion.
  Do not treat this initial value as a calibrated long-term budget.
- Dollar and token caps are disabled/unset initially. Report available usage/cost with its known/estimated/unknown
  meaning for later analysis; missing usage is not zero. Existing provider capacity/credit restrictions still apply.
- Agent executions and commands inherit the remaining task time unless an explicit narrower timeout is supplied.
  Do not invent initial role-specific timeout values or another set of price forecasts/reservations.
- Omitted timeout means inherit. Explicit timeout values must be positive and finite; zero/negative is invalid.
  Zero remaining task allowance means no dispatch. Effective limit is the smallest applicable remaining bound.
- Active time is elapsed task-working time including preparation, planning, implementation, checks and review.
  Parallel work counts elapsed time once, while actual usage includes every execution. Exclude only explicit
  whole-task waits when no owned workload is active. An agent still executing while awaiting an internal tool retains
  its execution deadline; a waiting parallel branch does not exempt other active work.
- Record consumed time and actual execution identity in existing runtime state. Normal restart/resume does not
  replenish allowance. Uncertain execution intervals are reconciled before replacement; unknown elapsed work is
  not silently counted as zero. Preserve required ownership until termination/handoff is established.

These inheritance defaults were validated by Astra as the smallest initial policy; the owner accepted the concepts
and workspace choice, suggested the provisional task allowance and explicitly requested no initial cost-budget setup.
The tradeoff is deliberate: a command can use nearly the entire remaining two hours. Inheritance gives an upper bound,
not fast hang detection or tuned per-tool timing. Add narrower overrides when a concrete command/step requires them.
Nested execution/cancellation uses the owning library/tool capability; unsupported hard guarantees remain explicit.

## Limits measure different things

| Guarantee | Meaning | Retained need |
|---|---|---|
| Task budget | Cumulative allowed usage/cost and active task time across attempts and repairs. | Yes. Retrying or restarting does not reset it. Actual agent usage always counts. |
| Agent execution timeout | Maximum duration of an actual harness execution. | Yes. Useful when an execution is unproductive or never returns; enforced through shared agent interface. |
| Command timeout | Maximum duration for a check/tool command the factory/tool server owns. | Yes. A Unity run may legitimately be much longer than a linter. |
| Silence/activity watchdog | Detect protocol/harness stalls using known activity semantics. | Shared agent/process owner where supported, not a separate factory interpretation of console silence. |
| Whole engine-process wall deadline | Outer deadline measured for one coordinator process, currently 45 min by default. | Proposed removal as a separate user-facing policy if task/operation limits cover its legitimate purpose. Do not remove stop/cancel or deadline propagation. |

Current defaults include budget_min 180, write_cap_min 120 and run_deadline_min 45. Lifecycle wraps the run body in
the outer deadline; the deadline adapter clamps child waits/timeouts to remaining time. The longer settings therefore
do not mean a writer can run for 120 minutes inside that ordinary 45-minute coordinator scope. Direct CLI checks can
have a different enclosing context. This is an actual layering issue, not proof that all three guarantees are identical.

WorkerCall.limits separately maps write to write_cap_min/write_idle_min, read-only roles to review_budget_min, and other
roles to node_timeout_min. Gate wall_limit chooses a check's own wall_min, otherwise check_wall_min or gate_timeout_min
depending on phase. gate_timeout_min is a per-command gate default, not an aggregate deadline on the complete gate.

## Recommended smaller limit contract

- One task budget across its execution attempts and workflow repairs, plus its admitted usage/cost allowance.
- One agent-execution timeout concept, with a default and explicit step overrides only where useful. Shared interface
  owns enforcement/liveness details; no factory-specific writer-silence inference.
- One command-timeout default with per-command override. Same check does not acquire a different default merely
  because an old engine path calls it stage versus gate.
- Use the smallest applicable remaining limit. Example: 20 minutes of active task budget remain, a command allows
  60 minutes, and no other tighter limit applies: dispatch is limited to 20 minutes. No allowance is reset by retry.
- Explicit whole-task waits for capacity/owner input do not consume active-work time or create agent attempts.
  Time is not exempt merely because one parallel command waits while other task execution still works; actual
  model/tool usage is always accounted. An actual execution's wall deadline is a different measurement.
- Preserve distinct outcomes for task-budget exhaustion, execution timeout, command timeout, cancellation and known
  unavailable capacity. Do not report every timeout as a test defect or automatically rerun until green.
- Remove independent whole-process run_deadline policy, phase-specific duplicate timeout names and per-role
  watchdog knobs only after their retained enforcement is covered. Keep one deadline/remaining-time mechanism,
  not multiple task budget implementations or a new watchdog service.

The three limit concepts and consolidation are now accepted. Exact successor field names follow the single-owner
contract, with initial values/inheritance above. Current numeric retry proposal remains separate and is not silently
approved by the two-hour task allowance.

## Workspace options

| Choice | What it proves | Cost/limit |
|---|---|---|
| Reused task slot at committed candidate | Checks ran against committed task code with that slot's actual setup/cache state. | Fast for Unity and similar tools; old ignored/generated files can influence behavior. |
| Fresh detached worktree at candidate | Checks do not rely on that slot's untracked/ignored leftovers. | May require setup/import/build again; shared tool caches/environment can still influence it. |

A Git worktree is not a fresh OS/toolchain environment. A fresh checkout shares Git storage and can still use global
packages/tool caches. Reproducibility requirements must be established by repository checks/tooling rather than
claimed from worktree creation alone. Both choices require exclusive ownership and known candidate identity.

Current gate_tree selects global clean/slot behavior. CheckSpec.run_in can route a check from an isolated gate back
to the prepared slot. guard_slot checks committed HEAD and uses gate_source_globs/gate_ignored_allow to look for
ignored source. This is a heuristic guarantee, not proof of a clean build. clean_tree creates a temporary detached
worktree at the same SHA with no slot files copied into it; it does not run slot setup in that helper itself.

## Recommended workspace simplification

Retain one explicit check-workspace choice with two meanings: prepared candidate slot or fresh candidate worktree.
Use the prepared slot by default as accepted by the owner; a repository requests fresh validation when needed.
This does not turn resource permits into workspace selection.

Remove the overlapping global gate_tree override rather than let it silently change a per-check choice. Resolve the
workspace once, execute through the same check runner and associate evidence with the actual candidate/environment.
If a fresh worktree is requested, setup must succeed there before validation; no silent fallback to the warm slot.

Retain dirty-work preservation, committed candidate verification, exclusive workspace ownership, command/resource
limits and evidence outside the reusable workspace. Do not clean by deleting arbitrary ignored/untracked files.
Repository tooling owns cleaning/rebuilding its generated outputs when that is the check's required meaning.

Assess removal of extension-based ignored-source heuristics after this policy is chosen. They currently protect
something real, so do not claim reused-slot checks have fresh-checkout guarantees after merely removing a guard.
Fresh validation stays available for a meaningful required case, not as an automatic duplicate of every check pass.
Generic pass-cache retention/removal remains the separate CHECK-EXECUTION decision.

## Evidence and validation

Read lifecycle deadline scope, worker limit mapping, Budget/PhaseClock use, deadline adapter, gate wall_limit,
runner routing, Executor slot handoff, clean_tree and guard_slot. No behavior tests, external tools or Git operations
were run. Proposed policy needs focused fake-backed tests for limit precedence, quiet long commands, cancellation,
known waits, candidate/setup identity, requested-fresh failure, dirty work preservation and both workspace choices.
Existing AGENT-CONTRACT, retry, CHECK-EXECUTION and PROFILE-SURFACE tasks own implementation; STORE remains held.
