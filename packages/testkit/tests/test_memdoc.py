"""In-memory stores preserve wire records, retention, and dead-holder recovery."""
from typing import ClassVar

from tlkernel.checks import CheckResult, PassRecord
from tlkernel.docstore import Absent, Present
from tlkernel.ids import CheckId, TreeSha
from tlkernel.lockenums import LockWhat
from tlkernel.locks import LockRecord
from tlkernel.runkey import BaseSha, Digest, RunKey
from tlkernel.wire import Rec
from tltestkit.memdoc import MemDoc, MemDocSet, MemLockTable


class Note(Rec):
    V: ClassVar[int] = 1
    text: str


def test_memdoc_roundtrip():
    doc = MemDoc(Note)
    assert doc.read() == Absent()
    rec = Note(text="héllo")
    doc.write(rec)
    assert doc.read() == Present(rec)
    assert doc.get() == doc.need() == rec
    assert doc.get() is not rec
    doc.delete()
    assert doc.read() == Absent()
    assert doc.get() is None


def test_memdocset_keys_of_and_keep_newest():
    docs = MemDocSet(PassRecord)
    assert docs.of("empty") is docs.of("empty")
    assert docs.keys() == []
    for key, ts in (("old", 1.0), ("new", 3.0), ("middle", 2.0)):
        runkey = RunKey(check=CheckId("test"), cmd=Digest("cmd"), config=Digest("config"),
                        toolchain=Digest("tools"), tree=TreeSha("tree"), base=BaseSha("base"),
                        inputs=Digest("inputs"), selected=Digest("selected"), env=Digest("env"))
        result = CheckResult(id=CheckId("test"), cmd="true", group="tests", exit=0, status="passed")
        rec = PassRecord(key=runkey, result=result, tree=TreeSha("tree"), base=BaseSha("base"), ts=ts)
        docs.of(key).write(rec)
    assert docs.keys() == ["middle", "new", "old"]
    docs.keep_newest(2)
    assert docs.keys() == ["middle", "new"]
    docs.keep_newest(0)
    assert docs.keys() == []


def test_memlocktable_breaks_dead_holder():
    locks = MemLockTable(pid=42, alive=lambda pid: pid == 42)
    dead = LockRecord(what=LockWhat.LAND, holder="dead", pid=41, t=0.0)
    locks.plant(LockWhat.LAND, "repo", dead)
    with locks.hold(LockWhat.LAND, "repo", "new", timeout=0) as held:
        assert held.pid == 42
        assert held.holder == "new"
        assert locks.holder(LockWhat.LAND, "repo") is held
    assert locks.holder(LockWhat.LAND, "repo") is None
