"""The git port: what the engine asks of git (Protocols and the typed answers), implemented by adapters.git and the git simulators."""
from typing import Literal, Protocol

from tlkernel.gitfacts import ConfigEntry, DiffEntry, GitOutcome, GrepHit, LogRow, Pick, Ref, StatusRow, TreeEntry
from tlkernel.slots import Checkout


class SlotGit(Protocol):
    """What a slot's life asks of git (reset, checkout, commit, worktrees). Every method takes the worktree it acts in and raises a
    SlotGitError subclass. Unknown read observations raise GitReadFailure; they never mean clean, empty or missing."""

    def fetch(self, d: str) -> None: ...
    def rebasing(self, d: str) -> bool: ...
    def rebase_abort(self, d: str) -> None: ...
    def dirty(self, d: str) -> bool: ...
    def branch(self, d: str) -> str:
        """The branch checked out in `d`, empty when HEAD is detached."""
        ...

    def commit_all(self, d: str, branch: str, message: str) -> None:
        """Commit every change on `branch`, created at HEAD when HEAD is detached."""
        ...

    def has_branch(self, d: str, branch: str) -> bool: ...
    def checkout(self, d: str, branch: str) -> None: ...
    def checkout_new(self, d: str, branch: str, start: str) -> None: ...
    def checkout_detached(self, d: str, ref: str) -> None: ...
    def clean(self, d: str, keep: list[str]) -> None: ...

    def checkouts(self, d: str) -> list[Checkout]: ...
    def remove_worktree(self, repo: str, path: str) -> bool: ...
    def add_worktree(self, repo: str, path: str, ref: str) -> None: ...
    def prune_worktrees(self, repo: str) -> None: ...
    def init_bare(self, d: str, branch: str) -> None:
        """A bare repository at the path `d` whose default branch is `branch`."""
        ...

    def clone(self, src: str, dst: str) -> None: ...
    def push(self, d: str, remote: str, refspec: str) -> None: ...


class Git(SlotGit, Protocol):
    """git, the one port every git call goes through (RealGit on the binary; a logic test runs it over tests/support/gitsim,
    and one contract suite, tests/ports/git_contract.py, holds both to the same answers). Reads return typed rows, not text to re-parse."""

    def clean(self, d: str, keep: list[str], ignored: bool = False) -> None:
        """Delete the untracked files (and the ignored ones with `ignored`) except those matching a `keep` pattern."""
        ...

    def remove_worktree_why(self, repo: str, path: str) -> str:
        """Remove one worktree without force; empty when it is gone, else the line of git's words that says why it stayed."""
        ...

    # -- reads that return rows (each raises a SlotGitError when git cannot answer) ------------------------------------------------
    def for_each_ref(self, d: str, *prefixes: str) -> list[Ref]:
        """Every ref under the prefixes (refs/heads/task/ ...), by full refname, with its oid."""
        ...

    def ls_remote(self, d: str, remote: str, *patterns: str) -> list[Ref]:
        """The refs `remote` shows for the patterns (refs/heads/task/*); raises when the remote does not answer."""
        ...

    def cherry(self, d: str, upstream: str, head: str) -> list[Pick]:
        """The commits of `head` not on `upstream`, each marked when its patch is already there."""
        ...

    def merged(self, d: str, into: str) -> list[Ref]:
        """The local branches (short names) whose tip is an ancestor of `into`."""
        ...

    def merge_base(self, d: str, a: str, b: str) -> str:
        """The best common ancestor of a and b, empty when a revision is absent or they share none; unknown reads raise."""
        ...

    def is_ancestor(self, d: str, a: str, b: str) -> bool: ...
    def symbolic_ref(self, d: str, ref: str) -> str:
        """The full target of a symbolic ref, empty when absent or not symbolic; unknown reads raise."""
        ...

    def rev_parse(self, d: str, rev: str) -> str:
        """The oid `rev` names, empty when it names nothing."""
        ...

    def log(self, d: str, include: list[str], exclude: list[str] | None = None, limit: int = 0, grep: str = "") -> list[LogRow]:
        """The commits reachable from `include` and not from `exclude`, newest first; `grep`: only subjects that contain it."""
        ...

    def ls_tree(self, d: str, rev: str, *paths: str, recursive: bool = False) -> list[TreeEntry]: ...
    def status(self, d: str, all_untracked: bool = False) -> list[StatusRow]:
        """Every changed and untracked path; untracked folders are listed whole with `all_untracked`, else as the folder."""
        ...

    def check_ignore(self, d: str, paths: list[str], excludes: str = "") -> list[str]:
        """Those of `paths` the ignore rules (and the excludes file, when given) cover, without asking the index."""
        ...

    def git_dir(self, d: str) -> str:
        """The absolute git dir of `d`, empty outside a repo; unknown reads raise."""
        ...

    def has_commit(self, d: str, oid: str) -> bool: ...
    def show(self, d: str, rev: str, path: str) -> str:
        """The text of the file `path` as it is at `rev`; raises when there is no such file there."""
        ...

    def ls_files(self, d: str, scope: Literal["tracked", "unignored", "ignored"] = "tracked", *spec: str) -> list[str]:
        """The tracked files; with `unignored` those and the untracked files the ignore rules do not cover; with `ignored` the untracked
        ones they cover, optionally only those under the pathspecs `spec`."""
        ...

    def grep(self, d: str, pattern: str, fixed: bool = False, word: bool = False) -> list[GrepHit]:
        """The lines of the tracked text files that match (a regex, or the literal text with `fixed`; `word`: whole words only)."""
        ...

    def config_get(self, d: str, key: str) -> str:
        """The value of one setting, empty when it is unset."""
        ...

    def config_entries(self, d: str, pattern: str) -> list[ConfigEntry]:
        """Every setting whose key matches the regex, each with the file it was set in."""
        ...

    def common_dir(self, d: str) -> str:
        """The absolute git dir the worktrees of `d`'s repo share, empty when `d` is in no repo."""
        ...

    def toplevel(self, d: str) -> str:
        """The root folder of the work tree `d` is in, empty when there is none."""
        ...

    def tree_of(self, d: str) -> str:
        """The tree id the work tree would commit now, untracked files included, without touching its index; raises when git cannot say."""
        ...

    def worktree_state(self, d: str) -> bytes | None:
        """git's own account of what differs from HEAD (branch line, changed and untracked paths), raw; None when git cannot say."""
        ...

    def diff(self, d: str, a: str, b: str, exclude: list[str] | None = None, stat: bool = False) -> str:
        """The patch (or with `stat` the summary) from tree a to tree b, leaving out the literal paths in `exclude`."""
        ...

    def profile_diff(self, d: str, base: str, tip: str) -> str:
        """The exact text of git diff base tip -- .task-loop.json, including its final newline."""
        ...

    def add_worktree_force(self, repo: str, path: str, ref: str) -> None:
        """Like add_worktree, again if the path is registered but missing."""
        ...

    def remove_worktree_force(self, repo: str, path: str) -> None:
        """Remove a worktree whatever it holds; a failure is not an error."""
        ...

    def unpinned(self) -> Git:
        """The same port asked as a worker's or a check's git would see the folder (no pin): for whether the pin itself is right."""
        ...

    # -- what a task's land, close and checks ask --------------------------------------------------------------------------------
    def count(self, d: str, include: list[str], exclude: list[str] | None = None) -> int:
        """How many commits are reachable from `include` and not from `exclude`."""
        ...

    def unmerged(self, d: str) -> list[str]:
        """The paths a stopped rebase or merge left in conflict."""
        ...

    def changed_paths(self, d: str, a: str, b: str, *, required: bool = False) -> list[str]:
        """Paths differing between a and b; a missing revision is empty unless required for a write or skip decision.
        Other read failures always raise."""
        ...

    def diff_entries(self, d: str, a: str, b: str, ignore_space: bool = False, *, required: bool = False) -> list[DiffEntry]:
        """The paths that differ between the trees a and b with their status, an exact (100%) rename as one R entry; with `ignore_space`
        only those with a change that is not whitespace. Missing revisions are empty unless required; other failures raise."""
        ...

    def staged(self, d: str) -> bool:
        """Whether the index holds work that is not committed."""
        ...

    def staged_paths(self, d: str) -> list[str]:
        """The paths the index adds, changes or renames to (not its deletions)."""
        ...

    def export_index(self, d: str, dest: str) -> None:
        """Lay the index over the checkout at `dest` (a worktree of HEAD): staged content in, staged deletions out."""
        ...

    def stage_literal(self, d: str, paths: list[str]) -> None:
        """Stage exactly these paths (as given, no globbing; a deleted one stages its deletion), however many there are."""
        ...

    def rename_branch(self, d: str, old: str, new: str) -> None: ...
    def checkout_reset(self, d: str, branch: str, start: str) -> None:
        """Point `branch` at `start` (created if missing) and check it out; refuses when local changes would be lost."""
        ...

    def try_commit(self, d: str, message: str, verify: bool = True, allow_empty: bool = False) -> GitOutcome:
        """Commit what is staged; `verify=False` skips the hooks. Never raises for git's refusal: the words are in the outcome."""
        ...

    def amend(self, d: str) -> None:
        """Fold what is staged into the last commit, keeping its message and skipping the hooks."""
        ...

    def rebase_continue(self, d: str) -> GitOutcome:
        """Go on with a stopped rebase once its conflicts are staged."""
        ...

    def push_lease(self, d: str, remote: str, refspec: str, expect_sha: str) -> GitOutcome:
        """The one way to move a remote ref non-fast-forward: SRC:DST pushed with ordinary hooks and
        --force-with-lease=DST:expect_sha, so DST is replaced only if the remote still holds expect_sha
        ('' = the caller never saw DST: a plain push, which can only create it or fast-forward it).
        `push` never forces or deletes."""
        ...

    def lfs_push(self, d: str, remote: str, refs: list[str]) -> GitOutcome:
        """Upload the LFS objects of the refs to the remote."""
        ...

    # -- writes ----------------------------------------------------------------------------------------------------------------
    def rebase(self, d: str, onto: str, update_refs: bool = True) -> GitOutcome: ...
    def reset(self, d: str, rev: str, mode: Literal["soft", "mixed", "hard"] = "mixed") -> None: ...
    def tag(self, d: str, name: str, rev: str = "HEAD") -> None: ...
    def checkout_force(self, d: str, branch: str, start: str) -> None:
        """Point `branch` at `start` and check it out, throwing away local changes (checkout -f -B)."""
        ...

    def fetch_ref(self, d: str, source: str, ref: str) -> None:
        """Fetch one `ref` of another repository (a path or url) into FETCH_HEAD; raises when it has no such ref."""
        ...

    def remote_url(self, d: str, remote: str) -> str:
        """The url of the remote; MissingRemote when unset, other read failures when unknown."""
        ...

    def merge_ff(self, d: str, rev: str) -> None:
        """Fast-forward the checked-out branch to `rev`; raises when it would need a merge."""
        ...

    def commit_tracked(self, d: str, message: str) -> None:
        """Commit the changes of the tracked files (commit -a); untracked files stay out."""
        ...

    def stage(self, d: str, *paths: str) -> None: ...
    def commit_staged(self, d: str, message: str) -> None:
        """Commit what is staged, hooks included."""
        ...

    def pull_rebase(self, d: str, remote: str, branch: str) -> None: ...
    def delete_branch_at(self, d: str, branch: str, oid: str) -> None:
        """Delete a local branch only while it is at `oid`; raises RefRace-or-other SlotGitError when it moved."""
        ...

    def delete_remote_at(self, d: str, remote: str, ref: str, oid: str) -> None:
        """Delete the remote's `ref` only while it is at `oid` (force-with-lease); already absent is success."""
        ...
