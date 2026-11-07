"""The enum migration operates on scratch text and files, without git or processes."""
import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("split_enums", Path(__file__).resolve().parents[2] / "dev/split_enums.py")
assert SPEC is not None and SPEC.loader is not None
split = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(split)

NAMES = ("Step", "Outcome", "Result", "WhyCode", "Cause", "AskKind", "AskClass", "AskStatus", "CheckStatus", "WaitWhat", "LockWhat")
BLOCKS = {name: f'class {name}(StrEnum):\n    """{name} docs."""\n    VALUE = "value"  # trailing\n    # end comment\n'
          for name in NAMES}
SOURCE = '"""Old vocabulary."""\nfrom enum import StrEnum\n\n\n' + "\n\n".join(BLOCKS.values())


def mini_repo(root):
    files = {
        (split.KERNEL / "enums.py").as_posix(): SOURCE,
        "src/plain.py": "from tlkernel.enums import WaitWhat, Step, AskStatus, AskKind, CheckStatus, LockWhat\n",
        "packages/paren.py": "from tlkernel.enums import (\n    Outcome,\n    AskClass,\n)  # noqa: F401\n",
        "dev/local.py": "def f():\n    from tlkernel.enums import Step, WaitWhat  # noqa: PLC0415\n    return Step, WaitWhat\n",
        split.WIRE: "from tlkernel import wire, enums\nfor e in vars(enums).values():\n    print(e)\n",
    }
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return files



def migrate(root, names):
    output = io.StringIO()
    with redirect_stdout(output):
        status = split.migrate(root, names)
    return status, output.getvalue()


def test_split_and_rewrite_are_rerunnable(workdir):
    files = mini_repo(workdir)
    status, report = migrate(workdir, list(files))
    assert status == 0
    assert "names moved: 6" in report
    assert (workdir / "src/plain.py").read_text() == (
        "from tlkernel.askenums import AskKind, AskStatus\n"
        "from tlkernel.checkenums import CheckStatus\n"
        "from tlkernel.enums import Step\n"
        "from tlkernel.lockenums import LockWhat\n"
        "from tlkernel.waitenums import WaitWhat\n"
    )
    assert (workdir / "packages/paren.py").read_text() == (
        "from tlkernel.askenums import AskClass  # noqa: F401\n"
        "from tlkernel.enums import Outcome  # noqa: F401\n"
    )
    assert (workdir / "dev/local.py").read_text() == (
        "def f():\n    from tlkernel.enums import Step  # noqa: PLC0415\n"
        "    from tlkernel.waitenums import WaitWhat  # noqa: PLC0415\n    return Step, WaitWhat\n"
    )
    wire = (workdir / split.WIRE).read_text()
    assert wire.startswith("from tlkernel import askenums, checkenums, enums, lockenums, waitenums, wire\n")
    assert "in (enums, askenums, checkenums, lockenums, waitenums)" in wire
    compile(wire, "wire", "exec")
    for filename, text in split.split_source(SOURCE).items():
        assert (workdir / split.KERNEL / filename).read_text() == text
        assert "from enum import StrEnum\n" in text
        for name in NAMES:
            if split.OWNERS.get(name, "enums") == filename[:-3]:
                assert BLOCKS[name] in text
            else:
                assert f"class {name}(" not in text
    shared = (workdir / split.KERNEL / "enums.py").read_text()
    assert shared.startswith('"""The shared run vocabulary."""')
    paths = list(workdir.rglob("*.py"))
    before = {p: p.read_text() for p in paths}
    status, report = migrate(workdir, [p.relative_to(workdir).as_posix() for p in paths])
    assert status == 0
    assert "files rewritten: 0; names moved: 0" in report
    assert before == {p: p.read_text() for p in paths}
    assert split.rewrite_imports(files["src/plain.py"]) == (workdir / "src/plain.py").read_text()
    schema = "from tlkernel import enums\nvalue = enums.Step\n"
    assert split.rewrite_imports(schema) == schema
    assert split.unsupported(schema) == []


def test_unsupported_uses_exit_one_without_writes(workdir):
    files = mini_repo(workdir)
    bad = workdir / "src/bad.py"
    bad.write_text("from tlkernel import enums\nx = enums.AskKind\n", encoding="utf-8")
    status, report = migrate(workdir, [*files, "src/bad.py"])
    assert status == 1
    assert "src/bad.py:2: enums.AskKind" in report
    assert all((workdir / name).read_text() == text for name, text in files.items())
    assert not (workdir / split.KERNEL / "askenums.py").exists()
    assert split.unsupported("import tlkernel.enums as vocabulary\nx = vocabulary.WaitWhat\n") == [
        "1: import tlkernel.enums", "2: vocabulary.WaitWhat",
    ]
