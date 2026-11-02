"""The owner audit has one shared path and preserves the exact JSONL row across readers."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.profile_changes import ProfileChange
from taskloop.contracts.wire import dump
from taskloop.stores.real import real_stores


class ProfileAudit(unittest.TestCase):
    def test_missing_audit_is_empty_and_one_append_is_one_shared_json_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = ConfigDir(tmp)
            writer, reader = real_stores(cfg), real_stores(cfg)
            self.assertEqual(reader.profile_changes.read_from().items, [])
            self.assertFalse(cfg.profile_changes().exists())
            row = ProfileChange(t=1000.0, owner_text='Denis: "approved" 2026-11-02', repo="/repo", branch="topic",
                                tip="tip", base="base", diff_sha="sha256", pid=42)
            writer.profile_changes.append(row)
            self.assertEqual(cfg.profile_changes(), Path(tmp) / "profile-changes.jsonl")
            lines = cfg.profile_changes().read_text().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0]), dump(row))
            self.assertEqual(set(json.loads(lines[0])), {"t", "owner_text", "repo", "branch", "tip", "base", "diff_sha", "pid"})
            self.assertEqual([item.rec for item in reader.profile_changes.read_from().items], [row])
