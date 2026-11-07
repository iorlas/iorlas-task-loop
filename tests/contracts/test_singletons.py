"""Cold singleton documents round trip as rows in their owning part's document table."""
import json
import sqlite3
import uuid
from dataclasses import replace

import support.paths  # noqa: F401
from support import homes
from support.narrow import must

from tlkernel import dbparts, wire
from tlkernel.factoryparts import RELEASE
from tlkernel.loop import BadVersions
from tlkernel.rowstores import BadVersionStore, PinStore, ReflectStateStore, SharedNotesStore, StatusStore, StatusTriedStore
from tlkernel.snapshots import Pin, ReflectState, SharedNotes, StatusSnapshot, StatusTried


def test_a_pin_is_a_release_doc_row_written_read_and_cleared():
    cfg = homes.cfg()
    store = PinStore(cfg)
    store.delete()
    store.write(Pin(task_loop="0.3.0"))
    assert must(PinStore(cfg).get()).task_loop == "0.3.0"
    assert store.docs.table == "release_doc"
    assert store.docs.rows.select("SELECT k FROM release_doc WHERE k='pin'") == [('pin',)]
    store.delete()
    assert PinStore(cfg).get() is None


def test_an_unknown_key_is_refused_and_a_repo_key_keeps_its_own_row():
    cfg = homes.cfg()
    a, b = f"r-{uuid.uuid4().hex[:6]}", f"r-{uuid.uuid4().hex[:6]}"
    notes = SharedNotesStore(cfg, a)
    assert notes.get() is None and SharedNotesStore(cfg, b).get() is None
    PinStore(cfg).write(Pin(task_loop="0.2.0"))
    with notes.docs.rows.transaction() as con:
        con.execute("UPDATE release_doc SET v=? WHERE k='pin'", (json.dumps(dict(wire.dump(Pin(task_loop="0.2.0")), future=1)),))
    assert PinStore(cfg).get() is None  # an unknown key is refused, never read past


def test_the_reflect_state_is_a_report_doc_row():
    store = ReflectStateStore(homes.cfg())
    store.write(ReflectState())
    assert store.docs.table == "report_doc"
    assert store.docs.rows.select("SELECT k FROM report_doc WHERE k='reflect:digest'") == [("reflect:digest",)]


def test_the_status_rows_live_in_lanes_doc():
    cfg = homes.cfg()
    status, tried = StatusStore(cfg), StatusTriedStore(cfg)
    snapshot, attempt = StatusSnapshot(at=123.0), StatusTried(t=124.0)
    status.write(snapshot)
    tried.write(attempt)
    assert StatusStore(cfg).get() == snapshot
    assert StatusTriedStore(cfg).get() == attempt
    assert status.docs.table == tried.docs.table == "lanes_doc"
    keys = [("snapshot:delegate.status",), ("snapshot:delegate.tried",)]
    assert status.docs.rows.select("SELECT k FROM lanes_doc ORDER BY k") == keys


def test_release_upgrade_discards_the_old_pin_and_preserves_release_result():
    con = sqlite3.connect(":memory:", isolation_level=None)
    dbparts.launch(con, readonly=False, parts=[replace(RELEASE, version=1, records=(), steps={})])
    old_pin = json.dumps({"v": 1, "task-loop": "0.2.0", "delegate": "0.5.0"})
    con.execute("INSERT INTO release_doc VALUES ('pin', ?, 0)", (old_pin,))
    con.execute("INSERT INTO release_doc VALUES ('release', '{}', 0)")
    dbparts.launch(con, readonly=False, parts=[RELEASE])
    assert con.execute("SELECT k, v FROM release_doc").fetchall() == [("release", "{}")]
    assert con.execute("SELECT version FROM schema_part WHERE name='release'").fetchone() == (2,)


def test_shared_notes_live_in_lanes_doc():
    store = SharedNotesStore(homes.cfg(), "repo")
    notes = SharedNotes()
    store.write(notes)
    assert store.get() == notes
    assert store.docs.table == "lanes_doc"
    assert store.docs.rows.select("SELECT k FROM lanes_doc WHERE k='shared:repo'") == [("shared:repo",)]


def test_bad_versions_live_in_loop_doc():
    store = BadVersionStore(homes.cfg())
    store.write(BadVersions())
    assert store.get() == BadVersions()
    assert store.docs.table == "loop_doc"
    assert store.docs.rows.select("SELECT k FROM loop_doc WHERE k='bad-versions'") == [("bad-versions",)]
