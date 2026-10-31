"""The factory runs detached processes; source must never install OS service definitions."""
import unittest
from pathlib import Path


class NoOsServices(unittest.TestCase):
    def test_source_contains_no_service_installation_vocabulary(self):
        root = Path(__file__).resolve().parents[2] / "src"
        forbidden = ("LaunchAgents", "launchctl", "crontab", "systemd", "LaunchDaemons")
        violations = []
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in (".py", ".plist", ".service", ".timer"):
                continue
            text = path.read_text(encoding="utf-8")
            if path.suffix in (".plist", ".service", ".timer") or any(word in text for word in forbidden):
                violations.append(str(path.relative_to(root)))
        self.assertEqual(violations, [])
