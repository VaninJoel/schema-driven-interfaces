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



def _prepare_sweep(gui, window, replicates):
    """Two swept parameters x `replicates`: enough runs to exceed any small cap."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QLineEdit
    from harness import schema_parameters, settle
    window.expertise_combo.setCurrentText('Advanced'); settle()
    numeric = [n for n, i in schema_parameters(window).items()
               if isinstance(i.get('_default'), float)
               and isinstance(window.param_widgets.get(n, {}).get('input'), QLineEdit)]
    for n in numeric[:2]:
        w = window.param_widgets[n]['input']; d = window.schema['inputs'][n]['_default']
        w.clear(); QTest.keyClicks(w, f"{d:g},{d * 1.1:g}"); QTest.keyClick(w, Qt.Key_Return)
    window.replicate_spinbox.setValue(replicates)
    FW = gui.main_window.SimulationWorker
    FW.instances.clear(); FW.active = 0; FW.peak_active = 0
    return FW


def test_batch_concurrency_cap_is_respected(gui, window, exc_guard):
    """Readiness audit 3.3: a sweep runs at most `Max simultaneous runs` at once,
    queued runs start as slots free, and every run still completes."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from harness import settle
    FW = _prepare_sweep(gui, window, replicates=3)
    FW.delay_s = 0.05
    cap = 2
    window.concurrency_spinbox.setValue(cap)
    QTest.mouseClick(window.run_button, Qt.LeftButton)
    total = window.total_combinations
    assert total >= 4, f"set-up produced only {total} runs"   # V-Cornea runs replicates inside one process
    # the launcher must not have started everything up front
    assert len(FW.instances) <= cap, f"{len(FW.instances)} workers created immediately with cap {cap}"
    for _ in range(400):
        settle(25)
        if window.completed_combinations >= total and window.run_button.isEnabled():
            break
    assert window.completed_combinations == total, f"{window.completed_combinations}/{total} completed"
    assert len(FW.instances) == total
    assert FW.peak_active <= cap, f"{FW.peak_active} runs executed at once; cap was {cap}"
    assert FW.peak_active >= 2, "cap of 2 never reached; concurrency not exercised"
    assert window.run_button.isEnabled() and not window.cancel_button.isVisible()


def test_cancel_drops_queued_runs(gui, window, exc_guard):
    """Cancelling a capped batch stops the queue: nothing queued is ever started."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from harness import settle
    FW = _prepare_sweep(gui, window, replicates=3)
    FW.delay_s = 0.4
    window.concurrency_spinbox.setValue(1)
    QTest.mouseClick(window.run_button, Qt.LeftButton)
    total = window.total_combinations
    settle(50)
    started_before_cancel = len(FW.instances)
    assert started_before_cancel == 1
    QTest.mouseClick(window.cancel_button, Qt.LeftButton)   # QMessageBox.question -> Yes
    settle(800)
    assert window.is_cancelled
    assert len(FW.instances) == started_before_cancel, "a queued run started after Cancel"
    assert not window._pending_runs
    assert window.run_button.isEnabled(), "Run button not restored after cancel"
    FW.delay_s = 0.0


def test_cancel_declined_keeps_the_batch_alive(gui, window, exc_guard, monkeypatch):
    """Answering 'No' to the cancel prompt must not poison the batch (angio used to
    set is_cancelled before asking, so the batch could never finalize)."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QMessageBox
    from harness import settle
    FW = _prepare_sweep(gui, window, replicates=2)
    FW.delay_s = 0.1
    window.concurrency_spinbox.setValue(1)
    monkeypatch.setattr(QMessageBox, 'question', staticmethod(lambda *a, **k: QMessageBox.No))
    QTest.mouseClick(window.run_button, Qt.LeftButton)   # confirmation also answers No...
    if not window.simulation_threads:                     # ...so re-arm with Yes for the launch only
        monkeypatch.setattr(QMessageBox, 'question', staticmethod(lambda *a, **k: QMessageBox.Yes))
        QTest.mouseClick(window.run_button, Qt.LeftButton)
        monkeypatch.setattr(QMessageBox, 'question', staticmethod(lambda *a, **k: QMessageBox.No))
    total = window.total_combinations
    settle(30)
    QTest.mouseClick(window.cancel_button, Qt.LeftButton)   # declined
    assert not window.is_cancelled
    for _ in range(400):
        settle(25)
        if window.completed_combinations >= total and window.run_button.isEnabled():
            break
    assert window.completed_combinations == total, "batch did not finish after a declined cancel"
    FW.delay_s = 0.0
