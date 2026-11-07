"""Loop command text is a result, tested with memory snapshots."""

import json
from unittest.mock import Mock, patch

import support.paths  # noqa: F401

from taskloop.app.loop import render
from taskloop.app.loop.queue import Queue, Ranked, Skipped
from tlkernel.bead import Bead
from tlkernel.config import RepoProfile
from tlkernel.ids import BeadId
from tlkernel.loop import LoopState, Skip


def test_next_text_limits_candidates_and_keeps_selection_and_skips():
    ranked = [Ranked(Bead(id=BeadId(f"x-{i}"), title="é" * 75, priority=i, status="open"), f"reason {i}") for i in range(7)]
    q = Queue(ranked, [Skipped(BeadId("x-9"), Skip(why="held"))])
    lines, code = render.next_lines(q, ["x-0", "x-9"], True, False)
    assert code == 0
    assert lines == [f"{'NEXT' if i == 0 else 'then'} x-{i}  P{i}  {'é' * 70}  (reason {i})" for i in range(6)] + [
        "ONLY: x-0, x-9",
        "skip x-9: held",
    ]
    lines, code = render.next_lines(q, [], False, True)
    assert code == 0
    assert lines == [
        json.dumps(
            {
                "pick": ranked[0].bead.to_dict(),
                "reason": "reason 0",
                "next": [{"id": f"x-{i}", "priority": i, "reason": f"reason {i}"} for i in range(1, 6)],
                "skipped": [{"id": "x-9", "why": "held"}],
            },
            ensure_ascii=False,
        )
    ]


def test_empty_next_and_stop_results():
    assert render.next_lines(Queue(), [], False, False) == (["NONE: no ready bead in the queue"], 1)
    assert render.next_lines(Queue(), [], False, True) == (['{"pick": null, "reason": "", "next": [], "skipped": []}'], 1)
    assert render.stop_lines("/repo", [], False) == (["no loop running on /repo"], 1)
    state = LoopState(pid=42, started=1, t=1, repo="/repo", version="", code_dir="", actor="owner", bead="x-1")
    assert render.stop_lines("/repo", [state], True) == (["STOP NOW: loop pid 42, running x-1"], 0)
    assert render.stop_lines("/repo", [state], False) == (["STOP after the current bead: loop pid 42, running x-1"], 0)


def test_status_health_refusals_and_skipped_rows_in_order():
    env = Mock(repo="/repo")
    env.profile.return_value = RepoProfile()
    env.now.return_value = 1000
    env.ask_lines.return_value = ["ask line"]
    files = Mock()
    files.live.return_value = []
    files.died.return_value = []
    files.last_exit.return_value = {}
    files.log_rows.return_value = Mock(items=[], skipped=2)
    installs = Mock()
    installs.refused.return_value = {"2": "bad" * 60, "1": "broken"}
    with patch.object(render, "rank_ready", return_value=(Queue([Mock()]), Mock())):
        assert render.cmd_status(env, files, installs, 5) == (
            [
                "no loop running on /repo",
                "RED: /repo has 1 ready bead(s) and no loop alive (last beat never): start one with `tl loop --repo /repo`",
                "ask line",
                "RED: task-loop 1 refused: broken",
                f"RED: task-loop 2 refused: {('bad' * 60)[:160]}",
                "2 log line(s) of an older version skipped",
            ],
            0,
        )
    files.log_rows.assert_called_once_with(5)


def test_live_status_and_history_table_are_exact():
    state = LoopState(
        pid=42,
        started=10,
        t=20,
        repo="/repo",
        version="1.2",
        code_dir="/code",
        actor="owner",
        bead="x-1",
        slot="s1",
        since=15,
        run_log="/run",
        log="/loop",
    )
    env = Mock(repo="/repo")
    env.profile.return_value = RepoProfile()
    env.now.return_value = 25
    env.behind.return_value = 2
    env.ask_lines.return_value = []
    files = Mock()
    files.live.return_value = [state]
    files.last_exit.return_value = {"t": 5, "reason": "failed", "detail": "detail"}
    files.stop_for.return_value = "after"
    row = Mock(t=5, bead="x-0", slot="", minutes=2.5, rounds=3, tests_added=4, asked=True, run_id="", why="w" * 70)
    row.outcome.value = "failed"
    files.log_rows.return_value = Mock(items=[Mock(rec=row)], skipped=0)
    installs = Mock()
    installs.refused.return_value = {}
    with patch.object(render, "rank_ready", return_value=(Queue(), Mock())), patch.object(render.time, "strftime", return_value="TIME"):
        lines, code = render.cmd_status(env, files, installs, 5)
    assert code == 0
    assert lines == [
        "LOOP pid 42 on /repo since TIME",
        "  running task-loop 1.2 from /code; lags 2 release(s)",
        "  now: x-1 in s1 since TIME; log /run",
        "  stop requested: after",
        "  log /loop",
        "last beat 0m ago",
        "last exit: failed: detail (0m ago)",
        "when              bead           slot outcome   min rounds tests ask  trace / why",
        f"TIME              x-0            -    failed    2.5      3     4 yes  {'w' * 60}",
    ]


def test_queue_diagnostics_precede_next_json():
    env = Mock()

    def rank(env, cfg, say, only):
        say("queue diagnostic")
        return Queue(), Mock(chosen=[], only=False)

    with patch.object(render, "rank_ready", side_effect=rank):
        assert render.cmd_next(env, [], True) == (["queue diagnostic", '{"pick": null, "reason": "", "next": [], "skipped": []}'], 1)
    env.fetch.assert_called_once_with()
