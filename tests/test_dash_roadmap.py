"""The Roadmap tab: lanes (stage rail, unlocks, last passes), the queue as a tree of what each bead unblocks, /api/roadmap."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop" / "dash"))
import graph  # noqa: E402
import roadmap  # noqa: E402

NOW = time.time()
CFG = {"pick_label": "auto", "skip_labels": []}


def bead(i, status="open", blocks=(), kind="task", **kw):
    b = {"id": i, "title": "title " + i, "status": status, "labels": ["auto"], "issue_type": kind, "priority": 2,
         "dependencies": [{"issue_id": i, "depends_on_id": x, "type": "blocks"} for x in blocks], "parent": None}
    b.update(kw)
    return b


def stamp(ago):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(NOW - ago))


def road(beads, lanes=(), ranked=(), skipped=(), history=(), trails=None, running=(), queued=()):
    g = graph.build(beads, CFG, set(queued) or {i for i, _ in ranked}, set(running), (), now=NOW)
    return roadmap.build(g, list(lanes), list(ranked), list(skipped), list(history), trails or {}, now=NOW)


def blocks(*kinds):
    return [{"kind": k, "label": k, "status": s} for k, s in kinds]


class Rail(unittest.TestCase):
    def state(self, bl, run=1):
        return {r["step"]: r["state"] for r in roadmap.rail(bl, run)}

    def test_live_block_is_now_and_earlier_steps_done(self):
        s = self.state(blocks(("plan", "ok"), ("write", "ok"), ("checks", "run")))
        self.assertEqual([s[k] for k in roadmap.STEPS], ["done", "done", "now", "todo", "todo", "todo"])

    def test_replan_counts_as_plan_and_a_finished_block_is_not_now(self):
        s = self.state(blocks(("write", "ok"), ("checks", "fail"), ("replan", "ok")))
        self.assertEqual((s["plan"], s["write"], s["checks"], s["review"]), ("done", "done", "done", "todo"))
        self.assertNotIn("now", s.values())

    def test_a_resumed_run_has_its_plan_done_and_no_blocks_is_all_todo(self):
        self.assertEqual(self.state(blocks(("write", "run")), run=2)["plan"], "done")
        self.assertEqual(set(self.state([]).values()), {"todo"})


class Tree(unittest.TestCase):
    def test_fan_out_depth_and_needs(self):
        # root -> k1..k7 ; k1 -> leaf ; k2 also needs other (open)
        beads = [bead("root"), bead("other")] + [bead("k%d" % i, blocks=["root"] + (["other"] if i == 2 else [])) for i in range(1, 8)]
        beads.append(bead("leaf", blocks=["k1"]))
        r = road(beads, ranked=[("root", "lowest id")])
        t = r["queue"][0]["tree"]
        self.assertEqual(len(t), roadmap.WIDE)  # capped, the cut ones counted in `more`
        self.assertEqual(t[-1]["more"], 2)
        by = {k["id"]: k for k in t}
        self.assertEqual([c["id"] for c in by["k1"]["kids"]], ["leaf"])  # unblocks-most first, so k1 leads
        self.assertEqual(by["k2"]["needs"], 1)
        self.assertEqual(by["k1"]["needs"], 0)
        self.assertEqual(r["queue"][0]["unblocks"], 8)

    def test_closed_epic_and_cycle_never_loop_or_show(self):
        beads = [bead("a", blocks=["c"]), bead("b", blocks=["a"]), bead("c", blocks=["b"]),
                 bead("done", status="closed", closed_at=stamp(60), blocks=["a"]), bead("ep", kind="epic", blocks=["a"])]
        r = road(beads, ranked=[("a", "")])

        def ids(ks):
            return [x for k in ks for x in [k["id"]] + ids(k["kids"])]
        shown = ids(r["queue"][0]["tree"])
        self.assertNotIn("done", shown)
        self.assertNotIn("ep", shown)
        self.assertEqual(len(shown), len(set(shown)) + 1 if "a" in shown else len(set(shown)))  # a seen id stops the walk
        self.assertLessEqual(len(shown), 6)

    def test_released_lists_what_a_landing_let_go(self):
        beads = [bead("a", status="closed", closed_at=stamp(60)), bead("b", blocks=["a"]), bead("c", blocks=["a", "x"]), bead("x")]
        g = graph.build(beads, CFG, {"b", "x"}, set(), (), now=NOW)
        by = {n["id"]: n for n in g["nodes"]}
        out = {}
        for e in g["edges"]:
            out.setdefault(e["source"], []).append(e["target"])
        self.assertEqual([x["id"] for x in roadmap.released("a", out, by)], ["b"])  # c still waits on x


class Build(unittest.TestCase):
    def test_lanes_queue_held_and_history(self):
        beads = [bead("run1", status="in_progress"), bead("next1"), bead("kid", blocks=["run1"]), bead("held1"),
                 bead("kid2", blocks=["held1"]), bead("landed1", status="closed", closed_at=stamp(900))]
        hist = [
            {"ts": stamp(7200), "bead": "run1", "slot": "s1", "outcome": "parked", "minutes": 30, "asked": True, "why": "needs you"},
            {"ts": stamp(3600), "bead": "x", "slot": "s1", "outcome": "taken", "minutes": 0, "why": "lost the claim"},
            {"ts": stamp(900), "bead": "landed1", "slot": "s2", "outcome": "landed", "minutes": 12, "asked": False, "why": ""}]
        trails = {"run1": {"run": 2, "stage": "checks", "blocks": blocks(("write", "ok"), ("checks", "run"))}}
        r = road(beads, lanes=[{"slot": "s2", "bead": None, "since": None}, {"slot": "s1", "bead": "run1", "since": NOW - 60}],
                 ranked=[("next1", "lowest id")], skipped=[("held1", "area sim busy: run1 in s1"), ("gone", "unknown")],
                 history=hist, trails=trails, running=["run1"])
        self.assertEqual([ln["slot"] for ln in r["lanes"]], ["s1", "s2"])
        s1, s2 = r["lanes"]
        self.assertEqual((s1["bead"], s1["run"], s1["stage"]), ("run1", 2, "checks"))
        self.assertEqual([k["id"] for k in s1["unlocks"]], ["kid"])
        self.assertEqual([p["outcome"] for p in s1["past"]], ["parked"])  # "taken" is not a pass
        self.assertEqual(s2["rail"], [])
        self.assertEqual([p["outcome"] for p in s2["past"]], ["landed"])
        self.assertEqual([(q["id"], q["reason"]) for q in r["queue"]], [("next1", "lowest id")])
        self.assertEqual([(h["id"], h["unblocks"], [k["id"] for k in h["tree"]]) for h in r["held"]], [("held1", 1, ["kid2"])])
        self.assertEqual(r["held_total"], 1)  # an id the graph does not know is dropped
        self.assertEqual((r["summary"]["parked"], r["summary"]["landed"], r["summary"]["ready"]), (1, 1, 1))
        self.assertEqual([p["id"] for p in r["recent"]], ["landed1", "run1"])  # newest first

    def test_landed_pass_names_what_it_released(self):
        beads = [bead("a", status="closed", closed_at=stamp(60)), bead("b", blocks=["a"])]
        r = road(beads, history=[{"ts": stamp(60), "bead": "a", "slot": "s1", "outcome": "landed", "minutes": 3}], queued={"b"})
        self.assertEqual([x["id"] for x in r["recent"][0]["released"]], ["b"])

    def test_empty_everything(self):
        r = road([])
        self.assertEqual((r["lanes"], r["queue"], r["held"], r["recent"]), ([], [], [], []))


class Verdict(unittest.TestCase):
    def test_one_line_on_churn_and_cost_empty_when_unremarkable(self):
        r = {"writes": 4, "red_checks": 6, "replans": 1, "secs": 1000, "checks_secs": 580, "tokens_all": {"in": 2_000_000, "cached": 1_500_000, "out": 100_000}}
        v = roadmap.verdict(r, {"median_fresh": 100_000})
        self.assertEqual(v, "write round 4 · checks failed 6× · planned 2× · 58% of its time in checks · 600k fresh tokens, 6.0× the median bead")
        self.assertEqual(roadmap.verdict({"secs": 100, "checks_secs": 10}, {"median_fresh": 100_000}), "")

    def test_briefs_cover_every_id_the_page_links(self):
        beads = [bead("run1", status="in_progress"), bead("kid", blocks=["run1"]), bead("q1")]
        rows = {"run1": {"state": "running", "label": "checks stage 2/2", "runs": 2, "blocks": 9, "secs": 600,
                         "tokens_all": {"in": 1000, "cached": 400, "out": 100}}}
        g = graph.build(beads, CFG, {"q1"}, {"run1"}, (), now=NOW)
        r = roadmap.build(g, [{"slot": "s1", "bead": "run1", "since": NOW}], [("q1", "")], [], [], {}, now=NOW, rows=rows)
        self.assertEqual(set(r["briefs"]), {"run1", "kid", "q1"})
        b = r["briefs"]["run1"]
        self.assertEqual((b["why"], b["tok"], b["fresh"], b["runs"]), ("checks stage 2/2", 1100, 700, 2))
        self.assertEqual((b["new_in"], b["cache"], b["out"]), (600, 400, 100))
        self.assertEqual(r["briefs"]["kid"]["state"], "blocked")


class Api(unittest.TestCase):
    """/api/roadmap over a temp HOME and config dir: bd, the loop's queue and its files stubbed."""

    def test_endpoint(self):
        import server
        with tempfile.TemporaryDirectory() as home:
            repo = Path(home) / "demo"
            repo.mkdir()
            cfg = Path(home) / "cfg" / "task-loop"
            cfg.mkdir(parents=True)
            (cfg / "repos.json").write_text(json.dumps({str(repo): {}}))
            beads = [bead("a", status="in_progress"), bead("b", blocks=["a"]), bead("c")]
            env = {"HOME": home, "XDG_CONFIG_HOME": str(cfg.parent), "APPDATA": str(cfg.parent)}
            with mock.patch.dict(os.environ, env), mock.patch.object(server, "HOME", Path(home)), \
                    mock.patch.object(server, "beads_of", lambda r: beads), \
                    mock.patch.object(server, "api_tasks", lambda: {"tasks": [{"id": "a", "state": "running", "repo": "demo", "slot": "s9",
                                                                              "stage": "writing", "since": 30}], "lanes": []}), \
                    mock.patch.object(server, "loop_order", lambda r, b, c: ([("c", "lowest id")], [("b", "area x busy")])), \
                    mock.patch.object(server, "loop_files", lambda r: ([], [])), \
                    mock.patch.object(server, "engine_logs", lambda retain=True: {}):
                server._cache.clear()
                out = server.api_roadmap("demo")
                self.assertEqual(out["repos"], ["demo"])
                (lane,) = out["lanes"]  # a bead run by hand has a slot but no loop: it still gets a lane
                self.assertEqual((lane["slot"], lane["bead"]), ("s9", "a"))
                self.assertEqual([k["id"] for k in lane["unlocks"]], ["b"])
                self.assertEqual([q["id"] for q in out["queue"]], ["c"])
                self.assertEqual([h["id"] for h in out["held"]], ["b"])
                self.assertEqual(out["briefs"]["a"]["state"], "running")
                self.assertTrue(out["signals"] == [] or all("sev" in x for x in out["signals"]))
                self.assertEqual(server.api_roadmap("nope")["error"], "no such repo")


class BeadApi(unittest.TestCase):
    def test_bead_panel_joins_bd_and_the_engine_runs(self):
        import server
        shown = [{"id": "a", "title": "T", "status": "open", "priority": 1, "labels": ["auto"], "description": "D", "acceptance_criteria": "AC",
                  "dependencies": [{"id": "z", "title": "Z", "status": "closed", "dependency_type": "blocks"}]}]
        comments = [{"author": "me", "text": "hello", "created_at": "2026-10-23T10:00:00Z"}]
        with mock.patch.object(server, "resolve_repo", lambda r, b="": "/repo"), \
                mock.patch.object(server, "bd_json", lambda repo, *a: shown if a[0] == "show" else comments), \
                mock.patch.object(server, "engine_logs", lambda retain=True: {}):
            server._cache.clear()
            out = server.api_bead("demo", "a")
        self.assertEqual((out["title"], out["description"], out["acceptance"], out["found"]), ("T", "D", "AC", True))
        self.assertEqual([c["text"] for c in out["comments"]], ["hello"])
        self.assertEqual(out["deps"][0]["id"], "z")
        self.assertEqual(out["runs"], [])

    def test_unknown_bead_is_not_found_not_an_error(self):
        import server
        with mock.patch.object(server, "resolve_repo", lambda r, b="": ""), mock.patch.object(server, "engine_logs", lambda retain=True: {}):
            server._cache.clear()
            self.assertFalse(server.api_bead("demo", "nope")["found"])


if __name__ == "__main__":
    unittest.main()
