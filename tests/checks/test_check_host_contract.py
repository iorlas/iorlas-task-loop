"""FakeCheckHost (support/check_host.py) against the Engine: the same checks run on both leave the same results, the same log kinds,
the same environment in the check's process. A checks test that runs on the fake is only as good as this file."""
import json
from pathlib import Path

from support.check_host import FakeCheckHost
from support.engine_case import EngineTest
from support.who import who

from taskloop.app.run.engine import Engine
from tltestkit import procsim

ST = {"checks": [], "files": []}


def dump_env(cwd, env):
    return 0, json.dumps(dict(env), sort_keys=True)


DUMP = procsim.default("dump-env", dump_env)
RED = procsim.default("red-check", procsim.exits(1, "boom"))
CHECKS = [{"id": "g", "cmd": DUMP, "group": "static"}, {"id": "r", "cmd": RED, "group": "tests"}]


class HostContract(EngineTest):
    def hosts(self):
        """The same config on an Engine and on the fake; their run folders differ, so the second one is a run of its own."""
        real = self.checks_engine(checks=CHECKS)
        fake = FakeCheckHost(self.wt, real.cfg, who().config)
        return real, fake

    def seen(self, host):
        run = host.run_checks(ST, "s")
        out = (host.run_dir / next(c.log for c in run.results if c.id == "g")).read_text().strip().splitlines()[-1]
        env = json.loads(out)
        return run, {k: v.replace(str(host.run_dir), "<run>").replace(host.run_id, "<id>") for k, v in env.items()}

    @staticmethod
    def shape(run):
        return [(c.id, c.status, c.exit) for c in run.results]

    def test_the_same_checks_give_the_same_results_and_the_same_process_env(self):
        real, fake = self.hosts()
        run_r, env_r = self.seen(real)
        run_f, env_f = self.seen(fake)
        assert self.shape(run_f) == self.shape(run_r)
        assert sorted(env_f) == sorted(env_r)
        assert env_f == env_r

    def test_the_log_rows_are_the_same_kinds_in_the_same_order(self):
        real, fake = self.hosts()
        real.run_checks(ST, "s")
        fake.run_checks(ST, "s")
        kinds_r = [r["kind"] for r in (json.loads(x) for x in real.log_path.read_text().splitlines())]
        assert [r["kind"] for r in fake.records()] == kinds_r

    def test_the_host_facts_a_check_reads_agree(self):
        real, fake = self.hosts()
        assert fake.MARKERS == Engine.MARKERS
        assert dict(fake.bead_env) == dict(real.bead_env)
        assert fake.cfg == real.cfg
        assert (fake.killed, fake.wall_hit, str(fake.wt)) == (real.killed, real.wall_hit, str(real.wt))
        assert fake.checkout.tree_hash() == real.checkout.tree_hash()
        assert Path(fake.wt) == Path(real.wt)
