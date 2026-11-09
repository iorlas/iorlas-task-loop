# Configuration, profiles and source identity

> STORE scope update, 2026-11-09: Denis accepted the identity/lifecycle contract and lifted its design hold for
> [reconciled STORE slices](../tl-sqd3.26/plan.md) only. Earlier blanket-hold statements below describe prior review history.
> Explicit dependencies still gate affected actions; historical migration/compatibility scope and unrelated holds remain excluded.

Review date: 2026-11-09. Tasks tl-8bh9.1.1 (reads), .1.2 (surface), .1.3 (remove profile approval).
Source review only, no source/config changes or Git operations. Owner accepted the configuration strategy and
removed profile-change approval on 2026-11-09. The additional knob consolidations below retain explicit status.

## What to remove, retain or reassess

| Settings/behavior | Disposition and reason |
|---|---|
| check_links | Remove with approved built-in link-check deletion. |
| areas, area_label_prefix, area_poll, area_say | Remove with approved areas deletion; keep actual workspace exclusion/resource permits. |
| epic_order, epic_only, ordered label, manual queue/queue_at | Remove with accepted native hierarchical priority contract. Keep explicit automation approval and dependencies. |
| Dedicated look_rounds, visual_paths/shot_table and look-stage branches | Retire where solely part of removed visual-review workflow. Retain general screenshots/artifact publication; generic resize behavior, if needed, belongs to that owner rather than a retained look stage. |
| RETIRED_ENGINE/RETIRED_CHECK filtering, _without_retired, _SAID/say_retired | Remove acceptance of ignored old keys and process-global warning memory. Unknown/retired keys fail normal validation; no no-op compatibility shape. |
| Renamed/gone-key message tables | They reject old keys rather than read them, so are not fallback readers. Generic unknown-key errors may replace unnecessary migration-message machinery; preserve useful error paths without accepting old shapes. |
| account_wait_min and EngineConfig.host | No runtime consumer found in reviewed source searches; confirm caller inventory before deleting schema fields/tests/docs. |
| land_queue_max_in_flight and speculative queue settings | Cap appears in schema/validation/tests with no runtime consumer found. Held MQUEUE is not admitted; do not carry dormant future knobs into the curated successor. Do not start or erase others' in-flight work during review. |
| queued_match, lock_fail, slow_cmd, test_pattern, project_log | Existing callers implement scheduling/output guessing and framework-specific diagnostics. Proposed cut/consolidation with mandatory checks, resource permits and OPAQUE-CHECKS work; do not just relocate the heuristics to another profile. |
| requestable/writer/run_checks limits and engine-only command distinctions | Reconcile with agreed mandatory checks and deferred repo tools. Preserve actual permissions until the owning behavior is replaced; no second check-request protocol. |
| review/review_every/skip_review and separate review/fix/replan caps | Reassess against one accepted review+repair policy; no implied activation of parked strict/fast modes or removal of required review. |
| Retry/cooldown/internal poll knobs | One retained retry/wait policy, not knobs for each removed loop. Numeric retry proposal remains unapproved; native execution/timeout limits still needed. |
| Automation approval, task-service binding, integration target/delivery choice | Retain explicit meanings and one owner. Approval cannot disappear because pick_label is empty or a manual queue emptied. |
| Check argv, environment/cwd/setup/input dependencies, deadlines and resource needs | Retain actual repository behavior. Validate through one schema and use shared execution APIs. Cache-specific keys remain conditional on the separate pass-cache decision. |
| Slot concurrency, task budget, host tool/account availability | Retain distinct units with explicit owners; do not confuse number of tasks with number of Unity commands. Machine credentials/actual capacity belong outside a task branch. |
| SSH executor, automatic preparation, reflection, per-label budget/review overrides | Not yet justified for removal by this pass. Verify actual use and user requirement before transferring them into successor. Same-PC state alone does not prove an external build command is unwanted. |

The goal is a setting only when a user/repository needs to choose behavior. An internal constant need not become a
public knob. Similar names do not prove identical meaning: task budget, agent execution deadline and command timeout
can all be necessary, but must not contradict or silently reset one another.

## Real loader disagreement

profile_at already centralizes much of the read/parse behavior. Preserve it where correct; remove competing semantics:

- raw_at/object_of rejects malformed or nonobject committed JSON, and source wraps failure as ProfileReadError.
- doctor.profiles.red_row suppresses JSONDecodeError when source is base; diagnostic_source also turns Git read errors
  into empty text. A bad committed profile can therefore appear healthy to doctor while execution refuses it.
- slots.profile_slots without Git catches read/parse errors and returns default SlotsConfig.
- config.load uses data or {}, allowing some falsey nonobjects through parse paths as empty defaults, while object_of
  explicitly rejects them elsewhere. Validation must begin with a JSON object check, not truthiness.
- CLI wrappers catch ConfigError/print/exit in several places. Edge-specific presentation is legitimate; shared readers
  return the same typed result/error/provenance and must not exit or silently reinterpret it.
- doctor.profiles.stamp traverses Git directory/ref files and hashes/signatures independently. Consolidate retained
  revision observation through shared Git/binding APIs; do not remove cache invalidation merely because it costs code.

Absent/unconfigured, invalid, unreadable and valid-with-defaulted-optional-fields are distinct outcomes. Missing required
factory setup is not permission to run all tasks. Administrative task commands need not require a factory profile.
One pure decoder/validator and one explicit source resolver serve consumers; no new configuration service is needed.

## Decided configuration source strategy

The earlier asynchronous question suggested committed factory policy versus candidate check recipes. Owner requested
an explanation and GitHub Actions comparison instead of accepting that split. No file restore or checkout overwrite
is proposed. Selecting a source means reading a versioned file from a named commit/tree or explicit working-tree input.

Main-only reads would keep using the old check recipe while a task changes .task-loop.json. Candidate reads exercise
the changed recipe with candidate code. Owner accepted a resolved profile snapshot tied to the operation's Git
revision, plus separately owned machine/launch settings. Do not read both versions of the same field opportunistically.

GitHub Actions uses the workflow at the Git revision associated with its triggering event; each run keeps that version.
See [workflow revision selection](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflows).
For ordinary pull_request, workflow and default checkout come from the PR merge commit. pull_request_target instead
uses the base repository default branch. See [the documented distinction](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target).
These are version-selection examples, not a requirement to reproduce GitHub's events/jobs/security machinery locally.

Required behavior, accepted by the owner on 2026-11-09:

- Admission/controller reads the repository configuration at a resolved target-branch revision; a task branch does not
  redefine all other tasks' scheduling or machine capacity while its work is in progress.
- The task operation/checks reads the repository recipe for the exact committed candidate it processes. A changed
  profile is ordinary versioned task content and uses normal checks/review/land, with no special profile approval.
- Each operation freezes its resolved snapshot until that operation ends. Config edits do not mutate limits mid-call.
  At a subsequent step/attempt boundary, resolve the appropriate new revision explicitly; reuse same snapshot for
  validation, execution and displayed source. Integration validation uses the actual integration candidate revision.
- Machine accounts/credentials/actual capacity and explicit launch limits remain owned by local machine/agent/launch
  configuration. Capture admitted budgets/limits in runtime state; candidate edits do not silently enlarge a running grant.
- CLI working-file validation/checking is an explicit local inspection context, not fallback after a committed read failed.
  No base available for a local-only repository must be an explicit source context, not swallowed corruption.

This is the implementation contract, not an open source-precedence choice. Source identity and snapshot lifetime
must be visible through the common resolved profile, not reimplemented by each caller. Existing one-snapshot-per-run
task tl-br2.7 must be reconciled with operation-level source binding and retained normal restart. A resumed live
execution keeps its admitted snapshot/limits; it does not reload them because the factory process restarted.
No redesigned namespace or held STORE implementation is admitted by recording this decision.

## Additional knob menu

Owner accepted one repository target branch, semantic delivery settings, the three limit concepts and the workspace
default on 2026-11-09. Other rows remain concrete proposals unless marked decided. The [timeout/workspace explanation](timeouts-workspaces.md) separates their guarantees.

| Current knobs | Proposed retained behavior | Removal or consolidation |
|---|---|---|
| engine.base and slots.base | Decided: one configured repository integration target; resolve its commit for each relevant operation. | Remove independent slot-base configuration. Slot preparation, checks and delivery use the same repository binding; a pinned commit is an observation, not another target knob. |
| engine.land argv plus land_mode/merge | Decided: semantic delivery push or PR, target remote/branch, and auto/wait integration policy where supported. | Remove raw Git-push argv configuration and its parsing/execution branch. Owning Git library performs Git; do not preserve arbitrary command mode just to retain old shape. Map actual consumers before removing source. |
| review/review_every/skip_review and review-off label | One required acceptance+code review of the candidate before landing under the current retained workflow; changed repair work is reviewed as required. | Remove intermediate sampling/skip policy from successor rather than implement several review products. Future strict/fast modes stay parked and are not silently enabled by this cut. |
| max_rounds/max_check_tries/max_fix_rounds/max_same_red/max_total_reviews/max_replans | One accepted semantic-repair cap, one finite execution allowance and cumulative task budgets, with exact failure outcomes. | Remove overlapping independently reset counters. Retain a distinct planning/task-decomposition limit only for a demonstrated need, not as another retry allowance. New execution retry numbers remain proposed separately. |
| budget_min, run_deadline_min, write_cap_min, node_timeout_min, review_budget_min, check_wall_min, gate_timeout_min | Decided: task budget, agent execution timeout and command timeout. Initial working policy: 120 active minutes per task, no enabled money/token caps; executions and commands inherit remaining time unless explicitly narrower. | Remove overlapping role/phase and independent outer-run policy knobs. Specify units and min-of-remaining enforcement once; preserve execution ownership and cancellation. See the linked timeouts review for accounting and restart rules. |
| gate_tree and CheckSpec.run_in, with gate_source_globs/gate_ignored_allow | Decided: prepared committed slot by default; fresh candidate worktree only when explicitly required. | Remove global gate_tree routing and retain one explicit workspace choice. Preserve necessary candidate integrity and setup guarantees; fresh worktrees are not hermetic environments. |
| requestable/writer/writer_check_max_s, max_run_checks, slow_cmd | Mandatory engine checks plus ordinary focused debugging; deferred repository tools supply explicit capabilities where needed. | Remove request-list/command-guessing machinery after its replacement is settled; preserve actual execution permissions and scarce-tool limits. No new check-admission DSL. |

Keep public settings for actual repository commands, environment/setup, declared resource needs, automation approval,
task budgets and supported delivery behavior. Machine capacity/accounts and credentials keep their local owners.
Internal poll intervals and safety constants need not all be public repository knobs. No speculative cache/SSH/prepare/
reflection feature is carried into the successor solely because a setting exists; assess each through its actual caller.

## Profile approval is removed, not moved

PushJudge.owner_approved currently reads ProfileChange JSONL rows, filters by tip/time within 600 seconds and compares
diff_sha. Stack delivery writes those records. That is live authorization from a log, not merely audit evidence.
Initial proposal was a DB grant; owner rejected that on 2026-11-09 and chose complete removal.

tl-8bh9.1.3 now deletes the special profile-change flags/owner gate/audit authorization model/store/callers/tests.
No replacement grant, special approval workflow or compatibility reader. Configuration edits follow ordinary work.
General owner questions, actual task automation approval, stop/hold and unrelated tool-access controls remain separate.

## Verification and coordination

Read config records/loader, profile_at, slots config/profile_facts, doctor profile diagnostics/stamp, gate authorization,
land stackgate/push_judge, profile-change records/store and selected consumers/default profile/setup generation.
The checked repo profile explicitly sets pick_label auto; the empty schema default is not a claim that this deployment
currently admits unlabeled work. No tests or real profile/permission mutations were run.

Reuse existing feature-removal tasks and PROFILEGEN tl-w7lt.32, AGENT-CONTRACT, retry consolidation, RepoId/Git binding
and held review-mode/STORE/MQUEUE scopes. config.py is shared: plan one writer at a time.
Eventual tests cover identical source results across consumers, malformed committed JSON, nonobjects, absent files,
removed-key refusal, snapshot provenance, ordinary profile delivery and explicit automation eligibility. Normal gates
are just check and just test; no full/live suite is authorized by this design review.


Owner decision 2026-11-09: checks use normal host networking. Remove check_net_isolate and
per-check network bypass fields together with their sandbox-exec/unshare wrappers, discovery probes and
isolation-specific errors. No replacement factory network policy or shelf extraction; harness permissions remain separate.
