"""V-Cornea GUI: what the operator is shown about a run must match the run.

* The parameter info panel's "Written to Parameters.py" line shows the CURRENT
  value in CC3D-native units (what the writer will emit), not the schema default.
* The analysis view plots only runs that succeeded: partial outputs of failed,
  cancelled or timed-out replicates, and the per-replicate CC3D project copies,
  are excluded rather than presented as results.
"""
import json
from pathlib import Path

import pytest

from harness import load_gui, make_window, quiet_dialogs


@pytest.fixture
def vcornea_window(qapp, tmp_path, monkeypatch, exc_guard):
    gui = load_gui('vcornea')
    quiet_dialogs(monkeypatch, gui, tmp_path)
    win = make_window(gui, tmp_path, monkeypatch)
    yield gui, win
    win.close()
    qapp.processEvents()


def _info_html(gui, win, name):
    from schema_utils import get_full_parameter_info
    info = get_full_parameter_info(win.schema, name)
    dlg = gui.main_window.ParameterInfoDialog(name, info, win.display_names, win)
    return dlg._generate_html(name, info, win.display_names)


def test_info_panel_shows_current_value_as_written(vcornea_window):
    gui, win = vcornea_window
    win.current_params['SimTime'] = 10          # days, as the GUI stores it
    html = _info_html(gui, win, 'SimTime')
    assert '<code>SimTime=2400</code>' in html  # 10 days x 240 MCS/day
    default_days = win.schema['inputs']['SimTime']['_default']
    assert f'<code>SimTime={default_days!r}</code>' not in html


def test_batch_timeout_kills_tree_and_archives_unfinished_replicates(qapp, tmp_path):
    """The GUI worker's outer limit: the wrapper subprocess hangs with a CC3D-like
    grandchild. Both must die, and the replicate it never finalized is recorded
    as timed_out instead of being left as a bare directory. (No window and no
    quiet_dialogs here: the real subprocess path is the thing under test.)"""
    psutil = pytest.importorskip('psutil')
    load_gui('vcornea')
    import time
    import zipfile
    import simulation_worker

    exp_name = 'hung_batch'
    rep_dir = tmp_path / exp_name / 'replicate_1'
    pid_file = tmp_path / 'grandchild.pid'
    script = tmp_path / 'hang.py'
    script.write_text(
        "import pathlib, subprocess, sys, time\n"
        f"pathlib.Path(r'{rep_dir}').mkdir(parents=True, exist_ok=True)\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"open(r'{pid_file}', 'w').write(str(c.pid))\n"
        "time.sleep(120)\n")

    worker = simulation_worker.SimulationWorker(
        {'exp_name': exp_name, 'run_timeout_seconds': 1}, output_dir=str(tmp_path))
    worker._create_simulation_script = lambda: script
    worker._TIMEOUT_GRACE_S = 4
    errors = []
    worker.error.connect(errors.append)
    worker.run()

    assert errors and 'timed out' in errors[0]
    grandchild = int(pid_file.read_text())
    deadline = time.time() + 10
    while psutil.pid_exists(grandchild) and time.time() < deadline:
        time.sleep(0.2)
    assert not psutil.pid_exists(grandchild), "CC3D-like grandchild survived"
    assert json.loads((tmp_path / exp_name / 'timed_out.json').read_text())['status'] == 'timed_out'
    assert json.loads((rep_dir / 'run_metadata.json').read_text())['simulation_status'] == 'timed_out'
    [omex] = rep_dir.glob('*.omex')
    with zipfile.ZipFile(omex) as zf:
        assert json.loads(zf.read('status.json'))['status'] == 'timed_out'


def _write(path, text=''):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_analysis_excludes_unsuccessful_runs_and_project_copies(vcornea_window, tmp_path):
    exp = tmp_path / 'exp'
    csv = 'Time,Stem\n0,1\n'
    meta = lambda status: json.dumps({'simulation_status': status,
                                      'simulation_success': status == 'success'})
    ok = exp / 'combo_001' / 'replicate_1'
    _write(ok / 'cell_count_240.csv', csv)
    _write(ok / 'run_metadata.json', meta('success'))
    _write(ok / 'vcornea_sim_ab12cd' / 'Simulation' / 'cell_count_240.csv', csv)
    failed = exp / 'combo_001' / 'replicate_2'
    _write(failed / 'cell_count_240.csv', csv)
    _write(failed / 'run_metadata.json', meta('failed'))
    timed_out = exp / 'combo_001' / 'replicate_3'
    _write(timed_out / 'cell_count_240.csv', csv)
    _write(timed_out / 'run_metadata.json', meta('timed_out'))
    cancelled = exp / 'combo_002' / 'replicate_1'          # no metadata: marker decides
    _write(cancelled / 'cell_count_240.csv', csv)
    _write(exp / 'combo_002' / 'cancelled.json', '{}')
    finished_before_cancel = exp / 'combo_003' / 'replicate_1'
    _write(finished_before_cancel / 'cell_count_240.csv', csv)
    _write(finished_before_cancel / 'run_metadata.json', meta('success'))
    _write(exp / 'combo_003' / 'cancelled.json', '{}')
    legacy = exp / 'combo_004' / 'replicate_1'            # pre-status run: kept
    _write(legacy / 'cell_count_240.csv', csv)

    import analysis_data
    ds = analysis_data.AnalysisDataset.__new__(analysis_data.AnalysisDataset)
    ds.exp_dir = exp
    counts, _thick, _surf, _meta = ds._collect()

    kept = {Path(p).parent for p in counts}
    assert kept == {ok, finished_before_cancel, legacy}
    assert ds.excluded_runs == {str(failed): 'failed', str(timed_out): 'timed_out',
                                str(cancelled): 'cancelled'}
