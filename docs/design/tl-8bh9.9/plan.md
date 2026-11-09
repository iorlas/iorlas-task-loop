# Git consolidation: mechanism versus factory policy

> STORE scope update, 2026-11-09: Denis accepted the identity/lifecycle contract and lifted its design hold for
> [reconciled STORE slices](../tl-sqd3.26/plan.md) only. Earlier blanket-hold statements below describe prior review history.
> Explicit dependencies still gate affected actions; historical migration/compatibility scope and unrelated holds remain excluded.

Task: tl-8bh9.9. Read-only review, 2026-11-08. Implementation remains behind the existing design gate.
No Git mutations, worktree resets, source edits or execution tests were performed for this review.

Owner strengthened the boundary on 2026-11-08: encapsulate all Git and process interactions in shared libraries;
task-loop tests use those libraries' fakes and do not invoke real Git/processes. Real behavior belongs in the owning
library's shared real/fake contract tests. Generic process control belongs to the shared process library, with
Git behavior owned by git_porcelain; do not turn the Git package into a general-purpose factory execution framework.
This supersedes the earlier permission to retain local low-level Git/process integration tests after migration.
No native subprocess fallback or new task-loop-local fake is part of the target design.

The owner made this a key acceptance check: factory-owned source/tests have no subprocess usage. Remove imports
as well as calls and facades that merely rebuild CompletedProcess/Popen/TimeoutExpired contracts; use shared library
result/handle/error types. An architecture rule must detect imported aliases and equivalent direct OS spawn/signal/wait
paths, not rely solely on searching for the literal subprocess string. Distinguish factory consumers from owning
library implementations, including vendored library copies; moving code into a local folder called a library does
not satisfy the ownership boundary. Inspect script/hook/bootstrap entry points too. This is a target invariant;
current source still violates it and was not changed during this review.

## Intended boundary

Owner refinement, 2026-11-08: subprocess use must be justified even inside shelf. The factory runs on one PC;
state management and ordinary operations should be Python-native. Shared-library ownership is necessary for retained
external interactions, but is not a reason to keep an unnecessary process. Use callable APIs, SQLite transactions,
Python synchronization and native OS primitives as appropriate, rather than shell commands or our own CLI for local
state operations. Do not introduce a remote coordinator for same-machine state. Genuine external tools such as agent
harnesses, repository checks or Git may still require processes; assess each retained boundary and its cost.
There is no requirement to reimplement Git or an external harness in Python solely to remove a legitimate tool process.

The shelf Git library owns generic repository operations, their results/errors, retained generic read caching,
environment binding and real/fake behavior. Factory code owns which branch/workspace to use, when to integrate,
what may land, which work is preserved and how a failure affects workflow. Generic behavior should not be copied
into the factory merely to match its old method names. Keep a thin factory-facing seam only where it has a purpose.

Task branches remain derived from task identity. Repository identity/binding must be reconciled with the RepoId/store
review, not implemented as another naming scheme. Existing merge-only/plain-push/final-squash direction governs
factory policy; do not preserve obsolete rebase-only factory APIs by extracting them unnecessarily.

## Evidence scope

Read src/taskloop/adapters/git.py, git_ops.py, git_base.py, git_pool.py, gitrepo.py and gitmemo.py; kernel gitport/gitfacts;
the vendored git_porcelain public operations, error/env/cache implementation, and selected land/slots/reconcile callers.
Ten reviewed adapter/vendor files matched the primary checkout byte for byte during this read. Vendor manifest pins
git_porcelain to 427ab3e75d94055f61efcc497ccd1244760cea8e. Verify actual shelf source before any library extension;
the locally vendored version is the behavior currently being assessed, not a claim about shelf HEAD.

RealGit already uses RealRepo for many operations. An AST call-path inventory found both direct shelf calls and
local raw-command/helper calls. That is a lead, not a proof that every wrapper or file can disappear. Some translation
may be required by a legitimate port boundary; many file names alone establish no duplication defect.

## Verified consolidation candidates

| Local behavior | Existing shelf mechanism | Proposed direction |
|---|---|---|
| Git.merge_base raw command plus absence handling | RealRepo.merge_base with typed read failures and missing-object checks | Migrate callers/semantics; remove local command/read path. |
| Git.is_ancestor raw predicate | RealRepo.is_ancestor | Use shared implementation, preserving false versus unavailable distinction. |
| Git.remote_url using local read memo | RealRepo.remote_url | Use shared observation after checking required config/environment behavior. |
| Git.branch using symbolic-ref | RealWorktree.branch | Adopt shared return semantics; do not add another alias solely to preserve an old name. |
| git_base classifier plus git_pool conversion | git_porcelain.errors typed failures and classifier | One generic failure owner; factory retains workflow decisions, not a second generic parser. |
| gitrepo discovery/pinning and gitmemo validation | real_env and real_cache | Assess semantic differences and need first; consolidate retained mechanism rather than blindly enable caching. |

These cover caller families in land, slots, reconciliation, worker stray checks, report inputs and task-close guards.
Full raw-operation mapping still needs to separate required API gaps from obsolete or unused factory behavior.

## Important differences to preserve or deliberately resolve

- Factory _pool constructs a new library repository per operation with memoize=False. Library memo state belongs to
  a repository instance. Turning its cache on alone does not recreate the local cross-call cache behavior.
- Local pinning searches ancestors for a checkout, while library pinning takes a checkout path. Resolve the caller's
  repository/worktree once through the agreed binding, or supply the required library behavior; do not drop it blindly.
- Local environment policy suppresses fsmonitor/hooks and pins the actual worktree. Preserve the relevant semantics
  rather than removing safeguards as duplicate boilerplate. A plain-python hook cannot acquire heavy dependencies.
- Both local and library ref-cache discovery avoid reftable. No reftable cache bug was demonstrated by this review.
  Supported config include files and external writes still need invalidation analysis where caching remains.
- The library distinguishes typed absence and unavailable/corrupt reads; local consumers sometimes map absence to
  empty strings. Do not turn an unknown read into a false predicate while simplifying result types.

## Bounded work

- tl-8bh9.9.1 maps and replaces local reads already covered by the public library, then removes superseded surface.
- tl-8bh9.9.2 consolidates generic errors and strips redundant translation after actual consumers migrate.
- tl-8bh9.9.3 reviews binding and caching, avoiding repeated queries before retaining extra memoization machinery.

The existing shared-test work tl-z6np/shelf-69pz owns fake/contract consolidation. Current vendored stream_proc
already provides capture/stream/spawn/stop/liveness used by adapters/procs.py, but no Fake implementation was found
in the vendored package searched. Verify current shelf source and add missing fake capability there rather than
create another task-loop implementation. Type-only subprocess imports are not evidence of a real process launch.
The plain-Python prepush hook still has actual direct subprocess calls: resolve this bootstrap boundary explicitly
with a small suitable shared API/extraction, not an unnoticed permanent exception to the owner's rule.

All share files and must not be implemented concurrently without a noncolliding plan. These children inherit the
design hold. Complete the necessary interface/identity decisions before source work; do not start held STORE work.
Coordinate shared fake/contracts with existing tl-z6np and shelf-69pz instead of creating another test-kit effort.

## Validation and deletion criteria

Use the library's one shared real/fake operation contract, retaining factory policy tests. Add only meaningful
missing behavioral cases: unavailable reads, concurrent ref changes, linked-worktree/root binding, dirty/held branch
and required environment behavior. A wrapper's existence alone does not warrant its own duplicate contract suite.

Remove a local implementation/helper only after its callers have migrated or the underlying behavior was removed.
Report net source/test change including shelf additions; gross deleted local lines are not savings. Library source
changes belong in its own worktree/gate and reach this repo through normal vendor tooling, not hand edits to the copy.
Run just check and just test for eventual source changes; no full/live suite is authorized by this review.


## Delivery and publication follow-up, 2026-11-09

The [delivery/publication review](delivery-publication.md) traces existing stage pushes, local-only plan publication,
PR waiting and failed task settlement. It proposes remote checkpoints at completed plan/mutating-step boundaries,
append-only task history and distinct published/landed/completed facts. The corrected strategy was accepted by the owner on 2026-11-09: merge plus target squash, ordinary task-branch
pushes, completed-step publication and retry only unfinished required actions. Structured result contracts are required;
PRs may intentionally await human review. Earlier broad opposition to final squash was withdrawn. No held implementation is admitted.
