"""Doctor and the engine inspect the same committed base, even from a stale worktree."""
import contextlib
import io
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from unittest import mock

from tlkernel.config import RepoProfile
from tltestkit.case import Case

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import tlbd  # noqa: E402
from support.who import who  # noqa: E402

from taskloop.adapters.beadtools import bd_store  # noqa: E402
from taskloop.app.doctor import ops, setup_checks  # noqa: E402
from taskloop.app.doctor.env_checks import Finding  # noqa: E402


def shown(p):
    """A path as git and the engine print it: forward slashes and long names on Windows."""
    return Path(p).resolve().as_posix() if os.name == "nt" else str(p)


class DoctorBeads(Case):
    """tl-f52: doctor lists the open beads whose text names material no worktree holds."""

    def test_doctor_lists_the_offenders_and_not_the_clean_or_escaped(self):
        beads = [{"id": "x-1", "description": "see ~/Documents/Drop/arch-study-1025/84-self-hosting.md"},
                 {"id": "x-2", "description": "change engine.py"},
                 {"id": "x-3", "description": "study 84 s.2: facts inline", "labels": ["facts-inline"]},
                 {"id": "x-4", "acceptance_criteria": "matches 79-test-impact-and-land-gate.md"},
                 {"id": "x-5", "issue_type": "epic", "description": "study 49"}]
        with mock.patch.dict(os.environ, {"TASK_LOOP_ACTOR": "tl-test"}), tlbd.bd_boundary(result=tlbd.done(json.dumps(beads))):
            out = setup_checks.bead_lint_warnings("/work/repo", lambda: bd_store(who().actor, "/work/repo"))
        assert [w.split(":")[0] for w in out] == ["bead x-1", "bead x-4"]
        assert all("needs inlined facts" in w for w in out)


def test_report_preserves_row_order_and_failure_verdict():
    def capture(facts):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = ops.report(facts)
        return code, stream.getvalue()

    facts = ops.DoctorFacts(
        repo="repo", contracts=lambda: Path("contracts"), migrate_command="migrate",
        profile=lambda: 0, source=lambda: (RepoProfile(), "main", "abc"),
        slots=lambda: ("slots", ["slot"]), path_link=lambda: ("foreign tl", True),
        git_warnings=lambda source: ["git"], layout_warnings=lambda source: ["layout"],
        bead_warnings=lambda: ["bead"], clone_warnings=lambda: ["clone"], capability_gap=lambda: "capability",
        lost_runs=lambda: ["lost"], legacy=lambda: "legacy", old_layout=lambda: ["old"],
        install_problems=lambda: ["install"], findings=lambda: [Finding("WARN", "environment", "repair")],
        rails=lambda source: [], queue=lambda base: [],
    )
    code, text = capture(facts)
    assert code == 1
    lines = text.splitlines()
    assert lines == [
        "config: .task-loop.json from base main at commit abc", "slots", "contracts: contracts",
        *[f"engine: {line}" for line in ops.product_lines(RepoProfile().engine.writer_exec, RepoProfile().engine.reviewer_other_family)],
        "WARN git", "WARN layout", "WARN bead", "WARN slot", "WARN foreign tl", "WARN clone", "WARN capability",
        "WARN run lost is lost: its process is gone and it recorded no end", "legacy",
        "WARN the config dir is in the old layout (1 places, first old): stop the loops, then run `migrate`",
        "FAIL install", "WARN environment; fix: repair",
    ]
    code, text = capture(replace(facts, install_problems=lambda: []))
    assert code == 0  # warnings alone never fail
    assert "ok: no setup problems" not in text
    assert capture(replace(facts, profile=lambda: 1, source=mock.Mock(side_effect=AssertionError))) == (1, "")
