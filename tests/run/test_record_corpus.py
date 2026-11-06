"""dev/record_corpus.py picks the newest landed runs that kept their node answers (tl-7i9k.48, slice 1: the replay corpus)."""
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("record_corpus", ROOT / "dev" / "record_corpus.py")
assert spec and spec.loader
corpus: Any = importlib.util.module_from_spec(spec)
sys.modules["record_corpus"] = corpus
spec.loader.exec_module(corpus)


def run(root: Path, name: str, landed=True, answers=("plan.json", "write-1.json", "review-1.json")) -> None:
    folder = root / name
    folder.mkdir()
    kinds = ["run_start", "land_receipt"] if landed else ["run_start"]
    (folder / "engine.jsonl").write_text("".join(json.dumps({"kind": k}) + "\n" for k in kinds))
    for a in answers:
        (folder / a).write_text("{}")


def test_only_landed_runs_that_kept_their_answers_are_picked_newest_first(tmp_path):
    run(tmp_path, "01A")
    run(tmp_path, "01B", landed=False)
    run(tmp_path, "01C", answers=())
    run(tmp_path, "01D", answers=("plan.json", "review-1.json"))  # no writer answer
    run(tmp_path, "01E")
    assert [p.name for p in corpus.pick(tmp_path, 30)] == ["01E", "01A"]


def test_at_most_n_are_picked_and_they_are_the_newest(tmp_path):
    for n in range(5):
        run(tmp_path, f"01{n}")
    assert [p.name for p in corpus.pick(tmp_path, 3)] == ["014", "013", "012"]


def test_a_torn_log_or_a_stray_file_is_skipped_not_fatal(tmp_path):
    run(tmp_path, "01A")
    (tmp_path / "01B").mkdir()
    (tmp_path / "01B" / "engine.jsonl").write_text('{"kind": "land_rece')
    (tmp_path / "notes.txt").write_text("x")
    assert [p.name for p in corpus.pick(tmp_path, 30)] == ["01A"]


def test_the_commands_name_each_picked_run_per_role_and_write_no_data(tmp_path):
    run(tmp_path, "01A")
    out = "\n".join(corpus.commands(tmp_path, 30))
    for role in ("planner", "writer", "reviewer"):
        assert f"dev/record_exchange.py {tmp_path / '01A'} {role} real-01A-{role}" in out
    assert out.endswith("# 1 landed run(s) with answers")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["01A"]  # nothing was written
