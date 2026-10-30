"""Doctor and the engine inspect the same committed base, even from a stale worktree."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401
from support import tlbd  # noqa: E402

from taskloop.app.wire import doctor  # noqa: E402


def shown(p):
    """A path as git and the engine print it: forward slashes and long names on Windows."""
    return Path(p).resolve().as_posix() if os.name == "nt" else str(p)


if __name__ == "__main__":
    unittest.main()


class DoctorBeads(unittest.TestCase):
    """tl-f52: doctor lists the open beads whose text names material no worktree holds."""

    def test_doctor_lists_the_offenders_and_not_the_clean_or_escaped(self):
        beads = [{"id": "x-1", "description": "see ~/Documents/Drop/arch-study-1025/84-self-hosting.md"},
                 {"id": "x-2", "description": "change engine.py"},
                 {"id": "x-3", "description": "study 84 s.2: facts inline", "labels": ["facts-inline"]},
                 {"id": "x-4", "acceptance_criteria": "matches 79-test-impact-and-land-gate.md"},
                 {"id": "x-5", "issue_type": "epic", "description": "study 49"}]
        with mock.patch.dict(os.environ, {"TASK_LOOP_ACTOR": "tl-test"}), tlbd.bd_boundary(result=tlbd.done(json.dumps(beads))):
            out = doctor.bead_lint_warnings("/work/repo")
        self.assertEqual([w.split(":")[0] for w in out], ["bead x-1", "bead x-4"])
        self.assertTrue(all("needs inlined facts" in w for w in out))
