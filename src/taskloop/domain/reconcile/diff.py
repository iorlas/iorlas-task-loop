"""`diff`: the observed state to the actions that tidy it. Pure: no git, no bd, no process, so a table of states tests it."""
from taskloop.domain.reconcile.facts import (
    Action,
    BeadFact,
    DeleteBranch,
    DeleteRemote,
    Keep,
    LocalBranch,
    Observed,
    RemoveTree,
    RepoView,
    Worktree,
)
from taskloop.domain.reconcile.lost import Finding, classify

DAY = 86400


def tree_why(t: Worktree, days: float, now: float) -> str:
    """Why a build tree stays, "" when it may go."""
    if t.run_holds:
        return "a run holds it (engine lock)"
    if t.shell_in:
        return "this shell is in it"
    if t.dirty:
        return t.dirty
    if not t.on_base:
        return "not merged into origin/main"
    if now - t.last_used < days * DAY:
        return f"used in the last {days:g} days"
    return ""


def held_why(r: RepoView, b: LocalBranch, going: set[str]) -> tuple[str, tuple[str, ...]]:
    """("checked out in a worktree" while a worktree the plan keeps has it, the plan's trees that hold it)."""
    hs = [c.path for c in r.checkouts if c.branch == b.name]
    return ("checked out in a worktree" if any(h not in going for h in hs) else ""), tuple(h for h in hs if h in going)


def release_actions(r: RepoView, days: float, now: float, going: set[str]) -> list[Action]:
    acts: list[Action] = []
    for b in r.release_branches:
        why, after = held_why(r, b, going)
        if not why and not b.on_base:
            why = "not merged into origin/main"
        if not why and (not b.last_commit or now - b.last_commit < days * DAY):
            why = f"its last commit is under {days:g} days old"
        acts.append(Keep(f"branch {b.name} ({r.name})", why) if why else DeleteBranch(r.path, r.name, b.name, b.oid, after))
    return acts


def closed_branches(beads: tuple[BeadFact, ...]) -> set[str]:
    return {b.branch for b in beads if b.status == "closed"}


def task_actions(r: RepoView, going: set[str]) -> list[Action]:
    if r.bd_down:
        return [Keep(f"task branches of {r.name}", f"bd did not answer ({r.bd_down})")]
    closed = closed_branches(r.beads)
    acts: list[Action] = []
    for rb in r.remotes:
        why = "" if not rb.known or rb.on_head else "origin's branch has commits that are not on HEAD"
        acts.append(Keep(f"remote branch {rb.ref.removeprefix('refs/heads/')} ({r.name})", why) if why
                    else DeleteRemote(r.path, r.name, rb.ref, rb.oid))
    for b in r.task_branches:
        held, after = held_why(r, b, going)
        why = ("" if b.name in closed else "its bead is not closed (or unknown)") or held or ("" if b.on_head else "not merged")
        acts.append(Keep(f"branch {b.name} ({r.name})", why) if why else DeleteBranch(r.path, r.name, b.name, b.oid, after))
    return acts


def diff(o: Observed) -> list[Action]:
    """Trees first, then each repo's release/* branches, then each repo's task branches (remote before local). Every ref carries the
    oid it was seen at; a branch held only by trees the plan removes goes after them."""
    acts: list[Action] = []
    going: set[str] = set()
    for t in o.trees:
        why = tree_why(t, o.keep_days, o.now)
        if why:
            acts.append(Keep(f"worktree {t.path}", why))
        else:
            going.add(t.key)
            acts.append(RemoveTree(t.repo, t.path, t.key))
    for r in o.repos:
        acts += release_actions(r, o.keep_days, o.now, going)
    for r in o.repos:
        acts += task_actions(r, going)
    return acts


def findings(o: Observed) -> list[Finding]:
    """The class of every observed bead-branch commit (landed, superseded, reclaimed, pending, unknown, lost), in the order seen."""
    return [classify(c) for c in o.commits]
