"""`tl doctor --disk`: where the config folder's bytes are, largest first, and a warning when the volume is nearly full (tl-7i9k.24)."""
from pathlib import Path

from taskloop.app.doctor import disk

GB = 1 << 30


def put(root: Path, name: str, size: int) -> None:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x" * size)


def test_areas_are_listed_largest_first_and_everything_else_is_one_row(workdir):
    root = Path(workdir)
    put(root, "runs/a/log", 3000)
    put(root, "runs/b/log", 1000)
    put(root, "engine/r1.jsonl", 500)
    put(root, "stray.txt", 7)
    lines = disk.report(root, free=100 * GB)
    assert [ln.split()[0] for ln in lines[:3]] == ["runs", "engine", "other"]
    assert lines[3].startswith("total ")
    assert not any(ln.startswith("WARN") for ln in lines)


def test_a_nearly_full_volume_warns_and_names_the_free_space(workdir):
    lines = disk.report(Path(workdir), free=GB // 2)
    assert any(ln.startswith("WARN") and "0.5 GB free" in ln for ln in lines)


def test_a_missing_config_folder_reports_nothing_used(workdir):
    lines = disk.report(Path(workdir) / "absent", free=100 * GB)
    assert lines == ["total 0.0 MB", "free 100.0 GB"]
