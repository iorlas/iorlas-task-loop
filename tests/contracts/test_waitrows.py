"""Parks, network pauses and re-exec notes are `wait` rows (tl-sqd3.26.2): one open row per bead and kind, a row in an older or newer
shape read (compatibility), and a database this tl cannot read answered quietly to the dashboard."""
import json
import os
import shutil

import pytest
import support.paths  # noqa: F401
from support.case import Case
from support.narrow import must

from taskloop.contracts import factorydb, scratch
from taskloop.contracts.ids import BeadId
from taskloop.contracts.parks import Park, ParkStore
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import NetPause, ReexecNote
from taskloop.contracts.waitrows import NET_PAUSE, PARK, WaitDoc, open_records

B = BeadId("t-1")


class WaitRows(Case):
    def setup_method(self):
        folder = scratch.scratch_dir(os.environ)
        self.addCleanup(shutil.rmtree, folder, True)
        self.cfg = ConfigDir(folder)
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

    def test_a_row_with_an_unknown_key_is_refused_and_one_lacking_fields_takes_defaults(self):
        self.parks.put(self.park())
        with self.parks.doc(B).rows.transaction() as con:
            body = json.loads(con.execute("SELECT facts FROM wait").fetchone()[0])
            newer = {**body, "from_the_future": 1}
            con.execute("UPDATE wait SET facts=?", (json.dumps(newer),))
        assert self.parks.get(B) is None  # the unknown key is refused, never read past
        older = {k: v for k, v in body.items() if k not in ("reason", "permanence", "retry_at", "attempts", "fingerprint")}
        with self.parks.doc(B).rows.transaction() as con:
            con.execute("UPDATE wait SET facts=?", (json.dumps(older),))
        assert self.parks.get(B) == self.park()  # the fields it lacks take their defaults

    def test_the_dashboard_reads_the_open_records_quietly_even_from_a_database_it_cannot_open(self):
        WaitDoc(self.cfg, NET_PAUSE, B, NetPause).write(NetPause(run="r", bead=B, t=1.0))
        assert open_records(self.cfg, NET_PAUSE, NetPause) == {B: NetPause(run="r", bead=B, t=1.0)}
        must(factorydb.shared_rw(self.cfg.factory_db())).execute("PRAGMA user_version=99")  # a database ahead of this tl
        factorydb.close_shared()
        assert open_records(self.cfg, PARK, Park) == {}
        with pytest.raises(factorydb.sqlite3.Error):
            self.parks.get(B)

    def test_a_record_with_a_renamed_wire_key_round_trips(self):
        note = ReexecNote(run="r", bead=B, frm="0.1.0", to="0.2.0", step="land", from_dir="/d", t=1.0)
        doc = WaitDoc(self.cfg, "reexec", B, ReexecNote)
        doc.write(note)
        assert doc.get() == note
