"""The push of a release: under the land lock, rebased onto an origin/main that moved, the version taken again."""
from collections.abc import Callable
from pathlib import Path

from tlkernel.paths import ConfigDir
from tlkernel.slots import SlotGitError

from taskloop.adapters import ident, landlock
from taskloop.app.release import clone
from taskloop.app.release.shell import Abort, Shell, fetch_or_abort


def release_lock_path(config: Path, url: str) -> Path:
    """The lock of the release clone: named from the clone's own directory, so every version that touches that clone takes the same
    lock (a key that changed between versions let an old caller reset the clone under a newer release mid-run, 0.23.198)."""
    return ConfigDir(config).lock_file(f"release-{clone.clone_dir(config, url).name}.lock")


def push_main(repo: Path, message: str, version: str, base: str, bump: Callable[[], str], sh: Shell) -> str:
    """Push under the land lock; a moved base is rebased and verified after releasing it.

    Every changed pre-bump tree needs its own green suite. Bounded retries refuse a perpetually moving base rather than
    running a suite while engines wait on the land lock. `base` precedes any replayed branch commits.
    """
    git = sh.port
    d = str(repo)
    url = git.remote_url(d, "origin") or d
    lock = landlock.land_lock_path(ConfigDir(ident.config_dir(sh.env)), url)
    for attempt in range(3):
        with landlock.os_lock(lock, "release: " + message, lambda who: sh.say(f"waiting for the land lock (held by {who})")):
            fetch_or_abort(git, repo)
            head = git.rev_parse(d, "origin/main")
            if not any(r.subject.startswith(version + ":") for r in git.log(d, ["HEAD"], limit=1)):
                raise Abort(f"HEAD is not the {version} commit (something reset the release clone); nothing pushed")
            if head == base:
                try:
                    git.push(d, "origin", "HEAD:main")
                    return version
                except SlotGitError as e:
                    refused = e.tail
                fetch_or_abort(git, repo)
                head = git.rev_parse(d, "origin/main")
                if head == base:
                    raise Abort("the push was refused and origin/main did not move:\n" + refused)
        if attempt == 2:
            break
        sh.say(f"push race: origin/main {head} is not the base {base}; rebasing, taking the next version, verifying again")
        git.reset(d, "HEAD~1", "hard")
        if not git.rebase(d, "origin/main", update_refs=False).ok:
            git.rebase_abort(d)
            raise Abort("the rebase onto origin/main after the push race failed")
        base = head
        version = bump()
    raise Abort("the push lost the race three times; nothing released")
