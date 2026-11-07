"""Work carve preserves bindings and rejects unsafe rewrites before moving files."""
import carve_work as carve


def test_parent_bindings_aliases_and_patch_targets():
    source = ('from taskloop.domain import work as w\n'
              'from taskloop.domain' + '.review import findings\n'
              'from taskloop.app' + '.review.link_check import LinkCheck\n'
              'patch("taskloop.app' + '.review.link_check.LinkCheck")\n')
    result, errors = carve.rewrite(source)
    assert not errors
    assert 'from tlwork import work as w' in result
    assert 'from tlwork.review import findings' in result
    assert 'patch("tlwork.review.link_check.LinkCheck")' in result
    assert carve.rewrite(result) == (result, [])


def test_unsupported_bindings_are_preflight_errors():
    assert carve.rewrite('import taskloop.app' + '.review.host\n')[1]
    assert carve.rewrite('from taskloop.domain import work, plan\n')[1]


def test_move_collision_and_rerun(tmp_path):
    source = tmp_path / 'src/taskloop/app' / 'review/host.py'
    source.parent.mkdir(parents=True)
    source.write_text('')
    dest = tmp_path / 'packages/work/src/tlwork/review/host.py'
    assert carve.plan(tmp_path)[0] == {source: dest}
    dest.parent.mkdir(parents=True)
    dest.write_text('')
    assert carve.plan(tmp_path)[2]
    source.unlink()
    assert carve.plan(tmp_path) == ({}, [], [])
