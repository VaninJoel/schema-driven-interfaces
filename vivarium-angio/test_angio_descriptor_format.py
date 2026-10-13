"""Every exposed angiogenesis parameter conforms to the common descriptor format.

The field list is the one in docs/parameter_descriptor_example.py (repo root),
so the manuscript example, the schema and this test cannot drift apart.

Run:  conda run -n vc --no-capture-output pytest vivarium-angio/test_angio_descriptor_format.py -v
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONTROL_EXEMPT = ('_reference_paper', '_literature', '_fitting_method')


def _field_groups():
    spec = importlib.util.spec_from_file_location(
        'descriptor_example', REPO / 'docs' / 'parameter_descriptor_example.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.FIELD_GROUPS


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
