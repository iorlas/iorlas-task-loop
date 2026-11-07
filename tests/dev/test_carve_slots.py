"""Slots carve preflight rejects ambiguous imports before changing the tree."""
import importlib.util
import sys
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("carve_slots", Path(__file__).resolve().parents[2] / "dev/carve_slots.py")
assert SPEC is not None and SPEC.loader is not None
carve = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(carve)


def test_rewrite_imports_and_patch_strings():
    text = (f'from {carve.APP} import config as c, engine_lock\n'
            f'from {carve.APP}.pool import SlotPool\n'
            'from taskloop' '.domain.slot_liveness import Kind\n'
            'from taskloop' '.domain.slot_env import folders\n'
            f'patch("{carve.APP}.engine_lock.live")\n')
    moved, errors = carve.rewrite(text)
    assert not errors
    assert 'from tlslots import config as c, engine_lock' in moved
    assert 'from tlslots.pool import SlotPool' in moved
    assert 'from tlslots.liveness import Kind' in moved
    assert 'from tlslots.slot_env import folders' in moved
    assert 'patch("tlslots.engine_lock.live")' in moved


def test_unsupported_forms():
    for text in (f'from {carve.APP} import *', 'from taskloop.app import slots',
                 'from taskloop.domain import slot_liveness', 'from taskloop.domain import slot_env'):
        assert carve.rewrite(text)[1]


def test_plan_moves_init_and_domain_and_is_rerunnable(tmp_path, monkeypatch):
    app = tmp_path / 'src/taskloop/app/slots'
    app.mkdir(parents=True)
    (app / '__init__.py').write_text('"""Slots."""\n')
    (app / 'config.py').write_text(f'from {carve.APP} import pool\n')
    domain = tmp_path / 'src/taskloop/domain'
    domain.mkdir(exist_ok=True)
    for name in carve.DOMAINS:
        (domain / (name + '.py')).write_text('')
    moves, _edits, errors = carve.plan(tmp_path)
    assert not errors
    assert len(moves) == 4
    monkeypatch.setattr(sys, 'argv', ['carve_slots', '--root', str(tmp_path)])
    carve.main()
    assert not app.exists()
    assert (tmp_path / 'packages/slots/src/tlslots/config.py').read_text() == 'from tlslots import pool\n'
    carve.main()
    assert carve.plan(tmp_path) == ({}, [], [])


def test_preflight_reports_collision_without_writing(tmp_path):
    app = tmp_path / 'src/taskloop/app/slots'
    app.mkdir(parents=True)
    source = app / '__init__.py'
    source.write_text('old')
    target = tmp_path / 'packages/slots/src/tlslots'
    target.mkdir(parents=True)
    (target / '__init__.py').write_text('new')
    assert carve.plan(tmp_path)[2]
    assert source.read_text() == 'old'
    assert (target / '__init__.py').read_text() == 'new'
