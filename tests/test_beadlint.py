"""tl-f52: the bead lint is conservative and has an escape."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "task-loop"))
import beadlint  # noqa: E402

ROOT = "/Users/me/Workspaces/proj"


def refs(**f):
    return beadlint.refs(f, ROOT)


class Detector(unittest.TestCase):
    def test_it_flags_what_a_worktree_cannot_read(self):
        for text in ("see ~/Documents/Drop/arch-study-1025/84-self-hosting.md", "read /Users/me/Documents/x.md",
                     "in /home/me/notes/a.txt", "per Documents/Drop/foo", "arch-study-1025 s.3", "study 84 section 1.4",
                     "Studies 72 to 81", "from 82-owner-answers-1026b.md", "the ~/.config/task-loop folder"):
            with self.subTest(text):
                self.assertTrue(refs(description=text), text)

    def test_it_leaves_ordinary_text_alone(self):
        for text in ("Edit skills/task-loop/engine.py and docs/design/stages.md", "a case study of the loop", "study the code",
                     "see docs/design/12-notes.md", "run `just check` at 10:30-11:00", "https://example.com/a/~/b",
                     "%s/skills/x.py" % ROOT, "tests/test_a-b.md"):
            with self.subTest(text):
                self.assertEqual(refs(description=text), [], text)

    def test_every_text_field_is_read(self):
        for f in ("title", "acceptance_criteria", "design", "notes"):
            self.assertTrue(refs(**{f: "see ~/Documents/Drop/x.md"}), f)

    def test_the_label_and_the_marker_line_override_a_false_positive(self):
        self.assertEqual(refs(description="study 84 s.2", labels=["facts-inline"]), [])
        self.assertEqual(refs(description="study 84 s.2\nfacts-inline: the facts are below\n"), [])
        self.assertTrue(refs(description="the facts-inline marker must start a line: study 84"))

    def test_one_reference_is_reported_once_and_why_names_it(self):
        b = {"description": "~/Documents/Drop/arch-study-1025/28-synthesis.md"}
        self.assertEqual(len(beadlint.refs(b, ROOT)), 1)
        self.assertTrue(beadlint.why(b, ROOT).startswith("needs inlined facts"))
        self.assertEqual(beadlint.why({"description": "fine"}, ROOT), "")


if __name__ == "__main__":
    unittest.main()
