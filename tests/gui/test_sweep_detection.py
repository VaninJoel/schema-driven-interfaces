"""A sweep sweeps the model parameters the operator listed, and nothing else.

Both GUIs used to scan every entry of current_params for a comma. The creator
record set by the operator name/email fields is a dict whose str() contains a
comma, so filling in an operator name silently swept two garbage "creator"
values: twice the runs, half of them labelled with a fragment of the name.
"""
SWEEP = {'vcornea': ('SLS_Concentration', '250, 750, 2000'),
         'angio': ('lchem', '100, 500, 1000')}


def test_operator_name_is_not_swept(window, gui):
    name, values = SWEEP[gui.name]
    window.operator_name_input.setText('Joel Vanin')
    window.operator_email_input.setText('jv@example.org')
    assert window.current_params['creator']          # the dict that used to be swept
    window.param_widgets[name]['input'].setText(values)

    assert window.detect_sweep_parameters()
    assert list(window.sweep_parameters) == [name]
    assert len(window.sweep_parameters[name]) == 3

    combos = window.generate_parameter_combinations()
    assert len(combos) == 3
    # every run carries the operator's creator record intact
    assert all(c['creator'] == window.current_params['creator'] for c in combos)
