"""The typed edges: a bead id is checked once where text becomes a BeadId, and nothing past the edge checks it again."""
import sys
from pathlib import Path

import msgspec
import pytest
from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.adapters import bd, delegate_wire
from taskloop.contracts.dash import ParkReq
from taskloop.contracts.ids import RunId, is_bead_id, parse_bead_id
from taskloop.contracts.ports import BdFailure


class BeadIdEdges(Case):
    def test_the_guard_and_the_parser_agree(self):
        for text in ("tl-1", "a", "9x", "tl-3u6.21", "A_b.c-d"):
            assert is_bead_id(text), text
            assert parse_bead_id(text) == text
        for text in ("", "-x", ".x", "a b", "a/b", "é", "a\n"):
            assert not is_bead_id(text), text
            with pytest.raises(ValueError):
                parse_bead_id(text)
        assert not is_bead_id(None)
        assert not is_bead_id(3)

    def test_a_request_body_with_a_bad_bead_is_refused_when_it_decodes(self):
        assert msgspec.json.decode(b'{"project": "p", "bead": "tl-1", "run": "r"}', type=ParkReq).bead == "tl-1"
        for bad in ("-rf", "a/b", "", "a b"):
            with pytest.raises(msgspec.ValidationError):
                msgspec.json.decode(msgspec.json.encode({"project": "p", "bead": bad, "run": "r"}), type=ParkReq)

    def test_bd_rows_with_an_id_that_is_no_bead_id_fault_the_whole_read(self):
        rows = [{"id": "tl-1", "title": "a", "status": "open"}, {"id": "-x", "title": "b", "status": "open"}]
        with pytest.raises(BdFailure) as cm:
            bd.beads_of(rows)
        assert cm.value.error.kind == "malformed"

    def test_a_run_name_is_read_once(self):
        rid = RunId.of("01KBN6Z0M4R5E8YQ2T7C9W3XHD")
        assert str(rid) == "01KBN6Z0M4R5E8YQ2T7C9W3XHD"
        for bad in ("tl-1", "tl-3u6.21-20261030-101500", ""):
            assert RunId.of(bad) is None, bad


class DelegateWireChoices(Case):
    def test_pick_and_choice_answer_a_member_of_the_set(self):
        assert delegate_wire.pick("observed", delegate_wire.TTL_SOURCES, "unknown") == "observed"
        assert delegate_wire.pick("bogus", delegate_wire.TTL_SOURCES, "unknown") == "unknown"
        assert delegate_wire._choice("bogus", delegate_wire.SCOPES) is None

    def test_a_stop_with_a_scope_outside_the_set_is_refused(self):
        stop = {"reason": "x", "scope": "galaxy", "permanence": "transient", "retry": {"kind": "none"}}
        with pytest.raises(ValueError):
            delegate_wire.stop_of(stop)
        stop["scope"] = "lane"
        got = delegate_wire.stop_of(stop)
        assert got is not None
        assert (got.scope if got else None) == "lane"
