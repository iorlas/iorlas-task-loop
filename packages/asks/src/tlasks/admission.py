"""Admission of a bead before a run: release dead claims, honor holds and questions, and reopen retries."""
import time
from collections.abc import Callable

from tlkernel import askparks as parks
from tlkernel import holds as hold
from tlkernel.askenums import AskStatus
from tlkernel.bead import Bead
from tlkernel.beadsport import BdFailure, BeadPatch, Beads
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.locator import RunLocator
from tlkernel.parks import ParkStore
from tlkernel.paths import ConfigDir
from tlkernel.planbrief import owner_written

from tlasks.contracts.records import AsksHost


def release_dead(h: AsksHost, repo: str, git: Git, who: Identity, store: Beads | None = None, *,
                 release: Callable[[str, Beads, dict[BeadId, str], str, float], list[str]],
                 running_now: Callable[[str, Git, Identity, Beads | None], dict[BeadId, str]],
                 say: Callable[[str], None]) -> None:
    """The reconcile sweep's lease rules, before a run takes its bead: a dead run's claim (a crashed or paused one, a restarted session's
    old actor) is given back by the same rule `tl prune` and the loop's step use."""
    for line in release(repo, store or h.bd(who.actor, repo), running_now(repo, git, who, store),
        h.hostname(), time.time()):
        say(line)


def _foreign_claim(b: Bead, repo: str, git: Git, who: Identity, store: Beads, fresh: bool = False, *,
                   running_now: Callable[[str, Git, Identity, Beads | None], dict[BeadId, str]]) -> str:
    """Why another actor's claim on the bead stops a run-task, "" when it does not: the sweep already gave back every dead one, so a claim
    that is left is live (a lease running, or a run on it). A blocked bead is the actor's still: it goes only when its engine is gone;
    so does any claim the owner's --fresh asks for (tl-159): the check is per bead (is an engine on THIS bead), never per actor."""
    bead_id, holder = b.id, b.assignee
    if not holder.startswith("tl-"):
        return f"claimed by {holder}"
    if (b.status == "blocked" or fresh) and bead_id not in running_now(repo, git, who, store):
        return ""
    logs = [b.log for b in RunLocator(who.config).of_bead(bead_id) if b.log.exists()]
    return f"another run of {bead_id} is still running as {holder} (a live claim)" + (f"; its engine log: {logs[-1]}" if logs else "")


def _blocked_by_engine(h: AsksHost, b: Bead, store: Beads, home: ConfigDir, owner_author: str) -> str:
    """Why a bead the engine blocked stays blocked ("" when a plain retry may reopen it)."""
    bead_id = b.id
    held = [d.id for d in b.dependencies if d.type == "blocks" and d.status != "closed"]
    if held:
        return "blocked by {}".format(", ".join(held))
    cs = store.comments(bead_id)
    blocks = [c for c in cs if hold.engine_written(c) and c.text.startswith("Blocked:")]
    if not blocks:
        return "blocked by a person, not by the engine"
    after = [c for c in cs if c.created_at > blocks[-1].created_at and owner_written(c, owner_author)]
    ask = h.asks_store(home).get(bead_id)
    asking = ask is not None and ask.consumed is None and ask.status in (AskStatus.OPEN, AskStatus.PARKED, AskStatus.ANSWERED)
    if ask is not None and asking and ask.answer is not None:  # tl-gy4: an answer filed on the ask (dashboard, tl ask answer) is an answer
        after, asking = after[:0], False  # whether or not a comment followed the block; the run's check_ask consumes it
    if ask is not None and asking and not after:
        return f"waiting for the answer to ask {ask.id} ({ask.kind.value})"
    if after and not asking:
        return "{} commented after the engine blocked it; read that first".format(after[-1].author or "someone")
    return ""


def admit(h: AsksHost, bead_id: BeadId, repo: str, git: Git, who: Identity, store: Beads | None = None, at: float | None = None,
          fresh: bool = False, owner_author: str = "", *,
          running_now: Callable[[str, Git, Identity, Beads | None], dict[BeadId, str]]) -> tuple[bool, str]:
    """(ok, why): whether run-task may take the bead, never taking what a person holds. A bead the engine blocked is reopened for a
    plain retry, or when a comment after the block answers the open ask; it stays blocked when a person commented after the block with
    no ask open (they may have parked it), while an ask waits unanswered, or while another bead blocks it. A claim by another actor
    that is still live stops it (dead ones are given back by `release_dead`, the reconcile lease rules, which runs first); `fresh` (the
    owner's rerun) also takes a claim whose lease still runs when no engine is on the bead."""
    store = store or h.bd(who.actor, repo)
    b = h.peek(store, bead_id) or Bead(id=bead_id, title="", status="")
    holder, me = b.assignee, who.actor
    if hold.held(b.metadata, at or time.time()):
        return False, f"held by the owner ({b.metadata[hold.HOLD]}): `tl hold {bead_id} --release` lets it go"
    if holder and holder != me:
        why = _foreign_claim(b, repo, git, who, store, fresh, running_now=running_now)
        if why:
            return False, why
    takeover = bool(fresh and holder and holder != me)  # _foreign_claim let it through: no engine runs the bead
    if b.status != "blocked" and not takeover:
        return True, ""
    why = _blocked_by_engine(h, b, store, who.config, owner_author) if b.status == "blocked" else ""
    if why:
        return False, why
    # tl-kwo: only if the claim is still the one just read (bd applies --if-assignee atomically): two loops looking at one freed bead
    # must not both reopen and then both claim
    guard = bool(holder and holder != me)
    try:
        store.update(bead_id, BeadPatch(status="open", if_assignee=holder if guard else "", assignee=""))
    except BdFailure:
        if guard:
            return False, f"the claim of {bead_id} changed hands just now ({holder} no longer holds it): not taken"
    return True, "reopened"


def parked(h: AsksHost, bead_id: BeadId, fresh: bool, repo: str, who: Identity, store: Beads | None = None) -> str:
    """Why run-task will not take a bead whose run ended on a question ("" when it may): its text is unchanged (--fresh or an answer
    lets it run), or this would be the third run on that text (nothing does). An answered ask starts the count again (tl-7y6.7.3)."""
    b = h.peek(store or h.bd(who.actor, repo), bead_id)
    cfg = who.config
    verdict = parks.gate(h.asks_store(cfg), cfg, b, fresh=fresh, store=ParkStore, now=time.time()) if b else None
    if b and verdict is None:
        parks.entering(h.asks_store(cfg), cfg, b, store=ParkStore)
    return verdict.why if verdict else ""
