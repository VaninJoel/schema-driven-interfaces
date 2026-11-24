"""The tables and checksums shipped beside the example runs come from the archives.

    conda run -n vc --no-capture-output pytest tests/test_examples_analysis.py -v
"""
import csv
import hashlib
import importlib.util
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / 'examples'


def _study():
    name = 'examples_angio_metric_study'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, EXAMPLES / 'analysis' / 'angio_metric_study.py')
        sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sys.modules[name])
    return sys.modules[name]


@pytest.fixture(scope='module')
def table():
    return _study().study()


def test_the_metric_table_regenerates_from_the_archives(table):
    study = _study()
    stored = pd.read_csv(study.TABLE)
    assert table['run'].nunique() == 30 and len(table) == 300
    pd.testing.assert_frame_equal(table, stored, check_exact=False, rtol=1e-12, atol=1e-12)
    pd.testing.assert_frame_equal(study.summarise(table), pd.read_csv(study.SUMMARY),
                                  check_exact=False, rtol=1e-12, atol=1e-12, check_dtype=False)


def test_the_numbers_quoted_from_the_study(table):
    final = table[table['step'] == table['step'].max()].groupby('lchem')
    assert (table['n_cells'] == 400).all()                       # every run, every step
    area = final['mean_cell_area'].mean()
    interior = final['interior_frac'].mean()
    assert [round(area[k], 1) for k in (100, 500, 1000)] == [45.3, 35.6, 27.1]
    assert [round(interior[k], 2) for k in (100, 500, 1000)] == [0.70, 0.47, 0.33]
    # density is the mean cell area times 400 cells over the 40,000 lattice sites
    np.testing.assert_allclose(table['density'], table['mean_cell_area'] * 400 / 40000)


def test_the_reexecution_checksums_name_the_archived_trajectory():
    from vivarium_angio.utils import omex_generator as og
    archive = (EXAMPLES / 'angio-gui_lchem_sweep' / 'angio_lchem_sweep_combo002_rep01'
               / 'angio_lchem_sweep_combo002_rep01.omex')
    with open(EXAMPLES / 'reexecution' / 'angio_combo002_rep01' / 'array_checksums.csv') as f:
        rows = {int(r['step']): r for r in csv.DictReader(f)}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = og.extract_archive_zarr(archive, tmp)
        archived = {int(s): np.ascontiguousarray(np.array(d))
                    for s, d in og._load_zarr_steps(store, strict=True)}
    assert sorted(rows) == sorted(archived) and len(rows) == 10
    for step, array in archived.items():
        digest = hashlib.sha256(array.tobytes()).hexdigest()
        row = rows[step]
        assert row['sha256_archived'] == digest
        # both re-execution pathways produced the same bytes as the archive
        assert row['sha256_stock_compucell3d'] == digest == row['sha256_run_model']


def test_the_reexecuted_vcornea_tables_equal_the_archived_ones():
    import io
    import zipfile
    archive = (EXAMPLES / 'vcornea_sls_sweep' / 'vcornea_sls_sweep_combo001' / 'replicate_1'
               / 'vcornea_sls_sweep_combo001.omex')
    replay = EXAMPLES / 'reexecution' / 'vcornea_combo001_rep1_30day_replay'
    with zipfile.ZipFile(archive) as zf:
        for name, read in (('cell_count_7201.csv', pd.read_csv),
                           ('surfactant_7201.csv', pd.read_csv),
                           ('thickness_rep_7201.parquet', pd.read_parquet)):
            archived = read(io.BytesIO(zf.read(name)))
            pd.testing.assert_frame_equal(read(replay / name), archived, check_exact=True)
