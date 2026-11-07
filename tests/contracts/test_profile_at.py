"""The kernel owns profile decoding, source resolution and diagnostic read policies."""
import io
import json
from unittest import mock

import pytest

from tlkernel import config, profile_at
from tlkernel.gitport import Git
from tlkernel.slots import NotARepo, SlotGitError


def test_typed_working_profile_and_existing_file_have_distinct_absence_policies(tmp_path):
    assert profile_at.typed_in(tmp_path) == config.RepoProfile()
    path = tmp_path / profile_at.FILE
    with pytest.raises(FileNotFoundError):
        profile_at.typed_file(path)
    path.write_text('{"slots": {"count": 3}}')
    assert profile_at.typed_in(tmp_path).slots.count == 3
    assert profile_at.typed_file(path).slots.count == 3
    path.write_text('[]')
    with pytest.raises(ValueError, match="the profile must be a JSON object"):
        profile_at.typed_in(tmp_path)
    assert profile_at.typed_file(path) == config.RepoProfile()


def test_parse_preserves_json_errors_config_errors_and_falsey_defaults():
    with pytest.raises(json.JSONDecodeError):
        profile_at.parse('{')
    with pytest.raises(config.ConfigError, match="cuont"):
        profile_at.parse('{"slots": {"cuont": 3}}')
    for text in ('null', 'false', '0', '[]', '{}'):
        assert profile_at.parse(text) == config.RepoProfile()


def test_typed_accessor_reports_retired_keys_once(tmp_path, monkeypatch):
    monkeypatch.setattr(config, '_SAID', set())
    (tmp_path / profile_at.FILE).write_text('{"engine": {"check_idle_min": 4}}')
    out = io.StringIO()
    profile_at.typed_in(tmp_path, say_to=out)
    profile_at.typed_in(tmp_path, say_to=out)
    assert out.getvalue() == 'task-loop: .task-loop.json: engine.check_idle_min is retired and ignored; safe to delete\n'


@pytest.mark.parametrize('text, expected', [
    ('{', 'origin/main'), ('[]', 'origin/main'),
    ('{"engine": {"base": ""}}', 'origin/main'),
    ('{"engine": {"base": 3}}', 'origin/main'),
    ('{"engine": {"base": "upstream/dev", "unknown": true}}', 'upstream/dev'),
])
def test_base_name_uses_only_the_unvalidated_hint(tmp_path, text, expected):
    (tmp_path / profile_at.FILE).write_text(text)
    assert profile_at.base_name(tmp_path) == expected


def test_working_engine_keeps_missing_file_and_json_diagnostics(tmp_path):
    with pytest.raises(SystemExit) as missing:
        profile_at.working_engine(str(tmp_path), profile_at.typed)
    assert str(missing.value) == f'tl check: cannot read {tmp_path / profile_at.FILE}: no such file'
    (tmp_path / profile_at.FILE).write_text('[]')
    with pytest.raises(SystemExit) as invalid:
        profile_at.working_engine(str(tmp_path), profile_at.typed)
    assert str(invalid.value).endswith(': the profile must be a JSON object')


def test_source_pins_the_base_and_never_falls_back_for_a_bad_committed_profile(tmp_path):
    git = mock.create_autospec(Git, instance=True)
    (tmp_path / profile_at.FILE).write_text('{"slots": {"count": 9}}')
    git.rev_parse.return_value = 'abc123'
    git.show.return_value = '{"slots": {"count": 2}}'
    assert profile_at.source(git, str(tmp_path), 'origin/dev') == ({'slots': {'count': 2}}, 'abc123')
    git.rev_parse.assert_called_with(str(tmp_path), 'origin/dev^{commit}')
    git.show.return_value = '{'
    with pytest.raises(config.ProfileReadError) as bad:
        profile_at.source(git, str(tmp_path), 'origin/dev')
    assert str(tmp_path / profile_at.FILE) in str(bad.value)
    assert 'abc123' in str(bad.value)
    git.show.side_effect = SlotGitError('read failed')
    git.ls_tree.return_value = []
    assert profile_at.source(git, str(tmp_path), 'origin/dev') == ({}, 'abc123')
    git.rev_parse.side_effect = NotARepo('not initialized')
    assert profile_at.source(git, str(tmp_path), 'origin/dev') == ({'slots': {'count': 9}}, '')
    (tmp_path / profile_at.FILE).write_text('{')
    with pytest.raises(config.ProfileReadError):
        profile_at.source(git, str(tmp_path), None)
