"""RunRows uses shared factory writers for atomic domain updates."""

import time
from pathlib import Path

import pytest

from tlkernel import factorydb
from tlkernel.paths import ConfigDir
from tlkernel.run import RunManifest
from tlkernel.runrows import RunRows
from tltestkit.case import Case
from tltestkit.narrow import must
from tltestkit.tmpdir import TemporaryDirectory


class SharedWriterTest(Case):
    def setup_method(self):
        factorydb.close_shared()
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(factorydb.close_shared)
        self.cfg = ConfigDir(Path(tmp.name))
        self.path = self.cfg.factory_db()

    def shared(self):
        return must(factorydb.shared_rw(self.path))

    def test_runrows_commit_and_rollback_keep_writer_idle_and_changes_atomic(self):
        rows = RunRows(self.cfg)
        manifest = RunManifest(run="r", repo="/repo", bead="b", started=1.0)
        rows.put(manifest)
        con = self.shared()
        assert not con.in_transaction
        with pytest.raises(ValueError, match="abort"), rows.transaction() as writer:
            assert writer is con
            rows.write(writer, manifest.replace(owner="rolled back"))
            raise ValueError("abort")
        assert not con.in_transaction
        assert self.shared() is con
        assert rows.get("r") == manifest
        reader = must(factorydb.open_ro(self.path))
        try:
            assert reader.execute("SELECT count(*) FROM run").fetchone() == (1,)
        finally:
            reader.close()

    def test_200_runrows_put_get_cycles_under_half_a_second(self):
        rows = RunRows(self.cfg)
        manifest = RunManifest(run="r", repo="/repo", bead="b", started=1.0)
        started = time.process_time()
        for _ in range(200):
            rows.put(manifest)
            assert rows.get("r") == manifest
        assert time.process_time() - started < 0.5
