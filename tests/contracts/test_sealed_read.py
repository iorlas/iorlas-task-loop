"""JsonStore.read says which of four it found, and a caller that must not read a damaged file as empty refuses it by name."""
import sys
from pathlib import Path

import pytest
from support.case import Case
from support.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from tlkernel.docstore import Absent, ForeignVersion, JsonStore, Present, Torn
from tlkernel.run import NetPause, Reexec
from tlkernel.wire import Refused


class SealedRead(Case):
    def setup_method(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "n.json"
        self.store = JsonStore(self.path, NetPause)

    def test_four_results(self) -> None:
        assert self.store.read() == Absent()
        rec = NetPause(run="r", bead="b", t=1.0)
        self.store.write(rec)
        assert self.store.read() == Present(rec)
        self.path.write_text('{"v": 1, "run": "r"')
        assert isinstance(self.store.read(), Torn)
        self.path.write_text('{"v": 99, "run": "r", "bead": "b", "t": 1.0}')
        assert self.store.read() == ForeignVersion(self.path, 99, NetPause.V)

    def test_get_is_lossy_and_need_refuses_with_the_path(self) -> None:
        assert self.store.need() is None
        self.path.write_text("{")
        assert self.store.get() is None
        with pytest.raises(Refused) as ctx:
            self.store.need()
        assert str(self.path) in str(ctx.value)
        self.path.write_text('{"v": 99}')
        with pytest.raises(Refused) as ctx:
            self.store.need()
        assert str(self.path) in str(ctx.value)


class Handover(Case):
    def test_the_tl_reexec_text_round_trips_and_a_bad_one_is_refused_by_name(self) -> None:
        rec = Reexec(run="r", bead="b", pid=42, frm="0.1.0", owned="s1", fallback=True)
        assert Reexec.parse(rec.text()) == rec
        assert Reexec.parse("") is None
        for bad in ('{"run": "r", "bead": "b", "from": "x", "owned": "s1"}', "{", '{"v": 1, "run": "r"}'):
            with pytest.raises(Refused) as ctx:
                Reexec.parse(bad)
            assert "TL_REEXEC" in str(ctx.value)

    def test_the_reexec_pid_defaults_to_none_for_an_older_install_and_must_be_an_integer(self) -> None:
        old = Reexec.parse('{"v": 1, "run": "r", "bead": "b", "from": "0.1.0"}')
        assert (old and old.pid) == 0
        with pytest.raises(Refused, match="pid"):
            Reexec.parse('{"v": 1, "run": "r", "bead": "b", "from": "0.1.0", "pid": "42"}')
