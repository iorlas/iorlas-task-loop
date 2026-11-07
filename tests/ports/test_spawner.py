"""adapters/spawner.py on the procsim: the Spawner contract (ports/spawner_contract.py) with the children answered in process."""
from ports.spawner_contract import SpawnerContract, contract
from tltestkit import procsim


@contract
class SpawnerOnProcsim(SpawnerContract):
    __test__ = True

    def command(self, code: int = 0, out: str = "", hang: bool = False) -> list[str]:
        name = f"contract-child-{code}-{len(out)}-{hang}"
        procsim.fake(name, procsim.hangs("partial") if hang else procsim.exits(code, out))
        return [name]
