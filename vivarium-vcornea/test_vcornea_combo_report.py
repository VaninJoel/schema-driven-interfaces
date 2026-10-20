"""The OMEX report lists unsuccessful runs instead of silently dropping them.

Failed / cancelled / timed-out archives deliberately carry no executable SED-ML.
The report tool used to recognise per-run archives by that SED-ML, so every
unsuccessful attempt vanished from the reports, and a combination whose
replicates all failed produced no report at all.

Run:  conda run -n vc --no-capture-output pytest vivarium-vcornea/test_vcornea_combo_report.py -v
"""
import importlib.util
import json
import zipfile
import sys
from datetime import datetime
from pathlib import Path

from vivarium_vcornea.utils.omex_generator import create_omex_archive

HERE = Path(__file__).resolve().parent
CSV = "Time,Superficial,Wing,Basal,Stem\n0,1,2,3,4\n10,2,3,4,5\n"


def _report_tool():
    # Loaded under a package-specific name: vivarium-angio has a report tool with
    # the same file name, and both may be imported in one pytest session.
    name = 'vcornea_make_omex_combo_report'
    if name not in sys.modules:
        sys.path.insert(0, str(HERE))      # for its sibling make_omex_summary_pdf
        spec = importlib.util.spec_from_file_location(name, HERE / 'make_omex_combo_report.py')
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


def _replicate(root, combo, rid, status, thickness=False):
    d = root / combo / f'replicate_{rid}'
    d.mkdir(parents=True)
    (d / 'cell_count_240.csv').write_text(CSV)
    if thickness:   # as the model writes it: top-cell height (voxels) per X-bin, hourly
        import pandas as pd
        pd.DataFrame([{'Time': float(h), 'Bin': b, 'Height': 40.0 + b + h}
                      for h in range(3) for b in range(10)]
                     ).to_parquet(d / 'thickness_rep_241.parquet')
    meta = {'run_name': combo, 'run_id': f'{combo}-{rid}',
            'created_at': datetime.now().isoformat(),
            'replicate_id': rid, 'total_replicates': 2,
            'simulation_status': status, 'simulation_success': status == 'success',
            'exit_code': 0 if status == 'success' else 3,
            'error_message': None if status == 'success' else f'{combo} rep {rid} broke',
            'random_seed': 100 + rid, 'random_seed_origin': 'drawn',
            'simulation_config': {'sim_time': 1, 'has_injury': False},
            'key_parameters': {'SimTime': 1}}
    # As VCorneaProcess does: run_metadata.json is in the run directory before
    # the archive is built, so the archive carries it.
    (d / 'run_metadata.json').write_text(json.dumps(meta))
    return create_omex_archive(run_output_dir=d, run_metadata=meta,
                               sim_params={'SimTime': 1}, include_model=False,
                               status=status)


def test_unsuccessful_runs_are_listed_not_dropped(tmp_path, monkeypatch):
    rep = _report_tool()
    ok = _replicate(tmp_path, 'combo_001', 1, 'success')
    failed = _replicate(tmp_path, 'combo_001', 2, 'failed')
    timed_out = _replicate(tmp_path, 'combo_002', 1, 'timed_out')
    cancelled = _replicate(tmp_path, 'combo_002', 2, 'cancelled')

    combos = rep.discover_combos(tmp_path)
    assert sorted(map(Path, combos['combo_001'])) == sorted([ok, failed])
    assert sorted(map(Path, combos['combo_002'])) == sorted([timed_out, cancelled])

    seen = {}
    real_combo, real_bad = rep.build_combo_report, rep.build_unsuccessful_combo_report

    def combo_spy(key, paths, out_pdf, unsuccessful=()):
        seen[key] = ([Path(p) for p in paths], [u['status'] for u in unsuccessful])
        return real_combo(key, paths, out_pdf, unsuccessful=unsuccessful)

    def bad_spy(key, outcomes, out_pdf):
        seen[key] = ([], [u['status'] for u in outcomes])
        return real_bad(key, outcomes, out_pdf)

    monkeypatch.setattr(rep, 'build_combo_report', combo_spy)
    monkeypatch.setattr(rep, 'build_unsuccessful_combo_report', bad_spy)
    written = rep.generate(tmp_path)

    # Successful runs are plotted; the failed one is listed beside them.
    assert seen['combo_001'] == ([ok], ['failed'])
    # A combination with no successful replicate still gets its report.
    assert seen['combo_002'] == ([], ['timed_out', 'cancelled'])
    assert (tmp_path / 'combo_002' / 'combo_002_omex_report.pdf').exists()
    assert all(Path(p).exists() and Path(p).stat().st_size > 0 for p in written)


def test_archive_outcome_reads_status_and_error(tmp_path):
    rep = _report_tool()
    omex = _replicate(tmp_path, 'combo_009', 2, 'timed_out')
    oc = rep.archive_outcome(omex)
    assert oc['status'] == 'timed_out' and oc['exit_code'] == 3
    assert oc['replicate'] == 'replicate_2' and 'broke' in oc['error']


def test_thickness_is_the_gui_analysis_not_a_raw_height_average(tmp_path):
    """The report's thickness figures are drawn by the V-Cornea GUI's own analysis
    (per-X-bin top position, membrane-subtracted thickness in µm), not a plot of
    raw Height averaged over the whole domain."""
    rep = _report_tool()
    omex = _replicate(tmp_path, 'combo_001', 1, 'success', thickness=True)
    ds, ap = rep._thickness_dataset({'combo_001': [omex]}, tmp_path / 'work')
    gui = HERE.parent / 'vcornea-gui' / 'gui'
    assert Path(ap.__file__).resolve() == (gui / 'analysis_plots.py').resolve()

    d = ds.thickness_um['combo_001'][0]
    assert sorted(d['Bin'].unique()) == list(range(10))     # per bin, not one mean
    expected = (d['Height'] - d['Bin'].map(ds.membrane_bins)) * 2
    assert (d['Thickness'] - expected).abs().max() < 1e-9

    names = zipfile.ZipFile(omex).namelist()
    figs = rep.make_thickness_plots([('replicate_1', omex, names)],
                                    tmp_path / 'figs', 'combo_001')
    assert len(figs) == 2 and all(Path(png).stat().st_size > 0 for png, _, _ in figs)
