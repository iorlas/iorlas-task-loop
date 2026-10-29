"""GET /api/snapshot and /api/bead end to end: a Dash over a temp config dir (recorded typed logs on disk, a registered repo, an ask
file, a fake bd), its handler on a loopback port. The snapshot's version is its ETag: an unchanged one answers 304, a poll never runs bd."""

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: F401
from support.dashlogs import RunScript, T, bead
from support.fakes import FakeBeadStore
from support.narrow import must

from taskloop.contracts import wire
from taskloop.contracts.ask import Ask, AskOption
from taskloop.contracts.dash import BeadDetail, Snapshot
from taskloop.contracts.enums import AskClass, AskKind, AskStatus
from taskloop.contracts.stores import AskStore
from taskloop_dash.app import Dash
from taskloop_dash.env import Env, Ports
from taskloop_dash.http import make_handler

NOW = T + 3600


class Api(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo = root / "lifesim"
        self.repo.mkdir()
        self.cfg = root / "cfg"
        self.cfg.mkdir()
        (self.cfg / "repos.json").write_text(json.dumps({str(self.repo): {}}))
        RunScript("b-1", slot="a", at=3000).step("plan", 300, 20_000, "OC Go").step(
            "write", 200, 30_000, text="write 1", end=False
        ).beat().write(self.cfg)
        RunScript("b-2", slot="b", at=100).step("plan", 100, 1).close("parked", "needs_human").write(self.cfg)
        AskStore.at(__import__("taskloop.contracts.paths", fromlist=["ConfigDir"]).ConfigDir(self.cfg)).put(
            Ask(
                id="b-2-1",
                n=1,
                bead="b-2",
                kind=AskKind.DECISION,
                ask_class=AskClass.OPEN_QUESTION,
                decision="Weekly or monthly?",
                run="r",
                t=T + 200,
                status=AskStatus.OPEN,
                options=[AskOption(label="Weekly", consequence="simple")],
            )
        )
        self.store = FakeBeadStore()
        for b in (
            bead("b-1", "Clamp mood", "in_progress", assignee="tl-a", description="Clamp it.", acceptance_criteria="mood >= 0"),
            bead("b-2", "Bills"),
            bead("b-3", "Later"),
        ):
            self.store.put(b)
        self.store.note("b-1", {"author": "denis", "text": "mind the old save"})
        self.finds = 0
        real_find = self.store.find

        def counting(query):
            self.finds += 1
            return real_find(query)

        self.store.find = counting
        slots = [bead("s-a", "slot box a", "in_progress", labels=["slot"], assignee="tl-a").model_dump()]
        self.now = NOW
        ports = Ports(store=lambda repo: self.store, slot_beads=lambda repo: slots)
        self.dash = Dash(Env(config=self.cfg, home=root, ports=ports, clock=lambda: self.now, version="v-test"))

    def tearDown(self):
        self.tmp.cleanup()

    def get(self, path, q=None, held=None):
        return self.dash.reads.get(path, q or {}, held)

    def test_snapshot_decodes_strictly_with_the_facts_of_the_machine(self):
        code, body, headers = self.get("/api/snapshot")
        self.assertEqual(code, 200)
        snap = wire.load(Snapshot, json.loads(body))
        self.assertEqual(headers["ETag"], f'"{snap.version}"')
        by = {c.id: c for c in snap.beads}
        self.assertEqual((by["b-1"].column.value, by["b-1"].marker.value, by["b-1"].slot, by["b-1"].lane), ("working", "run", "a", "OC Go"))
        self.assertEqual((by["b-2"].column.value, by["b-2"].status), ("questions", "Weekly or monthly?"))
        self.assertEqual((by["b-3"].column.value, by["b-3"].marker.value), ("backlog", "ready"))
        self.assertEqual([(s.id, s.state, s.bead) for s in snap.slots], [("a", "running", "b-1")])
        self.assertEqual((snap.server.version, [p.id for p in snap.projects]), ("v-test", ["lifesim"]))

    def test_an_unchanged_snapshot_answers_304_by_since_and_by_etag(self):
        _, body, headers = self.get("/api/snapshot")
        version = json.loads(body)["version"]
        self.now += 5  # the snapshot is rebuilt, nothing changed
        self.assertEqual(self.get("/api/snapshot", {"since": version})[:2], (304, b""))
        self.assertEqual(self.get("/api/snapshot", {}, headers["ETag"])[:2], (304, b""))
        code, body, _ = self.get("/api/snapshot", {"since": "stale"})
        self.assertEqual((code, json.loads(body)["version"], json.loads(body)["t"]), (200, version, self.now))

    def test_a_new_record_gives_a_new_version(self):
        _, body, _ = self.get("/api/snapshot")
        before = json.loads(body)["version"]
        RunScript("b-1", slot="a", at=3000).step("plan", 300, 20_000, "OC Go").step("write", 200, 30_000, text="write 1", end=False).step(
            "checks", 60, 1
        ).beat().write(self.cfg)
        self.now += 5
        self.assertNotEqual(json.loads(self.get("/api/snapshot")[1])["version"], before)

    def test_a_poll_does_not_run_bd_every_time(self):
        for _ in range(4):
            self.get("/api/snapshot")
            self.now += 1.5
        self.assertEqual(self.finds, 1)

    def test_the_bead_drawer(self):
        code, body, _ = self.get("/api/bead", {"project": "lifesim", "id": "b-1"})
        self.assertEqual(code, 200)
        d = wire.load(BeadDetail, json.loads(body))
        self.assertEqual((d.card.id, d.description, d.acceptance), ("b-1", "Clamp it.", "mood >= 0"))
        self.assertEqual([(m.who, m.md) for m in d.comments], [("denis", "mind the old save")])
        self.assertEqual([(p.n, [c.state for c in p.cells if c.state != "empty"]) for p in d.passes], [(1, ["small", "live"])])
        self.assertEqual((must(d.live).kind, must(d.live).phase.value), ("run", "write"))

    def test_unknown_or_malformed_requests(self):
        self.assertEqual(self.get("/api/bead", {"project": "lifesim", "id": "nope"})[0], 404)
        self.assertEqual(self.get("/api/bead", {"project": "other", "id": "b-1"})[0], 404)
        self.assertEqual(self.get("/api/bead", {"project": "lifesim", "id": "--flag"})[0], 404)
        self.assertEqual(self.get("/api/bead", {"id": "b-1"})[0], 400)
        self.assertEqual(self.get("/api/nothing")[0], 404)


class Wire(Api):
    def setUp(self):
        super().setUp()
        static = Path(self.tmp.name)
        (static / "index.html").write_text("<html></html>")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.dash, 0, ["127.0.0.1"], static, lambda: "t", "s"))
        threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True).start()  # shutdown waits one poll
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def fetch(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def test_etag_and_304_over_http(self):
        code, body, headers = self.fetch("/api/snapshot")
        self.assertEqual(code, 200)
        etag = headers["ETag"]
        self.assertEqual(etag, f'"{json.loads(body)["version"]}"')
        self.assertEqual(self.fetch("/api/snapshot", {"If-None-Match": etag})[:2], (304, b""))
        self.assertEqual(self.fetch("/api/snapshot?since=" + json.loads(body)["version"])[0], 304)
        self.assertEqual(self.fetch("/api/bead?project=lifesim&id=nope")[0], 404)
        self.assertEqual(self.fetch("/api/bead?project=lifesim&id=b-1")[0], 200)
        self.assertEqual(self.fetch("/api/tasks")[0], 404)  # the old API is gone


if __name__ == "__main__":
    unittest.main()
