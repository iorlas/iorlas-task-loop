"""tl-6ax: every delegate call resolves the delegate route.py again; a newer one is used only when it speaks worker-run v2."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent)); import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import engine  # noqa: E402
from lanes import route as lroute  # noqa: E402

V2 = "import json\nprint(json.dumps({'worker_run': 2}))\n"
OLD = "import sys\nsys.exit(2)\n"


class Stub:
    """Just what Engine.delegate_route touches."""
    def __init__(self, cfg, route):
        self.cfg, self.route, self.contract, self.notes = cfg, route, {"worker_run": 2}, []

    def log(self, kind, text, **kw):
        self.notes.append(text)


class RouteRefresh(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        for patch in (mock.patch.object(engine.Path, "home", return_value=Path(self.home.name)),
                      mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(Path(self.home.name, "cfg"))})):
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop("CLAUDE_CONFIG_DIR", None)

    def install(self, v, body=V2):
        p = Path(self.home.name, ".claude/plugins/cache/m/iorlas-delegate", v, "skills/delegate")
        p.mkdir(parents=True, exist_ok=True)
        (p / "route.py").write_text(body)
        return str(p / "route.py")

    def call(self, eng):
        return engine.Engine.delegate_route(eng)

    def test_a_newer_delegate_appearing_between_two_calls_is_used_by_the_second(self):
        old = self.install("0.40.10")
        eng = Stub({}, old)
        self.assertEqual(self.call(eng), old)
        new = self.install("0.40.12")
        self.assertEqual(self.call(eng), new)
        self.assertEqual(eng.route, new)
        self.assertTrue(any("0.40.12" in n for n in eng.notes))

    def test_a_pin_keeps_the_old_one(self):
        old = self.install("0.40.10")
        self.install("0.40.12")
        pin = Path(self.home.name, "cfg", "task-loop", "pinned.json")
        pin.parent.mkdir(parents=True)
        pin.write_text(json.dumps({"delegate": "0.40.10"}))
        eng = Stub({}, old)
        self.assertEqual(self.call(eng), old)

    def test_a_configured_path_wins(self):
        mine = self.install("0.1.0")
        self.install("0.40.12")
        eng = Stub({"delegate": mine}, mine)
        self.assertEqual(self.call(eng), mine)

    def test_a_newer_delegate_without_v2_is_ignored_with_a_note(self):
        old = self.install("0.40.10")
        eng = Stub({}, old)
        self.install("0.40.12", OLD)
        self.assertEqual(self.call(eng), old)
        self.assertTrue(any("keeping" in n and "0.40.12" in n for n in eng.notes))

    def test_every_call_is_logged_with_its_path(self):
        old = self.install("0.40.10")
        eng = Stub({}, old)
        self.call(eng)
        self.call(eng)
        self.assertEqual(sum(old in n for n in eng.notes), 2)


if __name__ == "__main__":
    unittest.main()
