"""tl-bxk.10.32: the Grok lane (delegate family xai, OpenCode): login hint, transcript reader, context size, fresh-writer limit."""
import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from typing import cast
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402, F401
from support.builders import cfg_with  # noqa: E402
from support.dashes import make_dash  # noqa: E402
from support.lanes import lane_statuses  # noqa: E402

from taskloop.adapters import (  # noqa: E402
    context_size,
    opencode,
)
from taskloop.app.run.calls import Calls  # noqa: E402
from taskloop.app.track import verbs  # noqa: E402
from taskloop.app.write.handoff import Handoff  # noqa: E402
from taskloop.contracts.delegate import DelegateResult  # noqa: E402
from taskloop.stores.runlog import RunLog  # noqa: E402
from taskloop_dash.api import lanes as lanes_mod  # noqa: E402
from taskloop_dash.views import arrows, names  # noqa: E402

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
    def tok(i, o, r, w):
        return {"role": "assistant", "tokens": {"input": i, "output": o, "reasoning": 0, "cache": {"read": r, "write": w}}}
    msgs = [("m1", T, {"role": "user", "time": {"created": T}}),
            ("m2", T + 1000, tok(5000, 10, 2000, 300)),
            ("m3", T + 5000, tok(9000, 20, 4000, 700)),
            ("m4", T + 9000, tok(0, 0, 0, 0))]
    for i, t, d in msgs:
        con.execute("INSERT INTO message VALUES (?,?,?,?,?)", (i, SID, t, t, json.dumps(d)))
    parts = [
        ("p1", "m1", T, {"type": "text", "text": "do the thing"}),
        ("p2", "m2", T + 1100, {"type": "reasoning", "text": "hmm"}),
        (
            "p3",
            "m2",
            T + 1200,
            {
                "type": "tool",
                "tool": "bash",
                "state": {
                    "status": "completed",
                    "input": {"command": "ls"},
                    "output": "a\nb",
                    "time": {"start": T + 1200, "end": T + 3200},
                },
            },
        ),
        (
            "p4",
            "m3",
            T + 5100,
            {"type": "tool", "tool": "read", "state": {"status": "error", "input": {"filePath": "/x"}, "error": "nope"}},
        ),
        ("p5", "m3", T + 5200, {"type": "text", "text": "done"}),
        ("p6", "m3", T + 5300, {"type": "tool", "tool": "bash", "state": {"status": "running", "input": {"command": "sleep 9"}}}),
    ]
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
        self.dash = make_dash()
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
        b = lanes_mod.lane_banners(lane_statuses({"GROK_SUBSCRIPTION": lane}), time.time())
        self.assertEqual(b["GROK_SUBSCRIPTION"]["text"], "Grok logged out: run opencode auth login")

    # reader
    def test_events_have_the_shape_of_the_other_readers(self):
        ev = self.dash.events.opencode_events(SID)
        self.assertEqual([e["kind"] for e in ev], ["user", "cmd", "cmd", "msg", "cmd"])
        cmd = ev[1]
        self.assertEqual((cmd["tool"], cmd["text"], cmd["state"], cmd["dur"], cmd["detail"]), ("bash", "ls", "ok", 2.0, "a\nb"))
        self.assertEqual((ev[2]["state"], ev[2]["text"]), ("fail", "/x"))
        self.assertEqual(ev[4]["state"], "run")
        self.assertEqual(self.dash.runs.adapters["opencode"], self.dash.events.opencode_events)
        self.assertEqual(self.dash.runs.run_events("opencode:" + SID)[3]["text"], "done")
        win = self.dash.events.opencode_events("opencode:" + SID, 1_790_000_005.0, None)
        self.assertEqual([e["kind"] for e in win], ["cmd", "msg", "cmd"])

    def test_a_missing_db_or_unknown_id_is_empty_never_an_error(self):
        self.assertEqual(self.dash.events.opencode_events("ses_nope"), [])
        self.assertEqual(self.dash.events.opencode_events("not-an-id"), [])
        self.assertEqual(self.dash.runs.run_events("opencode:ses_nope"), [])
        junk = os.path.join(self.tmp.name, "junk.db")
        Path(junk).write_text("not sqlite")
        for path in (os.path.join(self.tmp.name, "gone.db"), junk):
            with mock.patch.dict(os.environ, {"OPENCODE_DB": path}):
                self.assertEqual(self.dash.events.opencode_events(SID), [])
                self.assertEqual(opencode.transcript_of("xai", SID), "")
                self.assertIsNone(context_size.context_tokens("opencode:" + SID))

    def test_the_reader_never_writes(self):
        before = Path(self.db).read_bytes()
        self.dash.events.opencode_events(SID)
        opencode.opencode_context(SID)
        self.assertEqual(Path(self.db).read_bytes(), before)

    # lookups
    def test_transcript_of_xai_is_the_session_reference(self):
        self.assertEqual(opencode.transcript_of("xai", SID), "opencode:" + SID)
        self.assertEqual(opencode.transcript_of("xai", "ses_zzz"), "")
        self.assertEqual(opencode.transcript_of("xai", ""), "")

    def test_context_is_the_last_assistant_message_with_tokens(self):
        self.assertEqual(context_size.context_tokens("opencode:" + SID), 9000 + 4000 + 700)
        self.assertEqual(context_size.context_tokens(SID), 13700)
        self.assertIsNone(context_size.context_tokens("opencode:ses_nope"))

    # fresh-writer limit
    def test_xai_has_its_own_fresh_writer_limit(self):
        eng = types.SimpleNamespace(cfg=cfg_with())
        self.assertEqual(Handoff(eng).fresh_above_k("xai"), 100.0)
        eng.cfg = cfg_with(write_fresh_above_k={"xai": 40})
        self.assertEqual(Handoff(eng).fresh_above_k("xai"), 40.0)
        eng.cfg = cfg_with(write_fresh_above_k={"claude": 1})
        self.assertEqual(Handoff(eng).fresh_above_k("xai"), 100.0)


    # review fixes (7e5b07d)
    def test_api_block_for_xai_names_an_opencode_events_id(self):
        d = {
            "session": {"family": "xai", "ref": SID, "transcript": ""},
            "block": {"who": {"family": "xai"}, "t0": 100.0, "t1": 200.0},
            "checks": [],
        }
        with (
            mock.patch.object(self.dash.records, "run_path", return_value="/x"),
            mock.patch.object(self.dash.runlogs, "block_detail", return_value=d),
        ):
            out = self.dash.runs.api_block("r", "n", 0)
        self.assertEqual(out["events_id"], f"opencode:{SID}@70.0@230.0")
        self.assertEqual(out["transcript"], "opencode:" + SID)
        d["session"]["ref"] = "ses_unknown"
        with (
            mock.patch.object(self.dash.records, "run_path", return_value="/x"),
            mock.patch.object(self.dash.runlogs, "block_detail", return_value=d),
        ):
            out = self.dash.runs.api_block("r", "n", 0)  # a busy or unreadable DB must not blank the block: the id stays, events are empty
        self.assertEqual(out["events_id"], "opencode:ses_unknown@70.0@230.0")
        self.assertEqual(self.dash.runs.run_events(out["events_id"]), [])

    def test_the_newest_part_update_is_the_sessions_last_sign_of_life(self):
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO part VALUES ('p9','m3',?,?,?,'{}')", (SID, T + 9000, T + 99000))
        con.commit()
        con.close()
        self.assertAlmostEqual(opencode.opencode_updated(SID) or 0.0, 1_790_000_099.0)  # a part newer than every message

    def test_a_locked_db_reads_as_empty(self):
        con = sqlite3.connect(self.db, isolation_level=None)
        con.execute("BEGIN EXCLUSIVE")
        try:
            t0 = time.time()
            self.assertEqual(self.dash.events.opencode_events(SID), [])
            self.assertIsNone(opencode.opencode_context(SID))
            self.assertLess(
                time.time() - t0, 120
            )  # hang guard only: a read that blocks on the lock never returns; the empty results above are the gate
        finally:
            con.execute("ROLLBACK")
            con.close()

    def test_a_long_session_shows_its_newest_parts_and_a_window_is_cut_in_sql(self):
        con = sqlite3.connect(self.db)
        for i in range(5100):
            con.execute("INSERT INTO part VALUES (?,?,?,?,?,?)", (f"q{int(i):05d}", "m3", SID, T + 10000 + i, T + 10000 + i,
                                                                  json.dumps({"type": "text", "text": f"t{i}"})))
        con.commit()
        con.close()
        ev = self.dash.events.opencode_events(SID)
        self.assertEqual(len(ev), 5000)
        self.assertEqual(ev[-1]["text"], "t5099")
        self.assertEqual(ev[0]["text"], "t100")
        win = self.dash.events.opencode_events(SID, (T + 10000) / 1000.0 + 0.5, (T + 10000) / 1000.0 + 1.5)
        self.assertTrue(0 < len(win) < 4000)  # +-1 s of slack on each side

    def test_a_non_numeric_tool_time_gives_no_duration(self):
        con = sqlite3.connect(self.db)
        d = {"type": "tool", "tool": "bash", "state": {"status": "completed", "input": {"command": "x"}, "output": "",
                                                       "time": {"start": "a", "end": None}}}
        con.execute("INSERT INTO part VALUES ('z1','m3',?,?,?,?)", (SID, T + 9500, T + 9500, json.dumps(d)))
        con.commit()
        con.close()
        last = self.dash.events.opencode_events(SID)[-1]
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
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = verbs.trace("b-1", 0, True)
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue())[0]["sessions"][0]["transcript"], "")
        sessions = []
        calls = Calls(
            cast(RunLog, types.SimpleNamespace(emit=lambda rec: 0)),
            lambda: None,
            sessions,
            {"tokens_in": 0, "tokens_cached": 0, "tokens_out": 0},
            opencode.opencode_id,
            lambda path: None,
        )
        r = DelegateResult(ref=SID, secs=1, cost=0, family="xai")
        calls.end("c1", "write", "writer", 1, r)
        self.assertEqual(sessions[0]["transcript"], "opencode:" + SID)  # no DB look


if __name__ == "__main__":
    unittest.main()
