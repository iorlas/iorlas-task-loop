"""Where this process lives: the clock, the plugin tree, the config dir, and the stores under it (each file behind its store).

The functions are the seam tests patch; `load_routing` is the one place routing.json and the owner's config.json meet.
"""

import argparse
import contextlib
import copy
import json
import os
import shutil
import sys
import time
import types
from collections.abc import Callable
from pathlib import Path

from child_env import scrub_current

from delegate.contracts import codec
from delegate.contracts.history import HistoryRow
from delegate.contracts.json_types import Json, obj
from delegate.contracts.routing import Routing, replaced_settings, split_retired
from delegate.contracts.state import StateDoc
from delegate.contracts.stores import ConfigStore, HistoryStore, StateStore

Args = argparse.Namespace | types.SimpleNamespace  # the parsed command line (a stand-in namespace in tests)
DATA_DIR = Path(__file__).resolve().parents[1] / "data"  # routing.json, contract.json
ENTRY = Path(__file__).resolve().parents[1] / "entry.py"  # the script a worker's guard shim runs


def now() -> float:
    v = os.environ.get("DELEGATE_NOW")
    return float(v) if v else time.time()


LEGACY_DATA = "iorlas-delegate-iorlas-marketplace"  # the data dir of the retired iorlas-delegate plugin


def home_dir() -> Path:
    """task-loop's own folder: <XDG_CONFIG_HOME or ~/.config>/task-loop/delegate (the only place the factory keeps state)."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "task-loop" / "delegate"


def adopt_legacy(target: Path) -> None:
    """The first use after the plugin was retired: the old plugin's settings, state and history become this folder's. Once."""
    old = Path.home() / ".claude" / "plugins" / "data" / LEGACY_DATA
    if not target.exists() and old.is_dir():
        with contextlib.suppress(OSError):
            shutil.copytree(old, target)


def config_dir() -> Path:
    """Where settings, profile and state live: DELEGATE_CONFIG_DIR, else task-loop's folder for them (`home_dir`)."""
    explicit = os.environ.get("DELEGATE_CONFIG_DIR")
    p = Path(explicit) if explicit else home_dir()
    if not explicit:
        adopt_legacy(p)
    p.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(p, 0o700)  # holds state and history: private to the user
    return p


def deep_merge(a: dict[str, Json], b: dict[str, Json] | None) -> dict[str, Json]:
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = deep_merge(obj(out[k]), v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


_RETIRED_WARNED: set[str] = set()


def load_routing() -> dict[str, Json]:
    """routing.json with the owner's overrides (config.json, minus its `profile`) merged into `settings`, validated into
    contracts.routing.Routing.
    Retired settings keys are dropped with one stderr line each (stdout carries the answer); any other unknown key fails."""
    with open(DATA_DIR / "routing.json", encoding="utf-8") as f:
        cfg = json.load(f)
    moved = replaced_settings(cfg["lanes"])
    for k in config_store().overrides():
        if k in moved:
            sys.exit(
                f"route.py: {config_store().path}: '{k}' is replaced by the lane profile. Fix: delete \"{k}\" from config.json, "
                f"then run `route.py config set profile.lanes.{moved[k]} enabled`"
            )
    cfg["settings"], _ = split_retired(deep_merge(obj(cfg["settings"]), config_store().overrides()))
    for k in retired_keys_present():
        if k not in _RETIRED_WARNED:
            _RETIRED_WARNED.add(k)
            print(
                f"route.py: {config_store().path}: '{k}' is retired and ignored; "
                "it is safe to delete from config.json (nothing rewrites the file)",
                file=sys.stderr,
            )
    typed_routing(cfg)
    return cfg


def retired_keys_present() -> list[str]:
    """The retired settings keys config.json (the owner's file) still carries."""
    return split_retired(config_store().overrides())[1]


def typed_routing(cfg: dict[str, Json]) -> Routing:
    try:
        return codec.from_json(Routing, cfg)
    except codec.CodecError as e:
        sys.exit(
            f"route.py: routing.json / config.json is not a valid routing table: {e}. "
            f"Fix: delete the key from {config_store().path} (or rename it to a known settings key; see `route.py config show`)"
        )


def settings_of(cfg: dict[str, Json]):
    return typed_routing(cfg).settings


def states() -> StateStore:
    return StateStore(config_dir() / "state.json")


def config_store() -> ConfigStore:
    return ConfigStore(config_dir() / "config.json")


def history_path() -> Path:
    return config_dir() / "history.jsonl"


def history_store() -> HistoryStore:
    return HistoryStore(history_path())


def snapshot_path() -> Path:
    return config_dir() / "status-snapshot.json"


def net_cache_path() -> Path:
    return config_dir() / "net.json"


def load_state():
    return states().load()


def update_state(fn: Callable[[StateDoc], object]):
    return states().update(fn)


def update_config(fn: Callable[[dict[str, Json]], object]):
    return config_store().update(fn)


def profile_lanes() -> dict[str, Json]:
    return dict(config_store().profile().lanes)


def set_profile_lane(name: str, value: str | None) -> None:
    config_store().set_lane(name, value)


def history_add(row: HistoryRow) -> None:
    history_store().add(row)


def in_container() -> bool:
    return os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")


def session_host() -> str:
    """desktop | container | cli | headless | unknown, from the environment. The model never decides this."""
    ep = os.environ.get("CLAUDE_CODE_ENTRYPOINT", "")
    if "desktop" in ep:
        return "desktop"
    if in_container():
        return "container"
    if ep == "cli":
        return "cli"
    return "unknown" if ep else "headless"


# The child's environment is child_env.scrub (what a Claude session exports and credential-looking variables are removed); CLAUDE_CONFIG_DIR
# is kept
# so a worker on a custom Claude login finds it.
KEEP = ("CLAUDE_CONFIG_DIR",)


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The worker gets the caller's environment minus what a Claude session exports, delegate's and credential-looking variables, plus
    DELEGATE_DEPTH=1."""
    return scrub_current(keep=KEEP) | {"DELEGATE_DEPTH": "1"} | (extra or {})
