"""Semantic manifest fixtures for the digest, independent of installed distributions."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import override

import pytest
from git_porcelain import Sha, Tree
from git_porcelain.testing import FakeRepo

from taskloop.shelf_digest.identities import (
    PACKAGES,
    Identities,
    IdentityFailure,
    IdentityFailureReason,
    extract_identities,
    reconcile_manifests,
)
from taskloop.shelf_digest.source import ReadFailure, ReadFailureReason, open_source

URL = "https://example.invalid/shelf.git"
COMMIT = "a" * 40
SOURCE_COMMIT = "b" * 40


class Objects(FakeRepo):
    trees: dict[str, Tree]

    @override
    def tree(self, rev: str) -> Tree | None:
        return self.trees.get(rev.removesuffix("^{commit}"))


def objects(path: Path, commits: dict[str, dict[str, bytes]]) -> Objects:
    repo = Objects.init(path)
    repo.trees = {
        commit: Tree(Sha(commit), lambda files=files: {name: ("100644", Sha("c" * 40)) for name in files}, files.get)
        for commit, files in commits.items()
    }
    return repo


@dataclass
class Inputs:
    path: Path
    project: str
    lock: str
    shelf: dict[str, dict[str, bytes]]

    def extract(self, *, manifest_only: bool = False) -> Identities | IdentityFailure | ReadFailure:
        root = objects(self.path / "root", {SOURCE_COMMIT: {
            "pyproject.toml": self.project.encode(), "uv.lock": self.lock.encode(),
        }})
        source = open_source(root, SOURCE_COMMIT)
        assert not isinstance(source, ReadFailure)
        if manifest_only:
            return reconcile_manifests(source)
        return extract_identities(source, objects(self.path / "shelf", self.shelf))


def inputs(path: Path, *, version: str = "1.2.3", encoded: bool = True) -> Inputs:
    dependencies = ", ".join(f'"{name}=={version}"' for name in reversed(PACKAGES))
    declarations: list[str] = []
    records: list[str] = []
    metadata: list[str] = []
    manifests: dict[str, bytes] = {}
    for name in reversed(PACKAGES):
        tag = f"{'any-agent' if name == 'stream-proc' else name}-v{version}"
        directory = f"packages/{name}"
        selected_directory = directory.replace("/", "%2F") if encoded else directory
        selector = f"{URL}?tag={tag}&subdirectory={selected_directory}"
        declarations.append(f'{name} = {{git = "{URL}", subdirectory = "{directory}", tag = "{tag}"}}')
        records.append(f'[[package]]\nname = "{name}"\nversion = "{version}"\nsource = {{git = "{selector}#{COMMIT}"}}')
        metadata.append(f'{{name = "{name}", git = "{selector}"}}')
        manifests[f"{directory}/pyproject.toml"] = f'[project]\nname = "{name}"\nversion = "{version}"'.encode()
    project = (f'[project]\nname = "task-loop"\nversion = "0.1.0"\ndependencies = [{dependencies}]\n'
               '[tool.uv.sources]\n' + "\n".join(declarations))
    root = ('[[package]]\nname = "task-loop"\nversion = "0.1.0"\nsource = {editable = "."}\n'
            'dependencies = [' + ", ".join(f'{{name = "{name}"}}' for name in PACKAGES) + ']\n'
            '[package.metadata]\nrequires-dist = [' + ", ".join(metadata) + "]")
    return Inputs(path, project, "\n".join([*records, root]), {COMMIT: manifests})


@pytest.mark.parametrize(("version", "encoded"), [("1.2.3", True), ("2.0.7", False)])
def test_complete_extraction_derives_values_and_orders_by_name(tmp_path: Path, version: str, encoded: bool) -> None:
    case = inputs(tmp_path, version=version, encoded=encoded)
    result = case.extract()
    assert isinstance(result, Identities)
    assert result.source_commit == SOURCE_COMMIT
    assert tuple(item.name for item in result.packages) == PACKAGES
    for item in result.packages:
        assert (item.version, item.repository_url, item.subdirectory, item.commit) == (
            version, URL, f"packages/{item.name}", COMMIT,
        )
        assert item.requested_tag == f"{'any-agent' if item.name == 'stream-proc' else item.name}-v{version}"


def test_current_project_and_lock_pins_including_stream_procs_own_version(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    project, lock = (root / "pyproject.toml").read_text(), (root / "uv.lock").read_text()
    files: dict[str, dict[str, bytes]] = {}
    for record in tomllib.loads(lock)["package"]:
        if record["name"] in PACKAGES:
            commit = record["source"]["git"].split("#")[1]
            files.setdefault(commit, {})[f'packages/{record["name"]}/pyproject.toml'] = (
                f'[project]\nname = "{record["name"]}"\nversion = "{record["version"]}"'.encode()
            )
    result = Inputs(tmp_path, project, lock, files).extract()
    assert isinstance(result, Identities)
    assert tuple(item.version for item in result.packages) == ("0.15.0", "0.3.0", "0.22.0", "0.2.1", "0.1.0", "0.9.0")
    assert result.packages[0].commit == result.packages[-1].commit
    assert result.packages[-1].requested_tag == "any-agent-v0.15.0"


def test_manifest_reconciliation_requires_no_shelf_source(tmp_path: Path) -> None:
    case = inputs(tmp_path)
    expected = case.extract()
    case.shelf.clear()
    assert case.extract(manifest_only=True) == expected
    assert isinstance(case.extract(), ReadFailure)
    case.lock = case.lock.replace("tag=any-agent-v1.2.3", "branch=main")
    assert isinstance(case.extract(manifest_only=True), IdentityFailure)


@pytest.mark.parametrize(("field", "old", "new", "detail"), [
    ("project", '"any-agent==1.2.3"', '"any-agent>=1.2.3"', "exact version"),
    ("project", '"any-agent==1.2.3"', '"any-agent==1.2.3", "any-agent==1.2.3"', "observed 2"),
    ("project", '"any-agent==1.2.3"', '"unrelated==1.2.3"', "observed 0"),
    ("project", "any-agent =", "absent-agent =", "source names"),
    ("project", 'tag = "any-agent-v1.2.3"', 'branch = "main"', "tag"),
    ("project", 'subdirectory = "packages/any-agent"', 'subdirectory = "../any-agent"', "subdirectory"),
    ("project", f'git = "{URL}"', 'git = "file:///tmp/shelf"', "repository URL"),
    ("lock", 'name = "any-agent"\nversion = "1.2.3"', 'name = "any-agent"\nversion = "9.0.0"', "version"),
    ("lock", 'name = "any-agent"\nversion', 'name = "absent-agent"\nversion', "observed 0"),
    ("lock", f"#{COMMIT}", "#abc", "immutable commit"),
    ("lock", f"#{COMMIT}", "", "immutable commit"),
    ("lock", "tag=any-agent-v1.2.3", "branch=main", "expected one subdirectory and one tag"),
    ("lock", "tag=any-agent-v1.2.3", "tag=any-agent-v1.2.3&tag=duplicate", "expected one subdirectory and one tag"),
    ("lock", "tag=any-agent-v1.2.3", "tag=other", "source"),
    ("lock", "tag=any-agent-v1.2.3", "tag=", "tag"),
    ("lock", "subdirectory=packages%2Fany-agent", "subdirectory=packages%2Fother", "source"),
    ("lock", "subdirectory=packages%2Fany-agent", "subdirectory=..%2Foutside", "subdirectory"),
    ("lock", "subdirectory=packages%2Fany-agent", "subdirectory=%FF", "utf-8"),
    ("lock", URL, "https://other.invalid/shelf.git", "source"),
    ("lock", '{name = "any-agent"}', '{name = "absent-agent"}', "root dependency"),
    ("lock", '{name = "any-agent"}', '{name = "any-agent", git = "wrong"}', "root dependency selectors"),
    ("lock", '{name = "any-agent", git', '{name = "absent-agent", git', "requires-dist"),
    ("lock", '{name = "any-agent", git', '{name = "any-agent", specifier = "==9.0.0", git', "specifier"),
    ("lock", '[package.metadata]', '[package.unused]', "metadata"),
    ("lock", 'name = "task-loop"', 'name = "absent-task-loop"', "task-loop package"),
    ("lock", 'version = "0.1.0"', 'version = "0.2.0"', "task-loop version"),
    ("lock", 'source = {editable = "."}', 'source = {editable = "elsewhere"}', "task-loop source"),
])
def test_disagreements_are_explained_without_partial_identities(
    tmp_path: Path, field: str, old: str, new: str, detail: str,
) -> None:
    case = inputs(tmp_path)
    setattr(case, field, getattr(case, field).replace(old, new, 1))
    result = case.extract()
    assert isinstance(result, IdentityFailure)
    assert detail in result.explanation
    assert "pyproject.toml" in result.explanation or "uv.lock" in result.explanation
    assert SOURCE_COMMIT in result.explanation


def test_duplicate_locked_package_and_different_shared_commit(tmp_path: Path) -> None:
    case = inputs(tmp_path)
    case.lock += f'\n[[package]]\nname = "any-agent"\nversion = "1.2.3"\nsource = {{git = "{URL}"}}'
    result = case.extract()
    assert isinstance(result, IdentityFailure)
    assert "any-agent" in result.explanation and "observed 2" in result.explanation
    case = inputs(tmp_path)
    case.lock = case.lock.replace(f"#{COMMIT}", "#" + "d" * 40, 1)  # stream-proc is the first record.
    result = case.extract()
    assert isinstance(result, IdentityFailure)
    assert "shared source commit" in result.explanation


@pytest.mark.parametrize("path", ["pyproject.toml", "uv.lock"])
@pytest.mark.parametrize("data", [b"[", b"\xff", b"project = 3", b"package = 'wrong'"])
def test_invalid_documents_have_context(tmp_path: Path, path: str, data: bytes) -> None:
    case = inputs(tmp_path)
    root = objects(tmp_path / "invalid", {SOURCE_COMMIT: {
        "pyproject.toml": case.project.encode(), "uv.lock": case.lock.encode(), path: data,
    }})
    source = open_source(root, SOURCE_COMMIT)
    assert not isinstance(source, ReadFailure)
    result = extract_identities(source, objects(tmp_path / "shelf", case.shelf))
    assert isinstance(result, IdentityFailure)
    assert result.reason == IdentityFailureReason.INVALID_MANIFEST
    assert path in result.explanation and SOURCE_COMMIT in result.explanation


@pytest.mark.parametrize(("field", "observed"), [("name", "other"), ("version", "9.9.9")])
def test_package_manifest_identity_disagrees(tmp_path: Path, field: str, observed: str) -> None:
    case = inputs(tmp_path)
    path = "packages/any-agent/pyproject.toml"
    case.shelf[COMMIT][path] = '[project]\nname = "any-agent"\nversion = "1.2.3"\n'.replace(
        f'{field} = "{"any-agent" if field == "name" else "1.2.3"}"', f'{field} = "{observed}"',
    ).encode()
    result = case.extract()
    assert isinstance(result, IdentityFailure)
    assert all(part in result.explanation for part in ("any-agent", path, COMMIT, "expected", "observed", observed))


@pytest.mark.parametrize("missing_commit", [True, False])
def test_missing_shelf_objects_explain_package_and_path(tmp_path: Path, missing_commit: bool) -> None:
    case = inputs(tmp_path)
    if missing_commit:
        case.shelf.clear()
    else:
        del case.shelf[COMMIT]["packages/any-agent/pyproject.toml"]
    result = case.extract()
    assert isinstance(result, ReadFailure)
    assert result.reason == (ReadFailureReason.NO_COMMIT if missing_commit else ReadFailureReason.NO_PATH)
    assert all(part in result.explanation for part in ("any-agent", "packages/any-agent/pyproject.toml", COMMIT))


@pytest.mark.parametrize("data", [b"[", b"\xff", b'[project]\nname = "any-agent"', b"[project]\nversion = 4"])
def test_invalid_package_manifests_explain_package_and_path(tmp_path: Path, data: bytes) -> None:
    case = inputs(tmp_path)
    path = "packages/any-agent/pyproject.toml"
    case.shelf[COMMIT][path] = data
    result = case.extract()
    assert isinstance(result, IdentityFailure) and result.reason == IdentityFailureReason.INVALID_MANIFEST
    assert all(part in result.explanation for part in ("any-agent", path, COMMIT))


@pytest.mark.parametrize("path", ["pyproject.toml", "uv.lock"])
def test_missing_input_manifest_is_explained(tmp_path: Path, path: str) -> None:
    case = inputs(tmp_path)
    files = {"pyproject.toml": case.project.encode(), "uv.lock": case.lock.encode()}
    del files[path]
    source = open_source(objects(tmp_path / "root", {SOURCE_COMMIT: files}), SOURCE_COMMIT)
    assert not isinstance(source, ReadFailure)
    result = extract_identities(source, objects(tmp_path / "shelf", case.shelf))
    assert isinstance(result, ReadFailure) and result.reason == ReadFailureReason.NO_PATH
    assert path in result.explanation and SOURCE_COMMIT in result.explanation
