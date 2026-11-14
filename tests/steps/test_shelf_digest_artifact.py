"""Offline checks for the delivered digest's pins, mandatory facts and encoding."""

import json
import tomllib
from pathlib import Path

from taskloop.shelf_digest.facts import CONTRACTS, FactName
from taskloop.shelf_digest.identities import PACKAGES
from taskloop.shelf_digest.render import TOKEN_LIMIT
from taskloop.shelf_digest.source import relative_path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_COMMIT = "4b9a05ab1ca3e64ddeabba495c7a1a13b31d85e7"


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
