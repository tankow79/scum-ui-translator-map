"""Start the real application in --smoke-test mode (a subprocess) and require a healthy start.

This is the test that would have caught a crash on start-up (e.g. a missing attribute in the log
parser): unit tests never run the full start-up path, this one does.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(tmp_path, extra_env=None):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", SCUM_DATA_DIR=str(tmp_path))
    env.update(extra_env or {})
    proc = subprocess.run([sys.executable, str(ROOT / "main.py"), "--smoke-test"], env=env, cwd=str(ROOT),
                          capture_output=True, text=True, timeout=180)
    report = (tmp_path / "smoke-result.txt").read_text(encoding="utf-8") if (tmp_path / "smoke-result.txt").exists() else ""
    return proc, report


def test_application_starts_and_passes_self_checks(tmp_path):
    proc, report = _run(tmp_path)
    assert proc.returncode == 0 and report.startswith("OK"), f"{report}\n{proc.stderr[-2000:]}"


def test_smoke_test_uses_isolated_data_and_does_not_touch_real_files(tmp_path):
    proc, report = _run(tmp_path)
    assert report.startswith("OK")
    # data written by the run lives in the isolated folder, never next to the sources
    assert (tmp_path / "config.json").exists()
    assert (tmp_path / "players.json").exists()
