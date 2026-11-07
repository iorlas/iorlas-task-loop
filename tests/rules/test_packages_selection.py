"""dev/packages.py: a change reaches the packages under it and those that declare them; a file outside every package reaches all."""
import pytest
from packages import reached


def workspace(root):
    for name, deps in {"kernel": [], "review": ["kernel"], "plan": ["kernel"], "compose": ["review", "plan"]}.items():
        manifest = root / "packages" / name / "pyproject.toml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(f'[project]\nname = "{name}"\nversion = "0"\ndependencies = {deps!r}\n'.replace("'", '"'))
    return root


def test_a_leaf_change_reaches_itself_and_its_dependents(tmp_path):
    assert reached(workspace(tmp_path), {"packages/review/src/review/x.py"}) == ["compose", "review"]


def test_a_kernel_change_reaches_every_package(tmp_path):
    assert reached(workspace(tmp_path), {"packages/kernel/src/kernel/ids.py"}) == ["compose", "kernel", "plan", "review"]


def test_an_internal_change_reaches_only_its_package(tmp_path):
    root = workspace(tmp_path)
    api = root / "packages/kernel/src/kernel/api.py"
    api.parent.mkdir(parents=True)
    api.touch()
    for path in ("ids.py", "nested/testing.py", "nested/api.py"):
        assert reached(root, {f"packages/kernel/src/kernel/{path}"}) == ["kernel"]


def test_public_surface_changes_reach_dependents(tmp_path):
    root = workspace(tmp_path)
    api = root / "packages/kernel/src/kernel/api.py"
    api.parent.mkdir(parents=True)
    api.touch()
    for path in ("api.py", "contracts/x.py", "testing.py"):
        assert reached(root, {f"packages/kernel/src/kernel/{path}"}) == ["compose", "kernel", "plan", "review"]


def test_without_an_api_every_file_is_public(tmp_path):
    root = workspace(tmp_path)
    for path in ("src/kernel/ids.py", "pyproject.toml", "tests/test_ids.py"):
        assert reached(root, {f"packages/kernel/{path}"}) == ["compose", "kernel", "plan", "review"]


def test_a_file_outside_every_package_reaches_all(tmp_path):
    root = workspace(tmp_path)
    assert reached(root, {"pyproject.toml"}) == ["compose", "kernel", "plan", "review"]
    assert reached(root, {"packages/review/x.py", "uv.lock"}) == ["compose", "kernel", "plan", "review"]


def test_the_folder_is_named_not_the_project(tmp_path):
    for folder, name, deps in (("kernel", "tlkernel", []), ("land", "tlland", ["tlkernel"])):
        manifest = tmp_path / "packages" / folder / "pyproject.toml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(f'[project]\nname = "{name}"\nversion = "0"\ndependencies = {deps!r}\n'.replace("\'", '"'))
    assert reached(tmp_path, {"packages/land/src/tlland/x.py"}) == ["land"]
    assert reached(tmp_path, {"packages/kernel/src/tlkernel/x.py"}) == ["kernel", "land"]


def test_a_dev_group_member_reaches_its_users(tmp_path):
    for folder, name, extra in (("testkit", "tltestkit", ""), ("land", "tlland", '\n[dependency-groups]\ndev = ["pytest", "tltestkit"]\n')):
        manifest = tmp_path / "packages" / folder / "pyproject.toml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(f'[project]\nname = "{name}"\nversion = "0"\ndependencies = []\n{extra}')
    assert reached(tmp_path, {"packages/testkit/src/tltestkit/plugin.py"}) == ["land", "testkit"]


@pytest.mark.parametrize("changed,selected", [
    ("src/taskloop/app/write/step.py", False), ("dev/packages.py", False),
    ("uv.lock", False), ("packages/review/src/review/x.py", False),
    ("packages/delegate/src/delegate/run.py", True), ("packages/delegate/tests/real/test_run.py", True),
    ("src/delegate/run.py", True), ("tests/delegate/test_run.py", True),
    ("skills/task-loop/_vendor/any_agent/procs.py", True), ("dev/vendor.json", True),
    ("packages/testkit/src/tltestkit/plugin.py", True), ("packages/kernel/src/kernel/ids.py", True),
])
def test_scoped_member_uses_own_paths_extra_inputs_and_declared_dependencies(tmp_path, changed, selected):
    root = workspace(tmp_path)
    manifest = root / "packages/delegate/pyproject.toml"
    manifest.parent.mkdir()
    manifest.write_text('[project]\nname = "tldelegate"\ndependencies = ["kernel"]\n')
    result = reached(root, {changed})
    assert ("delegate" in result) == selected
    baseline = set(reached(workspace_without_delegate(root), {changed}))
    assert set(result) - {"delegate"} == (set() if changed.startswith("packages/delegate/") else baseline)


def workspace_without_delegate(root):
    (root / "packages/delegate/pyproject.toml").unlink()
    return root
