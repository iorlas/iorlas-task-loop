"""What `tl prune` does to landed task branches: a local task/* branch of a closed bead, in a registered repo's main checkout, goes with
`git branch -d` alone (git's own refusal keeps it, with its reason). No remote ref, no other tool's branch."""
from collections.abc import Callable
from pathlib import Path

from taskloop.app.prune.trees import main_repo
from taskloop.app.release import tidy
from taskloop.app.release.shell import REAL, Shell
from taskloop.contracts.ports import BdFailure, BeadQuery, Beads

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
        if not out:
            continue
        try:
            closed = closed_branches(repo, store_of(str(repo)))
        except (BdFailure, SystemExit, OSError) as e:
            kept.append(f"task branches of {repo.name}: bd did not answer ({str(getattr(e, 'error', e))[:80]})")
            continue
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
