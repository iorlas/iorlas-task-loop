"""ApiAgent reads the worker's live file: who started, where it ran, what it did (the engine opens no live file itself)."""
import json
from pathlib import Path

from delegate import api
from taskloop.adapters.agent import ApiAgent, last_event_t, new_live
from taskloop.contracts.delegate import LiveStart


def lines(path: Path, *rows: object) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def agent(live: Path) -> ApiAgent:
    return ApiAgent(api.RunRequest(role="worker", brief_file="b.md", cwd=".", live_file=str(live)))


def test_no_file_no_worker_and_no_events(workdir):
    a = agent(Path(workdir) / "none.jsonl")
    assert (a.worker(), a.start_event(), a.events()) == (None, None, [])


def test_the_first_line_is_the_worker_and_the_start_event_says_where_it_ran(workdir):
    live = Path(workdir) / "live.jsonl"
    started = {"k": "start", "t": 1.0, "harness": "h", "pid": 7, "lane": "L", "model": "m", "effort": "e"}
    lines(live, {"v": 1, "pid": 7, "pgid": 7, "run_id": "r1"}, started, {"k": "nope", "t": 2.0})
    a = agent(live)
    worker = a.worker()
    assert worker is not None and worker.pid == 7
    start = a.start_event()
    assert isinstance(start, LiveStart) and start.lane == "L"
    assert [type(e).__name__ for e in a.events()] == ["LiveStart"]  # the unknown kind is passed over


def test_the_live_file_of_a_call_is_numbered_in_the_runs_folder_and_its_age_is_read(workdir):
    path = new_live(Path(workdir) / "live", 3, "re view/2")
    assert path.endswith("live/03-re-view-2.jsonl")
    assert last_event_t(path) == 0.0  # not written yet
    Path(path).write_text("{}\n", encoding="utf-8")
    assert last_event_t(path) > 0.0
