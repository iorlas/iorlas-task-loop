"""Run the existing ask and ledger behavior contracts against AskStore.at's database adapter."""

from pathlib import Path

import support.paths  # noqa: F401

from asks import test_ask_v3
from taskloop.app.asks.intake import Intake
from tlkernel import factorydb
from tlkernel.askstore import AskStore
from tlkernel.paths import ConfigDir
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory


class DatabaseAsks(Case):
    def database(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(factorydb.close_shared)
        return AskStore.at(ConfigDir(Path(tmp.name)))


class DbAskV3(DatabaseAsks, test_ask_v3.AskV3):
    def setup_method(self):
        super().setup_method()
        self.asks = self.database()


class DbLedger(DatabaseAsks, test_ask_v3.Ledger):
    def setup_method(self):
        super().setup_method()
        self.asks = self.database()
        self.verbs = Intake(self.asks, self.beads, lambda: test_ask_v3.T + 5, "denis")


class DbRepeats(DatabaseAsks, test_ask_v3.Repeats):
    def setup_method(self):
        super().setup_method()
        self.asks = self.database()
