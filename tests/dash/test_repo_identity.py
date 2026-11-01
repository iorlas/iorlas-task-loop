"""Repository collisions must never mix dashboard reads or owner writes."""

import tempfile
import unittest
from pathlib import Path

import support.paths  # noqa: F401
from support.dashlogs import RunScript, T, bead
from support.fakes import FakeBeadStore
from support.narrow import must
from support.repos import write_repos
from support.runs import manifest

from taskloop.app.launch.dash_ports import owner_intake, owner_writes
from taskloop.contracts.ids import loop_key
from taskloop.contracts.run import RunManifest, RunState
from taskloop.contracts.stores import AskStore, JsonStore
from taskloop_dash.app import Dash
from taskloop_dash.env import Env, Ports


class RepoIdentity(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
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
            script = RunScript("b-1", stamp=f"run{n}", at=n * 100).step("write", 10, 100 + n, text=f"repo {n}", end=False)
            script.write(cfg)
            manifest(cfg, script.name, "b-1", script.t0, repo=str(repo), state=RunState.RUNNING)
            self.runs.append(script.name)
        write_repos(cfg / "repos.json", *self.repos)
        env = Env(cfg, home=root, clock=lambda: T + 200)
        intake = owner_intake(AskStore.at(env.config), self.stores.__getitem__, env.clock)
        env.ports = Ports(store=self.stores.__getitem__, **owner_writes(intake, env.config))
        self.dash = Dash(env)

    def test_same_basename_projects_have_distinct_keys_and_names(self):
        projects = self.dash.reads.snapshot().projects
        self.assertEqual({p.id for p in projects}, {loop_key(r) for r in self.repos})
        self.assertEqual(len({p.name for p in projects}), 2)
        self.assertTrue(all(p.name.startswith("demo") for p in projects))
        self.assertTrue(all(p.id not in p.name for p in projects))

    def test_same_bead_runs_stay_in_their_project(self):
        cards = self.dash.reads.snapshot().beads
        self.assertEqual({c.project: c.totals.tokens for c in cards},
                         {loop_key(r): 100 + n for n, r in enumerate(self.repos)})
        for n, repo in enumerate(self.repos):
            detail = must(self.dash.reads.bead(loop_key(repo), "b-1"))
            self.assertEqual(detail.card.totals.tokens, 100 + n)
            code, page = self.dash.live.page(loop_key(repo), "b-1")
            self.assertEqual(code, 200)
            self.assertIn(f"repo {n}", str(page))
            self.assertNotIn(f"repo {1 - n}", str(page))

    def test_cross_repo_stop_is_refused_without_writing(self):
        for verb, fields in (("stop", {}), ("park", {}), ("note", {"text": "hello"}),
                             ("cause", {"cause": "process"}), ("ack", {"ack": True})):
            with self.subTest(verb=verb):
                code, out = self.dash.writes.post(verb, {"project": loop_key(self.repos[0]), "bead": "b-1",
                                                        "run": self.runs[1], **fields})
                self.assertEqual(code, 200)
                self.assertFalse(out["ok"])
                self.assertIn("repo", out["message"].lower())
        self.assertFalse(any(self.dash.env.config.run_request(r).exists() for r in self.runs))
        self.assertFalse(any(s.show("b-1").metadata for s in self.stores.values()))

    def test_stop_refuses_the_wrong_bead_and_an_observed_run_that_ended(self):
        body = {"project": loop_key(self.repos[0]), "bead": "b-2", "run": self.runs[0]}
        self.assertIn("repo and bead", self.dash.writes.post("stop", body)[1]["message"])
        cfg = self.dash.env.config
        store = JsonStore(cfg.run_manifest(self.runs[0]), RunManifest)
        store.write(must(store.get()).replace(state=RunState.DONE))
        body["bead"] = "b-1"
        out = self.dash.writes.post("stop", body)[1]
        self.assertFalse(out["ok"])
        self.assertIn("no run", out["message"])
        self.assertFalse(cfg.run_request(self.runs[0]).exists())
        self.assertFalse(self.stores[str(self.repos[0])].show("b-1").metadata)

    def test_stop_targets_the_observed_run_even_when_a_newer_run_exists(self):
        repo = self.repos[0]
        cfg = self.dash.env.config
        manifest(cfg, "successor", "b-1", T + 150, repo=str(repo), state=RunState.RUNNING)
        code, out = self.dash.writes.post("stop", {"project": loop_key(repo), "bead": "b-1", "run": self.runs[0]})
        self.assertEqual((code, out["ok"]), (200, True))
        self.assertTrue(cfg.run_request(self.runs[0]).exists())
        self.assertFalse(cfg.run_request("successor").exists())

    def test_old_command_without_observed_run_is_a_bad_body(self):
        code, _ = self.dash.writes.post("stop", {"project": loop_key(self.repos[0]), "bead": "b-1"})
        self.assertEqual(code, 400)
