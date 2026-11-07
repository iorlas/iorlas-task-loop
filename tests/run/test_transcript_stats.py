"""The run's stats line quotes each worker session's transcript file (a Codex rollout, a Claude transcript)."""
from taskloop.app.pipeline.closing import transcript_stats

ROLLOUT = "/home/u/.codex/sessions/2026/11/05/rollout-2026-11-05T01-02-03-abc.jsonl"


def test_each_distinct_file_is_quoted_once_with_the_node_that_wrote_it():
    sessions = [{"node": "write", "transcript": ROLLOUT}, {"node": "write", "transcript": ROLLOUT},
                {"node": "review", "transcript": "/home/u/.claude/projects/p/s.jsonl"},
                {"node": "plan", "transcript": ""}, {"node": "plan"}]
    assert transcript_stats(sessions) == f"; write-transcript={ROLLOUT}; review-transcript=/home/u/.claude/projects/p/s.jsonl"


def test_no_session_files_add_nothing():
    assert transcript_stats([]) == transcript_stats([{"node": "plan", "transcript": ""}]) == ""
