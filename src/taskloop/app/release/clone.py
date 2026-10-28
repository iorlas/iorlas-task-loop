"""The release's own clone of the repo: <config>/release/<origin hash>/. The tool resets it as it likes; the main checkout, dirty or on
any branch, is never touched."""
import hashlib
from pathlib import Path

from taskloop.app.release.shell import REAL, Abort, Shell


def clone_dir(config: Path, url: str) -> Path:
    return config / "release" / hashlib.sha1(url.encode()).hexdigest()[:12]


def ready(config: Path, url: str, sh: Shell = REAL) -> Path:
    """The clone, made on first use, then fetched and put on origin/main with nothing left over from an earlier release."""
    where = clone_dir(config, url)
    if not (where / ".git").exists():
        where.parent.mkdir(parents=True, exist_ok=True)
        sh.run(["git", "clone", "-q", url, str(where)], where.parent)
    sh.fetch(where)
    sh.run(["git", "rebase", "--abort"], where, check=False)
    sh.git(where, "checkout", "-q", "-f", "-B", "main", "origin/main")
    sh.git(where, "clean", "-fdxq")
    return where


def replay_branch(where: Path, repo: Path, branch: str, sh: Shell = REAL) -> None:
    """The commits of `branch` (a branch of the main checkout, else its origin/ one) replayed on origin/main in the clone. The branch
    itself and its worktrees stay as they are."""
    for ref in (branch, "refs/remotes/origin/" + branch):
        if sh.run(["git", "fetch", "-q", str(repo), ref], where, check=False).returncode == 0:
            break
    else:
        raise Abort(f"{branch} is not a branch of {repo}")
    sh.git(where, "reset", "-q", "--hard", "FETCH_HEAD")
    r = sh.run(["git", "-c", "rebase.updateRefs=false", "rebase", "-q", "origin/main"], where, check=False)
    if r.returncode:
        sh.run(["git", "rebase", "--abort"], where, check=False)
        raise Abort(f"{branch} does not rebase onto origin/main; nothing released\n{(r.stdout + r.stderr).strip()[-600:]}")
