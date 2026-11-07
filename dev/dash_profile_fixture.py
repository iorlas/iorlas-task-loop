"""Local profiling input: 171 runs, varied logs and no access to host state."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from support.fakes import FakeBeadStore

from tldash.env import Ports
from tldash.testing import RunScript, bead
from tlkernel.paths import ConfigDir
from tltestkit.repos import write_repos

RUNS = 171


def ports() -> Ports:
    store = FakeBeadStore()
    for i in range(RUNS):
        store.put(bead(f"b-{i}", f"Profile run {i}"))
    return Ports(store=lambda _: store)


def populate(cfg: ConfigDir) -> None:
    repo = cfg.root / "project"
    repo.mkdir()
    write_repos(cfg.repos(), repo)
    now = time.time()
    beat = json.dumps({"v": 3, "kind": "beat", "t": now}).encode() + b"\n"
    for i in range(RUNS):
        script = RunScript(f"b-{i}", at=i).step("plan", 10, 1000).step("write", 30, 2000).close("done")
        script.write(cfg.root, repo=str(repo))
        with cfg.engine_log(script.name).open("ab") as file:
            file.write(beat * (500 + i * 10))
