"""
End-to-end OMEX/SED-ML validation for vivarium-angio.

Builds a synthetic Zarr-like directory tree, runs
create_omex_archive_from_zarr() against it, then validates the resulting
archive with:
  1) the built-in structural checks in omex_generator.py
  2) biosimulators-utils (if installed) for COMBINE-spec compliance

No vivarium / zarr / numpy / pandas imports required: Zarr stores are just
directories on disk, so we synthesize one by writing JSON metadata + a few
binary chunk files. This exercises the file-walking and packaging path
without needing the zarr library.

Usage
-----
    cd vivarium-angio
    python test_omex_validation.py

Optional external check:
    pip install biosimulators-utils
    python test_omex_validation.py
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
UTILS_DIR = REPO_ROOT / 'vivarium_angio' / 'utils'
sys.path.insert(0, str(UTILS_DIR))

from omex_generator import (  # noqa: E402
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
    # Constructing AngiogenesisProcess starts a CC3D service (known limitation);
    # skipped with a note when cc3d is unavailable so the archive path still runs.
    parameter_audit = None
    try:
        import contextlib, io
        from vivarium_angio.processes.angiogenesis_process import AngiogenesisProcess
        from parameter_audit import build_parameter_audit
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
