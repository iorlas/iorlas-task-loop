"""Resource and storm waits, probed between beads without changing NETPAUSE."""
from taskloop.app.loop.env import LoopEnv
from taskloop.contracts.config import LoopConfig
from taskloop.contracts.loop import LoopWait


def blocked(env: LoopEnv, tune: LoopConfig) -> LoopWait | None:
    """Each wait has a measurable wake condition; the next pass probes it again."""
    probe_at = env.now() + max(1, tune.poll)
    if env.free_bytes() < int(tune.min_free_gb * (1 << 30)):
        return LoopWait(reason="low_disk", wake=f"config disk free >= {tune.min_free_gb:g} GB", probe_at=probe_at)
    ram = env.available_mb()
    if ram is not None and ram < tune.min_ram_mb:
        return LoopWait(reason="low_ram", wake=f"available RAM >= {tune.min_ram_mb} MB", probe_at=probe_at)
    storm = env.storm()
    if storm:
        return LoopWait(reason="storm", wake="storm record expires or is cleared", probe_at=probe_at,
                        fingerprint=storm.fingerprint)
    return None
