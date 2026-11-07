"""The close's storm banner is narrated through its supplied port."""
from types import SimpleNamespace
from unittest.mock import Mock

from support.pipeline_ports import FakeNarrate

from taskloop.app.pipeline.closing_decide import Decide
from taskloop.domain import outcome as oc
from tlkernel.kinds import Kind


def test_storm_narrates_banner_through_port(monkeypatch):
    host = Mock(dry=False, bead='t-1')
    host.clock.now.return_value = 1000.0
    narrator = FakeNarrate()
    trip = SimpleNamespace(fingerprint='fp', beads=['t-1', 't-2'], t=900.0)
    monkeypatch.setattr('taskloop.app.pipeline.closing_decide.storm.storm_trip', lambda *args: trip)
    monkeypatch.setattr('taskloop.app.pipeline.closing_decide.storm.banner', lambda *args: 'storm banner')
    write = Mock(return_value=True)
    monkeypatch.setattr('taskloop.app.pipeline.closing_decide.storm_file.write_storm', write)
    monkeypatch.setattr('taskloop.app.pipeline.closing_decide.storm_file.storm_path', lambda *args: 'storm')
    monkeypatch.setattr(Decide, 'repo_id', lambda self: 'repo')
    done = oc.make(Kind.FAULT_INFRA, 'disk full')
    Decide(host, narrator).storm([], done.kind, done, done.detail)
    assert narrator.notes == ['storm banner']
    host.warn.assert_called_once_with('storm banner')
    assert host.storm == 'storm banner'
