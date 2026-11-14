"""Offline checks for the delivered digest's pins, mandatory facts and encoding."""

import json
import tomllib
from pathlib import Path

import pytest
from shelf_input_fixtures import shelf_files

from taskloop.shelf_digest.artifact import PATH, read_artifact
from taskloop.shelf_digest.facts import CONTRACTS, FactName
from taskloop.shelf_digest.identities import PACKAGES, Identities, reconcile_manifests
from taskloop.shelf_digest.render import TOKEN_LIMIT
from taskloop.shelf_digest.source import SourceSnapshot, relative_path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_COMMIT = "9c93e77e742a18d63616cd44e53ded71bf6f204b"


def test_artifact_decodes_all_six_manifest_identities() -> None:
    artifact = json.loads((ROOT / "docs/shelf-digest.json").read_bytes())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    declarations = project["tool"]["uv"]["sources"]
    locked = {package["name"]: package for package in lock["package"]}
    assert artifact["source_commit"] == SOURCE_COMMIT
    assert [package[0] for package in artifact["packages"]] == list(PACKAGES)
    assert set(declarations) == set(PACKAGES)
    for name, version, repository, tag, directory, commit in artifact["packages"]:
        declared = declarations[name]
        assert f"{name}=={version}" in project["project"]["dependencies"]
        assert version == locked[name]["version"]
        repository_url = artifact["repositories"][repository]
        assert repository_url == declared["git"]
        assert tag == declared["tag"] and directory == declared["subdirectory"]
        selector = f"subdirectory={directory.replace('/', '%2F')}&tag={tag}"
        assert locked[name]["source"]["git"] == f"{repository_url}?{selector}#{artifact['commits'][commit]}"
    agent, stream = artifact["packages"][0], artifact["packages"][-1]
    assert agent[5] == stream[5] and stream[1] == locked["stream-proc"]["version"]


def test_artifact_preserves_required_facts_and_source_attribution() -> None:
    artifact = json.loads((ROOT / "docs/shelf-digest.json").read_bytes())
    assert set(artifact["facts"]) == set(FactName)
    used: set[int] = set()
    for contract in CONTRACTS:
        text, references = artifact["facts"][contract.name]
        assert text == contract.text and references == sorted(set(references)) and references
        expected = {(rule.package, f"src/{rule.package.replace('-', '_')}/{rule.module}.py") for rule in contract.rules}
        observed: set[tuple[str, str]] = set()
        for index in references:
            assert 0 <= index < len(artifact["sources"])
            used.add(index)
            package, path, start, end, checksum = artifact["sources"][index]
            assert 0 <= package < len(artifact["packages"])
            assert relative_path(path) and path.startswith("src/") and 1 == start <= end
            assert len(checksum) == 64 and set(checksum) <= set("0123456789abcdef")
            observed.add((artifact["packages"][package][0], path))
        assert observed == expected
    assert used == set(range(len(artifact["sources"])))


def test_artifact_is_complete_canonical_json_within_bound() -> None:
    output = (ROOT / "docs/shelf-digest.json").read_bytes()
    artifact = json.loads(output)
    canonical = (json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    assert output == canonical and len(output) <= TOKEN_LIMIT


def test_consumer_validates_all_pins_and_keeps_generation_provenance() -> None:
    files = shelf_files()
    identities = reconcile_manifests(SourceSnapshot("b" * 40, files))
    assert isinstance(identities, Identities)
    result = read_artifact(files[PATH], identities)
    assert result.source_commit == "a" * 40 and result.encode() == files[PATH]


@pytest.mark.parametrize(("old", "new", "reason"), [
    (b'"0.9.0"', b'"0.8.0"', "package identities"),
    (b'"any-agent-v0.15.0"', b'"any-agent-v0.14.0"', "package identities"),
    (b'"packages/stream-proc"', b'"packages/other"', "package identities"),
    (b'"7292d63cca18ba875fb78a2f4df406a104d03fc2"', b'"7292d63cca18ba875fb78a2f4df406a104d03fc3"', "commit identities"),
    (b'"0.15.0",0', b'"0.15.0",-1', "identity index"),
    (b'"0.15.0",0', b'"0.15.0",true', "valid integer"),
    (b'"stream-proc","0.9.0"', b'"any-agent","0.9.0"', "package identities"),
    (b"0=off", b"0=on", "fact or references"),
    (b'[3]],"usage"', b'[-1]],"usage"', "fact or references"),
    (b'[3]],"usage"', b'[0]],"usage"', "fact attribution"),
    (b'[3]],"usage"', b'[3,3]],"usage"', "fact or references"),
    (b'[0,"src/any_agent/events.py"', b'[6,"src/any_agent/events.py"', "package index"),
    (b'"src/any_agent/events.py"', b'"../any_agent/events.py"', "source path"),
    (b'"src/any_agent/events.py",1,132', b'"src/any_agent/events.py",1,0', "range"),
    (b"958a16997841b2e1217eebb1bc464b847cf1057ca07a35aca4416198c22d43a6", b"invalid", "hash"),
    (b'"source_commit":', b'"source_commit":false,"source_commit":', "Duplicate"),
    (b'"source_commit":', b'"extra":0,"source_commit":', "Extra inputs"),
    (b'"timeout":[', b'"unknown":[', "Input should be"),
    (b'{"commits":', b'{"commits":[],"commits":', "Duplicate"),
])
def test_consumer_rejects_altered_or_unsafe_artifacts(old: bytes, new: bytes, reason: str) -> None:
    files = shelf_files()
    identities = reconcile_manifests(SourceSnapshot("b" * 40, files))
    assert isinstance(identities, Identities) and old in files[PATH]
    with pytest.raises(ValueError, match=reason):
        read_artifact(files[PATH].replace(old, new), identities)


@pytest.mark.parametrize("data", [b"{", b"\xff", b" " * (TOKEN_LIMIT + 1), b"{}", b"[" * 1000 + b"]" * 1000])
def test_consumer_rejects_malformed_missing_or_oversized_content(data: bytes) -> None:
    identities = reconcile_manifests(SourceSnapshot("b" * 40, shelf_files()))
    assert isinstance(identities, Identities)
    with pytest.raises(ValueError):
        read_artifact(data, identities)
