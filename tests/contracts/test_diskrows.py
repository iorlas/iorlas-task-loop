"""Free-space samples of the config volume in factory.db's disk_doc table: one a hour, kept a fortnight (tl-7i9k.24.1)."""
import sqlite3

import pytest

from tlkernel import diskrows
from tlkernel.factoryparts import DISK, LOOK

DAY = 86400.0
GB = 1 << 30


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.executescript(LOOK.ddl)
    c.executescript(DISK.ddl)
    yield c
    c.close()


def test_a_second_sample_in_the_same_hour_is_not_kept(con):
    diskrows.sample(con, 10 * GB, 3600.0 * 5 + 10)
    diskrows.sample(con, 9 * GB, 3600.0 * 5 + 3000)
    assert diskrows.samples(con) == [(3600.0 * 5 + 10, 10 * GB)]


def test_samples_come_back_oldest_first_and_a_new_sample_drops_those_past_fourteen_days(con):
    for day in (0, 8, 20):
        diskrows.sample(con, (30 - day) * GB, day * DAY)
    assert diskrows.samples(con) == [(8 * DAY, 22 * GB), (20 * DAY, 10 * GB)]


def test_a_foreign_document_row_is_not_a_sample(con):
    con.execute("INSERT INTO look_doc(k,v,t) VALUES ('unrelated.x','{}',1)")
    assert diskrows.samples(con) == []


def test_samples_live_in_disk_doc_only(con):
    diskrows.sample(con, 10 * GB, 3600.0)
    assert con.execute("SELECT k FROM disk_doc").fetchall() == [("disk.free.1",)]
    assert diskrows.samples(con) == [(3600.0, 10 * GB)]
