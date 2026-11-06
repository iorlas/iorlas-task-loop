"""RunFacts and the ports (docs/design/facts.md, tl-e5t0.28): the types are frozen data and structural Protocols, and the fake that
stands in for an Engine satisfies every one of them."""
import dataclasses
import typing

import pytest
from support.facts import fake_facts
from support.host_conformance import missing

from taskloop.contracts import stagefacts as rf
from taskloop.stores.runports import RunPorts

PORT_PROTOCOLS = {
    "steps": rf.StepBook, "log": rf.Narrate, "checklog": rf.CheckLogPort, "checkpoints": rf.CheckpointsPort,
    "checker": rf.CheckerPort, "repo": rf.RepoKey,
}


def test_the_facts_are_frozen(workdir):
    facts, ports = fake_facts(workdir)
    with pytest.raises(dataclasses.FrozenInstanceError):
        facts.run_id = "other"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        ports.log = None  # type: ignore[misc]
    assert dataclasses.replace(facts, dry=True).dry and not facts.dry


def test_two_reads_of_the_facts_are_equal_and_the_fake_builds_them_complete(workdir):
    facts, _ = fake_facts(workdir)
    assert facts == dataclasses.replace(facts)
    assert {f.name for f in dataclasses.fields(facts)} == {
        "bead", "wt", "cfg", "home", "run_id", "run_dir", "task_dir", "brief_file", "evidence_dir", "repo", "dry", "fresh", "claim"}


@pytest.mark.parametrize("name", sorted(PORT_PROTOCOLS))
def test_each_fake_port_has_every_member_of_its_protocol(workdir, name):
    _, ports = fake_facts(workdir)
    assert missing(getattr(ports, name), PORT_PROTOCOLS[name]) == []


def test_ports_name_every_capability_of_the_design():
    assert {f.name for f in dataclasses.fields(RunPorts)} == {
        "clock", "env", "git", "spawner", "steps", "log", "checklog", "store", "stores", "checkpoints", "checker", "repo"}


def test_the_protocols_are_structural_not_classes_of_app():
    assert all(typing.is_protocol(p) for p in PORT_PROTOCOLS.values())
