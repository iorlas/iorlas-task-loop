"""A torn ask file fails closed: it is never read as no ask, so a new ask or an answer cannot overwrite it unseen."""
import sys
import tempfile
from pathlib import Path

import pytest
from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from contracts import samples as S

from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.stores import AskStore
from taskloop.contracts.wire import Refused


class TornAsk(Case):
    def setup_method(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = ConfigDir(Path(tmp.name))
        self.asks = AskStore.at(self.cfg)
        self.bead = BeadId("tl-7")
        self.path = self.cfg.ask(self.bead)
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"v": 3, "id": "tl-7-1", "bead"')

    def test_get_and_a_new_ask_refuse_with_the_path_and_leave_the_file(self) -> None:
        with pytest.raises(Refused) as ctx:
            self.asks.get(self.bead)
        assert str(self.path) in str(ctx.value)
        with pytest.raises(Refused):
            self.asks.file(S.ASK.replace(bead=self.bead))
        assert self.path.read_text() == '{"v": 3, "id": "tl-7-1", "bead"'

    def test_a_torn_ask_is_no_orphan_to_be_asked_again(self) -> None:
        assert self.asks.orphans() == []
        assert self.asks.all() == []
