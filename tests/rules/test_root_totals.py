"""Root totals and Engine attribute inventory use source alone, with no stored baseline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from rules import root_ratchet


def test_totals_count_each_root_file_once(workdir):
    folder = workdir / "src/taskloop/cli"
    folder.mkdir(parents=True)
    (folder / "sample.py").write_text('''"""Ignored docstring."""
# Ignored comment.
def sample():
    if True:
        return 1
    return 0
''', encoding="utf-8")
    (folder / "empty.py").write_text('"""Only a docstring."""\n', encoding="utf-8")
    assert root_ratchet.totals(workdir) == {"files": 2, "sloc": 4, "branch": 1, "long_function": 0}


def test_engine_attributes_follow_bases_and_deduplicate(workdir):
    folder = workdir / "src/taskloop/app/run"
    folder.mkdir(parents=True)
    (folder / "fields.py").write_text('''class Fields:
    field: int
    def __init__(self):
        self.assigned = 1
''', encoding="utf-8")
    (folder / "engine.py").write_text('''from functools import cached_property
from .fields import Fields as Base
class Unrelated:
    excluded: int
class Engine(Base):
    field: int
    plain = 1
    def __init__(self):
        self.assigned, self.field = 2, 3
        del self.deleted
    @property
    def field(self):
        return 0
    @cached_property
    def cached(self):
        return 1
''', encoding="utf-8")
    assert root_ratchet.engine_attributes(workdir) == 3


def test_real_tree_has_root_code_and_engine_attributes():
    assert root_ratchet.engine_attributes() > 0 and root_ratchet.totals()["sloc"] > 0
