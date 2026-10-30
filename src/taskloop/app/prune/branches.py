"""What `tl prune` does to landed task branches: a local task/* branch of a closed bead, in a registered repo's main checkout, goes with
`git update-ref -d` at the oid the plan checked (a branch that moved stays, with git's reason). The one remote ref it deletes is
origin's task/<bead> (the engine's work-in-progress push, tl-7y6.22) of a closed bead whose land commit is on the checkout's HEAD, with
a lease on the oid the plan saw. No other ref, no other tool's branch."""
from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Step:
    """One ref of the plan: what it is, the oid it was checked at, and why it stays ("" when it goes)."""
    repo: Path
    ref: str  # refs/heads/task/<x>
    oid: str
    why: str
    remote: bool

    @property
    def line(self) -> str:
        return f"{'remote ' if self.remote else ''}branch {self.ref.removeprefix('refs/heads/')} ({self.repo.name})"


def plan_branches(repos: list[str], store_of: Callable[[str], Beads], sh: Shell, kept: list[str]) -> list[Step]:
    """The plan for the task/* refs of the main checkouts of `repos`: computed once; the dry run prints it, the real run executes it."""
    steps: list[Step] = []
    for repo in sorted({r for p in repos if (r := main_repo(Path(p)))}):
        fmt = "--format=%(refname:short) %(objectname)"
        out = sh.run(["git", "for-each-ref", fmt, "refs/heads/" + PREFIX], repo, check=False).stdout.splitlines()
        try:
            closed = closed_branches(repo, store_of(str(repo)))
        except (BdFailure, SystemExit, OSError) as e:
            kept.append(f"task branches of {repo.name}: bd did not answer ({str(getattr(e, 'error', e))[:80]})")
            continue
        steps += remote_steps(repo, sorted(set(closed.values())), sh)
        held = {t.branch for t in tidy.trees(repo, sh)}
        merged = set(sh.run(["git", "branch", "--merged", "HEAD", "--format=%(refname:short) %(objectname)"], repo, check=False)
                     .stdout.splitlines())
        for row in out:
            b, _, oid = row.partition(" ")
            why = "" if b in closed else "its bead is not closed (or unknown)"
            if not why and b in held:
                why = "checked out in a worktree"
            if not why and row not in merged:
                why = "not merged"
            steps.append(Step(repo, "refs/heads/" + b, oid, why, False))
    return steps


def prune_branches(repos: list[str], store_of: Callable[[str], Beads], dry_run: bool, sh: Shell = REAL) -> tuple[list[str], list[str]]:
    """(removed lines, kept lines with the reason) for the task/* branches of the main checkouts of `repos`. Each ref goes only while
    it is still at the oid the plan checked."""
    removed: list[str] = []
    kept: list[str] = []
    for st in plan_branches(repos, store_of, sh, kept):
        why = st.why
        if not why and not dry_run:
            gone = tidy.delete_remote_at if st.remote else tidy.delete_branch_at
            why = gone(st.repo, st.ref if st.remote else st.ref.removeprefix("refs/heads/"), st.oid, sh)
        line = f"{'would remove ' if dry_run and not why else ''}{st.line}"
        (kept if why else removed).append(line + (f": {why}" if why else ""))
    return removed, kept


def landed(repo: Path, bead: str, sh: Shell) -> bool:
    """The bead's land commit (subject ends `(<bead>)`) is on the checkout's HEAD."""
    subject = sh.run(["git", "log", "-1", "--format=%s", "--fixed-strings", f"--grep=({bead})", "HEAD"], repo, check=False).stdout.strip()
    return land_bead(subject) == bead


def remote_steps(repo: Path, beads: list[str], sh: Shell) -> list[Step]:
    """origin's task/<bead> of each closed, landed bead, at the oid ls-remote showed (one ls-remote for the lot; an origin that does
    not answer plans nothing). The oid is known here: a ref that holds commits HEAD lacks (when git has them) stays."""
    ls = sh.run(["git", "ls-remote", "--heads", "origin", f"refs/heads/{PREFIX}*"], repo, check=False)
    there = {ref: oid for oid, _, ref in (ln.partition("\t") for ln in ls.stdout.splitlines())} if ls.returncode == 0 else {}
    steps: list[Step] = []
    for bead in beads:
        ref = f"refs/heads/{PREFIX}{bead}"
        if ref not in there or not landed(repo, bead, sh):
            continue
        oid = there[ref]
        known = sh.run(["git", "cat-file", "-e", oid + "^{commit}"], repo, check=False).returncode == 0
        why = "" if not known or tidy.on_base(repo, oid, sh, "HEAD") else "origin's branch has commits that are not on HEAD"
        steps.append(Step(repo, ref, oid, why, True))
    return steps
