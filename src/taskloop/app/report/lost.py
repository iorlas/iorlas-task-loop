"""`tl lost`: the bead-branch commits no run will bring home, classed. Reads only."""
from collections.abc import Callable
from typing import Any

from taskloop.adapters import ident
from taskloop.adapters.gitenv import run_git
from taskloop.app.report.inputs import bases_of, bead_status, git, repo_traces
from taskloop.contracts.landed import LandedStore
from taskloop.contracts.paths import ConfigDir
from taskloop.domain.report import matchers


def _legacy_lands(repo: str, bases: list[str], traces: list[dict[str, Any]]) -> dict[str, list[int]]:
    """LEGACY (a bead landed before landed/<bead>.json, 0.23.179): bead -> times its land reached the base, by the subject
    '... (<bead>)' (committer time, which a rebase rewrites) and the sha a trace recorded. Used only for a bead with no record;
    it can go when no such bead is left."""
    lands: dict[str, list[int]] = {}
    for ln in git(repo, "log", "--format=%ct %s", *bases).splitlines():
        t, _, subj = ln.partition(" ")
        bead = matchers.land_bead(subj)
        if bead and t.isdigit():
            lands.setdefault(bead, []).append(int(t))
    for r in traces:
        if r.get("outcome") == "landed" and r.get("sha") and any(
                run_git(repo, "merge-base", "--is-ancestor", r["sha"], b,
                           capture_output=True).returncode == 0 for b in bases):
            lands.setdefault(str(r.get("bead")), []).append(r.get("ended") or 0)
    return lands


def _lands(repo: str, bases: list[str], store: LandedStore, legacy: dict[str, list[int]]) -> Callable[[str], list[float]]:
    """bead -> times its land reached the base: the landed record when it has one and its sha is on a base; else the legacy table."""
    def of(bead: str) -> list[float]:
        rec = store.get(bead)
        if rec is None:
            return list(legacy.get(bead, []))
        reached = any(run_git(repo, "merge-base", "--is-ancestor", rec.sha, b, capture_output=True).returncode == 0 for b in bases)
        return [rec.t] if reached else []
    return of


def _pending_class(bead: str, st: str | None, ct: int, traces: list[dict[str, Any]]) -> dict[str, str]:
    """The class and why of a commit whose bead is not landed: from the bead's state `st` ('?' unknown, '' absent)."""
    later = [r for r in traces if r.get("bead") == bead and (r.get("started") or 0) >= ct]
    if st == "?":
        return {"class": "unknown", "why": f"bd could not show {bead}: the tracker is unreachable"}
    if st == "closed":
        return {"class": "lost", "why": f"{bead} is closed and never landed this commit"}
    if not st:
        return {"class": "lost", "why": f"no bead {bead} in the tracker"}
    if later:
        return {"class": "reclaimed", "why": "run {} took it up".format(later[0].get("run"))}
    return {"class": "pending", "why": f"{bead} is {st}: its next run continues the branch"}


def lost_work(repo: str, base: str, since: float | None = None, status_of: Callable[[str], str | None] | None = None,
              traces: list[dict[str, Any]] | None = None, cfg: ConfigDir | None = None) -> list[dict[str, Any]]:
    """Every commit on a task/<bead> or wip/* branch that is not on the base, classed:
    landed     its patch is on the base (git cherry), or a land of its bead came after it: the bead's landed record (its sha on
               the base; legacy beads without one: a base commit titled '... (<bead>)' or a trace's land sha);
    reclaimed  a later run of the bead started after it (the engine continues the branch);
    superseded it is on a task/<bead>-stale-<time> branch --fresh set aside: the bead started again on the base;
    pending    its bead is still open, blocked or in progress: the next run continues the branch;
    unknown    bd failed, so the bead's state cannot be told (listed, never counted as lost);
    lost       its bead is closed (or unknown) with no land after it, or it is on a wip/* branch of a dead session."""
    bases = bases_of(repo, base) or [base]
    status_of = status_of or (lambda b: bead_status(b, repo))
    traces = repo_traces(repo) if traces is None else traces
    lands = _lands(repo, bases, LandedStore(cfg or ConfigDir(ident.config_dir())), _legacy_lands(repo, bases, traces))
    rows: list[dict[str, Any]] = []
    statuses: dict[str, str | None] = {}
    refs = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/task/", "refs/heads/wip/").splitlines()
    for ref in refs:
        bead, aside = matchers.unstale(ref[len("task/"):]) if ref.startswith("task/") else (None, False)
        log = git(repo, "log", "--format=%H %ct %s", ref, "--not", *bases)
        if not log:
            continue
        upstream = {ln[2:] for ln in git(repo, "cherry", bases[0], ref).splitlines() if ln.startswith("- ")}
        for ln in log.splitlines():
            sha, ct, subj = ([*ln.split(" ", 2), "", ""])[:3]
            ct = int(ct)
            if since is not None and ct < since:
                continue
            row = {"branch": ref, "bead": bead, "sha": sha, "time": ct, "subject": subj}
            if sha in upstream:
                row.update({"class": "landed", "why": f"its patch is on {bases[0]}"})
            elif bead and any(t >= ct for t in lands(bead)):
                row.update({"class": "landed", "why": f"{bead} landed on {bases[0]} after it"})
            elif aside:
                row.update({"class": "superseded", "why": f"--fresh set {ref} aside: {bead} started again on {bases[0]}"})
            elif not bead:
                row.update({"class": "lost", "why": f"a dead session's work on {ref}: no bead, no run takes it"})
            else:
                if bead not in statuses:
                    statuses[bead] = status_of(bead)
                row.update(_pending_class(bead, statuses[bead], ct, traces))
            rows.append(row)
    return rows

