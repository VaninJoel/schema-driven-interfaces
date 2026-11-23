#!/usr/bin/env python
"""Produce an example sweep by operating the real GUI, without a display.

The example runs in this folder are made the way a user makes them — experiment
name, operator name, a comma-separated list typed into one parameter field, a
replicate count, Run — except that the window is created on Qt's off-screen
platform and the clicks are scripted, so the runs can be regenerated unattended
from a source checkout. Everything else is the application's own code: the same
window class, validation, worker, archives and report generation.

    python examples/run_example_sweep.py angio   <out_dir> --name angio_lchem_sweep \
        --operator "A. Operator" --replicates 10 lchem="100, 500, 1000"
    python examples/run_example_sweep.py vcornea <out_dir> --name vcornea_sls_sweep \
        --operator "A. Operator" --replicates 5 SLS_Concentration="1500, 2000, 2500"

Every dialog the application raises is answered as an operator would for a valid
experiment (confirm), and its text is printed, so the log shows exactly what was
asked. The script exits when the batch has finished and its reports exist.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'tests' / 'gui'))


def log(*parts):
    print(time.strftime('[%H:%M:%S]'), *parts, flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('gui', choices=['angio', 'vcornea'])
    ap.add_argument('out_dir')
    ap.add_argument('--name', required=True, help='experiment name typed into the GUI')
    ap.add_argument('--operator', required=True, help='operator name typed into the GUI')
    ap.add_argument('--replicates', type=int, default=1)
    ap.add_argument('--report-wait', type=int, default=1800,
                    help='seconds to wait for the report PDFs after the batch ends')
    ap.add_argument('fields', nargs='*', help='parameter=text exactly as typed in its field')
    args = ap.parse_intermixed_args(argv)

    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from harness import load_gui

    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    gui = load_gui(args.gui)

    # Answer every message box, and print what it said.
    def _answer(kind, reply):
        def box(parent, title, text, *a, **k):
            log(f"dialog [{kind}] {title}: {' '.join(str(text).split())[:600]}")
            return reply
        return staticmethod(box)
    QMessageBox.question = _answer('question -> Yes', QMessageBox.Yes)
    QMessageBox.information = _answer('information', QMessageBox.Ok)
    QMessageBox.warning = _answer('warning', QMessageBox.Ok)
    QMessageBox.critical = _answer('critical', QMessageBox.Ok)

    win = gui.window_class()
    win.settings_file = out / '.gui_settings.json'      # never the user's own settings
    win.output_dir = out
    win.show()
    app.processEvents()

    win.expertise_combo.setCurrentIndex(win.expertise_combo.count() - 1)   # most permissive
    app.processEvents()
    win.exp_name_input.setText(args.name)
    win.operator_name_input.setText(args.operator)
    win.replicate_spinbox.setValue(args.replicates)
    for field in args.fields:
        key, _, text = field.partition('=')
        widget = win.param_widgets[key]['input']
        if not hasattr(widget, 'setText'):
            raise SystemExit(f"{key}: this driver only types into text fields")
        widget.setText(text)
        widget.editingFinished.emit() if hasattr(widget, 'editingFinished') else None
        log(f"typed {key} = {text!r}")
    app.processEvents()

    state = {'done': False, 'cancelled': None, 'finished_at': None}
    real_finalize = win.finalize_batch

    def finalize(was_cancelled=False):
        result = real_finalize(was_cancelled)
        state.update(done=True, cancelled=bool(was_cancelled), finished_at=time.time())
        log(f"batch finished (cancelled={bool(was_cancelled)})")
        return result
    win.finalize_batch = finalize

    def poll():
        if not state['done']:
            return
        reports = list(out.rglob('*_report.pdf'))
        waited = time.time() - state['finished_at']
        if any('experiment_report' in p.name for p in reports) or waited > args.report_wait:
            log(f"{len(reports)} report(s) present after {waited:.0f} s; closing")
            timer.stop()
            app.quit()

    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(5000)

    log(f"pressing Run: {args.gui} / {args.name} / {args.replicates} replicate(s) -> {out}")
    QTimer.singleShot(0, win.run_simulation)
    app.exec_()
    archives = sorted(out.rglob('*.omex'))
    log(f"{len(archives)} archive(s), {len(list(out.rglob('*_report.pdf')))} report(s) under {out}")
    return 0 if state['done'] and not state['cancelled'] else 1


if __name__ == '__main__':
    sys.exit(main())
