"""NO BACKWARD COMPATIBILITY (docs/design/compat.md): a checkpoint of a foreign version is refused by the reader and the engine."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from support import engine_case as T
from support.checkpoints import put_ck
from support.spawn import port_git, real_spawner
from support.who import who

from taskloop.app.run import engine
from tlslots import config as wslots_config
from tlkernel.checkpointrows import CheckpointDoc
from tlkernel.docstore import ForeignVersion
from tlkernel.env import snapshot
from tlkernel.ids import BeadId
from tlkernel.wire import Refused


class ForeignCheckpoint(T.EngineTest):
    def test_a_foreign_version_is_refused_by_the_reader_and_the_engine(self):
        c = wslots_config.load_cfg(str(self.wt), port_git())
        eng = engine.Engine(BeadId("t-1"), str(self.wt), c, store=self.store, env=snapshot(), spawner=real_spawner(),
            git=port_git(), who=who())
        put_ck(eng, step="close")
        doc = eng.stores.checkpoints.of(eng.bead)
        assert isinstance(doc, CheckpointDoc)
        with doc.docs.rows.transaction() as con:  # the install that wrote it is another version
            con.execute("UPDATE checkpoint SET body=json_set(body, '$.v', 4) WHERE bead=?", (eng.bead,))
        assert isinstance(doc.read(), ForeignVersion)
        with pytest.raises(Refused, match="v4"):
            doc.need()
        with pytest.raises(Refused, match="v4"):  # a run does not read past it either: the owner deletes or restores the record
            eng.checkpoints.read()
        with pytest.raises(Refused, match="v4"):
            engine.Engine(BeadId("t-1"), str(self.wt), c, store=self.store, env=snapshot(), spawner=real_spawner(),
                git=port_git(), who=who())
