"""Render native import contracts from the source tree, preserving reviewed exceptions."""

import argparse
from configparser import ConfigParser
from pathlib import Path

START = "# BEGIN GENERATED FOLDER CONTRACTS"
END = "# END GENERATED FOLDER CONTRACTS"
PREFIX = "importlinter:contract:"


def modules(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted((root / "src/taskloop").rglob("*.py")):
        parts = path.relative_to(root / "src").with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        result[name] = path
    return result


def slices(root: Path, files: dict[str, Path]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for module, path in files.items():
        folder = path.parent.relative_to(root / "src/taskloop")
        if not folder.parts:
            continue
        if len(folder.parts) > 2:
            raise ValueError(f"Slice exceeds two folder levels: {folder}")
        owner = ".".join(("taskloop", *folder.parts))
        owners.setdefault(owner, []).append(module)
    return owners


def section(name: str, settings: dict[str, str], previous: ConfigParser) -> str:
    heading = PREFIX + name
    lines = [f"[{heading}]"]
    for key, value in settings.items():
        lines.append(f"{key} = {value}" if "\n" not in value else f"{key} =\n{value}")
    if previous.has_option(heading, "ignore_imports"):
        lines.append("ignore_imports =")
        lines.extend(f"    {edge.strip()}" for edge in previous[heading]["ignore_imports"].splitlines() if edge.strip())
    return "\n".join(lines)


def listed(values: list[str]) -> str:
    return "\n" + "\n".join(f"    {value}" for value in sorted(values))


def generate(root: Path, text: str) -> str:
    """Replace generated sections only; never infer exceptions from source imports."""
    previous = ConfigParser(interpolation=None)
    previous.read_string(text)
    files = modules(root)
    sections = []
    for owner, owned in sorted(slices(root, files).items()):
        private = [module for module in owned if module != owner and files[module].name != "api.py"]
        if not private:
            continue
        sections.append(
            section(
                "slice-" + owner,
                {
                    "name": f"Private modules belong to {owner}; api.py is its public door",
                    "type": "protected",
                    "protected_modules": listed(private),
                    "allowed_importers": listed(owned),
                    "as_packages": "False",
                    "unmatched_ignore_imports_alerting": "error",
                },
                previous,
            )
        )
    sections.append(
        section(
            "sqlite-only-in-stores",
            {
                "name": "Only literal store.py modules import SQLite, including connection types",
                "type": "forbidden",
                "source_modules": listed([module for module, path in files.items() if path.name != "store.py"]),
                "forbidden_modules": "sqlite3",
                "as_packages": "False",
                "allow_indirect_imports": "True",
                "unmatched_ignore_alerting": "error",
            },
            previous,
        )
    )
    generated = START + "\n\n" + "\n\n".join(sections) + "\n\n" + END + "\n"
    if START not in text and END not in text:
        return text.rstrip() + "\n\n" + generated
    before, remainder = text.split(START)
    _, after = remainder.split(END)
    return before + generated.rstrip("\n") + after


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args()
    path = arguments.root / ".importlinter"
    print(generate(arguments.root, path.read_text()), end="")


if __name__ == "__main__":
    main()
