"""`tl doctor --disk`: where the config folder's bytes are, largest first, and a warning when the volume is nearly full (tl-7i9k.24)."""
from pathlib import Path

import pytest

from taskloop.app.doctor import disk
from taskloop.contracts.paths import ConfigDir

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


DAY = 86400.0


def falling(days: int, per_day: int, last_free: int) -> list[tuple[float, int]]:
    """Hourly samples over `days` days, `per_day` bytes lower each day, the last one at `last_free`."""
    return [(h * 3600.0, last_free + int((days * 24 - h) / 24 * per_day)) for h in range(days * 24 + 1)]


def test_eight_days_falling_a_gb_a_day_forecast_twenty_days_to_full(workdir):
    lines = disk.report(Path(workdir), free=20 * GB, samples=falling(8, GB, 20 * GB))
    assert "~20 days to full" in lines
    assert not any(ln.startswith("WARN") for ln in lines)


def test_a_volume_that_fills_within_a_week_warns(workdir):
    lines = disk.report(Path(workdir), free=20 * GB, samples=falling(8, 4 * GB, 20 * GB))
    assert "~5 days to full" in lines
    assert any(ln.startswith("WARN") and "5 days" in ln for ln in lines)


def test_only_the_last_seven_days_are_fitted(workdir):
    old = [(h * 3600.0, 100 * GB) for h in range(24 * 10)]  # ten flat days, then a week falling 1 GB a day
    week = [(240 * 3600.0 + h * 3600.0, 50 * GB - int(h / 24 * GB)) for h in range(24 * 7 + 1)]
    lines = disk.report(Path(workdir), free=week[-1][1], samples=old + week)
    assert "~43 days to full" in lines


@pytest.mark.parametrize("samples", [[], [(0.0, 5 * GB)], [(0.0, 5 * GB), (DAY, 6 * GB)], [(0.0, 5 * GB), (DAY, 5 * GB)]])
def test_no_forecast_with_fewer_than_two_samples_or_a_volume_that_is_not_filling(workdir, samples):
    lines = disk.report(Path(workdir), free=100 * GB, samples=samples)
    assert not any("to full" in ln for ln in lines)


def test_the_loop_records_a_sample_and_doctor_reads_it_back_from_factory_db(workdir):
    cfg = ConfigDir(Path(workdir))
    assert disk.read_samples(cfg) == []   # no database yet, and reading never creates one
    assert not cfg.factory_db().exists()
    disk.record_sample(cfg, 9 * GB, 1000.0)
    disk.record_sample(cfg, 8 * GB, 1000.0 + 3600)
    assert disk.read_samples(cfg) == [(1000.0, 9 * GB), (4600.0, 8 * GB)]
