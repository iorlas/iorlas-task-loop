"""No push through the Git port can rewrite or delete a remote ref (the 2026-11-05 main rewind), except the one lease method.

Hard rule, no table: adapter code never passes force= / allow_delete= to a push call and never builds `--force...` or a `+refspec`;
`push_lease` (the lease on one named ref and the sha the caller last saw) is the only function that may spell `--force-with-lease=`."""
import ast
import re
import sys
from pathlib import Path

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "taskloop"
PUSH_CALLS = frozenset({"push", "push_request", "push_refspecs"})
BANNED_KW = frozenset({"force", "allow_delete"})
PLUS_REFSPEC = re.compile(r"^\+\S*:")
LEASE_FN = "push_lease"


def violations(text: str, name: str = "x.py", strings: bool = True) -> list[str]:
    tree = ast.parse(text)
    bad = []
    lease_nodes = {id(n) for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef) and fn.name == LEASE_FN for n in ast.walk(fn)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            called = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            bad += [f"{name}:{node.lineno} {called}({kw.arg}=...)" for kw in node.keywords if called in PUSH_CALLS and kw.arg in BANNED_KW]
        elif strings and isinstance(node, ast.Constant) and isinstance(node.value, str):
            force = "--force" in node.value and not (node.value.startswith("--force-with-lease=") and id(node) in lease_nodes)
            if force or PLUS_REFSPEC.match(node.value):
                bad.append(f"{name}:{node.lineno} {node.value!r}")
    return bad


class NoForcePush(Case):
    def test_git_adapters_never_force_delete_or_plus_a_refspec_outside_the_lease(self):
        found = []
        for path in sorted((SRC / "adapters").glob("git*.py")):
            found += violations(path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix())
        assert found == []

    def test_no_src_call_passes_force_to_a_push(self):
        found = []
        for path in sorted(SRC.rglob("*.py")):
            found += violations(path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix(), strings=False)
        assert found == []

    def test_the_rule_sees_each_kind_of_escape(self):
        assert violations("x.push_request(r, [s], force=True)")
        assert violations("x.push_request(r, [s], allow_delete=True)")
        assert violations("opts = ['--force']")
        assert violations("spec = '+HEAD:main'")
        assert violations("def other():\n    return f'--force-with-lease={d}:{s}'")
        assert violations("def push_lease():\n    return f'--force-with-lease={d}:{s}'") == []
        assert violations("def other():\n    return '--force-with-lease=x'")
        assert violations("def push_lease():\n    return '--force-with-lease=x'") == []
        assert violations("w.add_worktree(p, r, force=True)") == []
