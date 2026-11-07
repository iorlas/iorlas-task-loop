"""A torn reflect memory fails closed: the digest does not start from an empty memory (it would file every cluster again)."""
import os
import sys
from pathlib import Path
from unittest import mock

import pytest
from support.case import Case
from support.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import homes

from taskloop.app.report import reflect as rd
from taskloop.contracts.looprows import LoopRows
from taskloop.contracts.wire import Refused


class TornReflect(Case):
    def setup_method(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root / "cfg"), "APPDATA": str(root / "cfg"), "HOME": str(root)})
        env.start()
        self.addCleanup(env.stop)
        self.key = "reflect:digest"
        with LoopRows(homes.cfg(), "").transaction() as con:
            con.execute("INSERT INTO report_doc (k, v, t) VALUES (?, ?, 0) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                        (self.key, self.torn))

    torn = '{"v": 1, "filed"'

    def test_read_and_write_back_refuse_with_the_row(self) -> None:
        with pytest.raises(Refused) as ctx:
            rd.read_state(homes.cfg())
        assert self.key in str(ctx.value)
        with pytest.raises(Refused):
            rd.due(homes.cfg())
        assert LoopRows(homes.cfg(), "").select("SELECT v FROM report_doc WHERE k=?", (self.key,)) == [(self.torn,)]
