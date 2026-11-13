"""Drain's closed vocabularies and validated database/output values."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from stream_proc import OwnedProcess


class Reason(StrEnum):
    DRAINING = "draining"
    DRAINED = "drained"


class State(StrEnum):
    OPEN = "open"
    DRAINING = "draining"
    COMPLETE = "complete"


class ActionKind(StrEnum):
    CLAIM = "claim"
    DISPATCH = "dispatch"
    LAND = "land"
    ROUND = "round"
    FINALIZE = "finalize"


class ActionState(StrEnum):
    PENDING = "pending"
    UNCERTAIN = "uncertain"
    DONE = "done"


class Role(StrEnum):
    ENTRY = "entry"
    AGENT = "agent"
    SETUP = "setup"
    CHECK = "check"
    CALLER = "caller"


class Seen(StrEnum):
    ALIVE = "alive"
    GONE = "gone"
    UNKNOWN = "unknown"


class Conclusion(StrEnum):
    WAITING = "waiting"
    COMPLETE = "complete"
    REFUSED = "refused"
    UNAVAILABLE = "unavailable"
    INTERRUPTED = "interrupted"


class Identity(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    pid: int = Field(gt=0)
    pgid: int = Field(gt=0)
    start: str = Field(min_length=1)
    boot: str = Field(min_length=1)

    def owned(self) -> OwnedProcess:
        return OwnedProcess(self.pid, self.pgid, self.start, self.boot)


class Owner(BaseModel):
    model_config = ConfigDict(frozen=True)
    subject: str
    role: Role
    identity: Identity


class Boundary(BaseModel):
    model_config = ConfigDict(frozen=True)
    generation: int = Field(ge=0)
    state: State


class Action(BaseModel):
    model_config = ConfigDict(frozen=True)
    action_id: str
    kind: ActionKind
    state: ActionState = ActionState.PENDING
    owner: Identity
    rev: int = 0
    checkout: str = ""
    subject: str = ""
    backlog: str = ""
    tracker_root: str = ""


class Result(BaseModel):
    model_config = ConfigDict(frozen=True)
    conclusion: Conclusion
    generation: int | None = None
    active: tuple[Owner, ...] = ()
    uncertain: tuple[Owner, ...] = ()
    actions: tuple[Action, ...] = ()
    detail: str = ""


BLOCKED = "New work is blocked by the factory's durable drain request."


def owners(rows: list[tuple[object, ...]], role: Role, *, group: bool) -> tuple[Owner, ...]:
    """Decode all recorded identities, including partial (invalid) identities; never silently drop one."""
    found: list[Owner] = []
    for row in rows:
        if all(value is None for value in row[1:]):
            continue
        pid, pgid, start, boot = row[1:] if group else (row[1], row[1], *row[2:])
        identity = Identity.model_validate({"pid": pid, "pgid": pgid, "start": start, "boot": boot})
        found.append(Owner(subject=str(row[0]), role=role, identity=identity))
    return tuple(found)
