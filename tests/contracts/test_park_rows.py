"""Parks are asks-owned rows, with strict bodies and quiet dashboard reads."""
import json
import os
import shutil
import sqlite3

import msgspec
import pytest
import support.paths  # noqa: F401
from support.case import Case
from support.narrow import must

from taskloop.contracts import dbparts, factorydb, factoryparts, scratch
from taskloop.contracts.ids import BeadId
from taskloop.contracts.parks import Park, ParkStore
from taskloop.contracts.paths import ConfigDir

B = BeadId("t-1")


class ParkRows(Case):
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
        with self.parks.docs.rows.transaction() as con:
            assert con.execute("SELECT count(*) FROM park").fetchone() == (1,)
        self.parks.drop(B)
        assert self.parks.get(B) is None
        assert self.parks.docs.keys() == []

    def test_a_row_with_an_unknown_key_is_refused_and_one_lacking_fields_takes_defaults(self):
        self.parks.put(self.park())
        with self.parks.docs.rows.transaction() as con:
            body = json.loads(con.execute("SELECT body FROM park").fetchone()[0])
            newer = {**body, "from_the_future": 1}
            con.execute("UPDATE park SET body=?", (json.dumps(newer),))
        assert self.parks.get(B) is None  # the unknown key is refused, never read past
        older = {k: v for k, v in body.items() if k not in ("reason", "permanence", "retry_at", "attempts", "fingerprint")}
        with self.parks.docs.rows.transaction() as con:
            con.execute("UPDATE park SET body=?", (json.dumps(older),))
        assert self.parks.get(B) == self.park()  # the fields it lacks take their defaults

    def test_the_dashboard_reads_the_open_records_quietly_even_from_a_database_it_cannot_open(self):
        self.parks.put(self.park())
        assert ParkStore.open_parks(self.cfg) == {B: self.park()}
        must(factorydb.shared_rw(self.cfg.factory_db())).execute("PRAGMA user_version=99")  # a database ahead of this tl
        factorydb.close_shared()
        assert ParkStore.open_parks(self.cfg) == {}
        with pytest.raises(sqlite3.Error):
            self.parks.get(B)

    def test_change_reads_and_writes_in_one_transaction_and_rolls_back_on_failure(self):
        self.parks.put(self.park())
        updated = self.parks.change(B, lambda rec: msgspec.structs.replace(must(rec), runs=2))
        assert updated.runs == 2 and self.parks.get(B) == updated
        assert self.parks.docs.keys() == [B]

        def fail(rec):
            assert rec == updated
            raise ValueError("cancel the change")

        with pytest.raises(ValueError, match="cancel the change"):
            self.parks.change(B, fail)
        assert self.parks.get(B) == updated

    def test_change_creates_an_absent_park(self):
        def create(rec):
            assert rec is None
            return self.park()

        assert self.parks.change(B, create) == self.park()
        assert self.parks.get(B) == self.park()

    @pytest.mark.parametrize("body", ['{', '{"v": 99}'])
    def test_torn_or_foreign_bodies_are_absent_to_both_readers(self, body):
        self.parks.put(self.park())
        with self.parks.docs.rows.transaction() as con:
            con.execute("UPDATE park SET body=?", (body,))
        assert self.parks.get(B) is None
        assert ParkStore.open_parks(self.cfg) == {}


def test_an_asks_part_at_v1_gains_the_park_table_in_place(tmp_path):
    con = sqlite3.connect(tmp_path / "f.db", isolation_level=None)
    v1 = dbparts.Part(name="asks", version=1, tables=("ask",), ddl="CREATE TABLE ask (bead TEXT PRIMARY KEY)")
    dbparts.launch(con, readonly=False, parts=[v1])
    old = dbparts.Part(name="asks", version=2, tables=("ask", "park"), steps=factoryparts.ASKS.steps,
                       ddl=f"CREATE TABLE ask (bead TEXT PRIMARY KEY);\n{factoryparts.PARK_DDL};")
    dbparts.launch(con, readonly=False, parts=[old])
    assert con.execute("SELECT count(*) FROM park").fetchone() == (0,)
    assert con.execute("SELECT version FROM schema_part WHERE name='asks'").fetchone() == (2,)
