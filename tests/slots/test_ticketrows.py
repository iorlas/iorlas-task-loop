"""The line for a slot in factory.db: numbers past every live ticket, older file and the counter; an older loop's file ticket counts."""
import os
import threading
import time
import uuid

import pytest
from support import homes
from support import slots as sl

from taskloop.stores.ticketrows import TicketRows
from tlkernel.locks import Ticket


@pytest.fixture
def key():
    """Each test has a repo of its own: the config dir is shared by the tests of a process."""
    return f"repo-{uuid.uuid4().hex[:8]}"


def take(rows, key, why="w", prio=2, **kw):
    return rows.take(key, why, prio, pid=os.getpid(), now=time.time(), **kw)


def test_the_line_is_in_priority_then_arrival_order_and_a_number_never_repeats(key):
    rows = TicketRows(homes.cfg())
    a, b, c = take(rows, key, "a"), take(rows, key, "b", prio=0), take(rows, key, "c")
    assert [t.why for t in rows.line(key)] == ["b", "a", "c"]
    rows.drop(key, c.seq)
    assert take(rows, key, "d").seq == c.seq + 1  # past an emptied tail
    assert b.seq == a.seq + 1


def test_a_dead_waiters_row_is_dropped_by_the_reader(key):
    rows = TicketRows(homes.cfg())
    sl.put_ticket_key(key, v=1, seq=5, prio=0, pid=sl.dead_pid(), why="dead", since=1)
    assert rows.line(key) == []


def test_tickets_of_another_repo_are_not_in_the_line(key):
    rows = TicketRows(homes.cfg())
    rows.take(key + "2", "other", 2, pid=os.getpid(), now=time.time())
    assert rows.line(key) == []


def test_threads_taking_at_once_get_distinct_numbers(key):
    rows, got = TicketRows(homes.cfg()), []

    def go():
        got.append(take(TicketRows(homes.cfg()), key).seq)

    threads = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(set(got)) == 6 and [t.seq for t in rows.line(key)] == sorted(got)
    assert isinstance(rows.line(key)[0], Ticket)
