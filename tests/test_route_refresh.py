"""tl-6ax: every delegate call resolves the delegate route.py again; a newer one is used only when it speaks contract 3."""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402, F401

# isort: split
import seams  # noqa: E402
from support.builders import cfg_with  # noqa: E402

from taskloop.app.run.delegation import Delegation  # noqa: E402

C3 = {"contract": 3, "reasons": {}}
OLD = {"contract": 2, "reasons": {}}


class Stub:
    """Just what Delegation.route touches."""
    def __init__(self, cfg, route):
        self.cfg, self.route, self.contract, self.notes = cfg_with(**cfg), route, {"contract": 3}, []
        self.resolved, self.refusal, self.router = None, None, seams.DelegateRoute()
        self.log = types.SimpleNamespace(note=self.notes.append)


class RouteRefresh(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        for patch in (mock.patch.object(Path, "home", return_value=Path(self.home.name)),
                      mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(Path(self.home.name, "cfg"))})):
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop("CLAUDE_CONFIG_DIR", None)

    def install(self, v, contract=C3, record=True):
        """A delegate version in the cache; `record` makes it the one installed_plugins.json names (the installed one)."""
        root = Path(self.home.name, ".claude/plugins/cache/iorlas-marketplace/iorlas-delegate", v)
        p = root / "skills/delegate"
        p.mkdir(parents=True, exist_ok=True)
        (p / "route.py").write_text("")
        (p / "contract.json").write_text(json.dumps(contract))
        if record:
            rec = Path(self.home.name, ".claude/plugins/installed_plugins.json")
            rec.write_text(json.dumps({"plugins": {"iorlas-delegate@m": [{"scope": "user", "installPath": str(root)}]}}))
        return str(p / "route.py")

    def call(self, eng):
        return Delegation(eng).route()

    def test_a_newer_delegate_appearing_between_two_calls_is_used_by_the_second(self):
        old = self.install("0.40.10")
        eng = Stub({}, old)
        self.assertEqual(self.call(eng), old)
        new = self.install("0.40.12")
        self.assertEqual(self.call(eng), new)
        self.assertEqual(eng.route, new)
        self.assertTrue(any("0.40.12" in n for n in eng.notes))

    def test_a_pin_keeps_the_old_one(self):
        old = self.install("0.40.10", record=False)
        self.install("0.40.12")
        pin = Path(self.home.name, "cfg", "task-loop", "pinned.json")
        pin.parent.mkdir(parents=True)
        pin.write_text(json.dumps({"delegate": "0.40.10"}))
        eng = Stub({}, old)
        self.assertEqual(self.call(eng), old)
        self.assertIsNone(eng.refusal)

    def test_a_configured_path_wins(self):
        mine = self.install("0.1.0")
        self.install("0.40.12")
        eng = Stub({"delegate": mine}, mine)
        self.assertEqual(self.call(eng), mine)

    def test_a_newer_delegate_without_v2_is_ignored_with_a_note(self):
        old = self.install("0.40.10")
        eng = Stub({}, old)
        self.call(eng)
        self.install("0.40.12", OLD)
        self.assertEqual(self.call(eng), old)
        self.assertTrue(any("keeping" in n for n in eng.notes))

    def test_every_call_is_logged_with_its_path(self):
        old = self.install("0.40.10")
        eng = Stub({}, old)
        self.call(eng)
        self.call(eng)
        self.assertEqual(sum(old in n for n in eng.notes), 2)


if __name__ == "__main__":
    unittest.main()
