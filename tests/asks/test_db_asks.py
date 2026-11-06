"""Run the existing ask and ledger behavior contracts against AskStore.at's database adapter."""

from pathlib import Path

import support.paths  # noqa: F401
from support.case import Case
from support.tmpdir import TemporaryDirectory

from asks import test_ask_v3
from taskloop.app.asks.intake import Intake
from taskloop.contracts import factorydb
from taskloop.contracts.askstore import AskStore
from taskloop.contracts.paths import ConfigDir


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
