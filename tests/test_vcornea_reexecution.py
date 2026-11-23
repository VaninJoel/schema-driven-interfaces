"""V-Cornea: what the recorded seed reproduces — executed, not asserted.

Runs the real, unmodified model (CompuCell3D) through the wrapper for one simulated
day (240 MCS, a few minutes; the three runs go in parallel), twice with the same seed and once with another, and compares the
output tables. The model draws from two random generators (CompuCell3D's, and
Python's for superficial-cell sloughing); the wrapper seeds both from the one
recorded seed (vivarium_vcornea/utils/seed_scope.py).

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


def _run(out_dir, seed):
    proc = VCorneaProcess({'output_base_dir': str(out_dir), 'SimTime': SIM_DAYS,
                           'replicates': 1, 'random_seed': seed, 'IsInjury': False})
    states = {'inputs': {k: v['_default'] for k, v in proc.ports_schema()['inputs'].items()}}
    [rep] = proc.next_update(1, states)['outputs']['replicate_results']
    assert rep['status'] == 'success', rep.get('error_message')
    run_dir = Path(rep['output_directory'])
    meta = json.loads((run_dir / 'run_metadata.json').read_text())
    tables = {
        'cell_count': pd.read_csv(next(run_dir.glob('cell_count_*.csv'))),
        'surfactant': pd.read_csv(next(run_dir.glob('surfactant_*.csv'))),
        'thickness': pd.read_parquet(next(run_dir.glob('thickness_*.parquet'))),
    }
    return run_dir, meta, tables


@pytest.fixture(scope='module')
def runs(tmp_path_factory):
    base = tmp_path_factory.mktemp('vc')      # short path: the project copy is deep
    from concurrent.futures import ThreadPoolExecutor
    plan = (('a', SEED), ('b', SEED), ('other', SEED + 1))
    with ThreadPoolExecutor(max_workers=len(plan)) as pool:     # each run is its own process
        futures = {name: pool.submit(_run, base / name, seed) for name, seed in plan}
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
