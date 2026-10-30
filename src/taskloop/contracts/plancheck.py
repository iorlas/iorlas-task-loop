"""A check of the plan is one of two things, parsed once from the planner's answer: `Ref`, a registered repo check (engine.checks) named by
its id, or `Adhoc`, an argv of the plan's own with the registered checks it reads declared in `reads` (the engine runs it after them and
exports their logs). A check has no other identity: a wrapper of a registered check is unwritable (domain/checks/planref.py refuses it)."""
import copy
import shlex
from typing import Any, NotRequired, TypedDict, assert_never, final

from taskloop.contracts.argv import FORM
from taskloop.contracts.ids import CheckId
from taskloop.contracts.wire import Tagged, load


@final
class Ref(Tagged, tag="ref"):
    """The registered check `check`: the round runs it anyway; naming it makes the plan depend on it."""

    check: CheckId

    @property
    def text(self) -> str:
        return str(self.check)


@final
class Adhoc(Tagged, tag="adhoc"):
    """A command of the plan's own. `reads` are the registered checks whose saved log ($TL_CHECK_LOG_<ID>) and exit code it reads."""

    argv: tuple[str, ...]
    reads: tuple[CheckId, ...]

    @property
    def text(self) -> str:
        return shlex.join(self.argv)


PlanCheck = Ref | Adhoc


class StageData(TypedDict):
    """One stage of a parsed plan (answers.Stage in its working form: every check a PlanCheck). A fix round and the land's retry checks
    build one with just the checks and the files."""

    files: list[str]
    checks: list[PlanCheck]
    goal: NotRequired[str]
    hard: NotRequired[bool]


class PlanData(TypedDict, total=False):
    """The plan as the land reads it: its summary and its stages. (The rest of the planner's answer rides in the same dict.)"""

    summary: str
    stages: list[StageData]


def stages_of(plan: PlanData | None) -> list[StageData]:
    """The plan's stages (none before the first plan is accepted)."""
    return (plan or {}).get("stages") or []


class RoundState(TypedDict, total=False):
    """A stage loop's starting counters: a resumed stage's, or a fix round's."""

    fix: bool
    conflict_fix: list[str] | None
    name: str
    fix_n: int
    fix_of: int
    failed: list[str] | None
    feedback: str
    scope: str
    rounds: int
    n: int
CHECK_DOC = ("a check is {kind: ref, check: <id of a repo check>} (the repo's own check, named) or {kind: adhoc, argv, reads} (your own "
             "command; reads lists the ids of the repo checks whose saved log it reads). " + FORM)


def text_of(check: PlanCheck) -> str:
    """The check as one line: a ref's id, an adhoc's argv joined."""
    match check:
        case Ref() | Adhoc():
            return check.text
        case _:
            assert_never(check)


def shown(check: PlanCheck | None) -> str:
    """The check as one line for a comment, a log row or a prompt ('' for none)."""
    return text_of(check) if check else ""


def adhoc(text: str, reads: tuple[CheckId, ...] = ()) -> Adhoc:
    """An adhoc check from its one-line text (the round trip of shlex.join)."""
    return Adhoc(argv=tuple(shlex.split(text)), reads=reads)


def of(raw: object) -> PlanCheck:
    """The check a planner or writer wrote (a dict of the wire form), or one already parsed; ValidationError when it is neither."""
    return raw if isinstance(raw, (Ref, Adhoc)) else load(PlanCheck, raw)


def parse(plan: dict[str, Any]) -> None:
    """A planner's or writer's answer, or a stored plan, with every check a PlanCheck: a stage's checks, a risk's, a case's and a new
    case's. A missing check is None. In place; a PlanCheck stays as it is."""
    for st in plan.get("stages") or []:
        st["checks"] = [of(c) for c in st["checks"]]
    for k in ("risks", "cases", "new_cases"):
        for x in plan.get(k) or []:
            x["check"] = of(x["check"]) if x.get("check") else None


def to_wire(plan: dict[str, Any]) -> dict[str, Any]:
    """A copy of the plan with every check in its wire form (a dict), as the planner is shown it and writes it."""
    out = copy.deepcopy(plan)
    for st in out.get("stages") or []:
        st["checks"] = [c.to_dict() if isinstance(c, (Ref, Adhoc)) else c for c in st.get("checks") or []]
    for k in ("risks", "cases"):
        for x in out.get(k) or []:
            if isinstance(x.get("check"), (Ref, Adhoc)):
                x["check"] = x["check"].to_dict()
    return out
