"""`tl close` and `tl bd close` as a person runs them: from the repo of the current directory, through the close guard
(app/wire/closeguard.py). `tl land` is cli/land.py."""
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

