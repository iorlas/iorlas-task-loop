"""Look kernel moves preserve bindings and preflight unsupported forms before writing."""
import sys

import move_look_kernel as move
import pytest


def test_bindings_and_rerun():
    text = ('"""Example."""\n'
            'from taskloop.adapters import bdcreate, beadtools\n'
            'from taskloop.adapters' + '.bdcreate import create_checked as create\n')
    result, errors = move.rewrite(text)
    assert not errors
    assert result.startswith('"""Example."""\n')
    assert 'from tlkernel import bdcreate as bdcreate' in result
    assert 'from taskloop.adapters import beadtools' in result
    assert 'from tlkernel.bdcreate import create_checked as create' in result
    assert move.rewrite(result) == (result, [])


def test_preflight_rejects_unsupported_forms(tmp_path):
    source = tmp_path / ('src/taskloop/adapters/' + 'bdcreate.py')
    source.parent.mkdir(parents=True)
    source.write_text('import taskloop.adapters' + '.bdcreate\n')
    outputs, moves, errors = move.plan(tmp_path)
    assert any('unsupported dotted import' in e for e in errors)
    assert source.read_text() == 'import taskloop.adapters' + '.bdcreate\n'
    assert len(moves) == 1
    assert source in outputs


def test_parent_alias_and_unsupported_inline_import():
    result, errors = move.rewrite('from taskloop.adapters import bdcreate as create\n')
    assert not errors
    assert result == 'from tlkernel import bdcreate as create\n'
    for text in ('from taskloop.adapters import *\n',
                 'if True: from taskloop.adapters import bdcreate\n',
                 'value = adapters.bdcreate\n'):
        assert move.rewrite(text)[1]


def test_main_moves_and_rewrites_once(tmp_path, monkeypatch):
    source = tmp_path / ('src/taskloop/adapters/' + 'bdcreate.py')
    source.parent.mkdir(parents=True)
    source.write_text('"""Checked creation."""\n')
    consumer = tmp_path / 'tests/test_create.py'
    consumer.parent.mkdir()
    consumer.write_text('from taskloop.adapters import bdcreate\n')
    monkeypatch.setattr(sys, 'argv', ['move_look_kernel', '--root', str(tmp_path)])
    move.main()
    target = tmp_path / 'packages/kernel/src/tlkernel/bdcreate.py'
    assert target.read_text() == '"""Checked creation."""\n'
    assert not source.exists()
    assert consumer.read_text() == 'from tlkernel import bdcreate as bdcreate\n'
    assert move.plan(tmp_path) == ({}, {}, [])
    consumer.write_text('import taskloop.adapters' + '.bdcreate\n')
    with pytest.raises(SystemExit, match='No files written'):
        move.main()
    assert target.exists()
    assert consumer.read_text() == 'import taskloop.adapters' + '.bdcreate\n'
