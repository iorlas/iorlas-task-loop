"""The converted-stage list and the name guard of HOSTBAN (tl-e5t0.61); the tests are test_host_ban.py and real/test_host_ban_list.py."""
import ast
import configparser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src" / "taskloop" / "app"
CONTRACT = "importlinter:contract:converted-stages-take-no-host"
HOST_NAMES = {"host", "e", "eng", "engine"}


def converted(text: str | None = None) -> list[str]:
    cp = configparser.ConfigParser(interpolation=None, comment_prefixes=("#",), inline_comment_prefixes=None)
    cp.read_string(text if text is not None else (ROOT / ".importlinter").read_text(encoding="utf-8"))
    names = [m.strip() for m in cp[CONTRACT]["source_modules"].splitlines() if m.strip()]
    stages = {"tlgate": "checks", "tlwork": "review"}
    stages.update({f"tlwork.{stage}": stage for stage in ("review", "plan", "look", "write")})
    return sorted({stages.get(m, m.removeprefix("taskloop.app.") if m.startswith("taskloop.")
                              else m.removeprefix("tl")) for m in names})


def code_dir(stage: str) -> Path:
    """Where a converted stage's code is: its app slice, or its workspace package once it moved."""
    if stage in {"review", "plan", "look", "write"}:
        return ROOT / "packages/work/src/tlwork" / stage
    if stage == "checks":
        return ROOT / "packages/gate/src/tlgate"
    return APP / stage if (APP / stage).is_dir() else ROOT / "packages" / stage / "src" / f"tl{stage}"


def ruff_file(stage: str) -> Path:
    if stage in {"review", "plan", "look", "write"}:
        return ROOT / "packages/work/ruff.toml"
    if stage == "checks":
        return ROOT / "packages/gate/ruff.toml"
    return code_dir(stage) / "ruff.toml" if (APP / stage).is_dir() else ROOT / "packages" / stage / "ruff.toml"


def protocols_of(tree: ast.Module) -> set[str]:
    return {n.name for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef) and any(ast.unparse(b).split(".")[-1] == "Protocol" for b in n.bases)}


def host_problems(source: str, protocols: frozenset[str] = frozenset()) -> list[str]:
    """What breaks the name guard in one module: a host-named `__init__` parameter that is not a declared Protocol, or `self.e =`."""
    tree = ast.parse(source)
    known = protocols_of(tree) | protocols
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "__init__":
            for a in [*node.args.args, *node.args.kwonlyargs]:
                annotation = a.annotation.value if isinstance(a.annotation, ast.Subscript) else a.annotation
                if a.arg in HOST_NAMES and not (annotation is not None and ast.unparse(annotation).split(".")[-1] in known):
                    found.append(f"line {a.lineno}: parameter {a.arg!r} is not a Protocol of the stage")
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store) and node.attr == "e" and ast.unparse(node.value) == "self":
            found.append(f"line {node.lineno}: self.e = ...")
    return found


def stage_files(stage: str) -> list[Path]:
    files = list(code_dir(stage).rglob("*.py"))
    if stage == "checks":
        files.extend((APP / stage).rglob("*.py"))
    return sorted(files)


def stage_protocols(stage: str) -> frozenset[str]:
    names: set[str] = set()
    for f in stage_files(stage):
        names |= protocols_of(ast.parse(f.read_text(encoding="utf-8")))
    return frozenset(names)
