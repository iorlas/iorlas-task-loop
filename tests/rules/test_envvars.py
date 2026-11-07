"""The registry of exported variables (contracts/envvars.py): every TL_* / TASK_LOOP_* name the docs, SKILL.md, prompts and code say is
registered, and every registered name is used outside the registry. The environment is read only at the edge (contracts/env.py)."""
import re
import sys
from pathlib import Path

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tlkernel.envvars import NOT_VARIABLES, PREFIXES, EnvVar, registered

ROOT = Path(__file__).resolve().parents[2]
NAME = re.compile(r"\b(?:TL|TASK_LOOP)_[A-Z0-9_]*[A-Z0-9]_?\b")
TEXTS = (*(ROOT / "docs").rglob("*.md"), ROOT / "README.md", ROOT / "skills/task-loop/SKILL.md", ROOT / "skills/task-loop/tl.py")
CODE = (*(ROOT / "src").rglob("*.py"), *(ROOT / "packages/kernel/src").rglob("*.py"))
# The edge modules: where the process environment is read or written (contracts/env.py owns os.environ; this list may only shrink).
ENV_EDGE = frozenset({"packages/kernel/src/tlkernel/env.py"})
# os.environ outside the edge today (none under taskloop or taskloop_dash;
# the dashboard takes its environment once, in taskloop_dash/cli/dash.py, through contracts/env).
ENV_ALLOWLIST: frozenset[str] = frozenset()


def mentioned(path: Path) -> set[str]:
    return set(NAME.findall(path.read_text(encoding="utf-8", errors="replace")))


class Registry(Case):
    def test_every_documented_name_is_registered(self):
        bad = {f"{p.relative_to(ROOT)}: {n}" for p in (*TEXTS, *CODE) for n in mentioned(p)
               if n not in NOT_VARIABLES and not registered(n) and not n.endswith("_") and n not in PREFIXES}
        assert not bad, "names missing from contracts/envvars.py:\n" + "\n".join(sorted(bad))

    def test_every_registered_name_is_used(self):
        reg = ROOT / "packages/kernel/src/tlkernel/envvars.py"
        text = "\n".join(p.read_text() for p in (*CODE, ROOT / "skills/task-loop/SKILL.md", *TEXTS) if p != reg)
        unused = [v.name for v in EnvVar if v.name not in text]
        assert unused == []

    def test_gate_passed_is_no_variable(self):
        assert "TL_GATE_PASSED" not in EnvVar.__members__
        said = [p for p in (*TEXTS, *CODE) if "TL_GATE_PASSED" in p.read_text(errors="replace")]
        assert said == []


class EnvEdge(Case):
    def test_os_environ_only_at_the_edge(self):
        hits = {str(p.relative_to(ROOT)) for p in (*(ROOT / "src/taskloop").rglob("*.py"), *(ROOT / "src/taskloop_dash").rglob("*.py"))
                if re.search(r"\bos\.(environ|getenv|putenv)\b|from os import[^\n]*\benviron\b", p.read_text())}
        assert sorted(hits - ENV_EDGE - ENV_ALLOWLIST) == [], "read the environment through tlkernel.env"

    def test_the_allowlist_only_shrinks(self):
        assert frozenset() == ENV_ALLOWLIST
