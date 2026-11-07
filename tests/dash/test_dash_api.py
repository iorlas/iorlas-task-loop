"""GET /api/snapshot and /api/bead end to end: a Dash over a temp config dir (recorded typed logs on disk, a registered repo, an ask
file, a fake bd), its handler on a loopback port. The snapshot's version is its ETag: an unchanged one answers 304, a poll never runs bd."""

import json
import socket
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from support.case import Case
from support.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.dashlogs import RunScript, T, bead
from support.factory_index import ingest, seed_beads
from support.fakes import FakeBeadStore
from support.narrow import must
from support.repos import write_repos

from taskloop.adapters.ident import hostname
from taskloop_dash.app import Dash
from taskloop_dash.env import Env, Ports
from taskloop_dash.http import make_handler
from tlkernel import wire
from tlkernel.ask import Ask, AskOption
from tlkernel.askstore import AskStore
from tlkernel.beadsport import BeadQuery
from tlkernel.dash import BeadDetail, Snapshot
from tlkernel.dashcost import CostPage
from tlkernel.enums import AskClass, AskKind, AskStatus
from tlkernel.ids import BeadId, loop_key
from tlkernel.locator import RunLocator

NOW = T + 3600


class ApiFixture(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo = root / "lifesim"
        self.repo.mkdir()
        self.cfg = root / "cfg"
        self.cfg.mkdir()
        write_repos(self.cfg / "repos.json", self.repo)
        RunScript("b-1", slot="a", at=3000).step("plan", 300, 20_000, "OC Go").step(
            "write", 200, 30_000, text="write 1", end=False
        ).beat().write(self.cfg, repo=str(self.repo))
        RunScript("b-2", slot="b", at=100).step("plan", 100, 1).close("parked", "needs_human").write(self.cfg, repo=str(self.repo))
        AskStore.at(__import__("tlkernel.paths", fromlist=["ConfigDir"]).ConfigDir(self.cfg)).put(
            Ask(
                id="b-2-1",
                n=1,
                bead=BeadId("b-2"),
                repo=str(self.repo),
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
        self.store.put(bead("s-a", f"slot {hostname()} a", "in_progress", labels=["slot"], assignee="tl-a"))
        self.now = NOW
        ports = Ports(store=lambda repo: self.store)
        seed_beads(self.cfg, self.repo, self.store.find(BeadQuery(include_closed=True)), self.now)
        ingest(self.cfg, self.now)
        self.dash = Dash(Env(config=self.cfg, home=root, ports=ports, clock=lambda: self.now, version="v-test",
                             host=socket.gethostname()))

    def teardown_method(self):
        self.dash.reads.wait()
        self.tmp.cleanup()

    def get(self, path, q=None, held=None):
        ingest(self.cfg, self.now)
        return self.dash.reads.get(path, q or {}, held)


class Api(ApiFixture):
    def test_snapshot_decodes_strictly_with_the_facts_of_the_machine(self):
        code, body, headers = self.get("/api/snapshot")
        assert code == 200
        snap = wire.load(Snapshot, json.loads(body))
        assert headers["ETag"] == f'"{snap.version}"'
        by = {c.id: c for c in snap.beads}
        assert (by["b-1"].column.value, by["b-1"].marker.value, by["b-1"].slot, by["b-1"].lane) == ("working", "run", "a", "OC Go")
        assert (by["b-2"].column.value, by["b-2"].status) == ("questions", "Weekly or monthly?")
        assert (by["b-3"].column.value, by["b-3"].marker.value) == ("backlog", "ready")
        assert [(s.id, s.state, s.bead) for s in snap.slots] == [("a", "running", "b-1")]
        assert (snap.server.version, [p.id for p in snap.projects]) == ("v-test", [loop_key(self.repo)])

    def test_a_repo_with_a_bad_profile_is_a_red_project_and_the_good_one_still_serves(self):
        bad = self.repo.parent / "broken"
        bad.mkdir()
        write_repos(self.cfg / "repos.json", self.repo, bad)
        row = f"RED {bad}: {bad}/.task-loop.json: engine.checks"
        self.dash.env.ports.profile_error = lambda repo: row if repo == str(bad) else ""
        code, body, _ = self.get("/api/snapshot")
        assert code == 200
        snap = wire.load(Snapshot, json.loads(body))
        assert {p.id: p.profile_error for p in snap.projects} == {loop_key(self.repo): "", loop_key(bad): row}
        assert "b-1" in {c.id for c in snap.beads}

    def test_an_unchanged_snapshot_answers_304_by_since_and_by_etag(self):
        _, body, headers = self.get("/api/snapshot")
        version = json.loads(body)["version"]
        self.now += 5  # the snapshot is rebuilt, nothing changed
        assert self.get("/api/snapshot", {"since": version})[:2] == (304, b"")
        self.dash.reads.wait()
        assert self.get("/api/snapshot", {}, headers["ETag"])[:2] == (304, b"")
        code, body, _ = self.get("/api/snapshot", {"since": "stale"})
        assert (code, json.loads(body)["version"], json.loads(body)["t"]) == (200, version, self.now)

    def test_a_new_record_gives_a_new_version(self):
        _, body, _ = self.get("/api/snapshot")
        before = json.loads(body)["version"]
        must(RunLocator(self.dash.env.config).get("b-1-20261015-100000")).log.unlink()
        RunScript("b-1", slot="a", at=3000).step("plan", 300, 20_000, "OC Go").step("write", 200, 30_000, text="write 1", end=False).step(
            "checks", 60, 1
        ).beat().write(self.cfg, repo=str(self.repo))
        self.now += 5
        self.get("/api/snapshot")  # stale response schedules the refresh
        self.dash.reads.wait()
        assert json.loads(self.get("/api/snapshot")[1])["version"] != before

    def test_a_poll_does_not_run_bd_every_time(self):
        for _ in range(4):
            self.get("/api/snapshot")
            self.now += 1.5
        assert self.finds == 1

    def test_the_cost_page_decodes_and_refuses_a_bad_window(self):
        code, body, _ = self.get("/api/cost", {"window": "7d", "project": loop_key(self.repo)})
        page = wire.load(CostPage, json.loads(body))
        assert (code, page.window, page.runs, [r.key for r in page.stages]) == (200, "7d", 2, ["plan", "write"])
        assert self.get("/api/cost", {"window": "3y"})[0] == 400
        assert self.get("/api/cost", {"last": "x"})[0] == 400

    def test_the_bead_drawer(self):
        code, body, _ = self.get("/api/bead", {"project": loop_key(self.repo), "id": "b-1"})
        assert code == 200
        d = wire.load(BeadDetail, json.loads(body))
        assert (d.card.id, d.description, d.acceptance) == ("b-1", "Clamp it.", "mood >= 0")
        assert [(m.who, m.md) for m in d.comments] == [("denis", "mind the old save")]
        assert [(p.n, [c.state for c in p.cells if c.state != "empty"]) for p in d.passes] == [(1, ["done", "live"])]

    def test_stage_live_lines_change_the_bead_etag_without_engine_changes(self):
        # Resolve through the same locator as the dashboard; live files are keyed by CallStart.n.
        bundle = RunLocator(self.dash.env.config).get("b-1-20261015-100000")
        assert bundle is not None
        bundle.live.mkdir(parents=True, exist_ok=True)
        path = bundle.live / "01-plan.jsonl"
        path.write_text(json.dumps({"k": "msg", "t": T + 3001, "text": "planner summary"}) + "\n")
        code, body, headers = self.get("/api/bead", {"project": loop_key(self.repo), "id": "b-1"})
        assert code == 200
        d = wire.load(BeadDetail, json.loads(body))
        assert d.passes[0].logs[0].roles[0].attempts[0].lines[0].text == "planner summary"
        path.write_text(json.dumps({"k": "msg", "t": T + 3001, "text": "updated planner summary"}) + "\n")
        self.now += 4
        self.get("/api/bead", {"project": loop_key(self.repo), "id": "b-1"})
        self.dash.reads.wait()
        code, body, changed = self.get("/api/bead", {"project": loop_key(self.repo), "id": "b-1"}, headers["ETag"])
        assert code == 200
        assert headers["ETag"] != changed["ETag"]
        assert "updated planner summary" in body.decode()
        assert (must(d.live).kind, must(d.live).phase.value) == ("run", "write")

    def test_bead_and_cost_have_independent_conditional_tokens(self):
        snapshot_token = json.loads(self.get("/api/snapshot")[1])["version"]
        routes = [("/api/bead", {"project": loop_key(self.repo), "id": "b-1"}), ("/api/cost", {"window": "7d"})]
        for route, query in routes:
            with self.subTest(route=route):
                code, body, headers = self.get(route, query)
                token = json.loads(body)["version"]
                assert (code, headers["ETag"]) == (200, f'"{token}"')
                self.now += 1 if route == "/api/bead" else 16  # comment ok time stays unchanged within its reuse window
                assert self.get(route, {**query, "since": token})[:2] == (304, b"")
                assert self.get(route, query, headers["ETag"])[:2] == (304, b"")
                self.dash.reads.wait()  # the conditional reads above started refreshes; none may still be in flight at the write
                if route == "/api/bead":
                    self.store.note("b-1", {"author": "owner", "text": "detail changed without a snapshot change"})
                else:
                    RunScript("b-1", slot="a", at=3000).step("plan", 300, 40_000, "OC Go").close("landed").write(
                        self.cfg, repo=str(self.repo))
                self.now += 16
                self.get(route, query)  # a stale read serves the last build and refreshes behind it
                self.dash.reads.wait()
                changed, body, _ = self.get(route, {**query, "since": token})
                assert changed == 200
                assert json.loads(body)["version"] != token
                if route == "/api/bead":
                    assert json.loads(self.get("/api/snapshot")[1])["version"] == snapshot_token

    def test_unknown_or_malformed_requests(self):
        assert self.get("/api/bead", {"project": loop_key(self.repo), "id": "nope"})[0] == 404
        assert self.get("/api/bead", {"project": "other", "id": "b-1"})[0] == 404
        assert self.get("/api/bead", {"project": loop_key(self.repo), "id": "--flag"})[0] == 404
        assert self.get("/api/bead", {"id": "b-1"})[0] == 400
        assert self.get("/api/nothing")[0] == 404


class Wire(Api):
    def setup_method(self):
        super().setup_method()
        static = Path(self.tmp.name)
        (static / "index.html").write_text("<html></html>")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.dash, 0, ["127.0.0.1"], static, "s"))
        threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True).start()  # shutdown waits one poll
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def teardown_method(self):
        self.server.shutdown()
        self.server.server_close()
        super().teardown_method()

    def fetch(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def test_etag_and_304_over_http(self):
        code, body, headers = self.fetch("/api/snapshot")
        assert code == 200
        etag = headers["ETag"]
        assert etag == f'"{json.loads(body)["version"]}"'
        assert self.fetch("/api/snapshot", {"If-None-Match": etag})[:2] == (304, b"")
        assert self.fetch("/api/snapshot?since=" + json.loads(body)["version"])[0] == 304
        assert self.fetch(f"/api/bead?project={loop_key(self.repo)}&id=nope")[0] == 404
        assert self.fetch(f"/api/bead?project={loop_key(self.repo)}&id=b-1")[0] == 200
        assert self.fetch("/api/tasks")[0] == 404  # the old API is gone
