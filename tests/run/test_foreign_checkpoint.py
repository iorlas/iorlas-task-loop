"""NO BACKWARD COMPATIBILITY (docs/design/compat.md): a checkpoint of a foreign version is refused loudly and the engine starts over."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from support import engine_case as T
from support.checkpoints import put_ck, read_ck
from support.spawn import port_git, real_spawner
from support.who import who

from taskloop.app.run import engine
from taskloop.app.wire import slots as wslots
from taskloop.contracts.docrows import RowDoc
from taskloop.contracts.docstore import ForeignVersion
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId
from taskloop.contracts.wire import Refused


class ForeignCheckpoint(T.EngineTest):
    def test_a_foreign_version_is_refused_loudly_and_the_engine_starts_over(self):
        c = wslots.load_cfg(str(self.wt), port_git())
        eng = engine.Engine(BeadId("t-1"), str(self.wt), c, store=self.store, env=snapshot(), spawner=real_spawner(),
            git=port_git(), who=who())
        put_ck(eng, step="close")
        doc = eng.stores.checkpoints.of(eng.bead)
        assert isinstance(doc, RowDoc)
        with doc.docs.rows.transaction() as con:  # the install that wrote it is another version
            con.execute("UPDATE checkpoint SET body=json_set(body, '$.v', 99) WHERE bead=?", (eng.bead,))
        assert isinstance(doc.read(), ForeignVersion)
        with pytest.raises(Refused, match="v99"):
            doc.need()
        assert read_ck(eng) is None  # absent to a run: nothing is migrated, no crash
        again = engine.Engine(BeadId("t-1"), str(self.wt), c, store=self.store, env=snapshot(), spawner=real_spawner(),
            git=port_git(), who=who())
        assert again.checkpoints.read() is None
