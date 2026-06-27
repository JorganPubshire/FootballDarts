"""Optional Node-based checks for GUI webcam math (static ES modules)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "tests" / "gui_camera_cv.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_gui_camera_cv_js_smoke() -> None:
    r = subprocess.run(
        [shutil.which("node"), str(_SCRIPT)],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_gui_camera_script_exists() -> None:
    assert _SCRIPT.is_file(), "add tests/gui_camera_cv.mjs"
