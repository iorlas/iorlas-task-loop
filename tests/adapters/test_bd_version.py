"""A bd older than the one that wrote the database is named, not left as bd's raw dolt error."""
import pytest

from taskloop.adapters.bd import BdRun, BdStore
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdFailure

RAW = "Error: failed to open database: embeddeddolt: check table wisps: Error 1105: table has unknown fields"


def store(tmp_path, db_version: str | None, exe_says: str):
    if db_version:
        (tmp_path / ".beads").mkdir()
        (tmp_path / ".beads" / ".local_version").write_text(db_version + "\n")
    calls = []

    def run(argv, cwd):
        calls.append(argv)
        if "--version" in argv:
            return BdRun(0, exe_says, "")
        return BdRun(1, "", RAW)

    return BdStore("a", str(tmp_path), exe="/old/bin/bd", run=run), calls


def test_an_older_bd_than_the_db_is_named_with_its_path(tmp_path):
    bd, _ = store(tmp_path, "1.3.1", "bd version 1.0.3 (dev)")
    with pytest.raises(BdFailure) as err:
        bd.show(BeadId("tl-1"))
    assert "bd 1.0.3 at /old/bin/bd is older than the db's 1.3.1; fix PATH" in err.value.error.text
    assert "unknown fields" in err.value.error.text  # bd's own words stay


def test_a_bd_as_new_as_the_db_keeps_its_own_error(tmp_path):
    bd, _ = store(tmp_path, "1.3.1", "bd version 1.3.1 (c1c4b642a)")
    with pytest.raises(BdFailure) as err:
        bd.show(BeadId("tl-1"))
    assert "older than" not in err.value.error.text


def test_no_db_version_means_no_extra_bd_call(tmp_path):
    bd, calls = store(tmp_path, None, "bd version 1.0.3")
    with pytest.raises(BdFailure):
        bd.show(BeadId("tl-1"))
    assert not any("--version" in c for c in calls)
