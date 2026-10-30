"""What the owner says to the engine, as typed records. A bd comment has no type, so prose never acts: an answer is an AskAnswer on the ask,
a hint, a hold or an override is a metadata key on the bead. Each verb leaves a receipt comment for people reading the bead; the engine
neither reads nor counts receipts as input, and parse() only labels them."""
import contextlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from taskloop.app.asks import looks, stick, sweeps
from taskloop.contracts.adrs import AdrStore
from taskloop.contracts.ask import Ask, AskAction, AskAnswer, ThreadEntry
from taskloop.contracts.dash import OwnerCause, Stick
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdFailure, BeadPatch, Beads
from taskloop.contracts.stores import AskStore
from taskloop.domain import timespec

HINT: Final = "owner_hint"
HOLD: Final = "owner_hold"
HOLD_UNTIL: Final = "owner_hold_until"  # epoch seconds; absent = until released
WAIVERS: Final = "owner_waivers"  # JSON list of Waiver: what the owner waived, deferred or dropped, with the quoted approval
WAIVER_KINDS: Final = ("waive", "defer", "drop")
OVERRIDE: Final = "owner_override"
OVERRIDES: Final = ("replan-cap",)
CAUSE: Final = "owner_cause"  # JSON {scope, cause, t, by}: why a run stopped or an ask was asked, per the owner; scope = a run or ask id
ACK: Final = "owner_ack"  # JSON {scope, t, by}: the owner has seen the stuck run `scope`; the key is unset when the owner takes it back
VERBS: Final = ("answer", "hint", "hold", "override", "decision", "look", "cause", "ack", "stick", "askback")
ASK_WHY: Final = {"gone": "This ask no longer exists.", "withdrawn": "The engine withdrew this ask.", "closed": "This ask is closed.",
                  "superseded": "The engine asked again for this bead; the new ask replaces this one.",
                  "consumed": "A run already used the answer."}
RECEIPT: Final = "Owner (tl) "
# What the engine writes into a bead (comments, and lines of Notes). It is never the owner's: not in the brief, not in the brief hash,
# not in the snapshot an amend diffs against, not in an answer. A receipt is ours too.
ENGINE_PREFIXES: Final = ("Plan (engine", "Review (engine", "Reflect (engine", "Blocked:", "Ask (engine", "Evidence (engine",
                          "Parked (engine", "Lane (engine", "Verify (engine", "Resume (engine", "Look (engine", "Land (engine",
                          "Follow-up (engine", "Engine paused:", "Engine failed:", RECEIPT)


def parse_until(text: str, now: float) -> float:
    """Epoch seconds of what the owner typed after --until (ValueError when it is not a future time)."""
    return timespec.parse_future(text, datetime.fromtimestamp(now).astimezone())


def held(meta: Mapping[str, str], now: float) -> str:
    """Who holds the bead ("" when nobody): a hold with an `until` ends when that time passes, one without lasts until released."""
    who = (meta.get(HOLD) or "")
    until = float(meta.get(HOLD_UNTIL) or 0)
    return who if who and (not until or until > now) else ""


@dataclass(frozen=True)
class Parsed:
    kind: str  # answer, hint, hold, override, decision (a receipt of that verb), engine (the engine's own), note (everything else)
    fields: dict[str, str] = field(default_factory=dict)
    body: str = ""


def engine_written(text: str) -> bool:
    return (text or "").lstrip().startswith(ENGINE_PREFIXES)


def receipt(verb: str, body: str = "", **fields: str) -> str:
    head = " ".join([f"{RECEIPT}{verb}"] + ["{}={}".format(*kv) for kv in fields.items()])
    return f"{head}: {body}" if body else head


def parse(comment: str) -> Parsed:
    """(kind, fields, body) of a comment. Only a receipt of ours has a verb; the engine's comments are `engine`; anything else, whatever it
    says and however it is worded, is a `note`. Nothing is ever done because of how a note reads."""
    text = (comment or "").strip()
    if text.startswith(RECEIPT):
        head, _sep, body = text[len(RECEIPT):].partition(": ")
        words = head.split()
        verb = words[0] if words else ""
        if verb in VERBS:
            return Parsed(verb, dict(w.split("=", 1) for w in words[1:] if "=" in w), body.strip())
    return Parsed("engine" if engine_written(text) else "note", {}, text)


class Intake:
    """The owner's verbs for one repo's tracker. `by` is who says it."""

    def __init__(self, asks: AskStore, store: Beads, now: Callable[[], float], by: str, adrs: Callable[[str], AdrStore] | None = None,
                 factory: Callable[[], Beads | None] | None = None) -> None:
        """`adrs(repo)` is the decision store of a repo, `factory()` the tracker of the task-loop repo (None: none registered)."""
        self.asks, self.store, self.now, self.by = asks, store, now, by
        self.adrs, self.factory = adrs, factory

    def note(self, bead: BeadId, text: str) -> None:
        with contextlib.suppress(BdFailure):  # the receipt is for people: the typed record is already written
            self.store.add_comment(bead, text)

    def answer(self, bead: BeadId, action: AskAction, text: str = "", amend: bool = False) -> tuple[Ask | None, str]:
        """File the answer on the bead's ask, open the bead for the loop. -> (the ask, "" or why it cannot be answered)."""
        ask = self.asks.get(bead)
        if ask is None:
            # a bead parked on an ask that was dropped at upgrade: "rerun" is how the owner has it asked again
            if action == "rerun" and bead in self.asks.orphans() and sweeps.reopen(self.asks, self.store, bead):
                return None, ""
            return None, "gone"
        given = AskAnswer(action=action, text=text.strip(), t=self.now(), by=self.by)
        done, why = (self.asks.amend if amend else self.asks.answer)(bead, ask.id, given)
        if why:
            return done, why
        with contextlib.suppress(BdFailure):  # the loop's own reopen takes a blocked bead whose ask is answered
            self.store.update(bead, BeadPatch(status="open"))
        self.note(bead, receipt("answer", given.text, ask=ask.id, action=action))
        return done, ""

    def withdraw(self, bead: BeadId, why: str) -> tuple[Ask | None, str]:
        ask = self.asks.get(bead)
        if ask is None:
            return None, "gone"
        return self.asks.withdraw(bead, ask.id, why, self.now())

    def hint(self, bead: BeadId, text: str) -> None:
        self.store.update(bead, BeadPatch(set_metadata={HINT: text.strip()}))
        self.note(bead, receipt("hint", text.strip()))

    def hold(self, bead: BeadId, on: bool = True, until: float = 0.0) -> None:
        """Keep the loop off a bead (until `until`, or until released); the loop reads the keys, the receipt is for people."""
        if on:
            patch = BeadPatch(set_metadata={HOLD: self.by, **({HOLD_UNTIL: f"{until:.0f}"} if until else {})},
                              unset_metadata=[] if until else [HOLD_UNTIL])
        else:
            patch = BeadPatch(unset_metadata=[HOLD, HOLD_UNTIL])
        self.store.update(bead, patch)
        self.note(bead, receipt("hold", "" if on else "released", on="1" if on else "0", **({"until": f"{until:.0f}"} if until else {})))

    def waive(self, bead: BeadId, kind: str, criterion: str, approval: str) -> None:
        """Waive, defer or drop one acceptance criterion. The owner's own words must come with it: an empty quote is refused, because a
        relayed 'he said it is fine' is how a criterion was lost on 10-21."""
        if kind not in WAIVER_KINDS:
            raise ValueError("override: one of --{}".format(", --".join(WAIVER_KINDS)))
        if not criterion.strip() or not approval.strip():
            raise ValueError(f"override --{kind} needs the criterion and --approval with the owner's own words, quoted")
        found = self.store.show(bead)
        have: list[dict[str, object]] = json.loads(found.metadata.get(WAIVERS) or "[]") if found else []
        have.append({"kind": kind, "criterion": criterion.strip(), "approval": approval.strip(), "t": self.now(), "by": self.by})
        self.store.update(bead, BeadPatch(set_metadata={WAIVERS: json.dumps(have)}))
        self.note(bead, receipt("override", f"{kind} {criterion.strip()} - approved: {approval.strip()}", what=kind))

    def override(self, bead: BeadId, what: str) -> None:
        if what not in OVERRIDES:
            raise ValueError("override what? one of: {}".format(", ".join(OVERRIDES)))
        self.store.update(bead, BeadPatch(set_metadata={OVERRIDE: what}))
        self.note(bead, receipt("override", what))

    def look(self, item: str, verdict: str, note: str = "", look_bead: str = "") -> tuple[str, str]:
        """Answer one look item (good, redo with a note, or undo). -> (the item's status after, "" or why nothing changed)."""
        return looks.answer(self.store, item, verdict, note, self.now(), look_bead)

    def cause(self, bead: BeadId, scope: str, cause: str) -> str:
        """Record why a run stopped or an ask was asked, for `scope` (a run id or an ask id). -> "" or why it was refused."""
        if cause not in {c.value for c in OwnerCause}:
            return f"unknown cause {cause!r}"
        if not scope:
            return "no run or ask to give a cause to"
        said = {"scope": scope, "cause": cause, "t": self.now(), "by": self.by}
        self.store.update(bead, BeadPatch(set_metadata={CAUSE: json.dumps(said)}))
        self.asks.correct_cause(bead, scope, OwnerCause(cause), self.now())  # no-op unless `scope` is an ask the ledger knows
        self.note(bead, receipt("cause", cause, scope=scope))
        return ""

    def stick(self, ask_id: str, outcome: Stick, text: str = "") -> str:
        """Turn an answered ask into what the owner chose (an ADR, a factory bead, a fix of the bead text, a link to a decision, or just
        a record). Works from the ledger, so it also holds for an ask a newer one replaced. -> "" or why it was refused."""
        rows = self.asks.history(ask_id)
        raised = next((r for r in rows if r.event == "raise"), None)
        answered = next((r for r in reversed(rows) if r.event == "answer"), None)
        if raised is None:
            return "this ask is not in the ledger"
        if answered is None:
            return "answer the ask first"
        if rows[-1].outcome is outcome:
            return ""  # already done: a second tap files nothing twice
        made, why = stick.decide(stick.Effects(self.adrs, self.factory, self.store), raised, answered, outcome, text, self.by, self.now())
        if why:
            return why
        self.asks.stuck(raised.bead, ask_id, outcome, made, self.now())
        self.note(raised.bead, receipt("stick", made, ask=ask_id, outcome=outcome.value))
        return ""

    def prune(self, repo: str, adr: str) -> str:
        """Retire a decision in force of `repo` (kept in the store, marked with who and when). -> "" or why not."""
        if self.adrs is None:
            return "there is no decision store here"
        return self.adrs(repo).retire(adr, self.by, self.now())

    def ask_back(self, bead: BeadId, ask_id: str, text: str) -> str:
        """The owner asks back instead of answering: the entry joins the ask's thread and the ask stays open. -> "" or why not."""
        if not text.strip():
            return "write the question first"
        _done, why = self.asks.say(bead, ask_id, ThreadEntry(by="owner", t=self.now(), md=text.strip()))
        return ASK_WHY.get(why, why)

    def ack(self, bead: BeadId, scope: str, on: bool = True) -> str:
        """The owner has seen that run `scope` is stuck (or takes that back). -> "" or why it was refused."""
        if on and not scope:
            return "no run to acknowledge"
        seen = {ACK: json.dumps({"scope": scope, "t": self.now(), "by": self.by})}
        self.store.update(bead, BeadPatch(set_metadata=seen) if on else BeadPatch(unset_metadata=[ACK]))
        self.note(bead, receipt("ack", "" if on else "taken back", on="1" if on else "0", scope=scope))
        return ""
