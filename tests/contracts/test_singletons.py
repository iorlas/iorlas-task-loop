"""Cold singleton documents (pin, bad versions, release result, snapshots) as `kv` rows: round trip, an older file adopted once, the
dashboard's quiet read neither adopts nor raises."""
import json
import uuid

import support.paths  # noqa: F401
from support import homes
from support.narrow import must

from taskloop.contracts import wire
from taskloop.contracts.docrows import singleton
from taskloop.contracts.snapshots import Pin
from taskloop.contracts.stores import PinStore, SharedNotesStore


def test_a_pin_is_a_kv_row_written_read_and_cleared():
    cfg = homes.cfg()
    store = PinStore(cfg)
    store.delete()
    store.write(Pin(task_loop="0.3.0"))
    assert must(PinStore(cfg).get()).task_loop == "0.3.0" and not cfg.pin().exists()
    store.delete()
    assert PinStore(cfg).get() is None


def test_an_older_tls_file_is_adopted_once_and_removed():
    cfg = homes.cfg()
    PinStore(cfg).delete()
    cfg.pin().parent.mkdir(parents=True, exist_ok=True)
    cfg.pin().write_text(json.dumps(wire.dump(Pin(task_loop="0.1.0"))))
    assert must(PinStore(cfg).get()).task_loop == "0.1.0"
    assert not cfg.pin().exists() and must(PinStore(cfg).get()).task_loop == "0.1.0"


def test_a_newer_writers_extra_key_is_read_past_and_a_repo_key_keeps_its_own_row():
    cfg = homes.cfg()
    a, b = f"r-{uuid.uuid4().hex[:6]}", f"r-{uuid.uuid4().hex[:6]}"
    notes = SharedNotesStore(cfg, a)
    assert notes.get() is None and SharedNotesStore(cfg, b).get() is None
    PinStore(cfg).write(Pin(task_loop="0.2.0"))
    with notes.docs.rows.transaction() as con:
        con.execute("UPDATE kv SET v=? WHERE k='pin'", (json.dumps(dict(wire.dump(Pin(task_loop="0.2.0")), future=1)),))
    assert must(PinStore(cfg).get()).task_loop == "0.2.0"


def test_a_quiet_read_does_not_adopt_an_older_file():
    cfg = homes.cfg()
    PinStore(cfg).delete()
    cfg.pin().parent.mkdir(parents=True, exist_ok=True)
    cfg.pin().write_text(json.dumps(wire.dump(Pin(task_loop="0.1.0"))))
    assert must(singleton(cfg, Pin, "pin", cfg.pin(), quiet=True).get()).task_loop == "0.1.0"
    assert cfg.pin().exists()
