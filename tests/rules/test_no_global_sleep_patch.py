"""No test patches time.sleep for the whole process: a second thread then spins on the mock, which records every call (~110 MB/s of
RSS, the shard-memory runaway of 2026-10-28; docs/dev/runaway-process.md). Use support.engine_case.no_sleep_here or a sleep seam."""
import re
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
BANNED = re.compile(r"""patch\(\s*["']time\.sleep["']|patch\.object\(\s*time\s*,\s*["']sleep["']""")
ALLOWED = {Path(__file__).resolve(), TESTS / "support" / "engine_case.py"}  # the rule itself; the one thread-scoped helper


class NoProcessWideSleepPatch(unittest.TestCase):
    def test_no_test_patches_time_sleep_process_wide(self):
        bad = [f"{p.relative_to(TESTS)}:{n}" for p in sorted(TESTS.rglob("*.py")) if p.resolve() not in ALLOWED
               for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if BANNED.search(line)]
        self.assertEqual(bad, [], "patching time.sleep replaces it for every thread (runaway RSS from a spinning thread); "
                                  "use support.engine_case.no_sleep_here() or patch a sleep seam; see docs/dev/runaway-process.md")


if __name__ == "__main__":
    unittest.main()
