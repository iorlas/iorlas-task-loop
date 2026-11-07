"""DASH-SEC (tl-7i9k.49): the page puts text into HTML in one place. No JS runtime is needed to hold that: the rule reads the sources.
Every HTML sink (dangerouslySetInnerHTML, innerHTML, outerHTML, insertAdjacentHTML, document.write) is the one in ui/kit.js `Md`, whose
text goes through format.js `md`, which escapes with `esc` before it builds a tag. The vendored runtime is not ours and is skipped."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STATIC = Path(__file__).resolve().parents[2] / "packages" / "dash" / "src" / "tldash" / "static"
SINK = re.compile(r"dangerouslySetInnerHTML|\.innerHTML|\.outerHTML|insertAdjacentHTML|document\.write")
OURS = [p for p in sorted(STATIC.rglob("*")) if p.suffix in {".js", ".html"} and "vendor" not in p.parts]


def sinks() -> list[str]:
    return [f"{p.relative_to(STATIC)}:{n}" for p in OURS for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if SINK.search(line)]


def test_the_only_html_sink_is_the_markdown_component():
    found = sinks()
    assert len(found) == 1 and found[0].startswith("js/ui/kit.js:"), f"an HTML sink outside Md: {found}"
    kit = (STATIC / "js" / "ui" / "kit.js").read_text(encoding="utf-8")
    assert "dangerouslySetInnerHTML=${{ __html: md(text) }}" in kit, "the sink must take md(text) and nothing else"


def test_markdown_escapes_before_it_builds_a_tag():
    fmt = (STATIC / "js" / "format.js").read_text(encoding="utf-8")
    assert "export const esc = (s) => String(s).replace(/[&<>\"']/g" in fmt, "esc must cover & < > \" '"
    inline = next(line for line in fmt.splitlines() if line.lstrip().startswith("const inline = "))
    assert re.search(r"=> esc\(s\)\.replace", inline), "md's inline pass must escape its input first"
    body = fmt[fmt.index("export function md("):]
    taken = re.findall(r"\$\{(\w+)", body.split("\n}\n", 1)[0])
    assert set(taken) <= {"list", "kind", "inline"}, f"md interpolates {sorted(set(taken))} into a tag: only the list kind and inline()"
