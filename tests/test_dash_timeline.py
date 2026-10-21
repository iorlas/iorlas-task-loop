"""The task-first dashboard: /api/tasks, /api/task-timeline, /api/block, built from the engine's records. Old runs
(before the structured records) are read from their node, session and warn text: the fixture is six real runs of
lifesim-d5f.58 (2026-10-21), trimmed."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop" / "dash"))
import server  # noqa: E402
import timeline  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "state"
BEAD = "lifesim-d5f.58"
RUNS = ["072411", "074926", "090321", "093704", "103215", "105946"]


def log(stamp):
    return str(FIXTURE / "engine" / ("%s-20261021-%s.jsonl" % (BEAD, stamp)))


def kinds(run):
    return [b["kind"] for b in run["blocks"]]


def causes(run):
    return [(b["arrow"] or {}).get("cause") for b in run["blocks"]]


class LegacyRuns(unittest.TestCase):
    """Runs logged before the structured records: the timeline comes from their text."""

    def run_of(self, stamp, **kw):
        return timeline.run_timeline(log(stamp), **kw)

    def test_run_1_plan_two_writes_red_then_green_checks_a_review_and_an_ask(self):
        r = self.run_of("072411")
        self.assertFalse(r["structured"])
        self.assertEqual(r["started_because"], "first")
        self.assertEqual(r["prev_run"], "")
        self.assertEqual(kinds(r), ["plan", "write", "checks", "write", "checks", "review"])
        self.assertEqual(causes(r), [None, "planned", None, "checks_red", None, "checks_green"])
        self.assertEqual(r["blocks"][3]["arrow"]["text"], "checks red: 1 failed → write again")
        self.assertEqual([b["label"] for b in r["blocks"]], ["Plan", "Write 1", "Checks", "Write 2", "Checks", "Review"])
        self.assertEqual(r["blocks"][1]["stage"], "1/2")
        self.assertEqual(r["blocks"][2]["result"]["status"], "fail")
        self.assertEqual(r["blocks"][4]["result"]["status"], "ok")
        p, w = r["blocks"][0]["who"], r["blocks"][1]["who"]
        self.assertEqual((p["family"], p["name"], p["model"], p["effort"]), ("claude", "Claude", "opus-5.5", "medium"))
        self.assertEqual((w["family"], w["name"], w["resumed"]), ("openai", "Codex", False))
        self.assertEqual(r["blocks"][1]["tokens"]["out"], 14826)
        self.assertEqual(r["blocks"][1]["secs"], 484)
        self.assertEqual(r["blocks"][5]["result"]["text"], "3 findings, 1 unmet")
        self.assertEqual((r["end"]["outcome"], r["end"]["cause"]), ("asks", "decision"))
        self.assertEqual(r["end"]["text"], "decision needed → asks you")

    def test_run_2_starts_from_the_owners_answer_and_pauses_when_codex_is_out(self):
        r = self.run_of("074926")
        self.assertEqual((r["started_because"], r["ask"], r["prev_run"]),
                         ("answer", "lifesim-d5f.58-1", "lifesim-d5f.58-20261021-072411"))
        self.assertEqual(kinds(r), ["plan", "write", "checks", "replan", "write"])
        self.assertEqual(r["blocks"][3]["arrow"]["cause"], "bad_checks")
        self.assertEqual(r["blocks"][3]["arrow"]["text"], "writer: the checks are wrong → re-plan")
        self.assertEqual(r["blocks"][4]["result"]["status"], "wait")
        self.assertEqual(r["blocks"][4]["result"]["text"], "Codex out")
        self.assertEqual((r["end"]["outcome"], r["end"]["until"]), ("paused", "09:02"))
        self.assertEqual(r["end"]["text"], "Codex out → paused until 09:02")

    def test_a_pause_says_what_it_waits_for(self):
        self.assertEqual(timeline.pause_reason("paused: logged_out on plan; run `claude auth login` on this machine"),
                         "Claude logged out")
        self.assertEqual(timeline.pause_reason("paused: no network for write until 09:00 (network: dns)"), "no network")
        self.assertEqual(timeline.pause_reason("paused: no lane for write until 09:02 (lane_out: OPENAI_SUBSCRIPTION)"),
                         "Codex out")

    def test_run_3_resumes_after_the_pause_and_a_write_with_no_session_still_shows(self):
        r = self.run_of("090321")
        self.assertEqual((r["started_because"], r["prev_run"]), ("resume", "lifesim-d5f.58-20261021-074926"))
        self.assertEqual(kinds(r), ["plan", "write"])
        self.assertIsNone(r["blocks"][1]["session"]["ref"])
        self.assertEqual(r["end"]["until"], "09:36")

    def test_run_4_without_a_close_record_ends_stopped(self):
        r = self.run_of("093704")
        self.assertEqual(kinds(r), ["plan", "write", "checks", "review", "write"])
        self.assertEqual(r["blocks"][4]["arrow"]["cause"], "accepted")
        self.assertEqual(r["blocks"][4]["stage"], "2/2")
        self.assertEqual(r["end"]["outcome"], "stopped")
        self.assertEqual(self.run_of("093704", alive=True)["end"]["outcome"], "running")

    def test_run_5_a_changed_branch_is_a_retry(self):
        r = self.run_of("103215")
        self.assertEqual((r["started_because"], r["prev_run"]), ("retry", "lifesim-d5f.58-20261021-093704"))
        self.assertEqual(kinds(r), ["plan", "write", "checks", "replan"])
        self.assertIn("4 failed", r["blocks"][2]["result"]["text"])
        self.assertEqual(r["end"]["cause"], "decision")

    def test_run_6_lands(self):
        r = self.run_of("105946")
        self.assertEqual((r["started_because"], r["ask"]), ("answer", "lifesim-d5f.58-2"))
        self.assertEqual(kinds(r), ["plan", "write", "checks", "review", "land"])
        self.assertEqual(r["blocks"][4]["arrow"]["cause"], "accepted")
        self.assertEqual(r["end"]["outcome"], "landed")
        self.assertEqual(r["end"]["text"], "landed " + timeline.when(r["end"]["t"]))
        self.assertTrue(timeline.when(r["end"]["t"]).endswith("11:20"))

    def test_block_detail_has_the_checks_of_its_round_and_the_engine_lines_of_its_step(self):
        r = self.run_of("072411")
        checks = r["blocks"][2]
        d = timeline.block_detail(log("072411"), checks["node"])
        self.assertEqual(len(d["checks"]), 8)
        red = [c for c in d["checks"] if c["exit"]]
        self.assertEqual([c["exit"] for c in red], [2])
        self.assertTrue(red[0]["tail"])
        self.assertTrue(all(ln["kind"] in ("cmd", "note", "warn") for ln in d["lines"]))
        self.assertTrue(any(ln["kind"] == "cmd" for ln in d["lines"]))
        w = timeline.block_detail(log("072411"), r["blocks"][1]["node"])  # a write shows the checks that judged it
        self.assertEqual([c["exit"] for c in w["checks"] if c["exit"]], [2])
        self.assertEqual(w["session"]["ref"], "01a15cb6-4820-73e0-be53-4cef9422cb4b")


class Api(unittest.TestCase):
    """The endpoints over a state dir holding the fixture."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self.cfg = home / "task-loop"
        shutil.copytree(str(FIXTURE), str(self.cfg))
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(home), "APPDATA": str(home)})
        self.env.start()
        server._cache.clear()
        timeline._parsed.clear()
        self.codex = home / "codex"
        p = mock.patch.object(server, "CODEX_SESSIONS", self.codex)
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(server, "PROJECTS", home / "projects")
        q.start()
        self.addCleanup(q.stop)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def task(self, bead=BEAD):
        return next(t for t in server.api_tasks()["tasks"] if t["id"] == bead)

    def test_the_task_list_has_one_row_per_bead_with_its_state(self):
        t = self.task()
        self.assertEqual((t["state"], t["runs"]), ("landed", 6))
        self.assertTrue(t["label"].startswith("landed "))
        self.assertEqual(t["slot"], "s2")  # the worktree of its last run, from the trace

    def test_an_open_ask_is_waiting_on_you(self):
        (self.cfg / "asks").mkdir()
        (self.cfg / "asks" / (BEAD + ".json")).write_text(json.dumps({
            "v": 1, "id": BEAD + "-3", "bead": BEAD, "kind": "decision", "question": "A or B?", "status": "open",
            "t": time.time(), "title": "Front approach"}))
        t = self.task()
        self.assertEqual((t["state"], t["label"]), ("asks", "waiting on you"))
        self.assertEqual(t["ask"]["id"], BEAD + "-3")
        self.assertEqual(t["title"], "Front approach")

    def test_an_ask_already_answered_waits_for_the_next_run_not_for_you(self):
        (self.cfg / "asks").mkdir()
        (self.cfg / "asks" / (BEAD + ".json")).write_text(json.dumps({"v": 1, "id": BEAD + "-2", "bead": BEAD,
                                                                   "status": "answered"}))
        for s in RUNS[5:]:
            os.unlink(str(self.cfg / "engine" / ("%s-20261021-%s.jsonl" % (BEAD, s))))
        t = self.task()
        self.assertEqual((t["state"], t["label"]), ("queued", "answered: waits for the next run"))

    def test_a_paused_run_says_which_lane_is_out_and_until_when(self):
        for s in RUNS[2:]:
            os.unlink(str(self.cfg / "engine" / ("%s-20261021-%s.jsonl" % (BEAD, s))))
        t = self.task()
        self.assertEqual((t["state"], t["label"]), ("paused", "paused: Codex out until 09:02"))

    def test_a_running_run_shows_its_stage_from_its_engine_lock(self):
        wt = Path(self.tmp.name) / "slots" / "s1"
        (wt / ".task").mkdir(parents=True)
        (wt / ".task" / "engine.lock").write_text(json.dumps({"pid": os.getpid(), "bead": "x-1", "slot": "s1"}))
        recs = [{"t": time.time() - 600, "kind": "run", "text": "run: first", "run": "x-1-20261021-120000", "bead": "x-1",
                 "worktree": str(wt), "slot": "s1", "started_because": "first", "prev_run": "", "ask": ""},
                {"t": time.time() - 590, "kind": "node", "text": "write: stage 2/3 write 1", "id": 3, "step": "write",
                 "stage": 2, "stages": 3, "write": 1, "round": 1}]
        (self.cfg / "engine" / "x-1-20261021-120000.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        t = self.task("x-1")
        self.assertEqual((t["state"], t["label"], t["slot"]), ("running", "writing stage 2/3", "s1"))
        self.assertGreaterEqual(t["since"], 590)
        (wt / ".task" / "engine.lock").unlink()
        server._cache.clear()
        timeline._parsed.clear()
        self.assertEqual(self.task("x-1")["state"], "stopped")

    def test_the_task_timeline_is_every_run_of_the_bead_oldest_first(self):
        d = server.api_task_timeline("", BEAD)
        self.assertEqual([r["run"][-6:] for r in d["runs"]], RUNS)
        self.assertEqual([r["started_because"] for r in d["runs"]],
                         ["first", "answer", "resume", "resume", "retry", "answer"])
        self.assertEqual(d["runs"][-1]["end"]["outcome"], "landed")
        self.assertEqual(d["task"]["id"], BEAD)

    def test_a_block_names_its_transcript_and_a_codex_thread_is_cut_to_the_blocks_time(self):
        ref = "01a15cb6-4820-73e0-be53-4cef9422cb4b"
        day = self.codex / "2026" / "10" / "21"
        day.mkdir(parents=True)
        (day / ("rollout-2026-10-21T07-26-%s.jsonl" % ref)).write_text("")
        run = "%s-20261021-072411" % BEAD
        blocks = timeline.run_timeline(log("072411"))["blocks"]
        d = server.api_block(run, blocks[3]["node"], 0)
        self.assertTrue(d["events_id"].startswith("codex-exec:" + str(day)))
        a, b = d["events_id"].rsplit("@", 2)[1:]
        self.assertLessEqual(float(a), blocks[3]["t0"])
        self.assertGreaterEqual(float(b), blocks[3]["t1"])
        self.assertEqual(server.api_block("../../etc/passwd", 1, 0), {"error": "no such run"})

    def test_a_windowed_rollout_keeps_only_the_blocks_events(self):
        p = Path(self.tmp.name) / "rollout.jsonl"

        def msg(ts, text):
            return json.dumps({"timestamp": ts, "type": "response_item",
                               "payload": {"type": "message", "role": "assistant", "content": [{"text": text}]}}) + "\n"
        p.write_text(msg("2026-10-21T07:00:00Z", "round 1") + msg("2026-10-21T08:00:00Z", "round 2"))
        t = server.parse_ts("2026-10-21T07:30:00Z")
        evs = server.run_events("codex-exec:%s@%s@%s" % (p, t, t + 3600))
        self.assertEqual([e["text"] for e in evs], ["round 2"])
        self.assertEqual(len(server.run_events("codex-exec:%s" % p)), 2)

    def test_a_codex_exec_call_shows_its_shell_commands(self):
        src = 'text(await tools.exec_command({cmd:"cat a.md; rg -n \\"x\\" src",max_output_tokens:6000}));\n' \
              'text(await tools.exec_command({cmd:"git status"}));'
        self.assertEqual(server.exec_cmds(src), ['cat a.md; rg -n "x" src', "git status"])
        self.assertEqual(server.exec_cmds("ls"), [])

    def test_a_check_log_is_served_from_its_run_and_nothing_outside_it(self):
        run = "%s-20261021-072411" % BEAD
        (self.cfg / "runs" / run / "checks").mkdir(parents=True)
        (self.cfg / "runs" / run / "checks" / "00-fmt.log").write_text("all formatted\n")
        self.assertEqual(server.run_file(run, "checks/00-fmt.log"), b"all formatted\n")
        self.assertIsNone(server.run_file(run, "../../traces.jsonl"))
        self.assertIsNone(server.run_file("../x", "checks/00-fmt.log"))


class LiveTaskView(unittest.TestCase):
    """The real server process over the fixture: the task view's endpoints and both pages answer."""

    def test_endpoints(self):
        import subprocess
        import urllib.request
        from test_dash import free_port
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(str(FIXTURE), os.path.join(d, "task-loop"))
            port = free_port()
            env = dict(os.environ, XDG_CONFIG_HOME=d, APPDATA=d, TASK_LOOP_DASH_BIND="127.0.0.1", HOME=d, USERPROFILE=d)
            p = subprocess.Popen([sys.executable, str(ROOT / "skills" / "task-loop" / "dash" / "server.py"),
                                  "--port", str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                base = "http://127.0.0.1:%d" % port
                for _ in range(50):
                    try:
                        urllib.request.urlopen(base + "/api/version", timeout=1)
                        break
                    except OSError:
                        time.sleep(0.1)

                def get(u):
                    return json.loads(urllib.request.urlopen(base + u).read())
                self.assertEqual([t["id"] for t in get("/api/tasks")["tasks"]], [BEAD])
                tl_ = get("/api/task-timeline?id=" + BEAD)
                self.assertEqual(len(tl_["runs"]), 6)
                run = tl_["runs"][0]
                blk = get("/api/block?run=%s&node=%s&k=0" % (run["run"], run["blocks"][2]["node"]))
                self.assertEqual(len(blk["checks"]), 8)
                page = urllib.request.urlopen(base + "/").read()
                self.assertIn(b"task-loop", page)
                self.assertIn(b"Asks", page)
                self.assertIn(b"task-loop", urllib.request.urlopen(base + "/classic").read())
            finally:
                p.terminate()
                p.wait(5)


if __name__ == "__main__":
    unittest.main()
