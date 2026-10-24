"""tl-65w: a task worked hours ago in a long session shows its events: the window of a huge transcript is found by byte offset,
not by reading only the last TAIL_BYTES."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop" / "dash"))
import server  # noqa: E402

T0 = datetime(2026, 10, 24, 0, 0, 0, tzinfo=timezone.utc).timestamp()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def line(n):
    """One assistant text per second, padded so the file is big: 'msg n' says which."""
    return json.dumps({"type": "assistant", "timestamp": iso(T0 + n),
                       "message": {"content": [{"type": "text", "text": "msg %d %s" % (n, "x" * 300)}]}})


class Window(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "s.jsonl")
        with open(self.path, "w") as f:
            for n in range(3000):
                f.write(line(n) + "\n")
                if n % 500 == 0:
                    f.write('{"type": "queue-operation"}\n')  # a line with no timestamp
        self.tail = mock.patch.object(server, "TAIL_BYTES", 200_000)
        self.tail.start()

    def tearDown(self):
        self.tail.stop()
        self.tmp.cleanup()

    def texts(self, t0, t1=None):
        return [int(e["text"].split()[1]) for e in server.claude_events(self.path, T0 + t0, T0 + t1 if t1 else None)]

    def test_a_window_far_before_the_tail_is_found(self):
        got = self.texts(400, 450)
        self.assertEqual(got, list(range(399, 452)))  # claude_events keeps a second of slack on both sides

    def test_the_window_start_at_the_file_start_and_a_window_inside_the_tail(self):
        self.assertEqual(self.texts(0, 5)[:3], [0, 1, 2])
        self.assertEqual(self.texts(2990)[-1], 2999)

    def test_no_window_is_the_tail_as_before(self):
        got = [int(e["text"].split()[1]) for e in server.claude_events(self.path)]
        self.assertEqual(got[-1], 2999)
        self.assertGreater(got[0], 1000)

    def test_a_window_after_the_end_is_empty_and_a_missing_file_is_too(self):
        self.assertEqual(self.texts(5000, 5100), [])
        self.assertEqual(server.window_lines(str(Path(self.tmp.name) / "nope"), T0, None), [])

    def test_a_small_file_is_just_read(self):
        small = Path(self.tmp.name) / "small.jsonl"
        small.write_text(line(1) + "\n" + line(2) + "\n")
        with mock.patch.object(server, "TAIL_BYTES", 6_000_000):
            self.assertEqual(len(server.window_lines(str(small), T0 + 1, None)), 2)

    def test_it_reads_a_bounded_amount_from_the_middle(self):
        with mock.patch.object(server, "WINDOW_BYTES", 5000):
            n = len(server.window_lines(self.path, T0 + 400, None))
        self.assertLess(n, 20)  # not the whole 1 MB, and no half line


if __name__ == "__main__":
    unittest.main()
