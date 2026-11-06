"""`tl doctor` says how many of the last beads had their worker on the warm second family: read from the run traces, unit-pure."""
import pytest
from support.narrow import must

from taskloop.app.doctor import ops
from taskloop.contracts.enums import Outcome
from taskloop.contracts.ids import RunId
from taskloop.contracts.trace import AiCall, RunTrace


def run(n: int, bead: str, *families: str, role: str = "worker") -> RunTrace:
    calls = [AiCall(node="n", family=f, ref="r", status="done", role=role, t=n) for f in families]
    return RunTrace(run=must(RunId.of(f"01KBN6Z0M4R5E8YQ2T7C9W3X{n:02d}")), bead=bead, repo_url="", worktree="", branch="",
                    coordinator_session="", started=n, ended=n + 1, outcome=Outcome.LANDED, why="", sha="", sessions=calls)


def test_a_bead_counts_once_however_many_runs_and_calls_it_had():
    runs = [run(1, "b-1", "claude", "claude"), run(2, "b-1", "claude"), run(3, "b-2", "openai")]
    assert ops.second_share(runs, "claude") == (1, 2)


def test_only_the_workers_family_counts_not_a_reviewers():
    assert ops.second_share([run(1, "b-1", "claude", role="reviewer")], "claude") == (0, 1)


def test_the_last_n_beads_by_their_latest_run_are_counted():
    runs = [run(i, f"b-{i}", "claude" if i % 2 else "openai") for i in range(1, 31)]
    routed, of = ops.second_share(runs, "claude", last=20)
    assert (of, routed) == (20, 10)  # b-11..b-30: ten odd ids


@pytest.mark.parametrize(("share", "line"), [
    ((0, 0), "second_writer_family claude routed: no runs yet"),
    ((2, 20), "second_writer_family claude routed: 2 of the last 20 beads"),
])
def test_the_doctor_line(share, line):
    assert ops.second_share_line("claude", *share) == line
