"""Slot helpers for tests: the slot code reached through tl's composition root, under short names."""
import os
import subprocess
import sys
import time

from taskloop.adapters import ident
from taskloop.app.wire import slots as wslots
from taskloop.app.slots.pool import SlotPool
from taskloop.contracts import paths
from taskloop.stores.files import FileTickets


def pool(repo, store=None, cfg=None):
    return SlotPool(wslots.slot_env(str(repo), store, cfg))


def take_slot(repo, cfg=None, why="tl loop", bead="", ticket=None, store=None):
    """(name, dir, slot bead) of the first free slot, or None."""
    return pool(repo, store, cfg).take_any(why, bead, ticket)


def free_expired(repo):
    p = pool(repo)
    with p.env.take_lock():
        p.free_expired()


def tickets():
    return FileTickets(paths.ConfigDir(ident.config_dir()))


def take_ticket(repo, why, prio=2):
    return tickets().take(wslots.repo_key(str(repo)), why, prio, pid=os.getpid(), now=time.time())


def drop_ticket(repo, t):
    tickets().drop(wslots.repo_key(str(repo)), t.seq)


def ticket_dir(repo):
    d = tickets().cfg.ticket(wslots.repo_key(str(repo)), 0).parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def dead_pid():
    """The pid of a process that has ended."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid
