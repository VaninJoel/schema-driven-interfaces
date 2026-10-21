"""
End-to-end OMEX/SED-ML validation for vivarium-angio.

Builds a synthetic Zarr-like directory tree, runs
create_omex_archive_from_zarr() against it, then validates the resulting
archive with:
  1) the built-in structural checks in omex_generator.py
  2) biosimulators-utils (if installed) for COMBINE-spec compliance

Zarr stores are just directories on disk, so we synthesize one by writing JSON
metadata + a few binary chunk files; this exercises the file-walking and
packaging path without running a simulation. Needs the vivarium-angio package
installed (the `vc` environment); the COMBINE check needs biosimulators-utils
(the [validation] extra).

Usage
-----
    cd vivarium-angio
    python test_angio_omex_validation.py

Optional external check:
    pip install biosimulators-utils
    python test_angio_omex_validation.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

# Imported by package name, never as a bare `omex_generator` off sys.path: both
# packages ship a module of that name, and a bare import let whichever test ran
# first shadow the other package's generator in a shared pytest session.
from vivarium_angio.utils.omex_generator import (  # noqa: E402
    create_omex_archive_from_zarr,
    validate_sedml_structure,
    validate_omex_manifest,
)


def make_fake_zarr_store(parent: Path, exp_name: str = 'fake_angio_run') -> Path:
    """Synthesize a Zarr-shaped directory tree under parent/<exp_name>.zarr/."""
    store = parent / f"{exp_name}.zarr"
    store.mkdir(parents=True, exist_ok=True)

    # Root-level Zarr metadata
    (store / '.zgroup').write_text(json.dumps({'zarr_format': 2}))
    (store / '.zattrs').write_text(json.dumps({
        'exp_name': exp_name,
        'params': {'jee': 2.0, 'jem': 2.0, 'lchem': 500.0},
    }))

    # A few timestep subgroups, each with a synthetic chunk
    for step in (0, 10, 20):
        step_dir = store / str(step)
        step_dir.mkdir(exist_ok=True)
        (step_dir / '.zgroup').write_text(json.dumps({'zarr_format': 2}))
        data_dir = step_dir / 'data'
        data_dir.mkdir(exist_ok=True)
        (data_dir / '.zarray').write_text(json.dumps({
            'zarr_format': 2,
            'shape': [200, 200, 1, 3],
            'chunks': [200, 200, 1, 3],
            'dtype': '<f4',
            'compressor': None,
            'fill_value': 0.0,
            'order': 'C',
            'filters': None,
        }))
        # Binary chunk: 200*200*1*3*4 bytes; we write a single small placeholder
        (data_dir / '0.0.0.0').write_bytes(b'\x00\x01\x02\x03' * 64)
    return store


def make_metadata(store: Path) -> tuple[dict, dict]:
    sim_params = {
        'exp_name': store.stem,
        'jee': 2.0,
        'jem': 2.0,
        'lchem': 500.0,
        'lsc': 0.1,
        'vedir': 1.0,
        'veder': 0.3,
        'vesec': 0.3,
        'sim_time': 100.0,
        'write_frequency': 10.0,
    }
    run_metadata = {
        'experiment_id': 'test-uuid-0001',
        'created_at': datetime.now().isoformat(),
        'model_name': 'Angiogenesis',
        'model_version': '1.0.0',
        'parameters': sim_params,
        'final_mcs': 100,
        'zarr_store_path': str(store),
    }
    return run_metadata, sim_params


def step_create_archive(tmpdir: Path) -> Path:
    print("\n[1/4] Creating OMEX archive from synthetic Zarr store...")
    store = make_fake_zarr_store(tmpdir)
    run_metadata, sim_params = make_metadata(store)
    # Parameter audit from the live schema, as the GUI main window / finish() do.
    # Skipped with a note when cc3d is unavailable so the archive path still runs.
    parameter_audit = None
    try:
        import contextlib, io
        from vivarium_angio.processes.angiogenesis_process import AngiogenesisProcess
        from vivarium_angio.utils.parameter_audit import build_parameter_audit
        with contextlib.redirect_stdout(io.StringIO()):
            schema = AngiogenesisProcess().ports_schema()
        parameter_audit = build_parameter_audit(schema, sim_params)
        print(f"  note  parameter audit built: {parameter_audit['summary']['n_parameters']} parameters")
    except Exception as e:
        print(f"  note  parameter audit skipped ({type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''})")
    omex_path = create_omex_archive_from_zarr(
        zarr_store_path=store,
        run_metadata=run_metadata,
        sim_params=sim_params,
        parameter_audit=parameter_audit,
    )
    if parameter_audit:
        with zipfile.ZipFile(omex_path) as zf:
            assert 'model/parameter_audit.json' in zf.namelist(), 'parameter_audit.json missing'
            assert 'model/parameter_audit.json' in zf.read('manifest.xml').decode(), 'not in manifest'
        print("  PASS  model/parameter_audit.json bundled and listed in manifest.xml")
    print(f"  PASS  archive written: {omex_path.name} ({omex_path.stat().st_size} bytes)")
    return omex_path


def step_inspect_archive(omex_path: Path) -> dict:
    print("\n[2/4] Inspecting archive contents...")
    with zipfile.ZipFile(omex_path, 'r') as zf:
        names = sorted(zf.namelist())
        for n in names[:25]:
            print(f"  - {n}")
        if len(names) > 25:
            print(f"  ... ({len(names) - 25} more entries)")
        for required in ('manifest.xml', 'simulation.sedml', 'run_metadata.json'):
            if required not in names:
                print(f"  FAIL  {required} missing")
                sys.exit(1)
        manifest = zf.read('manifest.xml').decode('utf-8')
        sedml = zf.read('simulation.sedml').decode('utf-8')
    zarr_entries = [n for n in names if n.startswith('zarr/')]
    if not zarr_entries:
        print("  FAIL  no zarr/ entries packed into archive")
        sys.exit(1)
    print(f"  PASS  manifest/sedml/metadata present; {len(zarr_entries)} zarr/ entries")
    return {'names': names, 'manifest': manifest, 'sedml': sedml}


def step_builtin_validators(payload: dict) -> bool:
    print("\n[3/4] Running built-in structural validators...")
    sedml_check = validate_sedml_structure(payload['sedml'])
    manifest_check = validate_omex_manifest(
        payload['manifest'],
        [n for n in payload['names'] if n != 'manifest.xml'],
    )
    ok = sedml_check['valid'] and manifest_check['valid']
    if sedml_check['valid']:
        print("  PASS  SED-ML structure OK")
    else:
        print(f"  FAIL  SED-ML errors: {sedml_check['errors']}")
    if manifest_check['valid']:
        print("  PASS  manifest structure OK")
    else:
        print(f"  FAIL  manifest errors: {manifest_check['errors']}")
    return ok


def step_biosimulators_validation(omex_path: Path) -> str:
    print("\n[4/4] Running biosimulators-utils validation (optional)...")
    try:
        from biosimulators_utils.combine.io import CombineArchiveReader
        from biosimulators_utils.combine.validation import validate as validate_archive
    except ImportError:
        print("  SKIP  biosimulators-utils not installed.")
        print("        To enable: pip install biosimulators-utils")
        return 'SKIPPED'

    with tempfile.TemporaryDirectory() as extract_dir:
        reader = CombineArchiveReader()
        archive = reader.run(str(omex_path), extract_dir)
        errors, warnings = validate_archive(
            archive,
            archive_dirname=extract_dir,
        )
    if errors:
        print("  FAIL  biosimulators errors:")
        for e in errors:
            print(f"        - {e}")
        return 'FAIL'
    print("  PASS  biosimulators COMBINE-spec validation OK")
    if warnings:
        print(f"  Warnings ({len(warnings)}):")
        for w in warnings[:20]:
            print(f"        - {w}")
    return 'PASS'


def main() -> int:
    print("=" * 60)
    print("OMEX / SED-ML end-to-end validation (vivarium-angio)")
    print("Generator: vivarium-angio/vivarium_angio/utils/omex_generator.py")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        omex_path = step_create_archive(tmpdir)
        payload = step_inspect_archive(omex_path)
        builtin_ok = step_builtin_validators(payload)
        external_status = step_biosimulators_validation(omex_path)

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  built-in validators  : {'PASS' if builtin_ok else 'FAIL'}")
    print(f"  biosimulators-utils  : {external_status}")
    if not builtin_ok or external_status == 'FAIL':
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())


# =============================================================================
# pytest entry points. The steps above only ran when the file was executed as a
# script, so pytest collected nothing and the COMBINE check never ran in the
# suite. These make it part of `pytest vivarium-angio/`.
# =============================================================================
import pytest  # noqa: E402


def _combine_errors(omex_path):
    try:
        from biosimulators_utils.combine.io import CombineArchiveReader
        from biosimulators_utils.combine.validation import validate as validate_archive
    except ImportError as e:  # a required check, not an optional one
        pytest.fail("biosimulators-utils is required for the COMBINE conformance "
                    "test: pip install -e ./vivarium-angio[validation] "
                    f"({e})")
    with tempfile.TemporaryDirectory() as extract_dir:
        archive = CombineArchiveReader().run(str(omex_path), extract_dir)
        errors, _warnings = validate_archive(archive, archive_dirname=extract_dir)
    return errors


def _status_doc(omex):
    with zipfile.ZipFile(omex) as zf:
        return zf.namelist(), json.loads(zf.read('status.json'))


@pytest.fixture
def success_archive(tmp_path):
    store = make_fake_zarr_store(tmp_path)
    run_metadata, sim_params = make_metadata(store)
    return create_omex_archive_from_zarr(zarr_store_path=store, run_metadata=run_metadata,
                                         sim_params=sim_params)


def test_success_archive_builtin_structure(success_archive):
    payload = step_inspect_archive(success_archive)
    assert step_builtin_validators(payload)


def test_success_archive_passes_combine_validator(success_archive):
    assert _combine_errors(success_archive) == []


@pytest.mark.parametrize('status', ['failed', 'cancelled', 'timed_out'])
def test_unsuccessful_archive_omits_sedml_and_records_status(tmp_path, status):
    store = make_fake_zarr_store(tmp_path)
    run_metadata, sim_params = make_metadata(store)
    run_metadata.update(run_id='r1', exit_code=None, run_timeout_seconds=60)
    omex = create_omex_archive_from_zarr(zarr_store_path=store, run_metadata=run_metadata,
                                         sim_params=sim_params, status=status)
    names, doc = _status_doc(omex)
    assert 'simulation.sedml' not in names
    assert doc['status'] == status and doc['simulation_success'] is False
    assert doc['timed_out'] is (status == 'timed_out') and doc['run_id'] == 'r1'


def _report_tool():
    # Loaded under a package-specific name: vivarium-vcornea has a report tool
    # with the same file name, and both may be imported in one pytest session.
    import importlib.util
    name = 'angio_make_omex_combo_report'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, REPO_ROOT / 'make_omex_combo_report.py')
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


def _run_dir(root, name, status):
    d = root / name
    store = make_fake_zarr_store(d, 'data')          # -> <d>/data.zarr
    run_metadata, sim_params = make_metadata(store)
    (d / 'run_metadata.json').write_text(json.dumps(
        {'parameters': sim_params, 'simulation_status': status,
         'execution': {'success': status == 'success'}}))
    return d, run_metadata, sim_params


@pytest.mark.parametrize('status', ['failed', 'cancelled', 'timed_out'])
def test_report_never_rewrites_a_typed_archive_as_success(tmp_path, status):
    # The worker's archive for an unsuccessful run has status.json but no
    # metrics.csv. Report generation used to take that as "old format" and
    # regenerate it as a success archive with executable SED-ML.
    rep = _report_tool()
    d, run_metadata, sim_params = _run_dir(tmp_path, 'run_rep01', status)
    create_omex_archive_from_zarr(zarr_store_path=d / 'data.zarr', run_metadata=run_metadata,
                                  sim_params=sim_params, archive_path=d / f'{d.name}.omex',
                                  status=status)
    rep._regenerate_archives({'run': [d]}, {'run': 'run'}, None, sim_params, tmp_path, 1, None)
    names, doc = _status_doc(d / f'{d.name}.omex')
    assert doc['status'] == status and 'simulation.sedml' not in names


def _zarr_run(root, name, status, n_ec_rows):
    """A run dir with a real Zarr trajectory (as the writer steppable lays it out:
    <step>/data = [x, y, z, (type, id, VEGF)]) and its run_metadata.json."""
    import numpy as np
    import zarr
    d = root / name
    d.mkdir(parents=True)
    store = zarr.open(str(d / 'data.zarr'), mode='w')
    for step in (0, 10):
        a = np.zeros((20, 20, 1, 3))
        a[:n_ec_rows, :, 0, 0] = 1                      # EC cell type
        a[:n_ec_rows, :, 0, 1] = 1                      # one cell id
        a[..., 2] = 0.5                                 # VEGF
        store.require_group(str(step))['data'] = a
    (d / 'run_metadata.json').write_text(json.dumps({
        'run_id': f'id-{name}', 'simulation_status': status, 'random_seed': 7,
        'parameters': {'sim_time': 10, 'jee': 2.0},
        'execution': {'exit_code': 0 if status == 'success' else 3}}))
    return d


def test_scan_archive_means_use_only_successful_replicates(tmp_path):
    from vivarium_angio.utils import omex_generator as og
    import io
    import pandas as pd
    ok = _zarr_run(tmp_path, 'scan_combo001_rep01', 'success', 4)
    bad = _zarr_run(tmp_path, 'scan_combo001_rep02', 'failed', 15)      # partial, different
    omex = og.create_experiment_scan_archive(
        tmp_path, {'jee': [2.0, 4.0]},
        [{'label': 'jee=2.0', 'replicate_dirs': [str(ok), str(bad)], '_index': 1}],
        {'sim_time': 10}, run_name='scan', num_replicates=2)
    with zipfile.ZipFile(omex) as zf:
        meta = json.loads(zf.read('scan_metadata.json'))
        [series] = [n for n in zf.namelist() if n.startswith('combo_data/')]
        mean = pd.read_csv(io.BytesIO(zf.read(series)))
    only_ok = pd.read_csv(io.StringIO(og.extract_zarr_metrics(ok / 'data.zarr')))
    pd.testing.assert_frame_equal(mean.reset_index(drop=True), only_ok.reset_index(drop=True),
                                  check_dtype=False)
    [combo] = meta['combinations']
    assert combo['replicates'] == 2 and combo['replicates_in_mean'] == 1
    assert [r['run_id'] for r in combo['included']] == ['id-scan_combo001_rep01']
    assert combo['included'][0]['run_dir'] == 'scan_combo001_rep01'
    assert [(r['run_id'], r['reason']) for r in combo['excluded']] == [('id-scan_combo001_rep02', 'failed')]


def test_report_plots_only_successful_replicates(tmp_path, monkeypatch):
    rep = _report_tool()
    ok = _zarr_run(tmp_path, 'exp_combo001_rep01', 'success', 4)
    bad = _zarr_run(tmp_path, 'exp_combo001_rep02', 'timed_out', 15)
    lost = _zarr_run(tmp_path, 'exp_combo002_rep01', 'failed', 15)     # no success at all
    seen = {}
    real_combo, real_only = rep.build_combo_report, rep.build_excluded_only_report

    def combo_spy(c, label, rep_dirs, omex_paths, sim_time, out_pdf, excluded=()):
        seen[c] = ([Path(d).name for d in rep_dirs], [(Path(d).name, s) for d, s in excluded])
        return real_combo(c, label, rep_dirs, omex_paths, sim_time, out_pdf, excluded=excluded)

    def only_spy(c, label, excluded, out_pdf):
        seen[c] = ([], [(Path(d).name, s) for d, s in excluded])
        return real_only(c, label, excluded, out_pdf)

    monkeypatch.setattr(rep, 'build_combo_report', combo_spy)
    monkeypatch.setattr(rep, 'build_excluded_only_report', only_spy)
    written = rep.generate(tmp_path)

    assert seen['exp_combo001'] == ([ok.name], [(bad.name, 'timed_out')])
    assert seen['exp_combo002'] == ([], [(lost.name, 'failed')])
    assert all(Path(p).exists() for p in written)


def test_report_rebuilds_legacy_archive_with_recorded_status(tmp_path):
    rep = _report_tool()
    d, _, sim_params = _run_dir(tmp_path, 'legacy_rep01', 'failed')   # no archive yet
    rep._regenerate_archives({'legacy': [d]}, {'legacy': 'legacy'}, None, sim_params,
                             tmp_path, 1, None)
    names, doc = _status_doc(d / f'{d.name}.omex')
    assert doc['status'] == 'failed' and 'simulation.sedml' not in names


def test_report_shows_parameter_credibility(tmp_path):
    # The credibility section imported parameter_audit by bare name, which is only
    # importable when the package is NOT installed, so in every installed copy the
    # section silently vanished from the report although every archive carries
    # the audit (model/parameter_audit.json).
    import zipfile
    from reportlab.lib.styles import getSampleStyleSheet
    from vivarium_angio.utils.parameter_audit import build_parameter_audit
    from vivarium_angio.processes.angiogenesis_process import AngiogenesisProcess
    rep = _report_tool()
    schema = AngiogenesisProcess().ports_schema()
    params = {k: v['_default'] for k, v in schema['inputs'].items() if '_default' in v}
    params['lchem'] = 1000                       # above the recommended 100-800
    audit = build_parameter_audit(schema, params)
    omex = tmp_path / 'run.omex'
    with zipfile.ZipFile(omex, 'w') as zf:       # where the run's archive keeps it
        zf.writestr('model/parameter_audit.json', json.dumps(audit))

    ss = getSampleStyleSheet()
    flow = rep._parameter_credibility_block([omex], ss['Heading2'], ss['Normal'],
                                            lambda rows, widths: rows)
    assert flow, "credibility section missing from the report"
    rows = [r for f in flow if isinstance(f, list) for r in f]
    assert any(r[0].startswith('Chemotaxis') or 'lchem' in str(r[0]) for r in rows[1:])


def test_report_statistics_are_across_replicates(tmp_path):
    """The experiment report draws each combination as mean ± SD across its
    replicates and summarises endpoints with mean, SD, 95% CI and Kruskal-Wallis."""
    import pandas as pd
    rep = _report_tool()
    n, m, sd, half = rep._summary([1.0, 2.0, 3.0])
    assert (n, m, sd) == (3, 2.0, 1.0)
    assert abs(half - 4.302653 / 3 ** 0.5) < 1e-5
    assert rep._kruskal_p([[1, 2, 3], [7, 8, 9], [14, 15, 16]]) < 0.05
    assert rep._kruskal_p([[1, 1], [1, 1]]) is None
    assert rep._short_labels(['lchem=100', 'lchem=500']) == (['100', '500'], 'lchem')

    frames = [pd.DataFrame({'Time': [0, 10, 20], 'num_clusters': [1.0, 2.0, v]})
              for v in (3.0, 5.0)]
    per_t = rep._per_time(frames, 'num_clusters')
    assert per_t.shape == (3, 2) and per_t.std(axis=1).iloc[-1] > 0
    p = rep._metric_compare_plot('num_clusters', [('lchem=100', frames)], tmp_path, 'c.png')
    assert p.stat().st_size > 0
    p = rep._endpoint_plot([('num_clusters', {'lchem=100': [3.0, 5.0], 'lchem=500': [6.0, 7.0]})],
                           ['lchem=100', 'lchem=500'], tmp_path, 'e.png')
    assert p.stat().st_size > 0


def test_unreadable_timestep_is_not_silently_dropped(tmp_path, monkeypatch):
    """A timestep that cannot be read used to be skipped, so that replicate's
    series quietly lost a row: its 'final' value became an earlier step and the
    across-replicate mean at that step was taken without it. Reads are retried;
    a step that stays unreadable makes the replicate's metrics unavailable
    (it is then excluded and listed), never a series with a hole."""
    from vivarium_angio.utils import omex_generator as og
    monkeypatch.setattr('time.sleep', lambda s: None)
    calls = []

    def flaky():                                  # fails once, then reads
        calls.append(1)
        if len(calls) == 1:
            raise OSError('file in use')
        return 'data'
    assert og._read_step(flaky, 10, strict=True) == 'data' and len(calls) == 2

    d = _zarr_run(tmp_path, 'scan_combo001_rep01', 'success', 4)
    assert len(og.extract_zarr_metrics(d / 'data.zarr').splitlines()) == 3   # header + 2 steps
    chunks = [p for p in (d / 'data.zarr' / '10').rglob('*') if p.is_file()
              and p.name not in ('zarr.json', '.zarray', '.zgroup', '.zattrs')]
    assert chunks
    for c in chunks:                              # corrupt step 10's array data
        c.write_bytes(b'not a chunk')
    assert og.extract_zarr_metrics(d / 'data.zarr') is None
    # the lenient reader used for snapshots still yields the readable steps
    assert [s for s, _ in og._load_zarr_steps(d / 'data.zarr')] == [0]
