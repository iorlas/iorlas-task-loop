"""Gate carve preflights mixed imports, patch strings and reruns without git."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("carve_gate", Path(__file__).resolve().parents[2] / "dev/carve_gate.py")
assert SPEC is not None and SPEC.loader is not None
carve = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(carve)


def test_mixed_multiline_import_preserves_step_aliases_and_patch_targets():
    old_app = "taskloop" + ".app.checks"
    old_domain = "taskloop" + ".domain.checks"
    source = ('def f():\n    from __APP__ import (\n'
              '        runner as r, step, evidence,\n    )  # noqa: F401\n'
              '    patch("__APP__.runner.Checker")\n'
              '    patch("__APP__.step.StageChecks")\n'
              '    from __DOMAIN__.cmd import matchers\n').replace("__APP__", old_app).replace("__DOMAIN__", old_domain)
    moved, errors = carve.rewrite(source)
    assert errors == []
    assert 'from tlgate import runner as r, evidence' in moved
    assert 'from taskloop.app.checks import step' in moved
    assert '"tlgate.runner.Checker"' in moved
    assert '"taskloop.app.checks.step.StageChecks"' in moved
    assert 'from tlgate.domain.cmd import matchers' in moved
    assert carve.rewrite(moved) == (moved, [])


def test_parent_domain_binding_is_reported_before_any_write():
    assert carve.rewrite('from taskloop.domain import checks as c\n')[1]


def test_plan_is_rerunnable_and_rejects_conflicting_destination(tmp_path):
    app = tmp_path / 'src/taskloop/app/checks'
    app.mkdir(parents=True)
    for name in ('__init__', 'step', 'runner'):
        (app / f'{name}.py').write_text('')
    dest = tmp_path / 'packages/gate/src/tlgate/runner.py'
    moves, _, errors = carve.plan(tmp_path)
    assert not errors
    assert moves == {app / 'runner.py': dest}
    dest.parent.mkdir(parents=True)
    dest.write_text('existing')
    assert carve.plan(tmp_path)[2]
    (app / 'runner.py').unlink()
    assert carve.plan(tmp_path) == ({}, [], [])
