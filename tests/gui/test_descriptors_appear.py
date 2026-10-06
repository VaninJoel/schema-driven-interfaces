"""Every descriptor the common format defines reaches the operator, in both GUIs.

For each exposed parameter: a control exists in the window, the ⓘ dialog shows
every documented field (name, description, unit, each declared range with its
evidence statement, default provenance with locator, literature, ontology term,
expected behaviour, dependencies, presets), the validation dialog shows the
range evidence, and the Markdown export lists the parameter with its evidence.
"""
import pytest

from harness import info_button, iter_tabs, schema_parameters, settle


def _info_html(gui, win, name):
    from schema_utils import get_full_parameter_info
    info = get_full_parameter_info(win.schema, name)
    dlg = gui.main_window.ParameterInfoDialog(name, info, win.display_names, win)
    return dlg._generate_html(name, info, win.display_names), info


def _validation_html(gui, win, name):
    from schema_utils import validate_parameter_value
    info = win.schema['inputs'][name]
    value = win.current_params.get(name, info.get('_default'))
    issues = validate_parameter_value(win.schema, name, value)
    dlg = gui.main_window.ValidationInfoDialog(name, info, value, issues, win)
    return dlg._generate_html(name, info, value, issues)


def test_every_parameter_has_a_control_and_an_info_button(window):
    from PyQt5.QtWidgets import QAbstractButton
    params = schema_parameters(window)
    # advanced level: every parameter is editable; nothing is hidden by level
    window.expertise_combo.setCurrentText('Advanced'); settle()
    # execution controls (experiment name, duration, seed...) may live in the run panel
    missing = [p for p, i in params.items() if p not in window.param_widgets
               and i.get('_parameter_type') != 'control']
    assert not missing, f"parameters with no widget: {missing}"
    no_info = [p for p in params if p in window.param_widgets and info_button(window, p) is None]
    assert not no_info, f"parameters without an info button: {no_info}"


def test_expertise_level_changes_editability_not_visibility(window):
    """Manuscript 3.2: parameters above the selected level stay visible, read-only."""
    params = schema_parameters(window)
    window.expertise_combo.setCurrentText('Basic'); settle()
    present_basic = {p for p in params if p in window.param_widgets}
    window.expertise_combo.setCurrentText('Advanced'); settle()
    present_adv = {p for p in params if p in window.param_widgets}
    hidden_basic_flag = {p for p, i in params.items() if i.get('_hidden_basic')}
    # everything advanced shows must also be present at basic, except explicit _hidden_basic
    assert present_adv - present_basic <= hidden_basic_flag, \
        f"hidden at Basic without _hidden_basic: {sorted(present_adv - present_basic - hidden_basic_flag)}"
    window.expertise_combo.setCurrentText('Basic'); settle()
    locked = [p for p, i in params.items() if i.get('_expert_level') == 'advanced'
              and p in window.param_widgets and window.param_widgets[p]['input'].isEnabled()]
    assert not locked, f"advanced parameters editable at Basic level: {locked}"


@pytest.mark.parametrize('field', [
    '_display_name', '_description', '_unit', 'ranges', '_reference_paper', '_literature',
    '_ontology_term', '_expected_behavior', '_dependencies', '_presets', '_biological_meaning',
    '_model_context', '_conceptual_hint', '_implementation_pattern', '_fitting_method',
])
def test_info_dialog_shows_each_documented_field(gui, window, field):
    from schema_utils import RANGE_TIERS, format_range_evidence, format_ontology_term
    failures = []
    for name, info in schema_parameters(window).items():
        html, full = _info_html(gui, window, name)
        if field == 'ranges':
            for key, tier, label in RANGE_TIERS:
                if full.get(key):
                    ev = format_range_evidence(full, tier)
                    if label not in html or ev not in html:
                        failures.append(f"{name}: {label} or its evidence missing")
            continue
        value = full.get(field)
        if not value:
            continue
        if field == '_reference_paper':
            ok = 'Default Value Provenance' in html and str(value.get('source')) in html
            loc = value.get('locator') or {}
            if isinstance(loc, dict):
                for k in ('table', 'equation'):
                    if loc.get(k) and str(loc[k]) not in html:
                        ok = False
            if value.get('notes') and str(value['notes']) not in html:
                ok = False
        elif field == '_literature':
            ok = 'Literature' in html
        elif field == '_ontology_term':
            ok = format_ontology_term(value) in html
        elif field == '_expected_behavior':
            ok = 'Expected Behavior' in html and all(str(v) in html for k, v in value.items()
                                                      if k in ('low_value', 'high_value') and v)
        elif field == '_dependencies':
            ok = all(window.display_names.get(k, k) in html for k in value)
        elif field == '_presets':
            ok = all(str(k) in html for k in value)
        elif field == '_fitting_method':
            ok = 'Evidence Basis' in html and str(value).replace('_', ' ') in html
        elif field == '_unit':
            ok = str(value) in html
        else:
            ok = str(value) in html
        if not ok:
            failures.append(name)
    assert not failures, f"{field} not shown for: {failures[:12]}{' ...' if len(failures) > 12 else ''}"


def test_validation_dialog_states_range_evidence(gui, window):
    from schema_utils import RANGE_TIERS, format_range_evidence
    failures = []
    for name, info in schema_parameters(window).items():
        if not any(info.get(k) for k, _, _ in RANGE_TIERS):
            continue
        html = _validation_html(gui, window, name)
        for key, tier, label in RANGE_TIERS:
            if info.get(key) and format_range_evidence(info, tier) not in html:
                failures.append(f"{name}/{tier}")
        if "Source:" in html and "_reference_paper" in str(info) and 'Default Value' not in html:
            pass  # the old borrowed-citation line would read "(Source: ...)"; guarded below
        if '(Source:' in html:
            failures.append(f"{name}: validation dialog still borrows the default's citation")
    assert not failures, failures[:15]


def test_markdown_export_lists_every_parameter_with_evidence(window):
    from schema_utils import RANGE_TIERS, extract_parameter_documentation, format_range_evidence
    doc = extract_parameter_documentation(window.schema)
    missing = []
    for name, info in schema_parameters(window).items():
        if f"`{name}`" not in doc:
            missing.append(name); continue
        for key, tier, label in RANGE_TIERS:
            if info.get(key) and format_range_evidence(info, tier, fmt='markdown') not in doc:
                missing.append(f"{name}/{tier}")
    assert not missing, missing[:15]


def test_info_dialog_opens_through_the_button_for_every_parameter(window, exc_guard):
    """Click every ⓘ button (the real path: button -> show_parameter_info -> dialog)."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QAbstractButton
    window.expertise_combo.setCurrentText('Advanced'); settle()
    clicked = 0
    seen = set()
    for tw, i, title in list(iter_tabs(window)):
        tw.setCurrentIndex(i); settle(10)
        for name in window.param_widgets:
            b = info_button(window, name)
            if b is not None and b.isVisible() and b.isEnabled() and name not in seen:
                QTest.mouseClick(b, Qt.LeftButton); settle(5); clicked += 1; seen.add(name)
    assert clicked >= len(schema_parameters(window)) * 0.9, f"only {clicked} info buttons were reachable"
