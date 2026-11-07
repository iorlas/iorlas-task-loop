"""Write kernel moves preserve bindings and preflight unsupported forms before writing."""
import sys

import move_write_kernel as move
import pytest


def test_bindings_and_rerun():
    text = ('"""Example."""\n'
            'from taskloop.app.asks import trustroots, closing\n'
            'from taskloop.app.asks' + '.trustroots import refusal as create\n')
    result, errors = move.rewrite(text)
    assert not errors
    assert result.startswith('"""Example."""\n')
    assert 'from tlkernel import trustroots as trustroots' in result
    assert 'from taskloop.app.asks import closing' in result
    assert 'from tlkernel.trustroots import refusal as create' in result
    assert move.rewrite(result) == (result, [])


def test_preflight_rejects_unsupported_forms(tmp_path):
    source = tmp_path / ('src/taskloop/app/asks/' + 'trustroots.py')
    source.parent.mkdir(parents=True)
    source.write_text('import taskloop.app.asks' + '.trustroots\n')
    outputs, moves, errors = move.plan(tmp_path)
    assert any('unsupported dotted import' in e for e in errors)
    assert source.read_text() == 'import taskloop.app.asks' + '.trustroots\n'
    assert len(moves) == 1
    assert source in outputs


def test_parent_alias_and_unsupported_inline_import():
    result, errors = move.rewrite('from taskloop.app.asks import trustroots as create\n')
    assert not errors
    assert result == 'from tlkernel import trustroots as create\n'
    for text in ('from taskloop.app.asks import *\n',
                 'if True: from taskloop.app.asks import trustroots\n',
                 'value = asks.trustroots\n'):
        assert move.rewrite(text)[1]


def test_main_moves_and_rewrites_once(tmp_path, monkeypatch):
    source = tmp_path / ('src/taskloop/app/asks/' + 'trustroots.py')
    source.parent.mkdir(parents=True)
    source.write_text('"""Trust roots."""\n')
    consumer = tmp_path / 'tests/test_create.py'
    consumer.parent.mkdir()
    consumer.write_text('from taskloop.app.asks import trustroots\n')
    monkeypatch.setattr(sys, 'argv', ['move_write_kernel', '--root', str(tmp_path)])
    move.main()
    target = tmp_path / 'packages/kernel/src/tlkernel/trustroots.py'
    assert target.read_text() == '"""Trust roots."""\n'
    assert not source.exists()
    assert consumer.read_text() == 'from tlkernel import trustroots as trustroots\n'
    assert move.plan(tmp_path) == ({}, {}, [])
    consumer.write_text('import taskloop.app.asks' + '.trustroots\n')
    with pytest.raises(SystemExit, match='No files written'):
        move.main()
    assert target.exists()
    assert consumer.read_text() == 'import taskloop.app.asks' + '.trustroots\n'
