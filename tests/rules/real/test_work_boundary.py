"""The work boundary rejects a stage import using the production contract."""
import configparser
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("stage_import", [False, True])
def test_work_reaches_no_stage(workdir, stage_import):
    config = configparser.ConfigParser()
    config.read(Path(__file__).resolve().parents[3] / ".importlinter")
    contract = next(config[s] for s in config.sections() if config[s].get("name") == "domain/work reaches no stage")
    synthetic = configparser.ConfigParser()
    synthetic["importlinter"] = {"root_package": "sample"}
    synthetic["importlinter:contract:work"] = {
        key: value.replace("taskloop", "sample") if key in {"source_modules", "forbidden_modules"} else value
        for key, value in contract.items()
    }
    modules = (contract["source_modules"] + contract["forbidden_modules"]).split()
    for module in modules:
        folder = workdir.joinpath(*module.replace("taskloop", "sample").split("."))
        folder.mkdir(parents=True, exist_ok=True)
        for package in (folder, *folder.parents):
            if package == workdir:
                break
            (package / "__init__.py").touch()
    (workdir / "sample/domain/work/policy.py").write_text("import sample.domain.plan\n" if stage_import else "VALUE = 1\n")
    config_path = workdir / "imports.ini"
    with config_path.open("w") as stream:
        synthetic.write(stream)
    executable = shutil.which("lint-imports")
    assert executable, "lint-imports must be installed"
    ran = subprocess.run(
        [executable, "--config", str(config_path), "--no-cache"],
        cwd=workdir, env={**os.environ, "PYTHONPATH": str(workdir)},
        text=True, capture_output=True, check=False,
    )
    output = ran.stdout + ran.stderr
    assert (ran.returncode != 0) == stage_import, output
    assert contract["name"] in output
