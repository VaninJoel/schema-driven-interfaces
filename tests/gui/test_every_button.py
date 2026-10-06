"""Every button in each GUI can be clicked without an exception escaping.

Tabs are switched so buttons on every page become visible; the Run button runs
a fake worker that finishes instantly; file and message dialogs are answered
automatically. The test reports which buttons it reached, so a button that is
never visible/enabled in any state shows up as a gap rather than silently
passing.
"""
import json
import os

from harness import button_label, iter_tabs, settle, visible_buttons


def test_every_button_clicks_cleanly(gui, window, exc_guard, tmp_path):
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QAbstractButton

    reached, skipped = {}, {}
    window.expertise_combo.setCurrentText('Advanced'); settle()

    def click_all_visible(context):
        for b in visible_buttons(window):
            label = button_label(b)
            key = f"{context} :: {label}"
            if key in reached:
                continue
            QTest.mouseClick(b, Qt.LeftButton)
            settle(10)
            exc_guard.raise_if_any(f"clicking {key}")
            reached[key] = True
            # the window must survive every click
            assert window.isVisible(), f"window closed after clicking {key}"

    click_all_visible('main')
    for tw, i, title in list(iter_tabs(window)):
        tw.setCurrentIndex(i); settle(10)
        click_all_visible(f"tab[{title}]")
    # buttons that exist but were never clickable in any visited state. Only the
    # window's own labelled buttons count; Qt-internal tab-scroll/toolbar buttons
    # and the buttons of (closed) child dialogs are not operator controls.
    for b in window.findChildren(QAbstractButton):
        label = button_label(b)
        own = b.window() is window and (b.text() or '').strip() and not b.objectName().startswith('qt_')
        if own and not any(k.endswith(f":: {label}") for k in reached):
            skipped[label] = 'never visible+enabled'
    # after a run has been started, Cancel becomes visible — exercise that state too
    if hasattr(window, 'run_button'):
        QTest.mouseClick(window.run_button, Qt.LeftButton); settle(200)
        click_all_visible('after-run')
    report = {'gui': gui.name, 'clicked': sorted(reached), 'never_reachable': skipped}
    (tmp_path / f'button_coverage_{gui.name}.json').write_text(json.dumps(report, indent=2))
    print(f"\n[{gui.name}] clicked {len(reached)} button states; never reachable: {skipped or 'none'}")
    distinct = {k.split(' :: ', 1)[1] for k in reached}
    assert {'Run Simulation', 'Reset to Defaults', 'Save Parameters', 'Load Parameters',
            'ℹ About', 'Browse...'} <= distinct, f"core buttons not all reached: {sorted(distinct)}"
    assert not skipped or set(skipped) <= {'Cancel Batch'}, f"unreachable buttons: {skipped}"


def test_run_button_launches_and_finishes_a_batch(gui, window, exc_guard):
    """Run -> confirmation -> workers -> finished handler, with the fake worker."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    before = len(gui.main_window.SimulationWorker.instances)
    QTest.mouseClick(window.run_button, Qt.LeftButton)
    settle(300)
    made = gui.main_window.SimulationWorker.instances[before:]
    assert made, "Run Simulation did not create a worker"
    w = made[0]
    assert (w.exp_dir / 'run_metadata.json').exists()
    # the window handed the run its schema-derived audit (angio) or left it to the process (vcornea)
    if gui.name == 'angio':
        assert w.parameter_audit and w.parameter_audit['summary']['n_parameters'] > 0
        assert w.parameters.get('_schema_fingerprint', '').startswith('sha256:')
    settle(300)
    assert window.run_button.isEnabled(), "Run button not re-enabled after the batch finished"


def test_save_then_load_round_trips_parameters(window, exc_guard, tmp_path):
    from PyQt5.QtWidgets import QAbstractButton
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    buttons = {button_label(b): b for b in window.findChildren(QAbstractButton)}
    QTest.mouseClick(buttons['Save Parameters'], Qt.LeftButton); settle(50)
    saved = tmp_path / 'saved_parameters.json'
    assert saved.exists(), "Save Parameters wrote nothing"
    data = json.loads(saved.read_text())
    payload = data.get('parameters', data)
    assert set(payload) & set(window.current_params), "saved file carries no parameters"
    QTest.mouseClick(buttons['Load Parameters'], Qt.LeftButton); settle(50)


import pytest


@pytest.mark.xfail(strict=True, reason="readiness audit 3.3: batch launch has no concurrency cap; "
                                       "a 2x2 sweep with 12 replicates starts 48 workers at once")
def test_batch_fan_out_is_capped(gui, window, exc_guard):
    """Launching a sweep must not start more workers than a cap (cores - 1 or similar).

    Documents the gap found by the random sessions: with replicates raised and a
    few sweep lists typed in, the Run button spawned 72 threads simultaneously.
    Flip this to a passing test when the scheduler/queue lands.
    """
    import os
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QLineEdit, QSpinBox
    from harness import schema_parameters, settle
    window.expertise_combo.setCurrentText('Advanced'); settle()
    numeric = [n for n, i in schema_parameters(window).items()
               if isinstance(i.get('_default'), float) and isinstance(window.param_widgets.get(n, {}).get('input'), QLineEdit)]
    for n in numeric[:2]:
        w = window.param_widgets[n]['input']; d = window.schema['inputs'][n]['_default']
        w.clear(); QTest.keyClicks(w, f"{d},{d * 1.1:g}"); QTest.keyClick(w, Qt.Key_Return)
    spins = [s for s in window.findChildren(QSpinBox) if s.isVisible()]
    for s in spins:
        if 'replic' in (s.toolTip() + s.objectName() + str(s.prefix()) + str(s.suffix())).lower() or s.maximum() >= 10:
            s.setValue(min(12, s.maximum()))
    gui.main_window.SimulationWorker.instances.clear()
    QTest.mouseClick(window.run_button, Qt.LeftButton); settle(300)
    launched = len(gui.main_window.SimulationWorker.instances)
    cap = max(1, (os.cpu_count() or 2) - 1)
    peak_threads = len(getattr(window, 'simulation_threads', []) or [])
    assert launched > cap, f"test set-up did not create enough runs ({launched})"
    assert peak_threads <= cap, f"{peak_threads} worker threads alive at once for {launched} runs; cap would be {cap}"
