"""The specification check shared by both interfaces of both applications.

One module, kept identical in the two packages, decides what is malformed
(always refused), inadmissible (refused unless explicitly allowed) and outside a
documented range (runs, recorded). These tests pin that contract and check it
against both live schemas.
"""
import filecmp
from pathlib import Path

import pytest

from vivarium_angio.utils import spec_validation as sv
from vivarium_vcornea.utils import spec_validation as sv_vcornea

REPO = Path(__file__).resolve().parents[1]

SCHEMA = {
    'rate': {'_default': 1.0, '_display_name': 'Rate', '_unit': '1/MCS',
             '_mathematical_range': (0.0, 10.0), '_physiological_range': (0.1, 2.0),
             '_recommended_range': (0.5, 1.5),
             '_range_evidence': {'mathematical': {'basis': 'numerical_stability'},
                                 'physiological': {'basis': 'expert_judgement'},
                                 'recommended': {'basis': 'exploratory'}}},
    'steps': {'_default': 10, '_display_name': 'Steps'},
    'flag': {'_default': True},
    'name': {'_default': 'run', '_validation_pattern': r'[A-Za-z0-9_]+', '_max_length': 8},
    'seed': {'_default': -1, '_mathematical_range': (0, 2 ** 31 - 1),
             '_range_evidence': {'mathematical': {'basis': 'numerical_stability'}}},
}


def _severities(params, **kw):
    return [(i['parameter'], i['severity'], i['tier'])
            for i in sv.validate_specification(SCHEMA, params, **kw)]


def test_the_two_packages_ship_the_same_check():
    assert filecmp.cmp(sv.__file__, sv_vcornea.__file__, shallow=False)
    a = REPO / 'vivarium-angio' / 'vivarium_angio' / 'utils' / 'parameter_audit.py'
    v = REPO / 'vivarium-vcornea' / 'vivarium_vcornea' / 'utils' / 'parameter_audit.py'
    assert filecmp.cmp(a, v, shallow=False)


def test_values_inside_every_range_and_defaults_raise_nothing():
    assert _severities({'rate': 1.0, 'steps': 10, 'flag': False, 'name': 'abc'}) == []
    assert _severities({'seed': -1}) == []          # a sentinel default is not a finding
    assert _severities({'steps': 20.0}) == []       # a whole number given as a float


def test_each_tier_is_reported_with_its_own_severity_and_basis():
    assert _severities({'rate': 1.8}) == [('rate', sv.OUTSIDE_RANGE, 'recommended')]
    assert _severities({'rate': 3.0}) == [('rate', sv.OUTSIDE_RANGE, 'physiological')]
    assert _severities({'rate': 12.0}) == [('rate', sv.INADMISSIBLE, 'mathematical')]
    assert _severities({'seed': -7}) == [('seed', sv.INADMISSIBLE, 'mathematical')]
    [issue] = sv.validate_specification(SCHEMA, {'rate': 3.0})
    assert issue['basis'] == 'expert_judgement' and issue['range'] == [0.1, 2.0]
    assert "the modeler's judgement" in issue['message']
    assert 'documented working range' in issue['message'] and '1/MCS' in issue['message']
    [issue] = sv.validate_specification(SCHEMA, {'rate': 12.0})
    assert 'implementation limit' in issue['message']
    assert 'may fail' not in issue['message'].lower()


def test_malformed_values_and_unknown_keys():
    assert _severities({'rate': 'fast'}) == [('rate', sv.MALFORMED, None)]
    assert _severities({'steps': 2.5}) == [('steps', sv.MALFORMED, None)]
    assert _severities({'flag': 1}) == [('flag', sv.MALFORMED, None)]
    assert _severities({'name': 'a b'}) == [('name', sv.MALFORMED, None)]
    assert _severities({'name': 'abcdefghij'}) == [('name', sv.MALFORMED, None)]
    assert _severities({'rte': 1.0}) == [('rte', sv.MALFORMED, None)]      # misspelt
    assert _severities({'output_dir': 'x'}, known_extra=['output_dir']) == []


def test_enforce_refuses_runs_and_records():
    record = sv.enforce(SCHEMA, {'rate': 3.0})                 # outside a range: runs
    assert record['n_outside_range'] == 1 and record['checked_by'] == 'process'
    assert record['allow_inadmissible'] is False and record['confirmed_by_operator'] is None

    with pytest.raises(sv.SpecificationError) as refused:      # inadmissible: refused...
        sv.enforce(SCHEMA, {'rate': 12.0})
    assert refused.value.issues[0]['parameter'] == 'rate'
    assert 'allow_inadmissible' in str(refused.value)
    record = sv.enforce(SCHEMA, {'rate': 12.0}, allow_inadmissible=True,   # ...unless allowed,
                        checked_by='gui', confirmed_by_operator=True)
    assert record['allow_inadmissible'] is True and record['n_inadmissible'] == 1   # recorded
    assert record['confirmed_by_operator'] is True and record['checked_by'] == 'gui'

    for bad in ({'rate': 'fast'}, {'rte': 1.0}):               # malformed: never allowed
        with pytest.raises(sv.SpecificationError):
            sv.enforce(SCHEMA, bad, allow_inadmissible=True)


@pytest.mark.parametrize('which', ['angio', 'vcornea'])
def test_live_schema_defaults_pass_and_every_declared_limit_is_enforced(which):
    if which == 'angio':
        from vivarium_angio.processes.angiogenesis_process import AngiogenesisProcess as P
    else:
        from vivarium_vcornea.processes.vcornea_process import VCorneaProcess as P
    inputs = P.__new__(P).ports_schema()['inputs'] if which == 'angio' else P({}).ports_schema()['inputs']
    defaults = {k: v['_default'] for k, v in inputs.items() if '_default' in v}
    assert sv.validate_specification(inputs, defaults) == []
    limited = [k for k, v in inputs.items()
               if v.get('_mathematical_range') and isinstance(v.get('_default'), (int, float))
               and not isinstance(v.get('_default'), bool)]
    assert limited
    for key in limited:
        lo, hi = inputs[key]['_mathematical_range']
        beyond = (hi + 1) if hi is not None else (lo - 1)
        if isinstance(inputs[key]['_default'], int):
            beyond = int(beyond)
        with pytest.raises(sv.SpecificationError):
            sv.enforce(inputs, {**defaults, key: beyond})


def test_non_finite_numbers_are_malformed_and_always_refused():
    # NaN compares False against every bound, so it used to pass every range tier.
    for bad in (float('nan'), float('inf'), float('-inf')):
        assert _severities({'rate': bad}) == [('rate', sv.MALFORMED, None)]
        with pytest.raises(sv.SpecificationError):
            sv.enforce(SCHEMA, {'rate': bad}, allow_inadmissible=True)


def test_a_negative_value_of_a_non_negative_quantity_is_inadmissible():
    # Where the schema declares no implementation limit, the declared dimension
    # still rules out a negative diffusion coefficient, length, area, rate...
    schema = {
        'diff': {'_default': 20.0, '_display_name': 'Diffusion', '_dimension': 'diffusion',
                 '_unit': 'voxel^2/MCS', '_physiological_range': (0.0, 186.0),
                 '_range_evidence': {'physiological': {'basis': 'literature'}}},
        'energy': {'_default': 2.0, '_dimension': 'energy'},
        'plain': {'_default': 1.0},
    }
    [issue] = sv.validate_specification(schema, {'diff': -5.0})
    assert issue['severity'] == sv.INADMISSIBLE and issue['tier'] == 'dimension'
    assert 'cannot be negative' in issue['message']
    with pytest.raises(sv.SpecificationError):
        sv.enforce(schema, {'diff': -5.0})
    assert sv.enforce(schema, {'diff': -5.0}, allow_inadmissible=True)['n_inadmissible'] == 1
    # An energy or an unlabelled number may be negative; a positive value outside
    # the working range still only runs-and-records.
    assert sv.validate_specification(schema, {'energy': -3.0, 'plain': -1.0}) == []
    [issue] = sv.validate_specification(schema, {'diff': 300.0})
    assert issue['severity'] == sv.OUTSIDE_RANGE


def test_negative_diffusion_is_refused_by_the_real_vcornea_schema():
    from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
    inputs = VCorneaProcess({}).ports_schema()['inputs']
    for key in ('EGF_SUPERDiffCoef', 'InitSTEM_TargetVolume', 'EGF_GlobalDecay'):
        with pytest.raises(sv.SpecificationError):
            sv.enforce(inputs, {key: -1.0})
