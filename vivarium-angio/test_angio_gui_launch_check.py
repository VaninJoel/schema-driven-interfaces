"""What the Angio-GUI does at launch with values the schema flags.

Drives the real main window off-screen (no display, a stand-in worker, no
CompuCell3D), using the repository's GUI test harness:

  * a malformed value never launches — there is no "proceed anyway";
  * a value outside an implementation limit launches only if the operator
    confirms, and the run's record then says it was allowed and confirmed;
  * a value outside the documented working range needs confirmation too, and is
    recorded without any permission flag;
  * a value outside the recommended range only is marked, recorded, and not
    asked about;
  * the dialogs say what is true (no blanket "simulation may crash").
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip('PyQt5')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'tests' / 'gui'))

import harness  # noqa: E402


@pytest.fixture(scope='module')
def qapp():
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def launch(qapp, tmp_path, monkeypatch):
    """(window, asked, launched): `asked` collects (kind, title, text) of every
    message box; `launched` the stand-in workers created. The answer to a
    question is taken from asked.answer (default Yes)."""
    from PyQt5.QtWidgets import QMessageBox
    gui = harness.load_gui('angio')
    with harness.ExceptionGuard() as guard:
        harness.quiet_dialogs(monkeypatch, gui, tmp_path)
        win = harness.make_window(gui, tmp_path, monkeypatch)

        class Asked(list):
            answer = QMessageBox.Yes
        asked = Asked()

        def box(kind):
            def _show(parent, title, text, *a, **k):
                asked.append((kind, title, text))
                return asked.answer if kind == 'question' else QMessageBox.Ok
            return staticmethod(_show)
        for kind in ('question', 'warning'):
            monkeypatch.setattr(QMessageBox, kind, box(kind))
        fake = gui.main_window.SimulationWorker
        fake.instances.clear()
        created = []
        real_make = win._make_worker

        def make(params_copy):
            worker = real_make(params_copy)
            created.append((worker, win._check_run_specification(dict(params_copy))))
            return worker
        win._make_worker = make
        yield win, asked, created
        for thread, _ in list(getattr(win, 'simulation_threads', []) or []):
            try:
                thread.quit(); thread.wait(2000)
            except Exception:
                pass
        win.close()
        guard.raise_if_any('launch-check test')


def _set(win, name, text):
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    win.expertise_combo.setCurrentText('Advanced')
    harness.settle(20)
    field = win.param_widgets[name]['input']
    field.clear()
    QTest.keyClicks(field, text)
    QTest.keyClick(field, Qt.Key_Return)
    harness.settle(20)


def _run(win, wait=True):
    win.run_simulation()
    deadline = time.time() + 20
    while wait and time.time() < deadline and not win.run_button.isEnabled():
        harness.settle(50)


def test_malformed_value_is_refused_without_a_proceed_option(launch):
    win, asked, created = launch
    _set(win, 'vedir', 'abc')
    _run(win, wait=False)
    assert created == []
    assert [k for k, _, _ in asked] == ['warning']          # told, not asked
    kind, title, text = asked[0]
    assert 'malformed' in title.lower() and 'Nothing was started' in text


def test_inadmissible_value_runs_only_on_confirmation_which_is_recorded(launch):
    from PyQt5.QtWidgets import QMessageBox
    win, asked, created = launch
    _set(win, 'vedir', '12')
    assert win.param_widgets['vedir']['validation'].text() == '❌'

    asked.answer = QMessageBox.No
    _run(win, wait=False)
    assert created == []                                     # declined: nothing launched
    question = next(text for kind, _, text in asked if kind == 'question')
    assert 'implementation limit' in question and 'recorded' in question
    assert 'crash' not in question.lower() and 'nonsensical' not in question.lower()

    asked.answer = QMessageBox.Yes
    _run(win)
    [(worker, _)] = created
    assert worker.parameters['allow_inadmissible'] is True
    check = win._check_run_specification(dict(worker.parameters))
    assert check['allow_inadmissible'] is True and check['confirmed_by_operator'] is True
    assert check['checked_by'] == 'gui' and check['n_inadmissible'] == 1


def test_value_outside_the_working_range_is_confirmed_and_recorded_without_permission(launch):
    win, asked, created = launch
    _set(win, 'vedir', '3')
    assert win.param_widgets['vedir']['validation'].text() == '⚠️'
    _run(win)
    [(worker, check)] = created
    assert 'allow_inadmissible' not in worker.parameters
    assert check['allow_inadmissible'] is False and check['confirmed_by_operator'] is True
    assert [(i['parameter'], i['tier']) for i in check['issues']] == [('vedir', 'physiological')]
    question = next(text for kind, title, text in asked
                    if kind == 'question' and 'documented ranges' in title)
    assert 'documented working range' in question and 'range set by' in question


def test_value_outside_the_recommended_range_only_is_marked_not_asked_about(launch):
    win, asked, created = launch
    _set(win, 'vedir', '1.8')
    indicator = win.param_widgets['vedir']['validation']
    assert indicator.text() == 'ℹ' and 'recommended range' in indicator.toolTip()
    _run(win)
    assert not any('documented ranges' in title for _, title, _ in asked)
    [(worker, check)] = created
    assert check['confirmed_by_operator'] is None and check['n_outside_range'] == 1
    assert check['issues'][0]['tier'] == 'recommended'


def test_validation_dialog_never_calls_an_out_of_range_value_valid(launch):
    win, _, _ = launch
    gui = harness.load_gui('angio')
    dialog_class = gui.main_window.ValidationInfoDialog
    from schema_utils import validate_parameter_value
    info = win.schema['inputs']['vedir']

    def html(value):
        return dialog_class._generate_html(
            None, 'vedir', info, value, validate_parameter_value(win.schema, 'vedir', value))
    assert 'No finding' in html(1.0)
    for value in (1.8, 3.0, 12.0):
        text = html(value)
        assert 'No finding' not in text and 'VALID' not in text
        assert 'range set by' in text
    assert 'crash' not in html(12.0).lower()
