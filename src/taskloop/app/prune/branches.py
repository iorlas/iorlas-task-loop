"""What `tl prune` does to landed task branches: a local task/* branch of a closed bead, in a registered repo's main checkout, goes with
`git branch -d` alone (git's own refusal keeps it, with its reason). The one remote ref it deletes is origin's task/<bead> (the engine's
work-in-progress push, tl-7y6.22) of a closed bead whose land commit is on the checkout's HEAD. No other ref, no other tool's branch."""
from collections.abc import Callable
from pathlib import Path

from taskloop.app.prune.trees import main_repo
from taskloop.app.release import tidy
from taskloop.app.release.shell import REAL, Shell
from taskloop.contracts.ports import BdFailure, BeadQuery, Beads
from taskloop.domain.report.matchers import land_bead

PREFIX = "task/"


def closed_branches(repo: Path, store: Beads) -> dict[str, str]:
    """{local branch the engine names: the closed bead it belongs to}: task/<bead>, or the bead's metadata branch when that is task/*."""
    found: dict[str, str] = {}
    for b in store.find(BeadQuery(status="closed", include_closed=True)):
        if b.status == "closed":
            meta = str(b.metadata.get("branch") or "")
            found[meta if meta.startswith(PREFIX) else PREFIX + b.id] = b.id
    return found


def prune_branches(repos: list[str], store_of: Callable[[str], Beads], dry_run: bool, sh: Shell = REAL) -> tuple[list[str], list[str]]:
    """(removed lines, kept lines with the reason) for the task/* branches of the main checkouts of `repos`."""
    removed: list[str] = []
    kept: list[str] = []
    for repo in sorted({r for p in repos if (r := main_repo(Path(p)))}):
        out = sh.run(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/" + PREFIX], repo, check=False).stdout.split()
        try:
            closed = closed_branches(repo, store_of(str(repo)))
        except (BdFailure, SystemExit, OSError) as e:
            kept.append(f"task branches of {repo.name}: bd did not answer ({str(getattr(e, 'error', e))[:80]})")
            continue
        removed += remote_lines(repo, sorted(set(closed.values())), dry_run, sh, kept)
        held = {t.branch for t in tidy.trees(repo, sh)}
        merged = set(sh.run(["git", "branch", "--merged", "HEAD", "--format=%(refname:short)"], repo, check=False).stdout.split())
        for b in out:
            why = "" if b in closed else "its bead is not closed (or unknown)"
            if not why and b in held:
                why = "checked out in a worktree"
            if not why and dry_run and b not in merged:
                why = "not merged"
            if not why and not dry_run:
                r = sh.run(["git", "branch", "-d", b], repo, check=False)
                why = "" if r.returncode == 0 else (r.stderr.strip().splitlines() or ["git branch -d failed"])[0].removeprefix("error: ")
            line = f"{'would remove ' if dry_run and not why else ''}branch {b} ({repo.name})"
            (kept if why else removed).append(line + (f": {why}" if why else ""))
    return removed, kept


def landed(repo: Path, bead: str, sh: Shell) -> bool:
    """The bead's land commit (subject ends `(<bead>)`) is on the checkout's HEAD."""
    subject = sh.run(["git", "log", "-1", "--format=%s", "--fixed-strings", f"--grep=({bead})", "HEAD"], repo, check=False).stdout.strip()
    return land_bead(subject) == bead


def remote_lines(repo: Path, beads: list[str], dry_run: bool, sh: Shell, kept: list[str]) -> list[str]:
    """origin's task/<bead> of each closed, landed bead goes with `git push origin --delete`, only when that ref exists there (one
    ls-remote for the lot; an origin that does not answer deletes nothing)."""
    ls = sh.run(["git", "ls-remote", "--heads", "origin", f"refs/heads/{PREFIX}*"], repo, check=False)
    there = {ln.split("\t")[-1] for ln in ls.stdout.splitlines()} if ls.returncode == 0 else set()
    gone: list[str] = []
    for bead in beads:
        ref = f"refs/heads/{PREFIX}{bead}"
        if ref not in there or not landed(repo, bead, sh):
            continue
        line = f"remote branch {PREFIX}{bead} ({repo.name})"
        if dry_run:
            gone.append("would remove " + line)
            continue
        r = sh.run(["git", "push", "origin", "--delete", ref], repo, check=False)
        if r.returncode == 0:
            gone.append(line)
        else:
            kept.append(f"{line}: {(r.stderr.strip().splitlines() or ['git push --delete failed'])[-1]}")
    return gone
