"""A doc or SKILL.md that names a worker-run file must name the version route.py contract --json answers with (tl-7y6.8.3)."""
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from support import fake_route  # noqa: E402

PLACES = ("README.md", "skills/task-loop/SKILL.md", "docs/dev", "docs/design", "docs/cutover.md", "docs/roadmap.md")
NAMED = re.compile(r"worker-run[- ]v(\d+)")


def texts():
    for place in PLACES:
        p = ROOT / place
        for f in sorted(p.rglob("*.md")) if p.is_dir() else [p]:
            yield f, f.read_text(encoding="utf-8")


class DocContractVersions(unittest.TestCase):
    def test_the_named_worker_run_version_is_the_contract_delegate_answers_with(self):
        want = fake_route.handshake()["contract"]
        wrong = [(str(f.relative_to(ROOT)), m.group(0)) for f, t in texts() for m in NAMED.finditer(t) if int(m.group(1)) != want]
        self.assertEqual(wrong, [], "docs naming a worker-run version other than contract %s" % want)

    def test_the_contract_file_for_that_version_exists_and_no_other_is_left(self):
        want = fake_route.handshake()["contract"]
        have = sorted(p.name for p in (ROOT / "docs" / "contracts").glob("worker-run-v*.md"))
        self.assertEqual(have, ["worker-run-v%s.md" % want])


if __name__ == "__main__":
    unittest.main()
