# Hooks and cleanup

Task: tl-8bh9.8. Source review and two Astra consultations, 2026-11-09. No Git operation, service
restart, prune, source edit or implementation test was performed. Findings refer to current source/vendor, not latest shelf HEAD.

## Version strategy removed

Owner, 2026-11-12: the factory does not manage its own versions, installs, pins or releases; the package manager (uv)
does. The earlier resolver, owner pin, rollback and release-contract design is removed (see the decision in the
[self-hosting roadmap](../self-hosting-roadmap.md)). A running factory process keeps the code it started with.

## Retained operational surface

| Flow | Retained purpose / recommendation |
|---|---|
| Doctor | Read actual prerequisites, DB readability and owned capability/resource health. Typed diagnostics; explicit safe repair stays separate. No recovery/reindex-as-state-rebuild or assumptions that PR protection is invalid. |
| Prune/reconcile | Show planned cleanup and actual kept/removed outcomes. Only proven owned/inactive resources are eligible; uncertainty keeps them. Retained evidence follows age policy separately from active state. |


## Earlier hook recommendation, superseded by lightweight-skill review below

PreToolUse runs under plain python3, imports only its lightweight rules and returns the harness's structured envelope.
Keep its no-msgspec/no-record/no-application-import boundary and bounded work per Bash call. SessionStart/PreCompact
currently use uv and can call shared bootstrap/session routines; they are not the same dependency boundary.

Git hook transport forwards exact argv/stdin and preserves repository hook/LFS chaining. The pre-push application judge
retains its explicit refusal behavior. Move generic external invocation/chaining through the owning process/Git library;
remove factory-local direct subprocess wrappers rather than exempting the hook wholesale. The plain-Python pretool path
must not acquire those heavier imports indirectly.

prepush.ours currently reads repos_doc with sqlite3 and independently discovers common-dir identity. Put registration,
repository binding and delivery decisions behind their one shared application owner; do not keep a thin script as a
second DB reader/policy engine. Hook errors follow their documented event behavior; this review does not introduce a
new generic permission/approval system. Human-facing diagnostics are rendered from typed results.

## Cleanup: ownership and liveness before age

Retain non-force worktree removal and compare-and-delete of an observed branch OID. Age may select an owned resource
for consideration, but cannot prove a worktree/scratch folder inactive. Current prune_scratch deletes matching names by
one-day mtime alone; old mtime does not prove a process died. Require registered creation/ownership and verified quiescence;
unknown ownership or liveness means keep/unavailable, not optimistic deletion. Do not add an unapproved global /tmp timer.

Missing path/mount does not authorize forgetting a configured repo. Current prune.verb._forget_missing removes such
bindings; instead show unavailable and require explicit unregister. Cleanup never touches the person's main checkout,
foreign worktrees, dirty/interrupted work, active installs or required retained evidence. DB absence is not proof
that workers stopped; no log-reconstruction/provenance guess is introduced after controlled discard.

A final squash means per-commit git cherry/ordinary ancestry cannot establish that an arbitrary task tip is safely
obsolete. Use the accepted delivery relationship and unchanged exact branch identity, then recheck ownership/occupancy.
If that proof is unavailable after DB discard, retain the branch; do not build a historical proof reconstruction system.
Release no longer deletes feature worktrees as a hidden publication side effect.

Retain one owning retention path per evidence area, separate from state/provenance. Active/unresolved work must not lose
required state through retention. Expired media/logs report their availability; they do not erase task/runtime state.
Do not report removed after an ignored deletion failure. General cleanup timeouts and failures are typed, not parsed
console text. Task claims still require genuine conditional backend mutation; the existing tl-r2g4 prerequisite applies.

## Other removal/consolidation leads

- setup_apply.open_pr privately creates a profile branch/commit/PR against the remote default branch, with Unity-shaped
  defaults. Keep useful machine setup; route repo profile authoring through normal configuration/work delivery rather
  than another special path. Coordinate PROFILEGEN; do not replace hardcoded behavior with a regex/report DSL.
- Doctor guard_rails currently hardcodes main, rejects required PR reviews and prints speculative queue rules. Align
  diagnostics with supported semantic delivery and delete queue/profile-approval/legacy-layout policy branches.
- launch/reindex currently attempts factorybackup.restore, then log reindex. Retire factory backup/restore and obsolete
  reconstruction under DISPOSABLE-DB; direct dashboard field replacement precedes log-derived state-index removal.
- Keep manifest integrity and normal vendor/package tools. Historical dev/carve_*, move_* and split_* scripts are source
  migration aids, not retained product behavior merely because they exist. Verify actual invocation before omission.
- Keep user task data/backups conceptually separate from disposable runtime DB; no automatic deletion of durable task data.

Read dev/release.py; tlrelease flow/push/gate/publish/clone/catalog/versions/pins/canary/selfupdate/tidy; doctor install/
setup_apply/guard_rails; hook main/pretool/prepush and hooks.json; launch reindex/loop_ops; prune verb/retention/slotstate;
reconcile apply and normal just/vendor tooling. Astra cross-checked the key boundaries. No source/runtime behavior was changed.


## Lightweight skill and hook retirement direction, 2026-11-09

Denis clarified that the skill should be lightweight: help set up/maintain the factory, author compliant tasks, handle
asks and perform requested operations for the owner. He questioned whether hooks are needed. A further Astra review
recommends retiring task-loop session hooks and its managed Git-hook overlay rather than retaining thin wrappers.
This supersedes the earlier keep-hooks recommendation. It records the owner's skill intent and the resulting hook-removal
recommendation; no source/installed hooks were changed.

The skill is an explicitly invoked assistant entry point. It calls normal CLI/API operations and reads their typed
results. Keep a short purpose, help/discovery entry, a few user-intent recipes and links to authoritative task/config/ask
references. Do not embed the runtime implementation, full command catalog, schema, scheduler/retry/state machinery or
a second orchestration loop. Runtime/CLI/dashboard/installer remain ordinary package assets even if bundled with a skill.

Current SKILL.md has 728 lines and blanket owner-preapproval language. Remove that invented authority and stale token/
profile/check guidance. Follow the actual user/session authorization, including valid standing instructions; do not
introduce repeated permission prompts or infer automation approval merely from creating a task. Author work requirements/
acceptance/dependencies through normal task verbs; avoid branch/slot/runtime bookkeeping in tasks.

| Current integration | Proposed disposition |
|---|---|
| SessionStart | Remove automatic bootstrap/launcher-hook rewriting and context injection. Current task/status/ask reads supply context. |
| PreCompact | Remove automatic handoff file generation/reinjection; no replacement chat-session snapshot/history mechanism. |
| PreToolUse | Remove task-loop's advisory pkill/killall rule and hook registration. Owned-process termination remains an execution responsibility, not prose or this hook. |
| Managed Git hook overlay | Remove generated dispatchers/healing, core.hooksPath environment injection, hook-presence diagnostics and private registry reader. Respect repository/user Git-hook configuration normally. |
| judge-push hook dispatcher | Retire its hook-only stdin/CLI path. Retained candidate/target/check/ownership obligations are enforced directly by publication/land/config operations, once. |
| Factory worker context | Provide through the shared execution interface at launch/continuation. It does not depend on hooks in the person's chat. |

Source correction: current session.start does NOT index transcripts, despite stale descriptions in hooks.json/session
module headers. Do not recreate an indexing requirement from those descriptions. Current PreToolUse has only the
pkill/killall rule; it is not the source-ownership or general execution-permission system.

The existing push judge really does inspect policy/checks/target rewind/deletion/credential-pattern rules. Before removing
its wrappers, map every rule to an agreed normal-operation requirement or deliberate deletion. Already retired profile
approval, historical pass reuse and queue guard must not be moved into a new interceptor. Do not copy the whole judge
blindly or add another global Bash/Git wrapper. Ordinary task-branch publication paths cannot rely on a
later hook for their own guarantees. Execution-adapter permissions remain separate and retain their owning contract.

Deliberate scope reduction: unrelated interactive sessions receive no automatic setup/handoff injection or extra pkill
denial, and arbitrary human/third-party Git commands receive no task-loop interceptor. Native repository/remote rules
still apply. Do not delete, replace or bypass repository-owned Git/LFS hooks. Generic invocation/permissions needed by
a harness adapter are not these retired plugin callbacks.

Retirement includes now-unused hook files/registrations, installer file checks, import-rule/test exceptions and hook-only
configuration/doctor branches. Do not keep phantom hook stubs or compatibility paths merely to satisfy old tests. Cleanup
of old generated files requires confirmed ownership/inactivity and must not disturb a running old installation.
