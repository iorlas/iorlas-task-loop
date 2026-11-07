"""config.json `profile` (the owner's lane choices) never leaks into the routing settings."""

import json
import os
from pathlib import Path
from unittest import mock

from delegate.app import env
from delegate.contracts.json_types import obj
from delegate.contracts.stores import ConfigStore
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]


class ProfileStaysOut:
    def write(self, d, doc):
        (Path(d) / "config.json").write_text(json.dumps(doc), encoding="utf-8")

    def test_profile_is_not_an_override_and_not_a_setting(self):
        with TemporaryDirectory() as d, mock.patch.dict(os.environ, {"DELEGATE_CONFIG_DIR": d}):
            self.write(d, {"profile": {"lanes": {"X": "enabled"}, "ack": ["volumes"]}, "max_parallel": 3})
            store = ConfigStore(Path(d) / "config.json")
            assert "profile" not in store.overrides()
            assert store.overrides().get("max_parallel") == 3
            cfg = env.load_routing()
            assert "profile" not in obj(cfg["settings"])
            assert not hasattr(env.typed_routing(cfg).settings, "profile")
            assert store.profile().lanes == {"X": "enabled"}

    def test_choosing_a_lane_keeps_the_settings_overrides_and_writes_only_the_profile(self):
        with TemporaryDirectory() as d:
            self.write(d, {"max_parallel": 3})
            store = ConfigStore(Path(d) / "config.json")
            store.set_lane("DEEPSEEK_FREE", "declined")
            doc = json.loads((Path(d) / "config.json").read_text())
            assert (doc["max_parallel"], doc["profile"]["lanes"]) == (3, {"DEEPSEEK_FREE": "declined"})
            assert "DEEPSEEK_FREE" not in json.dumps(store.overrides())
