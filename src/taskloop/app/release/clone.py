"""The release's own clone of the repo: <config>/release/<origin hash>/. The tool resets it as it likes; the main checkout, dirty or on
any branch, is never touched. Its git goes through the Git port."""
import hashlib
from pathlib import Path

from taskloop.app.release.shell import Abort, Shell, fetch_or_abort
from taskloop.contracts.slots import SlotGitError


def clone_dir(config: Path, url: str) -> Path:
    return config / "release" / hashlib.sha1(url.encode()).hexdigest()[:12]


def ready(config: Path, url: str, sh: Shell) -> Path:
    """The clone, made on first use, then fetched and put on origin/main with nothing left over from an earlier release."""
    git = sh.port
    where = clone_dir(config, url)
    if not (where / ".git").exists():
        where.parent.mkdir(parents=True, exist_ok=True)
        try:
            git.clone(url, str(where))
        except SlotGitError as e:
            raise Abort(f"git clone {url} failed:\n{e.tail}") from None
    fetch_or_abort(git, where)
    git.rebase_abort(str(where))
    try:
        git.checkout_force(str(where), "main", "origin/main")
        git.clean(str(where), [], ignored=True)
    except SlotGitError as e:
        raise Abort(f"git failed in {where}:\n{e.tail}") from None
    return where


def replay_branch(where: Path, repo: Path, branch: str, sh: Shell) -> None:
    """The commits of `branch` (a branch of the main checkout, else its origin/ one) replayed on origin/main in the clone. The branch
    itself and its worktrees stay as they are."""
    git = sh.port
    for ref in (branch, "refs/remotes/origin/" + branch):
        try:
            git.fetch_ref(str(where), str(repo), ref)
            break
        except SlotGitError:
            continue
    else:
        raise Abort(f"{branch} is not a branch of {repo}")
    try:
        git.reset(str(where), "FETCH_HEAD", "hard")
    except SlotGitError as e:
        raise Abort(f"git reset failed in {where}:\n{e.tail}") from None
    r = git.rebase(str(where), "origin/main", update_refs=False)
    if not r.ok:
        git.rebase_abort(str(where))
        raise Abort(f"{branch} does not rebase onto origin/main; nothing released\n{r.output[-600:]}")
