"""Every exposed angiogenesis parameter conforms to the common descriptor format.

FIELD_GROUPS is the common format shared by both models; the same dictionary
is in vivarium-vcornea/test_vcornea_descriptor_format.py, and the two must be kept identical.

Run:  conda run -n vc --no-capture-output pytest vivarium-angio/test_angio_descriptor_format.py -v
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONTROL_EXEMPT = ('_reference_paper', '_literature', '_fitting_method')


FIELD_GROUPS = {
    'execution contract': {                   # consumed by the simulator / Vivarium
        'required': ['_default', '_updater', '_emit', '_scope', '_parameter_type'],
        'optional': ['_validation_pattern', '_max_length', '_auto_generate',
                     '_debug_parameter'],
    },
    'identity and meaning': {                 # developer -> operator
        'required': ['_display_name', '_description', '_category', '_subcategory',
                     '_expert_level'],
        'optional': ['_long_description', '_conceptual_hint', '_biological_meaning',
                     '_model_context', '_implementation_pattern', '_ontology_term'],
    },
    'units': {
        'required': ['_unit', '_dimension'],
        'optional': ['_unit_long', '_display_unit', '_conversion_factor',
                     '_value_mapping'],
    },
    'admissible and supported values': {      # three tiers + their rationale
        'required': ['_range_evidence'],   # always present, one entry per tier; None = tier not declared
        'optional': ['_mathematical_range', '_physiological_range',
                     '_recommended_range', '_warning_threshold', '_presets'],
    },
    'relationships and expected effect': {
        'required': ['_related_parameters', '_dependencies', '_affects_output'],
        'optional': ['_expected_behavior', '_equations', '_output_files',
                     '_performance_impact', '_storage_impact'],
    },
    'evidence': {                             # run -> auditor
        'required': ['_reference_paper', '_literature', '_fitting_method'],
        'optional': ['_measurable', '_experimental_assay'],
    },
    'presentation': {                         # GUI only; never affects execution
        'required': [],
        'optional': ['_hidden_basic', '_depends_on_display', '_conditional_display',
                     '_gui_hints'],
    },
}


def _field_groups():
    return FIELD_GROUPS


def _schema():
    # Constructing AngiogenesisProcess is what the GUI does to read the schema
    # (no CC3D service starts until the first simulation step).
    from vivarium_angio.processes.angiogenesis_process import AngiogenesisProcess
    return AngiogenesisProcess().ports_schema()



def check_schema(schema, groups):
    required = [f for g in groups.values() for f in g['required']]
    allowed = set(required) | {f for g in groups.values() for f in g['optional']}
    problems = []
    for name, info in schema['inputs'].items():
        if not isinstance(info, dict) or '_default' not in info:
            continue
        req = required
        if info.get('_parameter_type') == 'control':
            # execution/output controls have no literature provenance to record
            req = [f for f in required if f not in CONTROL_EXEMPT]
        missing = [f for f in req if f not in info]
        unknown = [k for k in info if k.startswith('_') and k not in allowed]
        ev = info.get('_range_evidence')
        bad_ev = (not isinstance(ev, dict)
                  or set(ev) != {'mathematical', 'physiological', 'recommended'})
        for key, tier in (('_mathematical_range', 'mathematical'),
                          ('_physiological_range', 'physiological'),
                          ('_recommended_range', 'recommended')):
            # a declared tier must have an evidence entry; an undeclared one must be None
            if isinstance(ev, dict) and ((key in info) != (ev.get(tier) is not None)):
                bad_ev = True
        if missing or unknown or bad_ev:
            problems.append((name, missing, unknown, bad_ev))
    return problems


def test_all_parameters_conform():
    problems = check_schema(_schema(), _field_groups())
    assert not problems, '\n'.join(f'{n}: missing={m} unknown={u} bad_evidence={b}'
                                   for n, m, u, b in problems)


if __name__ == '__main__':
    p = check_schema(_schema(), _field_groups())
    print('OK: all parameters conform' if not p else p)
    sys.exit(1 if p else 0)
