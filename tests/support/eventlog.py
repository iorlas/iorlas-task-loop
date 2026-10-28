"""The events `tl` wrote (events.jsonl in the config dir of the test's XDG_CONFIG_HOME), for a test that asserts on what the code recorded."""
import json

from taskloop.adapters import ident


def read():
    """Every event so far, oldest first, as the dicts the code wrote."""
    f = ident.config_dir() / "events.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


def kinds():
    return [e["kind"] for e in read()]
