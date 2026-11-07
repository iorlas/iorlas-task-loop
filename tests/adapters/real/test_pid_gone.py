"""Process disappearance includes an exited child that has not been reaped."""
import subprocess
from pathlib import Path

import pytest
from support.procsim import real_proc
from support.waits import until
from support.world import pid_gone


@real_proc("an unreaped child stays in proc as a zombie")
def test_zombie_is_gone():
    if not Path("/proc").exists():
        pytest.skip("zombie state requires /proc")
    p = subprocess.Popen(["sh", "-c", "exit 0"])
    try:
        stat = Path(f"/proc/{p.pid}/stat")
        assert until(lambda: stat.read_text().rsplit(") ", 1)[1][0] == "Z", 5)
        assert pid_gone(p.pid)
    finally:
        p.wait()


@real_proc("a live child exists until it is killed and reaped")
def test_live_then_reaped_child():
    p = subprocess.Popen(["sleep", "5"])
    try:
        assert not pid_gone(p.pid)
    finally:
        p.kill()
        p.wait()
    assert pid_gone(p.pid)
