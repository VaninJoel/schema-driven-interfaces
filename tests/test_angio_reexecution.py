"""What can be reproduced from an Angio archive — executed, not asserted.

Runs the real model (CompuCell3D, about a minute in total) through the GUI's own
SimulationWorker, without a window, and then does what a reader of the archive is
told they can do:

  * the archive built on the worker's path carries its metrics table;
  * a second run with the same parameters and seed stores the same trajectory;
  * the exported native CompuCell3D project, run with the stock script runner
    from the unpacked archive, reproduces every recorded step, the last included;
  * model/run_model.py reproduces every recorded step.

Scope of the claim these tests support: same machine, same software environment,
one processor (the model is fixed at one).

    conda run -n vc --no-capture-output pytest tests/test_angio_reexecution.py -v
"""
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip('cc3d')
pytest.importorskip('PyQt5')

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'angio-gui'))

from vivarium_angio.utils import omex_generator as og  # noqa: E402

SIM_TIME, WRITE_EVERY, SEED = 20, 10, 20261123
RECORDED = [10, 20]


def _run(out_dir, name, **overrides):
    """One run through the GUI worker; returns its archive path."""
    from gui.simulation_worker import SimulationWorker
    params = {'jee': 2.0, 'jem': 2.0, 'lchem': 500.0, 'lsc': 0.1, 'vedir': 1.0,
              'veder': 0.3, 'vesec': 0.3, 'sim_time': float(SIM_TIME),
              'write_frequency': WRITE_EVERY, 'exp_name': name,
              'random_seed': SEED, 'random_seed_origin': 'explicit', **overrides}
    worker = SimulationWorker(params, output_dir=str(out_dir))
    errors = []
    worker.error.connect(errors.append)
    worker.run()
    assert not errors, errors
    archive = Path(out_dir) / name / f'{name}.omex'
    assert archive.exists()
    return archive


def _trajectory(archive, tmp):
    """{step: array} of the Zarr trajectory packed in an archive."""
    store = og.extract_archive_zarr(archive, tmp)
    return {step: np.array(data) for step, data in og._load_zarr_steps(store, strict=True)}


def _child_env():
    return {**os.environ, 'OPENBLAS_NUM_THREADS': '1'}


@pytest.fixture(scope='module')
def archived(tmp_path_factory):
    base = tmp_path_factory.mktemp('angio_rerun')
    archive = _run(base / 'runs', 'first')
    return base, archive, _trajectory(archive, base / 'first_zarr')


def test_worker_archive_is_successful_and_carries_metrics(archived):
    _, archive, trajectory = archived
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        assert json.loads(zf.read('status.json'))['status'] == 'success'
        assert 'metrics.csv' in names and 'simulation.sedml' in names
        assert 'model/angiogenesis.cc3d' in names and 'model/run_model.py' in names
        assert f'<RandomSeed>{SEED}</RandomSeed>' in zf.read(
            'model/Simulation/angiogenesis.xml').decode()
    assert sorted(trajectory) == RECORDED


def test_same_seed_and_parameters_store_the_same_trajectory(archived):
    base, _, first = archived
    second = _trajectory(_run(base / 'runs', 'second'), base / 'second_zarr')
    assert sorted(second) == RECORDED
    for step in RECORDED:
        assert np.array_equal(first[step], second[step]), f'step {step} differs'


def test_a_different_seed_stores_a_different_trajectory(archived):
    base, _, first = archived
    other = _trajectory(_run(base / 'runs', 'other_seed', random_seed=SEED + 1),
                        base / 'other_zarr')
    assert not np.array_equal(first[RECORDED[-1]], other[RECORDED[-1]])


def test_native_project_reproduces_every_recorded_step(archived):
    base, archive, trajectory = archived
    work = base / 'native'
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(work, [n for n in zf.namelist() if n.startswith('model/')])
    done = subprocess.run(
        [sys.executable, '-m', 'cc3d.run_script', '-i', 'model/angiogenesis.cc3d',
         '-o', str(work / 'out')],
        cwd=work, env=_child_env(), capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-2000:]
    snapshots = {int(p.stem.split('_')[1]): np.load(p)
                 for p in (work / 'model' / 'native_output').glob('step_*.npy')}
    # Every archived step is reproduced — the final one too — and equals the archive.
    assert set(RECORDED) <= set(snapshots), sorted(snapshots)
    for step in RECORDED:
        assert np.array_equal(snapshots[step], trajectory[step]), f'step {step} differs'


def test_run_model_script_reproduces_every_recorded_step(archived):
    base, archive, trajectory = archived
    work = base / 'integrated'
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(work, [n for n in zf.namelist() if n.startswith('model/')])
    done = subprocess.run([sys.executable, 'run_model.py'], cwd=work / 'model',
                          env=_child_env(), capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-2000:]
    store = work / 'model' / 'rerun_output' / 'data.zarr'
    rerun = {step: np.array(data) for step, data in og._load_zarr_steps(store, strict=True)}
    assert sorted(rerun) == RECORDED
    for step in RECORDED:
        assert np.array_equal(rerun[step], trajectory[step]), f'step {step} differs'
    # A second invocation must refuse, not mix runs into the same store.
    again = subprocess.run([sys.executable, 'run_model.py'], cwd=work / 'model',
                           env=_child_env(), capture_output=True, text=True, timeout=600)
    assert again.returncode != 0 and 'already exists' in (again.stderr + again.stdout)
