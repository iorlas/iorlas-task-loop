"""The version census of `tl status` and the ops checks of `tl doctor` (tl-7i9k.52): who runs which version, and what is stale."""
import hashlib
from unittest import mock

from taskloop.app.doctor import ops
from taskloop.app.wire import brief as wire_brief
from taskloop.domain import versions
from taskloop.domain.brief import Brief, LoopLine, status_json, status_lines


def loop(version):
    return LoopLine(100, 1.0, "tl-x", "s1", version)


def brief(loops=(), installed="0.23.9", shim=""):
    return Brief(repo="/r", now=2.0, version="0.23.9", installed=installed, pinned="", loops=tuple(loops), shim_sha256=shim)


def test_skew_lists_the_loop_versions_that_differ_from_the_newest_installed():
    assert versions.skew(["0.23.1", "0.23.9", "0.23.1", ""], "0.23.9") == ["0.23.1"]
    assert versions.skew(["0.23.9"], "0.23.9") == []
    assert versions.skew(["0.23.1"], "") == []  # nothing installed is known: no claim


def test_status_json_has_a_versions_block_and_keeps_the_old_keys():
    out = status_json(brief([loop("0.23.1"), loop("0.23.9")], shim="ab" * 32))
    assert out["versions"] == {
        "running": "0.23.9", "installed": "0.23.9", "pinned": "", "loops": ["0.23.1", "0.23.9"],
        "shim_sha256": "ab" * 32, "skew": ["0.23.1"],
    }
    assert out["installed"] == "0.23.9" and out["version"] == "0.23.9"


def test_the_text_prints_the_shim_prefix_and_a_skew_line_only_when_there_is_skew():
    flat = status_lines(brief([loop("0.23.9")], shim="abcdef0123" + "0" * 54))
    assert any("shim abcdef01" in ln for ln in flat)
    assert not any("SKEW" in ln for ln in flat)
    skewed = status_lines(brief([loop("0.23.1")]))
    assert any(ln.startswith("SKEW: ") and "0.23.1" in ln and "0.23.9" in ln for ln in skewed)
    assert not any("shim " in ln for ln in skewed)  # no shim file: nothing to print


def test_the_shim_hash_is_the_sha256_of_bin_tl_or_empty(tmp_path):
    assert wire_brief.shim_sha256(tmp_path) == ""
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "tl").write_bytes(b"#!/bin/sh\nexec x\n")
    assert wire_brief.shim_sha256(tmp_path) == hashlib.sha256(b"#!/bin/sh\nexec x\n").hexdigest()


def test_a_clone_behind_its_origin_is_a_warning_and_a_current_one_is_silent():
    assert ops.clone_line("ab12", 0) == ""
    assert ops.clone_line("ab12", 3) == "release clone ab12 is 3 commits behind its origin/main (as of its last fetch)"
    assert ops.clone_line("ab12", 1).endswith("1 commit behind its origin/main (as of its last fetch)")


def test_clones_are_read_through_the_git_port(tmp_path):
    (tmp_path / "release" / "ab12").mkdir(parents=True)
    (tmp_path / "release" / "file").write_text("x")
    git = mock.Mock()
    git.log.return_value = [object(), object()]
    assert ops.clone_warnings(tmp_path, git) == ["release clone ab12 is 2 commits behind its origin/main (as of its last fetch)"]
    git.log.assert_called_once_with(str(tmp_path / "release" / "ab12"), ["origin/main"], ["HEAD"])


def test_a_delegate_contract_missing_a_capability_the_engine_relies_on_is_a_warning():
    ok = {"capabilities": list(ops.REQUIRED_CAPABILITIES)}
    assert ops.capability_gap(ok) == ""
    gap = ops.capability_gap({"capabilities": []})
    assert all(name in gap for name in ops.REQUIRED_CAPABILITIES)
    assert ops.capability_gap({}) != ""
