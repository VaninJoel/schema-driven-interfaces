"""`_unit` is the unit of the STORED value (descriptor format, section 3).

V-Cornea stores physical parameters in simulation units and converts to physical
units only for display. Thirty-two entries used to put the DISPLAY unit in
`_unit`, so every consumer that prints a stored value with `_unit` mislabelled
it: the run's parameter audit read "20 µm²/min" for EGF_SUPERDiffCoef, whose
stored 20 voxel²/MCS is 13.3 µm²/min.

Run:  conda run -n vc --no-capture-output pytest vivarium-vcornea/test_vcornea_units.py -v
"""
import pytest

from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
from vivarium_vcornea.utils import units
from vivarium_vcornea.utils.parameter_audit import build_parameter_audit


@pytest.fixture(scope='module')
def schema():
    return VCorneaProcess().ports_schema()


def _converted(schema):
    for name, info in schema['inputs'].items():
        if not isinstance(info, dict):
            continue
        dim, du = info.get('_dimension'), info.get('_display_unit')
        if dim and abs(units.factor(dim, du) - 1.0) > 1e-12:
            yield name, info, dim, du


def test_converted_parameters_declare_the_stored_unit(schema):
    wrong = {}
    for name, info, dim, du in _converted(schema):
        unit = info.get('_unit')
        # The stored unit is the simulation unit of the dimension; a parameter with
        # a specific display label (normalised-concentration rates) keeps its
        # quantity but per MCS.
        expected = units.sim_unit_label(dim) if not du else du.replace('hour', 'MCS')
        if unit != expected:
            wrong[name] = (unit, expected)
    assert not wrong, f"_unit must name the stored (sim) unit: {wrong}"
    assert len(list(_converted(schema))) == 32


def test_audit_labels_run_values_with_their_stored_unit(schema):
    audit = build_parameter_audit(schema, {'EGF_SUPERDiffCoef': 20.0})
    entry = audit['parameters']['EGF_SUPERDiffCoef']
    assert entry['value'] == 20.0 and entry['unit'] == 'voxel^2/MCS'
    # The physical value that stored number stands for:
    assert units.to_display(20.0, entry['dimension']) == pytest.approx(13.333, rel=1e-3)


def test_display_labels_unchanged(schema):
    """The operator still sees physical units."""
    info = schema['inputs']
    assert units.display_unit_label('diffusion') == 'µm²/min'
    assert units.display_unit_label(info['InjuryRadius']['_dimension']) == 'µm'
    egf = info['EGF_ScreteAmount']
    assert units.display_unit_label(egf['_dimension'], egf['_display_unit']) == 'Normalized Conc. / hour'
    assert units.factor(egf['_dimension'], egf['_display_unit']) == units.factor('rate')
