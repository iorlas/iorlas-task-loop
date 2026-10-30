"""What `tl prune` does to build trees: a worktree under the build dir whose HEAD is on origin/main and that has no change, and a local
release/* branch on origin/main. Never --force; a tree git keeps, or one used in the last `days`, stays with its reason."""
import contextlib
from pathlib import Path

from taskloop.app.release import tidy
from taskloop.app.release.shell import REAL, Shell
from taskloop.contracts.paths import RepoDirs


def main_repo(p: Path) -> Path | None:
    """The main checkout a path belongs to, from its `.git` entry alone (no git process is started in a folder that may be no repo of
    ours): the folder itself when `.git` is one, else the repo a worktree's `.git` file points into (<repo>/.git/worktrees/<name>)."""
    if (p / ".git").is_dir():
        return p.resolve()
    try:
        text = (p / ".git").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    admin = Path(text.removeprefix("gitdir:").strip())
    if text.startswith("gitdir:") and admin.parent.name == "worktrees" and admin.parent.parent.name == ".git":
        return admin.parent.parent.parent.resolve()
    return None


def last_used(d: Path, sh: Shell) -> float:
    """When git last moved HEAD or the index of this worktree (its own admin folder), 0 when unknown."""
    r = sh.run(["git", "rev-parse", "--absolute-git-dir"], d, check=False)
    admin = Path(r.stdout.strip())
    stamps = []
    for name in ("HEAD", "index", "logs/HEAD"):
        with contextlib.suppress(OSError):
            stamps.append((admin / name).stat().st_mtime)
    return max(stamps, default=0.0)


def why_kept(d: Path, days: float, now: float, sh: Shell) -> tuple[Path | None, str]:
    """(its main repo, why the tree stays; "" when it may go)."""
    repo = main_repo(d)
    if RepoDirs(d).engine_lock().exists():
        return repo, "a run holds it (engine lock)"
    if Path.cwd().resolve().is_relative_to(d.resolve()):
        return repo, "this shell is in it"
    status = sh.run(["git", "status", "--porcelain"], d, check=False)
    if status.returncode or status.stdout.strip():
        return repo, "uncommitted or untracked files" if status.returncode == 0 else "git status failed"
    if not tidy.on_base(d, "HEAD", sh):
        return repo, "not merged into origin/main"
    if now - last_used(d, sh) < days * 86400:
        return repo, f"used in the last {days:g} days"
    return repo, ""


def prune_trees(build: Path, repos: list[str], days: float, now: float, dry_run: bool, sh: Shell = REAL) -> tuple[list[str], list[str]]:
    """(removed lines, kept lines with the reason) for the worktrees directly under `build` and the release/* branches of `repos`."""
    removed: list[str] = []
    kept: list[str] = []
    known = {r for p in repos if (r := main_repo(Path(p)))}
    for d in sorted(build.iterdir()) if build.is_dir() else []:
        if not (d / ".git").is_file():
            continue  # the main checkout of a repo (a .git folder), or no worktree at all
        if main_repo(d) not in known:
            continue  # a repo task-loop was never run in: not ours to tidy, and not worth a line
        repo, why = why_kept(d, days, now, sh)
        why = why or ("" if dry_run or repo is None else tidy.remove_tree(repo, d, sh))
        (kept if why else removed).append(f"{'would remove ' if dry_run and not why else ''}worktree {d}" + (f": {why}" if why else ""))
    for repo in sorted(known):
        branches(repo, days, now, dry_run, sh, removed, kept)
    return removed, kept


def branches(repo: Path, days: float, now: float, dry_run: bool, sh: Shell, removed: list[str], kept: list[str]) -> None:
    """One plan (each release/* branch with the oid it was checked at and why it stays), then the plan: the dry run prints it, the real
    run deletes exactly the branches without a reason, each only while still at its oid."""
    held = {t.branch for t in tidy.trees(repo, sh)}
    out = sh.run(["git", "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads/release/"], repo, check=False).stdout
    plan: list[tuple[str, str, str]] = []
    for row in out.splitlines():
        b, _, oid = row.partition(" ")
        ts = sh.run(["git", "log", "-1", "--format=%ct", oid], repo, check=False).stdout.strip()
        why = ("checked out in a worktree" if b in held else "" if tidy.on_base(repo, oid, sh) else "not merged into origin/main")
        if not why and (not ts.isdigit() or now - int(ts) < days * 86400):
            why = f"its last commit is under {days:g} days old"
        plan.append((b, oid, why))
    for b, oid, reason in plan:
        why = reason or ("" if dry_run else tidy.delete_branch_at(repo, b, oid, sh))  # a commit added since on_base keeps the branch
        line = f"{'would remove ' if dry_run and not why else ''}branch {b} ({repo.name})"
        (kept if why else removed).append(line + (f": {why}" if why else ""))
