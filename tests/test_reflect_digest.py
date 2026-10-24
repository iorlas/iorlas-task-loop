"""tl-bl5: recurring causes in the runs' reflections become one bead each, deduped, with the run ids as evidence."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "task-loop"))
import reflect_digest as rd  # noqa: E402
import tl  # noqa: E402

NOW = 1_800_000_000.0


class Res:
    def __init__(self, out="", rc=0):
        self.stdout, self.returncode, self.stderr = out, rc, ""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root / "cfg"), "APPDATA": str(self.root / "cfg"),
                                                "HOME": str(self.root)})
        self.env.start()
        tl.config_dir().mkdir(parents=True, exist_ok=True)
        self.repos = {}
        for n in ("iorlas-task-loop", "iorlas-delegate", "lifesim"):
            d = self.root / n
            (d / ".beads").mkdir(parents=True)
            self.repos[n] = str(d)
        (tl.config_dir() / "repos.json").write_text(json.dumps(list(self.repos.values())))
        self.traces = tl.config_dir() / "traces.jsonl"
        self.calls, self.open_rows, self.status, self.fail_create = [], [], {}, False
        self.n = 0
        self.patch = mock.patch.object(tl, "bd", self.bd)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def bd(self, *args, cwd=None, check=False):
        self.calls.append((args, cwd))
        if args[0] == "create":
            if self.fail_create:
                return Res("", 1)
            self.n += 1
            return Res("tl-new%d\n" % self.n)
        if args[0] == "list":
            return Res(json.dumps(self.open_rows))
        if args[0] == "show":
            return Res(json.dumps([{"id": args[1], "status": self.status.get(args[1], "open")}]))
        return Res("")

    def creates(self):
        return [c for c in self.calls if c[0][0] == "create"]

    def comments(self):
        return [c for c in self.calls if c[0][0] == "comments"]

    def trace(self, run, bad, repo="lifesim", bead="b1", t=NOW - 3600):
        rec = {"run": run, "bead": bead, "repo": self.repos[repo], "ended": t,
               "reflection": {"went_well": [], "wasted": [], "change": [], "went_badly": [
                   {"what": w, "cause": c, "session": "s-" + run, "evidence": e} for w, c, e in bad]}}
        with open(self.traces, "a") as f:
            f.write(json.dumps(rec) + "\n")


class Clusters(Base):
    def test_the_same_cause_in_two_runs_is_one_cluster_and_another_cause_is_not(self):
        self.trace("r1", [("writer reran the full Unity test suite after every edit", "prompt", "9 runs, 41 min")])
        self.trace("r2", [("writer reran the Unity test suite after each edit again", "prompt", "7 runs")], bead="b2")
        self.trace("r3", [("writer reran the Unity test suite after every edit", "engine", "x")], bead="b3")
        cs = rd.cluster(rd.items(NOW - 86400, NOW))
        self.assertEqual([(c["cause"], len(c["runs"])) for c in cs], [("prompt", 2), ("engine", 1)])
        self.assertEqual([c["cause"] for c in rd.recurring(cs)], ["prompt"])

    def test_a_shared_file_joins_items_that_say_different_things(self):
        self.trace("r1", [("planner missed the dependency", "engine", "see skills/task-loop/engine.py line 12")])
        self.trace("r2", [("close step crashed on empty list", "engine", "engine.py")], bead="b2")
        self.trace("r3", [("nothing alike whatsoever here", "engine", "other.py")], bead="b3")
        cs = rd.cluster(rd.items(NOW - 86400, NOW))
        self.assertEqual(sorted(len(c["runs"]) for c in cs), [1, 2])

    def test_only_the_window_counts_and_runs_without_a_reflection_are_skipped(self):
        self.trace("old", [("a thing went wrong", "bead", "e")], t=NOW - 3 * 86400)
        with open(self.traces, "a") as f:
            f.write(json.dumps({"run": "x", "ended": NOW - 10, "reflection": None}) + "\nnot json\n")
        self.assertEqual(rd.items(NOW - 86400, NOW), [])

    def test_the_owner_repo_follows_the_cause(self):
        for cause, want in (("engine", "iorlas-task-loop"), ("prompt", "iorlas-task-loop"), ("delegate", "iorlas-delegate"),
                            ("repo_profile", "lifesim"), ("sandbox", "lifesim")):
            self.trace("r-" + cause, [("x %s thing" % cause, cause, "e")])
        owners = {c["cause"]: Path(rd.owner_repo(c)).name for c in rd.cluster(rd.items(NOW - 86400, NOW))}
        self.assertEqual(owners, {"engine": "iorlas-task-loop", "prompt": "iorlas-task-loop", "delegate": "iorlas-delegate",
                                  "repo_profile": "lifesim", "sandbox": "lifesim"})


class Filing(Base):
    def two(self, a="r1", b="r2"):
        self.trace(a, [("writer reran the whole test suite after every edit", "prompt", "9 reruns")])
        self.trace(b, [("writer reran the whole test suite after every edit again", "prompt", "7 reruns")], bead="b2")

    def test_a_recurring_cause_files_one_bead_with_runs_and_acceptance(self):
        self.two()
        d = rd.digest(NOW - 86400, NOW)
        (c,) = self.creates()
        args = c[0]
        self.assertEqual(c[1], self.repos["iorlas-task-loop"])
        self.assertIn("r1", args[args.index("--description") + 1])
        self.assertIn("r2", args[args.index("--description") + 1])
        self.assertIn("--acceptance", args)
        self.assertEqual(args[args.index("--labels") + 1], "reflect,cause-prompt")
        self.assertEqual([a["action"] for a in d["actions"]], ["filed"])
        self.assertEqual(rd.read_state()["filed"][0]["bead"], "tl-new1")

    def test_a_cause_seen_once_files_nothing(self):
        self.trace("r1", [("writer reran the whole test suite", "prompt", "e")])
        d = rd.digest(NOW - 86400, NOW)
        self.assertEqual((self.creates(), d["actions"]), ([], []))

    def test_the_same_cause_tomorrow_is_never_filed_twice_and_only_new_runs_are_commented(self):
        self.two()
        rd.digest(NOW - 86400, NOW)
        d = rd.digest(NOW - 86400, NOW)  # nothing new
        self.assertEqual(len(self.creates()), 1)
        self.assertEqual((d["actions"][0]["action"], self.comments()), ("skipped", []))
        self.trace("r3", [("writer reran the whole test suite after every edit", "prompt", "5 reruns")], bead="b3")
        d = rd.digest(NOW - 86400, NOW)
        self.assertEqual(len(self.creates()), 1)
        (c,) = self.comments()
        self.assertIn("r3", c[0][3])
        self.assertNotIn("r1", c[0][3].split("\n")[0])
        rd.digest(NOW - 86400, NOW)
        self.assertEqual(len(self.comments()), 1)  # r3 is counted now

    def test_a_like_open_bead_of_the_repo_gets_the_comment_not_a_duplicate(self):
        self.two()
        self.open_rows = [{"id": "tl-77", "title": "Writer reruns the whole test suite after every edit"}]
        d = rd.digest(NOW - 86400, NOW)
        self.assertEqual(self.creates(), [])
        self.assertEqual(d["actions"][0]["bead"], "tl-77")

    def test_a_closed_bead_whose_cause_comes_back_gets_a_new_bead_that_names_it(self):
        self.two()
        rd.digest(NOW - 86400, NOW)
        self.status["tl-new1"] = "closed"
        self.trace("r3", [("writer reran the whole test suite after every edit", "prompt", "5")], bead="b3")
        self.trace("r4", [("writer reran the whole test suite after every edit", "prompt", "4")], bead="b4")
        rd.digest(NOW - 86400, NOW)
        self.assertEqual(len(self.creates()), 2)
        args = self.creates()[1][0]
        self.assertIn("tl-new1", args[args.index("--description") + 1])

    def test_dry_run_files_and_writes_nothing(self):
        self.two()
        d = rd.digest(NOW - 86400, NOW, dry=True)
        self.assertEqual(d["actions"][0]["action"], "filed")
        self.assertEqual((self.creates(), rd.read_state()), ([], {}))

    def test_a_failed_create_records_nothing_so_the_next_day_tries_again(self):
        self.two()
        self.fail_create = True
        d = rd.digest(NOW - 86400, NOW)
        self.assertEqual((d["actions"][0]["action"], rd.read_state().get("filed")), ("failed", None))

    def test_the_dashboard_view_shows_the_filed_bead_and_writes_nothing(self):
        self.two()
        rd.digest(NOW - 86400, NOW)
        before = len(self.calls)
        v = rd.view(24, NOW)
        self.assertEqual((v["clusters"][0]["bead"], v["clusters"][0]["runs"], v["clusters"][0]["recurring"]), ("tl-new1", 2, True))
        self.assertEqual(len(self.calls), before)


class Daily(Base):
    def test_once_a_day(self):
        with mock.patch.object(rd.subprocess, "Popen") as p:
            self.assertEqual(rd.maybe_run(NOW), "started")
            self.assertEqual(rd.maybe_run(NOW + 60), "")
            self.assertEqual(rd.maybe_run(NOW + 86400 + 1), "started")
        self.assertEqual(p.call_count, 2)
        self.assertEqual(p.call_args[0][0][-2:], ["reflect", "digest"])


if __name__ == "__main__":
    unittest.main()


class Api(Base):
    def test_the_dashboard_api_returns_the_view(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "task-loop" / "dash"))
        import server
        self.trace("r1", [("writer reran the whole test suite after every edit", "prompt", "9")], t=time.time() - 60)
        self.trace("r2", [("writer reran the whole test suite after every edit again", "prompt", "7")], bead="b2", t=time.time() - 30)
        v = server.api_reflections("24")
        self.assertEqual((v["hours"], v["clusters"][0]["runs"], v["clusters"][0]["recurring"]), (24, 2, True))
        self.assertEqual(server.api_reflections("99999")["hours"], 24 * 14)
