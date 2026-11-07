"""dev/packages.py: a change reaches the packages under it and those that declare them; a file outside every package reaches all."""
import support.paths  # noqa: F401
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
