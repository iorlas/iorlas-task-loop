"""FakeGit's multi-step writes: the rebase (and its pause), linked worktrees, and the remote."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from git_porcelain.api import Conflict, HookRejected, Offline, Pushed, Rebased, RefRejected, Sha, Synced, Transient
from git_porcelain.errors import GitUnavailable, RefRace, WorktreeRemoveRefused, some
from git_porcelain.fake_merge import merge_trees, replay_list
from git_porcelain.fake_ops import hard_to, is_clean, make_commit, require_index, switch_tree
from git_porcelain.fake_store import CheckoutState, Rebase, ancestors
from git_porcelain.remote_validation import validate_remote

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from git_porcelain.api import PushResult, SyncResult
    from git_porcelain.fake_store import RepoState

__all__ = ["continue_rebase", "fetch", "push", "rebase_abort", "start_rebase", "worktree_add", "worktree_remove"]

MARKERS: Final = re.compile(r"^(?:<<<<<<<|>>>>>>>)(?: |$)", re.MULTILINE)


def start_rebase(repo: RepoState, wt: CheckoutState, head: str, target: str, *, update_refs: bool = False) -> Rebased | Conflict:
    """Detach at ``target`` and replay ``head``'s own commits on it, as ``git rebase`` does."""
    old = dict(repo.head_files(wt))
    new = dict(repo.store.commits[target].files)
    switch_tree(repo, wt, new, old)
    todo = replay_list(repo, head, target)
    state = Rebase(head, wt.head_ref, target, new, todo)
    if update_refs:
        held = {other.head_ref for other in repo.worktrees.values()}
        replayed = {commit.sha for commit in todo}
        state.update_refs = {
            ref: sha for ref, sha in repo.refs.items() if ref.startswith("refs/heads/") and ref not in held and sha in replayed
        }
    wt.head_ref, wt.detached, wt.rebase = None, target, state
    return _replay(repo, wt, state)


def _replay(repo: RepoState, wt: CheckoutState, state: Rebase) -> Rebased | Conflict:
    while state.todo:
        commit = state.todo.pop(0)
        base = repo.store.commits[commit.parents[0]].files if commit.parents else {}
        merged, conflicts = merge_trees(repo, base, state.files, commit.files)
        if conflicts:
            state.pending = commit
            _stop(repo, wt, merged, conflicts)
            return Conflict(
                tuple(sorted(conflicts)), f"CONFLICT (content): Merge conflict in {', '.join(sorted(conflicts))}", Sha(state.orig_sha)
            )
        if merged != state.files:
            switch_tree(repo, wt, merged, state.files)
            state.current = repo.store.put_commit(merged, (state.current,), commit.message, repo.tick()).sha
            state.files = merged
            wt.detached = state.current
        state.rewritten[commit.sha] = state.current
    new = state.current
    wt.head_ref, wt.detached, wt.rebase = state.orig_ref, None if state.orig_ref else new, None
    repo.move_head(wt, new)
    for ref, old in state.update_refs.items():
        repo.refs[ref] = state.rewritten.get(old, old)
    return Rebased(Sha(state.orig_sha), Sha(new), squashed=False)


def _stop(repo: RepoState, wt: CheckoutState, merged: dict[str, str], conflicts: dict[str, bytes]) -> None:
    """Leave the checkout the way a conflicted rebase does: clean merges staged, conflicts as markers."""
    for path, sha in merged.items():
        wt.index[path] = sha
        wt.files[path] = repo.store.blobs[sha]
    for path in [p for p in wt.index if p not in merged and p not in conflicts]:
        del wt.index[path]
        wt.files.pop(path, None)
    for path, data in conflicts.items():
        wt.files[path] = data
    wt.unmerged = set(conflicts)


def continue_rebase(repo: RepoState, wt: CheckoutState) -> Rebased | Conflict:
    """``rebase --continue`` after the conflicted files were edited: markers left means still conflicted."""
    state = wt.rebase
    state = some(state)
    require_index(wt)
    marked = tuple(sorted(p for p in wt.unmerged if MARKERS.search(wt.files.get(p, b"").decode("utf-8", "replace"))))
    if marked:
        return Conflict(marked, "conflict markers remain", Sha(state.orig_sha))
    for path in wt.unmerged:
        if path in wt.files:
            wt.index[path] = repo.store.put_blob(wt.files[path])
        else:
            wt.index.pop(path, None)
    wt.unmerged.clear()
    if dict(wt.index) == state.files:
        return Conflict((), "No changes - did you forget to use 'git add'?", Sha(state.orig_sha))
    state.current = make_commit(repo, wt, state.pending.message if state.pending else "", (state.current,))
    if state.pending is not None:
        state.rewritten[state.pending.sha] = state.current
    state.files = dict(wt.index)
    state.pending = None
    return _replay(repo, wt, state)


def rebase_abort(repo: RepoState, wt: CheckoutState) -> None:
    stopped = wt.rebase
    stopped = some(stopped)
    old = dict(repo.head_files(wt))
    hard_to(repo, wt, repo.store.commits[stopped.orig_sha].files, old)
    wt.head_ref, wt.detached = stopped.orig_ref, None if stopped.orig_ref else stopped.orig_sha
    repo.move_head(wt, stopped.orig_sha)
    wt.rebase = None


def worktree_add(repo: RepoState, path: Path, sha: str | None, *, force: bool = False) -> CheckoutState:
    """A new linked worktree at ``path``, detached at the commit."""
    target = repo.worktrees.get(path)
    if (target is not None and not (force and target.missing and not target.main)) or sha is None:
        msg = f"git worktree add exited 128: '{path}' already exists or the revision is unknown"
        raise GitUnavailable(msg)
    files = repo.store.commits[sha].files
    made = CheckoutState(path, None, detached=sha, index=dict(files), files={p: repo.store.blobs[s] for p, s in files.items()})
    repo.worktrees[path] = made
    return made


def worktree_remove(repo: RepoState, path: Path, *, force: bool) -> None:
    target = repo.worktrees.get(path)
    if target is None:
        msg = f"fatal: '{path}' is not a working tree"
        raise WorktreeRemoveRefused(msg)
    if target.main:
        msg = f"fatal: '{path}' is a main working tree"
        raise WorktreeRemoveRefused(msg)
    if not force and not target.missing and not is_clean(repo, target):
        msg = f"fatal: '{path}' contains modified or untracked files, use --force to delete it"
        raise WorktreeRemoveRefused(msg)
    del repo.worktrees[path]


def remote_state(repo: RepoState, name: str) -> RepoState | str:
    """The remote's repository, or why it cannot be reached."""
    found = repo.remote_repos.get(name)
    if found is None:
        return f"fatal: '{name}' does not appear to be a git repository\nfatal: Could not read from remote repository."
    if found.offline:
        return f"fatal: unable to access '{found.common}': Could not resolve host"
    return found


def fetch_races(repo: RepoState) -> None:
    """Consume at most five simulated ref races, matching the real fetch attempt budget."""
    races = repo.hooks.fetch_ref_races
    repo.hooks.fetch_ref_races = max(0, races - 5)
    if races >= 5:
        msg = "error: cannot lock ref 'refs/remotes/origin/main': is at abc but expected def"
        raise RefRace(msg)


def fetch(repo: RepoState, name: str, *, retry: bool = True) -> SyncResult:
    """Copy the remote's objects and set ``refs/remotes/<name>/<branch>`` for each of its branches."""
    validate_remote(name)
    if retry:
        try:
            fetch_races(repo)
        except RefRace as exc:
            return Offline(exc.tail, output=exc.output)
    there = remote_state(repo, name)
    if isinstance(there, str):
        return Offline(there)
    repo.store.absorb(there.store)
    for ref, sha in there.refs.items():
        if ref.startswith("refs/heads/"):
            repo.refs[f"refs/remotes/{name}/{ref.removeprefix('refs/heads/')}"] = sha
    return Synced()


def push(repo: RepoState, wt: CheckoutState, dst: str, name: str, env: Mapping[str, str], *, head: Sha | None = None) -> PushResult:
    """Fast-forward (or create) branch ``dst`` on the remote; the pre-push knobs first, then the network."""
    validate_remote(name)
    if head is not None and re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", head) is None:
        msg = "head must be a full object id"
        raise ValueError(msg)
    sha = head if head is not None else repo.head_sha(wt)
    if sha is None:
        msg = "nothing to push: HEAD is unborn"
        raise ValueError(msg)
    refusal = hook_refusal(repo, env)
    if refusal is not None:
        return refusal
    if repo.hooks.push_transport_failure is not None:
        return Transient(repo.hooks.push_transport_failure)
    there = remote_state(repo, name)
    if isinstance(there, str):
        return Transient(there)
    ref = f"refs/heads/{dst}"
    there.store.absorb(repo.store)
    old = there.refs.get(ref)
    if old is not None and old not in ancestors(there.store, sha):
        return RefRejected(f"! [rejected] HEAD -> {dst} (non-fast-forward)")
    there.refs[ref] = sha
    repo.refs[f"refs/remotes/{name}/{dst}"] = sha
    return Pushed(Sha(sha), output=f"To {name}\n \t{sha}:{ref}\t{sha[:7]}\nDone")


def hook_refusal(repo: RepoState, env: Mapping[str, str]) -> HookRejected | None:
    if repo.hooks.push_output is not None:
        output = (repo.hooks.push_output + "error: failed to push some refs\n").strip()
        return HookRejected(output[-600:], output=output)
    if repo.hooks.refuse_push:
        return HookRejected("pre-push hook declined the push")
    missing = {k: v for k, v in repo.hooks.push_requires_env.items() if env.get(k) != v}
    return HookRejected(f"pre-push hook wants {missing}") if missing else None
