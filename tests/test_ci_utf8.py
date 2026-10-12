"""Catch loss of UTF-8 mode at the CI controller/worker boundary."""

import os
from pathlib import Path
import re
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("workflow", ["ci.yml", "release.yml"])
def test_regression_environment_preserves_utf8_in_child_process(workflow, tmp_path):
    text = (ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
    block = text.split("- name: Run full regression with timings", 1)[1].split("        run:", 1)[0]
    env = os.environ.copy()
    env.pop("PYTHONUTF8", None)
    for key, value in re.findall(r'^\s+(PYTHONUTF8):\s*[\"\']?([01])[\"\']?\s*$', block, re.MULTILINE):
        env[key] = value
    output = tmp_path / "worker.txt"
    worker = (
        "import sys; from pathlib import Path; "
        "print(sys.flags.utf8_mode); "
        f"Path({str(output)!r}).write_text('\\u8a2d\\u5b9a'); "
    )
    controller = f"import subprocess,sys; subprocess.run([sys.executable, '-c', {worker!r}], check=True)"
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", controller],
        env=env, capture_output=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1", "CI worker lost UTF-8 mode"
    assert output.read_bytes() == "設定".encode("utf-8")
