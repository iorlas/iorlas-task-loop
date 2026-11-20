"""The sole owner of drain state and external-action ownership records."""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlite_store import begin_immediate

from taskloop.drain.models import Action, ActionKind, ActionState, Boundary, Identity, State
from taskloop.ids import Ids

type Connect = Callable[[], sqlite3.Connection | None]
type Begin = Callable[[sqlite3.Connection], AbstractContextManager[None]]


def boundary(con: sqlite3.Connection) -> Boundary:
    row = con.execute("SELECT generation,state FROM drain_state WHERE singleton=1").fetchone()
    return Boundary(generation=0, state=State.OPEN) if row is None else Boundary.model_validate({"generation": row[0], "state": row[1]})


def blocked(con: sqlite3.Connection) -> bool:
    """Called inside an admission's own committing transaction, never as a substitute for that transaction."""
    return boundary(con).state is not State.OPEN


class DrainStore:
    def __init__(self, connect: Connect, begin: Begin = begin_immediate, *, ids: Ids) -> None:
        self.ids = ids
        self.connect, self.begin = connect, begin

    def _con(self) -> sqlite3.Connection:
        con = self.connect()
        if con is None:
            raise sqlite3.DatabaseError("Factory database is unavailable")
        return con

    def boundary(self) -> Boundary:
        return boundary(self._con())

    def request(self) -> Boundary:
        con = self._con()
        with self.begin(con):
            before = boundary(con)
            if before.state is not State.OPEN:
                return before
            after = Boundary(generation=before.generation + 1, state=State.DRAINING)
            if before.generation == 0:
                con.execute("INSERT INTO drain_state(singleton,generation,state) VALUES(1,?,?)", (after.generation, after.state.value))
            else:
                con.execute("UPDATE drain_state SET generation=?,state=? WHERE singleton=1", (after.generation, after.state.value))
            return after

    def authorize(
        self,
        kind: ActionKind,
        owner: Identity,
        *,
        subject: str = "",
        backlog: str = "",
        tracker_root: str = "",
        checkout: str = "",
        generation: int | None = None,
    ) -> Action | None:
        con = self._con()
        with self.begin(con):
            current = boundary(con)
            if current.state is not State.OPEN or (generation is not None and generation != current.generation):
                return None
            action = Action(
                action_id=self.ids.hex(),
                kind=kind,
                owner=owner,
                subject=subject,
                backlog=backlog,
                tracker_root=tracker_root,
                checkout=checkout,
            )
            con.execute(
                "INSERT INTO drain_action(action_id,kind,state,pid,pgid,start,boot,subject,backlog,tracker_root,checkout) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    action.action_id,
                    kind.value,
                    ActionState.PENDING.value,
                    owner.pid,
                    owner.pgid,
                    owner.start,
                    owner.boot,
                    subject,
                    backlog,
                    tracker_root,
                    checkout,
                ),
            )
            return action

    def finish(self, action: Action) -> None:
        con = self._con()
        with self.begin(con):
            con.execute(
                "UPDATE drain_action SET state=? WHERE action_id=? AND rev=?", (ActionState.DONE.value, action.action_id, action.rev)
            )

    def uncertain(self, action: Action) -> None:
        con = self._con()
        with self.begin(con):
            con.execute(
                "UPDATE drain_action SET state=? WHERE action_id=? AND rev=?", (ActionState.UNCERTAIN.value, action.action_id, action.rev)
            )

    def adopt(self, action: Action, owner: Identity) -> Action | None:
        """One reconciler owns external IO before it asks the world; another drain caller observes that ownership."""
        con = self._con()
        with self.begin(con):
            changed = con.execute(
                "UPDATE drain_action SET pid=?,pgid=?,start=?,boot=?,state=?,rev=rev+1 WHERE action_id=? AND rev=? AND state=?",
                (
                    owner.pid,
                    owner.pgid,
                    owner.start,
                    owner.boot,
                    ActionState.PENDING.value,
                    action.action_id,
                    action.rev,
                    action.state.value,
                ),
            ).rowcount
            return action.model_copy(update={"owner": owner, "state": ActionState.PENDING, "rev": action.rev + 1}) if changed else None

    def owns_active(self, owner: Identity) -> bool:
        return any(action.owner == owner and action.state is ActionState.PENDING for action in self.pending())

    def pending(self) -> tuple[Action, ...]:
        return pending(con=self._con())

    def complete(self, generation: int) -> bool:
        con = self._con()
        with self.begin(con):
            current = boundary(con)
            if current.generation != generation or current.state is State.OPEN or self.pending():
                return False
            con.execute("UPDATE drain_state SET state=? WHERE singleton=1", (State.COMPLETE.value,))
            return True

    def reopen(self, expected: Boundary) -> Boundary | None:
        """Only explicit rounds startup calls this, after a fresh successful idle observation."""
        con = self._con()
        with self.begin(con):
            current = boundary(con)
            if current != expected or current.state is not State.COMPLETE or self.pending():
                return None
            con.execute("UPDATE drain_state SET state=?,generation=generation+1 WHERE singleton=1", (State.OPEN.value,))
            return Boundary(state=State.OPEN, generation=current.generation + 1)


def pending(con: sqlite3.Connection) -> tuple[Action, ...]:
    """The owning read shared by drain and registration fences; it never authorizes an action."""
    rows = con.execute(
        "SELECT action_id,kind,pid,pgid,start,boot,subject,backlog,tracker_root,state,checkout,rev FROM drain_action "
        "WHERE state<>? ORDER BY action_id", (ActionState.DONE.value,),
    ).fetchall()
    return tuple(
        Action.model_validate({
            "action_id": row[0], "kind": row[1],
            "owner": {"pid": row[2], "pgid": row[3], "start": row[4], "boot": row[5]},
            "subject": row[6], "backlog": row[7], "tracker_root": row[8], "state": row[9], "checkout": row[10], "rev": row[11],
        })
        for row in rows
    )
