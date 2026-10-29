"""What leaves the machine at a land besides the commit: the push argv (no repo hook runs there), the LFS objects of the pushed ref
before the push, and bd's Dolt data after it. The repo's hooks are not the land's gate: every check belongs in the profile."""
import os
import shutil
from pathlib import Path
from typing import Any

from taskloop.domain.land.matchers import lfs_in, no_dolt_remote


def is_push(argv: list[str]) -> bool:
    return len(argv) > 1 and os.path.basename(argv[0]) == "git" and argv[1] == "push"


def land_argv(land: list[str]) -> list[str]:
    """The land command as run: a `git push` gets --no-verify (the repo's pre-push hook is not the land's); any other command is the
    repo's own and owns its hooks."""
    return [*land[:2], "--no-verify", *land[2:]] if is_push(land) and "--no-verify" not in land else list(land)


def target(land: list[str]) -> tuple[str, list[str]] | None:
    """(remote, the refs pushed) from a `git push` argv; HEAD:main pushes HEAD. None for a custom command."""
    if not is_push(land):
        return None
    pos = [a for a in land[2:] if not a.startswith("-")]
    refs = [p.lstrip("+").partition(":")[0] or "HEAD" for p in pos[1:]]
    return (pos[0] if pos else "origin"), (refs or ["HEAD"])


def uses_lfs(wt: Any) -> bool:
    try:
        return lfs_in((Path(wt) / ".gitattributes").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False


class Outbound:
    def __init__(self, host: Any) -> None:
        self.e = host

    def lfs_push(self) -> tuple[int, str]:
        """In the lock, right before the push: `git lfs push <remote> <refs>` for the pushed refs only, when the repo uses LFS and the
        land is a `git push`. -> (exit code, tail). A repo that needs LFS on a box without git-lfs is a fault, branch kept."""
        e = self.e
        want = target(e.cfg.land)
        if want is None or not uses_lfs(e.wt):
            return 0, ""
        if shutil.which("git-lfs") is None:
            raise e.blocked_for("failed: .gitattributes puts files in Git LFS but git-lfs is not installed here (install git-lfs); "
                                "branch kept", "FAULT_LAND")
        argv = ["git", "lfs", "push", want[0], *want[1]]
        t0 = e.clock.monotonic()
        rc, tail = e.sh(argv, pin=True)
        e.log.note(f"{' '.join(argv)}: {'ok' if rc == 0 else 'failed'} in {e.clock.monotonic() - t0:.1f}s")
        return rc, tail

    def bd_sync(self, sha: str) -> None:
        """After the land, outside the lock: the Dolt push bd's own hook makes. No remote is a quiet no-op; a failure blocks the bead
        (tl-7y6.21: a warning let a box that cannot reach the remote keep every bead to itself). The rerun finds the land, pushes again."""
        e = self.e
        t0 = e.clock.monotonic()
        try:
            rc, text = e.store.dolt_push()
        except Exception as err:  # bd itself failed: the same block, the land stands
            rc, text = 1, str(err)
        if rc != 0 and no_dolt_remote(text):
            return
        e.log.note(f"bd dolt push: {'ok' if rc == 0 else 'failed'} in {e.clock.monotonic() - t0:.1f}s")
        if rc != 0:
            raise e.blocked_for(f"failed: landed {sha[:12]}, but bd dolt push after the land failed (fix bd's Dolt remote, then rerun: "
                                f"the rerun finds the land and pushes again)\n{text.strip()[-400:]}", "FAULT_LAND")
