"""Request one durable drain and observe its executions; never schedule, signal or release work."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from taskloop.attempt_reads import StoreUnavailable
from taskloop.drain.models import BLOCKED, Action, ActionState, Conclusion, Identity, Owner, Result, Role, Seen
from taskloop.drain.observe import identity
from taskloop.drain.store import DrainStore


@dataclass(frozen=True)
class Ports:
    store: DrainStore
    owners: Callable[[], tuple[Owner, ...]]
    observe: Callable[[Owner], Seen]
    reconcile: Callable[[Action], bool]
    wait: Callable[[float], None]
    report: Callable[[Result], None] = lambda _result: None
    me: Callable[[], Identity | None] = identity


def inspect(ports: Ports, generation: int) -> Result:
    """All historical owners, and pending intents, not task status or only the latest attempts."""
    active: list[Owner] = []
    uncertain: list[Owner] = []
    unresolved: list[Action] = []
    for recorded in ports.store.pending():
        action = recorded
        caller = Owner(subject=action.action_id, role=Role.CALLER, identity=action.owner)
        seen = ports.observe(caller)
        if seen is Seen.GONE or action.state is ActionState.UNCERTAIN:
            me = ports.me()
            adopted = None if me is None else ports.store.adopt(action, me)
            if adopted is not None:
                if ports.reconcile(adopted):
                    ports.store.finish(adopted)
                    continue
                ports.store.uncertain(adopted)
            # A competing reconciler is still an unresolved action, even if absent from this snapshot.
            action = action if adopted is None else adopted
            seen = Seen.UNKNOWN
        unresolved.append(action)
        (uncertain if seen in {Seen.UNKNOWN, Seen.GONE} or action.state is ActionState.UNCERTAIN else active).append(caller)
    for owner in ports.owners():
        seen = ports.observe(owner)
        if seen is Seen.ALIVE:
            active.append(owner)
        elif seen is Seen.UNKNOWN:
            uncertain.append(owner)
    conclusion = Conclusion.UNAVAILABLE if uncertain else Conclusion.WAITING if active or unresolved else Conclusion.COMPLETE
    return Result(
        conclusion=conclusion,
        generation=generation,
        active=tuple(active),
        uncertain=tuple(uncertain),
        actions=tuple(unresolved),
        detail=(BLOCKED + " An execution identity or external-action outcome is uncertain." if uncertain else BLOCKED),
    )


def drain(ports: Ports) -> Result:
    generation: int | None = None
    previous: Result | None = None
    try:
        generation = ports.store.request().generation
        ports.report(Result(conclusion=Conclusion.WAITING, generation=generation, detail=BLOCKED))
        while True:
            found = inspect(ports, generation)
            if found.conclusion is Conclusion.UNAVAILABLE:
                return found
            if found.conclusion is Conclusion.COMPLETE:
                if ports.store.complete(generation):
                    return found
                if ports.store.boundary().generation != generation:
                    return Result(
                        conclusion=Conclusion.REFUSED,
                        generation=generation,
                        detail="This drain boundary changed during explicit factory restart. Idle is not verified for the new boundary.",
                    )
            if found != previous:
                ports.report(found)
                previous = found
            ports.wait(0.2)
    except KeyboardInterrupt:
        return Result(
            conclusion=Conclusion.INTERRUPTED,
            generation=generation,
            detail="Waiting was interrupted. Existing executions remain intact; any committed drain request remains fenced.",
        )
    except (sqlite3.Error, ValidationError, OSError, StoreUnavailable) as error:
        return Result(
            conclusion=Conclusion.UNAVAILABLE,
            generation=generation,
            detail=f"Idle could not be verified ({type(error).__name__}). Any committed drain request remains fenced.",
        )
