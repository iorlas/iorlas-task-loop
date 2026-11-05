"""`tl accounts [enable|decline LANE]`: the worker accounts (lanes) delegate can use, what each needs, and the owner's choice for one."""
from taskloop.adapters import delegate as dg


def run(op: str, lane: str) -> int:
    try:
        if op in ("enable", "decline"):
            if not lane:
                print(f"usage: tl accounts {op} LANE")
                return 2
            dg.set_account(lane, op == "enable")
            print(f"{lane}: {'enabled' if op == 'enable' else 'declined'}")
        rows = dg.accounts()
    except (ValueError, SystemExit, OSError) as e:
        print(f"accounts: {e}")
        return 1
    width = max((len(r.lane) for r in rows), default=4)
    print(f"{'lane':<{width}}  enabled  ready  fix")
    for r in rows:
        print(f"{r.lane:<{width}}  {'yes' if r.enabled else 'no':<7}  {'yes' if r.ready else 'no':<5}  {r.fix}".rstrip())
    return 0
