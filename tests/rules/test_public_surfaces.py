"""Contract drift fails until a human deliberately refreshes the readable snapshot."""

from pathlib import Path
from types import ModuleType, SimpleNamespace

import public_surfaces
import pytest
from public_surface_cases import cli_cases
from public_surfaces import api_surfaces, assert_snapshot, collect, render

from taskloop import result_data
from taskloop.result_data import Shaped

SNAPSHOT = Path(__file__).with_name("public_surfaces.json")


def test_public_surfaces_match_reviewed_snapshot_without_writes() -> None:
    before = SNAPSHOT.stat().st_mtime_ns
    expected = SNAPSHOT.read_text()
    assert_snapshot(collect(cli_cases()), expected)
    assert SNAPSHOT.stat().st_mtime_ns == before


def api_example(root: Path, source: str) -> ModuleType:
    path = root / "src/taskloop/example/api.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    module = ModuleType("example_api")
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


API = '''from pydantic import BaseModel
class Record(BaseModel):
    value: int
def read(key: str) -> Record:
    return Record(value=1)
__all__ = ["Record", "read"]
'''


@pytest.mark.parametrize("changed", [
    API.replace('["Record", "read"]', '["Record"]'),
    API.replace('["Record", "read"]', '["Record", "read", "added"]') + '\nadded = 1\n',
    API.replace("key: str", "key: int"),
    API.replace("value: int", "value: str"),
    API.replace("value: int", "value: int\n    optional: str | None = None"),
    API.replace("value: int", "value: int\n    def changed(self, flag: bool) -> int:\n        return 1"),
])
def test_api_exports_signatures_and_model_fields_require_refresh(tmp_path: Path, changed: str) -> None:
    module = api_example(tmp_path, API)
    baseline = render(api_surfaces(tmp_path, lambda _name: module))
    module = api_example(tmp_path, changed)
    current = api_surfaces(tmp_path, lambda _name: module)
    with pytest.raises(AssertionError, match="Public surfaces changed"):
        assert_snapshot(current, baseline)
    assert_snapshot(current, render(current))


def test_reexported_model_and_new_or_removed_api_are_discovered(tmp_path: Path) -> None:
    owner = api_example(tmp_path, API)
    facade = ModuleType("facade")
    vars(facade)["Record"] = vars(owner)["Record"]
    vars(facade)["__all__"] = ["Record"]
    baseline = render(api_surfaces(tmp_path, lambda _name: facade))
    changed = api_example(tmp_path, API.replace("value: int", "value: str"))
    vars(facade)["Record"] = vars(changed)["Record"]
    with pytest.raises(AssertionError):
        assert_snapshot(api_surfaces(tmp_path, lambda _name: facade), baseline)
    baseline = render(api_surfaces(tmp_path, lambda _name: facade))
    added = tmp_path / "src/taskloop/second/api.py"
    added.parent.mkdir(parents=True)
    added.write_text("")
    with pytest.raises(AssertionError):
        assert_snapshot(api_surfaces(tmp_path, lambda _name: facade), baseline)
    added.unlink()
    assert_snapshot(api_surfaces(tmp_path, lambda _name: facade), baseline)
    (tmp_path / "src/taskloop/example/api.py").unlink()
    with pytest.raises(AssertionError):
        assert_snapshot(api_surfaces(tmp_path, lambda _name: facade), baseline)


@pytest.mark.parametrize("change", ["add", "remove", "type", "nested"])
def test_cli_json_drift_requires_refresh(monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    baseline = render(cli_cases())
    original = result_data.as_data

    def altered(result: Shaped, *, admission: bool = False) -> dict[str, object]:
        data = original(result, admission=admission)
        match change:
            case "add":
                data["new_field"] = True
            case "remove":
                data.pop(next(iter(data)))
            case "type":
                data[next(iter(data))] = 42
            case "nested":
                if isinstance(data.get("result"), dict):
                    data["result"] = {"new_nested_field": "changed"}
        return data

    monkeypatch.setattr(result_data, "as_data", altered)
    current = cli_cases()
    with pytest.raises(AssertionError, match="Public surfaces changed"):
        assert_snapshot(current, baseline)
    assert_snapshot(current, render(current))


def test_schema_version_requires_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = render(collect({}))
    monkeypatch.setattr(public_surfaces, "SCHEMA", SimpleNamespace(version=public_surfaces.SCHEMA.version + 1))
    current = collect({})
    with pytest.raises(AssertionError, match="schema_version"):
        assert_snapshot(current, baseline)
    assert_snapshot(current, render(current))
