"""Row: the one shape of an append-only line that says what happened in a run: events.jsonl, the engine log, loop/<key>.jsonl and the
check durations all carry this head. A field a row has no value for stays empty; a kind adds its own facts below the head.

`run_id` is the run's id (TL_RUN_ID in every check it starts), `parent_id` the run it continues, `call_id` the worker call or check
the row is about; `tree`, `base` and `sha` say which code; a kind that ends something adds its `outcome`; `exec_seconds` is the time a
step ran, `wait_seconds` the time it queued; `artifact` and `artifact_hash` name a file it left."""
from taskloop.contracts.wire import Tagged


class Row(Tagged, kw_only=True):
    t: float = 0.0  # UTC epoch seconds; unset (0): the writer stamps the time of the append
    run_id: str = ""
    parent_id: str = ""
    call_id: str = ""
    bead: str = ""
    host: str = ""
    tree: str = ""
    base: str = ""
    sha: str = ""
    step: str = ""
    exec_seconds: float | None = None
    wait_seconds: float | None = None
    artifact: str = ""
    artifact_hash: str = ""
