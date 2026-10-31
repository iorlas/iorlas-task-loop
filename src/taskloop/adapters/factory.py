"""Optional macOS idle prevention for the detached factory."""
import platform
import shutil


def caffeinate_argv(pid: int) -> list[str]:
    exe = shutil.which("caffeinate") if platform.system() == "Darwin" else None
    return [exe, "-i", "-w", str(pid)] if exe else []
