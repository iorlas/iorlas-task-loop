"""`observe_commits`: the commits on task/<bead> and wip/* branches that are not on the base, as the facts `diff.findings` classes.
Reads only, through the Git port, the landed records, bd (status_of) and the engine's traces."""
from collections.abc import Callable, Sequence

from tlkernel import lifecyclematchers as matchers
from tlkernel.branches import TASK
from tlkernel.enums import Outcome
from tlkernel.gitport import Git
from tlkernel.ids import BeadId, is_bead_id
from tlkernel.landed import Landed
from tlkernel.slots import MissingRevision, SlotGitError
from tlkernel.trace import RunTrace

from taskloop.domain.reconcile.lost import BranchCommit

LANDS = Callable[[str], list[float]]


def bases_of(git: Git, repo: str, base: str) -> list[str]:
    """The base and its local or remote twin, those that exist: a stale local main must not hide a land on origin."""
    twin = base[len("origin/"):] if base.startswith("origin/") else "origin/" + base
    found: list[str] = []
    for n in (base, twin):
        try:
            if git.rev_parse(repo, n + "^{commit}"):
                found.append(n)
        except MissingRevision:
            continue
    return found


def on_a_base(git: Git, repo: str, sha: str, bases: list[str]) -> bool:
    """Report whether a recorded sha reached a base; deleted or unknown revisions supply no match."""
    for b in bases:
        try:
            if git.is_ancestor(repo, sha, b):
                return True
        except MissingRevision:
            continue
    return False


def legacy_lands(git: Git, repo: str, bases: list[str], traces: Sequence[RunTrace]) -> dict[str, list[int]]:
    """LEGACY (a bead landed before landed/<bead>.json, 0.23.179): bead -> times its land reached the base, by the subject
    '... (<bead>)' (committer time, which a rebase rewrites) and the sha a trace recorded. Used only for a bead with no record;
    it can go when no such bead is left."""
    lands: dict[str, list[int]] = {}
    for row in git.log(repo, bases):
        bead = matchers.land_bead(row.subject)
        if bead:
            lands.setdefault(bead, []).append(row.time)
    for r in traces:
        if r.outcome is Outcome.LANDED and r.sha and on_a_base(git, repo, r.sha, bases):
            lands.setdefault(r.bead, []).append(int(r.ended))
    return lands


def lands_of(git: Git, repo: str, bases: list[str], landed_of: Callable[[BeadId], Landed | None], legacy: dict[str, list[int]]) -> LANDS:
    """bead -> times its land reached the base: the landed record when it has one and its sha is on a base; else the legacy table."""
    def of(bead: str) -> list[float]:
        rec = landed_of(BeadId(bead)) if is_bead_id(bead) else None
        if rec is None:
            return list(legacy.get(bead, []))
        return [rec.t] if on_a_base(git, repo, rec.sha, bases) else []
    return of


def observe_commits(git: Git, repo: str, base: str, since: float | None, status_of: Callable[[BeadId], str | None],
                    traces: Sequence[RunTrace], landed_of: Callable[[BeadId], Landed | None]) -> tuple[BranchCommit, ...]:
    bases = bases_of(git, repo, base) or [base]
    lands = lands_of(git, repo, bases, landed_of, legacy_lands(git, repo, bases, traces))
    statuses: dict[str, str | None] = {}
    found: list[BranchCommit] = []
    for ref in (r.name.removeprefix("refs/heads/") for r in git.for_each_ref(repo, f"refs/heads/{TASK}", "refs/heads/wip/")):
        bead, aside = matchers.unstale(ref[len(TASK):]) if ref.startswith(TASK) else (None, False)
        rows = git.log(repo, [ref], bases)
        if not rows:
            continue
        try:
            upstream = {p.oid for p in git.cherry(repo, bases[0], ref) if p.upstream}
        except SlotGitError:
            upstream = set()
        for row in rows:
            if since is not None and row.time < since:
                continue
            state: str | None = None
            if bead and bead not in statuses:
                statuses[bead] = status_of(bead) if is_bead_id(bead) else None
            if bead:
                state = statuses[bead]
            runs = tuple((r.started, str(r.run)) for r in traces if bead and r.bead == bead)
            found.append(BranchCommit(ref, bead, row.oid, row.time, row.subject, bases[0], aside, row.oid in upstream,
                                      tuple(lands(bead)) if bead else (), state, runs))
    return tuple(found)
