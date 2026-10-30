"""The six worker answers (plan, write, review, reflect, look, verify) as records. The JSON Schema a node sends is generated from
its record (`schema.of`), the strict form from that (`schema.strict`), and an answer is validated by decoding it into the record
(`check`): one definition, no hand-written schema. A visual stage's write and review also require their look field."""
from typing import Annotated, Any, Final, Literal, final, get_args

import msgspec

from taskloop.contracts import schema
from taskloop.contracts.argv import FORM
from taskloop.contracts.wire import Rec, load

Kind = Literal["engine_step", "checkable", "external_fact", "taste", "owner_decision", "requirement", "number", "deletion", "link",
               "case", "tooling", "other"]
InputKind = Literal["file", "platform", "object", "engine", "tool", "other"]
CaseClass = Literal["test", "look-objective", "taste"]
ProvedBy = Literal["check", "stage", "leftover", "engine_step"]
Irreversible = Literal["", "push_shared", "delete_outside", "close_epic", "spend_money"]
AskCause = Literal["requirement", "decision", "environment", "process", "unknown"]
Cause = Literal["engine", "prompt", "delegate", "repo_profile", "bead", "sandbox", "other"]
Severity = Literal["high", "medium", "low"]
Verdict = Literal["settled", "wrong", "open"]
Axis = Literal["spec", "standards"]
Status = Literal["met", "unmet", "engine"]

ARGV_DOC: Final = "argv: " + FORM  # a check: the program and its arguments, never a shell string
KINDS: Final = get_args(Kind)
ROUTED_KINDS: Final = ("engine_step", "checkable", "external_fact", "taste", "owner_decision")
LEGACY_KINDS: Final = ("requirement", "number", "deletion", "link", "case", "tooling")
INPUT_KINDS: Final = get_args(InputKind)
PROVED_BY: Final = get_args(ProvedBy)
CAUSE_CLASSES: Final = get_args(Cause)
VERDICTS: Final = get_args(Verdict)

# tl-ntp (owner ruling 82 item 1): agents assume and record an Assumption; only a step that cannot be undone may ask the owner.
IRREVERSIBLE: Final = {"push_shared": "a push to a shared branch", "delete_outside": "a deletion outside the worktree",
                "close_epic": "closing an epic", "spend_money": "spending money"}
CAUSE_DOC = ("why you ask, if you ask: requirement (the bead leaves out something it needs), decision (a choice only the owner makes), "
             "environment (a tool, access or machine you lack), process (how the factory works), unknown")
CITED_DOC: Final = "the id (ADR-n) of each decision in force that this plan relied on, as listed in the prompt; [] when it relied on none"
ASSUMPTION: Final = "Assumption: "  # the stable prefix of an assumption line (plan comment, plan summary)


@final
class Option(Rec):
    label: str
    cost: str
    answer: str
    recommended: bool


@final
class Leftover(Rec):
    title: str
    why: str


@final
class Unchecked(Rec):
    what: str
    kind: Kind
    source: str = ""


@final
class Anchor(Rec):
    path: str
    lines: str
    symbol: str
    why: str


@final
class Stage(Rec):
    goal: str
    files: list[str]
    checks: Annotated[list[list[str]], msgspec.Meta(description=ARGV_DOC)]
    hard: bool
    anchors: Annotated[
        list[Anchor], msgspec.Meta(description="at most 8: where in the code the stage's work starts")
    ] = msgspec.field(default_factory=list)
    read_first: Annotated[
        list[str], msgspec.Meta(description="files to read before touching anything")
    ] = msgspec.field(default_factory=list)
    patterns: Annotated[list[str], msgspec.Meta(description="existing code to follow, one line each")] = msgspec.field(default_factory=list)
    constraints: Annotated[str | None, msgspec.Meta(description="what the stage must not break or touch")] = None


@final
class Risk(Rec):
    what: str
    check: Annotated[list[str], msgspec.Meta(description=ARGV_DOC)]


@final
class Unresolved(Rec):
    what: str
    kind: InputKind
    path: str


class Case(Rec):
    criterion: str
    check: Annotated[list[str], msgspec.Meta(description=ARGV_DOC)]
    class_: CaseClass = msgspec.field(default="test", name="class")
    proved_by: ProvedBy = "check"
    via: str = ""


@final
class PlanAnswer(Rec):
    summary: str
    stages: list[Stage]
    risks: list[Risk]
    question: str
    options: list[Option]
    decided: str
    cases: list[Case]
    leftovers: list[Leftover]
    irreversible: Irreversible = ""
    unresolved: list[Unresolved] = msgspec.field(default_factory=list)
    owner_cause: Annotated[AskCause, msgspec.Meta(description=CAUSE_DOC)] = "unknown"
    cited: Annotated[list[str], msgspec.Meta(description=CITED_DOC)] = msgspec.field(default_factory=list)


@final
class ShotArg(Rec):
    name: str
    value: str


@final
class Shot(Rec):
    method: str
    args: list[ShotArg]
    names: list[str]


@final
class Flake(Rec):
    test: str
    note: str


@final
class NewCase(Rec):
    criterion: str
    check: Annotated[list[str], msgspec.Meta(description=ARGV_DOC)]
    why: str


@final
class BadCheck(Rec):
    cmd: str
    why: str


@final
class CheckRan(Rec):
    cmd: str
    exit: int


class WriteAnswer(Rec):
    summary: str
    checks_run: list[CheckRan]
    question: str
    options: list[Option]
    decided: str
    bad_checks: list[BadCheck]
    new_cases: list[NewCase]
    unchecked: list[Unchecked]
    shots: list[Shot] = msgspec.field(default_factory=list)
    flakes: list[Flake] = msgspec.field(default_factory=list)
    handoff: Annotated[
        str, msgspec.Meta(description="at most 1 KB: what a fresh writer taking over needs that the diff does not show")
    ] = ""
    owner_cause: Annotated[AskCause, msgspec.Meta(description=CAUSE_DOC)] = "unknown"


@final
class WriteAnswerLook(WriteAnswer, kw_only=True):
    logic_only: str


@final
class Finding(Rec):
    file: str
    line: int
    severity: Severity
    fix: str
    axis: Annotated[
        Axis, msgspec.Meta(description="spec: a requirement is unmet or unasked behaviour; standards: a break of the repo's rules")
    ]
    category: Annotated[str, msgspec.Meta(description="one word: logic, contract, test, docs, security, convention")]
    scenario: Annotated[
        str, msgspec.Meta(description="the inputs and the wrong output; empty when you cannot state one (then it is only a note)")
    ]


@final
class Criterion(Rec):
    item: Annotated[str, msgspec.Meta(description="the id of an acceptance item as listed in the prompt (A1, A2, ...)")]
    status: Status
    evidence: Annotated[
        str, msgspec.Meta(description="what shows it: a check, a file and line, the evidence folder; empty only for engine")
    ]


class ReviewAnswer(Rec):
    findings: list[Finding]
    unmet: list[str]
    criteria: Annotated[list[Criterion], msgspec.Meta(description="one entry per acceptance item the prompt lists; [] when it lists none")]
    question: str
    options: list[Option]
    decided: str
    leftovers: list[Leftover]
    unchecked: list[Unchecked]
    accept_files: list[str] = msgspec.field(default_factory=list)
    reject_files: list[str] = msgspec.field(default_factory=list)
    owner_cause: Annotated[AskCause, msgspec.Meta(description=CAUSE_DOC)] = "unknown"


@final
class ReviewAnswerLook(ReviewAnswer, kw_only=True):
    look: str


@final
class WentBadly(Rec):
    what: str
    cause: Cause
    session: str
    evidence: str


@final
class ReflectAnswer(Rec):
    went_well: list[str]
    went_badly: list[WentBadly]
    wasted: list[str]
    change: list[str]


@final
class LookFinding(Rec):
    item: str
    verdict: Literal["pass", "defect"]
    where: str
    why: str


@final
class LookAnswer(Rec):
    findings: list[LookFinding]
    summary: str


@final
class VerifyItem(Rec):
    n: int
    verdict: Verdict
    evidence: str
    why: str
    kind: Kind
    source: str


@final
class VerifyAnswer(Rec):
    items: list[VerifyItem]


NODES: dict[str, type] = {"plan": PlanAnswer, "write": WriteAnswer, "review": ReviewAnswer, "reflect": ReflectAnswer,
                          "look": LookAnswer, "verify": VerifyAnswer}
VISUAL: dict[str, type] = {"write": WriteAnswerLook, "review": ReviewAnswerLook}  # asked only on a visual stage


def record_for(node: str, visual: bool = False) -> type:
    """The record of a node's answer; on a visual stage the write and review records that also require the look field."""
    return VISUAL[node] if visual and node in VISUAL else NODES[node]


def schema_for(node: str, visual: bool = False) -> dict[str, Any]:
    """The node's contract schema (a fresh copy)."""
    return schema.of(record_for(node, visual))


def sent_schema(node: str, visual: bool = False) -> dict[str, Any]:
    """The node's schema as the worker's strict structured output takes it."""
    return schema.strict(schema_for(node, visual))


HANDOFF_MAX: Final = 1024


def check(node: str, visual: bool, data: Any) -> list[str]:
    """The reasons `data` is not this node's answer ([] when it is). `data` is a strict answer already mapped back
    (`schema.unstrict`); a key the contract does not name is ignored."""
    if node == "write" and len(str((data or {}).get("handoff") or "").encode()) > HANDOFF_MAX:
        return [f"WriteAnswer.handoff: over {HANDOFF_MAX} bytes; keep what a fresh writer needs and nothing else"]
    rec = record_for(node, visual)
    try:
        load(rec, schema.prune(data, schema_for(node, visual)))
    except msgspec.ValidationError as e:
        return [_reason(rec, str(e))]
    return []


def _reason(rec: type[Rec], error: str) -> str:
    """One validation error as `Record.path: what is wrong`; a command that is not an argv array also gets the form."""
    what, _, where = error.partition(" - at `$")
    where = where.rstrip("`")
    if what.startswith("Object missing required field `"):
        where, what = f"{where}.{what.split('`')[1]}", "missing"
    form = f" ({ARGV_DOC})" if what.startswith("Expected `array`") and ".check" in where else ""
    return f"{rec.__name__}{where}: {what}{form}"
