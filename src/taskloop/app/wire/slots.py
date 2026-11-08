"""The slot code's world, built from this machine: binds tlslots.machine to this machine's bd, git, ticket line, locks and events. The
composition root for `tl slot ...`, the loop and the engine."""
from collections.abc import Callable
from typing import Concatenate

from tlkernel.beadsport import Beads
from tlkernel.gitport import Git
from tlkernel.ids import loop_key
from tlkernel.paths import ConfigDir
from tlkernel.storeapi import Tickets
from tlslots import config, machine
from tlslots.host import SlotsHost

from taskloop.adapters.beadtools import bd_store, peek
from taskloop.adapters.gitrepo import repo_root
from taskloop.adapters.ident import hostname
from taskloop.adapters.landlock import os_lock
from taskloop.app.track import trail
from taskloop.app.wire import slotfx
from taskloop.stores.real import real_stores


def base_of(repo: str, git: Git) -> str:
    return config.load_cfg(repo, git).base


def bd(actor: str, repo: str) -> Beads:
    return bd_store(actor, repo)  # looked up at call time: a test replaces bd_store here


def tickets(cfg: ConfigDir) -> Tickets:
    return real_stores(cfg).tickets


def host() -> SlotsHost:
    return SlotsHost(bd, peek, repo_root, hostname, os_lock, trail.event, tickets, trail.now, slotfx.FX)  # the effects as bound now


def bound[**P, R](fn: Callable[Concatenate[SlotsHost, P], R]) -> Callable[P, R]:
    def call(*args: P.args, **kwargs: P.kwargs) -> R:
        return fn(host(), *args, **kwargs)
    return call

repo_key = loop_key  # callers ask the wire for the repo's key
slot_table = bound(machine.slot_table)
slot_env = bound(machine.slot_env)
slot_beads = bound(machine.slot_beads)
slot_bead = bound(machine.slot_bead)
slot_of = bound(machine.slot_of)
waiting_line = bound(machine.waiting_line)
wait_slot = bound(machine.wait_slot)
uninitialised = bound(machine.uninitialised)
take_named_slot = bound(machine.take_named_slot)
release_slot = bound(machine.release_slot)
bead_priority = bound(machine.bead_priority)
worktrees = bound(machine.worktrees)
start_worktree = bound(machine.start_worktree)
live_actors = bound(machine.live_actors)
worktree = bound(machine.worktree)
owned_worktrees = bound(machine.owned_worktrees)

named = bound(machine.named)
claimed = bound(machine.claimed)
any_slot = bound(machine.any_slot)
give_back = bound(machine.give_back)
