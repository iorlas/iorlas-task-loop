# Canonical repository inspection

Task: tl-sqd3.18.1, bounded child of REPOID tl-sqd3.18. Prepared 2026-11-09.
The successor foundation is the local base; this task is not the whole registry/backlog-binding implementation.

## Retained behavior

A real `tl repo inspect PATH` operation reports the selected local repository identity through the owning shared
Git API. Initial input is an explicit checkout root; no inferred registration or caller-path fallback. A missing,
unavailable or unsupported checkout is a truthful typed refusal/nonzero CLI result. Root/subdirectory policy is
explicit rather than introducing a factory topology-discovery framework. No stub task execution commands.

Return the opaque local RepoId, canonical common directory, selected checkout projection and optional origin.
Origin never determines local identity. Linked worktrees share identity, clones differ and missing origin is valid.
RepoIdentity.root is common-dir-derived and cannot be used as the selected linked checkout. Use actual public
worktree records to establish the selected checkout; do not parse private Git files or invent a main-root fallback.
Readonly inspection is not an execution admission/custody guarantee. Actual agent/check checkout protection is
owned at the later preparation/execution boundary.

The operation receives the shared Repo API. Composition selects RealRepo with memoize=False; consumer tests use
provided FakeRepo/FakeRemote. Observe identity/worktree information once for this operation and pass the returned
values; no factory memo cache or generic query layer. CLI owns formatting and error rendering, not Git mechanics.

## Verified shared prerequisite

Shelf tasks shelf-7qsd and shelf-66d2 are implemented and independently reviewed on local branch
codex/git-identity-contract, worktree /home/iorlas/.codex/worktrees/git-identity-contract/shelf.
Local checkpoints: fe41f2f (truthful identity/discovery failures) and 5b99aaa (explicit package type contracts).

- Origin-read errors previously became false absence; existing typed remote_url is now reused, catching only MissingRemote.
- Filesystem-boundary not-a-repository diagnostics now remain distinct from unavailable Git reads.
- Git already guarantees canonical paths for --path-format=absolute; actual linked/symlink scenarios passed the
  baseline, so no redundant Path.resolve or extra Git observation was added. See
  [Git's documented path contract](https://git-scm.com/docs/git-rev-parse#Documentation/git-rev-parse.txt---path-formatabsoluterelative).
- Explicit package typing repaired 18 errors with preserved constructors/runtime redaction and no new suppressions.
- Normal affected shelf check passed; explicit package/changed-test typing reports 0 errors with 2 existing suppressions.
  Independent read-only review found no blockers. This is not whole-repo check-all/release readiness.
- Correction, 2026-11-09: interpreter discovery excluded editable workspace source even in a visible worktree; shelf-j4qq owns the verified gate defect (74 editable roots, 312 omitted production files).

## Dependency and admission boundary

The shelf consumption contract requires portable Git URL + subdirectory + namespaced release tag, with uv.lock
pinning its commit. Preparation history, superseded by the release receipt below: the existing local tag was
git-porcelain-v0.12.0; source metadata was 0.12.1 and the corrected code had
been published as a review branch in [shelf PR #66](https://github.com/yoselabs/shelf/pull/66), but had not been
merged/released/tagged. A locally built candidate wheel is evidence, not a portable dependency release.

Do not commit an absolute path/editable override, pin a nonexistent tag, copy library source into factory or
claim normal locked consumer gates passed with a substituted local package. Local co-development overrides
are permitted by shelf for inner-loop work only and must not leak into committed dependency declarations.
Normal source integration requires the corrected dependency to be pinned reproducibly. During preparation,
Git authority covered local checkpoints and the authorized review branch/PR; merge, release and tagging required
separate authority and their required gate. The later receipt records that prerequisite's delivery.

## Source and verification after dependency is available

Add only the application inspection record/operation and actual CLI route, the shared Git dependency and its
portable source/lock, and fake-based consumer tests. No registration, SQLite, scheduler, account UI or old kernel.
Use supported typed library errors, not message regexes. A library mechanism gap is fixed in its owner.

Cover shared-identity linked worktrees, independent clones, origin absence/change and invalid checkout; repository
identity does not imply that the original path is the selected checkout. Real Git/symlink mechanism tests stay in
shelf. Update the foundation isolation assertions to the exact declared shared dependency, retaining noneditable
current-project provenance and no baseline imports. Required just check/just test and independent review remain
mandatory before a source completion claim. An executable smoke is separate from task delivery/publication.


Earlier publication receipt, 2026-11-09: PR #66 was open and clean against main at reviewed head
5b99aaa7a43f38b07eeebf2b7351468e55222cd2. User authorization then covered branch push/PR only; merge, release
and tagging remained separate. The PR was attached to the current task. No consumer dependency pin had been changed.

## Released dependency and consumer verification, 2026-11-09

The coordinator confirmed that shelf PR #66 was merged and `git-porcelain-v0.13.0` was published at commit
`e71d37571192d4ad6a7e95d64ad46c3d9210e1e8`, tree `db8b601de0cb6b1cc059db2936fc13bf2f3af9b4`.
The reported native and Linux shelf check/check-all gates passed. This supersedes the earlier dependency-release
blocker; the earlier receipts retain the preparation/publication history rather than describing the current state.

The successor now declares `git-porcelain==0.13.0` from `https://github.com/yoselabs/shelf.git`, subdirectory
`packages/git-porcelain`, tag `git-porcelain-v0.13.0`. Normal `uv lock` independently resolved that tag to the exact
commit above. `uv.lock` pins that commit. The temporary `/tmp` candidate-wheel source was removed from both files.
No local override, editable dependency, source copy or nonexistent release reference supplies the dependency.

Required gates rebuilt the declared environment using the justfile's
`uv sync --frozen --no-editable --reinstall-package iorlas-task-loop`:

- `just check`: passed; Ruff passed, Pyrefly reported zero errors, both import architecture contracts were kept.
- `just test`: passed, 54 focused tests. This includes portable dependency/tag/lock provenance, noneditable current
  successor source provenance and baseline-import isolation, alongside inspection/CLI behavior and source policy.
- Installed `git-porcelain` distribution metadata independently reports the HTTPS Git URL, subdirectory,
  `git-porcelain-v0.13.0` requested revision and exact `e71d3757...` commit; no wheel-path origin remains.

Real installed executable smokes, both exit zero:

`.venv/bin/tl repo inspect /home/iorlas/.codex/worktrees/successor-foundation/iorlas-task-loop`

`.venv/bin/tl repo inspect /home/iorlas/.codex/worktrees/successor-foundation/iorlas-task-loop --json`

Both reported RepoId `bf94a5f1022a`, common directory `/home/iorlas/Workspaces/iorlas-task-loop/.git`, the selected
successor checkout path, and origin `git@github.com:iorlas/iorlas-task-loop.git`. This confirms the selected linked
checkout remains distinct from the common-directory-derived main root in the real installed command.

Independent final acceptance review and any factory Git delivery/task completion remain separate effects. This
receipt records successful local consumer validation, not a factory merge, publication or completion of parent REPOID.
