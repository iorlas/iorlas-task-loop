"""The standalone process sim answers fakes, guards spawns and restores adapters."""
import contextlib
import subprocess
from types import ModuleType

import pytest

from tltestkit import procsim


def test_fake_answers_subprocess_run():
    world = procsim.Procs("fake", guarded=True)
    with contextlib.ExitStack() as stack:
        world.install(stack)
        command = procsim.fake("testkit-answer", procsim.exits(3, "answered"))
        result = subprocess.run([command], capture_output=True, text=True, check=False)
        assert (result.returncode, result.stdout, procsim.ran(command)) == (3, "answered", 1)
    world.check()


def test_guard_rejects_real_spawn():
    world = procsim.Procs("guard", guarded=True)
    with contextlib.ExitStack() as stack:
        world.install(stack)
        with pytest.raises(AssertionError, match="spawned a real process: testkit-unregistered"):
            subprocess.run(["testkit-unregistered"], check=False)
    with pytest.raises(AssertionError, match="spawned a real process"):
        world.check()


def test_registered_adapter_is_answered_and_restored(monkeypatch):
    adapter = ModuleType("testkit_adapter")

    def run_bytes(argv, *, capture=True):
        raise AssertionError("original adapter must not run")

    adapter.__dict__["run_bytes"] = run_bytes
    monkeypatch.setattr(procsim, "SHELL_PROCESS_ADAPTERS", [adapter])
    world = procsim.Procs("adapter", guarded=True)
    with contextlib.ExitStack() as stack:
        world.install(stack)
        command = procsim.fake("testkit-adapter", procsim.exits(0, "bytes"))
        result = adapter.run_bytes([command], capture=True)
        assert (result.returncode, result.stdout) == (0, b"bytes")
        assert adapter.run_bytes([command], capture=False).stdout is None
    assert adapter.run_bytes is run_bytes
    world.check()
