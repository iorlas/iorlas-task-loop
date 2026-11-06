"""tl layout migrate (tl-9un.44): an old config dir becomes the target tree, counts and hashes equal; a second run is a no-op."""
import json
import os
from pathlib import Path

from taskloop.adapters import layout_migrate as lm
from taskloop.contracts.paths import ConfigDir

RUN = "t-1-20261015-100000"
KEY = "repo-12345678"
OLD = {
    f"engine/{RUN}.jsonl": '{"v":3}\n',
    f"engine/{RUN}.jsonl.1": '{"v":3,"old":1}\n',
    f"engine/{RUN}.stderr": "boom\n",
    f"engine/{RUN}.live/01-write.jsonl": "{}\n",
    f"loop/{KEY}.json": "{}",
    f"loop/{KEY}.command.json": "{}",
    f"loop/{KEY}-rest.json": "{}",
    f"loop/{KEY}.jsonl": '{"a":1}\n',
    f"loop/{KEY}.4242.json": "{}",
    f"loop/{KEY}/factory.log": "x\n",
    "slots/abcdef123456/000001.json": "{}",
    "slots/abcdef123456/seq": "1",
    "slots/abcdef123456.setup": "",
    "slot-state/repo-1234567890/s1/scratch": "t",
    f"decisions/{KEY}/ADR-1.json": "{}",
    "check-durations/repo-1234567890.json": "{}",
    f"runs/{RUN}/plan.json": "{}",
}


def build(root: Path) -> None:
    for rel, text in OLD.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)


def tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): p.read_text() for p in sorted(root.rglob("*")) if p.is_file()}


def test_migrate_yields_the_target_tree_with_the_same_bytes_and_a_second_run_changes_nothing(workdir):
    cfg = ConfigDir(workdir)
    build(workdir)
    assert lm.old_layout(cfg)
    said: list[str] = []
    assert lm.migrate(cfg, said.append, 1.0) == 0
    after = tree(workdir)
    journal = after.pop("layout-migrate.jsonl")
    assert after == {
        f"runs/{RUN}/engine.jsonl": OLD[f"engine/{RUN}.jsonl"],
        f"runs/{RUN}/engine.jsonl.1": OLD[f"engine/{RUN}.jsonl.1"],
        f"runs/{RUN}/stderr.log": "boom\n",
        f"runs/{RUN}/live/01-write.jsonl": "{}\n",
        f"runs/{RUN}/plan.json": "{}",
        f"repos/{KEY}/loop/state.json": "{}",
        f"repos/{KEY}/loop/command.json": "{}",
        f"repos/{KEY}/loop/rest.json": "{}",
        f"repos/{KEY}/loop/log.jsonl": '{"a":1}\n',
        f"repos/{KEY}/loop/factory.log": "x\n",
        "repos/abcdef123456/slots/000001.json": "{}",
        "repos/abcdef123456/slots/seq": "1",
        "slots/abcdef123456.setup": "",
        "repos/repo-1234567890/slot-state/s1/scratch": "t",
        f"repos/{KEY}/decisions/ADR-1.json": "{}",
        "repos/repo-1234567890/durations.json": "{}",
    }
    assert [json.loads(x)["from"] for x in journal.splitlines()]
    assert not lm.old_layout(cfg)
    assert lm.migrate(cfg, said.append, 2.0) == 0
    assert tree(workdir) == {**after, "layout-migrate.jsonl": journal}  # the second run changed nothing, not even the journal
    assert said[-1].startswith("nothing to migrate")


def test_a_target_that_exists_stops_the_move_before_anything_moves(workdir):
    cfg = ConfigDir(workdir)
    build(workdir)
    (workdir / "runs" / RUN / "engine.jsonl").write_text("new\n")
    before = tree(workdir)
    said: list[str] = []
    assert lm.migrate(cfg, said.append, 1.0) == 3
    assert tree(workdir) == before


def test_a_live_lock_holder_stops_the_move(workdir):
    cfg = ConfigDir(workdir)
    build(workdir)
    lock = cfg.lock_file("loop-x.lock")
    lock.parent.mkdir(parents=True)
    lock.write_text("")
    lock.with_name(lock.name + ".holder").write_text(
        json.dumps({"v": 1, "what": "loop_run", "holder": "loop", "pid": os.getpid(), "t": 1.0}))
    said: list[str] = []
    before = tree(workdir)
    assert lm.migrate(cfg, said.append, 1.0) == 2
    assert tree(workdir) == before
