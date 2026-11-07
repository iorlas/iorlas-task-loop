"""The engine's rebase-conflict path when the checkout is reached through a symlinked folder (/var is /private/var on a Mac): the
conflict is still found and goes to a fix round."""

import os
from unittest import mock

from support.engine_case import EngineTest

from land.test_engine_land_1 import EngineLand1Test
from tltestkit.tmpdir import TemporaryDirectory

REAL_TEMP = TemporaryDirectory


class SymlinkedTemp:
    """A TemporaryDirectory whose name is a symlink to the real folder."""

    def __init__(self, *args, **kwargs):
        self.real = REAL_TEMP(*args, **kwargs)
        self.name = self.real.name + "-link"
        os.symlink(self.real.name, self.name)

    def __enter__(self):
        return self.name

    def __exit__(self, *exc):
        self.cleanup()

    def cleanup(self):
        os.unlink(self.name)
        self.real.cleanup()


class TestEngineThroughASymlink(EngineTest):
    def setup_method(self):
        with mock.patch("support.world.TemporaryDirectory", SymlinkedTemp):
            super().setup_method()

    def test_a_rebase_conflict_goes_to_a_fix_round_not_blocked(self):
        assert os.path.realpath(self.tmp.name) != self.tmp.name
        same_case = EngineLand1Test.__dict__["test_a_rebase_conflict_goes_to_a_fix_round_not_blocked"]
        same_case(self)
