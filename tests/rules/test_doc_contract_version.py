"""The contract number the docs name is the one delegate speaks (`CONTRACT` in src/delegate/contracts/wire.py)."""
import re
from pathlib import Path

from tltestkit.case import Case

ROOT = Path(__file__).resolve().parents[2]
DOCS = ("docs/dev/integrations.md", "docs/contracts/delegate-api.md", "README.md", "CLAUDE.md")
NAMED = re.compile(r"\bcontract (\d+)\b")


def spoken() -> int:
    found = re.search(r"^CONTRACT = (\d+)$", (ROOT / "src/delegate/contracts/wire.py").read_text(encoding="utf-8"), re.M)
    assert found, "wire.py no longer declares `CONTRACT = N`"
    return int(found.group(1))


class DocContractVersion(Case):
    def test_every_contract_number_a_doc_names_is_the_wire_contract(self):
        want, seen = spoken(), 0
        for doc in DOCS:
            for n in NAMED.findall((ROOT / doc).read_text(encoding="utf-8")):
                seen += 1
                assert int(n) == want, f"{doc} names contract {n}; delegate speaks {want}"
        assert seen, "no doc names the contract: the rule would pass on nothing"
