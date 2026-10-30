"""One lock primitive (tl-74i, from tl-09w): src/ and skills/ take no flock/lockf of their own; every lock is the vendored
ProcessLock, reached through taskloop.adapters.locks."""
import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "skills" / "task-loop" / "_vendor"
LOCK_CALLS = {"flock", "lockf"}


def lock_calls(tree):
    return [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in LOCK_CALLS]


class OneLockPrimitive(unittest.TestCase):
    def test_no_flock_or_lockf_outside_the_vendored_packages(self):
        found = []
        for top in ("src", "skills"):
            for f in sorted((ROOT / top).rglob("*.py")):
                if VENDOR in f.parents:
                    continue
                found += [f"{f.relative_to(ROOT)}:{n}" for n in lock_calls(ast.parse(f.read_text(encoding="utf-8")))]
        self.assertEqual(found, [])

    def test_the_scan_sees_a_planted_flock(self):
        self.assertEqual(lock_calls(ast.parse("import fcntl\nfcntl.flock(f, 1)\n")), [2])


if __name__ == "__main__":
    unittest.main()
