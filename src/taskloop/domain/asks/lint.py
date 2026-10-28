"""Ask lint: whether a record is an ask an owner can answer. Pure; `lint(ask)` returns the broken rules, empty when the ask may be raised.

An ask has a class, a decision (one sentence of 120 characters or less that ends in '?'), what was tried (3 bullets at most) and
2 to 5 options, each with its consequence, the recommended one first. The engine's own trouble (a lane that failed, a bad request,
a denied command, a stale base, a missing tool) is a class lint refuses: it never reaches the owner as a question."""
from typing import Final

from taskloop.contracts.ask import Ask
from taskloop.contracts.enums import AskClass, AskKind

INFRA: Final = frozenset({AskClass.LANE_FAILURE, AskClass.BAD_REQUEST, AskClass.SANDBOX_DENIAL, AskClass.STALE_BASE, AskClass.MISSING_TOOL})
KIND_OF: Final = {
    AskClass.OPEN_QUESTION: AskKind.DECISION, AskClass.EXTERNAL_FACT: AskKind.DECISION,
    AskClass.UNPROVEN: AskKind.STUCK, AskClass.NO_PROGRESS: AskKind.STUCK, AskClass.CAP_REACHED: AskKind.STUCK,
    AskClass.OVER_BUDGET: AskKind.BUDGET,
    AskClass.MISSING_CRITERIA: AskKind.TICKET, AskClass.TOO_BIG: AskKind.TICKET,
}
DECISION_MAX: Final = 120
TRIED_MAX: Final = 3
LABEL_MAX: Final = 40
OPTIONS: Final = (2, 5)
SENTENCE_ENDS: Final = (". ", "? ", "! ")
PAYLOAD: Final = ("{", "}", "\\n", "/bin/")


def one_sentence(text: str) -> bool:
    return "\n" not in text and not any(e in text for e in SENTENCE_ENDS)


def payload_free(text: str) -> bool:
    """No JSON, escaped newline or shell path: a dump of the engine's state is not something to read."""
    return not any(p in text for p in PAYLOAD)


def decision_problems(text: str) -> list[str]:
    out = []
    if not text.strip():
        out.append("decision: empty")
    if len(text) > DECISION_MAX:
        out.append(f"decision: {len(text)} characters, at most {DECISION_MAX}")
    if not text.endswith("?"):
        out.append("decision: does not end in '?'")
    if not one_sentence(text):
        out.append("decision: more than one sentence")
    if not payload_free(text):
        out.append("decision: carries a payload")
    return out


def option_problems(ask: Ask) -> list[str]:
    out = []
    low, high = OPTIONS
    if not low <= len(ask.options) <= high:
        out.append(f"options: {len(ask.options)}, need {low} to {high}")
    if ask.options and not ask.options[0].recommended:
        out.append("options: the recommended one is not first")
    if sum(o.recommended for o in ask.options) > 1:
        out.append("options: more than one recommended")
    labels = [o.label for o in ask.options]
    if len(set(labels)) != len(labels):
        out.append("options: two share a label")
    for k, o in enumerate(ask.options):
        if not o.label.strip() or len(o.label) > LABEL_MAX or not payload_free(o.label):
            out.append(f"option {k + 1}: label is empty, over {LABEL_MAX} characters or carries a payload")
        if not o.consequence.strip():
            out.append(f"option {k + 1}: no consequence")
    return out


def lint(ask: Ask) -> list[str]:
    out: list[str] = []
    if ask.ask_class in INFRA:
        out.append(f"class: {ask.ask_class.value} is the engine's own trouble, never an ask")
    elif KIND_OF[ask.ask_class] != ask.kind:
        out.append(f"class: {ask.ask_class.value} is not a {ask.kind.value} ask")
    out += decision_problems(ask.decision)
    if len(ask.tried) > TRIED_MAX:
        out.append(f"tried: {len(ask.tried)} bullets, at most {TRIED_MAX}")
    if any(not t.strip() or "\n" in t for t in ask.tried):
        out.append("tried: a bullet is empty or spans lines")
    return out + option_problems(ask)
