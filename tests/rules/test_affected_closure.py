"""dev/affected.py --closure: the files the selected tests can depend on, so that a result can be carried over a base move only when none
of them changed (app/land/carry.py)."""
import support.paths  # noqa: F401
from affected import Repo, closure, select


def listing(root):
    return [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]


def tree(root, files):
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    return root


BASE = {
    "src/pkg/__init__.py": "", "src/pkg/a.py": "import pkg.b\n", "src/pkg/b.py": "X = 1\n",
    "src/pkg/unrelated.py": "Y = 2\n",
    "tests/conftest.py": "", "tests/x/test_a.py": "import pkg.a\n", "tests/x/data.json": "{}",
    "tests/y/test_u.py": "import pkg.unrelated\n",
    "tests/rules/test_all.py": "def test_x(): pass\n", "pyproject.toml": "",
}


def test_the_closure_holds_the_tests_their_imports_conftest_data_and_config(tmp_path):
    repo = Repo(tree(tmp_path, BASE))
    chosen = select(repo, {"src/pkg/b.py"})
    got = closure(repo, chosen, listing(tmp_path))
    assert {"src/pkg/a.py", "src/pkg/b.py", "tests/x/test_a.py", "tests/conftest.py", "tests/x/data.json", "pyproject.toml"} <= set(got)
    assert "src/pkg/unrelated.py" not in got and "tests/y/test_u.py" not in got  # not reached by a selected test
    assert not [p for p in got if p.startswith("tests/rules/")]  # the rules read the whole tree: a check of their own


def test_a_new_test_that_imports_the_changed_module_joins_the_closure(tmp_path):
    t = tree(tmp_path / "t", BASE)
    before = closure(Repo(t), select(Repo(t), {"src/pkg/b.py"}), listing(t))
    m = tree(tmp_path / "m", {**BASE, "tests/z/test_new.py": "import pkg.b\n"})
    after = closure(Repo(m), select(Repo(m), {"src/pkg/b.py"}), listing(m))
    assert before != after and "tests/z/test_new.py" in after
