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
    }) == {"first": 5, "first (external modules)": 0, "second": 3, "second (external modules)": 0}


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
    }) == {"demo": 4, "demo (external modules)": 2}


def test_new_stage_and_empty_graph():
    assert closures({}) == {}
    assert closures({"src/taskloop/app/new/__init__.py": "import os"}) == {"new": 1, "new (external modules)": 1}


def test_gate_member_is_the_checks_stage_and_the_shell_glue_keeps_no_budget():
    counts = closures({
        "src/taskloop/app/checks/__init__.py": "",
        "src/taskloop/app/checks/step.py": "from tlgate.runner import Checker",
        "packages/gate/src/tlgate/__init__.py": "",
        "packages/gate/src/tlgate/runner.py": "from tlgate.domain import plan",
        "packages/gate/src/tlgate/domain/__init__.py": "",
        "packages/gate/src/tlgate/domain/plan.py": "import json",
    })
    assert counts == {"checks": 4, "checks (external modules)": 1}


def test_a_package_testing_module_is_outside_the_stage_closure():
    counts = closures({
        "packages/gate/src/tlgate/__init__.py": "",
        "packages/gate/src/tlgate/runner.py": "",
        "packages/gate/src/tlgate/testing.py": "import json\nfrom tlgate import runner",
    })
    assert counts == {"checks": 2, "checks (external modules)": 0}


def test_slots_member_keeps_the_slots_stage_identity_and_kernel_closure():
    counts = closures({
        "packages/slots/src/tlslots/__init__.py": "",
        "packages/slots/src/tlslots/engine_lock.py": "from tlslots.effects import Effects",
        "packages/slots/src/tlslots/effects.py": "from tlkernel.locks import LockRecord",
        "packages/kernel/src/tlkernel/__init__.py": "",
        "packages/kernel/src/tlkernel/locks.py": "import dataclasses",
    })
    assert counts == {"slots": 4, "slots (external modules)": 1}


def test_work_review_keeps_its_identity_and_reaches_moved_domain():
    counts = closures({
        "packages/work/src/tlwork/__init__.py": "",
        "packages/work/src/tlwork/review/__init__.py": "",
        "packages/work/src/tlwork/review/routing.py": "from tlwork.work.ledger import Ledger",
        "packages/work/src/tlwork/work/__init__.py": "",
        "packages/work/src/tlwork/work/ledger.py": "import dataclasses",
    })
    assert counts == {"review": 3, "review (external modules)": 1}
