"""Release code comparisons include every workspace package."""

from dataclasses import replace
from pathlib import Path
from unittest import mock

from support.shells import quiet_shell

from tlkernel.env import Env
from tlrelease import selfupdate


def test_workspace_package_change_selects_the_clones_release_script(tmp_path: Path):
    tool = tmp_path / "tool"
    clone = tmp_path / "clone"
    script = clone / "dev" / "release.py"
    script.parent.mkdir(parents=True)
    script.write_text("")
    ids = {"HEAD:src": "engine", "HEAD:packages": "packages", "HEAD:dev/release.py": "entry"}
    clone_ids = {**ids, "HEAD:packages": "new-packages"}
    port = mock.Mock()
    port.rev_parse.side_effect = lambda root, path: (clone_ids if root == str(clone) else ids)[path]
    sh = replace(quiet_shell(), port=port)

    assert selfupdate.newer_release(tool, clone, sh, Env({})) == script
    clone_ids.update(ids)
    assert selfupdate.newer_release(tool, clone, sh, Env({})) is None
