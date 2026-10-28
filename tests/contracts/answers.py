"""The six worker answers as dataclasses (test fixtures: the real ones arrive with their slices). Their generated schemas must
equal the engine's SCHEMAS, which is the proof the schema generator can carry them."""
import sys
from dataclasses import field
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401
from taskloop.contracts.codec import record  # noqa: E402

Kind = Literal["engine_step", "checkable", "external_fact", "taste", "owner_decision", "requirement", "number", "deletion", "link",
               "case", "tooling", "other"]


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
class Stage:
    goal: str
    files: list[str]
    checks: list[list[str]]
    hard: bool


@record
class Risk:
    what: str
    check: list[str]


@record
class Unresolved:
    what: str
    kind: Literal["file", "platform", "object", "engine", "tool", "other"]
    path: str


@record
class Case:
    criterion: str
    check: list[str]
    class_: Literal["test", "look-objective", "taste"] = field(default="test", metadata={"name": "class"})
    proved_by: Literal["check", "stage", "leftover", "engine_step"] = "check"
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
    irreversible: Literal["", "push_shared", "delete_outside", "close_epic", "spend_money"] = ""
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
    check: list[str]
    why: str


@record
class BadCheck:
    cmd: str
    why: str


@record
class CheckRun:
    cmd: str
    exit: int


@record
class WriteAnswer:
    summary: str
    checks_run: list[CheckRun]
    question: str
    options: list[Option]
    decided: str
    bad_checks: list[BadCheck]
    new_cases: list[NewCase]
    unchecked: list[Unchecked]
    shots: list[Shot] = field(default_factory=list)
    flakes: list[Flake] = field(default_factory=list)


@record
class Finding:
    file: str
    line: int
    severity: Literal["high", "medium", "low"]
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
class WentBadly:
    what: str
    cause: Literal["engine", "prompt", "delegate", "repo_profile", "bead", "sandbox", "other"]
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
    verdict: Literal["settled", "wrong", "open"]
    evidence: str
    why: str
    kind: Kind
    source: str


@record
class VerifyAnswer:
    items: list[VerifyItem]


NODES = {"plan": PlanAnswer, "write": WriteAnswer, "review": ReviewAnswer, "reflect": ReflectAnswer, "look": LookAnswer,
         "verify": VerifyAnswer}
