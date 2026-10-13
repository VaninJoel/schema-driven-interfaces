"""Angio GUI worker: every attempt is recorded with the outcome it actually had.

Drives the real SimulationWorker.run() (subprocess launch, Zarr monitoring,
metadata, archive) with the CC3D simulation replaced by a tiny script:

* success -> finished signal, success metadata/archive, run_id;
* a crash -> error signal, failed metadata/archive carrying the exit code;
* a hang  -> the wall-clock limit (previously dead code) kills the whole
  process tree and the run is archived as timed_out;
* a rerun into a directory that already holds a store is refused and leaves
  the earlier run's records untouched;
* the analysis view lists only completed runs, at any depth.
"""
import json
import time
import zipfile

import pytest

from harness import load_gui

SUCCESS = """
import numpy as np, zarr, sys
root = zarr.open(sys.argv[1], mode='w')
root.attrs['exp_name'] = 'x'; root.attrs['params'] = {}
for step in (0, 10):
    root.require_group(str(step))['data'] = np.zeros((20, 20, 1, 3))
"""
CRASH = "import sys; sys.stderr.write('boom'); sys.exit(3)"
HANG = """
import pathlib, subprocess, sys, time
c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
pathlib.Path(sys.argv[2]).write_text(str(c.pid))
time.sleep(120)
"""


@pytest.fixture
def angio(qapp):
    return load_gui('angio')


def _worker(gui_pkg, tmp_path, body, exp_name='run1', **params):
    import simulation_worker
    w = simulation_worker.SimulationWorker(
        {'exp_name': exp_name, 'sim_time': 10, **params}, output_dir=str(tmp_path))
    script = tmp_path / f'{exp_name}_fake.py'
    # argv: store path, grandchild pid file
    script.write_text("import sys\nsys.argv[1:] = [r'%s', r'%s']\n%s" % (
        w.zarr_path, tmp_path / 'grandchild.pid', body))
    w._create_simulation_script = lambda: script
    w.signals = {'finished': [], 'error': []}
    w.finished.connect(w.signals['finished'].append)
    w.error.connect(w.signals['error'].append)
    return w


def _records(w):
    meta = json.loads(w.metadata_path.read_text())
    with zipfile.ZipFile(w.exp_dir / f'{w.exp_name}.omex') as zf:
        return meta, zf.namelist(), json.loads(zf.read('status.json'))


def test_success(angio, tmp_path):
    w = _worker(angio, tmp_path, SUCCESS)
    w.run()
    assert w.signals['finished'] and not w.signals['error']
    meta, names, status = _records(w)
    assert meta['simulation_status'] == 'success' and meta['run_id'] == w.run_id
    assert status['status'] == 'success' and status['exit_code'] == 0
    assert status['run_id'] == w.run_id and 'simulation.sedml' in names


def test_crash_is_failed_with_exit_code(angio, tmp_path):
    w = _worker(angio, tmp_path, CRASH)
    w.run()
    assert w.signals['error'] and not w.signals['finished']
    meta, names, status = _records(w)
    assert meta['simulation_status'] == 'failed' and meta['execution']['exit_code'] == 3
    assert status['status'] == 'failed' and status['exit_code'] == 3
    assert 'simulation.sedml' not in names


def test_timeout_kills_tree_and_is_archived_as_timed_out(angio, tmp_path):
    psutil = pytest.importorskip('psutil')
    w = _worker(angio, tmp_path, HANG, run_timeout_seconds=3)
    started = time.time()
    w.run()
    assert time.time() - started < 60
    assert w.signals['error'] and 'wall-clock limit' in w.signals['error'][0]
    grandchild = int((tmp_path / 'grandchild.pid').read_text())
    deadline = time.time() + 10
    while psutil.pid_exists(grandchild) and time.time() < deadline:
        time.sleep(0.2)
    assert not psutil.pid_exists(grandchild), "grandchild survived the timeout"
    meta, names, status = _records(w)
    assert meta['simulation_status'] == 'timed_out' and meta['execution']['timed_out']
    assert status['status'] == 'timed_out' and status['timeout_seconds'] == 3
    assert 'simulation.sedml' not in names


def test_rerun_into_existing_store_is_refused(angio, tmp_path):
    first = _worker(angio, tmp_path, SUCCESS)
    first.run()
    before = first.metadata_path.read_text()
    again = _worker(angio, tmp_path, SUCCESS)
    again.run()
    assert again.signals['error'] and 'Refusing to reuse' in again.signals['error'][0]
    assert first.metadata_path.read_text() == before   # earlier record untouched


def test_analysis_lists_only_completed_runs_at_any_depth(angio, tmp_path):
    import analysis_utils
    for sub, status in (('batch_a/ok', 'success'), ('batch_a/bad', 'failed'),
                        ('batch_b/deep/ok2', 'success'), ('slow', 'timed_out')):
        d = tmp_path / sub
        (d / 'data.zarr').mkdir(parents=True)
        (d / 'run_metadata.json').write_text(json.dumps({'simulation_status': status}))
    cancelled = tmp_path / 'batch_c' / 'stopped'
    (cancelled / 'data.zarr').mkdir(parents=True)
    (cancelled / 'run_metadata.json').write_text(json.dumps({'simulation_status': 'success'}))
    (cancelled / 'cancelled.json').write_text('{}')
    found = analysis_utils.find_experiments(tmp_path)
    assert [p.relative_to(tmp_path).as_posix() for p in found] == ['batch_a/ok', 'batch_b/deep/ok2']
