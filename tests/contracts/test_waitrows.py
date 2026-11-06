"""Parks, network pauses and re-exec notes are `wait` rows (tl-sqd3.26.2): one open row per bead and kind, an older loop's file adopted
once, a row in an older or newer shape read (compatibility), and a database this tl cannot read answered quietly to the dashboard."""
import json
import tempfile
from pathlib import Path

import pytest
import support.paths  # noqa: F401
from support.case import Case
from support.narrow import must

from taskloop.contracts import factorydb
from taskloop.contracts.ids import BeadId
from taskloop.contracts.parks import Park, ParkStore
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import NetPause, ReexecNote
from taskloop.contracts.stores import JsonStore
from taskloop.contracts.waitrows import NET_PAUSE, PARK, WaitDoc, open_records

B = BeadId("t-1")


class WaitRows(Case):
    def setup_method(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = ConfigDir(Path(tmp.name))
        self.parks = ParkStore(self.cfg)

    def park(self, **kw):
        return Park(bead=B, hash="h", runs=1, run="r1", t=5.0, **kw)

    def test_a_park_round_trips_updates_in_place_and_goes_with_drop(self):
        self.parks.put(self.park(retry_at=99.0))
        assert self.parks.get(B) == self.park(retry_at=99.0) and self.parks.retry_at(B, "r1") == 99.0
        self.parks.put(self.park(retry_at=120.0))
        with self.parks.doc(B).rows.transaction() as con:
            assert con.execute("SELECT count(*), wake_at FROM wait WHERE kind='park'").fetchone() == (1, 120.0)
        self.parks.drop(B)
        assert self.parks.get(B) is None

    def test_an_older_loops_park_file_is_adopted_once_and_removed(self):
        JsonStore(self.cfg.park(B), Park).write(self.park())
        assert self.parks.get(B) == self.park() and not self.cfg.park(B).exists()
        assert self.parks.get(B) == self.park()  # now from the row

    def test_a_row_from_a_newer_writer_and_one_from_an_older_writer_both_read(self):
        self.parks.put(self.park())
        with self.parks.doc(B).rows.transaction() as con:
            body = json.loads(con.execute("SELECT facts FROM wait").fetchone()[0])
            newer = {**body, "from_the_future": 1}
            con.execute("UPDATE wait SET facts=?", (json.dumps(newer),))
        assert self.parks.get(B) == self.park()  # the newer key is read past
        older = {k: v for k, v in body.items() if k not in ("reason", "permanence", "retry_at", "attempts", "fingerprint")}
        with self.parks.doc(B).rows.transaction() as con:
            con.execute("UPDATE wait SET facts=?", (json.dumps(older),))
        assert self.parks.get(B) == self.park()  # the fields it lacks take their defaults

    def test_the_dashboard_reads_the_open_records_quietly_even_from_a_database_it_cannot_open(self):
        WaitDoc(self.cfg, NET_PAUSE, B, NetPause, self.cfg.net_pause(B)).write(NetPause(run="r", bead=B, t=1.0))
        assert open_records(self.cfg, NET_PAUSE, NetPause, self.cfg.net_pause(B).parent) == {B: NetPause(run="r", bead=B, t=1.0)}
        must(factorydb.shared_rw(self.cfg.factory_db())).execute("PRAGMA user_version=99")  # a database ahead of this tl
        factorydb.close_shared()
        assert open_records(self.cfg, PARK, Park, self.cfg.park(B).parent) == {}
        with pytest.raises(factorydb.sqlite3.Error):
            self.parks.get(B)

    def test_a_record_with_a_renamed_wire_key_keeps_it_when_unknown_keys_are_dropped(self):

        note = ReexecNote(run="r", bead=B, frm="0.1.0", to="0.2.0", step="land", from_dir="/d", t=1.0)
        doc = WaitDoc(self.cfg, "reexec", B, ReexecNote, self.cfg.reexec_note(B))
        doc.write(note)
        assert doc.get() == note
