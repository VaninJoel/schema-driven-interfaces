"""V-Cornea: what the recorded seed reproduces — executed, not asserted.

Runs the real, unmodified model (CompuCell3D) through the wrapper for one simulated
day (240 MCS, a few minutes; the three runs go in parallel), twice with the same seed and once with another, and compares the
output tables. The model draws from two random generators (CompuCell3D's, and
Python's for superficial-cell sloughing); the wrapper seeds both from the one
recorded seed (vivarium_vcornea/utils/seed_scope.py).

Two further runs make the result mean something:
  * a control with the same seed in which Python's generator is deliberately left
    unseeded (the behaviour before the fix): it must NOT reproduce the tables, which
    shows that sloughing draws do change the outcome within this horizon and that
    the seeding of Python's generator is what gives the replay;
  * a run configured to record thickness only (cell counts and surfactant switched
    off): it must be classified as a success.

Two more real runs end with exit status zero and must NOT be classified as a
success (the model code is untouched in both; only this replicate's own copy of
its configuration is edited after the wrapper has written it):
  * 'step_limit': CompuCell3D's step limit in the replicate's CC3DML is lowered
    from 100000 to 120, so the simulator ends normally at step 120, before the
    model's end-of-run step (241) at which it writes its tables. Nothing is written.
  * 'stops_a_day_early': the wrapper is asked for two simulated days, and a line
    appended to the replicate's Parameters.py makes the model end itself after
    one. The model writes complete-looking tables that cover only the first day.

Scope of the claim these tests support: same machine, same software environment,
one processor, a short run without injury. A full-length run is not checked here.

    conda run -n vc --no-capture-output pytest tests/test_vcornea_reexecution.py -v
"""
import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip('cc3d')

from vivarium_vcornea.processes.vcornea_process import VCorneaProcess  # noqa: E402

SIM_DAYS = 1               # 240 MCS (the schema takes whole days); sloughing draws start near MCS 11
SEED = 20261123
STEP_LIMIT = 120           # below the model's end-of-run step (SIM_DAYS * 240 + 1)


UNSEEDED_PYTHON = "\n# test control: Python's generator deliberately left unseeded\n"


def _lower_the_cc3d_step_limit(simulation_dir):
    [xml] = [f for f in simulation_dir.glob('*.xml') if '<Potts>' in f.read_text()]
    text = xml.read_text()
    assert text.count('<Steps>100000</Steps>') == 1
    xml.write_text(text.replace('<Steps>100000</Steps>', f'<Steps>{STEP_LIMIT}</Steps>'))


def _make_the_model_stop_a_day_early(simulation_dir):
    params = simulation_dir / 'Parameters.py'
    assert f'SimTime={2 * 240}' in params.read_text().replace(' ', '')
    with open(params, 'a') as f:
        f.write('\n# test: the model ends itself after one day; the wrapper asked for two\n'
                'SimTime = 240\n')


def _run(out_dir, seed, python_seed_lines=None, edit_copy=None, sim_days=SIM_DAYS,
         expect='success', **switches):
    """One real run. python_seed_lines replaces the lines the wrapper appends to
    the generated Parameters.py (the control passes a comment instead). edit_copy
    is called with this replicate's own Simulation directory after the wrapper has
    finished writing it."""
    proc = VCorneaProcess({'output_base_dir': str(out_dir), 'SimTime': sim_days,
                           'replicates': 1, 'random_seed': seed, 'IsInjury': False,
                           **switches})
    if python_seed_lines is not None or edit_copy is not None:
        real_write = proc._write_parameters_file

        def write_then_edit(params_file, sim_params):
            # Edit the files this replicate just wrote; nothing shared is changed, so
            # the runs going on in parallel are not affected.
            from vivarium_vcornea.utils.seed_scope import PYTHON_SEED_LINES
            written = real_write(params_file, sim_params)
            if python_seed_lines is not None:
                text = Path(params_file).read_text()
                assert PYTHON_SEED_LINES in text
                Path(params_file).write_text(text.replace(PYTHON_SEED_LINES, python_seed_lines))
            if edit_copy is not None:
                edit_copy(Path(params_file).parent)
            return written
        proc._write_parameters_file = write_then_edit
    states = {'inputs': {k: v['_default'] for k, v in proc.ports_schema()['inputs'].items()}}
    [rep] = proc.next_update(1, states)['outputs']['replicate_results']
    assert rep['status'] == expect, rep.get('error_message')
    run_dir = Path(rep['output_directory'])
    meta = json.loads((run_dir / 'run_metadata.json').read_text())
    meta['_replicate_result'] = rep
    tables = {}
    for name, pattern, read in (('cell_count', 'cell_count_*.csv', pd.read_csv),
                                ('surfactant', 'surfactant_*.csv', pd.read_csv),
                                ('thickness', 'thickness_*.parquet', pd.read_parquet)):
        found = sorted(run_dir.glob(pattern))
        if found:
            tables[name] = read(found[0])
    return run_dir, meta, tables


@pytest.fixture(scope='module')
def runs(tmp_path_factory):
    base = tmp_path_factory.mktemp('vc')      # short path: the project copy is deep
    from concurrent.futures import ThreadPoolExecutor
    plan = {
        'a': dict(seed=SEED),
        'b': dict(seed=SEED),
        'other': dict(seed=SEED + 1),
        'python_unseeded': dict(seed=SEED, python_seed_lines=UNSEEDED_PYTHON),
        'thickness_only': dict(seed=SEED, CellCount=False, SurfactantTracking=False),
        'step_limit': dict(seed=SEED, edit_copy=_lower_the_cc3d_step_limit, expect='failed'),
        'stops_a_day_early': dict(seed=SEED, sim_days=2, expect='failed',
                                  edit_copy=_make_the_model_stop_a_day_early),
    }
    with ThreadPoolExecutor(max_workers=len(plan)) as pool:     # each run is its own process
        futures = {name: pool.submit(_run, base / name, **kw) for name, kw in plan.items()}
        return {name: f.result() for name, f in futures.items()}


def test_one_recorded_seed_reaches_both_generators(runs):
    run_dir, meta, _ = runs['a']
    assert meta['random_seed'] == SEED and meta['random_seed_applied'] is True
    assert meta['output_check']['ok'] is True
    params = (run_dir / 'Parameters.py').read_text()
    assert f'random_seed={SEED}' in params
    assert '_python_random.seed(random_seed)' in params          # Python's generator
    with zipfile.ZipFile(run_dir / meta['omex_archive']) as zf:
        names = zf.namelist()
        archived = zf.read('model/Simulation/Parameters.py').decode()
        xml = next(zf.read(n).decode() for n in names
                   if n.startswith('model/Simulation/') and n.endswith('.xml')
                   and b'<Potts>' in zf.read(n))
        steppables = zf.read('model/Simulation/vCornea_v2Steppables.py').decode()
    # The archive re-executes with the same two seeds, and the model code is untouched.
    assert '_python_random.seed(random_seed)' in archived
    assert f'<RandomSeed>{SEED}</RandomSeed>' in xml             # CompuCell3D's generator
    source = (Path(__file__).resolve().parents[1] / 'vcornea_paper' / 'Local' / 'Project'
              / 'paper_version' / 'Simulation' / 'vCornea_v2Steppables.py').read_text()
    # Compared line by line (the archive stores the file's bytes; line endings may
    # differ from a text-mode read): no seeding line was added to the model.
    assert steppables.splitlines() == source.splitlines()


def test_same_seed_and_parameters_give_identical_output_tables(runs):
    _, _, a = runs['a']
    _, _, b = runs['b']
    for name in ('cell_count', 'thickness', 'surfactant'):
        pd.testing.assert_frame_equal(a[name], b[name], check_exact=True)
    assert len(a['thickness']) > 0 and a['cell_count']['Time'].max() == SIM_DAYS * 24


def test_a_different_seed_gives_a_different_run(runs):
    _, _, a = runs['a']
    _, _, other = runs['other']
    assert not a['thickness'].equals(other['thickness'])


def test_without_seeding_pythons_generator_the_same_seed_does_not_replay(runs):
    # The control: CompuCell3D's seed is the same as in run 'a', Python's generator
    # is left to seed itself. If this run reproduced 'a', the replay above would
    # owe nothing to the Python seeding (or no sloughing draw mattered in a day).
    run_dir, meta, control = runs['python_unseeded']
    _, _, a = runs['a']
    assert meta['random_seed'] == SEED
    assert '_python_random.seed' not in (run_dir / 'Parameters.py').read_text()
    assert not (a['cell_count'].equals(control['cell_count'])
                and a['thickness'].equals(control['thickness']))


def test_a_real_run_that_records_thickness_only_is_a_success(runs):
    run_dir, meta, tables = runs['thickness_only']
    check = meta['output_check']
    by = {e['output']: e for e in check['outputs']}
    assert meta['simulation_status'] == 'success' and check['ok'] is True
    assert check['completion_evidence'] == 'end_of_run_output'
    assert by['cell_count']['state'] == 'not requested'
    assert by['surfactant']['state'] == 'not requested'
    assert by['thickness']['state'] == 'complete'
    assert set(tables) == {'thickness'} and len(tables['thickness']) > 0
    assert not list(run_dir.glob('cell_count_*.csv'))
    with zipfile.ZipFile(run_dir / meta['omex_archive']) as zf:
        assert 'simulation.sedml' in zf.namelist()          # archived as a completed run
        assert json.loads(zf.read('status.json'))['status'] == 'success'


# --- exit status zero, results missing or short: real runs ---------------------

def _archive(run_dir, meta):
    return run_dir / meta['omex_archive']


def _assert_recorded_as_failed(run_dir, meta):
    assert meta['exit_code'] == 0                       # the process ended normally
    assert meta['simulation_status'] == 'failed' and meta['simulation_success'] is False
    assert meta['output_check']['ok'] is False
    result = meta['_replicate_result']
    assert result['success'] is False and not result['results']   # nothing parsed
    with zipfile.ZipFile(_archive(run_dir, meta)) as zf:
        status = json.loads(zf.read('status.json'))
        assert status['status'] == 'failed' and status['exit_code'] == 0
        assert 'simulation.sedml' not in zf.namelist()  # not offered as a completed run


def test_a_real_run_ended_by_the_step_limit_exits_zero_and_is_a_failure(runs):
    run_dir, meta, tables = runs['step_limit']
    _assert_recorded_as_failed(run_dir, meta)
    check = meta['output_check']
    assert check['cc3d_end_of_run_report'] is True      # CompuCell3D finished its run
    assert check['completion_evidence'] is None         # the model did not reach its end
    assert {e['output']: e['state'] for e in check['outputs']} == {
        'cell_count': 'missing', 'thickness': 'missing', 'surfactant': 'missing'}
    assert tables == {} and 'exited cleanly (code 0)' in meta['error_message']
    assert 'did not reach the final step of the requested period (step 241)' in meta['error_message']
    assert 'startup' not in meta['error_message']       # not mistaken for a launch failure


def test_a_real_run_that_covers_half_the_requested_period_is_a_failure(runs):
    run_dir, meta, tables = runs['stops_a_day_early']
    _assert_recorded_as_failed(run_dir, meta)
    check = meta['output_check']
    assert check['final_mcs'] == 480 and check['expected_last_time_hours'] == 48
    # The model wrote its tables, complete for the day it ran: stamped with step
    # 241 instead of 481, last sample at 24 h instead of 48 h.
    assert len(tables['cell_count']) == 25 and tables['cell_count']['Time'].max() == 24
    by = {e['output']: e for e in check['outputs']}
    for name, written in (('cell_count', 'cell_count_241.csv'),
                          ('surfactant', 'surfactant_241.csv')):
        assert by[name]['state'] == 'missing'
        assert written in by[name]['detail'] and 'different step' in by[name]['detail']
    assert by['thickness']['state'] == 'missing'
    assert 'covered a different period than requested' in meta['error_message']


def test_the_two_failed_real_runs_are_left_out_of_the_summaries(runs):
    import importlib.util
    import sys
    tool = Path(__file__).resolve().parents[1] / 'vivarium-vcornea' / 'make_omex_combo_report.py'
    name = 'vcornea_make_omex_combo_report'
    if name not in sys.modules:
        sys.path.insert(0, str(tool.parent))            # for its sibling module
        spec = importlib.util.spec_from_file_location(name, tool)
        sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sys.modules[name])
    report = sys.modules[name]
    good = _archive(*runs['a'][:2])
    bad = [_archive(*runs[k][:2]) for k in ('step_limit', 'stops_a_day_early')]
    summarised, listed = report.split_by_outcome([good, *bad])
    assert summarised == [good]                         # only the completed run is plotted
    assert [(o['status'], o['exit_code']) for o in listed] == [('failed', 0), ('failed', 0)]
    assert all(o['error'] for o in listed)              # each listed with its reason
