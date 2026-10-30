"""The registry of exported variables (contracts/envvars.py): every TL_* / TASK_LOOP_* name the docs, SKILL.md, prompts and code say is
registered, and every registered name is used outside the registry. The environment is read only at the edge (contracts/env.py)."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts.envvars import NOT_VARIABLES, PREFIXES, EnvVar, registered

ROOT = Path(__file__).resolve().parents[2]
NAME = re.compile(r"\b(?:TL|TASK_LOOP)_[A-Z0-9_]*[A-Z0-9]_?\b")
TEXTS = (*(ROOT / "docs").rglob("*.md"), ROOT / "README.md", ROOT / "skills/task-loop/SKILL.md", ROOT / "skills/task-loop/tl.py")
CODE = tuple((ROOT / "src").rglob("*.py"))
# The edge modules: where the process environment is read or written (contracts/env.py owns os.environ; this list may only shrink).
ENV_EDGE = frozenset({"src/taskloop/contracts/env.py"})
# os.environ outside the edge today (none under taskloop or taskloop_dash;
# the dashboard takes its environment once, in taskloop_dash/cli/dash.py, through contracts/env).
ENV_ALLOWLIST: frozenset[str] = frozenset()


def mentioned(path: Path) -> set[str]:
    return set(NAME.findall(path.read_text(encoding="utf-8", errors="replace")))


class Registry(unittest.TestCase):
    def test_every_documented_name_is_registered(self):
        bad = {f"{p.relative_to(ROOT)}: {n}" for p in (*TEXTS, *CODE) for n in mentioned(p)
               if n not in NOT_VARIABLES and not registered(n) and not n.endswith("_") and n not in PREFIXES}
        self.assertFalse(bad, "names missing from contracts/envvars.py:\n" + "\n".join(sorted(bad)))

    def test_every_registered_name_is_used(self):
        reg = ROOT / "src/taskloop/contracts/envvars.py"
        text = "\n".join(p.read_text() for p in (*CODE, ROOT / "skills/task-loop/SKILL.md", *TEXTS) if p != reg)
        unused = [v.name for v in EnvVar if v.name not in text]
        self.assertEqual(unused, [])

    def test_gate_passed_is_no_variable(self):
        self.assertNotIn("TL_GATE_PASSED", EnvVar.__members__)
        said = [p for p in (*TEXTS, *CODE) if "TL_GATE_PASSED" in p.read_text(errors="replace")]
        self.assertEqual(said, [])


class EnvEdge(unittest.TestCase):
    def test_os_environ_only_at_the_edge(self):
        hits = {str(p.relative_to(ROOT)) for p in (*(ROOT / "src/taskloop").rglob("*.py"), *(ROOT / "src/taskloop_dash").rglob("*.py"))
                if re.search(r"\bos\.(environ|getenv|putenv)\b|from os import[^\n]*\benviron\b", p.read_text())}
        self.assertEqual(sorted(hits - ENV_EDGE - ENV_ALLOWLIST), [], "read the environment through taskloop.contracts.env")

    def test_the_allowlist_only_shrinks(self):
        self.assertEqual(ENV_ALLOWLIST, frozenset())
