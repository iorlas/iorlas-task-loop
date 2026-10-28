"""The slot line: waiters get free slots by bead priority (P0 first), then arrival order (tl-bxk.11.5, tl-43k).

A waiter (a loop, run-task --slot any) takes a Ticket; only the first live ticket may take a slot. A ticket whose process is
gone is dropped by whoever reads the line (the store does it)."""
from collections.abc import Callable

from taskloop.app.slots.env import DEFAULT_PRIO, TICKET_POLL, SlotEnv
from taskloop.app.slots.pool import SlotPool
from taskloop.contracts.locks import Ticket
from taskloop.contracts.loop import QueueRow


def order(t: Ticket) -> tuple[int, int]:
    """(priority, arrival) of a ticket: P0 before P2, and among equals the one that joined first."""
    return t.prio, t.seq


def waiting_line(env: SlotEnv) -> list[Ticket]:
    """The live tickets, first in line first."""
    return env.tickets.line(env.repo_key)


def queue_rows(env: SlotEnv) -> list[QueueRow]:
    """The line as the loop's state file carries it (LoopState.queue): first in line first, `ahead` the places before it."""
    return [QueueRow(bead=t.bead, prio=t.prio, since=t.since, ahead=n) for n, t in enumerate(waiting_line(env))]  # pyrefly: ignore[unexpected-keyword]


def wait_slot(env: SlotEnv, why: str, bead: str = "", stop: Callable[[], bool] | None = None,
              sleep: Callable[[float], object] | None = None, poll: tuple[float, float] | None = None,
              on_wait: Callable[[int], None] | None = None, prio: int = DEFAULT_PRIO) -> tuple[str, str, str] | None:
    """(name, dir, slot bead) once this waiter is first in line and a slot is free; None when stop() says so after a look
    (stop=lambda: True: one look, no wait). on_wait(ahead) is called before each sleep. Never takes a slot while a live
    ticket is ahead of it: a lower `prio` number (read when the waiter joins), or the same and earlier."""
    first, most = poll or TICKET_POLL
    nap = sleep or env.sleep
    pool = SlotPool(env)
    ticket = env.tickets.take(env.repo_key, why, prio, pid=env.pid, now=env.now(), bead=bead)
    delay = first
    try:
        while True:
            ahead = [x for x in waiting_line(env) if order(x) < order(ticket)]
            if not ahead:
                got = pool.take_any(why, bead, ticket.seq)
                if got:
                    return got
            if stop and stop():
                return None
            if on_wait:
                on_wait(len(ahead))
            nap(delay)
            delay = min(delay * 2, most)
    finally:
        env.tickets.drop(env.repo_key, ticket.seq)
