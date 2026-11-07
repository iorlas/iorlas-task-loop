"""dev/release.py loads every module of the release at start: it rebases and bumps the clone it runs from."""
import importlib.util
import sys
from pathlib import Path

import pytest

from taskloop.app.launch.release_host import release_host
from tltestkit.case import Case

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(not (hasattr(sys, "set_lazy_imports")), reason="lazy imports are a 3.15 feature")
class Eager(Case):
    def test_the_release_modules_are_loaded_when_the_script_starts(self):
        before = sys.get_lazy_imports()
        self.addCleanup(sys.set_lazy_imports, before)
        for name in [m for m in sys.modules if m.startswith("tlrelease")]:
            self.addCleanup(sys.modules.__setitem__, name, sys.modules.pop(name))
        spec = importlib.util.spec_from_file_location("release_script", ROOT / "dev" / "release.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.release_host is release_host
        assert "tlrelease.tidy" in sys.modules  # loaded at start: a lazy import is not in sys.modules until first use
