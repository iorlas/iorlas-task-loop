"""The typed edges: a bead id is checked once where text becomes a BeadId, and nothing past the edge checks it again."""
import sys
import unittest
from pathlib import Path

import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.adapters import bd, delegate_wire
from taskloop.contracts.dash import BeadReq
from taskloop.contracts.ids import RunId, is_bead_id, parse_bead_id


class BeadIdEdges(unittest.TestCase):
    def test_the_guard_and_the_parser_agree(self):
        for text in ("tl-1", "a", "9x", "tl-3u6.21", "A_b.c-d"):
            self.assertTrue(is_bead_id(text), text)
            self.assertEqual(parse_bead_id(text), text)
        for text in ("", "-x", ".x", "a b", "a/b", "é", "a\n"):
            self.assertFalse(is_bead_id(text), text)
            with self.assertRaises(ValueError):
                parse_bead_id(text)
        self.assertFalse(is_bead_id(None))
        self.assertFalse(is_bead_id(3))

    def test_a_request_body_with_a_bad_bead_is_refused_when_it_decodes(self):
        self.assertEqual(msgspec.json.decode(b'{"project": "p", "bead": "tl-1"}', type=BeadReq).bead, "tl-1")
        for bad in ("-rf", "a/b", "", "a b"):
            with self.assertRaises(msgspec.ValidationError, msg=bad):
                msgspec.json.decode(msgspec.json.encode({"project": "p", "bead": bad}), type=BeadReq)

    def test_bd_rows_with_an_id_that_is_no_bead_id_are_left_out(self):
        rows = [{"id": "tl-1", "title": "a", "status": "open"}, {"id": "-x", "title": "b", "status": "open"}]
        self.assertEqual([b.id for b in bd.beads_of(rows)], ["tl-1"])

    def test_a_run_name_is_read_once(self):
        rid = RunId.of("tl-3u6.21-20261030-101500")
        self.assertIsNotNone(rid)
        self.assertEqual(rid.bead if rid else None, "tl-3u6.21")
        for bad in ("tl-1", "tl-1-2026-10", "-x-20261030-101500", ""):
            self.assertIsNone(RunId.of(bad), bad)


class DelegateWireChoices(unittest.TestCase):
    def test_pick_and_choice_answer_a_member_of_the_set(self):
        self.assertEqual(delegate_wire.pick("observed", delegate_wire.TTL_SOURCES, "unknown"), "observed")
        self.assertEqual(delegate_wire.pick("bogus", delegate_wire.TTL_SOURCES, "unknown"), "unknown")
        self.assertIsNone(delegate_wire._choice("bogus", delegate_wire.SCOPES))

    def test_a_stop_with_a_scope_outside_the_set_is_refused(self):
        stop = {"reason": "x", "scope": "galaxy", "permanence": "transient", "retry": {"kind": "none"}}
        with self.assertRaises(ValueError):
            delegate_wire.stop_of(stop)
        stop["scope"] = "lane"
        got = delegate_wire.stop_of(stop)
        self.assertIsNotNone(got)
        self.assertEqual(got.scope if got else None, "lane")


if __name__ == "__main__":
    unittest.main()
