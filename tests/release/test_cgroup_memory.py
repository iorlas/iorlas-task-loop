"""available_mb is the smaller of MemAvailable and the cgroup v2 headroom (a container's /proc/meminfo shows the host)."""
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.case import Case

from taskloop.app.release import suite

MB = 1024 * 1024


class CgroupHeadroom(Case):
    def available(self, files: dict[str, str], path: str = "/box", mem_kb: int = 8 * 1024 * 1024) -> int | None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "cg"
            for name, text in files.items():
                (root / "box").mkdir(parents=True, exist_ok=True)
                (root / name).write_text(text)
            (Path(d) / "meminfo").write_text(f"MemAvailable: {mem_kb} kB\n")
            (Path(d) / "cgroup").write_text(f"0::{path}\n")
            with mock.patch.object(suite, "MEMINFO", Path(d) / "meminfo"), mock.patch.object(suite, "PROC_CGROUP", Path(d) / "cgroup"), \
                    mock.patch.object(suite, "CGROUP_ROOT", root):
                return suite.available_mb()

    def test_a_headroom_smaller_than_memavailable_wins(self):
        assert self.available({"box/memory.max": str(4096 * MB), "box/memory.current": str(1024 * MB)}) == 3072

    def test_a_headroom_larger_than_memavailable_loses(self):
        assert self.available({"box/memory.max": str(64 * 1024 * MB), "box/memory.current": "0"}) == 8192

    @pytest.mark.parametrize("p0,p1", [("max\n", "5"), ("lots", "??")], ids=['max_means_no_limit', 'garbage_means_no_limit'])
    def test_max_means_no_limit_cases(self, p0, p1):
        assert self.available({"box/memory.max": p0, "box/memory.current": p1}) == 8192

    def test_a_missing_memory_max_means_no_limit(self):
        assert self.available({"box/memory.current": "5"}) == 8192

    def test_a_missing_memory_current_means_no_limit(self):
        assert self.available({"box/memory.max": str(MB)}) == 8192

    def test_the_root_path_reads_the_cgroup_root_itself(self):
        assert self.available({"memory.max": str(2048 * MB), "memory.current": str(MB)}, path="/") == 2047

    def test_usage_above_the_limit_is_zero_headroom(self):
        assert self.available({"box/memory.max": str(MB), "box/memory.current": str(2 * MB)}) == 0
