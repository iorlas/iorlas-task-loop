"""Bootstrap cleanup is conservative and rerunnable on scratch files."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('drop_paths', Path(__file__).resolve().parents[2] / 'dev/drop_paths_bootstrap.py')
assert SPEC is not None and SPEC.loader is not None
drop = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(drop)


def test_plan_is_conservative_and_rerunnable(workdir):
    samples = {
        'test_plain.py': 'import support.paths  # noqa: F401 trailing\nx = 1\n',
        'test_pair.py': 'import sys\nfrom pathlib import Path\n\n' + drop.PREAMBLE + '\nimport support.paths\n',
        'test_used.py': 'import support.paths\nx = support.paths.ROOT\n',
        'test_other.py': 'import support.paths\nx = support.other.VALUE\n',
        'test_alias.py': 'import support.paths as bootstrap\n',
        'test_inline.py': 'import support.paths; x = 1\n',
        'test_live.py': 'import sys\nfrom pathlib import Path\n' + drop.PREAMBLE + '\nimport support.paths\nx = Path.cwd()\n',
        'conftest.py': 'import support.paths\n',
        'support/helper.py': 'import support.paths\n',
    }
    for name, text in samples.items():
        path = workdir / 'tests' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    edits, reports = drop.plan(workdir, [])
    assert {p.name for p, _ in edits} == {'test_plain.py', 'test_pair.py', 'test_live.py'}
    assert len(reports) == 7
    for path, text in edits:
        path.write_text(text)
    assert (workdir / 'tests/test_plain.py').read_text() == 'x = 1\n'
    assert (workdir / 'tests/test_pair.py').read_text() == 'import sys\nfrom pathlib import Path\n'
    assert drop.PREAMBLE in (workdir / 'tests/test_live.py').read_text()
    assert drop.plan(workdir, [])[0] == []
    bad = workdir / 'tests/test_bad.py'
    bad.write_text('def broken(\n')
    try:
        drop.plan(workdir, [])
    except SyntaxError:
        pass
    else:
        raise AssertionError('preflight accepted invalid Python')
