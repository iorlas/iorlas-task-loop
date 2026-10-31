"""The close guard: a task, feature or bug bead that has an engine run or a task branch is closed only with a land on record, or a typed
reason. One function (`refusal`) decides; every close goes through it: `tl close`, `tl bd close`, the release's close. The engine's own
close after its run passes `ENGINE`: that run is the record.

A land on record is a LANDED row in traces.jsonl (the engine writes one per landed run; `record_land` writes the same row for a land by
hand). Typed reasons: duplicate, wontfix, superseded, epic, manual-landed-with-sha:<sha> (the sha must be an ancestor of the base; it is
then recorded as the land, exactly as `tl land` records one)."""
import time
from typing import Final

from taskloop.app.track import verbs
from taskloop.app.track.verbs import Guard
from taskloop.app.wire import slots as wslots
from taskloop.contracts.enums import Outcome
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId, RunId
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.ports import BdFailure, Beads, Git
from taskloop.contracts.stores import TraceStore
from taskloop.contracts.trace import RunTrace

ENGINE: Final[Guard] = lambda bead, reason: ""  # noqa: E731  the engine's own close: its run is the record
GATED: Final = ("task", "feature", "bug")
FREE: Final = ("duplicate", "wontfix", "superseded", "epic")
MANUAL: Final = "manual-landed-with-sha:"
TASK: Final = "task/"


def reason_head(reason: str) -> str:
    return reason.strip().split(None, 1)[0].rstrip(":,;.") if reason.strip() else ""


def manual_sha(reason: str) -> str:
    """The sha a `manual-landed-with-sha:<sha> ...` reason names; "" for any other reason."""
    head = reason.strip().split(None, 1)[0] if reason.strip() else ""
    return head.removeprefix(MANUAL) if head.startswith(MANUAL) else ""


def has_land(who: Identity, bead: BeadId) -> bool:
    return any(i.rec.bead == bead and i.rec.outcome is Outcome.LANDED for i in TraceStore(who.config).read_from(0).items)


def has_work(who: Identity, git: Git, repo: str, bead: BeadId) -> bool:
    """An engine run of the bead, or its task branch (local or origin's, as last fetched)."""
    if RunLocator(who.config).of_bead(bead):
        return True
    return bool(git.for_each_ref(repo, f"refs/heads/{TASK}{bead}", f"refs/remotes/origin/{TASK}{bead}"))


def record_land(who: Identity, store: Beads, git: Git, repo: str, base: str, bead: BeadId, sha: str, why: str) -> int:
    """`tl land`'s record (event and provenance, the sha only when it is on `base`), then the LANDED row of traces.jsonl."""
    rc = verbs.land(who, bead, sha, store, git, repo, base)
    if rc == 0:
        full = git.rev_parse(repo, sha + "^{commit}") or sha
        now = time.time()
        TraceStore(who.config).append(RunTrace(
            run=RunId.new(now), bead=bead, repo_url=git.remote_url(repo, "origin") or repo, worktree=repo, branch="",
            coordinator_session=who.session, started=now, ended=now, outcome=Outcome.LANDED, why=why, sha=full, repo_path=repo))
    return rc


def fix(bead: str) -> str:
    return (f"tl land {bead} --sha SHA   (when the work is on the base), or: "
            f"tl bd close {bead} --reason 'manual-landed-with-sha:<sha> <why>', or a typed reason: "
            f"tl bd close {bead} --reason 'duplicate|wontfix|superseded|epic <why>'")


def refusal(who: Identity, store: Beads, git: Git, repo: str, bead: BeadId, reason: str) -> str:
    """"" when the close may go on; else the refusal, naming the fix. A manual-landed-with-sha reason is checked and recorded here."""
    try:
        found = store.show(bead)
    except BdFailure:
        return ""  # bd itself will say what is wrong with the close
    if found is None or found.issue_type not in GATED or reason_head(reason) in FREE:
        return ""
    if sha := manual_sha(reason):
        return manual(who, store, git, repo, bead, sha)
    if has_land(who, bead) or not has_work(who, git, repo, bead):
        return ""
    return f"{bead} has an engine run or a task branch and no land on record: not closed. Fix: " + fix(bead)


def manual(who: Identity, store: Beads, git: Git, repo: str, bead: BeadId, sha: str) -> str:
    """manual-landed-with-sha: the sha must be on the base; it is then recorded as the land."""
    base = wslots.load_cfg(repo, git).base
    if record_land(who, store, git, repo, base, bead, sha, f"manual-landed-with-sha: {sha[:12]} is on {base}") == 0:
        return ""
    return f"{bead}: {sha[:12]} is not an ancestor of {base}: not a land. Fix: tl land {bead} --sha SHA with a sha that is."


def guard_for(who: Identity, store: Beads, git: Git, repo: str) -> Guard:
    return lambda bead, reason: refusal(who, store, git, repo, bead, reason)


def close_released(who: Identity, store: Beads, git: Git, where: str, bead: BeadId, reason: str, version: str) -> str:
    """A release closes its bead: the pushed commit (HEAD of the release clone `where`, on its origin/main) is recorded as the land, then
    the close goes through the guard. -> "" when the bead is closed, else why not."""
    sha = git.rev_parse(where, "HEAD")
    if record_land(who, store, git, where, "origin/main", bead, sha, f"release {version}") != 0:
        return f"the release of {bead} is not on origin/main: land not recorded"
    if why := guard_for(who, store, git, where)(bead, reason):
        return why
    try:
        store.close(bead, reason)
    except BdFailure as e:
        return e.error.text[-300:]
    return ""
