"""One durable bead projection: replacement, revisions, health and faithful dashboard rows."""

import pytest

from taskloop_dash.readers.beads import row_of
from tlkernel import beadrows, factorydb
from tlkernel.bead import Bead, Dep
from tlkernel.ids import BeadId


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "factory.db"
    con = factorydb.open_rw(path)
    assert con is not None
    try:
        yield path, con
    finally:
        con.close()


def listing(title="Title"):
    return row_of(Bead(id=BeadId("b-1"), title=title, status="open", priority=2,
                       description="Full description", metadata={"owner": "denis"}, labels=["work"],
                       dependencies=[Dep(id="b-2", type="blocks", title="Dependency", status="closed", close_reason="done")]))


def test_round_trip_is_exactly_the_dashboard_row(database):
    path, con = database
    row = listing()
    with factorydb.begin_immediate(con):
        beadrows.replace_repo(con, "repo", [row], 123, 10)
    assert beadrows.read_repo(path, "repo") == ([row], 10, "")
    assert beadrows.marker_of(con, "repo") == 123
    assert row["dependencies"] == [{"id": "b-2", "type": "blocks", "title": "Dependency", "status": "closed"}]


def test_replace_updates_deletes_and_only_changed_bodies_advance_revision(database):
    path, con = database
    first = listing()
    second = dict(first, id="b-2")
    for rows, marker, now in (([first, second], 1, 10), ([first, second], 2, 20), ([listing("Changed")], 3, 30)):
        with factorydb.begin_immediate(con):
            beadrows.replace_repo(con, "repo", rows, marker, now)
        revisions = con.execute("SELECT title,rev FROM bead ORDER BY title").fetchall()
        assert revisions == ([("Changed", 1)] if now == 30 else [("Title", 0), ("Title", 0)])
    assert beadrows.read_repo(path, "repo") == ([listing("Changed")], 30, "")
    assert con.execute("SELECT fetched,updated FROM bead").fetchone() == (30, 30)


def test_error_keeps_rows_marker_and_success_time_then_recovery_clears_it(database):
    path, con = database
    with factorydb.begin_immediate(con):
        beadrows.replace_repo(con, "repo", [listing()], 12, 10)
    with factorydb.begin_immediate(con):
        beadrows.set_error(con, "repo", "bd locked", 20)
    assert beadrows.read_repo(path, "repo") == ([listing()], 10, "bd locked")
    assert beadrows.observation(con, "repo") == (12, 10, "bd locked", 20)
    with factorydb.begin_immediate(con):
        beadrows.replace_repo(con, "repo", [listing()], 13, 30)
    assert beadrows.read_repo(path, "repo") == ([listing()], 30, "")
    assert con.execute("SELECT rev FROM bead").fetchone() == (0,)


def test_empty_success_and_cold_failure_have_distinct_health(database):
    path, con = database
    assert beadrows.read_repo(path, "repo") == ([], None, "")
    with factorydb.begin_immediate(con):
        beadrows.set_error(con, "repo", "not installed", 1)
        beadrows.replace_repo(con, "empty", [], 2, 3)
    assert beadrows.read_repo(path, "repo") == ([], None, "not installed")
    assert beadrows.read_repo(path, "empty") == ([], 3, "")


def test_repositories_with_the_same_bd_id_are_independent(database):
    path, con = database
    with factorydb.begin_immediate(con):
        beadrows.replace_repo(con, "one", [listing("One")], 1, 10)
        beadrows.replace_repo(con, "two", [listing("Two")], 2, 20)
        beadrows.replace_repo(con, "one", [], 3, 30)
    assert beadrows.read_repo(path, "one") == ([], 30, "")
    assert beadrows.read_repo(path, "two") == ([listing("Two")], 20, "")


def test_missing_database_has_no_fallback_and_uses_database_health(tmp_path):
    path = tmp_path / "factory.db"
    assert beadrows.read_repo(path, "repo") == ([], None, "")
    assert not path.exists()


def test_caller_rollback_restores_listing_and_observation(database):
    path, con = database
    with pytest.raises(ValueError), factorydb.begin_immediate(con):
        beadrows.replace_repo(con, "repo", [listing()], 1, 10)
        raise ValueError("abort")
    assert beadrows.read_repo(path, "repo") == ([], None, "")
