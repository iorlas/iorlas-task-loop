"""Plan text boundaries, independent of Git and execution state."""

import re
from collections.abc import Iterator
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, ValidationError

from taskloop.attempt_types import PlanContentRule, Rule


class PlanDepth(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"

    @property
    def cap(self) -> int:
        return {self.SMALL: 4_000, self.MEDIUM: 8_000, self.LARGE: 12_000}[self]


class PlanHeader(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    depth: PlanDepth


def _lines(text: str) -> Iterator[str]:
    """Markdown outside fenced code; keep indentation for heading recognition."""
    fence = ""
    for line in text.splitlines():
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if fence:
            if indent <= 3 and stripped.startswith(fence) and not stripped[len(fence):].strip(fence[0] + " \t"):
                fence = ""
            continue
        if indent <= 3 and stripped.startswith(("```", "~~~")):
            marker = stripped[0]
            fence = marker * (len(stripped) - len(stripped.lstrip(marker)))
            yield "    [fenced code]"
        else:
            yield line


def _headings(lines: tuple[str, ...]) -> Iterator[str]:
    previous = ""
    for line in lines:
        atx = re.fullmatch(r" {0,3}#{1,6}(?:[ \t]+(.*)|[ \t]*)", line)
        if atx:
            yield re.sub(r"[ \t]+#+[ \t]*$", "", atx[1] or "").strip()
        elif previous.strip() and re.fullmatch(r" {0,3}(?:=+|-+)[ \t]*", line):
            yield previous.strip()
        previous = line if not line.startswith(("    ", "\t")) else ""


def _change_map(lines: tuple[str, ...]) -> bool:
    waiting = False
    for line in lines:
        if line == "## Change map":
            waiting = True
        elif waiting and line.strip():
            stripped = line.strip()
            if stripped.startswith(("- ", "* ", "+ ")) and stripped[2:].strip():
                return True
            waiting = False
    return False


def validate(text: str, size: int) -> Rule | None:
    """Validate one declared depth, UTF-8 byte budget and structural content rules."""
    lines = tuple(_lines(text))
    depths = [match[1].split(";", 1)[0].strip() for line in lines
              if (match := re.fullmatch(r" {0,3}Depth\s*:\s*(.*)", line, re.IGNORECASE))]
    if len(depths) != 1:
        return PlanContentRule.DEPTH
    try:
        header = PlanHeader.model_validate({"depth": depths[0]})
    except ValidationError:
        return PlanContentRule.DEPTH
    if size > header.depth.cap:
        return "plan_size"
    forbidden = {"as built", "status", "progress", "implementation progress"}
    if any(" ".join(title.partition(":")[0].casefold().split()) in forbidden for title in _headings(lines)):
        return PlanContentRule.HEADING
    return None if _change_map(lines) else PlanContentRule.CHANGE_MAP
