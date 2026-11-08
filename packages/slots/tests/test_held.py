"""An admitted engine lock is published and released under the stop guard."""
import contextlib

import pytest
from tlkernel.env import Env
from tlkernel.paths import ConfigDir

from tlslots import engine_lock
from tlslots.testing import FakeEffects


@pytest.mark.parametrize("raises", [False, True])
def test_held_releases_and_clears_under_guard(tmp_path, monkeypatch, raises):
    effects = FakeEffects()
    lock = engine_lock.EngineLock(ConfigDir(tmp_path), "/wt", "b-1", "s1", Env(), fx=effects.fx)
    held = engine_lock.HeldLock()
    events = []
    @contextlib.contextmanager
    def guard():
        events.append("enter")
        try:
            yield
        finally:
            assert held.slot == ""
            events.append("exit")
    def release():
        assert events == ["enter"]
        assert held.slot == "s1"
        events.append("release")
    monkeypatch.setattr(lock, "release", release)
    with pytest.raises(ValueError) if raises else contextlib.nullcontext(), engine_lock.held(lock, held, guard):
        assert held.slot == "s1"
        assert events == []
        if raises:
            raise ValueError("body")
    assert events == ["enter", "release", "exit"]
    assert held.slot == ""
