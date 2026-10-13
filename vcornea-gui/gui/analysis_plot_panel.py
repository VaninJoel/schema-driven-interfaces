"""Embeddable Qt panel for the count/thickness analyses.

Wraps the analysis_plots renderers with controls (Paper vs Enhanced family,
days/hours, mode, injury-centering, scale, combination) and a matplotlib canvas
+ toolbar. Time is days/hours only — never MCS.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QCheckBox, QLabel, QGroupBox,
    QPushButton, QDialog, QTextBrowser, QDialogButtonBox
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
try:
    from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
except ImportError:  # location moved across matplotlib versions
    from matplotlib.backends.backend_qt import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure

import analysis_plots as ap
import analysis_help
from export_provenance import attach_to_figure, build_record


class PlotPanel(QWidget):
    """kind = 'count', 'thickness' or 'surfactant'."""

    def __init__(self, dataset, kind, parent=None):
        super().__init__(parent)
        self.ds = dataset
        self.kind = kind
        self._build()
        self.render()

    def _build(self):
        layout = QVBoxLayout(self)
        controls = QGroupBox("Plot controls")
        row = QHBoxLayout(controls)

        # Surfactant has no paper figure, so no Style selector.
        self.family = QComboBox(); self.family.addItems(["Paper figure", "Enhanced"])
        if self.kind in ('count', 'thickness'):
            row.addWidget(QLabel("Style:")); row.addWidget(self.family)

        row.addWidget(QLabel("Time:"))
        self.unit = QComboBox(); self.unit.addItems(["Days", "Hours"])
        row.addWidget(self.unit)

        self.mode = QComboBox()
        if self.kind == 'count':
            self.mode.addItems(["Individual", "Comparison", "Statistics"])
            row.addWidget(QLabel("Mode:")); row.addWidget(self.mode)
        elif self.kind == 'surfactant':
            self.mode.addItems(["Compare", "Statistics"])
            row.addWidget(QLabel("Mode:")); row.addWidget(self.mode)

        self.scale = QComboBox(); self.scale.addItems(["Absolute", "Percentage", "PctChangeFromBaseline"])
        if self.kind == 'count':
            row.addWidget(QLabel("Scale:")); row.addWidget(self.scale)

        self.injury = QCheckBox("Center on injury")
        self.injury.setEnabled(bool(self.ds.has_injury))
        row.addWidget(self.injury)

        self.combo = QComboBox()
        data = {'count': self.ds.count_data, 'thickness': self.ds.thickness_um,
                'surfactant': self.ds.surfactant_data}[self.kind]
        self.combo.addItems([self.ds.combo_names.get(k, k) for k in data.keys()])
        self._combo_keys = list(data.keys())
        # A Run selector only makes sense where one combination is shown at a time.
        self._uses_combo = self.kind in ('count', 'thickness')
        if self._uses_combo and len(self._combo_keys) > 1:
            row.addWidget(QLabel("Run:")); row.addWidget(self.combo)

        row.addStretch(1)
        self.info_btn = QPushButton("ⓘ  What does this plot show?")
        self.info_btn.setToolTip("Explain the current plot and how to read it")
        self.info_btn.clicked.connect(self._show_info)
        row.addWidget(self.info_btn)
        layout.addWidget(controls)

        self.figure = Figure(figsize=(11, 8))
        # Every save (the toolbar's save button is this panel's export) embeds
        # and sidecars the runs behind the plot as drawn.
        attach_to_figure(self.figure, self._export_record)
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(NavigationToolbar(self.canvas, self))  # zoom/pan/save PNG
        layout.addWidget(self.canvas)

        # Re-render on any control change. mode → _on_family so dependent
        # controls (scale/injury visibility) update before re-rendering.
        self.family.currentIndexChanged.connect(self._on_family)
        self.mode.currentIndexChanged.connect(self._on_family)
        for w in (self.unit, self.scale, self.combo):
            w.currentIndexChanged.connect(self.render)
        self.injury.stateChanged.connect(self.render)
        self._on_family()

    def _on_family(self):
        """Enhanced-only controls are hidden for the Paper style."""
        if self.kind == 'surfactant':
            # No family: surfactant is always 'enhanced'. Injury applies in Compare.
            self.injury.setVisible(self.mode.currentText() == 'Compare')
            self.render()
            return
        enhanced = self.family.currentText() == "Enhanced"
        is_count = self.kind == 'count'
        self.mode.setVisible(enhanced and is_count)
        self.scale.setVisible(enhanced and is_count and self.mode.currentText() != 'Statistics')
        self.injury.setVisible(enhanced)
        self.render()

    def _export_record(self):
        """Provenance of the plot as currently drawn: the selected combination
        when one is shown alone, otherwise every combination of this kind."""
        family = ('enhanced' if self.kind == 'surfactant'
                  else 'paper' if self.family.currentText() == "Paper figure" else 'enhanced')
        mode = self.mode.currentText().lower() if not self.mode.isHidden() else None
        # Mirrors render(): thickness and paper/individual counts draw the selected
        # combination; count comparison/statistics and surfactant draw them all.
        single = (self.kind == 'thickness'
                  or (self.kind == 'count' and (family == 'paper' or mode == 'individual')))
        combos = [self._selected_combo()] if single else list(self._combo_keys)
        view = {'plot': self.kind, 'style': family, 'mode': mode,
                'time_unit': self.unit.currentText().lower(),
                'scale': self.scale.currentText() if not self.scale.isHidden() else None,
                'injury_centered': (self.injury.isChecked()
                                    if not self.injury.isHidden() else None),
                'combinations': [self.ds.combo_names.get(c, c) for c in combos if c]}
        runs = self.ds.source_runs(combos)
        return build_record(runs, 'vcornea-gui analysis', view) if runs else None

    def _selected_combo(self):
        i = self.combo.currentIndex()
        if 0 <= i < len(self._combo_keys):
            return self._combo_keys[i]
        return None

    def _show_info(self):
        """Explain the current plot configuration (kind × style × mode × options)."""
        if self.kind == 'surfactant':
            family = 'enhanced'
        else:
            family = 'paper' if self.family.currentText() == "Paper figure" else 'enhanced'
        unit = 'days' if self.unit.currentText() == 'Days' else 'hours'
        html = analysis_help.build_help(
            self.kind, family, self.mode.currentText().lower(),
            self.injury.isChecked(), self.scale.currentText(), unit, self.ds)
        dlg = QDialog(self)
        dlg.setWindowTitle("About this plot")
        dlg.setMinimumSize(560, 460)
        lay = QVBoxLayout(dlg)
        browser = QTextBrowser()
        browser.setHtml(html)
        lay.addWidget(browser)
        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.accepted.connect(dlg.accept)
        lay.addWidget(bb)
        dlg.exec_()

    def render(self):
        unit = 'days' if self.unit.currentText() == 'Days' else 'hours'
        combo = self._selected_combo()
        paper = self.family.currentText() == "Paper figure"
        try:
            if self.kind == 'count':
                if paper:
                    ap.paper_count(self.figure, self.ds, combo=combo, unit=unit)
                else:
                    ap.enhanced_count(
                        self.figure, self.ds, mode=self.mode.currentText().lower(),
                        combo=combo, unit=unit,
                        injury_centered=self.injury.isChecked(),
                        scale=self.scale.currentText())
            elif self.kind == 'thickness':
                if paper:
                    ap.paper_thickness(self.figure, self.ds, combo=combo, unit=unit)
                else:
                    ap.enhanced_thickness(self.figure, self.ds, combo=combo, unit=unit,
                                          injury_centered=self.injury.isChecked())
            else:  # surfactant
                if self.mode.currentText() == 'Statistics':
                    ap.surfactant_stats(self.figure, self.ds, unit=unit)
                else:
                    ap.surfactant_compare(self.figure, self.ds, unit=unit,
                                          injury_centered=self.injury.isChecked())
        except Exception as e:
            self.figure.clear()
            self.figure.text(0.5, 0.5, f"Plot error:\n{e}", ha='center', va='center', wrap=True)
        self.canvas.draw_idle()
