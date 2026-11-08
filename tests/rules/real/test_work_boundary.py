"""The work boundary rejects a stage import using the production contract."""
import configparser
import contextlib
import os
import resource
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def sampled(text: str) -> str:
    return (text.replace("taskloop", "sample").replace("tlwork", "sample").replace("tlasks", "sample")
            .replace("tlland", "sample"))


@pytest.mark.parametrize("stage_import", [False, True])
def test_work_reaches_no_stage(workdir, stage_import):
    config = configparser.ConfigParser()
    config.read(ROOT / ".importlinter")
    contract = next(config[s] for s in config.sections() if config[s].get("name") == "domain/work reaches no stage")
    synthetic = configparser.ConfigParser()
    synthetic["importlinter"] = {"root_package": "sample"}
    synthetic["importlinter:contract:work"] = {
        key: sampled(value) if key in {"source_modules", "forbidden_modules"} else value
        for key, value in contract.items()
    }
    modules = (contract["source_modules"] + contract["forbidden_modules"]).split()
    for module in modules:
        folder = workdir.joinpath(*sampled(module).split("."))
        folder.mkdir(parents=True, exist_ok=True)
        for package in (folder, *folder.parents):
            if package == workdir:
                break
            (package / "__init__.py").touch()
    (workdir / "sample/work/policy.py").write_text("import sample.plan\n" if stage_import else "VALUE = 1\n")
    config_path = workdir / "imports.ini"
    with config_path.open("w") as stream:
        synthetic.write(stream)
    pins = tomllib.loads((ROOT / "mise.toml").read_text(encoding="utf-8"))["tools"]
    # Share the tool env with the justfile rules recipe; runtests.isolated_env preserves the real uv cache across HOME isolation.
    # The bare mise shim fails outside the repo cwd.
    lint = ["uv", "tool", "run", "--with", "msgspec", "--from", f"import-linter@{pins['pipx:import-linter']}", "lint-imports"]

    def lift_address_space_cap():
        # The Rust child aborts under the inherited address-space cap.
        if hasattr(resource, "RLIMIT_AS"):
            with contextlib.suppress(OSError, ValueError):
                _, hard = resource.getrlimit(resource.RLIMIT_AS)
                resource.setrlimit(resource.RLIMIT_AS, (hard, hard))

    ran = subprocess.run(
        [*lint, "--config", str(config_path), "--no-cache"],
        cwd=workdir, env={**os.environ, "PYTHONPATH": str(workdir)},
        text=True, capture_output=True, check=False,
        preexec_fn=lift_address_space_cap,
    )
    output = ran.stdout + ran.stderr
    assert (ran.returncode != 0) == stage_import, output
    assert contract["name"] in output
