"""tl-bxk.10.32: the Grok lane (delegate family xai, OpenCode): login hint, transcript reader, context size, fresh-writer limit."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
sys.path.insert(0, str(ROOT / "skills" / "task-loop" / "dash"))
import delegate_link as dl  # noqa: E402
import engine  # noqa: E402
import server  # noqa: E402
from taskloop_dash.views import arrows, names  # noqa: E402
from taskloop.app.run.calls import Calls  # noqa: E402
import tl  # noqa: E402
from lanes import call as lcall  # noqa: E402,F401

SID = "ses_abc123"
T = 1_790_000_000_000  # OpenCode stores milliseconds


def make_db(path):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE session (id text PRIMARY KEY, directory text, title text, time_created integer, time_updated integer);
        CREATE TABLE message (id text PRIMARY KEY, session_id text, time_created integer, time_updated integer, data text);
        CREATE TABLE part (id text PRIMARY KEY, message_id text, session_id text, time_created integer, time_updated integer, data text);
    """)
    con.execute("INSERT INTO session VALUES (?,?,?,?,?)", (SID, "/w", "t", T, T + 9000))
    tok = lambda i, o, r, w: {"role": "assistant", "tokens": {"input": i, "output": o, "reasoning": 0, "cache": {"read": r, "write": w}}}  # noqa: E731
    msgs = [("m1", T, {"role": "user", "time": {"created": T}}),
            ("m2", T + 1000, tok(5000, 10, 2000, 300)),
            ("m3", T + 5000, tok(9000, 20, 4000, 700)),
            ("m4", T + 9000, tok(0, 0, 0, 0))]
    for i, t, d in msgs:
        con.execute("INSERT INTO message VALUES (?,?,?,?,?)", (i, SID, t, t, json.dumps(d)))
    parts = [("p1", "m1", T, {"type": "text", "text": "do the thing"}),
             ("p2", "m2", T + 1100, {"type": "reasoning", "text": "hmm"}),
             ("p3", "m2", T + 1200, {"type": "tool", "tool": "bash", "state": {
                 "status": "completed", "input": {"command": "ls"}, "output": "a\nb", "time": {"start": T + 1200, "end": T + 3200}}}),
             ("p4", "m3", T + 5100, {"type": "tool", "tool": "read", "state": {"status": "error", "input": {"filePath": "/x"}, "error": "nope"}}),
             ("p5", "m3", T + 5200, {"type": "text", "text": "done"}),
             ("p6", "m3", T + 5300, {"type": "tool", "tool": "bash", "state": {"status": "running", "input": {"command": "sleep 9"}}})]
    for i, m, t, d in parts:
        con.execute("INSERT INTO part VALUES (?,?,?,?,?,?)", (i, m, SID, t, t, json.dumps(d)))
    con.commit()
    con.close()


class OpenCode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "opencode.db")
        make_db(self.db)
        self.cfg = os.path.join(self.tmp.name, "cfg")
        self.env = mock.patch.dict(os.environ, {"OPENCODE_DB": self.db, "XDG_CONFIG_HOME": self.cfg, "APPDATA": self.cfg})
        self.env.start()
        server._cache.clear()
        self.runs = Path(self.cfg, "agent-runs", "runs")
        self.runs.mkdir(parents=True)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    # login hint
    def test_a_logged_out_xai_lane_says_grok_and_opencode(self):
        self.assertEqual(names.lane_name("GROK_SUBSCRIPTION", ""), "Grok")
        self.assertEqual(names.lane_name("x", "xai"), "Grok")
        self.assertEqual(arrows.pause_reason("paused: logged_out on write; run `opencode auth login` on this machine"),
                         "Grok logged out")
        lane = {"out": True, "reason": "logged_out", "family": "xai"}
        b = server.lane_banners({"v": 1, "lanes": {"GROK_SUBSCRIPTION": lane}})
        self.assertEqual(b["GROK_SUBSCRIPTION"]["text"], "Grok logged out: run opencode auth login")

    # reader
    def test_events_have_the_shape_of_the_other_readers(self):
        ev = server.opencode_events(SID)
        self.assertEqual([e["kind"] for e in ev], ["user", "cmd", "cmd", "msg", "cmd"])
        cmd = ev[1]
        self.assertEqual((cmd["tool"], cmd["text"], cmd["state"], cmd["dur"], cmd["detail"]), ("bash", "ls", "ok", 2.0, "a\nb"))
        self.assertEqual((ev[2]["state"], ev[2]["text"]), ("fail", "/x"))
        self.assertEqual(ev[4]["state"], "run")
        self.assertEqual(server.ADAPTERS["opencode"], server.opencode_events)
        self.assertEqual(server.run_events("opencode:" + SID)[3]["text"], "done")
        win = server.opencode_events("opencode:" + SID, 1_790_000_005.0, None)
        self.assertEqual([e["kind"] for e in win], ["cmd", "msg", "cmd"])

    def test_a_missing_db_or_unknown_id_is_empty_never_an_error(self):
        self.assertEqual(server.opencode_events("ses_nope"), [])
        self.assertEqual(server.opencode_events("not-an-id"), [])
        self.assertEqual(server.run_events("opencode:ses_nope"), [])
        junk = os.path.join(self.tmp.name, "junk.db")
        Path(junk).write_text("not sqlite")
        for path in (os.path.join(self.tmp.name, "gone.db"), junk):
            with mock.patch.dict(os.environ, {"OPENCODE_DB": path}):
                self.assertEqual(server.opencode_events(SID), [])
                self.assertEqual(tl.transcript_of("xai", SID), "")
                self.assertIsNone(engine.context_tokens("opencode:" + SID))

    def test_the_reader_never_writes(self):
        before = Path(self.db).read_bytes()
        server.opencode_events(SID)
        tl.opencode_context(SID)
        self.assertEqual(Path(self.db).read_bytes(), before)

    # lookups
    def test_transcript_of_xai_is_the_session_reference(self):
        self.assertEqual(tl.transcript_of("xai", SID), "opencode:" + SID)
        self.assertEqual(tl.transcript_of("xai", "ses_zzz"), "")
        self.assertEqual(tl.transcript_of("xai", ""), "")

    def test_context_is_the_last_assistant_message_with_tokens(self):
        self.assertEqual(engine.context_tokens("opencode:" + SID), 9000 + 4000 + 700)
        self.assertEqual(engine.context_tokens(SID), 13700)
        self.assertIsNone(engine.context_tokens("opencode:ses_nope"))

    def test_agent_run_session_and_mtime_follow_an_opencode_id(self):
        (self.runs / "r1.json").write_text(json.dumps({"v": 1, "id": "r1", "kind": "opencode", "transcript": SID}))
        self.assertEqual(lcall.agent_run_session("r1"), "opencode:" + SID)
        self.assertAlmostEqual(lcall.file_mtime("opencode:" + SID), 1_790_000_009.0)

    def test_contract_runs_find_the_session_by_session_thread_or_transcript(self):
        now = time.time()
        for i, field in enumerate(("session", "thread", "transcript")):
            (self.runs / ("r%d.json" % i)).write_text(json.dumps({
                "v": 1, "id": "r%d" % i, "kind": "opencode", "family": "xai", "started": now, "status": "running", field: SID}))
        (self.runs / "r9.json").write_text(json.dumps({"v": 1, "id": "r9", "kind": "opencode", "started": now,
                                                       "status": "running", "session": "ses_unknown"}))
        got = {r["id"] for r in server.contract_runs(now - 60)}
        self.assertEqual(got, {"opencode:" + SID, "none:r9"})

    # fresh-writer limit
    def test_xai_has_its_own_fresh_writer_limit(self):
        self.assertEqual(engine.DEFAULTS["write_fresh_above_k"]["xai"], 100)
        eng = types.SimpleNamespace(cfg={})
        self.assertEqual(engine.Engine.fresh_above_k(eng, "xai"), 100.0)
        eng.cfg = {"write_fresh_above_k": {"xai": 40}}
        self.assertEqual(engine.Engine.fresh_above_k(eng, "xai"), 40.0)
        eng.cfg = {"write_fresh_above_k": {"claude": 1}}
        self.assertEqual(engine.Engine.fresh_above_k(eng, "xai"), 100.0)


    # review fixes (7e5b07d)
    def test_api_block_for_xai_names_an_opencode_events_id(self):
        d = {"session": {"family": "xai", "ref": SID, "transcript": ""}, "block": {"who": {"family": "xai"}, "t0": 100.0, "t1": 200.0}, "checks": []}
        with mock.patch.object(server, "run_path", return_value="/x"), mock.patch.object(server, "block_detail", return_value=d):
            out = server.api_block("r", "n", 0)
        self.assertEqual(out["events_id"], "opencode:%s@70.0@230.0" % SID)
        self.assertEqual(out["transcript"], "opencode:" + SID)
        d["session"]["ref"] = "ses_unknown"
        with mock.patch.object(server, "run_path", return_value="/x"), mock.patch.object(server, "block_detail", return_value=d):
            out = server.api_block("r", "n", 0)  # a busy or unreadable DB must not blank the block: the id stays, events are empty
        self.assertEqual(out["events_id"], "opencode:ses_unknown@70.0@230.0")
        self.assertEqual(server.run_events(out["events_id"]), [])

    def test_watchdog_reads_an_opencode_path_by_part_updates_and_survives_a_locked_db(self):
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO part VALUES ('p9','m3',?,?,?,'{}')", (SID, T + 9000, T + 99000))
        con.commit()
        con.close()
        self.assertAlmostEqual(tl.opencode_updated(SID), 1_790_000_099.0)  # a part newer than every message
        t = [1_790_000_100.0]
        w = lcall.Idle(900, 1500, 7200, clock=lambda: t[0], session=lambda r: "opencode:" + SID)
        w.begin()
        w.t0 = t[0] - 60
        self.assertEqual(w.check({"run_id": "r"}, 2820), "")
        t[0] += 600
        self.assertEqual(w.check({"run_id": "r"}, 2820), "")
        with mock.patch.dict(os.environ, {"OPENCODE_DB": os.path.join(self.tmp.name, "gone.db")}):  # unreadable now: last time kept
            self.assertAlmostEqual(lcall.file_mtime("opencode:" + SID), 1_790_000_099.0)
            t[0] += 300
            self.assertEqual(w.check({"run_id": "r"}, 2820), "")

    def test_a_locked_db_reads_as_empty(self):
        con = sqlite3.connect(self.db, isolation_level=None)
        con.execute("BEGIN EXCLUSIVE")
        try:
            t0 = time.time()
            self.assertEqual(server.opencode_events(SID), [])
            self.assertIsNone(tl.opencode_context(SID))
            self.assertLess(time.time() - t0, 120)  # hang guard only: a read that blocks on the lock never returns; the empty results above are the gate
        finally:
            con.execute("ROLLBACK")
            con.close()

    def test_a_long_session_shows_its_newest_parts_and_a_window_is_cut_in_sql(self):
        con = sqlite3.connect(self.db)
        for i in range(5100):
            con.execute("INSERT INTO part VALUES (?,?,?,?,?,?)", ("q%05d" % i, "m3", SID, T + 10000 + i, T + 10000 + i,
                                                                  json.dumps({"type": "text", "text": "t%d" % i})))
        con.commit()
        con.close()
        ev = server.opencode_events(SID)
        self.assertEqual(len(ev), 5000)
        self.assertEqual(ev[-1]["text"], "t5099")
        self.assertEqual(ev[0]["text"], "t100")
        win = server.opencode_events(SID, (T + 10000) / 1000.0 + 0.5, (T + 10000) / 1000.0 + 1.5)
        self.assertTrue(0 < len(win) < 4000)  # +-1 s of slack on each side

    def test_a_non_numeric_tool_time_gives_no_duration(self):
        con = sqlite3.connect(self.db)
        d = {"type": "tool", "tool": "bash", "state": {"status": "completed", "input": {"command": "x"}, "output": "",
                                                       "time": {"start": "a", "end": None}}}
        con.execute("INSERT INTO part VALUES ('z1','m3',?,?,?,?)", (SID, T + 9500, T + 9500, json.dumps(d)))
        con.commit()
        con.close()
        last = server.opencode_events(SID)[-1]
        self.assertEqual((last["text"], "dur" in last), ("x", False))

    def test_a_lane_named_openai_xai_is_grok_by_family_or_name(self):
        self.assertEqual(names.lane_name("OPENAI_XAI"), "Grok")
        self.assertEqual(names.lane_name("OPENAI_SUBSCRIPTION"), "Codex")

    def test_trace_with_a_missing_db_prints_and_the_engine_trace_keeps_the_session_id(self):
        os.environ["OPENCODE_DB"] = os.path.join(self.tmp.name, "gone.db")
        Path(self.cfg, "task-loop").mkdir(parents=True, exist_ok=True)
        rec = {"v": 1, "bead": "b-1", "run": "r", "outcome": "landed", "sessions": [
            {"node": "write", "family": "xai", "ref": SID, "transcript": ""}]}
        Path(self.cfg, "task-loop", "traces.jsonl").write_text(json.dumps(rec) + "\n")
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = tl.cmd_trace(types.SimpleNamespace(id="b-1", last=0, json=True))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue())[0]["sessions"][0]["transcript"], "")
        sessions = []
        calls = Calls(types.SimpleNamespace(emit=lambda rec: 0), lambda: None, sessions, {"tokens_in": 0, "tokens_cached": 0, "tokens_out": 0},
                      tl.opencode_id, lambda path: None)
        r = dl.CallResult(ref=SID, secs=1, cost=0, family="xai", raw={"ref": SID, "transcript": ""})
        calls.end("c1", "write", "writer", 1, r)
        self.assertEqual(sessions[0]["transcript"], "opencode:" + SID)  # no DB look


if __name__ == "__main__":
    unittest.main()
