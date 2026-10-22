"""Run-lifecycle tests for VCorneaProcess.next_update().

Drives the real launch / monitor / collect / archive path with CompuCell3D
replaced by a tiny Python subprocess, so each outcome the paper describes
(success, failure, timeout) is exercised end to end in seconds:

  * every attempt gets a run_id, exit code, duration, run_metadata.json, an
    experiment-log row and a status-typed archive;
  * the archive's SED-ML seed and bundled model are THIS replicate's
    (generated Parameters.py + seeded CC3DML), not the source project's;
  * a timed-out replicate has its whole process tree killed and is archived
    as timed_out.

Run:  conda run -n vc --no-capture-output pytest vivarium-vcornea/test_run_lifecycle.py -v
"""
import csv
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
from vivarium_vcornea.utils import experiment_log

SIM_DAYS = 1
SIM_MCS = SIM_DAYS * 240

FAKE_CC3D = {
    'success': f"open('cell_count_{SIM_MCS}.csv', 'w').write('Time,Stem\\n0,1\\n')",
    'crash': "import sys; sys.stderr.write('boom'); sys.exit(3)",
    # Spawns a grandchild, records its pid, then hangs: the timeout must kill both.
    'hang': ("import subprocess, sys, time; "
             "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
             "open('child.pid', 'w').write(str(c.pid)); time.sleep(120)"),
}


def _fake_launcher(mode):
    def _run(self, project_path, output_dir):
        stdout_log = open(output_dir / "stdout.log", 'w')
        stderr_log = open(output_dir / "stderr.log", 'w')
        proc = subprocess.Popen([sys.executable, '-c', FAKE_CC3D[mode]],
                                cwd=os.fspath(output_dir),
                                stdout=stdout_log, stderr=stderr_log, text=True)
        return proc, stdout_log, stderr_log
    return _run


def _run_batch(tmp_path, monkeypatch, mode, **params):
    monkeypatch.setattr(VCorneaProcess, '_run_cc3d_simulation', _fake_launcher(mode))
    proc = VCorneaProcess({'output_base_dir': str(tmp_path), 'SimTime': SIM_DAYS,
                           'replicates': 1, **params})
    states = {'inputs': {k: v['_default'] for k, v in proc.ports_schema()['inputs'].items()}}
    out = proc.next_update(1, states)['outputs']
    reps = sorted(out['replicate_results'], key=lambda r: r['replicate_id'])
    metas = [json.loads((Path(r['output_directory']) / 'run_metadata.json').read_text())
             for r in reps]
    return out, reps, metas


def _archive(rep, meta):
    return zipfile.ZipFile(Path(rep['output_directory']) / meta['omex_archive'])


def _log_rows(tmp_path):
    with open(tmp_path / experiment_log.LOG_NAME, newline='', encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


def test_success_records_identity_and_this_replicates_seed(tmp_path, monkeypatch):
    out, reps, metas = _run_batch(tmp_path, monkeypatch, 'success')
    rep, meta = reps[0], metas[0]

    assert out['simulation_success'] is True
    assert meta['simulation_status'] == 'success'
    assert re.fullmatch(r'[0-9a-f]{32}', meta['run_id'])
    assert meta['exit_code'] == 0 and meta['duration_seconds'] >= 0
    assert meta['simulation_config']['vcornea_project_path'] not in ('None', '')
    seed = meta['random_seed']
    assert isinstance(seed, int) and seed > 0

    with _archive(rep, meta) as zf:
        names = zf.namelist()
        sedml = zf.read('simulation.sedml').decode()
        params = zf.read('model/Simulation/Parameters.py').decode()
        xml = next(zf.read(n).decode() for n in names
                   if n.startswith('model/Simulation/') and n.endswith('.xml')
                   and b'<Potts>' in zf.read(n))
        steppables = zf.read('model/Simulation/vCornea_v2Steppables.py').decode()
        status = json.loads(zf.read('status.json'))
    # The executable description and the bundled model are this replicate's.
    assert f'value="{seed}"' in sedml
    assert f'random_seed={seed}' in params
    assert f'SimTime={SIM_MCS}' in params
    assert f'<RandomSeed>{seed}</RandomSeed>' in xml
    # ...but not the copy's machine-specific output redirect.
    assert str(tmp_path).replace('\\', '/') not in steppables
    assert status['run_id'] == meta['run_id'] and status['exit_code'] == 0

    [row] = _log_rows(tmp_path)
    assert row['run_id'] == meta['run_id']
    assert row['status'] == 'success' and row['random_seed'] == str(seed)


def test_pinned_seed_applies_to_first_replicate_only(tmp_path, monkeypatch):
    _, reps, metas = _run_batch(tmp_path, monkeypatch, 'success',
                                replicates=2, random_seed=4242)
    assert [m['random_seed_origin'] for m in metas] == ['explicit', 'drawn']
    assert metas[0]['random_seed'] == 4242 and metas[1]['random_seed'] != 4242
    for rep, meta in zip(reps, metas):
        with _archive(rep, meta) as zf:
            assert f'value="{meta["random_seed"]}"' in zf.read('simulation.sedml').decode()
    assert len({m['run_id'] for m in metas}) == 2
    assert len(_log_rows(tmp_path)) == 2


def test_failed_run_keeps_its_evidence(tmp_path, monkeypatch):
    out, reps, metas = _run_batch(tmp_path, monkeypatch, 'crash')
    rep, meta = reps[0], metas[0]
    run_dir = Path(rep['output_directory'])

    assert out['simulation_success'] is False
    assert meta['simulation_status'] == 'failed' and meta['exit_code'] == 3
    assert meta['duration_seconds'] is not None
    assert (run_dir / 'Parameters.py').exists()      # generated spec kept
    assert (run_dir / 'stderr.log').read_text() == 'boom'
    with _archive(rep, meta) as zf:
        assert 'simulation.sedml' not in zf.namelist()
        status = json.loads(zf.read('status.json'))
        assert 'Parameters.py' in zf.namelist()
    assert status['status'] == 'failed' and status['exit_code'] == 3
    assert _log_rows(tmp_path)[0]['status'] == 'failed'


def test_timeout_kills_tree_and_is_archived_as_timed_out(tmp_path, monkeypatch):
    psutil = pytest.importorskip('psutil')
    out, reps, metas = _run_batch(tmp_path, monkeypatch, 'hang', run_timeout_seconds=3)
    rep, meta = reps[0], metas[0]

    assert meta['simulation_status'] == 'timed_out' and meta['timed_out'] is True
    assert meta['run_timeout_seconds'] == 3
    child_pid = int((Path(rep['output_directory']) / 'child.pid').read_text())
    deadline = time.time() + 10
    while psutil.pid_exists(child_pid) and time.time() < deadline:
        time.sleep(0.2)
    assert not psutil.pid_exists(child_pid), "grandchild survived the timeout"
    with _archive(rep, meta) as zf:
        assert 'simulation.sedml' not in zf.namelist()
        status = json.loads(zf.read('status.json'))
    assert status['status'] == 'timed_out' and status['timeout_seconds'] == 3
    assert _log_rows(tmp_path)[0]['timed_out'] == 'True'


@pytest.mark.parametrize('user_value, expected', [(None, '1'), ('4', '4')])
def test_cc3d_child_gets_single_threaded_blas_unless_user_set(tmp_path, monkeypatch,
                                                             user_value, expected):
    """The CC3D subprocess runs with OPENBLAS_NUM_THREADS=1 (numpy's OpenBLAS would
    otherwise commit ~120 MB per logical CPU in every parallel replicate); a value
    the user exported is kept."""
    from vivarium_vcornea.processes import vcornea_process as vp
    if user_value is None:
        monkeypatch.delenv('OPENBLAS_NUM_THREADS', raising=False)
    else:
        monkeypatch.setenv('OPENBLAS_NUM_THREADS', user_value)
    seen = {}
    monkeypatch.setattr(vp.subprocess, 'Popen',
                        lambda cmd, **kw: seen.update(kw) or object())
    out = tmp_path / 'out'
    out.mkdir()
    _, so, se = VCorneaProcess({'output_base_dir': str(tmp_path)})._run_cc3d_simulation(tmp_path, out)
    so.close(); se.close()
    assert seen['env']['OPENBLAS_NUM_THREADS'] == expected
    assert seen['env'].get('PATH') == os.environ.get('PATH')   # rest of the env inherited
