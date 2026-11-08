"""`route.py doctor` (and `init`): a plain account table (account, enabled, ready, fix) and the notes about retired config keys; and `config
set|show`.
Nothing here installs, logs in or decides for the owner: the fix column says what to run."""

import json
import os

from delegate.app import env, onboard
from delegate.contracts import codec
from delegate.contracts.history import RefusalRow
from delegate.contracts.json_types import Json, arr, as_str, obj
from delegate.contracts.routing import split_retired
from delegate.contracts.state import Profile


def account_rows(cfg: dict[str, Json]) -> list[dict[str, Json]]:
    """One row per account: {account, enabled, ready, fix}. enabled = the router may use it (not declined; an opt-in account only when the
    profile
    enables it); ready = the machine can run it."""
    ready, chosen = onboard.configured_accounts(cfg), env.profile_accounts()
    rows: list[dict[str, Json]] = []
    accounts = obj(cfg["accounts"])
    for name in accounts:
        enabled = chosen.get(name) != "declined" and (not obj(accounts[name]).get("opt_in") or chosen.get(name) == "enabled")
        rows.append(
            {"account": name, "enabled": enabled, "ready": ready[name], "fix": "" if ready[name] and enabled else onboard.fix_hint(name)}
        )
    return rows


LEFTOVER_FILES = ("claude-credit.key", "ledger.jsonl")  # of the deleted CLAUDE_CREDIT account
LEFTOVER_ENV = "CLAUDE_CREDIT_WORKER_KEY"


def leftovers() -> list[dict[str, str]]:
    """Notes for what the deleted CLAUDE_CREDIT account left behind. Nothing reads or deletes them."""
    out: list[dict[str, str]] = [
        {"id": "unused_file", "file": str(env.config_dir() / n), "say": f"{env.config_dir() / n}: unused, safe to delete."}
        for n in LEFTOVER_FILES
        if (env.config_dir() / n).exists()
    ]
    if os.environ.get(LEFTOVER_ENV):
        out.append({"id": "unused_env", "key": LEFTOVER_ENV, "say": f"env {LEFTOVER_ENV}: unused, safe to unset."})
    return out


def history_loss_notes() -> list[dict[str, str]]:
    """One note when history rows could not be written (the breaker's only input): how many, and where the record is."""
    path = env.history_lost_path()
    try:
        n = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return []
    if not n:
        return []
    return [
        {
            "id": "history_lost",
            "file": str(path),
            "say": f"{n} history rows could not be written (see {path}); the account health "
            "may be missing them. Delete the file once read.",
        }
    ]


def lock_answer_notes() -> list[dict[str, str]]:
    n = sum(1 for row in env.history_store().rows() if isinstance(row, RefusalRow) and row.outcome == "lock")
    if not n:
        return []
    return [
        {
            "id": "lock_answers",
            "say": f"{n} calls were answered `lock` (the state lock stayed held 10 s) "
            "in the last 14 days; with several accounts running, find the holder",
        }
    ]


def notes(cfg: dict[str, Json]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = [
        {
            "id": "retired_key",
            "key": k,
            "file": str(env.config_store().path),
            "say": f"{env.config_store().path}: '{k}' is retired and ignored; safe to delete from config.json.",
        }
        for k in env.retired_keys_present()
    ]
    with open(env.DATA_DIR / "routing.json", encoding="utf-8") as f:
        out += [
            {
                "id": "retired_key",
                "key": k,
                "file": str(env.DATA_DIR / "routing.json"),
                "say": f"{env.DATA_DIR / 'routing.json'}: '{k}' is retired and ignored.",
            }
            for k in split_retired(obj(json.load(f).get("settings")))[1]
        ]
    return out + leftovers() + history_loss_notes() + lock_answer_notes() + smoke_problems(cfg)


PROFILE_VALUES = ("enabled", "declined")
SMOKE_IDS = ("bad_profile", "enabled_not_ready")


def smoke_problems(cfg: dict[str, Json]) -> list[dict[str, str]]:
    """The post-update smoke check: the profile parses and names known accounts with known values, and every account the owner enabled can
    run
    here
    (its CLI resolves, its login is there). Each problem is a note (ids in SMOKE_IDS) with the exact fix; `doctor` exits 1 on any."""
    out: list[dict[str, str]] = []
    raw = env.config_store().read().get("profile") or {}
    try:
        codec.from_json(Profile, raw)
        accounts = obj(obj(raw).get("accounts"))
    except codec.CodecError as e:
        return [
            {
                "id": "bad_profile",
                "say": f'{env.config_store().path}: profile does not parse ({e}). Fix: correct or delete the "profile" key.',
            }
        ]
    for name, v in accounts.items():
        if name not in obj(cfg["accounts"]) or v not in PROFILE_VALUES:
            out.append(
                {
                    "id": "bad_profile",
                    "account": name,
                    "say": f"profile.accounts.{name} = {v!r}: expected an account of {sorted(obj(cfg['accounts']))} "
                    f"set to enabled or declined. Fix: `route.py config set profile.accounts.<ACCOUNT> enabled|declined`.",
                }
            )
    ready = onboard.configured_accounts(cfg)
    out += [
        {"id": "enabled_not_ready", "account": n, "say": f"{n} is enabled but not ready: {onboard.fix_hint(n)}"}
        for n, v in accounts.items()
        if v == "enabled" and n in ready and not ready[n]
    ]
    return out


def doctor(cfg: dict[str, Json]) -> dict[str, Json]:
    return {"v": 1, "harness": env.session_host(), "accounts": account_rows(cfg), "notes": notes(cfg)}


def print_doctor(d: dict[str, Json]) -> None:
    account_rows_, note_rows = [obj(r) for r in arr(d["accounts"])], [obj(n) for n in arr(d["notes"])]
    w = max(len(as_str(r["account"])) for r in account_rows_)
    print(f"{'account':<{w}}  enabled  ready  fix")
    for r in account_rows_:
        print(f"{as_str(r['account']):<{w}}  {'yes' if r['enabled'] else 'no':<7}  {'yes' if r['ready'] else 'no':<5}  {r['fix']}".rstrip())
    for n in note_rows:
        print(f"note [{n['id']}]: {n['say']}")


def cmd_doctor(a: env.Args, cfg: dict[str, Json]):
    d = doctor(cfg)
    if a.json:
        print(json.dumps(d, indent=1))
    else:
        print_doctor(d)
    return 1 if any(obj(n)["id"] in SMOKE_IDS for n in arr(d["notes"])) else 0


def config_set(key: str, value: str) -> dict[str, Json]:
    try:
        val = json.loads(value)
    except ValueError:
        val = value

    parts = key.split(".")
    if parts[:2] == ["profile", "accounts"] and (len(parts) != 3 or val not in PROFILE_VALUES):
        raise SystemExit(f"route.py: config set profile.accounts.<ACCOUNT> enabled|declined (got {key} {value})")

    def put(cur: dict[str, Json]) -> None:
        node = cur
        for part in parts[:-1]:
            nxt = node.get(part)
            if isinstance(nxt, dict):
                node = nxt
            else:
                fresh: dict[str, Json] = {}
                node[part] = fresh
                node = fresh
        node[parts[-1]] = val

    return env.update_config(put)


def config_show(cfg: dict[str, Json]) -> dict[str, Json]:
    p = env.config_dir() / "config.json"
    return {
        "file": str(p),
        "overrides": json.loads(p.read_text(encoding="utf-8")) if p.exists() else {},
        "effective_settings": cfg["settings"],
    }


def cmd_config(a: env.Args, cfg: dict[str, Json]):
    if a.action == "set":
        if not a.key or a.value is None:
            raise SystemExit("route.py: config set KEY VALUE")
        print(json.dumps(config_set(a.key, a.value), indent=1))
    else:
        print(json.dumps(config_show(cfg), indent=1))
    return 0
