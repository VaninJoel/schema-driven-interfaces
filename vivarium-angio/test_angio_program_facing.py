"""The program-facing path of Angio-GUI does what the graphical one does.

A specification is checked by the same code whether it is typed into the window,
passed to the process, or run from the command line (angio-gui/run_headless.py);
every attempt — including one that is refused — leaves a run record and a
status-typed archive; and a store never holds more than one run.

One test runs the real model for 20 MCS (about half a minute).
"""
from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip('cc3d')

from vivarium_angio.processes import angiogenesis_process as ap  # noqa: E402
from vivarium_angio.processes.angiogenesis_process import AngiogenesisProcess  # noqa: E402
from vivarium_angio.utils.spec_validation import SpecificationError  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def _runner():
    name = 'angio_run_headless'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, REPO / 'angio-gui' / 'run_headless.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


# ---- the process checks what it is given ---------------------------------------
def test_process_accepts_defaults_and_records_the_check():
    p = AngiogenesisProcess({})
    check = p.specification_check
    assert check['checked_by'] == 'process' and check['issues'] == []
    assert check['allow_inadmissible'] is False
    assert p.core_sim is None                       # constructing starts no simulation


@pytest.mark.parametrize('bad', [
    {'vedir': 50.0},          # above the declared implementation limit
    {'jee': -5.0},            # below it
    {'lchem': 'strong'},      # not a number
    {'vedirr': 1.0},          # not a parameter (misspelt): must not run at the default
])
def test_process_refuses_what_the_gui_would_refuse(bad):
    with pytest.raises(SpecificationError):
        AngiogenesisProcess(bad)


def test_inadmissible_value_runs_only_with_recorded_permission():
    p = AngiogenesisProcess({'vedir': 50.0, 'allow_inadmissible': True,
                             'confirmed_by_operator': True})
    check = p.specification_check
    assert check['allow_inadmissible'] is True and check['n_inadmissible'] == 1
    assert check['confirmed_by_operator'] is True
    with pytest.raises(SpecificationError):          # permission never covers malformed input
        AngiogenesisProcess({'lchem': 'strong', 'allow_inadmissible': True})


def test_outside_the_working_range_runs_and_names_the_basis():
    check = AngiogenesisProcess({'vedir': 3.0}).specification_check
    [finding] = check['issues']
    assert finding['severity'] == 'outside_range' and finding['tier'] == 'physiological'
    assert finding['basis'] and 'range set by' in finding['message']


def test_gui_and_process_judge_a_value_identically():
    sys.path.insert(0, str(REPO / 'angio-gui' / 'utils'))
    spec = importlib.util.spec_from_file_location(
        'angio_schema_utils', REPO / 'angio-gui' / 'utils' / 'schema_utils.py')
    gui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gui)
    schema = AngiogenesisProcess.__new__(AngiogenesisProcess).ports_schema()
    process = AngiogenesisProcess.__new__(AngiogenesisProcess)
    for key, value in (('vedir', 1.0), ('vedir', 1.8), ('vedir', 3.0), ('vedir', 12.0),
                       ('jee', -1.0), ('lchem', 6000.0), ('lchem', 'x'), ('sim_time', 100.0)):
        shown = gui.validate_parameter_value(schema, key, value)
        found = process.validate_parameters({key: value}).get(key, [])
        assert [i['kind'] for i in shown] == [f['severity'] for f in found], (key, value)
        assert [i['tier'] for i in shown] == [f['tier'] for f in found]
        for i in shown:
            assert 'may fail' not in i['message'].lower()
    # One mark per severity of finding; "no finding" only when nothing is violated.
    assert gui.validate_parameter_value(schema, 'vedir', 1.0) == []
    assert [i['severity'] for i in gui.validate_parameter_value(schema, 'vedir', 1.8)] == ['NOTE']
    assert [i['severity'] for i in gui.validate_parameter_value(schema, 'vedir', 3.0)] == ['WARNING']
    assert [i['severity'] for i in gui.validate_parameter_value(schema, 'vedir', 12.0)] == ['ERROR']


# ---- a store holds one run -------------------------------------------------------
def test_a_store_that_already_holds_steps_is_refused(tmp_path):
    import zarr
    store = tmp_path / 'used.zarr'
    ap.refuse_used_store(store)                              # absent: fine
    root = zarr.open(str(store), mode='w')
    ap.refuse_used_store(store)                              # empty: fine
    root.require_group('10')['data'] = np.zeros((2, 2, 1, 3))
    with pytest.raises(RuntimeError, match='already holds'):
        ap.refuse_used_store(store)
    manager = ap.StoreManager(str(store))
    manager.setup_exp('x', {})
    with pytest.raises(RuntimeError, match='already holds step 10'):
        manager.write_data(np.zeros((2, 2, 1, 3)), 10)


# ---- the headless runner ---------------------------------------------------------
def test_runner_resolves_files_overrides_and_sweeps():
    runner = _runner()
    inputs = AngiogenesisProcess.schema_inputs()
    params, sweeps = runner.resolve_specification(
        inputs, {'lchem': 250.0, 'creator': {'given': 'A'}},
        {'vedir': '1.5', 'lchem': '100, 500,1000', 'write_frequency': '5', 'jee': 'abc'})
    assert sweeps == {'lchem': [100.0, 500.0, 1000.0]}
    assert params['vedir'] == 1.5 and params['write_frequency'] == 5
    assert params['jee'] == 'abc'                 # left for the check to report
    assert params['creator'] == {'given': 'A'} and params['jem'] == inputs['jem']['_default']

    runs = runner.plan_runs({**params, 'random_seed': 77}, sweeps, 2, 'exp')
    assert [n for n, _ in runs] == [f'exp_combo{c:03d}_rep{r:02d}'
                                    for c in (1, 2, 3) for r in (1, 2)]
    first, second = runs[0][1], runs[1][1]
    assert (first['random_seed'], first['random_seed_origin']) == (77, 'explicit')
    assert second['random_seed_origin'] == 'drawn' and second['random_seed'] != 77
    assert first['scan_point'] == {'lchem': 100.0} and first['replicate_id'] == 1
    # A pinned seed reproduces one realization per combination; further
    # replicates are distinct realizations and draw their own.
    assert all(r['random_seed'] == 77 for n, r in runs if n.endswith('rep01'))
    drawn = [r['random_seed'] for n, r in runs if n.endswith('rep02')]
    assert 77 not in drawn and len(set(drawn)) == len(drawn)


@pytest.mark.parametrize('overrides, allow, expected', [
    ({'vedir': '50'}, False, 'allow_inadmissible'),       # needs the flag
    ({'vedirr': '1.0'}, True, 'not a parameter'),         # never runs, flag or not
    ({'lchem': 'strong'}, True, 'expected a number'),
])
def test_refused_specification_still_leaves_a_failed_record(tmp_path, overrides, allow,
                                                            expected):
    runner = _runner()
    folder, [result] = runner.run_specification(
        None, overrides, out_dir=tmp_path, name='refused', allow_inadmissible=allow,
        report=False, echo=lambda *_: None)
    run_dir = folder / 'refused'
    meta = json.loads((run_dir / 'run_metadata.json').read_text())
    assert result['status'] == meta['simulation_status'] == 'failed'
    assert expected in meta['error_message']
    assert meta['run_id'] and meta['specification_check']['issues']
    assert not (run_dir / 'data.zarr').exists()           # nothing was simulated
    with zipfile.ZipFile(result['archive']) as zf:
        names = zf.namelist()
        assert 'simulation.sedml' not in names
        assert json.loads(zf.read('status.json'))['status'] == 'failed'
        assert json.loads(zf.read('run_metadata.json'))['specification_check']['issues']


def test_runner_executes_like_the_gui_and_records_the_permission(tmp_path):
    runner = _runner()
    saved = tmp_path / 'saved_from_gui.json'
    saved.write_text(json.dumps({'exp_name': 'from_file', 'sim_time': 20.0,
                                 'write_frequency': 10, 'vedir': 3.0, 'creator': None}))
    code = runner.main(['--params', str(saved), '--out', str(tmp_path / 'out'),
                        'lchem=6000', '--allow-inadmissible', '--no-report'])
    assert code == 0
    [folder] = (tmp_path / 'out').iterdir()
    run_dir = folder / 'from_file'
    meta = json.loads((run_dir / 'run_metadata.json').read_text())
    check = meta['specification_check']
    assert meta['simulation_status'] == 'success' and meta['run_id']
    assert check['checked_by'] == 'worker' and check['allow_inadmissible'] is True
    assert {('lchem', 'inadmissible'), ('vedir', 'outside_range')} <= {
        (i['parameter'], i['severity']) for i in check['issues']}
    assert check['n_inadmissible'] == 1 and check['n_malformed'] == 0
    assert meta['provenance']['code_identity_is_of_executed_package'] is True
    assert (run_dir / 'logs' / 'stdout.log').exists()
    with zipfile.ZipFile(run_dir / 'from_file.omex') as zf:
        names = zf.namelist()
        assert 'simulation.sedml' in names and 'metrics.csv' in names
        archived = json.loads(zf.read('run_metadata.json'))
        assert archived['specification_check']['allow_inadmissible'] is True
        assert archived['run_id'] == meta['run_id']
        audit = json.loads(zf.read('model/parameter_audit.json'))
        assert audit['parameters']['lchem']['credibility'] == 'inadmissible'
