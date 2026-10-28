"""Child process of the race tests: `append LOGPATH N TAG` or `count LOCKROOT COUNTERFILE N`. Run by path, never imported."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.append(str(Path(__file__).resolve().parents[2] / "skills" / "task-loop" / "_vendor"))
from taskloop.contracts import paths  # noqa: E402
from taskloop.contracts.enums import LockWhat  # noqa: E402
from jsonl_log import Jsonl  # noqa: E402
from taskloop.adapters.locks import ProcessLockTable  # noqa: E402


def main(argv: list[str]) -> None:
    if argv[0] == "append":
        j = Jsonl(Path(argv[1]))
        for i in range(int(argv[2])):
            j.append({"who": argv[3], "i": i, "pad": "é" * (i % 50 + 1) * 40})
    else:
        table = ProcessLockTable(paths.ConfigDir(argv[1]))
        counter = Path(argv[2])
        for _ in range(int(argv[3])):
            with table.hold(LockWhat.LAND, "r", "worker", timeout=60):
                n = int(counter.read_text() or 0)  # read, then write: a lost update unless the lock really excludes
                counter.write_text(str(n + 1))


main(sys.argv[1:])
