"""The Engine's facts and ports against the fake that stands in for them (tests/support/facts.py): the same probes on both leave the same
observations, and a fake that drops a verb or lies about a fact fails them (the mutation tests), so a stage test on the fake is only as
good as this file."""
import dataclasses
from pathlib import Path

import pytest
from support.check_host import FakeCheckHost
from support.engine_case import EngineTest
from support.facts import FakeRepoKey, fake_facts
from support.host_conformance import missing
from support.who import who

from taskloop.stores.runports import RunPorts
from tlkernel import stagefacts as sf

PROTOCOLS = {"steps": sf.StepBook, "log": sf.Narrate, "checklog": sf.CheckLogPort, "checkpoints": sf.CheckpointsPort,
             "checker": sf.CheckerPort, "repo": sf.RepoKey}


def probe(facts: sf.RunFacts, ports: RunPorts) -> dict[str, object]:
    """What a stage can observe through the facts and ports, as comparable values."""
    first = ports.steps.begin("plan", "probe")
    id_open = ports.steps.id
    noted, warned = ports.log.note("a"), ports.log.warn("b")
    ports.steps.outcome("ok")
    ports.steps.end("ok")
    return {
        "fact_types": {f.name: type(getattr(facts, f.name)).__name__ for f in dataclasses.fields(facts)},
        "step_number_then_id": (first, id_open),
        "step_closed": ports.steps.id,
        "log_ids_rise": warned > noted,
        "repo_stable": ports.repo.key() == ports.repo.key() != "",
        "checkpoint_before_a_save": ports.checkpoints.read() is None,
        "applied_before": ports.checkpoints.applied(),
        "clock_moves_forward": ports.clock.monotonic() >= 0,
    }


class FactsContract(EngineTest):
    def hosts(self):
        real = self.checks_engine()
        return real, fake_facts(Path(self.tmp.name), cfg=real.cfg)

    def test_the_engine_s_facts_are_its_own_values_and_frozen(self):
        e = self.checks_engine()
        assert (e.facts.bead, e.facts.wt, e.facts.run_id, e.facts.cfg, e.facts.claim) == (e.bead, e.wt, e.run_id, e.cfg, e.claim)
        assert (e.facts.run_dir, e.facts.task_dir, e.facts.evidence_dir) == (Path(e.run_dir), Path(e.task_dir), Path(e.evidence_dir))
        assert e.ports.log is e.log and e.ports.steps is e.steps and e.ports.checker is e.checker and e.ports.stores is e.stores
        with pytest.raises(dataclasses.FrozenInstanceError):
            e.facts.run_id = "x"  # type: ignore[misc]

    def test_every_port_protocol_member_is_on_the_engine_s_port_and_on_the_fake(self):
        e = self.checks_engine()
        _, fake = fake_facts(Path(self.tmp.name), cfg=e.cfg)
        for name, protocol in PROTOCOLS.items():
            assert missing(getattr(e.ports, name), protocol) == [], f"engine {name}"
            assert missing(getattr(fake, name), protocol) == [], f"fake {name}"

    def test_the_same_probes_give_the_same_observations_on_the_engine_and_the_fake(self):
        e = self.checks_engine()
        facts, ports = fake_facts(Path(self.tmp.name), cfg=e.cfg)
        assert probe(facts, ports) == probe(e.facts, e.ports)

    def test_the_engine_s_repo_key_is_the_one_ask_flow_memoises(self):
        e = self.checks_engine()
        key = e.ports.repo.key()
        assert key and e.artifact_repo == key
        e.artifact_repo = "set-by-ask-flow"
        assert e.ports.repo.key() == "set-by-ask-flow"

    def test_a_fake_that_lies_about_the_repo_key_fails_the_probes(self):
        e = self.checks_engine()
        facts, ports = fake_facts(Path(self.tmp.name), cfg=e.cfg)
        seq = iter(range(100))
        liar = dataclasses.replace(ports, repo=type("Liar", (), {"key": lambda self: str(next(seq))})())
        assert probe(facts, liar) != probe(e.facts, e.ports)

    def test_a_fake_that_drops_a_verb_fails_the_protocol_check(self):
        _, ports = fake_facts(Path(self.tmp.name))

        class NoMove:
            id = ""
            begin = end = outcome = ports.steps.begin

        assert missing(NoMove(), sf.StepBook) == ["move"]
        assert FakeRepoKey("k").key() == "k"


class CheckHostOnFacts(EngineTest):
    def test_the_fake_check_host_is_a_view_of_its_facts_and_ports(self):
        host = FakeCheckHost(self.wt, self.checks_engine().cfg, who().config)
        f, p = host.facts, host.ports
        assert (host.bead, host.wt, host.cfg, host.home, host.run_id, host.run_dir) == (f.bead, f.wt, f.cfg, f.home, f.run_id, f.run_dir)
        assert host.log is p.log and host.steps is p.steps and host.checklog is p.checklog and host.stores is p.stores
        assert host.env is p.env and host.spawner is p.spawner and host.git is p.git and host.clock is p.clock
