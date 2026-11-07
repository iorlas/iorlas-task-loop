"""Kernel-only helpers import and work in the member's isolated environment."""
from pathlib import Path

from tlkernel import factorydb, factoryparts
from tlkernel.paths import ConfigDir
from tltestkit import checks, fake_route, logs, narrow, repos, runs
from tltestkit.tmpdir import TemporaryDirectory


def test_helpers():
    assert checks.ck(["true"])
    assert fake_route.as_check("true")["argv"] == ["true"]
    assert callable(repos.write_repos)
    assert logs.pairs([logs.typed("step_start", 0, id="s")]) == ([("step_start", "s")], [])
    assert narrow.must("present") == "present"
    assert narrow.only(str, "value") == "value"
    factorydb.declare_parts((factoryparts.PIPELINE,))
    with TemporaryDirectory() as folder:
        cfg = ConfigDir(Path(folder))
        bundle = runs.manifest(cfg, "run", "bead")
        assert bundle.manifest.run == "run"
        factorydb.close_shared()
