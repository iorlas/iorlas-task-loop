"""The push of a release: under the land lock, rebased onto an origin/main that moved, the version taken again."""
from collections.abc import Callable
from pathlib import Path

from taskloop.adapters import landlock
from taskloop.app.release import clone
from taskloop.app.release.shell import Abort, Shell, fetch_or_abort
from taskloop.contracts.slots import SlotGitError


def release_lock_path(config: Path, url: str) -> Path:
    """The lock of the release clone: named from the clone's own directory, so every version that touches that clone takes the same
    lock (a key that changed between versions let an old caller reset the clone under a newer release mid-run, 0.23.198)."""
    return config / "locks" / f"release-{clone.clone_dir(config, url).name}.lock"


def push_main(repo: Path, message: str, version: str, base: str, bump: Callable[[], str], sh: Shell) -> str:
    """Push, under the land lock (an engine lands only while it holds it): an origin/main that moved since the bump (a land during the
    suite) is rebased onto, the version taken again (`bump` verifies, bumps and commits) and the suite run again, then pushed while no
    land can get in. A push refused all the same (one that skipped the lock) gets one more round. `base` is the origin/main the bump
    was built on: HEAD~1 is not, --from-branch puts the branch's commits between them."""
    git = sh.port
    d = str(repo)
    url = git.remote_url(d, "origin") or d
    with landlock.os_lock(landlock.land_lock_path(url), "release: " + message,
                          lambda who: sh.say(f"waiting for the land lock (held by {who})")):
        for _ in range(2):
            fetch_or_abort(git, repo)
            head = git.rev_parse(d, "origin/main")
            if head != base:
                sh.say(f"push race: origin/main {head} is not the base {base}; rebasing, taking the next version, verifying again")
                git.reset(d, "HEAD~1", "hard")
                if not git.rebase(d, "origin/main", update_refs=False).ok:
                    git.rebase_abort(d)
                    raise Abort("the rebase onto origin/main after the push race failed")
                base = head
                version = bump()
            if not any(r.subject.startswith(version + ":") for r in git.log(d, ["HEAD"], limit=1)):
                raise Abort(f"HEAD is not the {version} commit (something reset the release clone); nothing pushed")
            try:
                git.push(d, "origin", "HEAD:main")
                return version
            except SlotGitError as e:
                refused = e.tail
            fetch_or_abort(git, repo)
            if git.rev_parse(d, "origin/main") == base:
                raise Abort("the push was refused and origin/main did not move:\n" + refused)
    raise Abort("the push lost the race twice, the land lock held; nothing released")
