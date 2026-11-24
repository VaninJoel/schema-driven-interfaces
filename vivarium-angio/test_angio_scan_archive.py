"""The experiment-level (scan) archive and what the SED-ML says was recorded.

* The scan archive is derived from the per-run archives it catalogues, not from
  the working directories.
* It describes the experiment, not one of its runs.
* The time course in the per-run and scan SED-ML is the one actually stored: no
  output at time 0, and the same number of steps in both.
* The report quotes the validator's own messages.
"""
from __future__ import annotations

import io
import json
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pandas as pd
import pytest

from vivarium_angio.utils import omex_generator as og

from test_angio_omex_validation import _report_tool, _zarr_run

SED = {'s': 'http://sed-ml.org/sed-ml/level1/version4'}


@pytest.mark.parametrize('sim_time, write_frequency, expected', [
    (100, 10, (10.0, 100.0, 9)),      # 10 snapshots: 10, 20, ..., 100
    (20, 10, (10.0, 20.0, 1)),
    (10, 10, (10.0, 10.0, 1)),        # one snapshot: a single zero-length step
    (105, 10, (10.0, 100.0, 9)),      # the last recorded step, not the run length
    (5, 10, (5.0, 5.0, 1)),           # nothing recorded before the end
])
def test_recorded_time_course(sim_time, write_frequency, expected):
    assert og.recorded_time_course(
        {'sim_time': sim_time, 'write_frequency': write_frequency}) == expected


def _course(sedml_text):
    sim = ET.fromstring(sedml_text).find('.//s:uniformTimeCourse', SED)
    return (float(sim.get('outputStartTime')), float(sim.get('outputEndTime')),
            int(sim.get('numberOfSteps')))


@pytest.fixture
def sweep(tmp_path):
    """Two scan points, two replicates each, exported to per-run archives."""
    rep = _report_tool()
    rows = {'exp_combo001_rep01': 4, 'exp_combo001_rep02': 6,
            'exp_combo002_rep01': 8, 'exp_combo002_rep02': 10}
    for name, n in rows.items():
        d = _zarr_run(tmp_path, name, 'success', n)
        meta = json.loads((d / 'run_metadata.json').read_text())
        combo = 1 if 'combo001' in name else 2
        meta['parameters'].update({'jee': 2.0 * combo, 'write_frequency': 10,
                                   'random_seed': 1000 + n, 'exp_name': name,
                                   'parameter_scan': {'jee': [2.0, 4.0]},
                                   'scan_point': {'jee': 2.0 * combo}})
        (d / 'run_metadata.json').write_text(json.dumps(meta))
    scan, unarchived = rep._export_missing_archives(tmp_path)
    assert scan is not None and unarchived == []
    return rep, tmp_path, scan


def test_scan_means_come_from_the_run_archives_not_the_working_directories(sweep):
    import zarr
    rep, root, _ = sweep
    # Alter every working-directory trajectory AFTER the per-run archives exist,
    # then rebuild the scan archive.
    for d in root.glob('exp_combo*_rep*'):
        store = zarr.open(str(d / 'data.zarr'), mode='a')
        for step in (0, 10):
            a = np.zeros((20, 20, 1, 3))
            a[:19, :, 0, 0] = 1
            store[str(step)]['data'][...] = a
    scan, _ = rep._export_missing_archives(root)
    with zipfile.ZipFile(scan) as zf:
        meta = json.loads(zf.read('scan_metadata.json'))
        series = {n: pd.read_csv(io.BytesIO(zf.read(n)))
                  for n in zf.namelist() if n.startswith('combo_data/')}
    assert len(series) == 2
    finals = sorted(df['cell_density'].iloc[-1] for df in series.values())
    assert finals == pytest.approx([(4 + 6) / 2 / 20, (8 + 10) / 2 / 20])   # archived values
    for combo in meta['combinations']:
        assert combo['replicates_in_mean'] == 2
        assert {r['series_source'] for r in combo['included']} == {'archive'}
    assert 'archive' in meta['replicate_mean_policy']


def test_scan_archive_describes_the_experiment_not_one_run(sweep):
    _, _, scan = sweep
    with zipfile.ZipFile(scan) as zf:
        summary = json.loads(zf.read('model/model_summary.json'))
    params = summary['parameters']
    for per_run in ('random_seed', 'scan_point', 'exp_name', 'store_path'):
        assert per_run not in params
    assert 'jee' not in params and params['swept_parameters'] == {'jee': [2.0, 4.0]}
    assert params['sim_time'] == 10                       # what the points share


def test_scan_and_run_sedml_declare_the_time_course_that_was_stored(sweep):
    _, root, scan = sweep
    with zipfile.ZipFile(scan) as zf:
        scan_sedml = zf.read('scan.sedml').decode()
    run = root / 'exp_combo001_rep01' / 'exp_combo001_rep01.omex'
    with zipfile.ZipFile(run) as zf:
        run_sedml = zf.read('simulation.sedml').decode()
    # sim_time 10, written every 10: one snapshot, at MCS 10, none at MCS 0.
    assert _course(run_sedml) == _course(scan_sedml) == (10.0, 10.0, 1)
    assert 'schema keys of the swept parameters' in ' '.join(scan_sedml.split())


def test_report_quotes_the_validators_own_messages(sweep):
    pytest.importorskip('biosimulators_utils')
    rep, root, scan = sweep
    run = root / 'exp_combo001_rep01' / 'exp_combo001_rep01.omex'
    for archive in (run, scan):
        detail = rep.validation_detail(archive)
        assert detail['skipped'] is None and detail['errors'] == []
        assert any('No validation is available for models encoded in' in w
                   for w in detail['warnings'])
        s_ok, m_ok, verdict = rep.run_validation(archive)
        assert s_ok and m_ok
        assert verdict == f"PASS (0 errors, {len(detail['warnings'])} " \
                          f"warning{'' if len(detail['warnings']) == 1 else 's'})"
        assert 'warning group' not in verdict
    from reportlab.lib.styles import getSampleStyleSheet
    flow = rep._validator_messages_block([run, scan], getSampleStyleSheet()['Normal'])
    text = ' '.join(f.text for f in flow)
    assert 'cannot validate a CompuCell3D model file' in text
    assert 'No validation is available' in text and 'Validator warnings' in text
