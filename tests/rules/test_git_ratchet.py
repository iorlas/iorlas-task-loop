"""A ratchet on git calls that skip the Git port (contracts/ports.py): a process started for `git` (an argv list that begins
"git", run_git), or a call to a string-in string-out `git(...)` helper (gitrepo.git, the engine's e.git), anywhere in src/ but the
modules that hold git itself. tests/rules/git_ratchet.json records the count per file left today; a file may only get
fewer (above its record, or absent from it, fails; below fails until the record is lowered), so the remainder cannot grow back.
New git work goes through a Git port method (adapters/git.py RealGit, contracts/ports.py Git) that tests/ports/git_contract.py
holds the sim and real git to.
"""
import ast
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
RECORD = Path(__file__).with_name("git_ratchet.json")
HOME = frozenset({"src/taskloop/adapters/git.py", "src/taskloop/adapters/git_base.py", "src/taskloop/adapters/git_ops.py"})
# Why a file outside HOME still names git, each one a command that is data or a script git cannot be asked through.
STAYS = {
    "src/taskloop/hook/prepush.py": "the git pre-push hook: plain python3 in git's hook path, it imports no port and no record",
    "src/taskloop/adapters/markers.py": "a plain-python3 script run in the slot (conflict markers): it imports no taskloop code",
    "src/taskloop/contracts/config.py": "the default of the repo's land command, an argv the shell runs: data, not a call",
}


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
        if "_vendor" in path.parts or rel in HOME:
            continue
        if n := count_source(path.read_text(encoding="utf-8")):
            found[rel] = n
    return found


def problems(actual: dict[str, int], recorded: dict[str, int]) -> list[str]:
    out = []
    for rel in sorted(set(actual) | set(recorded)):
        a, r = actual.get(rel, 0), recorded.get(rel, 0)
        if a > r:
            out.append(f"{rel}: {a} git calls outside the Git port, recorded {r}: use a port method, do not raise the record")
        elif a < r:
            out.append(f"{rel}: {a} git calls outside the Git port, recorded {r}: lower it in tests/rules/git_ratchet.json")
    return out


class GitRatchet(unittest.TestCase):
    def test_no_file_gains_a_git_call_outside_the_port(self):
        self.assertEqual(problems(count_tree(), json.loads(RECORD.read_text(encoding="utf-8"))), [])

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
                self.assertEqual(count_source(text), 1)
        self.assertEqual(count_source("port.fetch(d)\nx = ['git']\ngit.fetch(d)\nreal.git(env)"), 0)

    def test_what_is_left_is_only_what_cannot_go_through_the_port(self):
        self.assertEqual(sorted(json.loads(RECORD.read_text(encoding="utf-8"))), sorted(STAYS))

    def test_a_new_call_fails_and_a_removed_one_asks_for_the_record_to_drop(self):
        self.assertEqual(len(problems({"a.py": 2}, {"a.py": 1})), 1)
        self.assertEqual(len(problems({"b.py": 1}, {})), 1)
        self.assertEqual(len(problems({}, {"a.py": 1})), 1)
        self.assertEqual(problems({"a.py": 1}, {"a.py": 1}), [])


if __name__ == "__main__":
    unittest.main()
