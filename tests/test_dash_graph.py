import json
import os
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop" / "dash"))
import graph  # noqa: E402

NOW = time.time()


def ts(ago=0):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - ago))


def bead(i, status="open", labels=("auto",), blocks=(), parent=None, kind="task", **kw):
    b = {"id": i, "title": "title " + i, "status": status, "labels": list(labels), "issue_type": kind, "priority": 2,
         "dependencies": [{"issue_id": i, "depends_on_id": x, "type": "blocks"} for x in blocks], "parent": parent}
    if parent:
        b["dependencies"].append({"issue_id": i, "depends_on_id": parent, "type": "parent-child"})
    b.update(kw)
    return b


CFG = {"pick_label": "auto", "skip_labels": []}


def states(beads, queued=(), running=(), asks=(), cfg=CFG):
    g = graph.build(beads, cfg, queued, running, asks, now=NOW)
    return {n["id"]: n for n in g["nodes"]}, g


class States(unittest.TestCase):
    def test_every_state(self):
        beads = [
            bead("run"), bead("q"), bead("blk", blocks=["q"]), bead("ask"), bead("taste", labels=["auto", "owner-taste"]),
            bead("info", labels=["needs-info"]), bead("manual", labels=[]), bead("ep", kind="epic", labels=[]),
            bead("fin", status="closed", closed_at=ts(3600)), bead("old", status="closed", closed_at=ts(3 * 86400)),
            bead("dfr", status="deferred"), bead("rev", status="review")]
        n, g = states(beads, queued={"q"}, running={"run"}, asks={"ask"})
        self.assertEqual({k: v["state"] for k, v in n.items()},
                         {"run": "running", "q": "queued", "blk": "blocked", "ask": "waits", "taste": "waits",
                          "info": "waits", "manual": "not_auto", "ep": "epic", "fin": "done", "rev": "waits"})
        self.assertNotIn("old", n)  # closed more than a day ago
        self.assertNotIn("dfr", n)  # deferred and holding nothing up
        s = g["summary"]
        self.assertEqual((s["ready"], s["running"], s["blocked"], s["waits"], s["not_auto"], s["done_today"]),
                         (1, 1, 1, 4, 1, 1))

    def test_closed_blocker_does_not_block(self):
        n, _ = states([bead("a", status="closed", closed_at=ts(60)), bead("b", blocks=["a"])], queued={"b"})
        self.assertEqual(n["b"]["state"], "queued")

    def test_deferred_blocker_is_shown_and_blocks(self):
        n, g = states([bead("d", status="deferred"), bead("b", blocks=["d"])])
        self.assertEqual((n["d"]["state"], n["b"]["state"]), ("deferred", "blocked"))
        self.assertEqual(g["edges"], [{"source": "d", "target": "b"}])

    def test_local_queue_fallback(self):
        beads = [bead("a"), bead("b", blocks=["a"]), bead("c", labels=[]), bead("e", kind="epic"),
                 bead("s", labels=["auto", "skipme"])]
        self.assertEqual(graph.local_queue(beads, {"pick_label": "auto", "skip_labels": ["skipme"]}), {"a"})


class Unblocks(unittest.TestCase):
    def test_transitive_count(self):
        # a -> b -> c, a -> d ; e is unrelated
        beads = [bead("a"), bead("b", blocks=["a"]), bead("c", blocks=["b"]), bead("d", blocks=["a"]), bead("e")]
        n, g = states(beads)
        self.assertEqual([n[i]["unblocks"] for i in "abcde"], [3, 1, 0, 0, 0])
        self.assertEqual(len(g["edges"]), 3)

    def test_diamond_counts_once(self):
        beads = [bead("a"), bead("b", blocks=["a"]), bead("c", blocks=["a"]), bead("d", blocks=["b", "c"])]
        n, _ = states(beads)
        self.assertEqual(n["a"]["unblocks"], 3)

    def test_closed_and_epics_do_not_count(self):
        beads = [bead("a"), bead("b", status="closed", closed_at=ts(60), blocks=["a"]),
                 bead("ep", kind="epic", blocks=["a"]), bead("c", blocks=["a"])]
        n, _ = states(beads)
        self.assertEqual(n["a"]["unblocks"], 1)

    def test_cycle_does_not_crash(self):
        beads = [bead("a", blocks=["b"]), bead("b", blocks=["c"]), bead("c", blocks=["a"]), bead("self", blocks=["self"])]
        n, g = states(beads)
        self.assertEqual([n[i]["unblocks"] for i in "abc"], [2, 2, 2])
        self.assertEqual(n["self"]["unblocks"], 0)
        self.assertTrue(all(e["source"] != e["target"] for e in g["edges"]))

    def test_missing_blocker_is_ignored(self):
        n, g = states([bead("a", blocks=["gone"])], queued={"a"})
        self.assertEqual((n["a"]["state"], g["edges"]), ("queued", []))


class Epics(unittest.TestCase):
    def test_parent_child_is_grouping_not_an_edge(self):
        beads = [bead("ep", kind="epic", labels=[]), bead("k1", parent="ep"), bead("k2", parent="ep", blocks=["k1"])]
        n, g = states(beads, queued={"k1"})
        self.assertEqual((n["k1"]["epic"], n["k2"]["epic"], n["ep"]["epic"]), ("ep", "ep", None))
        self.assertEqual(g["edges"], [{"source": "k1", "target": "k2"}])
        self.assertEqual(n["ep"]["kids"], {"queued": 1, "blocked": 1})
        self.assertEqual(n["ep"]["unblocks"], 0)

    def test_nested_epic_and_cyclic_parents(self):
        beads = [bead("top", kind="epic"), bead("mid", kind="epic", parent="top"), bead("leaf", parent="mid"),
                 bead("x", parent="y"), bead("y", parent="x")]
        n, _ = states(beads)
        self.assertEqual((n["leaf"]["epic"], n["mid"]["epic"]), ("mid", "top"))
        self.assertIsNone(n["x"]["epic"])

    def test_closed_epic_is_not_a_group(self):
        beads = [bead("ep", kind="epic", status="closed", closed_at=ts(9 * 86400)), bead("k", parent="ep")]
        n, _ = states(beads)
        self.assertIsNone(n["k"]["epic"])


class Api(unittest.TestCase):
    """/api/graph over a temp HOME and config dir, bd stubbed with a fake beads set."""

    def test_endpoint(self):
        import server
        with tempfile.TemporaryDirectory() as home:
            repo = Path(home) / "demo"
            repo.mkdir()
            cfg = Path(home) / "cfg" / "task-loop"
            cfg.mkdir(parents=True)
            (cfg / "repos.json").write_text(json.dumps({str(repo): {}}))
            (cfg / "asks").mkdir()
            (cfg / "asks" / "b.json").write_text(json.dumps({"status": "open", "question": "?"}))
            beads = [bead("a"), bead("b", blocks=["a"]), bead("c", blocks=["a"], labels=[])]
            env = {"HOME": home, "XDG_CONFIG_HOME": str(cfg.parent), "APPDATA": str(cfg.parent)}
            with mock.patch.dict(os.environ, env), mock.patch.object(server, "HOME", Path(home)), \
                    mock.patch.object(server, "beads_of", lambda r: beads), \
                    mock.patch.object(server, "api_tasks", lambda: {"tasks": [{"id": "a", "state": "running"}]}), \
                    mock.patch.object(server, "loop_queue", lambda r, b, c: set()):
                server._cache.clear()
                out = server.api_graph("demo")
                self.assertEqual(out["repos"], ["demo"])
                by = {n["id"]: n for n in out["nodes"]}
                self.assertEqual((by["a"]["state"], by["b"]["state"], by["c"]["state"]), ("running", "waits", "blocked"))
                self.assertEqual(by["a"]["unblocks"], 2)
                self.assertEqual(server.api_graph("nope")["error"], "no such repo")
                self.assertEqual(server.api_graph("")["repo"], "demo")  # no repo named: the first registered one


if __name__ == "__main__":
    unittest.main()
