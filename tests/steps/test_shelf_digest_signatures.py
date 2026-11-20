"""Semantic committed-source fixtures; no fixture package is imported or executed."""

from collections.abc import Mapping
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import override

import pytest
from git_porcelain import Sha, Tree
from git_porcelain.testing import FakeRepo

from taskloop.shelf_digest.identities import Identities, PackageIdentity
from taskloop.shelf_digest.models import Signature, SignatureFailure, SignatureFailureReason, SignatureKind
from taskloop.shelf_digest.signatures import extract_signatures
from taskloop.shelf_digest.source import ReadFailure, ReadFailureReason, open_source

COMMIT = "a" * 40
NEXT_COMMIT = "b" * 40
IDENTITY = PackageIdentity("example", "1.0", "https://example.invalid/shelf", "example-v1.0", "packages/example", COMMIT)
PREFIX = "packages/example/src/demo/"


class Objects(FakeRepo):
    trees: dict[str, Tree]

    @override
    def tree(self, rev: str) -> Tree | None:
        return self.trees.get(rev.removesuffix("^{commit}"))


def repository(path: Path, commits: dict[str, dict[str, bytes]]) -> Objects:
    repo = Objects.init(path)
    repo.trees = {
        commit: Tree(Sha(commit), lambda files=files: {name: ("100644", Sha("c" * 40)) for name in files}, files.get)
        for commit, files in commits.items()
    }
    return repo


def extract(path: Path, modules: Mapping[str, str | bytes]) -> tuple[Signature, ...] | SignatureFailure | ReadFailure:
    files = {PREFIX + name: data.encode() if isinstance(data, str) else data for name, data in modules.items()}
    return extract_signatures(Identities("d" * 40, (IDENTITY,)), partial(open_source, repository(path, {COMMIT: files})))


def test_aliases_chains_stars_and_exported_submodules(tmp_path: Path) -> None:
    result = extract(tmp_path, {
        "__init__.py": (
            "from .bridge import renamed as API\nfrom . import _impl as tools\n"
            "from pathlib import Path\nfrom ._impl import *\n"
            "__all__ = ('API',) + ('tools',)\n__all__ += ['Value', 'Again']\n"
        ),
        "bridge.py": "from demo._impl import Again as renamed\n",
        "_impl.py": (
            "from typing import TypeAlias\nclass Value:\n    field: int = 3\n"
            "Alias = Value\nAgain = Alias\n_private = 9\n"
            "__all__ = ['Value', 'Again']\n"
        ),
    })
    assert isinstance(result, tuple)
    assert [item.public_name for item in result] == [
        "demo.API", "demo.Again", "demo.Value", "demo.bridge.renamed", "demo.tools", "demo.tools.Again", "demo.tools.Value",
    ]
    for item in result:
        assert item.identity == IDENTITY and item.commit == COMMIT
        if item.kind == SignatureKind.CLASS:
            assert item.defining_name == "demo._impl.Value"
            assert item.path == PREFIX + "_impl.py"
            assert (item.start_line, item.end_line) == (2, 3)
            assert item.declaration == "class Value:\n    field: int = 3"
    module = next(item for item in result if item.public_name == "demo.tools")
    assert module.kind == SignatureKind.MODULE and module.defining_name == "demo._impl"


def test_default_exports_exclude_incidental_imports_and_private_names(tmp_path: Path) -> None:
    result = extract(tmp_path, {
        "__init__.py": "from os import PathLike\nfrom ._impl import f as run\nimport demo._impl as tools\n_hidden = 1\n",
        "_impl.py": "def f(value: int = 2) -> str:\n    raise RuntimeError('never execute')\n",
        "utility.py": "ANSWER = 42\n_private = 0\n",
    })
    assert isinstance(result, tuple)
    assert [(item.public_name, item.defining_name) for item in result] == [
        ("demo.run", "demo._impl.f"), ("demo.tools", "demo._impl"), ("demo.tools.f", "demo._impl.f"),
        ("demo.utility.ANSWER", "demo.utility.ANSWER"),
    ]
    assert result[0].declaration == "def f(value: int=2) -> str:\n    ..."


def test_relative_imports_and_attribute_assignment_aliases(tmp_path: Path) -> None:
    result = extract(tmp_path, {
        "__init__.py": "from .nested import API\n__all__ = ['API']\n",
        "nested/__init__.py": "from .. import _impl as backend\nAPI = backend.work\n__all__ = ['API']\n",
        "_impl.py": "async def work[T](value: T, /, *, count: int = 1) -> T:\n    return value\n",
    })
    assert isinstance(result, tuple)
    assert [item.public_name for item in result] == ["demo.API", "demo.nested.API"]
    assert {item.defining_name for item in result} == {"demo._impl.work"}
    assert result[0].declaration == "async def work[T](value: T, /, *, count: int=1) -> T:\n    ..."


@pytest.mark.parametrize("other", ["pid: int", "pid: str"])
def test_platform_branches_require_equivalent_declarations(tmp_path: Path, other: str) -> None:
    result = extract(tmp_path, {"__init__.py": (
        "import sys\nif sys.platform == 'darwin':\n def alive(pid: int) -> bool:\n  return True\n"
        f"else:\n def alive({other}) -> bool:\n  return False\n"
    )})
    if other == "pid: str":
        assert isinstance(result, SignatureFailure) and "platform" in result.explanation
    else:
        assert isinstance(result, tuple) and len(result) == 1
        assert (result[0].start_line, result[0].end_line) == (3, 7)


def test_star_cycles_keep_reachable_declarations(tmp_path: Path) -> None:
    result = extract(tmp_path, {
        "__init__.py": "from .left import *\n",
        "left.py": "from .right import *\nLEFT = 1\n",
        "right.py": "from .left import *\nRIGHT = 2\n",
    })
    assert isinstance(result, tuple)
    assert [(item.public_name, item.defining_name) for item in result] == [
        ("demo.LEFT", "demo.left.LEFT"), ("demo.RIGHT", "demo.right.RIGHT"),
        ("demo.left.LEFT", "demo.left.LEFT"), ("demo.left.RIGHT", "demo.right.RIGHT"),
        ("demo.right.LEFT", "demo.left.LEFT"), ("demo.right.RIGHT", "demo.right.RIGHT"),
    ]


def test_star_and_direct_bindings_follow_source_order(tmp_path: Path) -> None:
    result = extract(tmp_path, {
        "__init__.py": "VALUE = 0\nfrom ._first import *\nfrom ._second import *\nLOCAL = 4\n",
        "_first.py": "VALUE = 1\nLOCAL = 2\n",
        "_second.py": "VALUE = 3\n",
    })
    assert isinstance(result, tuple)
    assert [(item.public_name, item.declaration) for item in result] == [("demo.LOCAL", "LOCAL = 4"), ("demo.VALUE", "VALUE = 3")]


def test_later_import_replaces_assignment_alias(tmp_path: Path) -> None:
    result = extract(tmp_path, {
        "__init__.py": "OLD = 1\nAlias = OLD\nfrom ._impl import NEW as Alias\n__all__ = ['Alias']\n",
        "_impl.py": "NEW = 2\n",
    })
    assert isinstance(result, tuple) and len(result) == 1
    assert (result[0].defining_name, result[0].declaration) == ("demo._impl.NEW", "NEW = 2")


def test_assignment_alias_to_star_reexport(tmp_path: Path) -> None:
    result = extract(tmp_path, {
        "__init__.py": "from ._impl import *\nAlias = Original\n__all__ = ['Alias']\n",
        "_impl.py": "class Original: ...\n",
    })
    assert isinstance(result, tuple) and len(result) == 1
    assert result[0].defining_name == "demo._impl.Original"
    assert result[0].declaration == "class Original:\n    ..."


def test_package_binding_takes_precedence_over_same_named_submodule(tmp_path: Path) -> None:
    result = extract(tmp_path, {
        "__init__.py": "from ._impl import work\n",
        "_impl.py": "def work(): ...\n",
        "work.py": "VALUE = 1\n",
        "consumer.py": "from demo import work as run\n",
    })
    assert isinstance(result, tuple)
    consumer = next(item for item in result if item.public_name == "demo.consumer.run")
    assert consumer.defining_name == "demo._impl.work" and consumer.kind == SignatureKind.FUNCTION


def test_tuple_assignments_and_nonbinding_attribute_writes(tmp_path: Path) -> None:
    result = extract(tmp_path, {"__init__.py": "LEFT, RIGHT = (1, 2)\nexternal.setting = 3\n"})
    assert isinstance(result, tuple)
    assert [(item.public_name, item.declaration) for item in result] == [
        ("demo.LEFT", "LEFT, RIGHT = (1, 2)"), ("demo.RIGHT", "LEFT, RIGHT = (1, 2)"),
    ]


def test_module_cycles_terminate(tmp_path: Path) -> None:
    result = extract(tmp_path, {"__init__.py": "from . import child\n", "child.py": "import demo as parent\nVALUE = 1\n"})
    assert isinstance(result, tuple)
    assert [item.public_name for item in result] == [
        "demo.child", "demo.child.VALUE", "demo.child.parent", "demo.child.parent.child",
    ]


@pytest.mark.parametrize("modules", [
    {"__init__.py": "from .left import lost\n", "left.py": "from . import lost\n"},
    {"__init__.py": "A = B\nB = A\n"},
    {"__init__.py": "__all__ = ['absent']\n"},
    {"__init__.py": "from os import PathLike\n__all__ = ['PathLike']\n"},
    {"__init__.py": "from .missing import absent\n"},
    {"__init__.py": "from .missing import *\n"},
])
def test_unresolved_exports_return_an_explanation(tmp_path: Path, modules: dict[str, str]) -> None:
    result = extract(tmp_path, modules)
    assert isinstance(result, SignatureFailure) and result.reason == SignatureFailureReason.UNRESOLVED_EXPORT
    assert COMMIT in result.explanation and PREFIX in result.explanation


@pytest.mark.parametrize("text", [
    "__all__ = make_names()", "__all__ = ['X']\n__all__.append('Y')", "if flag:\n    __all__ = ['X']",
    "__all__: list[str]", "__all__ = ['X']\n__all__ += names", "__all__ = ['X', 3]",
])
def test_dynamic_exports_fail_without_partial_records(tmp_path: Path, text: str) -> None:
    result = extract(tmp_path, {"__init__.py": "X = 1\n" + text + "\n"})
    assert isinstance(result, SignatureFailure) and result.reason == SignatureFailureReason.UNSUPPORTED_EXPORT
    assert "__all__" in result.explanation and COMMIT in result.explanation


@pytest.mark.parametrize("data", [b"def broken(:", b"\xff", b"X = '\x00'", b"# coding: no-such-encoding\n"])
def test_invalid_source_is_explained(tmp_path: Path, data: bytes) -> None:
    result = extract(tmp_path, {"__init__.py": data})
    assert isinstance(result, SignatureFailure) and result.reason == SignatureFailureReason.INVALID_SOURCE
    assert PREFIX + "__init__.py" in result.explanation and COMMIT in result.explanation


def test_declaration_forms_retain_semantics_without_bodies(tmp_path: Path) -> None:
    result = extract(tmp_path, {"__init__.py": (
        "from typing import TypeAlias, overload\n"
        "type Items[T] = tuple[T, ...]\nLegacy: TypeAlias = dict[str, int]\n"
        "LIMIT: int = 4\nFIRST = SECOND = 8\n"
        "@overload\ndef choose(x: int, /) -> int: ...\n"
        "@overload\ndef choose(x: str, /) -> str: ...\n"
        "def choose(x):\n    return x\n"
        "@decorate(flag=True)\nasync def consume[T: str](x: T = 'a', /, *args: T, enabled: bool = True, **kw: int) -> T:\n"
        "    'docstring'\n    raise RuntimeError\n"
        "@dataclass(frozen=True)\nclass Box[T](Base[T], metaclass=Meta):\n"
        "    'class docs'\n    value: T\n    count: int = 1\n    _hidden = 2\n"
        "    def __init__(self, value: T) -> None:\n        self.value = value\n"
        "    @property\n    def item(self) -> T:\n        return self.value\n"
        "    def _private(self): ...\n"
        "raise RuntimeError('source must never execute')\n"
    )})
    assert isinstance(result, tuple)
    actual = {item.public_name: (item.kind, item.declaration) for item in result}
    assert actual == {
        "demo.Items": (SignatureKind.TYPE_ALIAS, "type Items[T] = tuple[T, ...]"),
        "demo.Legacy": (SignatureKind.TYPE_ALIAS, "Legacy: TypeAlias = dict[str, int]"),
        "demo.LIMIT": (SignatureKind.CONSTANT, "LIMIT: int = 4"),
        "demo.FIRST": (SignatureKind.CONSTANT, "FIRST = 8"),
        "demo.SECOND": (SignatureKind.CONSTANT, "SECOND = 8"),
        "demo.choose": (SignatureKind.FUNCTION,
                        "@overload\ndef choose(x: int, /) -> int:\n    ...\n"
                        "@overload\ndef choose(x: str, /) -> str:\n    ...\ndef choose(x):\n    ..."),
        "demo.consume": (SignatureKind.FUNCTION,
                         "@decorate(flag=True)\nasync def consume[T: str](x: T='a', /, *args: T, "
                         "enabled: bool=True, **kw: int) -> T:\n    ..."),
        "demo.Box": (SignatureKind.CLASS,
                     "@dataclass(frozen=True)\nclass Box[T](Base[T], metaclass=Meta):\n    value: T\n    count: int = 1\n"
                     "\n    def __init__(self, value: T) -> None:\n        ...\n"
                     "\n    @property\n    def item(self) -> T:\n        ..."),
    }
    consume = next(item for item in result if item.public_name == "demo.consume")
    assert (consume.start_line, consume.end_line) == (12, 15)


def test_source_encoding_cookie_is_respected(tmp_path: Path) -> None:
    result = extract(tmp_path, {"__init__.py": b"# coding: latin-1\nLABEL = 'caf\xe9'\n"})
    assert isinstance(result, tuple) and result[0].declaration == "LABEL = 'café'"


def test_type_comments_are_retained(tmp_path: Path) -> None:
    result = extract(tmp_path, {"__init__.py": "COUNT = 1  # type: int\ndef call(value):  # type: (int) -> str\n    return str(value)\n"})
    assert isinstance(result, tuple)
    assert [item.declaration for item in result] == [
        "COUNT = 1 # type: int", "def call(value): # type: (int) -> str\n    ...",
    ]


def test_pin_changes_and_body_only_edits(tmp_path: Path) -> None:
    old = {PREFIX + "__init__.py": b"def call(value: int = 1) -> int:\n    return value\n"}
    new = {PREFIX + "__init__.py": b"def call(value: str = 'new') -> str:\n    return value.upper()\n"}
    bodies = {PREFIX + "__init__.py": b"def call(value: int = 1) -> int:\n    raise RuntimeError\n"}
    repo = repository(tmp_path, {COMMIT: old, NEXT_COMMIT: new, "e" * 40: bodies})
    original = extract_signatures(Identities("d" * 40, (IDENTITY,)), partial(open_source, repo))
    changed_identity = replace(IDENTITY, version="2.0", requested_tag="example-v2.0", commit=NEXT_COMMIT)
    changed = extract_signatures(Identities("d" * 40, (changed_identity,)), partial(open_source, repo))
    body = extract_signatures(Identities("d" * 40, (replace(IDENTITY, commit="e" * 40),)), partial(open_source, repo))
    assert isinstance(original, tuple) and isinstance(changed, tuple) and isinstance(body, tuple)
    assert original[0].declaration == body[0].declaration == "def call(value: int=1) -> int:\n    ..."
    assert changed[0].declaration == "def call(value: str='new') -> str:\n    ..."
    assert changed[0].identity == changed_identity and changed[0].commit == NEXT_COMMIT
    assert changed[0].public_name == original[0].public_name == "demo.call"


def test_repeated_and_reordered_inputs_are_equal(tmp_path: Path) -> None:
    other = replace(IDENTITY, name="another", subdirectory="packages/another")
    files = {PREFIX + "__init__.py": b"Z = 1\nA = 2\n", "packages/another/src/other.py": b"C = 3\n"}
    forward = repository(tmp_path / "forward", {COMMIT: files})
    reverse = repository(tmp_path / "reverse", {COMMIT: dict(reversed(list(files.items())))})
    identities = Identities("d" * 40, (IDENTITY, other))
    first = extract_signatures(identities, partial(open_source, forward))
    assert isinstance(first, tuple)
    assert first == extract_signatures(identities, partial(open_source, forward))
    assert first == extract_signatures(replace(identities, packages=(other, IDENTITY)), partial(open_source, reverse))
    assert [(item.identity.name, item.public_name) for item in first] == [
        ("another", "other.C"), ("example", "demo.A"), ("example", "demo.Z"),
    ]


def test_missing_module_and_commit_failures(tmp_path: Path) -> None:
    missing = extract(tmp_path / "empty", {})
    assert isinstance(missing, SignatureFailure) and missing.reason == SignatureFailureReason.NO_MODULE
    assert COMMIT in missing.explanation
    result = extract_signatures(Identities("d" * 40, (IDENTITY,)), partial(open_source, repository(tmp_path / "missing", {})))
    assert isinstance(result, ReadFailure) and result.reason == ReadFailureReason.NO_COMMIT


def test_later_package_failure_does_not_return_earlier_records(tmp_path: Path) -> None:
    earlier = replace(IDENTITY, name="aaa", subdirectory="packages/aaa")
    repo = repository(tmp_path, {COMMIT: {"packages/aaa/src/aaa.py": b"VALUE = 1\n", PREFIX + "__init__.py": b"__all__ = ['missing']"}})
    result = extract_signatures(Identities("d" * 40, (earlier, IDENTITY)), partial(open_source, repo))
    assert isinstance(result, SignatureFailure) and result.reason == SignatureFailureReason.UNRESOLVED_EXPORT
    assert "demo.missing" in result.explanation


def test_unreadable_committed_source_retains_read_failure(tmp_path: Path) -> None:
    repo = repository(tmp_path, {})
    repo.trees = {COMMIT: Tree(Sha(COMMIT), lambda: {PREFIX + "__init__.py": ("120000", Sha("c" * 40))}, lambda _: b"target")}
    result = extract_signatures(Identities("d" * 40, (IDENTITY,)), partial(open_source, repo))
    assert isinstance(result, ReadFailure) and result.reason == ReadFailureReason.NOT_A_FILE
    assert PREFIX + "__init__.py" in result.explanation and COMMIT in result.explanation
