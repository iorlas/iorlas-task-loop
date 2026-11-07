"""dev/affected.py --closure: the files the selected tests can depend on, so that a result can be carried over a base move only when none
of them changed (app/land/cleanup.py)."""
from affected import Repo, closure, mark_green, not_green, select


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


def pending(root, ledger, changed):
    repo = Repo(root)
    return not_green(repo, select(repo, changed), ledger, listing(root))


def test_a_green_test_is_skipped_until_a_file_of_its_own_closure_changes(tmp_path):
    root, ledger = tree(tmp_path / "r", BASE), tmp_path / "green.txt"
    both = {"src/pkg/b.py", "src/pkg/unrelated.py"}
    assert {"tests/x/test_a.py", "tests/y/test_u.py"} <= set(pending(root, ledger, both))
    mark_green(Repo(root), ["tests/x/test_a.py", "tests/y/test_u.py"], ledger, listing(root))
    left = pending(root, ledger, both)
    assert "tests/x/test_a.py" not in left and "tests/y/test_u.py" not in left and "tests/rules/test_all.py" in left
    (root / "src/pkg/b.py").write_text("X = 2\n")  # only test_a reaches b
    left = pending(root, ledger, both)
    assert "tests/x/test_a.py" in left and "tests/y/test_u.py" not in left


def green_then(tmp_path, files=None):
    root, ledger = tree(tmp_path / "r", {**BASE, **(files or {})}), tmp_path / "green.txt"
    mark_green(Repo(root), ["tests/x/test_a.py"], ledger, listing(root))
    assert "tests/x/test_a.py" not in pending(root, ledger, {"src/pkg/b.py"})
    return root, ledger


def test_a_changed_dependency_conftest_data_or_config_runs_the_green_test_again(tmp_path):
    for changed in ("src/pkg/b.py", "tests/conftest.py", "tests/x/data.json", "pyproject.toml"):
        root, ledger = green_then(tmp_path / changed.replace("/", "_"))
        (root / changed).write_text("changed\n" if changed.endswith(".py") or changed.endswith(".toml") else '{"a": 1}')
        assert "tests/x/test_a.py" in pending(root, ledger, {"src/pkg/b.py"}), changed


def test_a_changed_file_of_an_unrelated_test_folder_leaves_the_green_test_green(tmp_path):
    root, ledger = green_then(tmp_path, {"tests/z/data.json": "{}"})
    (root / "tests/z/data.json").write_text('{"a": 1}')
    assert "tests/x/test_a.py" not in pending(root, ledger, {"src/pkg/b.py"})


def test_a_red_run_marks_nothing_and_a_corrupt_ledger_means_run(tmp_path):
    root, ledger = green_then(tmp_path)
    ledger.write_bytes(b"\xff\xfe not a key\n" + ledger.read_bytes()[:20])  # torn, not utf-8
    assert "tests/x/test_a.py" in pending(root, ledger, {"src/pkg/b.py"})
    mark_green(Repo(root), ["tests/x/test_a.py"], ledger, listing(root))  # rewritten whole, the bad lines gone
    assert "tests/x/test_a.py" not in pending(root, ledger, {"src/pkg/b.py"})
    assert all(len(line) == 40 for line in ledger.read_text().split())


def test_a_directory_in_place_of_the_ledger_means_run(tmp_path):
    root, _ = green_then(tmp_path)
    assert "tests/x/test_a.py" in pending(root, tmp_path, {"src/pkg/b.py"})


def test_the_data_of_an_unrelated_test_folder_or_fixture_folder_is_not_in_the_closure(tmp_path):
    files = {**BASE, "tests/y/y.json": "{}", "tests/fixtures/other/a.json": "{}", "tests/fixtures/x/b.json": "{}",
             "tests/fixtures/n/c.json": "{}", "tests/x/test_n.py": "NAME = 'n'\n", "tests/loose.txt": ""}
    repo = Repo(tree(tmp_path, files))
    got = closure(repo, ["tests/x/test_a.py", "tests/x/test_n.py"], listing(tmp_path))
    assert {"tests/x/data.json", "tests/fixtures/x/b.json", "tests/fixtures/n/c.json", "tests/loose.txt"} <= set(got)
    assert "tests/y/y.json" not in got and "tests/fixtures/other/a.json" not in got
