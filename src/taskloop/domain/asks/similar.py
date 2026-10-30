"""Repeat detection: the typed key of an ask and what it matches. No model call and no fuzzy score: two asks are the same question when
they have the same class and the same set of significant words, so a hit is explainable by comparing two strings."""
from collections.abc import Iterable
from typing import Final

from taskloop.contracts.ask import SimilarRef
from taskloop.contracts.enums import AskClass
from taskloop.contracts.ledger import Adr, LedgerEntry
from taskloop.domain.asks.matchers import words

STOP: Final = frozenset({
    "the", "and", "for", "how", "can", "this", "that", "with", "are", "was", "were", "what", "which", "should", "would", "could", "does",
    "did", "not", "you", "your", "its", "from", "into", "than", "then", "them", "they", "has", "have", "had", "been", "being", "bead",
    "beads", "engine"})
KEY_WORDS: Final = 12


def key_of(ask_class: AskClass, question: str) -> str:
    """`<class>:<up to 12 distinct significant words of the question, sorted>`; '' when the question has none."""
    kept = sorted({w for w in words(question) if w not in STOP})[:KEY_WORDS]
    return f"{ask_class.value}:{' '.join(kept)}" if kept else ""


def find(key: str, ask: str, ledger: Iterable[LedgerEntry], adrs: Iterable[Adr]) -> list[SimilarRef]:
    """The past asks (newest first, each ask once, answered ones only: an unanswered ask teaches nothing) and the ADRs with this key."""
    if not key:
        return []
    answered = {e.ask for e in ledger if e.event == "answer"}
    seen: list[str] = []
    for e in sorted(ledger, key=lambda e: -e.t):
        if e.key == key and e.ask != ask and e.ask in answered and e.ask not in seen:
            seen.append(e.ask)
    return [SimilarRef(kind="adr", id=a.id) for a in adrs if a.key == key] + [SimilarRef(kind="ask", id=i) for i in seen[:3]]
