"""dev/release.py loads every module of the release at start: it rebases and bumps the clone it runs from."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(hasattr(sys, "set_lazy_imports"), "lazy imports are a 3.15 feature")
class Eager(unittest.TestCase):
    def test_the_release_modules_are_loaded_when_the_script_starts(self):
        before = sys.get_lazy_imports()
        self.addCleanup(sys.set_lazy_imports, before)
        for name in [m for m in sys.modules if m.startswith("taskloop.app.release")]:
            self.addCleanup(sys.modules.__setitem__, name, sys.modules.pop(name))
        spec = importlib.util.spec_from_file_location("release_script", ROOT / "dev" / "release.py")
        assert spec and spec.loader
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
        self.assertIn("taskloop.app.release.tidy", sys.modules)  # loaded at start: a lazy import is not in sys.modules until first use
