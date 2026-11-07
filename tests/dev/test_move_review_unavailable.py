"""Review exception moves preserve bindings and preflight unsupported forms before writing."""
import sys

import move_review_unavailable as move
import pytest


def test_bindings_and_rerun():
    text = ('"""Example."""\n'
            'from tlwork.review import availability, routing\n'
            'from tlwork.review' + '.availability import ReviewUnavailable as unavailable\n')
    result, errors = move.rewrite(text)
    assert not errors
    assert result.startswith('"""Example."""\n')
    assert 'from tlkernel import reviewunavailable as availability' in result
    assert 'from tlwork.review import routing' in result
    assert 'from tlkernel.reviewunavailable import ReviewUnavailable as unavailable' in result
    assert move.rewrite(result) == (result, [])


def test_preflight_rejects_unsupported_forms(tmp_path):
    source = tmp_path / ('packages/work/src/tlwork/review/' + 'availability.py')
    source.parent.mkdir(parents=True)
    source.write_text('import tlwork.review' + '.availability\n')
    outputs, moves, errors = move.plan(tmp_path)
    assert any('unsupported dotted import' in e for e in errors)
    assert source.read_text() == 'import tlwork.review' + '.availability\n'
    assert len(moves) == 1
    assert source in outputs


def test_parent_alias_and_unsupported_inline_import():
    result, errors = move.rewrite('from tlwork.review import availability as create\n')
    assert not errors
    assert result == 'from tlkernel import reviewunavailable as create\n'
    for text in ('from tlwork.review import *\n',
                 'if True: from tlwork.review import availability\n',
                 'value = review.availability\n'):
        assert move.rewrite(text)[1]


def test_main_moves_and_rewrites_once(tmp_path, monkeypatch):
    source = tmp_path / ('packages/work/src/tlwork/review/' + 'availability.py')
    source.parent.mkdir(parents=True)
    source.write_text('"""Review availability."""\n')
    consumer = tmp_path / 'tests/test_create.py'
    consumer.parent.mkdir()
    consumer.write_text('from tlwork.review import availability\n')
    monkeypatch.setattr(sys, 'argv', ['move_review_unavailable', '--root', str(tmp_path)])
    move.main()
    target = tmp_path / 'packages/kernel/src/tlkernel/reviewunavailable.py'
    assert target.read_text() == '"""Review availability."""\n'
    assert not source.exists()
    assert consumer.read_text() == 'from tlkernel import reviewunavailable as availability\n'
    assert move.plan(tmp_path) == ({}, {}, [])
    consumer.write_text('import tlwork.review' + '.availability\n')
    with pytest.raises(SystemExit, match='No files written'):
        move.main()
    assert target.exists()
    assert consumer.read_text() == 'import tlwork.review' + '.availability\n'


def test_api_import_preserves_other_bindings():
    text = 'from tlwork.api import ReviewUnavailable as unavailable, Planner\n'
    result, errors = move.rewrite(text)
    assert not errors
    assert result == ('from tlkernel.reviewunavailable import ReviewUnavailable as unavailable\n'
                      'from tlwork.api import Planner\n')
    assert move.rewrite(result) == (result, [])


def test_surface_loses_the_export_and_documented_paths_move():
    text = ('from tlwork.review' + '.availability import ReviewUnavailable\n'
            '__all__ = [\n    "ReviewUnavailable",\n    "Planner",\n]\n')
    result = move.remove_export(text)
    assert result == '__all__ = [\n    "Planner",\n]\n'
    assert move.remove_export(result) == result
    old = 'packages/work/src/tlwork/review/' + 'availability.py'
    assert move.references(old) == 'packages/kernel/src/tlkernel/reviewunavailable.py'
