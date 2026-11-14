# Repository binding and storage ownership

Status: **design**. Accepted decisions and pending proposals are distinguished below; historical source observations are not a delivery receipt. Explicit holds remain in force except where superseded.

> STORE scope update, 2026-11-09: Denis accepted the identity/lifecycle contract and lifted its design hold for
> [reconciled STORE slices](../tl-sqd3.26/plan.md) only. Earlier blanket-hold statements below describe prior review history.
> Explicit dependencies still gate affected actions; historical migration/compatibility scope and unrelated holds remain excluded.

Task: tl-8bh9.1. Source review, 2026-11-08. Design only.
Owner confirms joint RepoId/storage review and one shelf agent interface. Held STORE implementation remains held.

## Current identities are not all the same fact

| Current function/owner | Meaning | Consumers observed |
|---|---|---|
| ids.loop_key | Real checkout path basename plus path hash; local spelling. | Run rows, task-list projection, dashboard project keys. |
| check_files.repo_key | Resolves Git common directory then derives loop_key from its parent, falling back to the input worktree. | Shared check/repository scope for linked worktrees. |
| reponame.repo_name | Last two origin URL components, else folder basename. | ReposStore registration name; rejects a second registered path with the same name. |
| ReposStore | Local name-to-path registration in disposable factory.db. | Known repositories and dashboard lookup. |

These observations do not establish that every scheme needs a replacement. A local checkout key changing on another
PC is compatible with discarding its runtime database. A display name is not necessarily a globally unique repository ID.
The defect to avoid is callers independently discovering and substituting these facts as if interchangeable.

## Proposed boundary

Resolve the repository binding once at the edge through the shared Git API. Carry that binding into execution/storage
and dashboard queries. One RepoId owner exposes named projections required by actual consumers; do not introduce
a second dashboard parser, universal remote-ID scheme or another compatibility mapping.

Keep local checkout/worktree paths and disposable table keys local. Portable task references and committed design/code
must not require yesterday's absolute checkout path, database key, slot or host. A fresh machine rediscovers its local
binding from its checkout and task-service configuration. No identity migration framework is required.

reponame currently reads .git, commondir and config itself, parses the origin URL and drops host information from the
registration name. This is another Git read owner to consolidate with git_porcelain, not a reason to grow a second
Git config parser. Preserve or deliberately remove supported binding semantics through the shared owner.
Coordinate existing tl-8bh9.9.3 rather than create another generic Git discovery task.

## Choices still requiring evidence or an owner decision

Whether two independent clones of the same remote may be registered at once affects the registration-name rule.
The current name collision refusal is observable policy, not a proven defect. Also inspect repositories without an
origin and distinct forge hosts sharing owner/name. Do not choose a global identity mechanism solely for hypothetical
future coordination. Task-service identity and local Git binding must be explicit where they differ.

Storage shape follows the agreed task/step/attempt/session model. Current attempt rows count engine take-up and current
dashboard log folds infer execution detail; reconcile those together before changing keys/tables. Merely wrapping old
strings in RepoId would not settle ownership. Conversely, do not rebuild all storage just to rename a key.

## Existing work and verification

Reuse tl-sqd3.18 and the tl-sqd3.26 design scope, plus tl-8bh9.3.1, tl-8bh9.7.2 and Git consolidation.
No held STORE child is admitted. Existing acceptance about pending effects must be reassessed against the simpler
restart policy; no decision here authorizes deleting protection against duplicated external effects.

Read ids.loop_key, check_files.repo_key, reponame, rowstores.ReposStore, runrows and dashboard consumers. No Git revision
queried, no source edits, no runtime checks. Shelf Git binding contract plus factory fake tests should cover required
linked-worktree/root/no-origin/name-collision behavior once the policy is settled; eventual just check and just test.


## Consolidated identity and STORE decision, 2026-11-09

The [identity/store contract](identity-store-contract.md) correlates task/branch/worktree/slot lifecycles, removes
workspace as a separate entity, distinguishes completed validation from live worktree custody, and proposes the local
Git binding/task-backlog namespace contract. It identifies stale STORE migration scope and the bounded approval needed
to release reconciled successor slices. This review itself does not lift STORE's hold.
