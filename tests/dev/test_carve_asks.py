"""The asks carve rewrites bindings and refuses unsafe moves before writing."""
import ast
import sys

import carve_asks as carve


def tree(root, clash=False):
    app = root / 'src/taskloop/app/asks'
    app.mkdir(parents=True)
    (app / '__init__.py').write_text('"""Asks."""\n')
    (app / 'intake.py').write_text(f'from {carve.APP} import parks\n')
    if clash:
        (app / 'hold.py').write_text('"""Application hold."""\n')
    domain = root / 'src/taskloop/domain/asks'
    domain.mkdir(parents=True)
    (domain / '__init__.py').write_text('')
    for name in carve.DOMAINS:
        (domain / (name + '.py')).write_text('"""Domain rule."""\n')
    (domain.parent / 'timespec.py').write_text('')
    return app, domain


def test_imports_parent_bindings_aliases_and_patch_strings():
    text = (f'from {carve.APP}.intake import Intake\n'
            'from taskloop.app import asks as inbox, loop\n'
            'from taskloop.domain import asks, timespec as clock, look\n'
            'from taskloop' '.domain.asks import hold as h, similar\n'
            'from taskloop' '.domain.asks.matchers import words\n'
            f'patch("{carve.APP}.intake.Intake")\n')
    moved, errors = carve.rewrite(text)
    assert errors == []
    ast.parse(moved)
    assert 'from tlasks.intake import Intake' in moved
    assert 'import tlasks as inbox' in moved
    assert 'import tlasks as asks' in moved
    assert 'from tlasks import timespec as clock' in moved
    assert 'from taskloop.domain import look' in moved
    assert 'from tlasks import hold as h' in moved
    assert 'from tlasks.matchers import words' in moved
    assert 'patch("tlasks.intake.Intake")' in moved


def test_unsupported_bindings_are_errors():
    for text in (f'from {carve.APP} import *', f'import {carve.APP}.intake',
                 'if ready: from taskloop.app import asks'):
        assert carve.rewrite(text)[1]


def test_preflight_and_rerun(tmp_path, monkeypatch):
    app, domain = tree(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['carve_asks', '--root', str(tmp_path), '--preflight'])
    carve.main()
    assert app.is_dir() and domain.is_dir()
    monkeypatch.setattr(sys, 'argv', ['carve_asks', '--root', str(tmp_path)])
    carve.main()
    assert not app.exists() and not domain.exists()
    assert (tmp_path / 'packages/asks/src/tlasks/intake.py').read_text() == 'from tlasks import parks\n'
    carve.main()
    assert carve.plan(tmp_path) == ({}, [], [])


def test_rerun_preserves_historic_move_scripts_and_tests(tmp_path, monkeypatch):
    tree(tmp_path)
    historic = [tmp_path / 'dev/move_write_kernel.py',
                tmp_path / 'tests/dev/test_move_write_kernel.py']
    text = f'from {carve.APP} import parks\n'
    for path in historic:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    current = tmp_path / 'dev/current.py'
    current.write_text(text)
    monkeypatch.setattr(sys, 'argv', ['carve_asks', '--root', str(tmp_path)])
    carve.main()
    carve.main()
    assert all(path.read_text() == text for path in historic)
    assert current.read_text() == 'from tlasks import parks\n'
    assert carve.plan(tmp_path) == ({}, [], [])


def test_domain_collision_chooses_a_free_name(tmp_path, monkeypatch):
    app, _domain = tree(tmp_path, clash=True)
    (app / 'intake.py').write_text('from taskloop' '.domain.asks import hold\n')
    monkeypatch.setattr(sys, 'argv', ['carve_asks', '--root', str(tmp_path)])
    carve.main()
    target = tmp_path / 'packages/asks/src/tlasks'
    assert (target / 'hold.py').read_text() == '"""Application hold."""\n'
    assert (target / 'domain_hold.py').read_text() == '"""Domain rule."""\n'
    assert (target / 'intake.py').read_text() == 'from tlasks import domain_hold as hold\n'
    assert carve.plan(tmp_path) == ({}, [], [])


def test_existing_destination_and_domain_code_are_refused(tmp_path):
    app, domain = tree(tmp_path)
    target = tmp_path / 'packages/asks/src/tlasks'
    target.mkdir(parents=True)
    (target / '__init__.py').write_text('destination')
    (domain / '__init__.py').write_text('important = True\n')
    errors = carve.plan(tmp_path)[2]
    assert any('both source and target' in error for error in errors)
    assert any('cannot discard' in error for error in errors)
    assert (app / '__init__.py').exists()


def test_domain_collision_skips_occupied_prefixed_names(tmp_path, monkeypatch):
    app, _domain = tree(tmp_path, clash=True)
    (app / 'domain_hold.py').write_text('"""Another application module."""\n')
    monkeypatch.setattr(sys, 'argv', ['carve_asks', '--root', str(tmp_path)])
    carve.main()
    target = tmp_path / 'packages/asks/src/tlasks'
    assert (target / 'domain_domain_hold.py').read_text() == '"""Domain rule."""\n'
    assert carve.plan(tmp_path) == ({}, [], [])
