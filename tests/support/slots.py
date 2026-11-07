"""Slot helpers for tests: the slot code reached through tl's composition root, under short names."""
import json
import os
import time

from support import homes
from support.spawn import port_git, real_spawner
from support.who import who
from tlslots.pool import SlotPool
from taskloop.app.wire import slots as wslots
from taskloop.stores import ticketrows
from taskloop.stores.ticketrows import TicketRows
from tlkernel.looprows import LoopRows
from tltestkit import procsim


def pool(repo, store=None, cfg=None):
    return SlotPool(wslots.slot_env(str(repo), store, cfg, spawner=real_spawner(), git=port_git(), who=who()))


def take_slot(repo, cfg=None, why="tl loop", bead="", ticket=None, store=None):
    """(name, dir, slot bead) of the first free slot, or None."""
    return pool(repo, store, cfg).take_any(why, bead, ticket)


def free_expired(repo):
    p = pool(repo)
    with p.env.take_lock():
        p.free_expired()


def tickets():
    return TicketRows(homes.cfg())


def take_ticket(repo, why, prio=2):
    return tickets().take(wslots.repo_key(str(repo)), why, prio, pid=os.getpid(), now=time.time())


def drop_ticket(repo, t):
    tickets().drop(wslots.repo_key(str(repo)), t.seq)


def ticket_names(repo):
    """Every ticket of the repo as it sits: rows of the line, dead waiters' too."""
    key = wslots.repo_key(str(repo))
    cfg = homes.cfg()
    sql = "SELECT name FROM lease WHERE kind=? AND name >= ? AND name < ?"
    rows = LoopRows(cfg, "").select(sql, (ticketrows.KIND, *ticketrows.span(key)))
    return [r[0] for r in rows]


def put_ticket(repo, **fields):
    """A ticket row as a waiter that did (or did not) write it whole."""
    put_ticket_key(wslots.repo_key(str(repo)), **fields)


def put_ticket_key(key, **fields):
    with LoopRows(homes.cfg(), "").transaction() as con:
        con.execute("INSERT INTO lease (kind, name, holder, pid, since, body) VALUES (?, ?, ?, ?, ?, ?)",
                    (ticketrows.KIND, ticketrows.name_of(key, fields["seq"]), "t", fields.get("pid"), 1, json.dumps(fields)))


def dead_pid():
    """The pid of a process that has ended."""
    return procsim.DEAD_PID
