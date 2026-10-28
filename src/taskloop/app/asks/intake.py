"""What the owner says to the engine, as typed records. A bd comment has no type, so prose never acts: an answer is an AskAnswer on the ask,
a hint, a hold or an override is a metadata key on the bead. Each verb leaves a receipt comment for people reading the bead; the engine
neither reads nor counts receipts as input, and parse() only labels them."""
import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from taskloop.app.asks import sweeps
from taskloop.contracts.ask import Ask, AskAction, AskAnswer
from taskloop.contracts.ports import BdFailure, BeadPatch, Beads
from taskloop.contracts.stores import AskStore

HINT: Final = "owner_hint"
HOLD: Final = "owner_hold"
OVERRIDE: Final = "owner_override"
OVERRIDES: Final = ("replan-cap",)
VERBS: Final = ("answer", "hint", "hold", "override", "decision")
RECEIPT: Final = "Owner (tl) "
# What the engine writes into a bead (comments, and lines of Notes). It is never the owner's: not in the brief, not in the brief hash,
# not in the snapshot an amend diffs against, not in an answer. A receipt is ours too.
ENGINE_PREFIXES: Final = ("Plan (engine", "Review (engine", "Reflect (engine", "Blocked:", "Ask (engine", "Evidence (engine",
                          "Parked (engine", "Lane (engine", "Verify (engine", "Resume (engine", "Look (engine", "Land (engine",
                          "Follow-up (engine", "Engine paused:", "Engine failed:", RECEIPT)


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

    def __init__(self, asks: AskStore, store: Beads, now: Callable[[], float], by: str) -> None:
        self.asks, self.store, self.now, self.by = asks, store, now, by

    def note(self, bead: str, text: str) -> None:
        with contextlib.suppress(BdFailure):  # the receipt is for people: the typed record is already written
            self.store.add_comment(bead, text)

    def answer(self, bead: str, action: AskAction, text: str = "", amend: bool = False) -> tuple[Ask | None, str]:
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

    def withdraw(self, bead: str, why: str) -> tuple[Ask | None, str]:
        ask = self.asks.get(bead)
        if ask is None:
            return None, "gone"
        return self.asks.withdraw(bead, ask.id, why, self.now())

    def hint(self, bead: str, text: str) -> None:
        self.store.update(bead, BeadPatch(set_metadata={HINT: text.strip()}))
        self.note(bead, receipt("hint", text.strip()))

    def hold(self, bead: str, on: bool = True) -> None:
        self.store.update(bead, BeadPatch(set_metadata={HOLD: self.by}) if on else BeadPatch(unset_metadata=[HOLD]))
        self.note(bead, receipt("hold", "" if on else "released", on="1" if on else "0"))

    def override(self, bead: str, what: str) -> None:
        if what not in OVERRIDES:
            raise ValueError("override what? one of: {}".format(", ".join(OVERRIDES)))
        self.store.update(bead, BeadPatch(set_metadata={OVERRIDE: what}))
        self.note(bead, receipt("override", what))
