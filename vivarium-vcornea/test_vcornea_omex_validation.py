"""
End-to-end OMEX/SED-ML validation for the vivarium-vcornea OMEX generator.

Runs the create_omex_archive() path against synthetic CC3D-shaped outputs
(no real simulation required), then validates the resulting archive with:
  1) the built-in structural checks in omex_generator.py
  2) biosimulators-utils (if installed) for COMBINE-spec compliance

Needs the vivarium-vcornea package installed (the `vc` environment); the
COMBINE check needs biosimulators-utils (the [validation] extra).

Usage
-----
    cd vivarium-vcornea
    python test_vcornea_omex_validation.py

To also run the biosimulators-utils check:
    pip install biosimulators-utils
    python test_vcornea_omex_validation.py

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

# Imported by package name, never as a bare `omex_generator` off sys.path: both
# packages ship a module of that name, and a bare import let whichever test ran
# first shadow the other package's generator in a shared pytest session.
from vivarium_vcornea.utils.omex_generator import (  # noqa: E402
    create_omex_archive,
    executed_model_overrides,
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
        from vivarium_vcornea.utils.parameter_audit import build_parameter_audit
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


# =============================================================================
# pytest entry points. The steps above only ran when the file was executed as a
# script, so pytest collected nothing and the COMBINE check never ran in the
# suite. These make it part of `pytest vivarium-vcornea/`.
# =============================================================================
import pytest  # noqa: E402


def _combine_errors(omex_path):
    try:
        from biosimulators_utils.combine.io import CombineArchiveReader
        from biosimulators_utils.combine.validation import validate as validate_archive
    except ImportError as e:  # a required check, not an optional one
        pytest.fail("biosimulators-utils is required for the COMBINE conformance "
                    "test: pip install -e ./vivarium-vcornea[validation] "
                    f"({e})")
    with tempfile.TemporaryDirectory() as extract_dir:
        archive = CombineArchiveReader().run(str(omex_path), extract_dir)
        errors, _warnings = validate_archive(archive, archive_dirname=extract_dir)
    return errors


@pytest.fixture
def success_archive(tmp_path):
    run_metadata, sim_params = make_synthetic_run(tmp_path, num_replicates=3)
    return create_omex_archive(run_output_dir=tmp_path, run_metadata=run_metadata,
                               sim_params=sim_params, include_model=False)


def test_success_archive_builtin_structure(success_archive):
    payload = step_inspect_archive(success_archive)
    assert step_builtin_validators(payload)


def test_success_archive_passes_combine_validator(success_archive):
    assert _combine_errors(success_archive) == []


def test_sedml_seed_is_the_replicates_not_the_batch_sentinel(tmp_path):
    # sim_params carries the batch-level sentinel; run_metadata the seed this
    # replicate ran with. The executable description must name the latter.
    run_metadata, sim_params = make_synthetic_run(tmp_path)
    run_metadata['random_seed'] = 98765
    sim_params['random_seed'] = -1
    omex = create_omex_archive(run_output_dir=tmp_path, run_metadata=run_metadata,
                               sim_params=sim_params, include_model=False)
    with zipfile.ZipFile(omex) as zf:
        assert 'value="98765"' in zf.read('simulation.sedml').decode()


@pytest.mark.parametrize('status', ['failed', 'cancelled', 'timed_out'])
def test_unsuccessful_archive_omits_sedml_and_records_status(tmp_path, status):
    run_metadata, sim_params = make_synthetic_run(tmp_path)
    run_metadata.update(simulation_success=False, run_timeout_seconds=60,
                        run_id='r1', exit_code=None if status != 'failed' else 2)
    omex = create_omex_archive(run_output_dir=tmp_path, run_metadata=run_metadata,
                               sim_params=sim_params, include_model=False, status=status)
    with zipfile.ZipFile(omex) as zf:
        names = zf.namelist()
        doc = json.loads(zf.read('status.json'))
        assert len(names) == len(set(names)), "duplicate archive entries"
    assert 'simulation.sedml' not in names
    assert doc['status'] == status and doc['simulation_success'] is False
    assert doc['timed_out'] is (status == 'timed_out')
    assert doc['run_id'] == 'r1'


def test_bundled_model_carries_executed_parameters_and_seed(tmp_path):
    # Source project vs. the per-replicate copy that ran: the archive must hold
    # the copy's Parameters.py and seeded XML, but the source steppables.
    source, executed, out = tmp_path / 'src', tmp_path / 'run', tmp_path / 'out'
    for root, params, seed, step in ((source, 'SimTime=5760', '', 'SOURCE'),
                                     (executed, 'SimTime=240', '<RandomSeed>7</RandomSeed>', 'REDIRECTED')):
        (root / 'Simulation').mkdir(parents=True)
        (root / 'vCornea_v2.cc3d').write_text('<Simulation/>')
        (root / 'Simulation' / 'Parameters.py').write_text(params)
        (root / 'Simulation' / 'vCornea_v2.xml').write_text(f'<CompuCell3D><Potts>{seed}</Potts></CompuCell3D>')
        (root / 'Simulation' / 'vCornea_v2Steppables.py').write_text(step)
    out.mkdir()
    run_metadata, sim_params = make_synthetic_run(out)
    omex = create_omex_archive(run_output_dir=out, run_metadata=run_metadata,
                               sim_params=sim_params, model_path=source,
                               model_overrides=executed_model_overrides(executed))
    with zipfile.ZipFile(omex) as zf:
        assert zf.read('model/Simulation/Parameters.py').decode() == 'SimTime=240'
        assert '<RandomSeed>7</RandomSeed>' in zf.read('model/Simulation/vCornea_v2.xml').decode()
        assert zf.read('model/Simulation/vCornea_v2Steppables.py').decode() == 'SOURCE'
        assert 'model/vCornea_v2.cc3d' in zf.read('simulation.sedml').decode()
