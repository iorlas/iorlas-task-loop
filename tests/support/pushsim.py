"""A land command (`land=` in the engine config) as a procsim fake: it counts its runs in a file, fails the first ones with a cut
connection, and otherwise runs the real `git push` (git is the one real process these tests keep: the server's state is the subject)."""
import subprocess
from pathlib import Path

from support import procsim

CUT = "error: RPC failed; curl 56 Send failure: Broken pipe\nfatal: the remote end hung up unexpectedly\n"


def pusher(text: str, count: Path, cut_first: int = 0, then_fail: str = "", cut: str = CUT) -> str:
    """Register the land command `text`. Run n (from 0) writes n+1 to `count`; the first `cut_first` runs print `cut` and exit 1
    without pushing; after that it pushes for real, and exits 1 with `then_fail` when that is given (a push the server took)."""
    def run(cwd, env):
        n = int(count.read_text()) if count.exists() else 0
        count.write_text(str(n + 1))
        if n < cut_first:
            return 1, cut
        done = subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=cwd, capture_output=True, text=True, check=False)
        return (1, then_fail) if then_fail else (done.returncode, done.stdout + done.stderr)
    return procsim.fake(text, run)
