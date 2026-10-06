"""
End-to-end OMEX/SED-ML validation for the vivarium-vcornea OMEX generator.

Runs the create_omex_archive() path against synthetic CC3D-shaped outputs
(no real simulation required), then validates the resulting archive with:
  1) the built-in structural checks in omex_generator.py
  2) biosimulators-utils (if installed) for COMBINE-spec compliance

This avoids the vivarium import chain so it runs in any Python environment
with only stdlib + (optionally) biosimulators-utils.

Usage
-----
    cd vivarium-vcornea
    python test_omex_validation.py

To also run the biosimulators-utils check:
    pip install biosimulators-utils
    python test_omex_validation.py

The script prints PASS/FAIL for each step and exits non-zero on any failure.
Paste the full stdout back if you want me to interpret the results.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
UTILS_DIR = REPO_ROOT / 'vivarium_vcornea' / 'utils'
sys.path.insert(0, str(UTILS_DIR))

from omex_generator import (  # noqa: E402
    create_omex_archive,
    validate_sedml_structure,
    validate_omex_manifest,
)


SYNTHETIC_CSV = "time,value\n0,0.0\n100,0.5\n200,1.0\n300,1.2\n400,1.1\n500,1.0\n"


def make_synthetic_run(tmpdir: Path, num_replicates: int = 1) -> tuple[dict, dict]:
    """Populate tmpdir with CC3D-shaped outputs and return (run_metadata, sim_params)."""
    output_files = [
        'injury_edge_500.csv',
        'cell_states_500.csv',
        'cell_count_500.csv',
        'maboss_states_500.csv',
        'memb_disruption_500.csv',
        'surfactant_500.csv',
    ]
    for name in output_files:
        (tmpdir / name).write_text(SYNTHETIC_CSV)
    (tmpdir / 'Parameters.py').write_text("# synthetic CC3D Parameters.py\nSLS_Concentration = 5200.0\n")

    run_metadata = {
        'run_name': 'test_omex_validation',
        'created_at': datetime.now().isoformat(),
        'vivarium_wrapper_version': '1.0.0',
        'total_parameters': 156,
        'parameters_changed': 3,
        'simulation_config': {
            'sim_time': 500,
            'has_injury': True,
            'injury_type': 'chemical',
        },
        'key_parameters': {
            'SLS_Concentration': 5200.0,
            'InjuryTime': 6,
            'SimTime': 500,
            'IsInjury': True,
        },
        'replicate_id': 1,
        'total_replicates': num_replicates,
        'simulation_success': True,
        'simulation_completed_at': datetime.now().isoformat(),
        'files_generated': output_files,
    }
    (tmpdir / 'run_metadata.json').write_text(json.dumps(run_metadata, indent=2))

    sim_params = {
        'SimTime': 500,
        'IsInjury': True,
        'InjuryType': False,
        'SLS_Concentration': 5200.0,
    }
    return run_metadata, sim_params


def step_create_archive(tmpdir: Path) -> Path:
    print("\n[1/4] Creating OMEX archive from synthetic outputs...")
    run_metadata, sim_params = make_synthetic_run(tmpdir, num_replicates=3)
    # Parameter audit from the live schema, as the process does for a real run.
    # Skipped (with a note) when the CC3D project cannot be located, so the
    # archive path itself is still exercised on a bare checkout.
    parameter_audit = None
    try:
        from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
        from parameter_audit import build_parameter_audit
        parameter_audit = build_parameter_audit(VCorneaProcess().ports_schema(), sim_params)
        print(f"  note  parameter audit built: {parameter_audit['summary']['n_parameters']} parameters")
    except Exception as e:
        print(f"  note  parameter audit skipped ({type(e).__name__}: {str(e).splitlines()[0]})")
    omex_path = create_omex_archive(
        run_output_dir=tmpdir,
        run_metadata=run_metadata,
        sim_params=sim_params,
        parameter_audit=parameter_audit,
    )
    if parameter_audit:
        with zipfile.ZipFile(omex_path) as zf:
            assert 'parameter_audit.json' in zf.namelist(), 'parameter_audit.json missing from archive'
            assert 'parameter_audit.json' in zf.read('manifest.xml').decode(), 'parameter_audit.json not in manifest'
        print("  PASS  parameter_audit.json bundled and listed in manifest.xml")
    print(f"  PASS  archive written: {omex_path.name} ({omex_path.stat().st_size} bytes)")
    return omex_path


def step_inspect_archive(omex_path: Path) -> dict:
    print("\n[2/4] Inspecting archive contents...")
    with zipfile.ZipFile(omex_path, 'r') as zf:
        names = sorted(zf.namelist())
        for n in names:
            print(f"  - {n}")
        if 'manifest.xml' not in names:
            print("  FAIL  manifest.xml missing")
            sys.exit(1)
        if 'simulation.sedml' not in names:
            print("  FAIL  simulation.sedml missing")
            sys.exit(1)
        manifest = zf.read('manifest.xml').decode('utf-8')
        sedml = zf.read('simulation.sedml').decode('utf-8')
    print("  PASS  manifest.xml and simulation.sedml present")
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
        print(f"  FAIL  biosimulators errors:")
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
    print("OMEX / SED-ML end-to-end validation")
    print("Generator: vivarium-vcornea/vivarium_vcornea/utils/omex_generator.py")
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
