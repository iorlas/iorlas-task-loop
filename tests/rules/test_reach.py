"""dev/reach.py: the stage of a path, the summary of counts, the files that alone select half, the stage pairs that import each other."""
from affected import Repo
from reach import stage_edges, stage_of, summary, two_way, wide_alone


def tree(root, files):
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    return root


FILES = {
    "src/taskloop/__init__.py": "", "packages/kernel/src/tlkernel/__init__.py": "", "packages/kernel/src/tlkernel/k.py": "X = 1\n",
    "src/taskloop/app/__init__.py": "", "src/taskloop/app/doctor/__init__.py": "",
    "src/taskloop/app/doctor/a.py": "from taskloop.app" ".slots import s\n",
    "src/taskloop/app/slots/__init__.py": "", "src/taskloop/app/slots/s.py": "from taskloop.app.doctor import a\n",
    "tests/conftest.py": "", "tests/land/test_a.py": "from taskloop.app.doctor import a\n",
    "tests/x/test_k.py": "from tlkernel import k\n", "tests/x/test_k2.py": "from tlkernel import k\n",
}


def test_stage_of_maps_app_and_domain_slices_top_packages_and_the_rest_to_kernel():
    assert stage_of("src/taskloop/app/checks/x.py") == "gate"
    assert stage_of("packages/work/src/tlwork/review/x.py") == "work"
    assert stage_of("packages/dash/src/tldash/a.py") == "dash"
    assert stage_of("packages/kernel/src/tlkernel/wire.py") == "kernel"
    assert stage_of("tests/x.py") is None


def test_summary_gives_median_mean_p90_and_max():
    assert summary([1, 2, 3, 4, 10]) == {"median": 3, "mean": 4, "p90": 10, "max": 10}


def test_a_contract_file_alone_selects_the_tests_that_import_it(tmp_path):
    repo = Repo(tree(tmp_path, FILES))
    assert wide_alone(
        repo, {"packages/kernel/src/tlkernel/k.py", "src/taskloop/app/doctor/a.py"}, 3,
    ) == ["packages/kernel/src/tlkernel/k.py"]


def test_two_stages_that_import_each_other_are_listed_with_both_counts(tmp_path):
    [(a, b, forward, back)] = two_way(stage_edges(Repo(tree(tmp_path, FILES))))
    assert (a, b) == ("doctor", "slots") and forward > 0 and back > 0
