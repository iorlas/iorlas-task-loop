"""The contract tie (tl-3k5): the reader of delegate's `route.py status --json` against a real answer of delegate 0.51.0, and against
the installed delegate's own answer when there is one. A delegate release that renames or drops a key the reader needs fails here."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from taskloop.adapters import delegate as sdelegate  # noqa: E402
from taskloop.adapters.ident import claude_dir  # noqa: E402
from taskloop.contracts import codec  # noqa: E402
from taskloop.contracts.delegate_status import snapshot_of  # noqa: E402
from taskloop.contracts.snapshots import StatusSnapshot  # noqa: E402

REAL = json.loads((ROOT / "tests" / "fixtures" / "delegate_status_0.51.0_real.json").read_text())


def keys(j: dict, path: str = "") -> set[str]:
    """The key paths of an answer, lists of rows folded into one row's paths."""
    out = set()
    for k, v in j.items():
        out.add(path + k)
        if isinstance(v, dict) and k in ("cockpit", "unlock", "login", "next_worker"):
            out |= keys(v, path + k + ".")
        if isinstance(v, list) and v and isinstance(v[0], dict) and k == "lanes":
            out |= {p for row in v for p in keys(row, path + k + "[].")}
    return out


class Reader(unittest.TestCase):
    def test_a_real_answer_reads_into_a_snapshot_with_every_card_field(self):
        snap = snapshot_of(REAL)
        self.assertEqual([ln.id for ln in snap.lanes], [r["id"] for r in REAL["cockpit"]["lanes"]])
        for ln in snap.lanes:
            self.assertTrue(ln.label and ln.family and ln.kind and ln.model and ln.state and ln.emoji and ln.reason, ln)
        self.assertEqual(snap.at, REAL["ts"])
        self.assertEqual(codec.from_json(StatusSnapshot, codec.to_json(snap)), snap)

    def test_a_dropped_or_renamed_key_fails_the_reader(self):
        for drop in ("ts", "lanes", "cockpit"):
            with self.subTest(drop=drop), self.assertRaises(ValueError):
                snapshot_of({k: v for k, v in REAL.items() if k != drop})
        rows = [{k: v for k, v in r.items() if k != "state"} for r in REAL["cockpit"]["lanes"]]
        with self.assertRaises(ValueError):
            snapshot_of(dict(REAL, cockpit=dict(REAL["cockpit"], lanes=rows)))
        with self.assertRaises(ValueError):
            snapshot_of(dict(REAL, lanes={k: dict(v, out="no") for k, v in REAL["lanes"].items()}))

    def test_the_fixture_has_every_key_the_reader_consumes(self):
        have = keys(REAL)
        for need in ("ts", "lanes", "cockpit", "needs_input", "cockpit.lanes[].id", "cockpit.lanes[].state", "cockpit.lanes[].windows",
                     "cockpit.lanes[].unlock", "cockpit.lanes[].warnings", "cockpit.lanes[].model", "cockpit.lanes[].label",
                     "cockpit.lanes[].family", "cockpit.lanes[].kind", "cockpit.lanes[].emoji", "cockpit.lanes[].reason"):
            self.assertIn(need, have)


class Installed(unittest.TestCase):
    """The installed delegate's real answer has the shape of the fixture and reads."""

    def test_the_installed_delegate_answers_in_the_shape_of_the_fixture(self):
        route = sdelegate.find_route("", None, claude_dir() / "plugins" / "cache", sdelegate.installed_dir(claude_dir()))
        if not route:
            self.skipTest("no delegate installed")
        r = subprocess.run([sys.executable, route, "status", "--json"], capture_output=True, text=True, timeout=60, check=False)
        got = json.loads(r.stdout[r.stdout.index("{"):])
        snapshot_of(got)
        self.assertLessEqual(keys(REAL) - {k for k in keys(REAL) if k.startswith("cockpit.next_worker")}, keys(got),
                             "delegate's status dropped a key the fixture has: refresh tests/fixtures/delegate_status_*.json")


if __name__ == "__main__":
    unittest.main()
