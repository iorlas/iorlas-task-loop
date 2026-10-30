"""How the engine reads the kind of an unchecked item: what the engine itself does, what a check could reach, which kind wins when the
writer and the verifier differ (tl-bxk.10.28). Pure; the facts about the repo come in as arguments."""
from collections.abc import Callable, Collection
from typing import Final

from taskloop.contracts.answers import LEGACY_KINDS, ROUTED_KINDS
from taskloop.domain.review.matchers import CodeNames, EngineActions

UNCHECKED_KINDS: Final = ROUTED_KINDS + LEGACY_KINDS  # one of these unchecked is verified before the land
# a kind may move only toward a stricter route (never to a looser one): the engine settles the loosest, asks the strictest
KIND_RANK: Final = dict({"engine_step": 0, "external_fact": 1, "taste": 1, "checkable": 2, "owner_decision": 3},
                        **dict.fromkeys(LEGACY_KINDS, 2))


def engine_does(what: str, has_leftovers: bool) -> bool:
    """True when the item names an action the engine will in fact perform for this bead: file the leftovers (only if there are any),
    land, run the gate, close the bead."""
    w = " ".join(what.split())
    if EngineActions.files_beads(w):
        return has_leftovers
    return EngineActions.lands_or_closes(w)


def names_code(what: str, files: Collection[str], names: Collection[str], diff: Callable[[], str]) -> bool:
    """True when the item names something a check can reach: a repo path or file name, a code or config file, or a code symbol
    that is in the task's diff (`diff` is read only then)."""
    for t in CodeNames.tokens(what):
        if t in files or t in names or CodeNames.is_code_file(t):
            return True
    syms = CodeNames.symbols(what)
    if not syms:
        return False
    text = diff()
    return any(x in text for x in syms)


def resolve_kind(old: str, said: str | None, source: str, does: Callable[[], bool], reaches: Callable[[], bool]) -> str:
    """The kind of an item: the verifier's (it read the code) when it is as strict as the writer's, else the writer's. An engine_step
    the engine will not do, an external_fact with no source, and a taste or external_fact that names a path, a code file or a symbol
    in the diff is checkable, whatever its label."""
    new = said if said in UNCHECKED_KINDS else old
    if KIND_RANK.get(new, 2) < KIND_RANK.get(old, 2):
        new = old
    if new == "engine_step" and not does():
        return "checkable"
    if new in ("external_fact", "taste") and (reaches() or (new == "external_fact" and not source)):
        return "checkable"
    return new
