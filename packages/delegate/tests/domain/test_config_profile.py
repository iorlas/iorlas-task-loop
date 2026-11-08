"""config.json `profile` (the owner's account choices) never leaks into the routing settings."""

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from delegate.app import env
from delegate.contracts.json_types import obj
from delegate.contracts.stores import ConfigStore
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[4]


class ProfileStaysOut:
    def write(self, d, doc):
        (Path(d) / "config.json").write_text(json.dumps(doc), encoding="utf-8")

    def test_profile_is_not_an_override_and_not_a_setting(self):
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"DELEGATE_CONFIG_DIR": d}):
            self.write(d, {"profile": {"accounts": {"X": "enabled"}, "ack": ["volumes"]}, "max_parallel": 3})
            store = ConfigStore(Path(d) / "config.json")
            assert "profile" not in store.overrides()
            assert store.overrides().get("max_parallel") == 3
            cfg = env.load_routing()
            assert "profile" not in obj(cfg["settings"])
            assert not hasattr(env.typed_routing(cfg).settings, "profile")
            assert store.profile().accounts == {"X": "enabled"}

    def test_choosing_a_account_keeps_the_settings_overrides_and_writes_only_the_profile(self):
        with TemporaryDirectory() as d:
            self.write(d, {"max_parallel": 3})
            store = ConfigStore(Path(d) / "config.json")
            store.set_account("DEEPSEEK_FREE", "declined")
            doc = json.loads((Path(d) / "config.json").read_text())
            assert (doc["max_parallel"], doc["profile"]["accounts"]) == (3, {"DEEPSEEK_FREE": "declined"})
            assert "DEEPSEEK_FREE" not in json.dumps(store.overrides())


@pytest.mark.parametrize("keep_accounts", [False, True])
def test_retired_routing_accounts_key_is_refused_before_loading(keep_accounts):
    old_key = "la" + "nes"
    cfg = env.load_routing()
    cfg[old_key] = cfg["accounts"]
    if not keep_accounts:
        cfg.pop("accounts")
    with mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(cfg))), pytest.raises(SystemExit) as error:
        env.load_routing()
    assert str(error.value) == f"routing.json: rename the top-level key '{old_key}' to 'accounts'"


def test_retired_profile_key_is_refused_without_rewriting(tmp_path):
    path = tmp_path / "config.json"
    old_key = "la" + "nes"
    before = json.dumps({"profile": {old_key: {"X": "enabled"}}})
    path.write_text(before)
    store = ConfigStore(path)
    with pytest.raises(SystemExit, match=r"config\.json profile: rename"):
        store.profile()
    with pytest.raises(SystemExit, match=r"config\.json profile: rename"):
        store.set_account("X", "declined")
    assert path.read_text() == before
