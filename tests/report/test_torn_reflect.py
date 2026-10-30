"""A torn reflect memory fails closed: the digest does not start from an empty memory (it would file every cluster again)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.adapters import ident
from taskloop.app.report import reflect as rd
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.wire import Refused


class TornReflect(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root / "cfg"), "APPDATA": str(root / "cfg"), "HOME": str(root)})
        env.start()
        self.addCleanup(env.stop)
        self.path = ConfigDir(ident.config_dir()).reflect_state()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text('{"v": 1, "filed"')

    def test_read_and_write_back_refuse_with_the_path(self) -> None:
        with self.assertRaises(Refused) as ctx:
            rd.read_state()
        self.assertIn(str(self.path), str(ctx.exception))
        with self.assertRaises(Refused):
            rd.due()
        self.assertEqual(self.path.read_text(), '{"v": 1, "filed"')


if __name__ == "__main__":
    unittest.main()
