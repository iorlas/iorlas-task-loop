"""How much work a test did, in seconds an idle host would have needed: the measure behind a logic test's time limit.

CPU time is not work. On a host whose cores are all taken (shared caches, SMT, work moved to slow cores) the same test is charged 2x to 4x
the CPU seconds, and a fixed CPU limit fails a healthy test only because the box is busy. Where the kernel counts the instructions a
process retired (macOS: proc_pid_rusage, `ri_instructions`), those do not depend on the load; they are turned into seconds at the rate
this host showed at its best (the fastest of nine runs of a fixed workload, taken at start). Elsewhere the measure is CPU time."""
import ctypes
import os
import resource
import sys

_FIELDS = [
    "user_time", "system_time", "pkg_idle_wkups", "interrupt_wkups", "pageins", "wired_size", "resident_size",
    "phys_footprint", "proc_start_abstime", "proc_exit_abstime", "child_user_time", "child_system_time",
    "child_pkg_idle_wkups", "child_interrupt_wkups", "child_pageins", "child_elapsed_abstime", "diskio_bytesread",
    "diskio_byteswritten", "cpu_time_qos_default", "cpu_time_qos_maintenance", "cpu_time_qos_background",
    "cpu_time_qos_utility", "cpu_time_qos_legacy", "cpu_time_qos_user_initiated", "cpu_time_qos_user_interactive",
    "billed_system_time", "serviced_system_time", "logical_writes", "lifetime_max_phys_footprint", "instructions",
    "cycles", "billed_energy", "serviced_energy", "interval_max_phys_footprint", "runnable_time",
]


class _RusageV4(ctypes.Structure):
    _fields_ = [("uuid", ctypes.c_uint8 * 16), *[(name, ctypes.c_uint64) for name in _FIELDS]]  # struct rusage_info_v4


def _libproc():
    if sys.platform != "darwin":
        return None
    try:
        return ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    except OSError:
        return None


_LIB = _libproc()
_RATE: list[float] = []  # instructions per second of an idle core, once measured


def instructions() -> int | None:
    """Instructions this process has retired so far; None where the kernel does not say."""
    if _LIB is None:
        return None
    info = _RusageV4()
    if _LIB.proc_pid_rusage(os.getpid(), 4, ctypes.byref(info)) != 0 or not info.instructions:
        return None
    return info.instructions


def cpu_s() -> float:
    used = resource.getrusage(resource.RUSAGE_SELF)
    return used.ru_utime + used.ru_stime


def _fixed_work() -> tuple[int, float] | None:
    """(instructions, CPU seconds) of the same pure-Python loop every time."""
    before, start = instructions(), cpu_s()
    total = 0
    for i in range(1_500_000):
        total += i * i % 7
    after = instructions()
    if before is None or after is None:
        return None
    return after - before, cpu_s() - start


def calibrate() -> None:
    """The rate of this host at its best: the most instructions per CPU second seen in nine runs of the fixed workload."""
    best = 0.0
    for _ in range(9):
        run = _fixed_work()
        if run and run[1] > 0:
            best = max(best, run[0] / run[1])
    if best:
        _RATE[:] = [best]


def measured() -> bool:
    return bool(_RATE)


def seconds(instruction_count: int) -> float:
    """The CPU seconds an idle core would need for this many instructions."""
    return instruction_count / _RATE[0]

