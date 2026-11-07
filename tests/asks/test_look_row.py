"""The look items' look_doc row: an owner's answer and the engine's filing of new items write the same row, each by compare-and-set, so
neither order loses the other's write; the owner's hold on the look bead is not touched by either."""
from support.look_world import world

from tlasks import looks
from tlkernel import gallery
from tlkernel.ids import BeadId
from tlkernel.lookrows import LookRaced, LookRows
from tlkernel.paths import ConfigDir

NOW = 1_800_000_000.0
NEW = {"id": "tl-2#1", "bead": "tl-2", "title": "new", "note": "", "shots": [], "status": "open"}


def rows(workdir):
    return LookRows(ConfigDir(workdir))


def ids(items):
    return {e["id"]: e["status"] for e in items}


def test_an_answer_between_the_engines_read_and_write_is_not_lost(workdir):
    fake, r = world("open"), rows(workdir)
    r.modify("tl-look", lambda: gallery.stored("tl-look", looks.row(fake.beads[BeadId("tl-look")])), lambda i: i)
    seen = []

    def engine(items):  # the engine read the row; the owner answers before the engine writes
        if not seen:
            seen.append(1)
            looks.answer(fake, r, "tl-1#1", "good", "", NOW)
        return [*items, NEW]

    r.modify("tl-look", list, engine)
    assert ids(r.items("tl-look")) == {"tl-1#1": "good", "tl-2#1": "open"}


def test_the_engine_filing_between_the_owners_read_and_write_is_not_lost(workdir):
    fake, r = world("open"), rows(workdir)
    seen = []
    real = r.modify

    def racing(look_bead, seed, fn):
        def fn_then_engine_writes(items):
            if not seen:
                seen.append(1)
                real(look_bead, seed, lambda i: [*i, NEW])  # the engine writes after the owner's read, before the owner's write
            return fn(items)
        return real(look_bead, seed, fn_then_engine_writes)

    r.modify = racing
    assert looks.answer(fake, r, "tl-1#1", "good", "", NOW) == ("good", "")
    assert ids(r.items("tl-look")) == {"tl-1#1": "good", "tl-2#1": "open"}


def test_an_owner_hold_set_during_an_answer_survives(workdir):
    fake, r = world("open", "open"), rows(workdir)
    seen = []
    real = r.modify

    def racing(look_bead, seed, fn):
        def hold_then_answer(items):
            if not seen:
                seen.append(1)
                fake.beads[BeadId("tl-look")].metadata["owner_hold"] = "denis"
            return fn(items)
        return real(look_bead, seed, hold_then_answer)

    r.modify = racing
    looks.answer(fake, r, "tl-1#1", "good", "", NOW)
    assert fake.beads[BeadId("tl-look")].metadata["owner_hold"] == "denis"


def test_a_row_that_never_settles_gives_up_with_a_reason(workdir):
    r = rows(workdir)
    r.modify("b", lambda: [NEW], lambda i: i)

    def always_lose(items):
        r.modify("b", list, lambda i: [*i, dict(NEW, id="x")])
        return items

    try:
        r.modify("b", list, always_lose)
    except LookRaced as err:
        assert "b" in str(err)
    else:
        raise AssertionError("expected LookRaced")


def test_an_old_bead_with_metadata_looks_is_moved_to_the_row_by_the_first_answer(workdir):
    fake, r = world("open"), rows(workdir)
    assert r.items("tl-look") is None
    looks.answer(fake, r, "tl-1#1", "good", "", NOW)
    assert ids(r.items("tl-look")) == {"tl-1#1": "good"}


def test_the_gallery_reads_the_row_before_the_metadata():
    shown = {"metadata": {"looks": [{"id": "a#1", "status": "open"}]}}
    assert [e["status"] for e in gallery.items_of("b", shown, [{"id": "a#1", "status": "good"}])] == ["good"]
    assert [e["status"] for e in gallery.items_of("b", shown)] == ["open"]


def test_gallery_lives_in_look_doc_only(workdir):
    r = rows(workdir)
    r.modify("tl-look", lambda: [NEW], lambda items: items)
    assert r.rows.select("SELECT k FROM look_doc") == [("look:tl-look",)]
    assert r.items("tl-look") == [NEW]
