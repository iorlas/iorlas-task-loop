"""The root binds the slots effects without changing adapter call signatures."""
import inspect
import os

from taskloop.adapters import agent, ident, locks, pidcheck
from taskloop.app.wire.slotfx import FX


def test_effect_signatures():
    for name, adapter in (("hostname", ident.hostname), ("proc_alive", pidcheck.proc_alive),
                          ("proc_start", pidcheck.proc_start), ("hold_path", locks.hold_path),
                          ("running_for", agent.running_for)):
        def parameters(call):
            return [(p.name, p.kind) for p in inspect.signature(call).parameters.values()]
        assert parameters(getattr(FX, name)) == parameters(adapter), name


def test_machine_effects():
    assert FX.proc_alive(os.getpid()) is True
    assert FX.hostname() == ident.hostname()
