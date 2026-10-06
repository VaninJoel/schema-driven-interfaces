"""Headless GUI tests for both schema-driven GUIs (V-Cornea and Angio).

Runs the real PyQt5 windows under Qt's offscreen platform: no display, no
CompuCell3D process, no simulation subprocess. Everything else is the real
code path — the schema, the widgets, the dialogs, the validation, the
documentation export.

    conda run -n vc --no-capture-output pytest tests/gui -v
    GUI_FUZZ_STEPS=1000 GUI_FUZZ_SEED=7 conda run -n vc pytest tests/gui -k fuzz

See README.md in this directory.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_LOGGING_RULES', '*.debug=false;qt.qpa.*=false')

import pytest  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from harness import GUIS, load_gui, ExceptionGuard, quiet_dialogs, make_window  # noqa: E402


@pytest.fixture(scope='session')
def qapp():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(params=list(GUIS), scope='module')
def gui(request, qapp):
    """The loaded GUI package for one of the two applications."""
    return load_gui(request.param)


@pytest.fixture
def exc_guard():
    """Fail the test on any exception raised inside a Qt slot or event handler.

    PyQt5 aborts the interpreter on an unhandled slot exception when the default
    excepthook is installed; this hook records instead, so a crash in a button
    handler becomes a test failure with a traceback.
    """
    with ExceptionGuard() as g:
        yield g
    g.raise_if_any()


@pytest.fixture
def window(gui, qapp, tmp_path, monkeypatch, exc_guard):
    """A fully constructed main window with modal dialogs neutralised."""
    quiet_dialogs(monkeypatch, gui, tmp_path)
    win = make_window(gui, tmp_path, monkeypatch)
    yield win
    # tear down threads/analysis windows before the next window is built
    for thread, worker in list(getattr(win, 'simulation_threads', []) or []):
        try:
            thread.quit(); thread.wait(2000)
        except Exception:
            pass
    aw = getattr(win, 'analysis_window', None)
    if aw is not None:
        try:
            aw.close()
        except Exception:
            pass
    win.close()
    qapp.processEvents()
