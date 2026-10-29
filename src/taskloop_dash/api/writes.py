"""POST /api/<verb>: the owner's writes as typed requests (contracts.dash.WRITES) and one Result back. Each is an in-process Port call,
never a process or a bd argv. A refused write is Result(ok=false) with status 200; a body that is not the verb's record is 400, an
unknown verb 404. Every verb is routed to a Port (one with no backend answers a Result that says so). park, stop and note name the
bead's newest run; the engine acts on them at its next step boundary (stop at once, through its stop flag)."""

from collections.abc import Callable
from typing import Any, Final

from taskloop.contracts import wire
from taskloop.contracts.ask import Ask, AskAction
from taskloop.contracts.dash import WRITES, AckReq, AnswerReq, BeadReq, CauseReq, LookReq, NoteReq, PruneReq, Result, StickReq
from taskloop.contracts.stores import AskStore
from taskloop_dash.api.looks import Looks
from taskloop_dash.env import Env
from taskloop_dash.readers.beads import Beads
from taskloop_dash.readers.records import Records
from taskloop_dash.views import names

Reply = tuple[int, dict[str, Any]]
LATER: Final = Result(ok=False, message="Not available yet.")
NO_PROJECT: Final = Result(ok=False, message="That project is not registered.")
PROBLEMS: Final = {
    "withdrawn": "The engine withdrew this ask. Nothing to answer.",
    "closed": "This ask is closed: its bead is closed or gone. Nothing to answer.",
    "consumed": "A run already used the answer to this ask; comment on the bead to say more.",
    "answered": "This ask is already answered.",
    "superseded": "The engine asked again for this bead; the new ask replaces this one.",
}


def words(a: Ask, option: int | None, text: str) -> tuple[AskAction, str]:
    """(action, text) of an answer: `option` picks one of the ask's own options (its typed action and text, the owner's words added);
    otherwise the words are a text answer. An option that is not one of the ask's counts as none."""
    text = text.strip()
    if option is not None and 0 <= option < len(a.options):
        o = a.options[option]
        return o.action, " ".join(x for x in (o.text or (o.label if o.action == "text" else ""), text) if x)
    return "text", text


def refused(why: str) -> Result:
    """Why an ask cannot be answered, as the page shows it."""
    return Result(ok=False, message=PROBLEMS.get(why, "This ask no longer exists."))


class Writes:
    def __init__(self, env: Env, records: Records, beads: Beads, looks: Looks) -> None:
        self.env, self.records, self.beads, self.looks = env, records, beads, looks
        self.store = AskStore.at(env.config)
        self.verbs: dict[str, Callable[[Any], Result]] = {"answer": self.answer, "look": self.look, "cause": self.cause, "ack": self.ack,
                                                          "park": self.park, "stop": self.stop, "note": self.note, "stick": self.stick,
                                                          "prune": self.prune}

    def post(self, verb: str, body: object) -> Reply:
        cls = WRITES.get(verb)
        if cls is None:
            return 404, {"error": "unknown verb"}
        try:
            req = wire.load(cls, body)
        except ValueError as err:
            return 400, {"error": str(err)}
        self.env.touch()
        write = self.verbs.get(verb)
        return 200, wire.dump(write(req) if write else LATER)

    def find(self, ask_id: str) -> tuple[Ask | None, str]:
        """(the ask, "") when `ask_id` is the bead's current ask, else (the bead's ask or None, why not)."""
        bead = ask_id.rsplit("-", 1)[0]
        if not bead or "/" in bead or ".." in bead:
            return None, "gone"
        return self.store.state(bead, ask_id)

    def repo_of(self, project: str) -> str:
        return self.beads.resolve_repo(project, "")

    def run_of(self, bead: str) -> str:
        """The newest run of the bead: what a cause or an ack is about when no ask is named."""
        logs = self.records.engine_logs(retain=False).get(bead, []) if names.is_bead_id(bead) else []
        return names.run_name(logs[-1]) if logs else ""

    def answer(self, req: AnswerReq) -> Result:
        """File the answer on the ask: an option by its 0-based index, or the owner's words. An answered ask no run has used is amended.
        An ask back (kind ask_back) joins the ask's thread and leaves it open; no helper answers it yet."""
        a, why = self.find(req.ask)
        if a is None or why not in ("", "answered"):
            return refused(why)
        if req.kind == "ask_back":
            return self.env.ports.ask_back(a.repo, a.bead, a.id, req.text)
        if req.option is not None and not 0 <= req.option < len(a.options):
            return Result(ok=False, message="That option is not one of this ask's options.")
        action, text = words(a, req.option, req.text)
        if not text and action == "text":
            return Result(ok=False, message="Write an answer first.")
        try:
            _done, problem = self.env.ports.answer(a.repo, a.bead, action, text, why == "answered")
        except OSError as err:
            return Result(ok=False, message=f"The dashboard cannot run bd ({err.strerror}). Nothing was changed.")
        return refused(problem) if problem else Result(ok=True)

    def prune(self, req: PruneReq) -> Result:
        """Retire a decision in force: the plan stage stops reading it and the page drops it from the list."""
        repo = self.repo_of(req.project)
        return self.env.ports.prune(repo, req.adr) if repo else NO_PROJECT

    def stick(self, req: StickReq) -> Result:
        """Make an answered ask stick. The ask may be one a newer ask replaced, so the repo is the project's, the ask is the ledger's."""
        repo = self.repo_of(req.project)
        return self.env.ports.stick(repo, req.ask, req.outcome.value, req.text) if repo else NO_PROJECT

    def look(self, req: LookReq) -> Result:
        repo = self.repo_of(req.project)
        return self.looks.answer(repo, req.bead, req.verdict, req.note) if repo else NO_PROJECT

    def cause(self, req: CauseReq) -> Result:
        repo = self.repo_of(req.project)
        if not repo:
            return NO_PROJECT
        return self.env.ports.cause(repo, req.bead, req.ask or self.run_of(req.bead), req.cause.value)

    def ack(self, req: AckReq) -> Result:
        repo = self.repo_of(req.project)
        if not repo:
            return NO_PROJECT
        return self.env.ports.ack(repo, req.bead, self.run_of(req.bead), req.ack)

    def park(self, req: BeadReq) -> Result:
        repo = self.repo_of(req.project)
        return self.env.ports.park(repo, req.bead, self.run_of(req.bead)) if repo else NO_PROJECT

    def stop(self, req: BeadReq) -> Result:
        repo = self.repo_of(req.project)
        return self.env.ports.stop(repo, req.bead, self.run_of(req.bead)) if repo else NO_PROJECT

    def note(self, req: NoteReq) -> Result:
        repo = self.repo_of(req.project)
        return self.env.ports.note(repo, req.bead, self.run_of(req.bead), req.text) if repo else NO_PROJECT
