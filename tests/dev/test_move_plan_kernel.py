"""Plan kernel moves preserve aliases and abort before unsupported imports write."""
import ast

import move_plan_kernel as move


def test_bindings_and_rerun():
    text = ('"""Example."""\n'
            'from taskloop.adapters import bdids\n'
            'from taskloop.domain.beads import matchers as acnames\n'
            'from taskloop.app.asks.intake import HINT, Intake\n'
            'value = intake.OVERRIDE\n')
    result, errors = move.rewrite(text)
    assert not errors
    assert result.startswith('"""Example."""\n')
    assert 'from tlkernel import bdids as bdids' in result
    assert 'from tlkernel import beadmatchers as acnames' in result
    assert 'from tlkernel.ownerkeys import HINT' in result
    assert 'from taskloop.app.asks.intake import Intake' in result
    assert 'value = OVERRIDE' in result
    assert move.rewrite(result) == (result, [])


def test_preflight_does_not_accept_plain_dotted_imports(tmp_path):
    source = tmp_path / 'packages/kernel/src/tlkernel/bdids.py'
    source.parent.mkdir(parents=True)
    source.write_text('import taskloop.adapters' + '.bdids\n')
    _, _, errors = move.plan(tmp_path)
    assert any('unsupported dotted import' in e for e in errors)
    assert source.exists()


def test_intake_does_not_reexport_constants():
    text = '"""Intake."""\nfrom typing import Final\nHINT: Final = "owner_hint"\nx = HINT\n'
    result = move.intake_keys(text)
    assert 'from tlkernel import ownerkeys' in result
    assert 'x = ownerkeys.HINT' in result
    assert not any(isinstance(n, ast.Name) and n.id in move.KEYS for n in ast.walk(ast.parse(result)))
    assert move.intake_keys(result) == result
