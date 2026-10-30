"""`observe`: one look at bd, the local and remote branches, the worktrees and the leases, as the typed facts `diff` judges. Reads only."""
import contextlib
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from taskloop.app.release import tidy
from taskloop.app.release.shell import REAL, Shell
from taskloop.contracts import fence
from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId, is_bead_id
from taskloop.contracts.landed import LandedStore
from taskloop.contracts.paths import ConfigDir, RepoDirs
from taskloop.contracts.ports import BdFailure, BeadQuery, Beads
from taskloop.domain.reconcile.facts import (
    BeadFact,
    Checkout,
    Lease,
    LocalBranch,
    Observed,
    RemoteBranch,
    RepoView,
    Worktree,
)
from taskloop.domain.report.matchers import land_bead

TASK = "task/"
RELEASE = "release/"


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


def bead_fact(b: Bead) -> BeadFact:
    meta = str(b.metadata.get("branch") or "")
    return BeadFact(b.id, b.status, b.assignee, meta if meta.startswith(TASK) else TASK + b.id)


def lease_of(b: Bead) -> Lease | None:
    """The lease a bead is held under, None when nobody holds it."""
    if b.status == "closed" or not b.assignee:
        return None
    return Lease(b.id, b.assignee, fence.gen_of(b), b.lease_expires_at)


def landed(repo: Path, bead: BeadId, sh: Shell, cfg: ConfigDir | None = None) -> bool:
    """The bead's landed record names a sha that is on the checkout's HEAD. LEGACY, only for a bead with no record (landed before
    0.23.179): its land commit (subject ends `(<bead>)`, not a revert) is on HEAD; this can go when no such bead is left."""
    rec = LandedStore(cfg or ConfigDir()).get(bead)
    if rec is not None:
        return sh.run(["git", "merge-base", "--is-ancestor", rec.sha, "HEAD"], repo, check=False).returncode == 0
    subject = sh.run(["git", "log", "-1", "--format=%s", "--fixed-strings", f"--grep=({bead})", "HEAD"], repo, check=False).stdout.strip()
    return land_bead(subject) == bead


def refs_of(repo: Path, prefix: str, sh: Shell) -> list[tuple[str, str]]:
    out = sh.run(["git", "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads/" + prefix], repo, check=False).stdout
    return [(b, oid) for b, _, oid in (row.partition(" ") for row in out.splitlines())]


def task_branches(repo: Path, sh: Shell) -> tuple[LocalBranch, ...]:
    merged = set(sh.run(["git", "branch", "--merged", "HEAD", "--format=%(refname:short) %(objectname)"], repo, check=False)
                 .stdout.splitlines())
    return tuple(LocalBranch(b, oid, on_head=f"{b} {oid}" in merged) for b, oid in refs_of(repo, TASK, sh))


def release_branches(repo: Path, sh: Shell) -> tuple[LocalBranch, ...]:
    found = []
    for b, oid in refs_of(repo, RELEASE, sh):
        ts = sh.run(["git", "log", "-1", "--format=%ct", oid], repo, check=False).stdout.strip()
        found.append(LocalBranch(b, oid, on_base=tidy.on_base(repo, oid, sh), last_commit=int(ts) if ts.isdigit() else 0))
    return tuple(found)


def remote_branches(repo: Path, closed: list[str], sh: Shell, cfg: ConfigDir | None) -> tuple[RemoteBranch, ...]:
    """origin's task/<bead> of each closed, landed bead, at the oid ls-remote showed (one ls-remote for the lot; an origin that does
    not answer shows nothing)."""
    ls = sh.run(["git", "ls-remote", "--heads", "origin", f"refs/heads/{TASK}*"], repo, check=False)
    there = {ref: oid for oid, _, ref in (ln.partition("\t") for ln in ls.stdout.splitlines())} if ls.returncode == 0 else {}
    found: list[RemoteBranch] = []
    for bead in closed:
        ref = f"refs/heads/{TASK}{bead}"
        if ref not in there or not is_bead_id(bead) or not landed(repo, bead, sh, cfg):
            continue
        oid = there[ref]
        known = sh.run(["git", "cat-file", "-e", oid + "^{commit}"], repo, check=False).returncode == 0
        found.append(RemoteBranch(ref, oid, known, known and tidy.on_base(repo, oid, sh, "HEAD")))
    return tuple(found)


def last_used(d: Path, sh: Shell) -> float:
    """When git last moved HEAD or the index of this worktree (its own admin folder), 0 when unknown."""
    admin = Path(sh.run(["git", "rev-parse", "--absolute-git-dir"], d, check=False).stdout.strip())
    stamps = []
    for name in ("HEAD", "index", "logs/HEAD"):
        with contextlib.suppress(OSError):
            stamps.append((admin / name).stat().st_mtime)
    return max(stamps, default=0.0)


def worktree(d: Path, repo: Path, sh: Shell) -> Worktree:
    status = sh.run(["git", "status", "--porcelain"], d, check=False)
    dirty = "" if status.returncode == 0 and not status.stdout.strip() else (
        "uncommitted or untracked files" if status.returncode == 0 else "git status failed")
    here = d.resolve()
    return Worktree(str(d), str(here), str(repo), RepoDirs(d).engine_lock().exists(), Path.cwd().resolve().is_relative_to(here),
                    dirty, tidy.on_base(d, "HEAD", sh), last_used(d, sh))


def repo_view(repo: Path, store_of: Callable[[str], Beads] | None, release: bool, sh: Shell,
              cfg: ConfigDir | None) -> tuple[RepoView, list[Lease]]:
    checkouts = tuple(Checkout(str(t.path.resolve()), t.branch) for t in tidy.trees(repo, sh))
    view = RepoView(str(repo), repo.name, checkouts, release_branches=release_branches(repo, sh) if release else ())
    if store_of is None:
        return view, []
    try:
        beads = store_of(str(repo)).find(BeadQuery(include_closed=True))
    except (BdFailure, SystemExit, OSError) as e:
        return replace(view, bd_down=str(getattr(e, "error", e))[:80]), []
    facts = tuple(bead_fact(b) for b in beads)
    closed = sorted({f.id for f in facts if f.status == "closed"})
    leases = [ls for b in beads if (ls := lease_of(b))]
    return replace(view, beads=facts, task_branches=task_branches(repo, sh), remotes=remote_branches(repo, closed, sh, cfg)), leases


def observe(repos: list[str], store_of: Callable[[str], Beads] | None, build: Path | None, keep_days: float, now: float,
            sh: Shell = REAL, cfg: ConfigDir | None = None) -> Observed:
    """The world once. `store_of` None: bd and the task branches are not looked at; `build` None: no build trees and no release/*
    branches."""
    known = sorted({r for p in repos if (r := main_repo(Path(p)))})
    views: list[RepoView] = []
    leases: list[Lease] = []
    for repo in known:
        v, ls = repo_view(repo, store_of, build is not None, sh, cfg)
        views.append(v)
        leases += ls
    trees: list[Worktree] = []
    for d in sorted(build.iterdir()) if build is not None and build.is_dir() else []:
        # a main checkout (a .git folder) or a worktree of a repo we never ran in is not ours to tidy
        if (d / ".git").is_file() and (repo := main_repo(d)) in known:
            trees.append(worktree(d, repo, sh))
    return Observed(now, keep_days, tuple(views), tuple(trees), tuple(leases))
