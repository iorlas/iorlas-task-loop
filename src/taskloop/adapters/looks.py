"""Resize rendered pictures with the installed image tool, falling back to a copy."""
import shutil
import subprocess
from pathlib import Path

from taskloop.adapters import procs


def downscale(src: str | Path, dst: str | Path, px: float) -> str:
    """Copy `src` to `dst`, no side longer than `px` when a tool is there to shrink it (sips on macOS, ImageMagick); else a plain
    copy. Returns "" on success or why it was a plain copy."""
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    tool = shutil.which("sips")
    if tool:
        cmd = [tool, "-Z", str(int(px)), str(src), "--out", str(dst)]
    else:
        tool = shutil.which("magick") or shutil.which("convert")
        cmd = [tool, str(src), "-resize", f"{int(px)}x{int(px)}>", str(dst)] if tool else None
    if cmd:
        try:
            r = procs.run_bytes(cmd, timeout=120)
            if r.returncode == 0 and Path(dst).is_file():
                return ""
        except (OSError, subprocess.SubprocessError):
            pass
    shutil.copy2(src, dst)
    return "not downscaled (no sips or ImageMagick, or it failed)"
