"""adapters/spawner.py on real processes: the Spawner contract (ports/spawner_contract.py) with `sh -c` children."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ports.spawner_contract import SpawnerContract, contract


@contract
class RealSpawnerContract(SpawnerContract):
    __test__ = True

    def command(self, code: int = 0, out: str = "", hang: bool = False) -> list[str]:
        script = f"printf %b '{out}'; " + ("sleep 30" if hang else f"exit {code}")
        return ["sh", "-c", script]
