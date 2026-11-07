"""Admission rules use observations and callbacks without real adapters."""
from dataclasses import dataclass, field

import pytest

from tlkernel.gitfacts import StatusRow
from tlkernel.ids import BeadId
from tlpipeline.api import admission, closeguard


@pytest.mark.parametrize('kind,reason,expected', [
    ('task', '', True), ('bug', 'done', True), ('epic', '', False),
    ('task', 'duplicate: another bead', False), (None, '', False),
])
def test_close_refusal(kind, reason, expected):
    why = closeguard.refusal(BeadId('t-1'), reason, kind,
        has_land=lambda: False, has_work=lambda: True, manual=lambda sha: sha)
    assert bool(why) is expected


def test_manual_land_precedes_existing_land():
    assert closeguard.refusal(BeadId('t-1'), 'manual-landed-with-sha:abc why', 'task',
        has_land=lambda: True, has_work=lambda: False, manual=lambda sha: 'checked ' + sha) == 'checked abc'


@pytest.mark.parametrize('park,allowed,claim_rc,expected', [
    ('parked', True, 0, 'parked'), ('', False, 0, 'held'),
    ('', True, 1, 'claimed by another session'), ('', True, 0, None),
])
def test_entry_order(park, allowed, claim_rc, expected):
    calls = []
    def admit():
        calls.append('admit')
        return allowed, 'reopened' if allowed else 'held'
    def claim():
        calls.append('claim')
        return claim_rc
    why = admission.enter(BeadId('t-1'), release_dead=lambda: calls.append('release'),
        parked=lambda: park, admit=admit, claim=claim, say=calls.append, taken=calls.append)
    assert why == expected
    assert calls[0] == 'release'
    if park:
        assert calls == ['release', 'TAKEN: parked']
    elif allowed:
        assert calls == ['release', 'admit', 't-1: reopened', 'claim']
    else:
        assert calls == ['release', 'admit', 'TAKEN: held']


@dataclass
class View:
    paths: list[StatusRow] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    def branch(self, d): return 'task/t-1'
    def toplevel(self, d): return d
    def status(self, d, all_untracked=False): return self.paths
    def rev_parse(self, d, rev): return 'tree'
    def say(self, text): self.lines.append(text)


@pytest.mark.parametrize('stage,green,land,expected', [
    ('close', True, False, 'close refused'), ('land', False, True, 'land refused'),
    ('land', True, False, ''), ('gate', False, False, ''),
])
def test_preview_refusals(stage, green, land, expected):
    view = View()
    why = admission.inspect(BeadId('t-1'), '/work', '/repo', git=view, printer=view,
        newest=lambda bead, repo: None, checkpoint=lambda: None, has_land=lambda: land,
        green_gate=lambda tree, planned: green, plan_deferred=True, requested=stage,
        fresh=False, force=False, continuous=False, dry=True)
    assert why.startswith(expected)
    assert ('refusals: none' in view.lines) is (not why)


def test_uncommitted_files_are_sorted_and_refused_before_gate():
    view = View(paths=[StatusRow(path='z', index='?', work='?'), StatusRow(path='a', index='?', work='?')])
    gates = []
    why = admission.inspect(BeadId('t-1'), '/work', '/repo', git=view, printer=view,
        newest=lambda bead, repo: None, checkpoint=lambda: None, has_land=lambda: False,
        green_gate=lambda tree, planned: bool(gates.append(tree)), plan_deferred=False, requested='land',
        fresh=False, force=False, continuous=False, dry=True)
    assert why == 'uncommitted work refused: use --force to allow a WIP commit'
    assert view.lines[-2:] == ['  a', '  z']
    assert gates == []
