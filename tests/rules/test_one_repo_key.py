"""One repo key (tl-sqd3.18, Z18): ids.loop_key is the one place a repo path becomes a key; check_files.repo_key only picks the folder
(the git common dir's parent) and asks it. No other module hashes a path into a key or defines its own loop_key/repo_key."""
import ast
from pathlib import Path

from rules.gate_rules import ROOT, parsed, py_files

OWNER = "packages/kernel/src/tlkernel/ids.py"
PROJECTION = "packages/kernel/src/tlkernel/check_files.py"
SCAN = ("src", "packages")


def key_defs(tree: ast.Module) -> list[str]:
    return [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in {"loop_key", "repo_key"}]


def hashes_realpath(tree: ast.Module) -> bool:
    """A function that calls os.path.realpath and a sha1 in one body: a key computed by hand."""
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        names = {c.func.attr for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
        if "realpath" in names and "sha1" in names:
            return True
    return False


def test_only_ids_and_check_files_define_a_repo_key():
    found = {}
    for path in py_files(ROOT, scan=SCAN):
        rel = path.relative_to(ROOT).as_posix()
        if "/tests/" in rel:
            continue
        names = key_defs(parsed(path)[1])
        if names:
            found[rel] = sorted(names)
    assert found == {OWNER: ["loop_key"], PROJECTION: ["repo_key"]}


def test_no_module_but_ids_hashes_a_path_into_a_key():
    offenders = [path.relative_to(ROOT).as_posix() for path in py_files(ROOT, scan=SCAN)
                 if "/tests/" not in path.relative_to(ROOT).as_posix() and hashes_realpath(parsed(path)[1])]
    assert offenders == [OWNER]


def test_the_scan_sees_a_hand_made_key():
    assert hashes_realpath(ast.parse("def key(p):\n    return hashlib.sha1(os.path.realpath(p).encode()).hexdigest()\n"))
    assert not hashes_realpath(ast.parse("def key(p):\n    return os.path.realpath(p)\n"))
