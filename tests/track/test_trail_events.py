"""EVENTSV: `trail.event` is the one writer of events.jsonl and writes the typed Event record: `v`, the contract's kind names, only the
contract's fields; strict `events.decode` reads back every row."""
import contextlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, get_args
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import eventlog
from support.who import who

from taskloop.app.track import trail
from taskloop.contracts import events, wire
from taskloop.contracts.events import EventRec

# one call per kind, the fields the code passes (a field the writer sets itself is not here)
CALLS = {
    "claim": {"worktree": "/w", "branch": "task/x-1", "title": "T", "slot": "s1"},
    "stage": {"text": "writing"},
    "slot_take": {"slot": "s1", "slot_bead": "slot-1", "worktree": "/w", "ticket": 3},
    "slot_release": {"slot": "s1", "slot_bead": "slot-1"},
    "slot_setup": {"slot": "s1", "worktree": "/w", "exit": 1, "secs": 4},
    "slot_hold": {"slot": "s1", "slot_bead": "slot-1", "why": "by hand", "until": 1.5e9},
    "slot_aside": {"slot": "s1", "why": "3 runs failed", "held": True},
    "slot_hold_expired": {"slot": "s1", "slot_bead": "slot-1"},
    "block": {"why": "needs a human"},
    "close": {"reason": "done"},
    "land": {"sha": "abc"},
    "reload": {"who": "engine", "old": "1", "new": "2", "step": "n3", "run": "r1", "code_dir": "/c"},
    "reload_fallback": {"who": "loop", "old": "2", "new": "1", "why": "crashed", "run": "r1"},
    "worktree_start": {"worktree": "/w"},
    "worktree_sunset": {"worktree": "/w"},
    "loop_exit": {"who": "loop", "pid": 7, "reason": "idle", "detail": "d"},
    "net_up": {"who": "loop", "down_s": 12},
    "net_down": {"who": "loop", "why": "no route"},
    "install_missing": {"who": "loop", "version": "1", "running": "2", "target": "3"},
}


@contextlib.contextmanager
def isolated_home():
    with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d, "APPDATA": d}):
        yield


class EveryKindDecodes(unittest.TestCase):
    def test_the_calls_cover_every_kind_of_the_contract(self):
        union: Any = events.Event
        self.assertEqual(set(CALLS), {m.__struct_config__.tag for m in get_args(union)})

    def test_each_row_written_decodes_strictly_with_its_fields(self):
        for kind, fields in CALLS.items():
            with self.subTest(kind), isolated_home():
                trail.event(who(), kind, "x-1", repo="/r", **fields)
                (row,) = eventlog.read()
                self.assertEqual(row["v"], EventRec.V)
                got = events.decode(row)
                self.assertEqual((got.kind, got.bead, got.repo), (kind, "x-1", "/r"))
                self.assertEqual({k: v for k, v in wire.dump(got).items() if k in fields}, fields)

    def test_a_kind_or_field_the_contract_does_not_name_is_refused_and_nothing_is_written(self):
        for kind, fields in (("slot-hold", {}), ("land", {"slotty": 1})):
            with self.subTest(kind), isolated_home():
                with self.assertRaises(ValueError):
                    trail.event(who(), kind, "x-1", repo="/r", **fields)
                self.assertEqual(eventlog.read(), [])


if __name__ == "__main__":
    unittest.main()
