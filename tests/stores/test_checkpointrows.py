"""One checkpoint storage contract for SQLite rows and the split-row memory fake."""
import json
import sqlite3
from collections.abc import Iterator
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from contracts.samples import other
from support.memcheckpoints import MemCheckpointDoc, MemCheckpointRows

from tlkernel import dbparts, factorydb, factoryparts, wire
from tlkernel.checkpoint import SECTION_TYPES, Checkpoint, RunState, Shared, StageProgress, join, split
from tlkernel.checkpointrows import CheckpointDoc, CheckpointRows
from tlkernel.dbparts import Part
from tlkernel.docrows import StaleRevision
from tlkernel.docstore import ForeignVersion, Present, Torn
from tlkernel.paths import ConfigDir
from tlkernel.wire import Rec, Refused

type Document = CheckpointDoc | MemCheckpointDoc


@pytest.fixture(params=["sqlite", "memory"])
def rows(request, tmp_path) -> Iterator[CheckpointRows | MemCheckpointRows]:
    if request.param == "memory":
        yield MemCheckpointRows()
    else:
        yield CheckpointRows(ConfigDir(tmp_path))


@pytest.fixture
def doc(rows) -> Document:
    return rows.of("tl-1")


def sample() -> Checkpoint:
    base = other(Checkpoint)
    state = base.state.replace(
        planner_ref="planner", planned=2, replans=3, extra=4, rebase_resets=5,
        fixes=6, accepted_new=["new"], denials=["denied"], writer_family="family",
        stage_tree="tree", leftovers=[{"title": "left"}], followup_ids={"left": "tl-2"},
        look_notes=["note"], look_unjudged={"look": "busy"}, look_done=7, render_stale=True,
    )
    return base.replace(state=state, closed=True, gate_tail="tail", progress=StageProgress(red=1, failed=["check"]))


@pytest.mark.parametrize("n", range(20))
def test_split_join_identity_for_populated_checkpoints(n):
    ck = sample().replace(n=n, state=sample().state.replace(planned=n, done=[str(n)]))
    cursor, sections = split(ck)
    # Exercise the real wire boundary as well as the pure functions.
    decoded = {name: wire.load(SECTION_TYPES[name], wire.dump(section)) for name, section in sections.items()}
    assert join(wire.load(type(cursor), wire.dump(cursor)), decoded) == ck
    owned = [field for name, cls in SECTION_TYPES.items() if name != "review" for field in wire.names(cls)]
    owned += ["review", *wire.names(Shared)]
    assert len(owned) == len(set(owned))
    assert set(owned) == set(wire.names(RunState))


def test_read_write_amend_stale_and_delete(doc):
    ck = sample()
    assert doc.need() is None
    assert not doc.modify(lambda ck: ck)
    doc.write(ck)
    assert doc.need() == ck and doc.revision() == 0
    doc.write(ck.replace(step="next"), expect_rev=0)
    with pytest.raises(StaleRevision):
        doc.write(ck, expect_rev=0)
    assert doc.need() == ck.replace(step="next")
    seen = []
    assert doc.modify_with(lambda ck: ck.replace(step="amended"), seen.append)
    assert len(seen) == 1
    assert doc.need() == ck.replace(step="amended")
    doc.delete()
    assert doc.need() is None and doc.revision() is None
    if isinstance(doc, CheckpointDoc):
        assert doc.docs.rows.select("SELECT * FROM checkpoint_section") == []
        assert doc.store.keys() == []
    else:
        assert all(section.data is None for section in doc.sections.values())


def test_modify_retries_a_lost_revision(doc):
    doc.write(sample())
    seen = []

    def amend(ck):
        seen.append(ck.step)
        if len(seen) == 1:
            doc.write(ck.replace(step="racer"))
        return ck.replace(feedback=ck.step)

    assert doc.modify(amend)
    assert seen == ["write", "racer"]
    assert doc.need().feedback == "racer"


def test_section_failure_rolls_back_every_row(doc):
    ck = sample()
    doc.write(ck)
    changed = ck.replace(step="new", state=ck.state.replace(planned=99, fixes=99, look_done=99))
    if isinstance(doc, CheckpointDoc):
        with doc.docs.rows.transaction() as con:
            con.execute("CREATE TRIGGER fail_section BEFORE UPDATE ON checkpoint_section "
                        "WHEN NEW.section='land' BEGIN SELECT RAISE(ABORT, 'injected'); END")
        with pytest.raises(sqlite3.IntegrityError, match="injected"):
            doc.write(changed)
    else:
        with (patch.object(doc.sections["land"], "write", side_effect=ValueError("injected")),
              pytest.raises(ValueError, match="injected")):
            doc.write(changed)
    assert doc.need() == ck
    assert doc.revision() == 0


def test_only_changed_sections_are_written(doc):
    ck = sample()
    doc.write(ck)
    changed = ck.replace(step="next", state=ck.state.replace(planned=99))
    if isinstance(doc, CheckpointDoc):
        with doc.docs.rows.transaction() as con:
            con.execute("CREATE TEMP TABLE writes (section TEXT)")
            con.execute("CREATE TEMP TRIGGER count_section AFTER UPDATE ON checkpoint_section "
                        "BEGIN INSERT INTO writes VALUES (NEW.section); END")
        doc.write(changed)
        with doc.docs.rows.transaction() as con:
            assert con.execute("SELECT section FROM writes").fetchall() == [("plan",)]
    else:
        seen = []
        original = {name: section.write for name, section in doc.sections.items()}

        def write(name):
            def save(rec: Rec):
                seen.append(name)
                original[name](rec)
            return save

        with ExitStack() as stack:
            for name, section in doc.sections.items():
                stack.enter_context(patch.object(section, "write", side_effect=write(name)))
            doc.write(changed)
        assert seen == ["plan"]
    assert doc.need() == changed


@pytest.mark.parametrize("bad", ["missing", "torn", "foreign", "v4"])
def test_incomplete_or_foreign_checkpoint_refuses(doc, bad):
    doc.write(sample())
    if isinstance(doc, CheckpointDoc):
        with doc.docs.rows.transaction() as con:
            if bad == "missing":
                con.execute("DELETE FROM checkpoint_section WHERE section='land'")
            elif bad == "v4":
                con.execute("UPDATE checkpoint SET body=json_set(body, '$.v', 4)")
            else:
                body = "{" if bad == "torn" else json.dumps({"v": 99})
                con.execute("UPDATE checkpoint_section SET body=? WHERE section='land'", (body,))
    elif bad == "missing":
        doc.sections["land"].delete()
    elif bad == "v4":
        assert doc.cursor.data is not None
        doc.cursor.data["v"] = 4
    elif bad == "foreign":
        doc.sections["land"].data = {"v": 99}
    else:
        doc.sections["land"].data = {"v": 1, "fixes": "not an integer"}
    assert isinstance(doc.read(), (ForeignVersion, Torn))
    assert doc.get() is None
    with pytest.raises(Refused):
        doc.need()
    with pytest.raises(Refused):
        doc.modify(lambda ck: ck)


def test_sqlite_reads_one_transaction_and_modify_with_rolls_back(tmp_path):
    doc = CheckpointRows(ConfigDir(tmp_path)).of("tl-1")
    doc.write(sample())
    statements = []
    open_ro = factorydb.open_ro

    def traced(path):
        con = open_ro(path)
        assert con is not None
        con.set_trace_callback(statements.append)
        return con

    with patch.object(factorydb, "open_ro", side_effect=traced):
        assert isinstance(doc.read(), Present)
    assert sum(sql.startswith("BEGIN") for sql in statements) == 1
    assert sum(sql == "COMMIT" for sql in statements) == 1

    def fail(con):
        assert con is not None
        con.execute("DELETE FROM checkpoint_section")
        raise ValueError("injected")

    with pytest.raises(ValueError, match="injected"):
        doc.modify_with(lambda ck: ck.replace(step="new"), fail)
    assert doc.need() == sample()


def test_pipeline_v2_upgrade_adds_sections_without_migrating_checkpoints():
    pipeline = factoryparts.PIPELINE
    old = Part(name="pipeline", version=2,
               tables=tuple(t for t in pipeline.tables if t != "checkpoint_section"),
               ddl=pipeline.ddl.replace(factoryparts.SECTION_DDL + ";", ""))
    con = sqlite3.connect(":memory:", isolation_level=None)
    try:
        dbparts.launch(con, readonly=False, parts=[old])
        body = '{"v": 4, "bead": "tl-1"}'
        con.execute("INSERT INTO checkpoint VALUES ('tl-1', 1, 7, ?)", (body,))
        dbparts.launch(con, readonly=False, parts=[pipeline])
        assert con.execute("SELECT rev, body FROM checkpoint").fetchall() == [(7, body)]
        assert con.execute("SELECT * FROM checkpoint_section").fetchall() == []
        assert con.execute("SELECT version FROM schema_part WHERE name='pipeline'").fetchone() == (pipeline.version,)
    finally:
        con.close()


def test_store_primitives_and_keys(rows):
    ck = sample()
    assert rows.read(ck.bead) is None and rows.keys() == []
    rows.write(ck)
    assert rows.read(ck.bead) == ck and rows.keys() == [ck.bead]
    rows.write(ck.replace(step="next"), expect_rev=0)
    with pytest.raises(StaleRevision):
        rows.write(ck, expect_rev=0)
    rows.delete(ck.bead)
    assert rows.keys() == [] and rows.read(ck.bead) is None


def test_sqlite_read_cannot_mix_cursor_and_sections_from_different_revisions(tmp_path):
    doc = CheckpointRows(ConfigDir(tmp_path)).of("tl-1")
    ck = sample()
    doc.write(ck)
    new = ck.replace(step="next", state=ck.state.replace(planned=99))
    codec = doc.cursor.codec()
    decode = codec.decode

    def racing_decode(text):
        doc.write(new)
        return decode(text)

    with patch.object(doc.cursor, "codec", return_value=codec), patch.object(codec, "decode", side_effect=racing_decode):
        assert doc.need() == ck
    assert doc.need() == new


def test_foreign_bead_write_is_refused(doc):
    doc.write(sample())
    with pytest.raises(Refused, match="bead differs"):
        doc.write(sample().replace(bead="foreign"))
    assert doc.need() == sample()
