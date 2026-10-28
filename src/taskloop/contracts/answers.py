"""The six worker answers (plan, write, review, reflect, look, verify) as records. The JSON Schema a node sends is generated from
its record (`schema.of`), the strict form from that (`schema.strict`), and an answer is validated by decoding it into the record
(`check`): one definition, no hand-written schema. A visual stage's write and review also require their look field."""
from dataclasses import field
from typing import Any, Literal, get_args

from taskloop.contracts import schema
from taskloop.contracts.argv import FORM
from taskloop.contracts.codec import CodecError, from_json, record

Kind = Literal["engine_step", "checkable", "external_fact", "taste", "owner_decision", "requirement", "number", "deletion", "link",
               "case", "tooling", "other"]
InputKind = Literal["file", "platform", "object", "engine", "tool", "other"]
CaseClass = Literal["test", "look-objective", "taste"]
ProvedBy = Literal["check", "stage", "leftover", "engine_step"]
Irreversible = Literal["", "push_shared", "delete_outside", "close_epic", "spend_money"]
Cause = Literal["engine", "prompt", "delegate", "repo_profile", "bead", "sandbox", "other"]
Severity = Literal["high", "medium", "low"]
Verdict = Literal["settled", "wrong", "open"]

ARGV_DOC = "argv: " + FORM  # a check: the program and its arguments, never a shell string
NOT_AN_ARRAY = "expected an array"
KINDS = get_args(Kind)
ROUTED_KINDS = ("engine_step", "checkable", "external_fact", "taste", "owner_decision")
LEGACY_KINDS = ("requirement", "number", "deletion", "link", "case", "tooling")
INPUT_KINDS = get_args(InputKind)
PROVED_BY = get_args(ProvedBy)
CAUSE_CLASSES = get_args(Cause)
VERDICTS = get_args(Verdict)

# tl-ntp (owner ruling 82 item 1): agents assume and record an Assumption; only a step that cannot be undone may ask the owner.
IRREVERSIBLE = {"push_shared": "a push to a shared branch", "delete_outside": "a deletion outside the worktree",
                "close_epic": "closing an epic", "spend_money": "spending money"}
ASSUMPTION = "Assumption: "  # the stable prefix of an assumption line (plan comment, plan summary)


@record
class Option:
    label: str
    cost: str
    answer: str
    recommended: bool


@record
class Leftover:
    title: str
    why: str


@record
class Unchecked:
    what: str
    kind: Kind
    source: str = ""


@record
class Anchor:
    path: str
    lines: str
    symbol: str
    why: str


@record
class Stage:
    goal: str
    files: list[str]
    checks: list[list[str]] = field(metadata={"doc": ARGV_DOC})
    hard: bool
    anchors: list[Anchor] = field(default_factory=list, metadata={"doc": "at most 8: where in the code the stage's work starts"})
    read_first: list[str] = field(default_factory=list, metadata={"doc": "files to read before touching anything"})
    patterns: list[str] = field(default_factory=list, metadata={"doc": "existing code to follow, one line each"})
    constraints: str | None = field(default=None, metadata={"doc": "what the stage must not break or touch"})


@record
class Risk:
    what: str
    check: list[str] = field(metadata={"doc": ARGV_DOC})


@record
class Unresolved:
    what: str
    kind: InputKind
    path: str


@record
class Case:
    criterion: str
    check: list[str] = field(metadata={"doc": ARGV_DOC})
    class_: CaseClass = field(default="test", metadata={"name": "class"})
    proved_by: ProvedBy = "check"
    via: str = ""


@record
class PlanAnswer:
    summary: str
    stages: list[Stage]
    risks: list[Risk]
    question: str
    options: list[Option]
    decided: str
    cases: list[Case]
    leftovers: list[Leftover]
    irreversible: Irreversible = ""
    unresolved: list[Unresolved] = field(default_factory=list)


@record
class ShotArg:
    name: str
    value: str


@record
class Shot:
    method: str
    args: list[ShotArg]
    names: list[str]


@record
class Flake:
    test: str
    note: str


@record
class NewCase:
    criterion: str
    check: list[str] = field(metadata={"doc": ARGV_DOC})
    why: str


@record
class BadCheck:
    cmd: str
    why: str


@record
class CheckRan:
    cmd: str
    exit: int


@record
class WriteAnswer:
    summary: str
    checks_run: list[CheckRan]
    question: str
    options: list[Option]
    decided: str
    bad_checks: list[BadCheck]
    new_cases: list[NewCase]
    unchecked: list[Unchecked]
    shots: list[Shot] = field(default_factory=list)
    flakes: list[Flake] = field(default_factory=list)
    handoff: str = field(default="", metadata={"doc": "at most 1 KB: what a fresh writer taking over needs that the diff does not show"})


@record
class WriteAnswerLook(WriteAnswer):
    logic_only: str = field(kw_only=True)


@record
class Finding:
    file: str
    line: int
    severity: Severity
    fix: str


@record
class ReviewAnswer:
    findings: list[Finding]
    unmet: list[str]
    question: str
    options: list[Option]
    decided: str
    leftovers: list[Leftover]
    unchecked: list[Unchecked]
    accept_files: list[str] = field(default_factory=list)
    reject_files: list[str] = field(default_factory=list)


@record
class ReviewAnswerLook(ReviewAnswer):
    look: str = field(kw_only=True)


@record
class WentBadly:
    what: str
    cause: Cause
    session: str
    evidence: str


@record
class ReflectAnswer:
    went_well: list[str]
    went_badly: list[WentBadly]
    wasted: list[str]
    change: list[str]


@record
class LookFinding:
    item: str
    verdict: Literal["pass", "defect"]
    where: str
    why: str


@record
class LookAnswer:
    findings: list[LookFinding]
    summary: str


@record
class VerifyItem:
    n: int
    verdict: Verdict
    evidence: str
    why: str
    kind: Kind
    source: str


@record
class VerifyAnswer:
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


HANDOFF_MAX = 1024


def check(node: str, visual: bool, data: Any) -> list[str]:
    """The reasons `data` is not this node's answer ([] when it is). `data` is a strict answer already mapped back
    (`schema.unstrict`); a key the contract does not name is ignored."""
    if node == "write" and len(str((data or {}).get("handoff") or "").encode()) > HANDOFF_MAX:
        return [f"WriteAnswer.handoff: over {HANDOFF_MAX} bytes; keep what a fresh writer needs and nothing else"]
    try:
        from_json(record_for(node, visual), schema.prune(data, schema_for(node, visual)))
    except CodecError as e:
        return [f"{e} ({ARGV_DOC})" if str(e).endswith(NOT_AN_ARRAY) and ".check" in str(e) else str(e)]
    return []
