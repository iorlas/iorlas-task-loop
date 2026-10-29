"""CallState (the vendor call on disk) and the network gate (tl-7y6.2.13): checkpoints survive, finished output is never discarded."""
import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import support.paths  # noqa: E402, F401
from support import procsim  # noqa: E402
from support.narrow import must  # noqa: E402

from taskloop.adapters import delegate as dl  # noqa: E402
from taskloop.app.loop.net import NetState  # noqa: E402
from taskloop.domain.lanes import netgate  # noqa: E402
from taskloop.stores import call_state as cs  # noqa: E402

KEY = ("write", 1, 0, 2)


class Calls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "checkpoints"

    def tearDown(self):
        self.tmp.cleanup()

    def begin(self, **kw):
        return cs.begin(self.dir, "run-1", "t-1", KEY, role="worker", lane="OPENAI", now=10.0, **kw)

    def test_begin_writes_calling_before_the_call_and_load_reads_it_back(self):
        self.begin(prompt_sha="abc")
        st = cs.load_for(self.dir, "t-1", KEY)
        self.assertEqual(
            (must(st).phase, must(st).ref, must(st).key, must(st).lane, must(st).prompt_sha), ("calling", "", KEY, "OPENAI", "abc")
        )
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_the_first_ref_sticks_and_survives_a_reload(self):
        st = self.begin()
        st.note_ref("sess-1", 11.0)
        st.note_ref("sess-2", 12.0)
        again = cs.load_for(self.dir, "t-1", KEY)
        self.assertEqual((must(again).ref, must(again).t_ref), ("sess-1", 11.0))

    def test_another_key_a_newer_version_or_a_damaged_file_loads_as_none(self):
        self.begin()
        self.assertIsNone(cs.load_for(self.dir, "t-1", ("write", 1, 0, 3)))
        self.assertIsNone(cs.load_for(self.dir, "t-9", KEY))
        p = cs.path_for(self.dir, "t-1")
        d = json.loads(p.read_text())
        p.write_text(json.dumps(dict(d, v=cs.V + 1)))
        self.assertIsNone(cs.load_for(self.dir, "t-1", KEY))
        p.write_text("{not json")
        self.assertIsNone(cs.load_for(self.dir, "t-1", KEY))

    def test_a_newer_file_with_unknown_fields_still_loads_at_our_version(self):
        self.begin()
        p = cs.path_for(self.dir, "t-1")
        p.write_text(json.dumps(dict(json.loads(p.read_text()), future_field=1)))
        self.assertEqual(must(cs.load_for(self.dir, "t-1", KEY)).phase, "calling")

    def test_a_returned_answer_is_on_disk_and_a_restart_uses_it_without_a_call(self):
        st = self.begin()
        st.returned({"status": "done", "ref": "sess-1", "data": {"x": 1}}, self.dir / "write-2.raw.json", 20.0)
        again = cs.load_for(self.dir, "t-1", KEY)
        self.assertEqual((must(again).phase, must(again).ref), ("returned", "sess-1"))
        what = cs.reattach(again)
        self.assertEqual(must(what)[0], "answer")
        self.assertEqual(must(what)[1]["data"], {"x": 1})

    def test_a_returned_phase_with_a_lost_answer_file_falls_back_to_resuming_the_ref(self):
        st = self.begin()
        st.note_ref("sess-1")
        st.returned({"status": "done"}, self.dir / "a.json")
        (self.dir / "a.json").unlink()
        what = cs.reattach(cs.load_for(self.dir, "t-1", KEY))
        self.assertEqual(what, ("resume", "sess-1", cs.NETWORK_RESUME_DELTA))

    def test_a_call_with_a_ref_resumes_it_with_the_short_note_not_the_brief(self):
        self.begin().note_ref("sess-1")
        what = cs.reattach(cs.load_for(self.dir, "t-1", KEY))
        self.assertEqual(must(what)[:2], ("resume", "sess-1"))
        self.assertLess(len(must(what)[2]), 300)
        self.assertIn("Do not restart", must(what)[2])

    def test_a_call_that_never_got_a_ref_a_consumed_call_and_no_state_call_as_usual(self):
        self.assertIsNone(cs.reattach(None))
        st = self.begin()
        self.assertIsNone(cs.reattach(st))
        st.note_ref("sess-1")
        st.consumed()
        self.assertIsNone(cs.reattach(cs.load_for(self.dir, "t-1", KEY)))
        st.drop()
        self.assertIsNone(cs.load_for(self.dir, "t-1", KEY))

    def test_a_resumed_call_carries_the_ref_it_resumed(self):
        st = self.begin(resume_of="sess-0")
        self.assertEqual((st.resume_of, st.ref), ("sess-0", "sess-0"))


class Gate(unittest.TestCase):
    def test_down_is_one_transition_and_up_is_one_transition(self):
        s, p = NetState(), netgate.FakeProbe([False, False, False, True])
        self.assertTrue(s.mark_down(100.0))
        self.assertFalse(s.mark_down(101.0))
        self.assertEqual([s.poll(p, t) for t in (100.0, 160.0, 220.0, 280.0)], [False, False, False, True])
        self.assertFalse(s.down)
        self.assertFalse(s.poll(p, 340.0))
        self.assertEqual(p.calls, 4)

    def test_it_probes_no_more_than_once_a_minute(self):
        s, p = NetState(), netgate.FakeProbe([False])
        s.mark_down(0.0)
        for t in range(0, 180, 5):
            s.poll(p, float(t))
        self.assertEqual(p.calls, 3)  # 0, 60, 120

    def test_an_unknown_probe_never_holds_the_loop_down_beyond_one_gap(self):
        s, p = NetState(), netgate.FakeProbe([None])
        s.mark_down(0.0)
        self.assertFalse(s.poll(p, 0.0))
        self.assertTrue(s.poll(p, 60.0))

    def probe(self, out, code=0):
        """A RouteProbe over a route.py that is a procsim fake printing `out`; the fake notes the argv it was run with."""
        seen = []

        def route(cwd, env):
            seen.append(" ".join(procsim.argv()[2:]))
            return code, out
        procsim.fake(f"{shlex.quote(sys.executable)} /fake/route.py", route, args=True)
        return dl.RouteProbe("/fake/route.py", ("a.com", "b.com")), seen

    def test_route_probe_parses_the_last_line_and_reads_a_failure_as_unknown(self):
        for out, code, want in (("noise\n{\"v\": 1, \"up\": true}", 0, True), ("{\"v\": 1, \"up\": false}", 0, False),
                                ("", 0, None), ("Traceback", 1, None)):
            probe, _ = self.probe(out, code)
            self.assertIs(probe.up(), want, out)

    def test_route_probe_asks_route_py_net_with_the_hosts(self):
        probe, seen = self.probe("{\"up\": true}")
        probe.up()
        self.assertEqual(seen, ["net --host a.com --host b.com"])


if __name__ == "__main__":
    unittest.main()
