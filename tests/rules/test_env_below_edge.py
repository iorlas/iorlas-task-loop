"""Code below the edge takes an `Env` instead of reading the live process: a ratchet on the calls that still do.

A call is `ambient(`, `ambient_bead(`, `ambient_set(` or `snapshot(` of taskloop.contracts.env, or a Spawner built without an
environment (`real.spawner()`). tests/rules/env_ratchet.json records the count per file; a count above its record fails (a new read of the
live process), and a count below it fails too until the record is lowered (a freed slot cannot be spent again). The edges (tl.py, the
dev scripts, the dashboard's command line) take the snapshot once and are not counted.
"""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
RECORD = Path(__file__).with_name("env_ratchet.json")
EDGE = frozenset({"src/taskloop/contracts/env.py", "src/taskloop_dash/cli/dash.py"})  # the owner of os.environ, and the dashboard's edge
CALL = re.compile(r"\b(?:penv\.)?(?:ambient|ambient_bead|ambient_set|snapshot)\(|\breal\.spawner\(\)|\bwire_real\.spawner\(\)")
NOT_ENV = re.compile(r"\b(?:looks|bf|cfg|self|snap)\.snapshot\(|def snapshot|def ambient")


def count_source(text: str) -> int:
    return sum(1 for line in text.splitlines() for m in CALL.finditer(line) if not NOT_ENV.search(line))


def count_tree(root: Path = ROOT) -> dict[str, int]:
    out: dict[str, int] = {}
    for path in sorted((root / "src").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if "_vendor" in rel or rel in EDGE:
            continue
        n = count_source(path.read_text(encoding="utf-8"))
        if n:
            out[rel] = n
    return out


def problems(actual: dict[str, int], recorded: dict[str, int]) -> list[str]:
    out = []
    for rel in sorted(set(actual) | set(recorded)):
        a, r = actual.get(rel, 0), recorded.get(rel, 0)
        if a > r:
            out.append(f"{rel}: {a} reads of the live process, record {r}: take an Env parameter instead")
        elif a < r:
            out.append(f"{rel}: {a} reads, record {r}: lower tests/rules/env_ratchet.json to {a}")
    return out


class EnvBelowTheEdge(unittest.TestCase):
    def test_no_file_reads_the_process_more_than_its_record(self):
        recorded = json.loads(RECORD.read_text(encoding="utf-8"))
        self.assertEqual(problems(count_tree(), recorded), [])

    def test_a_planted_read_fails(self):
        self.assertEqual(count_source("x = penv.snapshot().vars\ny = real.spawner()\nz = real.spawner(env)\n"), 2)
        self.assertTrue(problems({"a.py": 2}, {"a.py": 1}))
        self.assertTrue(problems({"a.py": 1}, {"a.py": 2}))
        self.assertTrue(problems({"new.py": 1}, {}))
        self.assertEqual(problems({"a.py": 1}, {"a.py": 1}), [])


if __name__ == "__main__":
    unittest.main()
