"""Stage closures count local import reachability using only in-memory source texts."""
from rules.closure_ratchet import closures


def test_transitive_closure_includes_own_files_and_counts_stages_separately():
    assert closures({
        "src/taskloop/app/first/__init__.py": "from . import worker",
        "src/taskloop/app/first/worker.py": "from taskloop.shared import run",
        "src/taskloop/app/first/unused.py": "",
        "src/taskloop/app/second/__init__.py": "import taskloop.leaf",
        "src/taskloop/shared.py": "import taskloop.leaf",
        "src/taskloop/leaf.py": "import taskloop.shared",
    }) == {"first": 5, "second": 3}


def test_packages_longest_match_lazy_and_type_checking_imports():
    assert closures({
        "src/taskloop/app/demo/__init__.py": """
import requests
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from taskloop.pkg import exported

def run():
    import taskloop.pkg.child.attribute
""",
        "src/taskloop/pkg/__init__.py": "from . import sibling",
        "src/taskloop/pkg/child.py": "",
        "src/taskloop/pkg/sibling.py": "",
        "src/taskloop/app/not_a_stage/worker.py": "",
    }) == {"demo": 4}


def test_new_stage_and_empty_graph():
    assert closures({}) == {}
    assert closures({"src/taskloop/app/new/__init__.py": "import os"}) == {"new": 1}
