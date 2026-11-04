"""The owner audit has one shared path and preserves the exact JSONL row across readers."""
import json
import sys
import tempfile
from pathlib import Path

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.profile_changes import ProfileChange
from taskloop.contracts.wire import dump
from taskloop.stores.real import real_stores


class ProfileAudit(Case):
    def test_missing_audit_is_empty_and_one_append_is_one_shared_json_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = ConfigDir(tmp)
            writer, reader = real_stores(cfg), real_stores(cfg)
            assert reader.profile_changes.read_from().items == []
            assert not cfg.profile_changes().exists()
            row = ProfileChange(t=1000.0, owner_text='Denis: "approved" 2026-11-02', repo="/repo", branch="topic",
                                tip="tip", base="base", diff_sha="sha256", pid=42)
            writer.profile_changes.append(row)
            assert cfg.profile_changes() == Path(tmp) / "profile-changes.jsonl"
            lines = cfg.profile_changes().read_text().splitlines()
            assert len(lines) == 1
            assert json.loads(lines[0]) == dump(row)
            assert set(json.loads(lines[0])) == {"t", "owner_text", "repo", "branch", "tip", "base", "diff_sha", "pid"}
            assert [item.rec for item in reader.profile_changes.read_from().items] == [row]
