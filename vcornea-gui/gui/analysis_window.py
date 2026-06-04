"""
Analysis Window for vCornea CellFate Simulation Results.

Provides tabbed CSV/Parquet visualization by output category.
"""

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget, QFileDialog
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from analysis_utils import ExperimentData, detect_time_column, numeric_columns
from analysis_data import AnalysisDataset
from analysis_plot_panel import PlotPanel


CATEGORY_LABELS = {
    'cell_count': 'Cell Counts',
    'thickness': 'Thickness',
    'surfactant': 'Surfactant',
}


class AnalysisWindow(QMainWindow):
    """Main analysis window for CSV/Parquet outputs."""

    def __init__(self, exp_dir: Optional[Path] = None, default_dir: Optional[str] = None):
        super().__init__()
        self.setWindowTitle("vCornea CellFate Analysis & Visualization")
        self.resize(1200, 800)
        self.setMinimumSize(1000, 650)
        self.setStyleSheet(
            "QMainWindow { background: #f7f7f7; }"
            "QGroupBox { font-weight: bold; border: 1px solid #d9d9d9;"
            " border-radius: 6px; margin-top: 12px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
            "QLabel { color: #2c3e50; }"
            "QTabWidget::pane { border: 1px solid #d0d0d0; border-radius: 6px; }"
            "QTabBar::tab { padding: 6px 14px; }"
        )

        self.exp_dir = Path(exp_dir) if exp_dir else None
        self.exp_data = None
        # Where the Browse dialog opens: the output root (so users land among their
        # experiment folders), then the loaded experiment's parent, else cwd.
        self.default_dir = default_dir or (str(self.exp_dir.parent) if self.exp_dir else None)

        self.tab_widgets = {}

        self._build_ui()
        if self.exp_dir:
            self.load_experiment(self.exp_dir)

    def _build_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)

        layout.addWidget(self._build_header())

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.setCentralWidget(central)

    def _build_header(self):
        group = QGroupBox("Experiment")
        grid = QGridLayout(group)

        grid.addWidget(QLabel("Experiment Directory:"), 0, 0)
        self.exp_path_edit = QLineEdit()
        self.exp_path_edit.setReadOnly(True)
        grid.addWidget(self.exp_path_edit, 0, 1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_experiment)
        grid.addWidget(browse_btn, 0, 2)

        self.helper = QLabel(
            "Select an EXPERIMENT folder (the one containing the combo subfolders), "
            "then use the tabs to explore results."
        )
        self.helper.setWordWrap(True)
        self.helper.setStyleSheet("color: #5f6b77;")
        grid.addWidget(self.helper, 1, 0, 1, 3)

        grid.setColumnStretch(1, 1)
        return group

    def browse_experiment(self):
        start = self.default_dir if (self.default_dir and Path(self.default_dir).exists()) else str(Path.cwd())
        selected_dir = QFileDialog.getExistingDirectory(
            self, "Select Experiment Directory (pick the experiment folder, not a single combo, "
                  "to compare combinations)", start
        )
        if selected_dir:
            self.load_experiment(Path(selected_dir))

    def _resolve_experiment_root(self, selected: Path) -> Path:
        """If the user picked a single combo folder of a multi-combo experiment,
        load the parent experiment instead so all combinations are available for
        comparison. (A genuine single-run experiment has no combo siblings, so it
        is left as-is; the Run selector still lets you isolate one combo.)"""
        selected = Path(selected)
        try:
            if 'combo' in selected.name.lower() and selected.parent.exists():
                siblings = [d for d in selected.parent.iterdir()
                            if d.is_dir() and next(d.rglob('cell_count_*.csv'), None) is not None]
                if len(siblings) > 1:
                    print(f"[analysis] '{selected.name}' is one combo of {len(siblings)}; "
                          f"loading the experiment '{selected.parent.name}' for comparison.")
                    return selected.parent
        except Exception:
            pass
        return selected

    def load_experiment(self, exp_dir: Path):
        self.exp_dir = self._resolve_experiment_root(Path(exp_dir))
        self.exp_path_edit.setText(str(self.exp_dir))
        self.exp_data = ExperimentData(self.exp_dir)

        # Replicate-aware, hours-native dataset for the dedicated count/thickness tabs.
        try:
            self.dataset = AnalysisDataset(self.exp_dir)
        except Exception as e:
            print(f"[analysis] dataset load failed: {e}")
            self.dataset = None

        categories = self.exp_data.categories()
        has_dataset = bool(self.dataset and (self.dataset.count_data or self.dataset.thickness_um
                                              or self.dataset.surfactant_data))
        if not categories and not has_dataset:
            QMessageBox.warning(
                self, "No Outputs",
                f"No cell_count/thickness/surfactant outputs found under:\n{self.exp_dir}\n\n"
                "Pick the experiment folder (the one whose subfolders are the runs/combinations)."
            )
            return

        self.tabs.clear()
        self.tab_widgets = {}

        # Dedicated domain tabs (Paper + Enhanced plots) driven by the dataset.
        # The raw single-X/Y viewer for count/thickness/surfactant was removed —
        # these dedicated panels cover them better.
        if self.dataset and self.dataset.count_data:
            self.tabs.addTab(PlotPanel(self.dataset, 'count'), "Cell Counts")
        if self.dataset and self.dataset.thickness_um:
            self.tabs.addTab(PlotPanel(self.dataset, 'thickness'), "Thickness")
        if self.dataset and self.dataset.surfactant_data:
            self.tabs.addTab(PlotPanel(self.dataset, 'surfactant'), "Surfactant")

        # Generic table/line viewer kept only for any *unrecognised* categories
        # (none today: cell_count/thickness/surfactant all have dedicated panels).
        for category in categories:
            if category in ('cell_count', 'thickness', 'surfactant'):
                continue
            label = CATEGORY_LABELS.get(category, category.replace('_', ' ').title())
            tab = self._build_standard_category_tab(category, label)
            self.tabs.addTab(tab, label)

        # Status: how many combinations loaded + how to compare them.
        n = len(self.dataset.count_data) if self.dataset else 0
        if n >= 2:
            self.helper.setText(
                f"Loaded experiment '{self.exp_dir.name}' — {n} combinations. "
                f"To compare them: Cell Counts → Style: Enhanced → Mode: Comparison (or Statistics)."
            )
        elif n == 1:
            self.helper.setText(
                f"Loaded '{self.exp_dir.name}' — 1 combination (no cross-combination comparison). "
                f"Select the parent EXPERIMENT folder to compare multiple combos."
            )

    def _build_standard_category_tab(self, category: str, label: str):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        controls = QGroupBox(f"{label} Controls")
        grid = QGridLayout(controls)

        grid.addWidget(QLabel("Output File:"), 0, 0)
        file_combo = QComboBox()
        file_combo.currentIndexChanged.connect(
            lambda _idx, cat=category: self.on_file_changed(cat)
        )
        grid.addWidget(file_combo, 0, 1, 1, 2)

        grid.addWidget(QLabel("X Axis:"), 1, 0)
        x_combo = QComboBox()
        grid.addWidget(x_combo, 1, 1)

        grid.addWidget(QLabel("Y Axis:"), 1, 2)
        y_combo = QComboBox()
        grid.addWidget(y_combo, 1, 3)

        plot_btn = QPushButton("Plot")
        plot_btn.clicked.connect(lambda _checked, cat=category: self.plot_selected(cat))
        grid.addWidget(plot_btn, 1, 4)

        grid.setColumnStretch(1, 1)
        layout.addWidget(controls)

        plot_group = QGroupBox("Plot")
        plot_layout = QVBoxLayout(plot_group)
        figure = Figure(figsize=(6, 4))
        canvas = FigureCanvas(figure)
        plot_layout.addWidget(canvas)
        layout.addWidget(plot_group)

        table_group = QGroupBox("Table Preview")
        table_layout = QVBoxLayout(table_group)
        table = QTableWidget()
        table_layout.addWidget(table)
        layout.addWidget(table_group)

        self.tab_widgets[category] = {
            'file_combo': file_combo,
            'x_combo': x_combo,
            'y_combo': y_combo,
            'figure': figure,
            'canvas': canvas,
            'table': table,
            'current_df': None,
        }

        self._populate_file_combo(category)
        return widget

    def _populate_file_combo(self, category: str):
        if not self.exp_data:
            return
        widgets = self.tab_widgets[category]
        files = self.exp_data.files_for(category)

        widgets['file_combo'].clear()
        widgets['file_combo'].addItems([path.name for path in files])

        if files:
            widgets['file_combo'].setCurrentIndex(0)

    def on_file_changed(self, category: str):
        if not self.exp_data:
            return

        widgets = self.tab_widgets[category]
        index = widgets['file_combo'].currentIndex()
        try:
            df, _ = self.exp_data.load(category, index)
        except Exception as e:
            # e.g. parquet without pyarrow/fastparquet installed — degrade
            # gracefully instead of crashing the window.
            widgets['current_df'] = None
            table = widgets['table']
            table.clear(); table.setColumnCount(1); table.setRowCount(1)
            table.setHorizontalHeaderLabels(["Could not load file"])
            table.setItem(0, 0, QTableWidgetItem(str(e)))
            table.resizeColumnsToContents()
            return
        if df is None:
            return

        widgets['current_df'] = df
        self._populate_axis_selectors(category, df)
        self._populate_table(category, df)

    def _populate_axis_selectors(self, category: str, df):
        widgets = self.tab_widgets[category]
        x_combo = widgets['x_combo']
        y_combo = widgets['y_combo']

        x_combo.clear()
        y_combo.clear()

        time_col = detect_time_column(df)
        numeric_cols = numeric_columns(df)

        x_choices = [time_col] if time_col else []
        x_choices += [col for col in numeric_cols if col != time_col]

        x_combo.addItems(x_choices)
        y_combo.addItems(numeric_cols)

        if time_col:
            x_combo.setCurrentText(time_col)
        if numeric_cols:
            first_y = numeric_cols[1] if time_col in numeric_cols and len(numeric_cols) > 1 else numeric_cols[0]
            y_combo.setCurrentText(first_y)

    def _populate_table(self, category: str, df, max_rows: int = 200):
        widgets = self.tab_widgets[category]
        table = widgets['table']

        table.clear()
        table.setRowCount(0)
        table.setColumnCount(0)

        if df.empty:
            return

        view_df = df.head(max_rows)
        table.setColumnCount(len(view_df.columns))
        table.setHorizontalHeaderLabels([str(col) for col in view_df.columns])
        table.setRowCount(len(view_df))

        for row_idx, (_, row) in enumerate(view_df.iterrows()):
            for col_idx, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                table.setItem(row_idx, col_idx, item)

        table.resizeColumnsToContents()

    def plot_selected(self, category: str):
        widgets = self.tab_widgets[category]
        df = widgets['current_df']
        if df is None or df.empty:
            QMessageBox.warning(self, "No Data", "No data available to plot.")
            return

        x_col = widgets['x_combo'].currentText()
        y_col = widgets['y_combo'].currentText()

        if not x_col or not y_col:
            QMessageBox.warning(self, "Missing Columns", "Select X and Y columns to plot.")
            return

        figure = widgets['figure']
        figure.clear()
        ax = figure.add_subplot(111)
        ax.plot(df[x_col], df[y_col])
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        ax.set_title(f"{y_col} vs {x_col}")
        ax.grid(True, alpha=0.3)
        widgets['canvas'].draw()
