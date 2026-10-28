"""Jsonl: byte offsets that never move, a cursor that survives a growing file, a torn last line that waits; and the stores on it."""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401
from contracts import samples as S  # noqa: E402
from jsonl_log import Jsonl, cursor  # noqa: E402
from taskloop.contracts import codec, paths, stores  # noqa: E402
from taskloop.contracts.ask import Ask  # noqa: E402
from taskloop.contracts.loop import LoopState  # noqa: E402
from taskloop.contracts.snapshots import Pin  # noqa: E402


class JsonlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "sub" / "x.jsonl"
        self.j = Jsonl(self.path)

    def raw(self, data: bytes):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "ab") as f:
            f.write(data)

    def test_append_returns_the_offset_of_the_line_and_read_returns_it_back(self):
        offs = [self.j.append({"i": i, "s": "é" * i}) for i in range(5)]
        entries, cursor = self.j.read_from(0)
        self.assertEqual([e.start for e in entries], offs)
        self.assertEqual(entries[0].start, 0)
        self.assertEqual(cursor, self.path.stat().st_size)
        self.assertEqual([e.data["i"] for e in entries], list(range(5)))
        self.assertTrue(all(a.end == b.start for a, b in zip(entries, entries[1:])))  # contiguous, in bytes not characters

    def test_a_cursor_returns_only_what_came_after(self):
        for i in range(3):
            self.j.append({"i": i})
        _, cursor = self.j.read_from(0)
        self.assertEqual(self.j.read_from(cursor), ([], cursor))
        off = self.j.append({"i": 3})
        entries, cursor2 = self.j.read_from(cursor)
        self.assertEqual([(e.start, e.data["i"]) for e in entries], [(off, 3)])
        self.assertEqual(off, cursor)
        self.assertEqual(cursor2, self.path.stat().st_size)

    def test_a_torn_last_line_waits_and_the_cursor_stays_at_its_start(self):
        self.j.append({"i": 0})
        start = self.path.stat().st_size
        self.raw(b'{"i": 1, "te')
        entries, cursor = self.j.read_from(0)
        self.assertEqual(([e.data["i"] for e in entries], cursor), ([0], start))
        self.raw(b'xt": "done"}\n')
        entries, cursor = self.j.read_from(cursor)
        self.assertEqual(([(e.start, e.data) for e in entries], cursor), ([(start, {"i": 1, "text": "done"})], self.path.stat().st_size))

    def test_a_torn_multibyte_character_waits_too(self):
        data = (json.dumps({"s": "é"}, ensure_ascii=False) + "\n").encode()
        self.raw(data[:9])
        self.assertEqual(self.j.read_from(0), ([], 0))
        self.raw(data[9:])
        self.assertEqual(self.j.read_from(0)[0][0].data, {"s": "é"})

    def test_a_complete_bad_line_is_passed_not_waited_on(self):
        self.j.append({"i": 0})
        self.raw(b"not json\n[1, 2]\n\xff\xfe\n")
        self.j.append({"i": 1})
        entries, cursor = self.j.read_from(0)
        self.assertEqual([e.data["i"] for e in entries], [0, 1])
        self.assertEqual(cursor, self.path.stat().st_size)

    def test_limit_stops_the_cursor_after_the_last_entry_returned(self):
        for i in range(5):
            self.j.append({"i": i})
        first, cursor = self.j.read_from(0, limit=2)
        rest, end = self.j.read_from(cursor)
        self.assertEqual(([e.data["i"] for e in first], [e.data["i"] for e in rest]), ([0, 1], [2, 3, 4]))
        self.assertEqual(first[-1].end, cursor)

    def test_a_missing_file_reads_empty_and_a_truncated_one_restarts(self):
        self.assertEqual((self.j.read_from(0), self.j.tail(3), self.j.size()), (([], 0), [], 0))
        for i in range(3):
            self.j.append({"i": i})
        _, cursor = self.j.read_from(0)
        self.path.write_text('{"i": 9}\n')
        entries, _ = self.j.read_from(cursor)
        self.assertEqual([e.data["i"] for e in entries], [9])

    def test_offsets_stay_stable_while_a_writer_grows_the_file(self):
        written: list[tuple[int, int]] = []
        stop = threading.Event()

        def writer():
            for i in range(400):
                written.append((self.j.append({"i": i, "pad": "x" * (i % 37)}), i))
            stop.set()

        t = threading.Thread(target=writer)
        t.start()
        seen: list[tuple[int, int]] = []
        cursor = 0
        while not stop.is_set() or cursor < self.path.stat().st_size:
            entries, cursor = self.j.read_from(cursor)
            seen += [(e.start, e.data["i"]) for e in entries]
        t.join()
        self.assertEqual(seen, written)  # no entry lost, none twice, every offset the one append returned

    def test_tail_returns_the_last_entries_oldest_first_across_chunks(self):
        with mock.patch.object(cursor, "CHUNK", 64):
            for i in range(40):
                self.j.append({"i": i, "pad": "y" * 20})
            got = self.j.tail(7)
            self.assertEqual([e.data["i"] for e in got], list(range(33, 40)))
            self.assertEqual(self.j.tail(100)[0].data["i"], 0)
            self.assertEqual(len(self.j.tail(100)), 40)
            self.assertEqual(self.j.tail(0), [])

    def test_tail_ignores_a_torn_last_line_and_agrees_with_read_from(self):
        for i in range(10):
            self.j.append({"i": i})
        self.raw(b'{"i": 10')
        everything, _ = self.j.read_from(0)
        with mock.patch.object(cursor, "CHUNK", 16):
            self.assertEqual(self.j.tail(4), everything[-4:])

    def test_before_pages_back_through_the_file_exactly_once(self):
        for i in range(23):
            self.j.append({"i": i, "pad": "z" * (i % 5)})
        everything, _ = self.j.read_from(0)
        with mock.patch.object(cursor, "CHUNK", 48):
            page = self.j.tail(5)
            collected = list(page)
            while page and page[0].start > 0:
                page = self.j.tail(5, before=page[0].start)
                collected = page + collected
        self.assertEqual(collected, everything)


class StoresTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = paths.ConfigDir(self.tmp.name)

    def test_the_run_log_is_a_typed_union_and_skips_what_it_cannot_read(self):
        rl = stores.RunLog(self.cfg, "tl-1-20261027-000000")
        offs = [rl.append(S.LOG["run_start"]), rl.append(S.LOG["cmd_start"])]
        rl.file.append({"v": 1, "kind": "note", "t": 1.0, "text": "old"})      # a stale v
        rl.file.append({"v": 2, "kind": "from_the_future", "t": 1.0})          # an unknown kind
        rl.append(S.LOG["close"])
        page = rl.read_from(0)
        self.assertEqual([type(i.rec).__name__ for i in page.items], ["RunStart", "CmdStart", "Close"])
        self.assertEqual((page.items[0].start, page.items[1].start, page.skipped), (offs[0], offs[1], 2))
        self.assertEqual(page.cursor, rl.file.size())
        self.assertEqual([type(i.rec).__name__ for i in rl.tail(2).items], ["Close"])  # the two before it are skipped lines
        self.assertEqual(rl.file.path, self.cfg.root / "engine" / "tl-1-20261027-000000.jsonl")

    def test_a_json_document_is_replaced_whole(self):
        st = stores.LoopStateStore(self.cfg, "abc123abc123")
        self.assertIsNone(st.read())
        st.write(S.other(LoopState))
        self.assertEqual(st.read(), S.other(LoopState))
        self.assertEqual(list(st.path.parent.glob("*.tmp")), [])
        self.assertEqual(json.loads(st.path.read_text())["v"], 2)
        st.delete()
        self.assertIsNone(st.read())

    def test_torn_stale_and_alien_files_read_as_absent(self):
        st = stores.LoopCommandStore(self.cfg, "k")
        st.path.parent.mkdir(parents=True)
        for text in ('{"v": 1, "action": "stop', '{"v": 9, "action": "stop_now", "by": "d", "t": 1}', '[]', '{"v": 1, "action": "x"}'):
            st.path.write_text(text)
            self.assertIsNone(st.read(), text)

    def test_a_failed_write_leaves_no_temp_file_and_keeps_the_old_one(self):
        st = stores.PinStore(self.cfg)
        st.write(S.other(Pin))
        with mock.patch.object(Path, "replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                st.write(S.other(Pin))
        self.assertEqual(st.read(), S.other(Pin))
        self.assertEqual(list(st.path.parent.glob("*.tmp")), [])

    def test_each_family_lives_where_paths_says(self):
        self.assertEqual(stores.TraceStore(self.cfg).file.path.name, "traces.jsonl")
        self.assertEqual(stores.AskStore.at(self.cfg).of("tl-1").path, self.cfg.root / "asks" / "tl-1.json")
        stores.AskStore.at(self.cfg).of("tl-1").write(S.other(Ask))
        self.assertEqual(stores.AskStore.at(self.cfg).of("tl-1").read(), S.other(Ask))
        el = stores.EventLog(self.cfg)
        el.append(S.EVENTS["claim"])
        self.assertEqual(el.read_from(0).items[0].rec, S.EVENTS["claim"])
        tr = stores.TraceStore(self.cfg)
        tr.append(S.TRACE)
        self.assertEqual(tr.read_from(0).items[0].rec, S.TRACE)
        self.assertEqual(codec.to_json(tr.read_from(0).items[0].rec), codec.to_json(S.TRACE))


if __name__ == "__main__":
    unittest.main()
