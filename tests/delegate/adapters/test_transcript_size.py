"""transcript_size: the last turn's input tokens from a Claude or Codex transcript."""
import json

from delegate.adapters.transcript_size import context_k


def write(path, *rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_claude_counts_the_last_main_assistant_turn_with_its_cache(tmp_path):
    usage = {"input_tokens": 1000, "cache_read_input_tokens": 40000, "cache_creation_input_tokens": 500}
    side = {"type": "assistant", "isSidechain": True, "message": {"usage": {"input_tokens": 9}}}
    p = write(tmp_path / "c.jsonl", {"type": "assistant", "message": {"usage": {"input_tokens": 1}}},
              {"type": "assistant", "message": {"usage": usage}}, side)
    assert context_k(p) == 41.5


def test_codex_reads_the_last_token_count(tmp_path):
    p = write(tmp_path / "x.jsonl", {"payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 12345}}}})
    assert context_k(p) == 12.3


def test_no_file_or_no_usage_is_none(tmp_path):
    assert context_k(None) is None
    assert context_k(tmp_path / "gone.jsonl") is None
    assert context_k(write(tmp_path / "e.jsonl", {"type": "user"})) is None
