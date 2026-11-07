"""The one stores rule no linter holds: only the real implementations touch the disk. The rest of the stores rules are the layer
contracts in .importlinter (no domain, no re), ruff TID251 in stores/ruff.toml (no subprocess, no socket), D100 (a docstring on every
module) and tests/rules/gate_rules.py (the caps)."""
import ast
import sys
from pathlib import Path

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PKG = Path(__file__).resolve().parents[2] / "src" / "taskloop" / "stores"
REAL = {"files.py", "real.py"}


class StoreRules(Case):
    def test_only_the_real_implementations_touch_the_disk(self):
        for f in sorted(PKG.glob("*.py")):
            if f.name in REAL:
                continue
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call):
                    fn = node.func
                    name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
                    assert name not in {"open", "read_text", "write_text", "unlink", "mkdir"}, f"{f.name} calls {name}"
                if isinstance(node, ast.Import):
                    assert not {"fcntl", "tempfile", "shutil"} & {a.name for a in node.names}, f.name
