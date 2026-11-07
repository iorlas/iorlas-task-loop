"""The composition-root ratchet's counter (tl-e5t0.30, docs/design/nodes-and-roots.md): a root only constructs and binds, so it should hold
no rule. In each root file this counts, per kind: `branch` (an if, for, while, try or match statement), `long_function` (a function over
LONG_SLOC source lines) and `sloc` (source lines, blanks and comments left out). The roots are the cli and hook packages, tl.py, and the
modules the `nobody-imports-a-root` contract in .importlinter forbids (launch, wire and run's composition files). Judged on the change
(ratchet_change.py): a rise over the files the change touches fails unless a commit says `Ratchet-allow: root +N reason`; the way down is to
move the rule into a node. Today's numbers are the baseline: nothing is stored, a rise is judged against the merge base."""
import ast
import configparser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LONG_SLOC = 25
BRANCHES = (ast.If, ast.For, ast.While, ast.Try, ast.Match)
BEYOND = ("src/taskloop/cli/", "src/taskloop/hook/", "skills/task-loop/tl.py")


def is_root(rel: str) -> bool:
    if rel.startswith(BEYOND):
        return True
    module = rel.removesuffix(".py").removeprefix("src/").replace("/", ".")
    cp = configparser.ConfigParser(interpolation=None, comment_prefixes=("#",), inline_comment_prefixes=None)
    cp.read(ROOT / ".importlinter", encoding="utf-8")
    forbidden = [m.strip() for m in cp["importlinter:contract:nobody-imports-a-root"]["forbidden_modules"].splitlines() if m.strip()]
    return any(module == m or module.startswith(m + ".") for m in forbidden)


def code_lines(tree: ast.Module) -> set[int]:
    """The lines that hold code: every line of a simple statement, the first line of a compound one; docstrings, blanks and comments are
    not (it reads the tree alone, so the merge base's file and the working one are counted the same way)."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        compound = hasattr(node, "body")
        lines.update([node.lineno] if compound else range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return lines


def file_counts(rel: str, tree: ast.Module) -> dict[str, int]:
    if not rel.endswith(".py") or not is_root(rel):
        return {}
    code = code_lines(tree)
    out = {"branch": 0, "long_function": 0, "sloc": len(code)}
    for node in ast.walk(tree):
        if isinstance(node, BRANCHES):
            out["branch"] += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            span = range(node.lineno, (node.end_lineno or node.lineno) + 1)
            out["long_function"] += sum(1 for ln in span if ln in code) > LONG_SLOC
    return out


def root_counts(root: Path) -> list[tuple[str, dict[str, int]]]:
    """Parse each source file once and retain the roots counted by file_counts."""
    rows = []
    paths = [*sorted((root / "src").rglob("*.py")), root / "skills/task-loop/tl.py"]
    for path in paths:
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            counts = file_counts(rel, ast.parse(path.read_text(encoding="utf-8")))
            if counts:
                rows.append((rel, counts))
    return rows


def totals(root: Path = ROOT) -> dict[str, int]:
    """Sum the per-file root counts without a separate counting pass."""
    rows = root_counts(root)
    return {"files": len(rows), **{key: sum(c[key] for _, c in rows) for key in ("sloc", "branch", "long_function")}}


def offenders(root: Path = ROOT) -> list[str]:
    """Every root file, worst first: 'rel: branches, long functions, sloc' (the list the ratchet is judged against)."""
    rows = []
    for rel, c in root_counts(root):
        said = f"{rel}: {c['branch']} branches, {c['long_function']} long functions, {c['sloc']} sloc"
        rows.append((c["branch"] + 5 * c["long_function"], said))
    return [r for _, r in sorted(rows, reverse=True)]


def declared_attributes(cls: ast.ClassDef) -> set[str]:
    """Attribute declarations in this class alone, excluding unrelated nested classes."""
    names = {node.target.id for node in cls.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)}
    for method in cls.body:
        if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(ast.unparse(d).split(".")[-1] in ("property", "cached_property") for d in method.decorator_list):
            names.add(method.name)
        for statement in ast.walk(method):
            if isinstance(statement, ast.Assign):
                targets = statement.targets
            elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
                targets = [statement.target]
            else:
                continue
            for target in targets:
                for node in ast.walk(target):
                    if (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)
                            and isinstance(node.value, ast.Name) and node.value.id == "self"):
                        names.add(node.attr)
    return names


def engine_attributes(root: Path = ROOT) -> int:
    """Count distinct names Engine and its AST-followed bases declare as annotated class fields,
    self.<name> assignment targets in methods, or @property/@cached_property methods. Ordinary
    methods and unannotated class assignments do not count; inherited names count only once.
    Resolve local classes and imported bases from source, without importing the engine.
    """
    pending = [("taskloop.app.run.engine", "Engine")]
    seen: set[tuple[str, str]] = set()
    names: set[str] = set()
    while pending:
        module, name = pending.pop()
        if (module, name) in seen or (module, name) == ("builtins", "object"):
            continue
        seen.add((module, name))
        path = root / "src" / (module.replace(".", "/") + ".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
        imports = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                prefix = module.split(".")[:-node.level] if node.level else []
                source = ".".join([*prefix, node.module] if node.module else prefix)
                imports.update({a.asname or a.name: (source, a.name) for a in node.names})
        cls = classes[name]
        names.update(declared_attributes(cls))
        for base in cls.bases:
            if isinstance(base, ast.Name) and base.id != "object":
                pending.append(imports.get(base.id, (module, base.id)))
            elif isinstance(base, ast.Attribute):
                pending.append((ast.unparse(base.value), base.attr))
    return len(names)
