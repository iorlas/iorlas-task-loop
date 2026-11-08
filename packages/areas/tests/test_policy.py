"""Area precedence, ancestor caching and conservative exclusion on memory beads."""
from unittest import mock

import pytest
from tlkernel.bead import BdError, Bead
from tlkernel.beadsport import BdFailure
from tlkernel.ids import BeadId
from tltestkit.cfgs import cfg_with
from tltestkit.membeads import MemBeads

from tlareas.policy import ANY_AREA, Areas, area_busy_text, has_areas


@pytest.mark.parametrize("bid,parent,labels,configured,prefix,expected", [
    ("x-1", "e-core.1", ["lane:live"], {"core": ["e-core"], "build": ["build"]}, "lane:", "core"),
    ("x-2", "", ["lane:live", "lane:sim"], {"core": ["e-core"]}, "lane:", "live"),
    ("x-3", "", ["build"], {"core": ["e-core"], "build": ["build"]}, "lane:", "build"),
    ("x-4", "e-9", ["auto"], {"core": ["e-core"]}, "lane:", ""),
    ("x-5", "", ["lane:live"], {}, "", ""),
    ("x-1", "e-core", ["build"], {"first": ["build"], "second": ["x-1", "e-core"]}, "lane:", "first"),
    ("x-1", "", ["lane:"], {}, "lane:", ""),
    ("x-1", "", ["lane:live"], {"empty": None}, "lane:", "live"),
])
def test_area_precedence(bid, parent, labels, configured, prefix, expected):
    store = MemBeads().put(Bead(title="", status="open", id=BeadId("e-core.1"), parent="e-core"))
    areas = Areas(store, configured, prefix, {})
    assert areas.area_of(Bead(title="", status="open", id=BeadId(bid), parent=parent, labels=labels)) == expected


def test_parent_cache_and_cycles():
    store = MemBeads().put(Bead(title="", status="open", id=BeadId("e-1"), parent="e-2"))
    store.put(Bead(title="", status="open", id=BeadId("e-2"), parent="e-1"))
    areas = Areas(store, {}, "", {})
    with mock.patch.object(store, "show", wraps=store.show) as show:
        bead = Bead(title="", status="open", id=BeadId("x-1"), parent="e-1")
        assert areas.epics_of(bead) == ["e-1", "e-2"]
        assert areas.epics_of(bead) == ["e-1", "e-2"]
        assert show.call_count == 2


@pytest.mark.parametrize("raises", [False, True])
def test_unreadable_running_bead_blocks_every_area_and_says_why(raises):
    store, said = MemBeads(), []
    areas = Areas(store, {}, "lane:", {BeadId("x-1"): "s1"}, said.append)
    with mock.patch.object(store, "show", side_effect=BdFailure(BdError(kind="other"))) if raises else mock.patch.object(
        store, "show", return_value=None
    ):
        assert areas.busy_areas() == {ANY_AREA: ("x-1", "s1")}
    assert said == ["running bead x-1 in s1 is unreadable (bd show failed): every area counts as busy"]


def test_self_exclusion_and_sorted_holder_order():
    store = MemBeads()
    for bid in ("x-1", "x-2"):
        store.put(Bead(title="", status="open", id=BeadId(bid), labels=["lane:live"]))
    areas = Areas(store, {}, "lane:", {BeadId("x-2"): "s2", BeadId("x-1"): "s1"})
    assert areas.busy_areas() == {"live": ("x-1", "s1")}
    assert areas.busy_areas(but="x-1") == {"live": ("x-2", "s2")}
    assert area_busy_text(areas, store.beads[BeadId("x-1")]) == ("live", "area live busy: x-2 in s2")
    del areas.running[BeadId("x-2")]
    assert area_busy_text(areas, store.beads[BeadId("x-1")]) == ("live", "")


def test_filter_keeps_unrestricted_beads_and_does_not_reserve_free_areas():
    areas = Areas(MemBeads(), {}, "lane:", {})
    beads = [Bead(title="", status="open", id=BeadId("x-1"), labels=["lane:live"]), Bead(title="", status="open", id=BeadId("x-2"))]
    free, skipped = areas.drop_busy(beads, lambda b: b, {ANY_AREA: ("x-3", "s1")})
    assert free == beads[1:]
    assert [(bid, skip.why) for bid, skip in skipped] == [("x-1", "area live busy: x-3 in s1")]
    assert areas.drop_busy(beads, lambda b: b, {}) == (beads, [])


def test_has_areas_and_no_area_busy_text():
    assert not has_areas(cfg_with())
    assert has_areas(cfg_with(area_label_prefix="lane:"))
    assert has_areas(cfg_with(areas={"core": ["x-1"]}))
    assert area_busy_text(Areas(MemBeads(), {}, "", {}), Bead(title="", status="open", id=BeadId("x-1"))) == ("", "")
