"""Seeded random operator session against each GUI.

Hundreds of random actions — typing valid, invalid and sweep values into
parameter fields, clicking any visible button, toggling switches, changing
presets and expertise level, switching tabs, starting fake runs — must never
let an exception escape a slot or close the window. On failure the last actions
are printed so the sequence can be replayed with the same seed:

    GUI_FUZZ_SEED=<seed> GUI_FUZZ_STEPS=<n> pytest tests/gui/test_random_interaction.py
"""
import os

import pytest

from harness import Fuzzer, schema_parameters

SEEDS = [int(s) for s in os.environ.get('GUI_FUZZ_SEED', '0,1,2').split(',')]
STEPS = int(os.environ.get('GUI_FUZZ_STEPS', '250'))


@pytest.mark.parametrize('seed', SEEDS)
def test_random_operator_session(gui, window, exc_guard, seed):
    fz = Fuzzer(window, seed, exc_guard)
    log = fz.run(STEPS)
    kinds = {a.split(':', 1)[0] for a in log}
    print(f"\n[{gui.name}] seed={seed} steps={len(log)} action kinds={sorted(kinds)}")
    assert {'button', 'line'} <= kinds, "fuzzer never typed or clicked"
    # the window is still consistent: validation of every parameter runs clean
    window.validate_all_parameters()
    assert window.isVisible()


def test_invalid_values_are_flagged_not_fatal(gui, window, exc_guard):
    """Type garbage and out-of-range values into every numeric field; the GUI must
    flag them through validation rather than crash, and must still be runnable."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QLineEdit
    from schema_utils import validate_parameter_value
    window.expertise_combo.setCurrentText('Advanced')
    flagged = 0
    for name, info in schema_parameters(window).items():
        w = window.param_widgets.get(name, {}).get('input')
        if not isinstance(w, QLineEdit) or not isinstance(info.get('_default'), (int, float)) \
                or isinstance(info.get('_default'), bool):
            continue
        for bad in ('abc', '1e12', '-1e12'):
            w.clear(); QTest.keyClicks(w, bad); QTest.keyClick(w, Qt.Key_Return)
        issues = validate_parameter_value(window.schema, name, window.current_params.get(name))
        flagged += bool(issues)
    exc_guard.raise_if_any('typing invalid values')
    assert flagged > 0, "no invalid value was flagged by validation"


def test_every_preset_applies_without_a_type_error(gui, window, exc_guard):
    """Readiness audit 4.4: presets must not red-flag the parameters they set."""
    from schema_utils import validate_parameter_value
    combo = window.preset_combo
    bad = []
    for i in range(combo.count()):
        combo.setCurrentIndex(i)
        from harness import settle; settle(20)
        for name, value in window.current_params.items():
            if name not in window.schema['inputs']:
                continue
            for issue in validate_parameter_value(window.schema, name, value):
                if issue['severity'] == 'ERROR' and 'Expected' in issue['message']:
                    bad.append(f"{combo.itemText(i)}: {name}={value!r} -> {issue['message']}")
    assert not bad, bad


def test_experiment_name_never_produces_an_unsafe_folder(gui, window, exc_guard):
    """Whatever the operator types, the run name used for folders is filesystem-safe."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    import re
    field = getattr(window, 'exp_name_input', None) or window.param_widgets.get('exp_name', {}).get('input')
    assert field is not None, "no experiment-name field found"
    for raw in ('1,2,3', 'a b/c', '  -1  ', 'ok_name-2', '', 'x' * 80):
        field.clear(); QTest.keyClicks(field, raw); QTest.keyClick(field, Qt.Key_Return)
        name = window.current_params.get('exp_name', '')
        if gui.name == 'angio':
            # angio validates rather than rewrites: the schema pattern must flag bad names
            from schema_utils import validate_parameter_value
            issues = validate_parameter_value(window.schema, 'exp_name', name)
            if not re.match(r'^[a-zA-Z0-9_-]{1,50}$', name):
                assert any(i['severity'] == 'ERROR' for i in issues), f"{raw!r} accepted silently as {name!r}"
        else:
            assert re.match(r'^[a-zA-Z0-9_-]{1,50}$', name), f"{raw!r} became unsafe run name {name!r}"
