"""Bind the slots package to this machine."""
from tlslots.effects import Effects

from taskloop.adapters import agent, ident, locks, pidcheck

FX = Effects(hostname=ident.hostname, proc_alive=pidcheck.proc_alive, proc_start=pidcheck.proc_start,
             hold_path=locks.hold_path, running_for=agent.running_for)
