"""The task-first dashboard: /api/tasks, /api/task-timeline, /api/block, built from the engine's records. Old runs
are read from their node, session and end records: the fixture is six real runs of
lifesim-d5f.58 (2026-10-21), trimmed."""

import contextlib
import subprocess
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
sys.path.insert(0, str(ROOT / "tests"))
from support.narrow import must  # noqa: E402
from support.askjson import ask_json  # noqa: E402
from support.dashes import make_dash  # noqa: E402
from taskloop_dash import tails as tails_mod  # noqa: E402
from taskloop_dash.readers import events as events_mod  # noqa: E402
from support.logs import typed, write_log  # noqa: E402
from taskloop_dash.cache import FileCache  # noqa: E402
from taskloop_dash.views import arrows, names, timeline  # noqa: E402

DASH = make_dash()

FIXTURE = ROOT / "tests" / "fixtures" / "state"
BEAD = "lifesim-d5f.58"
RUNS = ["072411", "074926", "090321", "093704", "103215", "105946"]


def log(stamp):
    return str(FIXTURE / "engine" / ("%s-20261021-%s.jsonl" % (BEAD, stamp)))


def kinds(run):
    return [b["kind"] for b in run["blocks"]]


def causes(run):
    return [(b["arrow"] or {}).get("cause") for b in run["blocks"]]


class Runs(unittest.TestCase):
    """Six real runs of one bead (lifesim-d5f.58, 2026-10-21), as structured records."""

    def run_of(self, stamp, **kw):
        return timeline.run_timeline(log(stamp), **kw)

    def test_run_1_plan_two_writes_red_then_green_checks_a_review_and_an_ask(self):
        r = self.run_of("072411")
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
        self.assertEqual(arrows.pause_reason("paused: logged_out on plan; run `claude auth login` on this machine"),
                         "Claude logged out")
        self.assertEqual(arrows.pause_reason("paused: no network for write until 09:00 (network: dns)"), "no network")
        self.assertEqual(arrows.pause_reason("paused: no lane for write until 09:02 (lane_out: OPENAI_SUBSCRIPTION)"),
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
        self.assertEqual(r["end"]["text"], "landed " + names.when(r["end"]["t"]))
        # the fixture's end is 08:20 UTC (11:20 where it was recorded); the label is local time, so it follows the machine's zone
        self.assertEqual(time.strftime("%H:%M", time.gmtime(r["end"]["t"])), "08:20")
        self.assertTrue(names.when(r["end"]["t"]).endswith(time.strftime("%H:%M", time.localtime(r["end"]["t"]))))

    def test_block_detail_has_the_checks_of_its_round_and_the_engine_lines_of_its_step(self):
        r = self.run_of("072411")
        checks = r["blocks"][2]
        d = DASH.runlogs.block_detail(log("072411"), checks["node"])
        self.assertEqual(len(d["checks"]), 8)
        red = [c for c in d["checks"] if c["exit"]]
        self.assertEqual([c["exit"] for c in red], [2])
        self.assertTrue(red[0]["tail"])
        self.assertTrue(all(ln["kind"] in ("cmd", "note", "warn") for ln in d["lines"]))
        self.assertTrue(any(ln["kind"] == "cmd" for ln in d["lines"]))
        w = DASH.runlogs.block_detail(log("072411"), r["blocks"][1]["node"])  # a write shows the checks that judged it
        self.assertEqual([c["exit"] for c in w["checks"] if c["exit"]], [2])
        self.assertEqual(w["session"]["ref"], "01a15cb6-4820-73e0-be53-4cef9422cb4b")


class Api(unittest.TestCase):
    """The endpoints over a state dir holding the fixture."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        home = Path(self.tmp.name)
        self.cfg = home / "task-loop"
        shutil.copytree(str(FIXTURE), str(self.cfg))
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(home), "APPDATA": str(home)})
        self.env.start()
        self.codex = home / "codex"
        self.dash = make_dash()
        self.dash.env.codex_sessions = self.codex
        self.dash.env.projects = home / "projects"

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def task(self, bead=BEAD):
        return next(t for t in self.dash.tasks.api_tasks()["tasks"] if t["id"] == bead)

    def test_the_task_list_has_one_row_per_bead_with_its_state(self):
        t = self.task()
        self.assertEqual((t["state"], t["runs"]), ("landed", 6))
        self.assertTrue(t["label"].startswith("landed "))
        self.assertEqual(t["slot"], "s2")  # the worktree of its last run, from the trace

    def test_an_open_ask_is_waiting_on_you(self):
        (self.cfg / "asks").mkdir()
        (self.cfg / "asks" / (BEAD + ".json")).write_text(json.dumps(ask_json(BEAD, 3, status="open", t=time.time(), title="Front approach")))
        t = self.task()
        self.assertEqual((t["state"], t["label"]), ("asks", "waiting for your answer"))
        self.assertEqual(t["ask"]["id"], BEAD + "-3")
        self.assertEqual(t["title"], "Front approach")

    def test_an_ask_already_answered_waits_for_the_next_run_not_for_you(self):
        (self.cfg / "asks").mkdir()
        (self.cfg / "asks" / (BEAD + ".json")).write_text(json.dumps(ask_json(BEAD, 2, status="answered")))
        for s in RUNS[5:]:
            os.unlink(str(self.cfg / "engine" / ("%s-20261021-%s.jsonl" % (BEAD, s))))
        t = self.task()
        self.assertEqual((t["state"], t["label"]), ("queued", "answered: waits for the next run"))

    def ended_on_an_ask(self, ask_status, blocker_status="open"):
        """The bead's last run ended asking (run 5); its ask file says ask_status; bd says it is blocked by a design
        bead in blocker_status (lifesim-s28t, 2026-10-21)."""
        for s in RUNS[5:]:
            os.unlink(str(self.cfg / "engine" / ("%s-20261021-%s.jsonl" % (BEAD, s))))
        (self.cfg / "asks").mkdir()
        (self.cfg / "asks" / (BEAD + ".json")).write_text(json.dumps(ask_json(
            BEAD, 1, status=ask_status, t=time.time(), repo="/r/lifesim", title="Front approach")))
        beads = [{"id": BEAD, "title": "Front approach", "status": "blocked", "dependencies": [
                     {"id": "lifesim-5ban.33", "type": "parent-child"},
                     {"id": "lifesim-5ban.23", "type": "blocks"}]},
                 {"id": "lifesim-5ban.33", "title": "Epic", "status": "open"},
                 {"id": "lifesim-5ban.23", "title": "People design", "status": blocker_status}]
        for owner, name, val in ((self.dash.records, "repos", lambda: ["/r/lifesim"]),
                                 (self.dash.beads, "beads_of", lambda repo: beads if repo == "/r/lifesim" else [])):
            p = mock.patch.object(owner, name, side_effect=val)
            p.start()
            self.addCleanup(p.stop)
        return self.task()

    def test_an_open_ask_wins_over_a_blocker(self):
        t = self.ended_on_an_ask("open")
        self.assertEqual((t["state"], t["label"]), ("asks", "waiting for your answer"))

    def test_a_closed_ask_and_an_open_blocker_say_blocked_by_it(self):
        t = self.ended_on_an_ask("closed")
        self.assertEqual((t["state"], t["label"]), ("blocked_by", "blocked by lifesim-5ban.23 (People design)"))
        self.assertIsNone(t["ask"])
        self.assertEqual(t["blocked_by"], {"id": "lifesim-5ban.23", "title": "People design"})

    def test_a_parent_is_no_blocker_and_a_closed_blocker_is_none(self):
        t = self.ended_on_an_ask("closed", blocker_status="closed")
        self.assertNotIn("waiting", t["label"])
        self.assertNotIn("answer", t["label"])
        self.assertEqual(t["label"], "ask closed: owner decision needed")
        self.assertIsNone(t["blocked_by"])

    def test_no_ask_is_ever_waited_for_when_none_is_open(self):
        for s in RUNS[5:]:
            os.unlink(str(self.cfg / "engine" / ("%s-20261021-%s.jsonl" % (BEAD, s))))
        t = self.task()  # no ask file at all
        self.assertNotIn("waiting", t["label"])
        self.assertNotIn("answer", t["label"])
        self.assertNotEqual(t["state"], "asks")

    def test_one_bd_call_per_repo_however_many_tasks_and_polls(self):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            return mock.Mock(returncode=0, stdout=json.dumps([{"id": BEAD, "status": "open", "dependencies": []}]))
        with mock.patch.object(self.dash.records, "repos", return_value=["/r/lifesim"]), \
                mock.patch.object(shutil, "which", return_value="/bin/bd"), \
                mock.patch.object(subprocess, "run", side_effect=run):
            for _ in range(3):
                self.dash.tasks.api_tasks()
                self.dash.tasks.api_task_timeline("", BEAD)
        self.assertEqual(len([c for c in calls if c[0] == "/bin/bd" and "list" in c]), 1)

    def test_a_paused_run_says_which_lane_is_out_and_until_when(self):
        for s in RUNS[2:]:
            os.unlink(str(self.cfg / "engine" / ("%s-20261021-%s.jsonl" % (BEAD, s))))
        t = self.task()
        self.assertEqual((t["state"], t["label"]), ("paused", "paused: Codex out until 09:02"))

    def test_a_running_run_waiting_for_a_lane_says_which_and_until_when(self):
        now = time.mktime((2026, 10, 21, 12, 0, 0, 0, 0, -1))  # local noon: due (+5 min) never crosses midnight, whatever the real time is
        with self.frozen(now):
            self.waiting_for_a_lane(now)

    def frozen(self, now):
        class Frozen:
            def time(self):
                return now

            def localtime(self, t=None):
                return time.localtime(now if t is None else t)

            def strftime(self, fmt, tup=None):
                return time.strftime(fmt, self.localtime() if tup is None else tup)

            def __getattr__(self, name):
                return getattr(time, name)
        stack = contextlib.ExitStack()
        for mod in (timeline, names):
            stack.enter_context(mock.patch.object(mod, "time", Frozen()))
        stack.enter_context(mock.patch.object(self.dash.env, "clock", lambda: now))
        return stack

    def waiting_for_a_lane(self, now):
        wt = Path(self.tmp.name) / "slots" / "s1"
        (wt / ".task").mkdir(parents=True)
        (wt / ".task" / "engine.lock").write_text(json.dumps({"pid": os.getpid(), "bead": "x-1", "slot": "s1"}))
        due = now + 300
        recs = [{"v": 2, "t": now - 600, "kind": "run_start", "run": "x-1-20261021-120000", "bead": "x-1", "worktree": str(wt),
                 "slot": "s1", "started_because": "first", "prev_run": "", "ask": ""},
                {"v": 2, "t": now - 590, "kind": "step_start", "id": "n3", "step": "write", "text": "write: stage 1/1 write 1",
                 "stage": 1, "stages": 1, "write": 1, "round": 1},
                {"v": 2, "t": now - 10, "kind": "wait_start", "id": "w1", "what": "lane", "holder": "OPENAI_SUBSCRIPTION", "until": due}]
        path = self.cfg / "engine" / "x-1-20261021-120000.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in recs))
        t = self.task("x-1")
        self.assertEqual((t["state"], t["label"]), ("running", "waiting for Codex until " + names.hhmm(due)))
        recs.append({"v": 2, "t": now - 5, "kind": "wait_end", "id": "w1", "secs": 5})  # the wait is over: back to what the run is doing
        path.write_text("".join(json.dumps(r) + "\n" for r in recs))
        self.dash.env.ttl.clear()
        self.dash.env.files.items.clear()
        self.assertEqual(self.task("x-1")["label"], "writing")

    def test_a_running_run_shows_its_stage_from_its_engine_lock(self):
        wt = Path(self.tmp.name) / "slots" / "s1"
        (wt / ".task").mkdir(parents=True)
        (wt / ".task" / "engine.lock").write_text(json.dumps({"pid": os.getpid(), "bead": "x-1", "slot": "s1"}))
        recs = [{"v": 2, "t": time.time() - 600, "kind": "run_start", "run": "x-1-20261021-120000", "bead": "x-1",
                 "worktree": str(wt), "slot": "s1", "started_because": "first", "prev_run": "", "ask": ""},
                {"v": 2, "t": time.time() - 590, "kind": "step_start", "text": "write: stage 2/3 write 1", "id": "n3", "step": "write",
                 "stage": 2, "stages": 3, "write": 1, "round": 1}]
        (self.cfg / "engine" / "x-1-20261021-120000.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        t = self.task("x-1")
        self.assertEqual((t["state"], t["label"], t["slot"]), ("running", "writing stage 2/3", "s1"))
        self.assertGreaterEqual(t["since"], 590)
        (wt / ".task" / "engine.lock").unlink()
        self.dash.env.ttl.clear()
        self.dash.env.files.items.clear()
        self.assertEqual(self.task("x-1")["state"], "stopped")

    def test_the_task_timeline_is_every_run_of_the_bead_oldest_first(self):
        d = self.dash.tasks.api_task_timeline("", BEAD)
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
        d = self.dash.runs.api_block(run, blocks[3]["node"], 0)
        self.assertTrue(d["events_id"].startswith("codex-exec:" + str(day)))
        a, b = d["events_id"].rsplit("@", 2)[1:]
        self.assertLessEqual(float(a), blocks[3]["t0"])
        self.assertGreaterEqual(float(b), blocks[3]["t1"])
        self.assertEqual(self.dash.runs.api_block("../../etc/passwd", "1", 0), {"error": "no such run"})

    def test_a_windowed_rollout_keeps_only_the_blocks_events(self):
        p = Path(self.tmp.name) / "rollout.jsonl"

        def msg(ts, text):
            return json.dumps({"timestamp": ts, "type": "response_item",
                               "payload": {"type": "message", "role": "assistant", "content": [{"text": text}]}}) + "\n"
        p.write_text(msg("2026-10-21T07:00:00Z", "round 1") + msg("2026-10-21T08:00:00Z", "round 2"))
        t = tails_mod.parse_ts("2026-10-21T07:30:00Z")
        evs = self.dash.runs.run_events("codex-exec:%s@%s@%s" % (p, t, must(t) + 3600))
        self.assertEqual([e["text"] for e in evs], ["round 2"])
        self.assertEqual(len(self.dash.runs.run_events("codex-exec:%s" % p)), 2)

    def test_a_codex_exec_call_shows_its_shell_commands(self):
        src = 'text(await tools.exec_command({cmd:"cat a.md; rg -n \\"x\\" src",max_output_tokens:6000}));\n' \
              'text(await tools.exec_command({cmd:"git status"}));'
        self.assertEqual(events_mod.exec_cmds(src), ['cat a.md; rg -n "x" src', "git status"])
        self.assertEqual(events_mod.exec_cmds("ls"), [])

    def test_a_check_log_is_served_from_its_run_and_nothing_outside_it(self):
        run = "%s-20261021-072411" % BEAD
        (self.cfg / "runs" / run / "checks").mkdir(parents=True)
        (self.cfg / "runs" / run / "checks" / "00-fmt.log").write_bytes(b"all formatted\n")
        self.assertEqual(self.dash.runs.run_file(run, "checks/00-fmt.log"), b"all formatted\n")
        self.assertIsNone(self.dash.runs.run_file(run, "../../traces.jsonl"))
        self.assertIsNone(self.dash.runs.run_file("../x", "checks/00-fmt.log"))
        (self.cfg / "runs" / run / "plan.json").write_text("{}")
        self.assertEqual(self.dash.runs.run_file(run, "plan.json"), b"{}")
        (self.cfg / "runs" / run / "brief.md").write_text("the bead")
        (self.cfg / "runs" / run / "evidence").mkdir()
        (self.cfg / "runs" / run / "evidence" / "a.log").write_text("x")
        self.assertIsNone(self.dash.runs.run_file(run, "brief.md"))  # only check logs and the plan are served
        self.assertIsNone(self.dash.runs.run_file(run, "evidence/a.log"))
        self.assertIsNone(self.dash.runs.run_file(run, "checks/../brief.md"))

    def test_a_symlink_in_checks_that_leaves_the_run_folder_is_refused(self):
        run = "%s-20261021-072411" % BEAD
        (self.cfg / "runs" / run / "checks").mkdir(parents=True)
        secret = Path(self.tmp.name) / "secret.txt"
        secret.write_text("token")
        os.symlink(str(secret), str(self.cfg / "runs" / run / "checks" / "00-x.log"))
        self.assertIsNone(self.dash.runs.run_file(run, "checks/00-x.log"))

    def test_the_log_cache_forgets_gone_files_and_stays_small(self):
        cache = FileCache(limit=30)
        p = Path(self.tmp.name) / "x-1-20261021-120000.jsonl"
        p.write_text('{"v": 2, "kind": "note", "t": 1, "text": "a"}\n')
        self.assertEqual(len(timeline.read(str(p), cache)), 1)
        self.assertIn(str(p), cache.items)
        p.unlink()
        self.assertEqual(timeline.read(str(p), cache), [])
        self.assertNotIn(str(p), cache.items)
        for i in range(50):
            q = Path(self.tmp.name) / ("y-%d.jsonl" % i)
            q.write_text("{}\n")
            timeline.read(str(q), cache)
        self.assertLessEqual(len(cache.items), 30)


STAGED = "lifesim-d5f.56"
STAGED_RUN = STAGED + "-20261021-224641"


def staged_log(root=FIXTURE):
    return str(Path(root) / "engine" / (STAGED_RUN + ".jsonl"))


class Stages(unittest.TestCase):
    """lifesim-d5f.56 (2026-10-21): plan -> stage 1 write, checks, review (clean, same family) -> stage 2 write 1. Each
    block names its stage, with the title from the run's plan.json, and a review by the writer's family says so."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name) / "task-loop"
        shutil.copytree(str(FIXTURE), str(self.root))
        DASH.env.files.items.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_stage_block_has_its_index_count_and_plan_title(self):
        r = timeline.run_timeline(staged_log())
        self.assertEqual(kinds(r), ["plan", "write", "checks", "review", "write"])
        self.assertEqual([(b["stage_index"], b["stage_count"]) for b in r["blocks"]],
                         [(None, None), (1, 2), (1, 2), (1, 2), (2, 2)])
        self.assertEqual(r["blocks"][1]["stage_title"], "Add the knob")
        self.assertEqual(r["blocks"][3]["stage_title"], "Add the knob")
        self.assertEqual(r["blocks"][4]["stage_title"], "Add the layout test, building the HUD the way the screen does")
        self.assertIsNone(r["blocks"][0]["stage_title"])
        self.assertEqual([b["label"] for b in r["blocks"]], ["Plan", "Write 1", "Checks", "Review", "Write 1"])
        self.assertEqual(r["blocks"][4]["stage"], "2/2")

    def test_a_review_by_the_writers_family_is_marked(self):
        b = timeline.run_timeline(staged_log())["blocks"]
        self.assertTrue(b[3]["same_family"])
        self.assertEqual(b[3]["result"]["text"], "clean")
        self.assertFalse(b[1]["same_family"])
        self.assertFalse(b[2]["same_family"])

    def test_a_review_by_another_family_is_not_marked(self):
        r = timeline.run_timeline(log("072411"))
        rev = r["blocks"][5]
        self.assertEqual((rev["kind"], rev["who"]["family"]), ("review", "claude"))
        self.assertFalse(rev["same_family"])  # the writer was Codex

    def test_without_plan_json_the_stage_title_is_empty(self):
        shutil.rmtree(str(self.root / "runs" / STAGED_RUN))
        b = timeline.run_timeline(staged_log(self.root))["blocks"]
        self.assertEqual((b[4]["stage_index"], b[4]["stage_count"], b[4]["stage_title"]), (2, 2, ""))

    def test_stage_title_is_the_goals_first_sentence_cut_short(self):
        t = arrows.stage_title
        self.assertEqual(t("Add the knob: in content/ui/default.yaml under `live:`"), "Add the knob")
        self.assertEqual(t("Add the layout test.\n\n(1) Pull"), "Add the layout test")
        long = t("word " * 40)
        self.assertLessEqual(len(long), 81)
        self.assertTrue(long.endswith("\u2026"))
        self.assertEqual(t(""), "")
        self.assertEqual(t(None), "")

    def test_the_task_timeline_endpoint_carries_the_stage_fields(self):
        home = Path(self.tmp.name)
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(home), "APPDATA": str(home)}):
            d = make_dash().tasks.api_task_timeline("", STAGED)
        b = d["runs"][0]["blocks"]
        self.assertEqual((b[4]["stage_index"], b[4]["stage_count"]), (2, 2))
        self.assertTrue(b[4]["stage_title"].startswith("Add the layout test"))
        self.assertTrue(b[3]["same_family"])


class LiveTaskView(unittest.TestCase):
    """The real server process over the fixture: the task view's endpoints and both pages answer."""

    def test_endpoints(self):
        import subprocess
        import urllib.request
        from test_dash import free_port
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            shutil.copytree(str(FIXTURE), os.path.join(d, "task-loop"))
            port = free_port()
            env = dict(os.environ, XDG_CONFIG_HOME=d, APPDATA=d, TASK_LOOP_DASH_BIND="127.0.0.1", HOME=d, USERPROFILE=d)
            p = subprocess.Popen([sys.executable, "-m", "taskloop_dash",
                                  "--port", str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                base = "http://127.0.0.1:%d" % port
                end = time.monotonic() + 90  # generous: a loaded machine starts a server slowly; a poll, never a fixed wait
                while True:
                    try:
                        urllib.request.urlopen(base + "/api/version", timeout=5)
                        break
                    except OSError:
                        self.assertLess(time.monotonic(), end, "the server never answered")
                        time.sleep(0.1)

                def get(u):
                    return json.loads(urllib.request.urlopen(base + u, timeout=60).read())

                def raw(u):
                    return urllib.request.urlopen(base + u, timeout=60)
                self.assertEqual(sorted(t["id"] for t in get("/api/tasks")["tasks"]), sorted([BEAD, STAGED]))
                tl_ = get("/api/task-timeline?id=" + BEAD)
                self.assertEqual(len(tl_["runs"]), 6)
                run = tl_["runs"][0]
                blk = get("/api/block?run=%s&node=%s&k=0" % (run["run"], run["blocks"][2]["node"]))
                self.assertEqual(len(blk["checks"]), 8)
                page = raw("/").read()
                self.assertIn(b"task-loop", page)
                self.assertIn(b"Asks", page)
                self.assertIn(b"same family as writer", page)
                r = raw("/api/tasks")
                self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
            finally:
                p.terminate()
                try:
                    p.wait(60)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()


class WorkerCalls(unittest.TestCase):
    """block_detail shows every worker call of the step from the typed CallStart/CallEnd pair (lane, model, time, tokens, ref)."""

    def test_a_block_lists_its_calls_with_lane_model_secs_tokens_and_ref(self):
        T = 1_800_000_000.0
        recs = [typed("run_start", T, run="c-1-20261024-010101", bead="c-1", worktree=""),
                typed("step_start", T + 1, id="n1", step="write", text="write", stage=1, stages=1, write=1),
                typed("call_start", T + 2, id="c1", n=1, step="write", node="n1", role="worker"),
                typed("call_end", T + 9, id="c1", status="stopped", reason="lane_out", ref="ses_1", lane="ZAI", model="glm", effort="high", secs=7,
                      tokens={"in": 5, "cached": 1, "out": 2}, family="xai", transcript="opencode:ses_1", exit=-15),
                typed("call_start", T + 10, id="c2", n=2, step="write", node="n1", role="worker", resume=True),
                typed("call_end", T + 20, id="c2", status="done", ref="ses_2", lane="OPENAI_SUBSCRIPTION", model="gpt", effort="high", secs=10,
                      tokens={"in": 9, "cached": 0, "out": 4}, family="openai"),
                typed("step_end", T + 21, id="n1", step="write", outcome="done", secs=20)]
        with tempfile.TemporaryDirectory() as d:
            p = write_log(Path(d, "c-1-20261024-010101.jsonl"), recs)
            first, second = DASH.runlogs.block_detail(p, 1, 0), DASH.runlogs.block_detail(p, 1, 1)
        self.assertEqual([(c["k"], c["lane"], c["model"], c["secs"], c["ref"], c["status"]) for c in first["calls"]],
                         [(0, "ZAI", "glm", 7, "ses_1", "stopped"), (1, "OPENAI_SUBSCRIPTION", "gpt", 10, "ses_2", "done")])
        self.assertEqual(first["calls"][0]["tokens"], {"in": 5, "cached": 1, "out": 2})
        self.assertEqual(first["calls"][0]["transcript"], "opencode:ses_1")
        self.assertTrue(first["calls"][1]["resume"])
        self.assertEqual([c["exit"] for c in first["calls"]], [-15, None])  # the worker call that ended by SIGTERM shows its exit
        self.assertEqual((first["session"]["lane"], second["session"]["lane"]), ("ZAI", "OPENAI_SUBSCRIPTION"))


if __name__ == "__main__":
    unittest.main()
