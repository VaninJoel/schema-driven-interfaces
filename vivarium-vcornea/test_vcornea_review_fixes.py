"""Regression tests for the defects an independent review of the V-Cornea wrapper
found (each test names the claim it protects).

Runs the real launch / monitor / collect / archive path with CompuCell3D replaced
by a small Python subprocess (see test_run_lifecycle.py).

    conda run -n vc --no-capture-output pytest vivarium-vcornea/test_vcornea_review_fixes.py -v
"""
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from test_run_lifecycle import (FAKE_CC3D, SIM_DAYS, SIM_MCS, _archive, _fake_launcher,
                                _log_rows, _run_batch)
from vivarium_vcornea.processes import vcornea_process as vp
from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
from vivarium_vcornea.utils.seed_scope import RANDOM_SEED_SCOPE, SEED_SCOPE_SENTENCE
from vivarium_vcornea.utils.spec_validation import SpecificationError

HERE = Path(__file__).resolve().parent
GUI = HERE.parent / 'vcornea-gui'


def _process(tmp_path, **params):
    return VCorneaProcess({'output_base_dir': str(tmp_path), 'SimTime': SIM_DAYS,
                           'InjuryTime': 0.5, 'replicates': 1, **params})


def _states(proc):
    return {'inputs': {k: v['_default'] for k, v in proc.ports_schema()['inputs'].items()}}


# ---- 1. timed events fire: time parameters are whole Monte Carlo steps ------------
@pytest.mark.parametrize('days, mcs', [(4.1, 984), (0.01, 2), (3.0, 720), (2.5, 600)])
def test_time_parameters_are_written_as_whole_mcs(days, mcs):
    info = VCorneaProcess().ports_schema()['inputs']['InjuryTime']
    written = vp.to_cc3d_value(info, days)
    assert written == mcs and isinstance(written, int)      # 4.1 d used to be 983.9999...


def test_fractional_injury_time_reaches_the_model_as_an_integer(tmp_path, monkeypatch):
    # The model fires the injury on `mcs == InjuryTime`; a float that is not a
    # whole number never matches and the injury silently never happened.
    _, reps, metas = _run_batch(tmp_path, monkeypatch, 'success', InjuryTime=0.41)
    params = (Path(reps[0]['output_directory']) / 'Parameters.py').read_text()
    line = next(l for l in params.splitlines() if l.startswith('InjuryTime='))
    assert line == 'InjuryTime=98'                           # 0.41 d * 240 = 98.4 -> 98
    executed = metas[0]['executed_time_parameters']
    assert executed['InjuryTime'] == {'given': 0.41, 'unit': 'days', 'executed_mcs': 98}
    assert executed['SimTime']['executed_mcs'] == SIM_MCS


# ---- 2. no healing time is recorded (the old value was wrong for every run) ---------
def test_no_healing_time_is_recorded(tmp_path, monkeypatch):
    out, reps, metas = _run_batch(tmp_path, monkeypatch, 'success')
    assert metas[0]['healing_time'] is None
    assert reps[0]['results']['healing_time'] is None
    assert _log_rows(tmp_path)[0]['healing_time'] == ''
    assert not hasattr(VCorneaProcess, '_calculate_healing_time')


# ---- 4. tables left by an earlier run do not make a new run successful ---------------
def test_rerun_into_a_directory_holding_an_earlier_runs_tables_is_not_a_success(
        tmp_path, monkeypatch):
    _, reps, metas = _run_batch(tmp_path, monkeypatch, 'success', run_name='same_name')
    assert metas[0]['simulation_status'] == 'success'
    rep_dir = Path(reps[0]['output_directory'])
    old = sorted(p.name for p in rep_dir.glob('cell_count_*.csv'))
    assert old
    for p in rep_dir.iterdir():                 # make the earlier tables clearly older
        if p.is_file():
            os.utime(p, (p.stat().st_atime, p.stat().st_mtime - 3600))

    # Same name again; this time the simulator exits 0 and writes nothing.
    _, reps2, metas2 = _run_batch(tmp_path, monkeypatch, 'nothing', run_name='same_name')
    assert Path(reps2[0]['output_directory']) == rep_dir
    meta = metas2[0]
    assert meta['run_id'] != metas[0]['run_id']
    assert meta['simulation_status'] == 'failed'
    check = meta['output_check']
    assert check['ok'] is False and check['completion_evidence'] is None
    cell = next(e for e in check['outputs'] if e['output'] == 'cell_count')
    assert cell['state'] == 'missing' and cell['stale_files'] == old
    assert 'already in the directory before launch' in cell['detail']
    with _archive(reps2[0], meta) as zf:
        assert 'simulation.sedml' not in zf.namelist()


# ---- 5. the record exists from launch, not only after the process ends ---------------
def test_run_record_parameters_and_audit_are_on_disk_at_launch(tmp_path, monkeypatch):
    seen = {}
    real = _fake_launcher('success')

    def launcher(self, project_path, output_dir):
        seen['meta'] = json.loads((output_dir / 'run_metadata.json').read_text())
        seen['files'] = sorted(p.name for p in output_dir.iterdir() if p.is_file())
        return real(self, project_path, output_dir)

    monkeypatch.setattr(VCorneaProcess, '_run_cc3d_simulation', launcher)
    proc = _process(tmp_path, SLS_Concentration=1234.0)
    proc.next_update(1, _states(proc))

    at_launch = seen['meta']
    assert at_launch['simulation_status'] == 'running'
    assert len(at_launch['run_id']) == 32 and at_launch['random_seed'] > 0
    assert at_launch['random_seed_applied'] is True
    assert at_launch['parameters']['SLS_Concentration'] == 1234.0
    assert at_launch['parameters']['random_seed'] == at_launch['random_seed']
    assert at_launch['specification_check']['checked_by'] == 'process'
    assert {'Parameters.py', 'parameter_audit.json', 'run_metadata.json'} <= set(seen['files'])


def test_cancelled_run_archive_keeps_identity_and_specification(tmp_path, monkeypatch):
    """A run interrupted before the wrapper finalizes it is archived by the GUI
    worker from the launch record: run_id, seed, parameters, Parameters.py, audit."""
    pytest.importorskip('PyQt5')
    sys.path.insert(0, str(GUI))
    from gui.simulation_worker import SimulationWorker

    captured = {}
    real = _fake_launcher('success')

    def launcher(self, project_path, output_dir):
        # Freeze the replicate directory as it is the moment the simulator starts.
        import shutil
        snap = tmp_path / 'interrupted' / 'exp' / 'replicate_1'
        shutil.copytree(output_dir, snap, ignore=shutil.ignore_patterns('vcornea_sim_*'))
        captured['dir'] = snap
        return real(self, project_path, output_dir)

    monkeypatch.setattr(VCorneaProcess, '_run_cc3d_simulation', launcher)
    proc = _process(tmp_path / 'live', SLS_Concentration=1234.0)
    proc.next_update(1, _states(proc))

    launch = json.loads((captured['dir'] / 'run_metadata.json').read_text())
    worker = SimulationWorker({'exp_name': 'exp', 'creator': None},
                              output_dir=str(tmp_path / 'interrupted'))
    worker._generate_interrupted_archives('cancelled', 'Run interrupted by the operator.',
                                          only_unfinalized=True)
    [omex] = list(captured['dir'].glob('*.omex'))
    with zipfile.ZipFile(omex) as zf:
        names = zf.namelist()
        status = json.loads(zf.read('status.json'))
        meta = json.loads(zf.read('run_metadata.json'))
        audit = json.loads(zf.read('parameter_audit.json'))
        assert 'Parameters.py' in names and 'simulation.sedml' not in names
        assert 'SLS_Concentration=1234.0' in zf.read('Parameters.py').decode()
    assert status['status'] == 'cancelled' and status['run_id'] == launch['run_id']
    assert status['random_seed'] == launch['random_seed']
    assert meta['simulation_status'] == 'cancelled'
    assert meta['parameters']['SLS_Concentration'] == 1234.0
    assert audit['parameters']['SLS_Concentration']['value'] == 1234.0
    # A replicate the wrapper already finalized is left alone.
    finalized = tmp_path / 'done' / 'exp' / 'replicate_1'
    finalized.mkdir(parents=True)
    (finalized / 'run_metadata.json').write_text(json.dumps(
        {'run_name': 'exp', 'simulation_status': 'success'}))
    done = SimulationWorker({'exp_name': 'exp'}, output_dir=str(tmp_path / 'done'))
    done._generate_interrupted_archives('cancelled', 'x', only_unfinalized=True)
    assert not list(finalized.glob('*.omex'))


def test_one_unwritable_record_does_not_abort_the_other_replicates(tmp_path, monkeypatch):
    real_open = open
    target = {}

    def flaky_open(path, mode='r', *a, **k):
        p = str(path)
        if ('w' in mode and p.endswith('run_metadata.json')
                and os.sep + 'replicate_1' + os.sep in p and target.get('armed')):
            raise OSError('disk full')
        return real_open(path, mode, *a, **k)

    def launcher(self, project_path, output_dir):
        target['armed'] = True                     # fail only the Phase-3 writes
        return _fake_launcher('success')(self, project_path, output_dir)

    monkeypatch.setattr(VCorneaProcess, '_run_cc3d_simulation', launcher)
    monkeypatch.setattr('builtins.open', flaky_open)
    proc = _process(tmp_path, replicates=2)
    out = proc.next_update(1, _states(proc))['outputs']
    monkeypatch.setattr('builtins.open', real_open)
    reps = sorted(out['replicate_results'], key=lambda r: r['replicate_id'])
    assert [r['status'] for r in reps] == ['success', 'success']
    second = json.loads((Path(reps[1]['output_directory']) / 'run_metadata.json').read_text())
    assert second['simulation_status'] == 'success' and second['omex_archive']


# ---- 6. the environment is in the run record and says what it describes --------------
def test_environment_is_recorded_with_what_it_describes(tmp_path, monkeypatch):
    _, reps, metas = _run_batch(tmp_path, monkeypatch, 'success')
    env = metas[0]['environment']
    assert env['python_version'] and env['platform'] and 'cc3d' in env['packages']
    assert sys.executable in env['describes']
    assert env['simulator_environment']['mode'] == 'same_interpreter'
    with _archive(reps[0], metas[0]) as zf:
        assert json.loads(zf.read('environment.json'))['packages'] == env['packages']

    # CompuCell3D in a separate conda environment: the record must not pass the
    # wrapper's packages off as the simulator's.
    import importlib.util
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name, *a, **k: None)
    sim = VCorneaProcess({'cc3d_conda_env_name': 'cc3d_env'})._environment_record()
    assert sim['simulator_environment']['mode'] == 'conda_run'
    assert sim['simulator_environment']['conda_env'] == 'cc3d_env'
    assert 'NOT that environment' in sim['simulator_environment']['note']


# ---- 7. the seed caveat is stated wherever the seed is stated ------------------------
def test_seed_scope_is_stated_in_the_record_the_archive_and_the_sedml(tmp_path, monkeypatch):
    _, reps, metas = _run_batch(tmp_path, monkeypatch, 'success')
    assert metas[0]['random_seed_scope'] == RANDOM_SEED_SCOPE
    assert vp.RANDOM_SEED_SCOPE is RANDOM_SEED_SCOPE            # one source
    with _archive(reps[0], metas[0]) as zf:
        status = json.loads(zf.read('status.json'))
        sedml = zf.read('simulation.sedml').decode()
    assert status['random_seed'] == metas[0]['random_seed']
    assert status['random_seed_applied'] is True
    assert status['random_seed_scope'] == SEED_SCOPE_SENTENCE
    assert 'expected to reproduce the output tables exactly' in sedml
    assert 'reproducible experiment' not in status['note']


# ---- 8. one specification check, applied before anything is created -------------------
def test_a_misspelt_parameter_is_refused_before_any_directory_exists(tmp_path):
    proc = _process(tmp_path / 'out', SLS_Concetration=1500.0)
    with pytest.raises(SpecificationError) as refused:
        proc.next_update(1, _states(proc))
    assert 'SLS_Concetration' in str(refused.value)
    assert not (tmp_path / 'out').exists()


def test_wrong_type_is_always_refused(tmp_path):
    proc = _process(tmp_path / 'out', InitSTEM_TargetVolume='abc', allow_inadmissible=True)
    with pytest.raises(SpecificationError):
        proc.next_update(1, _states(proc))
    assert not (tmp_path / 'out').exists()


def test_value_outside_an_implementation_limit_runs_only_when_allowed_and_is_recorded(
        tmp_path, monkeypatch):
    proc = _process(tmp_path / 'refused', InjuryRadius=5000)
    with pytest.raises(SpecificationError) as refused:
        proc.next_update(1, _states(proc))
    assert 'allow_inadmissible' in str(refused.value)
    assert not (tmp_path / 'refused').exists()

    _, _, metas = _run_batch(tmp_path / 'allowed', monkeypatch, 'success',
                             InjuryRadius=5000, allow_inadmissible=True,
                             confirmed_by_operator=True)
    check = metas[0]['specification_check']
    assert check['allow_inadmissible'] is True and check['confirmed_by_operator'] is True
    assert check['checked_by'] == 'gui' and check['n_inadmissible'] == 1
    assert [i['parameter'] for i in check['issues']] == ['InjuryRadius']


def test_a_plain_run_records_that_nothing_needed_confirming(tmp_path, monkeypatch):
    _, _, metas = _run_batch(tmp_path, monkeypatch, 'success')
    check = metas[0]['specification_check']
    assert check['checked_by'] == 'process' and check['confirmed_by_operator'] is None
    assert check['allow_inadmissible'] is False and check['n_malformed'] == 0


def test_an_injury_scheduled_after_the_end_of_the_run_is_refused(tmp_path):
    proc = VCorneaProcess({'output_base_dir': str(tmp_path / 'out'), 'SimTime': 2,
                           'InjuryTime': 3.0, 'IsInjury': True})
    with pytest.raises(SpecificationError) as refused:
        proc.next_update(1, _states(proc))
    assert 'would never occur' in str(refused.value)
    assert not (tmp_path / 'out').exists()
    # ...but the same times are fine when the injury is switched off.
    VCorneaProcess({'SimTime': 2, 'InjuryTime': 3.0, 'IsInjury': False}).check_specification()


# ---- 3. the GUI follows the wrapper's verdict ----------------------------------------
def test_gui_worker_follows_the_recorded_status_not_a_cell_count_file(tmp_path):
    pytest.importorskip('PyQt5')
    sys.path.insert(0, str(GUI))
    from gui.simulation_worker import SimulationWorker

    def worker(name, status, error=None):
        rep = tmp_path / name / 'replicate_1'
        rep.mkdir(parents=True)
        if status is not None:
            (rep / 'run_metadata.json').write_text(json.dumps(
                {'replicate_id': 1, 'simulation_status': status,
                 'simulation_success': status == 'success', 'error_message': error}))
        return SimulationWorker({'exp_name': name}, output_dir=str(tmp_path)), rep

    # completed with cell counting off: no cell_count file anywhere, still a success
    w, rep = worker('thickness_only', 'success')
    (rep / 'thickness_rep_241.parquet').write_bytes(b'PAR1')
    assert w._verify_real_outputs(0) is True
    # a cell-count file does not rescue a run the wrapper recorded as failed
    w, rep = worker('failed', 'failed', 'cell_count truncated')
    (rep / 'cell_count_241.csv').write_text('Stem,Time\n1,0.0\n')
    assert w._verify_real_outputs(0) is False
    assert 'cell_count truncated' in w._format_failure_message(0, '', '', 'o', 'e')
    # nor does it stand in for a verdict that was never recorded
    w, rep = worker('no_record', None)
    (rep / 'cell_count_241.csv').write_text('Stem,Time\n1,0.0\n')
    assert w._verify_real_outputs(0) is False
    w, _ = worker('still_running', 'running')
    assert w._verify_real_outputs(0) is False
    w, _ = worker('nonzero', 'success')
    assert w._verify_real_outputs(1) is False


# ---- 9/10. analysis: per-combination injury, one value per replicate ------------------
def _gui_analysis():
    pytest.importorskip('matplotlib')
    gui = GUI / 'gui'
    for name in ('analysis_data', 'analysis_plots'):
        mod = sys.modules.get(name)
        if mod is not None and Path(getattr(mod, '__file__', '') or '').parent != gui:
            del sys.modules[name]
    if str(gui) not in sys.path:
        sys.path.insert(0, str(gui))
    import analysis_data
    import analysis_plots
    return analysis_data, analysis_plots


def _experiment(root, combos):
    """combos: {name: (injury_days or None, [total cells per replicate])}."""
    import pandas as pd
    for combo, (injury, levels) in combos.items():
        for i, level in enumerate(levels, 1):
            d = root / combo / f'replicate_{i}'
            d.mkdir(parents=True)
            hours = range(0, 241)
            pd.DataFrame({'Superficial': [level] * 241, 'Wing': [2 * level] * 241,
                          'Basal': [level] * 241, 'Stem': [4] * 241,
                          'Time': [float(h) for h in hours]}).to_csv(
                d / 'cell_count_2401.csv', index=False)
            (d / 'run_metadata.json').write_text(json.dumps({
                'simulation_status': 'success', 'simulation_success': True,
                'simulation_config': {'has_injury': injury is not None, 'sim_time': 10},
                'key_parameters': {'InjuryTime': injury if injury is not None else 3.0,
                                   'IsInjury': injury is not None, 'SimTime': 10},
                'parameter_changes': {}}))
    return root


def test_injury_time_and_switch_belong_to_the_combination(tmp_path):
    ad, _ = _gui_analysis()
    ds = ad.AnalysisDataset(_experiment(tmp_path, {
        'combo_001': (3.0, [50, 52]), 'combo_002': (6.0, [50, 52]), 'combo_003': (None, [50])}))
    assert ds.injury_day('combo_001') == 3.0 and ds.injury_day('combo_002') == 6.0
    assert ds.injury_day('combo_003') is None
    assert ds.metadata_varies() is True


def test_statistics_use_one_value_per_replicate(tmp_path):
    ad, ap = _gui_analysis()
    ds = ad.AnalysisDataset(_experiment(tmp_path, {
        'combo_001': (None, [50, 52, 54]), 'combo_002': (None, [60, 62, 64])}))
    stats = ap.replicate_window_means(ds, stable_day=4.0)
    assert {k: len(v['Total']) for k, v in stats.items()} == {'combo_001': 3, 'combo_002': 3}
    assert stats['combo_001']['Total'] == [204.0, 212.0, 220.0]      # 4*level + 4 stem
    assert 'steady-state window, day 4 to day 10' in ap.window_label(ds, 4.0)
    from matplotlib.figure import Figure
    fig = Figure()
    ap._enhanced_stats(fig, ds, 4.0, 'days')
    assert 'one value per replicate (n=3, n=3)' in fig._suptitle.get_text()

    injured = ad.AnalysisDataset(_experiment(tmp_path / 'inj', {'combo_001': (3.0, [50, 52])}))
    label = ap.window_label(injured, ap._default_stable_day(injured))
    assert label.startswith('post-injury window, day 3') and 'not a steady state' in label


def test_thickness_baseline_is_named_and_a_fallback_is_never_silent(tmp_path, monkeypatch):
    ad, _ = _gui_analysis()
    ds = ad.AnalysisDataset(_experiment(tmp_path / 'a', {'combo_001': (None, [50])}))
    assert ds.membrane_is_fallback is False and 'membrane_height.csv' in ds.membrane_source
    monkeypatch.setattr(ad, '_MEMBRANE_CSV', tmp_path / 'missing.csv')
    ds = ad.AnalysisDataset(_experiment(tmp_path / 'b', {'combo_001': (None, [50])}))
    assert ds.membrane_is_fallback is True and ds.membrane_source.startswith('FALLBACK')


# ---- 12. small items -----------------------------------------------------------------
def test_metadata_names_the_package_version_and_no_injury_type_without_injury(
        tmp_path, monkeypatch):
    from importlib.metadata import version
    _, _, metas = _run_batch(tmp_path / 'a', monkeypatch, 'success', IsInjury=False)
    assert metas[0]['vivarium_wrapper_version'] == version('vivarium-vcornea')
    assert metas[0]['simulation_config']['injury_type'] is None
    assert _log_rows(tmp_path / 'a')[0]['injury_type'] == ''
    _, _, metas = _run_batch(tmp_path / 'b', monkeypatch, 'success')
    assert metas[0]['simulation_config']['injury_type'] == 'chemical'


def test_an_archive_built_by_the_real_run_path_passes_the_combine_validator(
        tmp_path, monkeypatch):
    pytest.importorskip('biosimulators_utils')
    import warnings
    from biosimulators_utils.combine.io import CombineArchiveReader
    from biosimulators_utils.combine.validation import validate
    _, reps, metas = _run_batch(tmp_path / 'run', monkeypatch, 'success')
    omex = Path(reps[0]['output_directory']) / metas[0]['omex_archive']
    with zipfile.ZipFile(omex) as zf:                 # a real archive: model + tables
        names = zf.namelist()
    assert 'model/vCornea_v2.cc3d' in names and any(n.endswith('.parquet') for n in names)
    out = tmp_path / 'extracted'
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        errors, _ = validate(CombineArchiveReader().run(str(omex), str(out)),
                             archive_dirname=str(out))
    assert errors == []


# ---- second review round ---------------------------------------------------------------
def test_output_tables_are_checked_against_their_sampling_schedule(tmp_path):
    import pandas as pd
    from vivarium_vcornea.utils.output_check import check_requested_outputs
    final_mcs, hours = 240, 24

    def write(cell_hours, surf_rows, thickness=True):
        for old in tmp_path.glob('*'):
            old.unlink()
        pd.DataFrame({'Stem': 1, 'Time': [float(h) for h in cell_hours]}).to_csv(
            tmp_path / f'cell_count_{final_mcs + 1}.csv', index=False)
        pd.DataFrame({'Total Amount': 0.5, 'Time': [s / 10 for s in range(surf_rows)]}).to_csv(
            tmp_path / f'surfactant_{final_mcs + 1}.csv', index=False)
        if thickness is True:
            pd.DataFrame({'Time': [0.0], 'Bin': 0, 'Height': 30.0}).to_parquet(
                tmp_path / f'thickness_rep_{final_mcs + 1}.parquet', index=False)
        elif thickness == 'garbage':
            (tmp_path / f'thickness_rep_{final_mcs + 1}.parquet').write_bytes(b'not a parquet file')
        check = check_requested_outputs(tmp_path, {}, final_mcs)
        return check, {e['output']: e for e in check['outputs']}

    check, by = write(range(hours + 1), final_mcs + 1)
    assert check['ok'] and by['cell_count']['n_rows'] == hours + 1
    assert by['surfactant']['n_rows'] == final_mcs + 1 and by['thickness']['state'] == 'complete'

    # the last hour is present, but hours are missing inside the series
    check, by = write([h for h in range(hours + 1) if h not in (5, 6)], final_mcs + 1)
    assert not check['ok'] and by['cell_count']['state'] == 'incomplete'
    assert 'first missing at 5 h' in by['cell_count']['detail']

    # the per-step table reaches the last time but has too few rows
    check, by = write(range(hours + 1), final_mcs + 1)
    df = pd.read_csv(tmp_path / f'surfactant_{final_mcs + 1}.csv')
    df.iloc[::2].to_csv(tmp_path / f'surfactant_{final_mcs + 1}.csv', index=False)
    check = check_requested_outputs(tmp_path, {}, final_mcs)
    by = {e['output']: e for e in check['outputs']}
    assert not check['ok'] and by['surfactant']['state'] == 'incomplete'

    # a thickness table that cannot be read is not a delivered output
    check, by = write(range(hours + 1), final_mcs + 1, thickness='garbage')
    assert not check['ok'] and by['thickness']['state'] == 'unreadable'


def test_seed_is_verified_on_the_parsed_cc3dml_not_on_its_text(tmp_path):
    proc = _process(tmp_path / 'out')
    sim = tmp_path / 'proj' / 'Simulation'
    sim.mkdir(parents=True)
    xml = sim / 'model.xml'
    # the only <RandomSeed> is inside a comment: a text substitution "succeeds" there
    xml.write_text('<CompuCell3D><!-- <Potts><RandomSeed>1</RandomSeed></Potts> -->'
                   '<Metadata/></CompuCell3D>')
    assert proc._inject_random_seed_in_copy(tmp_path / 'proj', 4242) is False
    xml.write_text('<CompuCell3D><Potts><Steps>10</Steps></Potts></CompuCell3D>')
    assert proc._inject_random_seed_in_copy(tmp_path / 'proj', 4242) is True
    assert '<RandomSeed>4242</RandomSeed>' in xml.read_text()


def test_seed_counts_as_applied_only_when_it_reached_both_generators(tmp_path, monkeypatch):
    _, _, metas = _run_batch(tmp_path / 'ok', monkeypatch, 'success')
    assert metas[0]['random_seed_applied'] is True
    assert metas[0]['random_seed_applied_to'] == {'compucell3d': True, 'python_random': True}

    # Python's half missing: the run must not start under a record that says "applied".
    launched = []
    monkeypatch.setattr(VCorneaProcess, '_write_parameters_file',
                        lambda self, params_file, sim_params: False)
    monkeypatch.setattr(VCorneaProcess, '_run_cc3d_simulation',
                        lambda self, p, o: launched.append(o))
    proc = _process(tmp_path / 'half')
    out = proc.next_update(1, _states(proc))['outputs']
    [rep] = out['replicate_results']
    assert launched == [] and rep['status'] == 'failed'
    assert "Python's generator" in rep['error_message']


def test_an_empty_thickness_table_is_not_complete(tmp_path):
    import pandas as pd
    from vivarium_vcornea.utils.output_check import check_requested_outputs
    pd.DataFrame({'Time': [], 'Bin': [], 'Height': []}).to_parquet(tmp_path / 'thickness_rep_241.parquet')
    check = check_requested_outputs(tmp_path, {'CellCount': False, 'SurfactantTracking': False}, 240)
    [entry] = [e for e in check['outputs'] if e['output'] == 'thickness']
    assert entry['state'] == 'incomplete' and not check['ok']


def test_a_table_that_cannot_be_read_for_lack_of_an_engine_is_not_called_complete(tmp_path, monkeypatch):
    from vivarium_vcornea.utils import output_check
    (tmp_path / 'thickness_rep_241.parquet').write_bytes(b'x')

    def no_engine(path):
        raise ImportError('no parquet engine')
    monkeypatch.setattr(output_check, '_read_table', no_engine)
    check = output_check.check_requested_outputs(
        tmp_path, {'CellCount': False, 'SurfactantTracking': False}, 240)
    [entry] = [e for e in check['outputs'] if e['output'] == 'thickness']
    assert entry['state'] == 'present, not read' and 'not read' in entry['detail']
    assert check['ok']          # the file carries the final step; contents unjudged



# ---- 12. a run that cannot fit in a Windows path is refused before launch ----------
def test_a_run_too_deep_for_a_windows_path_is_refused_with_what_to_shorten(tmp_path, monkeypatch):
    from vivarium_vcornea.utils import path_budget as pb
    monkeypatch.setattr(pb, 'limit_applies', lambda: True)     # as on Windows without long paths
    deep = tmp_path / 'out'
    while len(str(deep)) < 200:
        deep = deep / 'a_folder_name_of_some_length'
    proc = _process(deep, SLS_Concentration=1500.0)
    launched = []
    monkeypatch.setattr(VCorneaProcess, '_run_cc3d_simulation',
                        lambda self, *a, **k: launched.append(a))
    with pytest.raises(pb.OutputPathTooLong) as refused:
        proc.next_update(1, _states(proc))
    record, message = refused.value.record, str(refused.value)
    assert record['length'] + record['margin'] > record['limit'] == 259
    assert record['longest_path'].endswith('vCornea_v2Steppables.py')
    assert f"at least {record['excess']} characters shorter" in message
    assert str(deep) in message and 'Run not started' in message
    assert not launched and not (tmp_path / 'out').exists()    # nothing created, nothing run


def test_the_path_check_counts_the_working_copy_and_the_archive(tmp_path):
    from vivarium_vcornea.utils import path_budget as pb
    project = tmp_path / 'project'
    (project / 'Simulation').mkdir(parents=True)
    (project / 'Simulation' / 'model.py').write_text('')
    base = Path('C:/r') if os.name == 'nt' else Path('/r')
    short = pb.path_budget(base, 'run', project, n_replicates=10)
    assert short['fits'] and short['excess'] == 0
    assert short['longest_path'] == str(
        base / 'run' / 'replicate_10' / 'vcornea_sim_xxxxxx' / 'Simulation' / 'model.py')
    # A long run name appears twice (directory and archive name): the archive wins.
    name = 'n' * 120
    long = pb.path_budget(base, name, project)
    assert long['longest_path'] == str(base / name / 'replicate_1' / f'{name}.omex')
    assert not long['fits']
    assert long['excess'] == long['length'] + long['margin'] - long['limit']
    # Shortening the output folder by the stated number of characters is enough.
    padded = pb.path_budget(Path(str(base) + 'x' * 40), name, project)
    assert padded['excess'] == long['excess'] + 40
    # Where the limit does not hold, nothing is refused.
    assert pb.require_path_budget(base, name, project, enforce=False)['enforced'] is False
