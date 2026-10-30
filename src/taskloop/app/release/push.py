"""The push of a release: under the land lock, rebased onto an origin/main that moved, the version taken again."""
from collections.abc import Callable
from pathlib import Path

from taskloop.adapters import landlock
from taskloop.app.release.shell import REAL, Abort, Shell


def release_lock_path(config: Path, url: str) -> Path:
    return config / "locks" / f"release-{landlock.lock_key(url)}.lock"


def push_main(repo: Path, message: str, version: str, base: str, bump: Callable[[], str], sh: Shell = REAL) -> str:
    """Push, under the land lock (an engine lands only while it holds it): an origin/main that moved since the bump (a land during the
    suite) is rebased onto, the version taken again (`bump` verifies, bumps and commits) and the suite run again, then pushed while no
    land can get in. A push refused all the same (one that skipped the lock) gets one more round. `base` is the origin/main the bump
    was built on: HEAD~1 is not, --from-branch puts the branch's commits between them."""
    url = sh.git(repo, "remote", "get-url", "origin", check=False) or str(repo)
    with landlock.os_lock(landlock.land_lock_path(url), "release: " + message,
                          lambda who: sh.say(f"waiting for the land lock (held by {who})")):
        for _ in range(2):
            sh.fetch(repo)
            head = sh.git(repo, "rev-parse", "origin/main")
            if head != base:
                sh.say(f"push race: origin/main {head} is not the base {base}; rebasing, taking the next version, verifying again")
                sh.git(repo, "reset", "-q", "--hard", "HEAD~1")
                if sh.run(["git", "-c", "rebase.updateRefs=false", "rebase", "-q", "origin/main"], repo, check=False).returncode:
                    sh.run(["git", "rebase", "--abort"], repo, check=False)
                    raise Abort("the rebase onto origin/main after the push race failed")
                base = head
                version = bump()
            r = sh.run(["git", "push", "-q", "origin", "HEAD:main"], repo, check=False)
            if not r.returncode:
                return version
            sh.fetch(repo)
            if sh.git(repo, "rev-parse", "origin/main") == base:
                raise Abort("the push was refused and origin/main did not move:\n" + r.stderr)
    raise Abort("the push lost the race twice, the land lock held; nothing released")
