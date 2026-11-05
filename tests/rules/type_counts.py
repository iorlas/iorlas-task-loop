"""The escapes from the type checker in one module's source, and the rule over a change: explicit `Any`, `# pyrefly: ignore`,
`# type: ignore` and `cast(`. No total is stored; a change may not add more than it removes."""
import ast
import io
import tokenize
from collections.abc import Mapping

KINDS = ("any", "pyrefly_ignore", "type_ignore", "cast")


def count_source(text: str) -> dict[str, int]:
    """The four counts in one module's source: Any names and attributes outside imports, ignore comments, cast calls."""
    out = dict.fromkeys(KINDS, 0)
    for node in ast.walk(ast.parse(text)):
        if (isinstance(node, ast.Name) and node.id == "Any") or (isinstance(node, ast.Attribute) and node.attr == "Any"):
            out["any"] += 1
        elif isinstance(node, ast.Call):
            fn = node.func
            if (isinstance(fn, ast.Name) and fn.id == "cast") or (isinstance(fn, ast.Attribute) and fn.attr == "cast"):
                out["cast"] += 1
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            body = tok.string.lstrip("# ").lower()
            out["pyrefly_ignore"] += body.startswith("pyrefly: ignore")
            out["type_ignore"] += body.startswith("type: ignore")
    return out


def change_problems(before: Mapping[str, str], after: Mapping[str, str]) -> list[str]:
    """{path: source} of the changed files at the base and now (a new file is absent from `before`, a deleted one from `after`).
    Summed over the change, so moving code between files is free and adding an escape is not."""
    total_before = dict.fromkeys(KINDS, 0)
    total_after = dict.fromkeys(KINDS, 0)
    for texts, total in ((before, total_before), (after, total_after)):
        for text in texts.values():
            for kind, n in count_source(text).items():
                total[kind] += n
    return [f"{kind}: this change adds {total_after[kind] - total_before[kind]} net ({total_before[kind]} -> {total_after[kind]} in the "
            "files it touches); remove one" for kind in KINDS if total_after[kind] > total_before[kind]]
