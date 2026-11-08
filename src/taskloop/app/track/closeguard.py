"""The close guard: a task, feature or bug bead that has an engine run or a task branch is closed only with a land on record, or a typed
reason. One function (`refusal`) decides; every close goes through it: `tl close`, `tl task close`, the release's close. The engine's own
close after its run passes `ENGINE`: that run is the record.

A land on record is a LANDED row in traces.jsonl (the engine writes one per landed run; `record_land` writes the same row for a land by
hand). Typed reasons: duplicate, wontfix, superseded, epic, manual-landed-with-sha:<sha> (the sha must be an ancestor of the base; it is
then recorded as the land, exactly as `tl land` records one)."""
import time
from collections.abc import Callable
from typing import Final

from tlkernel.beadsport import BdFailure, Beads
from tlkernel.branches import TASK
from tlkernel.enums import Outcome, Result
from tlkernel.finish import finish_run
from tlkernel.finish_projection import history
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.locator import RunLocator
from tlkernel.run import RunFinish, RunState
from tlkernel.slots import git_probe
from tlpipeline.api import closeguard

from taskloop.app.track import verbs
from taskloop.app.track.verbs import Guard
from taskloop.stores.real import real_stores

ENGINE: Final[Guard] = lambda bead, reason: ""  # noqa: E731  the engine's own close: its run is the record

def has_land(who: Identity, bead: BeadId) -> bool:
    return any(i.rec.bead == bead and i.rec.outcome is Outcome.LANDED for i in real_stores(who.config).traces.read_from(0).items)


def has_work(who: Identity, git: Git, repo: str, bead: BeadId) -> bool:
    """An engine run of the bead, or its task branch (local or origin's, as last fetched)."""
    if RunLocator(who.config).of_bead(bead):
        return True
    return bool(git.for_each_ref(repo, f"refs/heads/{TASK}{bead}", f"refs/remotes/origin/{TASK}{bead}"))


def record_land(who: Identity, store: Beads, git: Git, repo: str, base: str, bead: BeadId, sha: str, why: str,
                *, run: str = "") -> int:
    """`tl land`'s record (event and provenance, the sha only when it is on `base`), then the LANDED row of traces.jsonl."""
    rc = verbs.land(who, bead, sha, store, git, repo, base)
    if rc == 0:
        full = git.rev_parse(repo, sha + "^{commit}") or sha
        now = time.time()
        run = run or RunLocator(who.config).create(repo, bead, now, mode="stage:land",
                                                  owner=who.actor, session=who.session).run
        url = git_probe(lambda: git.remote_url(repo, "origin"), "") or repo
        done = RunFinish(state=RunState.DONE, ended=now, outcome=Outcome.LANDED, result=Result.LANDED,
                         kind=Kind.LANDED.value, why=why, sha=full)
        finish_run(who.config, run, done,
                   lambda m, r: history(who.config, m, r, repo_url=url))
    return rc



def refusal(who: Identity, store: Beads, git: Git, repo: str, bead: BeadId, reason: str, *, base_of: Callable[[str, Git], str]) -> str:
    """"" when the close may go on; else the refusal, naming the fix. A manual-landed-with-sha reason is checked and recorded here."""
    try:
        found = store.show(bead)
    except BdFailure:
        return ""  # bd itself will say what is wrong with the close
    return closeguard.refusal(bead, reason, found.issue_type if found else None,
                              has_land=lambda: has_land(who, bead), has_work=lambda: has_work(who, git, repo, bead),
                              manual=lambda sha: manual(who, store, git, repo, bead, sha, base_of=base_of))


def manual(who: Identity, store: Beads, git: Git, repo: str, bead: BeadId, sha: str, *, base_of: Callable[[str, Git], str]) -> str:
    """manual-landed-with-sha: the sha must be on the base; it is then recorded as the land."""
    base = base_of(repo, git)
    if record_land(who, store, git, repo, base, bead, sha, f"manual-landed-with-sha: {sha[:12]} is on {base}") == 0:
        return ""
    return f"{bead}: {sha[:12]} is not an ancestor of {base}: not a land. Fix: tl land {bead} --sha SHA with a sha that is."


def guard_for(who: Identity, store: Beads, git: Git, repo: str, *, base_of: Callable[[str, Git], str]) -> Guard:
    return lambda bead, reason: refusal(who, store, git, repo, bead, reason, base_of=base_of)


def close_released(who: Identity, store: Beads, git: Git, where: str, bead: BeadId, reason: str, version: str,
                   *, base_of: Callable[[str, Git], str]) -> str:
    """A release closes its bead: the pushed commit (HEAD of the release clone `where`, on its origin/main) is recorded as the land, then
    the close goes through the guard. -> "" when the bead is closed, else why not."""
    sha = git.rev_parse(where, "HEAD")
    if record_land(who, store, git, where, "origin/main", bead, sha, f"release {version}") != 0:
        return f"the release of {bead} is not on origin/main: land not recorded"
    if why := guard_for(who, store, git, where, base_of=base_of)(bead, reason):
        return why
    try:
        store.close(bead, reason)
    except BdFailure as e:
        return e.error.text[-300:]
    return ""
