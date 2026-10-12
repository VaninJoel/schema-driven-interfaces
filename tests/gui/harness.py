"""Shared machinery for the headless GUI tests."""
from __future__ import annotations

import importlib
import json
import random
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]

GUIS = {
    'vcornea': dict(gui_dir=REPO / 'vcornea-gui', pkg_dir=REPO / 'vivarium-vcornea',
                    window_class='VCorneaMainWindow', process_name='VCorneaProcess'),
    'angio': dict(gui_dir=REPO / 'angio-gui', pkg_dir=REPO / 'vivarium-angio',
                  window_class='AngiogenesisMainWindow', process_name='AngiogenesisProcess'),
}

# Both GUIs ship modules with the same bare names (main_window, schema_utils,
# simulation_worker, analysis_*). Loading one GUI must evict the other's.
_GUI_MODULE_NAMES = ('main_window', 'schema_utils', 'simulation_worker', 'analysis_window',
                     'analysis_plots', 'analysis_plot_panel', 'analysis_data', 'analysis_utils',
                     'analysis_help', 'equation_render')


def load_gui(name):
    cfg = GUIS[name]
    for n in list(sys.modules):
        mod = sys.modules[n]
        f = getattr(mod, '__file__', None) or ''
        if n in _GUI_MODULE_NAMES or any(str(c['gui_dir']) in f for c in GUIS.values()):
            del sys.modules[n]
    for other in GUIS.values():
        for sub in ('gui', 'utils'):
            p = str(other['gui_dir'] / sub)
            while p in sys.path:
                sys.path.remove(p)
    for p in (cfg['gui_dir'] / 'gui', cfg['gui_dir'] / 'utils', cfg['pkg_dir']):
        sys.path.insert(0, str(p))
    schema_utils = importlib.import_module('schema_utils')
    main_window = importlib.import_module('main_window')
    return SimpleNamespace(name=name, cfg=cfg, main_window=main_window, schema_utils=schema_utils,
                           window_class=getattr(main_window, cfg['window_class']))


# ---------------------------------------------------------------------------
class ExceptionGuard:
    """Collects exceptions raised inside Qt slots (via sys.excepthook)."""

    def __init__(self):
        self.records = []

    def __enter__(self):
        self._old = sys.excepthook
        sys.excepthook = self._hook
        return self

    def __exit__(self, *exc):
        sys.excepthook = self._old

    def _hook(self, etype, value, tb):
        self.records.append(''.join(traceback.format_exception(etype, value, tb)))

    def raise_if_any(self, context=''):
        if self.records:
            msg = f"{len(self.records)} exception(s) escaped Qt slots{(' during ' + context) if context else ''}:\n\n"
            raise AssertionError(msg + '\n---\n'.join(self.records))


# ---------------------------------------------------------------------------
def quiet_dialogs(monkeypatch, gui, tmp_path):
    """Make every modal dialog return immediately with a sensible answer.

    QDialog.exec_ still shows the dialog and lets it paint (so its HTML is
    generated and rendered) before closing it; the static QMessageBox /
    QFileDialog helpers answer 'yes / ok / <tmp path>' without blocking.
    """
    from PyQt5.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

    def _exec(self):
        self.show()
        QApplication.processEvents()
        self.close()
        return QDialog.Accepted
    monkeypatch.setattr(QDialog, 'exec_', _exec, raising=False)
    monkeypatch.setattr(QDialog, 'exec', _exec, raising=False)
    for name, answer in (('question', QMessageBox.Yes), ('information', QMessageBox.Ok),
                         ('warning', QMessageBox.Ok), ('critical', QMessageBox.Ok),
                         ('about', None)):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, _r=answer, **k: _r))
    save_target = str(tmp_path / 'saved_parameters.json')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        staticmethod(lambda *a, **k: (save_target, 'JSON (*.json)')))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName',
                        staticmethod(lambda *a, **k: (save_target if Path(save_target).exists() else '', '')))
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory',
                        staticmethod(lambda *a, **k: str(tmp_path)))
    # nothing leaves the process: the windows spawn the report tool and the
    # browser via `import subprocess` / `import webbrowser` inside the method,
    # so patch the modules themselves.
    import subprocess, webbrowser
    spawned = []
    monkeypatch.setattr(subprocess, 'Popen',
                        lambda *a, **k: (spawned.append(a), SimpleNamespace(poll=lambda: 0, pid=0, wait=lambda *x: 0))[1])
    monkeypatch.setattr(webbrowser, 'open', lambda *a, **k: True)
    mw = gui.main_window
    monkeypatch.setattr(mw, 'SimulationWorker', _fake_worker_class(), raising=True)


def _fake_worker_class():
    """A worker that 'runs' instantly: writes a run_metadata.json and emits finished."""
    from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

    class FakeWorker(QObject):
        progress = pyqtSignal(int, str)
        finished = pyqtSignal(dict)
        error = pyqtSignal(str)
        instances = []
        delay_s = 0.0          # make runs take time so concurrency is observable
        active = 0             # runs currently inside run()
        peak_active = 0
        lock = __import__('threading').Lock()

        def __init__(self, parameters, output_dir='experiments', parameter_audit=None, **kw):
            super().__init__()
            self.parameters = dict(parameters)
            self.parameter_audit = parameter_audit
            self.output_dir = Path(output_dir)
            self.exp_name = self.parameters.get('exp_name', 'fake_run')
            self.exp_dir = self.output_dir / self.exp_name
            self.cancelled = False
            FakeWorker.instances.append(self)

        @pyqtSlot()
        def run(self):
            with FakeWorker.lock:
                FakeWorker.active += 1
                FakeWorker.peak_active = max(FakeWorker.peak_active, FakeWorker.active)
            if FakeWorker.delay_s:
                time.sleep(FakeWorker.delay_s)
            self.exp_dir.mkdir(parents=True, exist_ok=True)
            (self.exp_dir / 'run_metadata.json').write_text(json.dumps({
                'experiment_id': self.exp_name, 'run_name': self.exp_name,
                'parameters': self.parameters, 'simulation_status': 'success',
                'simulation_success': True, 'final_step': 1,
                'parameter_credibility': (self.parameter_audit or {}).get('summary'),
            }, default=str))
            self.progress.emit(50, 'half')
            self.progress.emit(100, 'done')
            with FakeWorker.lock:
                FakeWorker.active -= 1
            if self.cancelled:
                return
            self.finished.emit({'exp_name': self.exp_name, 'exp_dir': str(self.exp_dir),
                                'final_step': 1, 'parameters': self.parameters,
                                'stdout': '', 'stderr': '', 'zarr_path': str(self.exp_dir / 'data.zarr'),
                                'store_path': str(self.exp_dir / 'data.zarr')})

        def cancel(self):
            self.cancelled = True
    return FakeWorker


# ---------------------------------------------------------------------------
def make_window(gui, tmp_path, monkeypatch):
    mw = gui.main_window
    if gui.name == 'angio':
        # The real constructor starts a CC3D service just to read the schema
        # (readiness audit 4.2). ports_schema()/presets use class attributes only.
        real = mw.AngiogenesisProcess

        class SchemaOnlyAngiogenesisProcess(real):
            def __init__(self, *a, **k):
                pass
        monkeypatch.setattr(mw, 'AngiogenesisProcess', SchemaOnlyAngiogenesisProcess)
    win = gui.window_class()
    win.settings_file = tmp_path / '.gui_settings.json'
    win.output_dir = tmp_path / 'experiments'
    win.output_dir.mkdir(exist_ok=True)
    win.show()
    from PyQt5.QtWidgets import QApplication
    QApplication.processEvents()
    return win


def info_button(win, name):
    """The ⓘ button of a parameter row (a child of the row container)."""
    from PyQt5.QtWidgets import QAbstractButton
    entry = win.param_widgets.get(name) or {}
    for key in ('info', 'info_btn', 'info_button'):
        if isinstance(entry.get(key), QAbstractButton):
            return entry[key]
    container = entry.get('container')
    if container is not None:
        for b in container.findChildren(QAbstractButton):
            if 'ℹ' in (b.text() or ''):
                return b
    return None


def schema_parameters(win):
    """name -> descriptor for every exposed parameter of the window's schema."""
    return {k: v for k, v in win.schema['inputs'].items()
            if isinstance(v, dict) and '_default' in v}


# ---------------------------------------------------------------------------
def visible_buttons(win):
    from PyQt5.QtWidgets import QAbstractButton
    return [b for b in win.findChildren(QAbstractButton) if b.isVisible() and b.isEnabled()]


def button_label(b):
    txt = (b.text() or '').strip() or b.toolTip().strip() or b.objectName() or type(b).__name__
    return txt.replace('\n', ' ')[:60]


def iter_tabs(win):
    """Yield (tab_widget, index, title) for every tab of every QTabWidget."""
    from PyQt5.QtWidgets import QTabWidget
    for tw in win.findChildren(QTabWidget):
        for i in range(tw.count()):
            yield tw, i, tw.tabText(i)


def settle(ms=30):
    from PyQt5.QtTest import QTest
    QTest.qWait(ms)


# ---------------------------------------------------------------------------
class Fuzzer:
    """Seeded random operator: types, clicks, toggles, switches tabs and levels."""

    LINE_EDIT_VALUES = ['', '0', '1', '-1', '1e6', '3.5', 'abc', '1,2,3', '10.0', ' 2 ', '1e-9',
                        'True', 'None', '999999999', '0.000001']

    def __init__(self, win, seed, exc_guard):
        self.win, self.rng, self.guard = win, random.Random(seed), exc_guard
        self.log = []

    def _targets(self):
        from PyQt5.QtWidgets import (QAbstractButton, QCheckBox, QComboBox, QDoubleSpinBox,
                                     QLineEdit, QSlider, QSpinBox, QTabWidget)
        vis = lambda w: w.isVisible() and w.isEnabled()
        return {
            'button': [b for b in self.win.findChildren(QAbstractButton) if vis(b) and not isinstance(b, QCheckBox)],
            'checkbox': [c for c in self.win.findChildren(QCheckBox) if vis(c)],
            'combo': [c for c in self.win.findChildren(QComboBox) if vis(c) and c.count() > 0],
            'line': [e for e in self.win.findChildren(QLineEdit) if vis(e) and not e.isReadOnly()],
            'spin': [s for s in self.win.findChildren((QSpinBox)) if vis(s)]
                    + [s for s in self.win.findChildren(QDoubleSpinBox) if vis(s)],
            'slider': [s for s in self.win.findChildren(QSlider) if vis(s)],
            'tab': [t for t in self.win.findChildren(QTabWidget) if t.isVisible() and t.count() > 1],
        }

    def step(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        t = self._targets()
        kinds = [k for k, v in t.items() if v]
        kind = self.rng.choice(kinds)
        w = self.rng.choice(t[kind])
        desc = f"{kind}:{button_label(w) if kind == 'button' else (w.objectName() or type(w).__name__)}"
        if kind == 'button':
            QTest.mouseClick(w, Qt.LeftButton)
        elif kind == 'checkbox':
            QTest.mouseClick(w, Qt.LeftButton)
        elif kind == 'combo':
            i = self.rng.randrange(w.count()); w.setCurrentIndex(i); desc += f"={w.itemText(i)!r}"
        elif kind == 'line':
            v = self.rng.choice(self.LINE_EDIT_VALUES)
            w.clear(); QTest.keyClicks(w, v); QTest.keyClick(w, Qt.Key_Return); desc += f"={v!r}"
        elif kind == 'spin':
            # keep replicate/step counts small: the GUIs have no concurrency cap, so
            # a large count times a few sweep lists launches thousands of (fake) runs
            lo = int(w.minimum()); v = self.rng.randint(lo, min(int(w.maximum()), lo + 3))
            w.setValue(v); desc += f"={v}"
        elif kind == 'slider':
            v = self.rng.randint(w.minimum(), w.maximum()); w.setValue(v); desc += f"={v}"
        elif kind == 'tab':
            i = self.rng.randrange(w.count()); w.setCurrentIndex(i); desc += f"={w.tabText(i)!r}"
        self.log.append(desc)
        settle(5)
        return desc

    def run(self, steps):
        for n in range(steps):
            self.step()
            if self.guard.records:
                tail = '\n'.join(f"  {i:4d}. {a}" for i, a in enumerate(self.log[-15:], start=max(1, len(self.log) - 14)))
                self.guard.raise_if_any(f"fuzz step {n + 1} (last actions):\n{tail}\n")
            if not self.win.isVisible():
                raise AssertionError(f"window closed during fuzzing at step {n + 1}: {self.log[-5:]}")
        return self.log
