"""Reach windows use real history and inventory whole package suites separately."""
import subprocess

from reach import main


def test_until_fixes_window_and_separates_package_inventory(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "reach@example.test")
    git("config", "user.name", "Reach")
    files = {
        "tests/x/test_one.py": "X = 1\n",
        "tests/x/test_two.py": "X = 2\n",
        "packages/demo/pyproject.toml": '[project]\nname = "demo"\n',
        "packages/demo/tests/test_demo.py": "",
    }
    for path, text in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    git("add", ".")
    git("commit", "-qm", "initial wide")
    initial = git("rev-parse", "--short", "HEAD")
    (tmp_path / "tests/x/test_one.py").write_text("X = 3\n")
    git("add", ".")
    git("commit", "-qm", "shell only")
    until = git("rev-parse", "--short", "HEAD")
    (tmp_path / "tests/x/test_two.py").write_text("X = 4\n")
    git("add", ".")
    git("commit", "-qm", "outside window")

    output = []
    monkeypatch.setattr("builtins.print", output.append)
    assert main(["--root", str(tmp_path), "--commits", "2", "--until", until, "--wide"]) == 0
    fixed = output.pop()
    assert f"window: 2 commits ending at {until} " in fixed
    assert "tests 2, commits measured 2" in fixed
    assert "selected per commit: median 1.5" in fixed
    assert "shell test files (root tests/ only)" in fixed
    assert "package suites selected (run whole, not counted above): median 1.0, max 1; test files median 1.0" in fixed
    assert fixed.index(f"{initial} initial wide: 2/2") < fixed.index(f"{until} shell only: 1/2")
    assert "outside window" not in fixed
    main(["--root", str(tmp_path), "--commits", "2"])
    rolling = output.pop()
    assert "selected per commit: median 1.0" in rolling
    assert until not in rolling
