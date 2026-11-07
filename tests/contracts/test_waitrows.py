"""Network pauses and re-exec notes remain pipeline-owned wait rows."""
import os
import shutil

import pytest
import support.paths  # noqa: F401
from support.case import Case
from support.narrow import must

from tlkernel import factorydb, scratch
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir
from tlkernel.run import NetPause, ReexecNote
from tlkernel.waitrows import NET_PAUSE, WaitDoc, open_records

B = BeadId("t-1")


class WaitRows(Case):
    def setup_method(self):
        folder = scratch.scratch_dir(os.environ)
        self.addCleanup(shutil.rmtree, folder, True)
        self.cfg = ConfigDir(folder)

    def test_the_dashboard_reads_the_open_records_quietly_even_from_a_database_it_cannot_open(self):
        WaitDoc(self.cfg, NET_PAUSE, B, NetPause).write(NetPause(run="r", bead=B, t=1.0))
        assert open_records(self.cfg, NET_PAUSE, NetPause) == {B: NetPause(run="r", bead=B, t=1.0)}
        must(factorydb.shared_rw(self.cfg.factory_db())).execute("PRAGMA user_version=99")  # a database ahead of this tl
        factorydb.close_shared()
        assert open_records(self.cfg, NET_PAUSE, NetPause) == {}
        with pytest.raises(factorydb.sqlite3.Error):
            WaitDoc(self.cfg, NET_PAUSE, B, NetPause).get()

    def test_a_record_with_a_renamed_wire_key_round_trips(self):
        note = ReexecNote(run="r", bead=B, frm="0.1.0", to="0.2.0", step="land", from_dir="/d", t=1.0)
        doc = WaitDoc(self.cfg, "reexec", B, ReexecNote)
        doc.write(note)
        assert doc.get() == note
