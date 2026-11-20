"""Read-only public contract collection.

To review a refresh, run from the repo root after installation:
uv run --frozen --no-sync python -I tests/steps/public_surfaces.py
Apply the printed JSON to tests/rules/public_surfaces.json deliberately; tests never refresh it.
"""

import inspect
import json
import sys
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from difflib import unified_diff
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from pydantic import BaseModel

from taskloop.factory_schema import SCHEMA

ROOT = Path(__file__).resolve().parents[2]


def declaration(value: object) -> dict[str, object]:
    if inspect.isclass(value):
        result: dict[str, object] = {"kind": "class", "signature": str(inspect.signature(value))}
        if issubclass(value, BaseModel):
            result["schema"] = value.model_json_schema()
        elif is_dataclass(value):
            result["fields"] = {field.name: str(field.type) for field in fields(value)}
        result["methods"] = {
            name: str(inspect.signature(member))
            for name, member in inspect.getmembers(value)
            if not name.startswith("_")
            and (inspect.isfunction(member) or inspect.ismethod(member))
            and (not issubclass(value, BaseModel) or name not in dir(BaseModel) or name in value.__dict__)
        }
        return result
    if inspect.isfunction(value):
        return {"kind": "function", "signature": str(inspect.signature(value))}
    if value is None or isinstance(value, str | int | float | bool):
        return {"kind": type(value).__name__, "value": value}
    raise TypeError(f"Add explicit public contract collection for {type(value).__name__}")


def load_api(name: str, path: Path) -> ModuleType:
    spec = spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def api_surfaces(root: Path, load: Callable[[str], ModuleType] | None = None) -> dict[str, object]:
    result: dict[str, object] = {}
    for path in sorted((root / "src/taskloop").rglob("api.py")):
        name = ".".join(path.relative_to(root / "src").with_suffix("").parts)
        module = load(name) if load is not None else load_api(name, path)
        exports = getattr(module, "__all__", [name for name in vars(module) if not name.startswith("_")])
        result[name] = {name: declaration(getattr(module, name)) for name in sorted(exports)}
    return result


def collect(cli_cases: dict[str, object], root: Path = ROOT) -> dict[str, object]:
    return {"api": api_surfaces(root), "cli": cli_cases, "schema_version": SCHEMA.version}


def render(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def assert_snapshot(actual: object, expected: str) -> None:
    shown = render(actual)
    assert shown == expected, "Public surfaces changed; review and deliberately refresh the snapshot:\n" + "".join(
        unified_diff(expected.splitlines(keepends=True), shown.splitlines(keepends=True), fromfile="snapshot", tofile="current")
    )


if __name__ == "__main__":
    # Isolated Python does not put this script's folder on sys.path.
    sys.path.insert(0, str(ROOT / "tests/steps"))
    from public_surface_cases import cli_cases

    print(render(collect(cli_cases())), end="")
