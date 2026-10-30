"""The input cap of every delegate call, one table. A brief over its role's cap is refused before anything spawns.

Measured on 2026-10-30 (golden templates in tests/fixtures/prompts, the recorded briefs in tests/fixtures/briefs):
  (Estimates from the templates and recorded briefs, not from live runs: each cap is 2x the worst so a real bead is not refused.)
  planner  PLAN_PROMPT 7.0 KB + the biggest recorded brief 9.8 KB = 16.8 KB; a re-plan adds replan.md (12.5 KB tail) and the amend
           text: about 31 KB at the worst. Cap 64 KB (2x the worst).
  worker   WRITE_PROMPT 3.3 KB + brief + plan + rules (RULES_MAX 3 KB) + the stage's checks: about 19 KB with the biggest brief.
           Cap 40 KB (2x).
  reviewer REVIEW_PROMPT 3.2 KB + brief + plan + the stage diff, which is inlined up to 40000 chars (STAGE_DIFF_CAP): about 56 KB
           at the worst. Cap 112 KB (2x). The verify, look and reflect calls ride the reviewer role and are far smaller.

Which fault: an over-cap brief is a Task fault (ASK_TICKET), not Infra: the machine is fine and a retry sends the same bytes; the
bead's brief is what is too big, and only the owner (or the bead's author) can split or shorten it. Nothing is trimmed here: no
prompt section is marked trimmable at the call (the bead's old comments are already cut to cfg.brief_kb where they are built), so
the call is refused whole and says by how much. Stdlib only."""

from dataclasses import dataclass
from typing import Final

KB: Final = 1024
CAPS: Final = {"planner": 64 * KB, "worker": 40 * KB, "reviewer": 112 * KB}  # bytes of UTF-8 sent per call, by delegate role


@dataclass(frozen=True)
class Over:
    role: str
    size: int
    cap: int

    def why(self, node: str) -> str:
        return (f"ticket: the {node} call's input is {self.size / KB:.1f} KB, over the {self.cap // KB} KB cap of the {self.role} role "
                f"({self.size - self.cap} bytes too many): the bead's brief is too big for one task; nothing was sent")


def check(role: str, text: str) -> Over | None:
    """None when the input fits its role's cap (at the cap is fine); an Over when it does not. A role with no cap is a KeyError."""
    size, cap = len(text.encode("utf-8")), CAPS[role]
    return Over(role, size, cap) if size > cap else None
