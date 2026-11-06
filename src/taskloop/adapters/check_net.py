"""Taking a check's network away (NETISO, tl-7i9k.59): the argv prefix per host, chosen by a pure function.

macOS: `sandbox-exec` with a profile that denies the network except loopback. Linux: `unshare -rn` (a user and a network namespace; the
loopback is brought up, so a check's own local servers work). A host with neither cannot remove the network: the plan says so in words
and adds nothing (slice 1 warns, it never refuses a check)."""
import functools
import platform
import shutil
import subprocess
from collections.abc import Callable
from typing import NamedTuple

MAC_PROFILE = '(version 1)(allow default)(deny network*)(allow network* (remote ip "localhost:*"))(allow network* (remote unix-socket))'
LINUX_WRAPPER = 'ip link set lo up >/dev/null 2>&1; exec "$@"'  # $0 is the `sh` that follows; the check's argv is "$@"

said: set[str] = set()  # the warnings already told in this process: one line per reason, not one per check


class Plan(NamedTuple):
    prefix: tuple[str, ...]
    warning: str


def plan(system: str, which: Callable[[str], str | None], userns: Callable[[], bool]) -> Plan:
    """The prefix for `system`, or no prefix and the reason this host cannot remove the network. `userns` is asked only on Linux."""
    if system == "Darwin" and (tool := which("sandbox-exec")):
        return Plan((tool, "-p", MAC_PROFILE), "")
    if system == "Linux":
        tool = which("unshare")
        if not tool:
            return Plan((), "this host cannot remove the network: no `unshare` on PATH")
        if not userns():
            return Plan((), "this host cannot remove the network: `unshare -rn` is refused (user namespaces are off)")
        return Plan((tool, "-rn", "sh", "-c", LINUX_WRAPPER, "sh"), "")
    return Plan((), f"this host cannot remove the network: no known way on {system}")


def system() -> str:
    return platform.system()


def which(name: str) -> str | None:
    return shutil.which(name)


@functools.cache
def userns_works() -> bool:
    """`unshare -rn true` exits 0 here (asked once per process)."""
    try:
        return subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=10, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def current() -> Plan:
    """The plan for this host."""
    return plan(system(), which, userns_works)
