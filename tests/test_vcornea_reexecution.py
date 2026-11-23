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


UNSEEDED_PYTHON = "\n# test control: Python's generator deliberately left unseeded\n"


def _run(out_dir, seed, python_seed_lines=None, **switches):
    """One real run. python_seed_lines replaces the lines the wrapper appends to
    the generated Parameters.py (the control passes a comment instead)."""
    proc = VCorneaProcess({'output_base_dir': str(out_dir), 'SimTime': SIM_DAYS,
                           'replicates': 1, 'random_seed': seed, 'IsInjury': False,
                           **switches})
    if python_seed_lines is not None:
        real_write = proc._write_parameters_file

        def write_without_python_seed(params_file, sim_params):
            # Edit the file this replicate just wrote; nothing shared is changed, so
            # the runs going on in parallel are not affected.
            from vivarium_vcornea.utils.seed_scope import PYTHON_SEED_LINES
            written = real_write(params_file, sim_params)
            text = Path(params_file).read_text()
            assert PYTHON_SEED_LINES in text
            Path(params_file).write_text(text.replace(PYTHON_SEED_LINES, python_seed_lines))
            return written
        proc._write_parameters_file = write_without_python_seed
    states = {'inputs': {k: v['_default'] for k, v in proc.ports_schema()['inputs'].items()}}
    [rep] = proc.next_update(1, states)['outputs']['replicate_results']
    assert rep['status'] == 'success', rep.get('error_message')
    run_dir = Path(rep['output_directory'])
    meta = json.loads((run_dir / 'run_metadata.json').read_text())
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
