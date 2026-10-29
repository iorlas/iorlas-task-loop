"""The run state and its one writer.

`carries_state` gives the engine every `RunState` field as an attribute that reads and writes `engine.state` (adding a field
is one edit, in contracts/checkpoint.py). `Checkpoints` is the only code that writes checkpoints/<bead>.json: save at a
node, close at the end, keep the follow-ups, follow a rebase, drop.
"""

import copy
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from taskloop.app.run.review_glue import review_of
from taskloop.contracts.checkpoint import Checkpoint, RunState
from taskloop.contracts.review import Unfiled
from taskloop.domain.checks import trim

NOT_ATTRS = ("review",)  # the one field of another lane's type: reached as `engine.state.review` only


class StateField:
    """An engine attribute that lives in `engine.state`."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, owner: Any = None) -> Any:
        return self if obj is None else getattr(obj.state, self.name)

    def __set__(self, obj: Any, value: Any) -> None:
        setattr(obj.state, self.name, value)


class StateAttrs:
    """Base of a class decorated with `carries_state`: tells the type checker the RunState fields are attributes."""

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...


def state_names() -> tuple[str, ...]:
    return tuple(name for name in RunState.model_fields if name not in NOT_ATTRS)


def carries_state[T](cls: type[T]) -> type[T]:
    for name in state_names():
        setattr(cls, name, StateField(name))
    return cls


class Checkpoints:
    """checkpoints/<bead>.json: the one writer. Every method is one read-modify-write of a whole record. `host` is the engine:
    its state, its bead, its run, its git."""

    def __init__(self, host: Any) -> None:
        self.e = host

    @property
    def doc(self) -> Any:
        return self.e.stores.checkpoints.of(self.e.bead)

    def read(self) -> Checkpoint | None:
        return self.doc.read()

    def save(self, *, step: str = "", stage: int = 0, rounds: int = 0, n: int = 0, feedback: str = "") -> None:
        """Where the run stands. Mid-rebase (a conflict fix) HEAD is detached: the record names the task branch the close goes
        back to. A pending land validation always parks at land-verify-red: a fix, a re-plan or an interrupted recovery must never
        turn it into a direct-to-land checkpoint."""
        e = self.e
        if e.pending_land_validation:
            step, feedback = "land-verify-red", e.pending_land_validation
        state = copy.deepcopy(e.state)
        state.review = review_of(e)
        self.doc.write(
            Checkpoint(
                bead=e.bead,
                run=e.log_path.stem,
                t=time.time(),
                branch=e.checkout.branch_now() or e.task_branch,
                head=e.git("rev-parse", "HEAD"),
                step=step,
                stage=stage,
                rounds=rounds,
                n=n,
                feedback=feedback,
                state=state,
            )
        )

    def close(self, why: str = "") -> None:
        """The close step committed everything: the record's head is now what the next run should find. A red gate at land is no
        stop: the next run re-plans with the gate's output, or it would rerun the same red gate."""
        ck = self.read()
        if ck is None:
            return
        red = why.startswith("gate red") and not ck.state.pending_land_validation
        review = ck.state.review.model_copy(update={"filed": list(self.e.filed)})
        state = ck.state.model_copy(update={"review": review})
        done = ck.model_copy(update={"head": self.e.git("rev-parse", "HEAD"), "closed": True, "state": state})
        if red:
            done = done.model_copy(update={"step": "gate-red", "gate_tail": trim.trim_log(why, log=str(self.e.gate_log or ""))})
        self.doc.write(done)

    def keep_filed(self, lost: list[dict[str, str]] | None = None) -> None:
        """The follow-ups filed so far and the ones bd refused (`lost`: kept, none lost): written at once, a kill loses no title."""
        self.e.unfiled += [Unfiled(title=lo["title"], why=lo["why"]) for lo in lost or []]
        ck = self.read()
        if ck is not None:
            kept = ck.state.model_copy(update={"review": review_of(self.e)})
            self.doc.write(ck.model_copy(update={"state": kept}))

    def keep_look(self) -> None:
        """What the owner-look bead needs goes into the record, so a crash after the land still files it."""
        ck, e = self.read(), self.e
        if ck is not None:
            kept = ck.state.model_copy(update={"look_paths": list(e.look_paths),
                "look_notes": list(e.look_notes),
                "look_unjudged": dict(e.look_unjudged),
                "review": review_of(e)})
            self.doc.write(ck.model_copy(update={"state": kept}))

    def amend(self, fn: Callable[[Checkpoint], Checkpoint]) -> bool:
        """Rewrite the stored record with `fn` (a rebase moves its head, a cap grant adds an amend). False when there is none."""
        ck = self.read()
        if ck is None:
            return False
        self.doc.write(fn(ck))
        return True

    def drop(self) -> None:
        self.doc.delete()
