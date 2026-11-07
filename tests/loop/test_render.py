"""Loop command text is a result, tested with memory snapshots."""

import json
from unittest.mock import Mock, patch

from taskloop.app.loop import factory_verbs, render
from taskloop.app.loop.loop import loop_identity
from taskloop.app.loop.queue import Queue, Ranked, Skipped
from tlkernel import wire
from tlkernel.bead import Bead
from tlkernel.config import RepoProfile
from tlkernel.env import Env
from tlkernel.identity import Identity
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


def test_cutover_text_and_json_are_exact():
    assert render.cutover_lines([], False) == (["CLEAR: no live loop or run"], 0)
    live = [("loop", "loop pid 7"), ("run", "run in /é")]
    assert render.cutover_lines(live, False) == (["LIVE loop pid 7\nLIVE run in /é"], 1)
    assert render.cutover_lines(live, True) == (
        ['{"live": [{"kind": "loop", "what": "loop pid 7"}, {"kind": "run", "what": "run in /\\u00e9"}]}'], 1)
    assert render.cutover_lines([], True) == (['{"live": []}'], 0)


def test_factory_stop_and_logs_results():
    files = Mock()
    files.request_stop.return_value = []
    rows, code = factory_verbs.stop_lines(files, False, "actor")
    assert (list(rows), code) == (["not running"], 1)
    files.request_stop.return_value = [Mock(pid=7), Mock(pid=8)]
    for now, text in [(True, "NOW"), (False, "after the current bead")]:
        rows, code = factory_verbs.stop_lines(files, now, "actor")
        assert (list(rows), code) == ([f"STOP {text}: loop pid 7", f"STOP {text}: loop pid 8"], 0)
    with patch.object(factory_verbs, "logs", return_value=(Mock(), "path")), patch.object(
        factory_verbs, "lines", return_value=iter(["line\n", "partial"])) as tail:
        rows, code = factory_verbs.log_lines(files, [], 2, 3, True)
        assert (list(rows), code) == (["line\n", "partial"], 0)
        tail.assert_called_once_with("path", 3, True)


def test_factory_start_target_and_status_order():
    files, profile, spawn, awake, dash = (Mock() for _ in range(5))
    with patch.object(factory_verbs, "wanted", return_value=3) as wanted, patch.object(
        factory_verbs, "start", return_value=([], 2)) as start, patch.object(factory_verbs, "facts", return_value=["facts"]):
        assert list(factory_verbs.start_lines(files, "repo", "v", [], spawn, None, profile, awake)) == [
            "started 2 more loop(s)", "facts"]
        wanted.assert_called_once_with(profile)
        assert start.call_args.kwargs == {"loops": 3, "caffeinate_argv": awake}
        start.return_value = ([], 0)
        assert list(factory_verbs.start_lines(files, "repo", "v", [], spawn, 1, profile, awake)) == [
            "already running (0 loops)", "facts"]
        assert wanted.call_count == 1
    with patch.object(factory_verbs, "status_facts", return_value=["facts"]), patch.object(
        factory_verbs, "status_wanted", return_value="?"), patch.object(factory_verbs, "last_by_loop", return_value=[
            {"pid": 7, "t": 42, "reason": "clean"}]):
        rows, code = factory_verbs.status_lines(files, [], "repo", "v", profile, dash)
        assert next(rows) == "facts"
        dash.assert_not_called()
        assert list(rows) == ["LOOPS running=0 wanted=?", "LOOP 7 LAST EXIT pid=7 time=42 reason=clean "]
        assert code == 1
        dash.assert_called_once_with()


def test_loop_identity_ignores_session_actor_and_preserves_handover():
    seen = []

    def identity(env):
        seen.append(env)
        session = env.get("TASK_LOOP_SESSION")
        return Identity(actor="session-actor", home="/home", session=session)

    tokens = iter(["a" * 32, "b" * 32])
    actor, loop_actor, session = loop_identity(Env({"TASK_LOOP_ACTOR": "inherited"}), identity, lambda: next(tokens))
    assert (actor, loop_actor, session.session) == ("session-actor", "session-actor-bbbbbb", "loop-aaaaaaaaaaaa")
    assert all("TASK_LOOP_ACTOR" not in env.vars for env in seen)
    state = LoopState(pid=7, started=1, t=1, repo="r", version="v", code_dir="c", actor="old-loop")
    token = Mock(side_effect=AssertionError("handover needs no new token"))
    actor, loop_actor, session = loop_identity(
        Env({"TASK_LOOP_SESSION": "existing", "TL_LOOP_STATE": json.dumps(wire.dump(state))}), identity, token)
    assert (actor, loop_actor, session.session) == ("session-actor", "old-loop", "existing")
