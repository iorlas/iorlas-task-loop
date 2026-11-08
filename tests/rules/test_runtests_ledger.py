"""dev/runtests.py with TL_GREEN_LEDGER=1: tests already green on their own files are left out, and a green run records the ones that ran.
Off by default: the ledger is for the accounts' runs until the land gate trusts it."""
import runtests
from affected import Repo

FILES = {"src/pkg/__init__.py": "", "src/pkg/a.py": "X = 1\n", "tests/x/test_a.py": "import pkg.a\n", "tests/x/test_b.py": "import pkg.a\n",
         "tests/rules/test_all.py": "def test_x(): pass\n"}


def tree(root):
    for path, text in FILES.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    return root


def listing(root):
    return [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]


def test_the_ledger_is_off_unless_the_switch_is_set(tmp_path):
    tests = ["tests/x/test_a.py", "tests/x/test_b.py"]
    assert runtests.ledger_path({}) is None
    assert runtests.pending(Repo(tree(tmp_path)), tests, None) == tests


def test_a_green_run_records_the_tests_and_the_next_run_skips_them(tmp_path):
    root, ledger = tree(tmp_path / "r"), tmp_path / "green.txt"
    repo, tests = Repo(root), ["tests/x/test_a.py", "tests/x/test_b.py"]
    assert runtests.ledger_path({"TL_GREEN_LEDGER": "1", "XDG_CACHE_HOME": str(tmp_path)}) == tmp_path / "task-loop" / "green-tests.txt"
    assert runtests.pending(repo, tests, ledger, listing(root)) == tests
    runtests.record(repo, tests, ledger, [0, 5], listing(root))
    assert runtests.pending(repo, tests, ledger, listing(root)) == []
    (root / "src/pkg/a.py").write_text("X = 2\n")
    assert runtests.pending(Repo(root), tests, ledger, listing(root)) == tests


def test_a_red_run_records_nothing(tmp_path):
    root, ledger = tree(tmp_path / "r"), tmp_path / "green.txt"
    runtests.record(Repo(root), ["tests/x/test_a.py"], ledger, [1, 0], listing(root))
    assert not ledger.exists()
