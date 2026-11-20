"""Concrete retired host resource dependencies stay outside the factory runtime."""

import ast
from pathlib import Path


def test_factory_does_not_manage_host_power_or_ram_admission() -> None:
    runtime = Path(__file__).resolve().parents[2] / "src" / "taskloop"
    retired = {"keep_awake", "host_resources"}
    forbidden_modules = retired | {"psutil"}
    forbidden_calls = {"virtual_memory", "swap_memory", "GlobalMemoryStatusEx", "SetThreadExecutionState",
                       "IOPMAssertionCreateWithName", "IOPMAssertionRelease"}
    forbidden_tools = {"caffeinate", "systemd-inhibit", "pmset"}
    for path in runtime.rglob("*.py"):
        assert path.stem not in retired, path
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert not any(set(alias.name.split(".")) & forbidden_modules for alias in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert not set((node.module or "").split(".")) & forbidden_modules, path
                assert not {alias.name for alias in node.names} & (retired | forbidden_calls), path
            elif isinstance(node, ast.Attribute):
                assert node.attr not in forbidden_calls, path
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in forbidden_tools, path
