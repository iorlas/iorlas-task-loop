"""Repository collisions must never mix dashboard reads or owner writes."""

from pathlib import Path

from support.dashlogs import RunScript, T, bead
from support.factory_index import ingest, seed_beads
from support.fakes import FakeBeadStore

from taskloop.app.launch.dash_ports import owner_intake, owner_writes
from taskloop_dash.app import Dash
from taskloop_dash.env import Env, Ports
from tlkernel.askstore import AskStore
from tlkernel.ids import loop_key
from tlkernel.lookrows import LookRows
from tlkernel.run import RunState
from tlkernel.runrows import RunRows
from tlpipeline.api import requests
from tltestkit.case import Case
from tltestkit.narrow import must
from tltestkit.repos import write_repos
from tltestkit.runs import manifest
from tltestkit.tmpdir import TemporaryDirectory


class RepoIdentity(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.repos = [root / side / "demo" for side in ("a", "b")]
        self.stores = {}
        self.runs = []
        cfg = root / "cfg"
        cfg.mkdir()
        for n, repo in enumerate(self.repos):
            repo.mkdir(parents=True)
            store = self.stores[str(repo)] = FakeBeadStore()
            store.put(bead("b-1", status="in_progress"))
            seed_beads(cfg, repo, store.beads.values(), T + 200)
            script = RunScript("b-1", stamp=f"run{n}", at=n * 100).step("write", 10, 100 + n, text=f"repo {n}", end=False)
            script.write(cfg)
            manifest(cfg, script.name, "b-1", script.t0, repo=str(repo), state=RunState.RUNNING)
            self.runs.append(script.name)
        write_repos(cfg / "repos.json", *self.repos)
        env = Env(cfg, home=root, clock=lambda: T + 200)
        intake = owner_intake(AskStore.at(env.config), self.stores.__getitem__, env.clock, look_rows=LookRows(env.config))
        env.ports = Ports(store=self.stores.__getitem__, **owner_writes(intake, env.config))
        ingest(env.config, env.clock())
        self.dash = Dash(env)

    def test_same_basename_projects_have_distinct_keys_and_names(self):
        projects = self.dash.reads.snapshot().projects
        assert {p.id for p in projects} == {loop_key(r) for r in self.repos}
        assert len({p.name for p in projects}) == 2
        assert all(p.name.startswith("demo") for p in projects)
        assert all(p.id not in p.name for p in projects)

    def test_same_bead_runs_stay_in_their_project(self):
        cards = self.dash.reads.snapshot().beads
        assert {c.project: c.totals.tokens for c in cards} == {loop_key(r): 100 + n for n, r in enumerate(self.repos)}
        for n, repo in enumerate(self.repos):
            detail = must(self.dash.reads.bead(loop_key(repo), "b-1"))
            assert detail.card.totals.tokens == 100 + n
            code, page = self.dash.live.page(loop_key(repo), "b-1")
            assert code == 200
            assert f"repo {n}" in str(page)
            assert f"repo {1 - n}" not in str(page)

    def test_cross_repo_stop_is_refused_without_writing(self):
        for verb, fields in (("stop", {}), ("park", {}), ("note", {"text": "hello"}),
                             ("cause", {"cause": "process"}), ("ack", {"ack": True})):
            with self.subTest(verb=verb):
                code, out = self.dash.writes.post(verb, {"project": loop_key(self.repos[0]), "bead": "b-1",
                                                        "run": self.runs[1], **fields})
                assert code == 200
                assert not out["ok"]
                assert "repo" in out["message"].lower()
        assert not any(requests.peek(self.dash.env.config, r) for r in self.runs)
        assert not any(s.show("b-1").metadata for s in self.stores.values())

    def test_stop_refuses_the_wrong_bead_and_an_observed_run_that_ended(self):
        body = {"project": loop_key(self.repos[0]), "bead": "b-2", "run": self.runs[0]}
        assert "repo and bead" in self.dash.writes.post("stop", body)[1]["message"]
        cfg = self.dash.env.config
        store = RunRows(cfg)
        store.put(must(store.get(self.runs[0])).replace(state=RunState.DONE))
        body["bead"] = "b-1"
        out = self.dash.writes.post("stop", body)[1]
        assert not out["ok"]
        assert "no run" in out["message"]
        assert requests.peek(cfg, self.runs[0]) is None
        assert not self.stores[str(self.repos[0])].show("b-1").metadata

    def test_stop_targets_the_observed_run_even_when_a_newer_run_exists(self):
        repo = self.repos[0]
        cfg = self.dash.env.config
        manifest(cfg, "successor", "b-1", T + 150, repo=str(repo), state=RunState.RUNNING)
        code, out = self.dash.writes.post("stop", {"project": loop_key(repo), "bead": "b-1", "run": self.runs[0]})
        assert (code, out["ok"]) == (200, True)
        assert requests.peek(cfg, self.runs[0]) is not None
        assert requests.peek(cfg, "successor") is None

    def test_old_command_without_observed_run_is_a_bad_body(self):
        code, _ = self.dash.writes.post("stop", {"project": loop_key(self.repos[0]), "bead": "b-1"})
        assert code == 400
