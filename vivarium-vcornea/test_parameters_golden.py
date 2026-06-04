"""Golden test for the Parameters.py writer + unit conversions.

Guards two things that, if broken, silently corrupt every run:

1. Writer completeness — `_write_parameters_file` must emit EVERY variable the
   steppable imports via `from Parameters import *`, including GUI-hidden ones the
   schema does not expose (e.g. InitBASAL_Division, read at Steppables.py:147).
   The writer layers canonical-base < schema-defaults < user-values; this test
   asserts no canonical variable is ever dropped.

2. Unit conversions — schema-stored values must reach Parameters.py in CC3D-native
   units (time days/hours -> MCS; sim-canonical values verbatim). The golden values
   below were validated against a real run (Test Runs/vcorneatest10).

Run:  conda run -n vc --no-capture-output pytest vivarium-vcornea/test_parameters_golden.py -v
or:   conda run -n vc --no-capture-output python vivarium-vcornea/test_parameters_golden.py
"""
import ast
import shutil
import tempfile
from pathlib import Path

from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
from vivarium_vcornea.utils import units

CANONICAL = (Path(__file__).resolve().parents[1]
             / "vcornea_paper/Local/Project/paper_version/Simulation/Parameters.py")


def _parse_params(path):
    """Parse a Parameters.py into {name: value}, ignoring comments/blank lines."""
    out = {}
    for line in Path(path).read_text().splitlines():
        stripped = line.split('#', 1)[0].strip()
        if not stripped or '=' not in stripped:
            continue
        name, _, value = stripped.partition('=')
        name, value = name.strip(), value.strip()
        if not name.isidentifier() or not value:
            continue
        try:
            out[name] = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            out[name] = value
    return out


def _generate_default_parameters():
    """Run the writer over a fresh copy of the canonical file with no user overrides."""
    proc = VCorneaProcess({})
    tmpdir = Path(tempfile.mkdtemp())
    tmpf = tmpdir / "Parameters.py"
    shutil.copy(CANONICAL, tmpf)          # seed the canonical base layer
    proc._write_parameters_file(tmpf, {})  # defaults only
    return _parse_params(tmpf)


def test_writer_preserves_all_canonical_variables():
    """No variable present in the canonical Parameters.py may be dropped."""
    canonical = _parse_params(CANONICAL)
    generated = _generate_default_parameters()
    missing = sorted(k for k in canonical if k not in generated)
    assert not missing, f"writer dropped steppable-required variables: {missing}"


def test_steppable_required_hidden_vars_present():
    """GUI-hidden but steppable-read variables must survive at canonical values."""
    g = _generate_default_parameters()
    assert g.get('InitBASAL_Division') == 20000.0   # read at vCornea_v2Steppables.py:147
    for v in ('EGF_GrowthScalar_STEM', 'DensityGrowthScalar_STEM',
              'L_max_links_SS', 'F_max_links_SS', 'XHypTracker'):
        assert v in g, f"hidden-but-required var dropped: {v}"


def test_time_params_converted_to_mcs():
    """Schema stores time in days/hours; Parameters.py must be in MCS."""
    g = _generate_default_parameters()
    assert g['SimTime'] == 7200       # 30 days  x 240
    assert g['InjuryTime'] == 720     # 3 days   x 240
    assert g['SnapShot_time'] == 100  # 10 hours x 10


def test_sim_canonical_values_written_verbatim():
    """Sim-canonical schema values pass through unchanged; schema wins over base."""
    g = _generate_default_parameters()
    assert g['InitSTEM_TargetVolume'] == 25.0
    assert g['EGF_SUPERDiffCoef'] == 20.0
    assert g['EGF_GlobalDecay'] == 0.5
    assert g['InjuryRadius'] == 25     # schema (25) overrides canonical base (45)
    assert g['SLS_Y_Center'] == 75     # paper (75) overrides canonical run-file (65)


def test_unit_service_roundtrip():
    """to_display / to_model_units must be exact inverses for every dimension."""
    cases = [(25, 'area', None), (18, 'length', None), (20, 'diffusion', None),
             (0.5, 'rate', None), (7200, 'time', 'days'), (100, 'time', 'hours')]
    for sim, dim, du in cases:
        disp = units.to_display(sim, dim, du)
        back = units.to_model_units(disp, dim, du)
        assert abs(back - sim) < 1e-9, f"roundtrip failed for {dim}: {sim}->{disp}->{back}"


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                print(f"FAIL {name}: {e}")
            except Exception as e:
                print(f"ERROR {name}: {type(e).__name__}: {e}")
