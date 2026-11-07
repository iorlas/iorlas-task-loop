"""Run projection failures belong to the dashboard."""
from taskloop.contracts import factorydb
from taskloop_dash.readers import runprojection


def test_reader_names_schema_errors_as_database_unavailable(tmp_path):
    path = tmp_path / "factory.db"
    con = factorydb.open_rw(path)
    assert con is not None
    con.execute("PRAGMA user_version=99")
    con.close()
    expected = "database unavailable: factory.db is schema v99, this code knows v5: update it"
    assert runprojection.database_error(path, 1) == expected
    assert runprojection.run_rows(path, 1) == ([], expected)


def test_missing_database_health(tmp_path):
    assert runprojection.database_error(tmp_path / "factory.db", 0) == "database unavailable: missing"


def test_projection_names_unmet_reader_needs(tmp_path, monkeypatch):
    path = tmp_path / "factory.db"
    con = factorydb.open_rw(path)
    assert con is not None
    con.execute("DELETE FROM schema_part WHERE name='pipeline'")
    con.close()
    monkeypatch.setattr(factorydb._STORE, "needs", {"pipeline": 1})
    expected = ("database unavailable: factory.db part pipeline is v0, this process needs v1: "
                "the writer has not upgraded it yet")
    assert runprojection.database_error(path, 1) == expected
    assert runprojection.run_rows(path, 1) == ([], expected)
