"""The retired session index folder: doctor names it as removable legacy, never deletes it, and no source reads it."""
from pathlib import Path

from support.case import Case
from support.tmpdir import TemporaryDirectory

from taskloop.app.doctor import setup_checks
from tlkernel.env import Env

SRC = Path(__file__).resolve().parents[2] / "src" / "taskloop"


class LegacySessions(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.env = Env({"HOME": tmp.name, "XDG_CONFIG_HOME": str(self.home / ".config")})
        self.folder = self.home / ".config" / "task-loop" / "sessions"

    def test_no_folder_no_line(self):
        assert setup_checks.legacy_line(self.folder.parent) == ""

    def test_the_folder_is_named_as_legacy_and_left_alone(self):
        self.folder.mkdir(parents=True)
        (self.folder / "a.json").write_text("{}")
        (self.folder / "b.json").write_text("{}")
        line = setup_checks.legacy_line(self.folder.parent)
        assert line.startswith("legacy: ") and "(2 files)" in line and "nothing reads it" in line
        assert sorted(p.name for p in self.folder.iterdir()) == ["a.json", "b.json"]

    def test_no_source_names_the_folder_any_more(self):
        named = [p.name for p in SRC.rglob("*.py") if '/ "sessions"' in p.read_text(encoding="utf-8")]
        assert sorted(named) == ["setup_checks.py"]  # doctor calls it legacy
        named = [p.name for p in SRC.rglob("*.py") if "SessionStore" in p.read_text(encoding="utf-8")]
        assert named == []
