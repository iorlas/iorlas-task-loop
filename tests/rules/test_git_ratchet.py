"""No git call skips the Git port (contracts/ports.py): a process started for `git` (argv list beginning "git", run_git), or a call to a
string-in string-out `git(...)` helper (gitrepo.git, the engine's e.git), anywhere in src/ but the modules that hold git itself. No table:
a file that cannot go through the port (a plain-python3 hook in git's own path, a script run by path from a slot) says so with one
`# git-port-exempt: <why>` comment line. New git work goes through a Git port method (adapters/git.py RealGit, contracts/ports.py Git) that
tests/ports/git_contract.py holds the sim and real git to.
"""
import ast
import sys
from pathlib import Path

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
PRAGMA = "# git-port-exempt:"
HOME = frozenset({"src/taskloop/adapters/git.py", "src/taskloop/adapters/git_base.py", "src/taskloop/adapters/git_ops.py"})


def count_source(text: str) -> int:
    """The git spawns and string-git calls in one module's source."""
    n = 0
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.List) and len(node.elts) > 1 and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "git":
            n += 1
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            built = isinstance(fn, ast.Attribute) and getattr(fn.value, "id", "") == "real"  # real.git(env) builds the port
            n += name == "run_git" or (name == "git" and bool(node.args) and not built)
    return n


def count_tree(root: Path = ROOT) -> dict[str, int]:
    found = {}
    for path in sorted((root / "src").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        if "_vendor" in path.parts or rel in HOME or PRAGMA in text:
            continue
        if n := count_source(text):
            found[rel] = n
    return found


class GitRule(Case):
    def test_no_file_calls_git_outside_the_port_unless_it_says_why(self):
        assert count_tree() == {}

    def test_each_kind_of_escape_is_counted(self):
        for text in (
            'subprocess.run(["git", "status"])',
            'argv = ["git", "push"]',
            "run_git(d, 'x')",
            "gitq.git('x', cwd=d)",
            "e.git('x')",
            "git('x')",
        ):
            with self.subTest(text):
                assert count_source(text) == 1
        assert count_source("port.fetch(d)\nx = ['git']\ngit.fetch(d)\nreal.git(env)") == 0

    def test_every_exemption_names_a_reason(self):
        pragmas = [(p.name, ln) for p in (ROOT / "src").rglob("*.py") for ln in p.read_text(encoding="utf-8").splitlines() if PRAGMA in ln]
        assert pragmas and all(ln.split(PRAGMA)[1].strip() for _, ln in pragmas)
