"""Both GUIs default numpy's OpenBLAS to one thread before anything imports numpy,
so every simulation, CC3D and report process they launch inherits it. Otherwise
OpenBLAS commits ~120 MB per logical CPU at import in each parallel run."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

PROBE = (
    "import sys, types, runpy; "
    "stub = types.ModuleType('main_window'); stub.main = lambda: None; "
    "sys.modules['main_window'] = stub; "
    "runpy.run_path(sys.argv[1], run_name='probe'); "
    "import os; print(os.environ.get('OPENBLAS_NUM_THREADS'))"
)


@pytest.mark.parametrize('gui', ['vcornea-gui', 'angio-gui'])
@pytest.mark.parametrize('user_value, expected', [(None, '1'), ('4', '4')])
def test_gui_entry_point_sets_single_threaded_blas(gui, user_value, expected):
    env = {k: v for k, v in os.environ.items() if k != 'OPENBLAS_NUM_THREADS'}
    if user_value is not None:
        env['OPENBLAS_NUM_THREADS'] = user_value
    out = subprocess.run([sys.executable, '-c', PROBE, str(ROOT / gui / 'run_gui.py')],
                         env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == expected
