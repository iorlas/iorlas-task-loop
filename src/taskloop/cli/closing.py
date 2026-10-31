"""`tl close`, `tl bd close` and `tl land` as a person runs them: each from the repo of the current directory, a close through the close
guard (app/track/closeguard.py), a land recorded with its LANDED row."""
from pathlib import Path

from taskloop.app.launch import repos
from taskloop.app.track import verbs
from taskloop.app.wire import closeguard
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import Beads, Git


def cmd_close(bead: BeadId, reason: str | None, who: Identity, git: Git, store: Beads) -> int:
    return verbs.close(who, bead, store, closeguard.guard_for(who, store, git, repos.repo_root()), reason)


def guard(who: Identity, git: Git, store: Beads) -> verbs.Guard:
    """The close guard of the repo of the current directory (what `tl bd close` runs before bd does)."""
    return closeguard.guard_for(who, store, git, repos.repo_root())


def cmd_land(bead: BeadId, sha: str, worktree: str | None, who: Identity, git: Git, store: Beads) -> int:
    """`tl land ID --sha SHA`: the sha must be on the repo's base (origin/main unless its profile names another)."""
    repo = str(Path(worktree).resolve()) if worktree else repos.repo_root()
    return closeguard.record_land(who, store, git, repo, repos.default_base(repo, git), bead, sha, f"tl land: {sha[:12]} is on the base")
