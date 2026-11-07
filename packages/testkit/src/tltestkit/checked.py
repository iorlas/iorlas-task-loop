"""A test helper's subprocess call that fails with what the process said: `check=True` with capture hides stderr and stdout."""
import subprocess


def run_checked(argv: list[str], cwd, **kw) -> subprocess.CompletedProcess:
    """subprocess.run(argv, capture_output=True); a non-zero exit raises with the command, cwd, exit code, stderr and stdout."""
    done = subprocess.run(argv, cwd=cwd, capture_output=True, check=False, **kw)
    if done.returncode:
        def text(v):
            return v.decode("utf-8", "replace") if isinstance(v, bytes) else v
        raise RuntimeError(f"{' '.join(argv)} (cwd {cwd}) exit {done.returncode}\nstderr: {text(done.stderr)}\nstdout: {text(done.stdout)}")
    return done
