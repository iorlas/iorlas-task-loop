"""Engine rounds, standalone checks and delivery queries share a slot-independent receipt environment."""
from pathlib import Path
from unittest import mock

from support import procsim
from support.engine_case import EngineTest

from taskloop.app.checks import authorization
from taskloop.app.checks.cache import RunMemo
from taskloop.app.checks.execution import check_env
from taskloop.app.checks.runner import Checker, cached_gate
from taskloop.app.launch.check_host import CliHost
from taskloop.contracts.runkey import BaseSha
from taskloop.domain.checks.specs import gate_items
from taskloop.domain.slot_env import slot_env


class KeyedEnv(EngineTest):
    def engine(self, cmd="true", **settings):
        eng = self.checks_engine(checks=[{"id": "suite", "cmd": cmd, "run": "both", **settings}])
        eng.bead_env = slot_env(Path(self.tmp.name) / "state-a", "repo", "slot-a")
        return eng

    def cli(self, eng):
        bundle = mock.Mock(run="standalone", dir=eng.run_dir)
        return CliHost(eng.wt, eng.cfg, eng.stores, bundle=bundle, log=eng.log,
                       env=eng.env, spawner=eng.spawner, git=eng.git)

    def test_an_engine_receipt_hits_delivery_standalone_and_another_slot(self):
        seen = []
        cmd = procsim.fake("observe-slot-env", lambda cwd, env: (seen.append(dict(env)) or 0, ""))
        eng = self.engine(cmd)
        result = eng.run_checks({"checks": [], "files": []}, "round")[0]
        self.assertEqual(result.status, "passed")
        self.assertFalse(result.cached)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["TL_SLOT"], "slot-a")
        self.assertEqual(seen[0]["TMPDIR"], eng.bead_env["TMPDIR"])
        tree = eng.checkout.tree_hash()
        base = BaseSha(eng.git.rev_parse(str(eng.wt), eng.cfg.base))
        check = gate_items(eng.cfg)[0]
        memo = authorization.memo_for(eng.stores, eng.git, str(eng.wt), eng.cfg, tree, base, eng.env)
        self.assertEqual(memo.result(check), result)
        self.assertEqual(authorization.results(eng.stores, eng.git, str(eng.wt), eng.cfg, tree, base, eng.env),
                         {check.id: result})
        cli = self.cli(eng)
        self.assertEqual(cli.bead_env, check_env())
        self.assertEqual(Checker(cli)._memo(tree, base).result(check), result)
        self.assertTrue(Checker(cli).run_items([check])[0].cached)
        eng.bead_env = slot_env(Path(self.tmp.name) / "state-b", "repo", "slot-b")
        other = Checker(eng)
        self.assertEqual(other._memo(tree, base).result(check), result)
        self.assertTrue(other.run_items([check])[0].cached)
        self.assertEqual(len(seen), 1)

    def test_all_three_memo_construction_sites_produce_equal_keys(self):
        eng = self.engine(env={"MODE": "declared", "TL_SLOT": "declared-slot"})
        eng.run_checks({"checks": [], "files": []}, "round")
        tree = eng.checkout.tree_hash()
        base = BaseSha(eng.git.rev_parse(str(eng.wt), eng.cfg.base))
        check = gate_items(eng.cfg)[0]
        engine = eng.checker._memo(tree, base)
        delivery = authorization.memo_for(eng.stores, eng.git, str(eng.wt), eng.cfg, tree, base, eng.env)
        standalone = Checker(self.cli(eng))._memo(tree, base)
        memos = []

        def capture(*args):
            memo = RunMemo(*args)
            memos.append(memo)
            return memo

        with mock.patch("taskloop.app.checks.runner.RunMemo", side_effect=capture):
            self.assertTrue(cached_gate(eng.cfg, eng.git, str(eng.wt), eng.stores, eng.env, tree, None))
        self.assertEqual(len(memos), 1)
        key = engine.key(check)
        self.assertIsNotNone(key)
        for memo in (delivery, standalone, memos[0]):
            self.assertEqual(memo.key(check), key)
            self.assertNotEqual(memo.key(check.replace(env={"MODE": "changed", "TL_SLOT": "declared-slot"})), key)
            self.assertNotEqual(memo.key(check.replace(env={"MODE": "declared", "TL_SLOT": "changed-slot"})), key)

