"""
Analysis and Visualization Window for Angiogenesis Simulation Results.

Provides tabs for:
- Network metrics analysis and time series plots
- Cell field and VEGF visualization
- Data export (CSV, images, animations)
- Multi-experiment comparison

Author: GUI Implementation
Date: 2025
"""

import sys
from pathlib import Path
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QLabel, QComboBox, QSlider, QTableWidget, QTableWidgetItem,
    QFileDialog, QMessageBox, QGroupBox, QCheckBox, QSpinBox, QProgressBar,
    QTextEdit
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont

# Import matplotlib for plotting
try:
    import matplotlib
    matplotlib.use('Qt5Agg')
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
    from matplotlib.figure import Figure
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("Warning: matplotlib not available. Plotting features disabled.")

import numpy as np

# Import analysis utilities
from analysis_utils import (
    ExperimentData, compute_network_metrics, compute_vegf_statistics,
    analyze_time_series, export_metrics_to_csv, find_experiments,
    create_animation_frames, export_animation_gif, export_animation_mp4,
    detect_cell_boundaries,
    ZARR_AVAILABLE, SCIPY_AVAILABLE
)


class AnalysisWindow(QMainWindow):
    """Main analysis and visualization window."""

    def __init__(self, output_dir: Path = None, parent=None):
        super().__init__(parent)

        self.output_dir = output_dir
        self.current_experiment = None
        self.experiments = []  # For comparison
        self.vegf_vmin = None  # Global VEGF min for locked colorbar
        self.vegf_vmax = None  # Global VEGF max for locked colorbar

        self.setWindowTitle("Angiogenesis Analysis & Visualization")
        self.setGeometry(100, 100, 1200, 800)

        # Check dependencies
        if not ZARR_AVAILABLE:
            QMessageBox.warning(
                self,
                "Missing Dependency",
                "zarr package not installed. Analysis features will be limited.\n\n"
                "Install with: pip install zarr"
            )

        self.init_ui()

    def init_ui(self):
        """Initialize the UI with tabs."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Top controls - experiment selection
        controls_layout = QHBoxLayout()

        controls_layout.addWidget(QLabel("Experiment:"))
        self.experiment_combo = QComboBox()
        self.experiment_combo.currentIndexChanged.connect(self.on_experiment_changed)
        controls_layout.addWidget(self.experiment_combo, 1)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_experiment)
        controls_layout.addWidget(browse_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_experiments)
        controls_layout.addWidget(refresh_btn)

        controls_layout.addStretch()
        main_layout.addLayout(controls_layout)

        # Tab widget
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # Create tabs
        self.create_metrics_tab()
        self.create_visualization_tab()
        self.create_export_tab()
        self.create_statistics_tab()
        self.create_comparison_tab()

        # Initial load
        if self.output_dir:
            self.refresh_experiments()

    def create_metrics_tab(self):
        """Create tab for network metrics and statistics."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Metrics table
        table_group = QGroupBox("Network Metrics")
        table_layout = QVBoxLayout()

        self.metrics_table = QTableWidget()
        self.metrics_table.setColumnCount(2)
        self.metrics_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self.metrics_table.horizontalHeader().setStretchLastSection(True)
        table_layout.addWidget(self.metrics_table)

        table_group.setLayout(table_layout)
        layout.addWidget(table_group, stretch=1)

        # Time series plots
        if MATPLOTLIB_AVAILABLE:
            plot_group = QGroupBox("Time Series Analysis")
            plot_layout = QVBoxLayout()

            # Create matplotlib figure
            self.metrics_figure = Figure(figsize=(10, 6))
            self.metrics_canvas = FigureCanvas(self.metrics_figure)
            self.metrics_toolbar = NavigationToolbar(self.metrics_canvas, self)

            plot_layout.addWidget(self.metrics_toolbar)
            plot_layout.addWidget(self.metrics_canvas)

            plot_group.setLayout(plot_layout)
            layout.addWidget(plot_group, stretch=2)

        # Export button
        export_layout = QHBoxLayout()
        export_csv_btn = QPushButton("Export Metrics to CSV")
        export_csv_btn.clicked.connect(self.export_metrics_csv)
        export_layout.addWidget(export_csv_btn)
        export_layout.addStretch()
        layout.addLayout(export_layout)

        self.tabs.addTab(tab, "📊 Metrics")

    def create_visualization_tab(self):
        """Create tab for cell field and VEGF visualization."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        if not MATPLOTLIB_AVAILABLE:
            layout.addWidget(QLabel("Matplotlib not available. Install with: pip install matplotlib"))
            self.tabs.addTab(tab, "🔬 Visualization")
            return

        # Controls
        controls_layout = QHBoxLayout()

        controls_layout.addWidget(QLabel("Timestep:"))
        self.timestep_combo = QComboBox()
        self.timestep_combo.currentIndexChanged.connect(self.update_visualization)
        controls_layout.addWidget(self.timestep_combo)

        controls_layout.addSpacing(20)

        # Layer toggles
        self.show_cells_check = QCheckBox("Show Cells")
        self.show_cells_check.setChecked(True)
        self.show_cells_check.stateChanged.connect(self.update_visualization)
        controls_layout.addWidget(self.show_cells_check)

        self.show_vegf_check = QCheckBox("Show VEGF")
        self.show_vegf_check.setChecked(True)
        self.show_vegf_check.stateChanged.connect(self.update_visualization)
        controls_layout.addWidget(self.show_vegf_check)

        self.show_boundaries_check = QCheckBox("Show Cell Borders")
        self.show_boundaries_check.setChecked(False)
        self.show_boundaries_check.stateChanged.connect(self.update_visualization)
        controls_layout.addWidget(self.show_boundaries_check)

        controls_layout.addStretch()

        # Animation controls
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.clicked.connect(self.toggle_animation)
        controls_layout.addWidget(self.play_btn)

        layout.addLayout(controls_layout)

        # Visualization canvas
        self.viz_figure = Figure(figsize=(12, 6))
        self.viz_canvas = FigureCanvas(self.viz_figure)
        self.viz_toolbar = NavigationToolbar(self.viz_canvas, self)

        layout.addWidget(self.viz_toolbar)
        layout.addWidget(self.viz_canvas)

        self.tabs.addTab(tab, "🔬 Visualization")

        # Animation state
        self.animation_playing = False
        self.animation_timer = None

    def create_export_tab(self):
        """Create tab for exporting data and images."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # CSV Export
        csv_group = QGroupBox("CSV Export")
        csv_layout = QVBoxLayout()

        csv_btn = QPushButton("Export Metrics to CSV")
        csv_btn.clicked.connect(self.export_metrics_csv)
        csv_layout.addWidget(csv_btn)

        csv_label = QLabel("Export time series metrics (clusters, density, VEGF stats) to CSV file.")
        csv_label.setWordWrap(True)
        csv_layout.addWidget(csv_label)

        csv_group.setLayout(csv_layout)
        layout.addWidget(csv_group)

        # Image Export
        image_group = QGroupBox("Image Export")
        image_layout = QVBoxLayout()

        image_btn = QPushButton("Export Current Frame as PNG")
        image_btn.clicked.connect(self.export_frame_png)
        image_layout.addWidget(image_btn)

        image_label = QLabel("Export the currently displayed visualization as a high-resolution PNG image.")
        image_label.setWordWrap(True)
        image_layout.addWidget(image_label)

        image_group.setLayout(image_layout)
        layout.addWidget(image_group)

        # Animation Export
        anim_group = QGroupBox("Animation Export")
        anim_layout = QVBoxLayout()

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("FPS:"))
        self.fps_spinbox = QSpinBox()
        self.fps_spinbox.setRange(1, 30)
        self.fps_spinbox.setValue(5)
        controls_layout.addWidget(self.fps_spinbox)
        controls_layout.addStretch()
        anim_layout.addLayout(controls_layout)

        # Layer options for animation
        layer_layout = QHBoxLayout()
        self.anim_show_cells = QCheckBox("Show Cells")
        self.anim_show_cells.setChecked(True)
        layer_layout.addWidget(self.anim_show_cells)

        self.anim_show_vegf = QCheckBox("Show VEGF")
        self.anim_show_vegf.setChecked(True)
        layer_layout.addWidget(self.anim_show_vegf)

        self.anim_show_boundaries = QCheckBox("Show Cell Borders")
        self.anim_show_boundaries.setChecked(False)
        layer_layout.addWidget(self.anim_show_boundaries)
        layer_layout.addStretch()
        anim_layout.addLayout(layer_layout)

        mp4_btn = QPushButton("Export Animation as MP4")
        mp4_btn.clicked.connect(self.export_animation_mp4)
        anim_layout.addWidget(mp4_btn)

        gif_btn = QPushButton("Export Animation as GIF")
        gif_btn.clicked.connect(self.export_animation_gif)
        anim_layout.addWidget(gif_btn)

        anim_label = QLabel("Create an animation showing the time evolution of the simulation.")
        anim_label.setWordWrap(True)
        anim_layout.addWidget(anim_label)

        anim_group.setLayout(anim_layout)
        layout.addWidget(anim_group)

        # Plot Export
        plot_group = QGroupBox("Plot Export")
        plot_layout = QVBoxLayout()

        plot_btn = QPushButton("Export Metric Plots as PNG")
        plot_btn.clicked.connect(self.export_plots_png)
        plot_layout.addWidget(plot_btn)

        plot_label = QLabel("Export the time series metric plots as PNG images.")
        plot_label.setWordWrap(True)
        plot_layout.addWidget(plot_label)

        plot_group.setLayout(plot_layout)
        layout.addWidget(plot_group)

        layout.addStretch()

        self.tabs.addTab(tab, "💾 Export")

    def create_comparison_tab(self):
        """Create tab for comparing multiple experiments."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Experiment selection
        select_group = QGroupBox("Select Experiments to Compare")
        select_layout = QVBoxLayout()

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Add Experiment")
        add_btn.clicked.connect(self.add_comparison_experiment)
        btn_layout.addWidget(add_btn)

        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self.clear_comparison_experiments)
        btn_layout.addWidget(clear_btn)
        btn_layout.addStretch()
        select_layout.addLayout(btn_layout)

        self.comparison_list = QTextEdit()
        self.comparison_list.setReadOnly(True)
        self.comparison_list.setMaximumHeight(100)
        select_layout.addWidget(self.comparison_list)

        select_group.setLayout(select_layout)
        layout.addWidget(select_group)

        # Comparison plots
        if MATPLOTLIB_AVAILABLE:
            plot_group = QGroupBox("Comparison Plots")
            plot_layout = QVBoxLayout()

            self.comparison_figure = Figure(figsize=(12, 8))
            self.comparison_canvas = FigureCanvas(self.comparison_figure)
            self.comparison_toolbar = NavigationToolbar(self.comparison_canvas, self)

            plot_layout.addWidget(self.comparison_toolbar)
            plot_layout.addWidget(self.comparison_canvas)

            plot_group.setLayout(plot_layout)
            layout.addWidget(plot_group, stretch=1)

        # Generate comparison button
        compare_btn = QPushButton("Generate Comparison")
        compare_btn.clicked.connect(self.generate_comparison)
        layout.addWidget(compare_btn)

        self.tabs.addTab(tab, "📈 Comparison")

    # =========================================================================
    # EXPERIMENT LOADING
    # =========================================================================

    def browse_experiment(self):
        """Browse for experiment directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Experiment or Output Directory",
            str(self.output_dir) if self.output_dir else str(Path.home())
        )

        if directory:
            directory = Path(directory)

            # Check if this is an experiment directory or contains experiments
            if (directory / 'data.zarr').exists():
                # Single experiment
                self.load_experiment(directory)
            else:
                # Directory containing experiments
                self.output_dir = directory
                self.refresh_experiments()

    def refresh_experiments(self):
        """Refresh list of available experiments."""
        if not self.output_dir:
            return

        experiments = find_experiments(self.output_dir)

        self.experiment_combo.blockSignals(True)
        self.experiment_combo.clear()

        for exp_path in experiments:
            self.experiment_combo.addItem(exp_path.name, str(exp_path))

        self.experiment_combo.blockSignals(False)

        if experiments:
            self.on_experiment_changed(0)

    def on_experiment_changed(self, index):
        """Handle experiment selection change."""
        if index < 0:
            return

        exp_path = self.experiment_combo.itemData(index)
        if exp_path:
            self.load_experiment(Path(exp_path))

    def load_experiment(self, exp_path: Path):
        """Load experiment data."""
        try:
            self.current_experiment = ExperimentData(exp_path)

            # Compute global VEGF range for locked colorbar
            self.statusBar().showMessage(f"Computing VEGF range for {exp_path.name}...")
            self.vegf_vmin, self.vegf_vmax = self.current_experiment.get_vegf_global_range()

            # Update timestep combo
            self.timestep_combo.blockSignals(True)
            self.timestep_combo.clear()
            for timestep in self.current_experiment.timesteps:
                self.timestep_combo.addItem(f"Step {timestep}", timestep)
            self.timestep_combo.blockSignals(False)

            # Update displays
            self.update_metrics_display()
            self.update_visualization()

            self.statusBar().showMessage(
                f"Loaded: {exp_path.name} | VEGF range: [{self.vegf_vmin:.4f}, {self.vegf_vmax:.4f}]"
            )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load experiment:\n{str(e)}")

    # =========================================================================
    # METRICS TAB
    # =========================================================================

    def update_metrics_display(self):
        """Update metrics table and plots."""
        if not self.current_experiment:
            return

        # Analyze time series
        time_series = analyze_time_series(self.current_experiment)

        # Update table with latest timestep metrics
        if time_series['network_metrics']:
            latest_metrics = time_series['network_metrics'][-1]
            self.populate_metrics_table(latest_metrics)

        # Plot time series
        if MATPLOTLIB_AVAILABLE and time_series['timesteps']:
            self.plot_time_series(time_series)

    def populate_metrics_table(self, metrics: dict):
        """Populate metrics table."""
        self.metrics_table.setRowCount(len(metrics))

        for row, (key, value) in enumerate(metrics.items()):
            # Metric name
            name_item = QTableWidgetItem(key.replace('_', ' ').title())
            self.metrics_table.setItem(row, 0, name_item)

            # Metric value
            if value is None:
                value_str = "N/A"
            elif isinstance(value, float):
                value_str = f"{value:.4f}"
            else:
                value_str = str(value)

            value_item = QTableWidgetItem(value_str)
            self.metrics_table.setItem(row, 1, value_item)

    def plot_time_series(self, time_series: dict):
        """Plot time series metrics."""
        self.metrics_figure.clear()

        timesteps = time_series['timesteps']
        network_metrics = time_series['network_metrics']
        vegf_stats = time_series['vegf_stats']

        # Create subplots
        gs = self.metrics_figure.add_gridspec(2, 2, hspace=0.3, wspace=0.3)

        # Plot 1: Cell density over time
        ax1 = self.metrics_figure.add_subplot(gs[0, 0])
        if network_metrics:
            densities = [m['cell_density'] for m in network_metrics]
            ax1.plot(timesteps, densities, 'b-o', linewidth=2)
            ax1.set_xlabel('Timestep (MCS)')
            ax1.set_ylabel('Cell Density')
            ax1.set_title('Cell Density Over Time')
            ax1.grid(True, alpha=0.3)

        # Plot 2: Number of clusters
        ax2 = self.metrics_figure.add_subplot(gs[0, 1])
        if network_metrics and SCIPY_AVAILABLE:
            clusters = [m.get('num_clusters', 0) for m in network_metrics]
            ax2.plot(timesteps, clusters, 'r-o', linewidth=2)
            ax2.set_xlabel('Timestep (MCS)')
            ax2.set_ylabel('Number of Clusters')
            ax2.set_title('Network Fragmentation')
            ax2.grid(True, alpha=0.3)

        # Plot 3: VEGF mean concentration
        ax3 = self.metrics_figure.add_subplot(gs[1, 0])
        if vegf_stats:
            vegf_mean = [v['mean'] for v in vegf_stats]
            ax3.plot(timesteps, vegf_mean, 'g-o', linewidth=2)
            ax3.set_xlabel('Timestep (MCS)')
            ax3.set_ylabel('Mean VEGF Concentration')
            ax3.set_title('VEGF Field Evolution')
            ax3.grid(True, alpha=0.3)

        # Plot 4: VEGF statistics (min, max, mean)
        ax4 = self.metrics_figure.add_subplot(gs[1, 1])
        if vegf_stats:
            vegf_min = [v['min'] for v in vegf_stats]
            vegf_max = [v['max'] for v in vegf_stats]
            vegf_mean = [v['mean'] for v in vegf_stats]

            ax4.plot(timesteps, vegf_min, 'b-', linewidth=2, label='Min', alpha=0.7)
            ax4.plot(timesteps, vegf_mean, 'g-', linewidth=2, label='Mean')
            ax4.plot(timesteps, vegf_max, 'r-', linewidth=2, label='Max', alpha=0.7)
            ax4.fill_between(timesteps, vegf_min, vegf_max, alpha=0.2, color='gray')
            ax4.set_xlabel('Timestep (MCS)')
            ax4.set_ylabel('VEGF Concentration')
            ax4.set_title('VEGF Range')
            ax4.legend()
            ax4.grid(True, alpha=0.3)

        self.metrics_canvas.draw()

    def export_metrics_csv(self):
        """Export metrics to CSV file."""
        if not self.current_experiment:
            QMessageBox.warning(self, "No Data", "Please load an experiment first.")
            return

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Metrics CSV",
            f"{self.current_experiment.exp_name}_metrics.csv",
            "CSV Files (*.csv)"
        )

        if filename:
            try:
                time_series = analyze_time_series(self.current_experiment)
                export_metrics_to_csv(time_series, Path(filename))
                QMessageBox.information(self, "Success", f"Metrics exported to:\n{filename}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export metrics:\n{str(e)}")

    # =========================================================================
    # VISUALIZATION TAB
    # =========================================================================

    def update_visualization(self):
        """Update cell field and VEGF visualization."""
        if not self.current_experiment or not MATPLOTLIB_AVAILABLE:
            return

        timestep = self.timestep_combo.currentData()
        if timestep is None:
            return

        # Get data
        cell_types = self.current_experiment.get_cell_types(timestep)
        vegf_field = self.current_experiment.get_vegf_field(timestep)

        if cell_types is None or vegf_field is None:
            return

        # Clear figure
        self.viz_figure.clear()

        show_cells = self.show_cells_check.isChecked()
        show_vegf = self.show_vegf_check.isChecked()
        show_boundaries = self.show_boundaries_check.isChecked()

        # Determine subplot layout
        if show_cells and show_vegf:
            # Side by side
            ax_cells = self.viz_figure.add_subplot(1, 2, 1)
            ax_vegf = self.viz_figure.add_subplot(1, 2, 2)
        elif show_cells:
            ax_cells = self.viz_figure.add_subplot(1, 1, 1)
            ax_vegf = None
        elif show_vegf:
            ax_cells = None
            ax_vegf = self.viz_figure.add_subplot(1, 1, 1)
        else:
            return

        # Plot cells
        if ax_cells is not None:
            # Custom colormap: 0 (Medium) -> white, 1 (EC) -> dark red
            colors = ['white', '#8B0000']
            cmap = ListedColormap(colors)

            # Use 2D slice (z=0)
            cell_slice = cell_types[:, :, 0]
            im_cells = ax_cells.imshow(cell_slice, cmap=cmap, interpolation='nearest')

            # Overlay cell boundaries if requested
            if show_boundaries:
                cell_ids = self.current_experiment.get_cell_ids(timestep)
                if cell_ids is not None:
                    boundaries = detect_cell_boundaries(cell_ids)
                    boundaries_2d = boundaries[:, :, 0] if boundaries.ndim == 3 else boundaries

                    # Use contour lines for sub-pixel thickness
                    # Contour at 0.5 level to draw lines between 0 and 1 values
                    ax_cells.contour(boundaries_2d, levels=[0.5], colors='black',
                                    linewidths=0.1, linestyles='solid')

            ax_cells.set_title(f'Cell Field - Step {timestep}')
            ax_cells.set_xlabel('X')
            ax_cells.set_ylabel('Y')
            ax_cells.axis('tight')

        # Plot VEGF
        if ax_vegf is not None:
            vegf_slice = vegf_field[:, :, 0]
            # Use locked colorbar range across entire simulation
            im_vegf = ax_vegf.imshow(vegf_slice, cmap='viridis', interpolation='bilinear',
                                     vmin=self.vegf_vmin, vmax=self.vegf_vmax)
            ax_vegf.set_title(f'VEGF Field - Step {timestep}')
            ax_vegf.set_xlabel('X')
            ax_vegf.set_ylabel('Y')
            ax_vegf.axis('tight')

            # Add colorbar with locked range
            self.viz_figure.colorbar(im_vegf, ax=ax_vegf, label='VEGF Concentration')

        self.viz_figure.tight_layout()
        self.viz_canvas.draw()

    def toggle_animation(self):
        """Toggle animation playback."""
        if not self.current_experiment:
            return

        if self.animation_playing:
            # Stop animation
            self.animation_playing = False
            self.play_btn.setText("▶ Play")
            if self.animation_timer:
                self.killTimer(self.animation_timer)
                self.animation_timer = None
        else:
            # Start animation
            self.animation_playing = True
            self.play_btn.setText("⏸ Pause")
            self.animation_timer = self.startTimer(500)  # 500ms between frames

    def timerEvent(self, event):
        """Handle animation timer event."""
        if self.animation_playing:
            # Move to next timestep
            current_index = self.timestep_combo.currentIndex()
            next_index = (current_index + 1) % self.timestep_combo.count()
            self.timestep_combo.setCurrentIndex(next_index)

    # =========================================================================
    # EXPORT TAB
    # =========================================================================

    def export_frame_png(self):
        """Export current visualization frame as PNG."""
        if not self.current_experiment or not MATPLOTLIB_AVAILABLE:
            QMessageBox.warning(self, "No Data", "Please load an experiment and view visualization first.")
            return

        timestep = self.timestep_combo.currentData()
        if timestep is None:
            return

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Frame as PNG",
            f"{self.current_experiment.exp_name}_step{timestep}.png",
            "PNG Files (*.png)"
        )

        if filename:
            try:
                self.viz_figure.savefig(filename, dpi=300, bbox_inches='tight')
                QMessageBox.information(self, "Success", f"Frame exported to:\n{filename}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export frame:\n{str(e)}")

    def export_plots_png(self):
        """Export metric plots as PNG."""
        if not self.current_experiment or not MATPLOTLIB_AVAILABLE:
            QMessageBox.warning(self, "No Data", "Please load an experiment first.")
            return

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Plots as PNG",
            f"{self.current_experiment.exp_name}_metrics.png",
            "PNG Files (*.png)"
        )

        if filename:
            try:
                self.metrics_figure.savefig(filename, dpi=300, bbox_inches='tight')
                QMessageBox.information(self, "Success", f"Plots exported to:\n{filename}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export plots:\n{str(e)}")

    def export_animation_mp4(self):
        """Export animation as MP4 video."""
        if not self.current_experiment or not MATPLOTLIB_AVAILABLE:
            QMessageBox.warning(self, "No Data", "Please load an experiment first.")
            return

        # Get save filename
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Animation as MP4",
            f"{self.current_experiment.exp_name}_animation.mp4",
            "MP4 Files (*.mp4)"
        )

        if not filename:
            return

        try:
            # Get export options
            fps = self.fps_spinbox.value()
            show_cells = self.anim_show_cells.isChecked()
            show_vegf = self.anim_show_vegf.isChecked()
            show_boundaries = self.anim_show_boundaries.isChecked()

            if not show_cells and not show_vegf:
                QMessageBox.warning(self, "Invalid Options", "Please select at least one layer to show.")
                return

            # Show progress dialog
            from PyQt5.QtWidgets import QProgressDialog
            progress = QProgressDialog("Generating animation frames...", "Cancel", 0, 100, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)

            # Create frames
            self.statusBar().showMessage("Creating animation frames...")
            frames = create_animation_frames(
                self.current_experiment,
                show_cells=show_cells,
                show_vegf=show_vegf,
                show_boundaries=show_boundaries,
                vegf_vmin=self.vegf_vmin,
                vegf_vmax=self.vegf_vmax
            )

            progress.setValue(50)

            if progress.wasCanceled():
                return

            # Export to MP4
            self.statusBar().showMessage("Encoding MP4 video...")
            progress.setLabelText("Encoding MP4 video...")
            export_animation_mp4(frames, Path(filename), fps=fps)

            progress.setValue(100)
            progress.close()

            self.statusBar().showMessage(f"Animation exported to {filename}")
            QMessageBox.information(self, "Success", f"Animation exported to:\n{filename}")

        except ImportError as e:
            QMessageBox.critical(
                self,
                "Missing Dependency",
                f"MP4 export requires imageio with ffmpeg plugin.\n\n"
                f"Install with:\n"
                f"  pip install imageio imageio-ffmpeg\n\n"
                f"Error: {str(e)}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export animation:\n{str(e)}")

    def export_animation_gif(self):
        """Export animation as GIF."""
        if not self.current_experiment or not MATPLOTLIB_AVAILABLE:
            QMessageBox.warning(self, "No Data", "Please load an experiment first.")
            return

        # Get save filename
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Animation as GIF",
            f"{self.current_experiment.exp_name}_animation.gif",
            "GIF Files (*.gif)"
        )

        if not filename:
            return

        try:
            # Get export options
            fps = self.fps_spinbox.value()
            show_cells = self.anim_show_cells.isChecked()
            show_vegf = self.anim_show_vegf.isChecked()
            show_boundaries = self.anim_show_boundaries.isChecked()

            if not show_cells and not show_vegf:
                QMessageBox.warning(self, "Invalid Options", "Please select at least one layer to show.")
                return

            # Show progress dialog
            from PyQt5.QtWidgets import QProgressDialog
            progress = QProgressDialog("Generating animation frames...", "Cancel", 0, 100, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)

            # Create frames
            self.statusBar().showMessage("Creating animation frames...")
            frames = create_animation_frames(
                self.current_experiment,
                show_cells=show_cells,
                show_vegf=show_vegf,
                show_boundaries=show_boundaries,
                vegf_vmin=self.vegf_vmin,
                vegf_vmax=self.vegf_vmax
            )

            progress.setValue(50)

            if progress.wasCanceled():
                return

            # Export to GIF
            self.statusBar().showMessage("Encoding GIF animation...")
            progress.setLabelText("Encoding GIF animation...")
            export_animation_gif(frames, Path(filename), fps=fps)

            progress.setValue(100)
            progress.close()

            self.statusBar().showMessage(f"Animation exported to {filename}")
            QMessageBox.information(self, "Success", f"Animation exported to:\n{filename}")

        except ImportError as e:
            QMessageBox.critical(
                self,
                "Missing Dependency",
                f"GIF export requires imageio.\n\n"
                f"Install with:\n"
                f"  pip install imageio\n\n"
                f"Error: {str(e)}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export animation:\n{str(e)}")

    # =========================================================================
    # STATISTICS TAB
    # =========================================================================

    def create_statistics_tab(self):
        """Create tab for statistical analysis of replicates and parameter sweeps."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Replicate Analysis Section
        replicate_group = QGroupBox("Replicate Analysis")
        replicate_layout = QVBoxLayout()

        # Instructions
        info_label = QLabel(
            "Compare statistics across multiple replicates of the same experiment. "
            "Add replicate experiments below and select a metric to analyze."
        )
        info_label.setWordWrap(True)
        replicate_layout.addWidget(info_label)

        # Experiment selection
        exp_select_layout = QHBoxLayout()
        add_replicate_btn = QPushButton("Add Replicate")
        add_replicate_btn.clicked.connect(self.add_replicate_experiment)
        exp_select_layout.addWidget(add_replicate_btn)

        clear_replicates_btn = QPushButton("Clear All")
        clear_replicates_btn.clicked.connect(self.clear_replicate_experiments)
        exp_select_layout.addWidget(clear_replicates_btn)
        exp_select_layout.addStretch()
        replicate_layout.addLayout(exp_select_layout)

        # Replicate list display
        self.replicate_list = QTextEdit()
        self.replicate_list.setReadOnly(True)
        self.replicate_list.setMaximumHeight(80)
        self.replicate_list.setPlainText("No replicates selected.")
        replicate_layout.addWidget(self.replicate_list)

        # Metric selection for replicates
        metric_layout = QHBoxLayout()
        metric_layout.addWidget(QLabel("Metric to analyze:"))
        self.replicate_metric_combo = QComboBox()
        self.replicate_metric_combo.addItems([
            "cell_density", "num_clusters", "fragmentation_index",
            "connectivity_index", "compactness", "num_cells",
            "mean_cell_size", "vegf_mean", "vegf_max"
        ])
        metric_layout.addWidget(self.replicate_metric_combo, 1)

        analyze_replicates_btn = QPushButton("Analyze Replicates")
        analyze_replicates_btn.clicked.connect(self.analyze_replicates)
        metric_layout.addWidget(analyze_replicates_btn)
        replicate_layout.addLayout(metric_layout)

        # Statistics results table
        self.replicate_stats_table = QTableWidget()
        self.replicate_stats_table.setColumnCount(8)
        self.replicate_stats_table.setHorizontalHeaderLabels([
            "Statistic", "n", "Mean", "Std Dev", "SEM", "95% CI Lower", "95% CI Upper", "Median"
        ])
        self.replicate_stats_table.horizontalHeader().setStretchLastSection(True)
        self.replicate_stats_table.setMaximumHeight(100)
        replicate_layout.addWidget(self.replicate_stats_table)

        replicate_group.setLayout(replicate_layout)
        layout.addWidget(replicate_group)

        # Parameter Sweep Analysis Section
        sweep_group = QGroupBox("Parameter Sweep Analysis (ANOVA)")
        sweep_layout = QVBoxLayout()

        sweep_info = QLabel(
            "Compare a metric across different parameter values with replicates. "
            "Group experiments by parameter value and perform one-way ANOVA."
        )
        sweep_info.setWordWrap(True)
        sweep_layout.addWidget(sweep_info)

        # This is a simplified interface - in practice, you'd group experiments by parameter
        sweep_note = QLabel(
            "Note: Automatic parameter grouping not yet implemented. "
            "Use Comparison tab for multi-experiment visualization."
        )
        sweep_note.setWordWrap(True)
        sweep_note.setStyleSheet("color: #666; font-style: italic;")
        sweep_layout.addWidget(sweep_note)

        sweep_group.setLayout(sweep_layout)
        layout.addWidget(sweep_group)

        # Statistical Plots
        if MATPLOTLIB_AVAILABLE:
            plot_group = QGroupBox("Statistical Visualization")
            plot_layout = QVBoxLayout()

            self.stats_figure = Figure(figsize=(10, 6))
            self.stats_canvas = FigureCanvas(self.stats_figure)
            self.stats_toolbar = NavigationToolbar(self.stats_canvas, self)

            plot_layout.addWidget(self.stats_toolbar)
            plot_layout.addWidget(self.stats_canvas)

            plot_group.setLayout(plot_layout)
            layout.addWidget(plot_group, stretch=1)

        layout.addStretch()
        self.tabs.addTab(tab, "📊 Statistics")

        # Initialize replicate experiments list
        self.replicate_experiments = []

    def add_replicate_experiment(self):
        """Add experiment(s) to replicate analysis list - supports multi-selection."""
        # Use custom file dialog to allow multi-directory selection
        dialog = QFileDialog(self)
        dialog.setWindowTitle("Select Replicate Experiment Directory(ies)")
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)

        # Enable multi-selection
        file_view = dialog.findChild(QWidget, "listView")
        if file_view:
            file_view.setSelectionMode(3)  # MultiSelection
        tree_view = dialog.findChild(QWidget, "treeView")
        if tree_view:
            tree_view.setSelectionMode(3)  # MultiSelection

        if self.output_dir:
            dialog.setDirectory(str(self.output_dir))

        if dialog.exec_() == QFileDialog.Accepted:
            directories = dialog.selectedFiles()
            added_count = 0
            invalid_dirs = []

            for directory in directories:
                directory = Path(directory)
                if (directory / 'data.zarr').exists():
                    if directory not in self.replicate_experiments:
                        self.replicate_experiments.append(directory)
                        added_count += 1
                else:
                    invalid_dirs.append(directory.name)

            if added_count > 0:
                self.update_replicate_list()
                self.statusBar().showMessage(f"Added {added_count} replicate(s)")

            if invalid_dirs:
                QMessageBox.warning(
                    self,
                    "Invalid Experiments",
                    f"The following directories do not contain data.zarr:\n" +
                    "\n".join(invalid_dirs[:5]) +
                    (f"\n... and {len(invalid_dirs)-5} more" if len(invalid_dirs) > 5 else "")
                )

    def clear_replicate_experiments(self):
        """Clear all replicate experiments."""
        self.replicate_experiments = []
        self.update_replicate_list()
        if MATPLOTLIB_AVAILABLE:
            self.stats_figure.clear()
            self.stats_canvas.draw()

    def update_replicate_list(self):
        """Update replicate experiments list display."""
        if not self.replicate_experiments:
            self.replicate_list.setPlainText("No replicates selected.")
        else:
            text = ""
            for i, exp_path in enumerate(self.replicate_experiments, 1):
                text += f"{i}. {exp_path.name}\n"
            self.replicate_list.setPlainText(text)

    def analyze_replicates(self):
        """Perform statistical analysis on replicates."""
        if len(self.replicate_experiments) < 2:
            QMessageBox.warning(
                self,
                "Insufficient Data",
                "Please add at least 2 replicate experiments for statistical analysis."
            )
            return

        try:
            from analysis_utils import compare_replicates_statistics

            # Load all replicate experiments
            exp_data_list = [ExperimentData(exp_path) for exp_path in self.replicate_experiments]

            # Get selected metric
            metric_name = self.replicate_metric_combo.currentText()

            # Analyze time series for all experiments
            time_series_list = [analyze_time_series(exp_data) for exp_data in exp_data_list]

            # Extract final values for the metric
            metric_values = []
            for ts in time_series_list:
                if metric_name.startswith('vegf_'):
                    # VEGF metric
                    vegf_key = metric_name.replace('vegf_', '')
                    if ts['vegf_stats']:
                        metric_values.append(ts['vegf_stats'][-1][vegf_key])
                else:
                    # Network metric
                    if ts['network_metrics']:
                        value = ts['network_metrics'][-1].get(metric_name)
                        if value is not None:
                            metric_values.append(value)

            if not metric_values or len(metric_values) < 2:
                QMessageBox.warning(
                    self,
                    "No Data",
                    f"Could not extract metric '{metric_name}' from experiments."
                )
                return

            # Compute statistics
            n = len(metric_values)
            mean = np.mean(metric_values)
            std = np.std(metric_values, ddof=1)
            sem = std / np.sqrt(n)
            median = np.median(metric_values)

            # Compute 95% confidence interval
            if SCIPY_AVAILABLE:
                from scipy import stats as scipy_stats
                ci = scipy_stats.t.interval(0.95, n-1, loc=mean, scale=sem)
                ci_lower, ci_upper = ci
            else:
                ci_lower = mean - 1.96 * sem
                ci_upper = mean + 1.96 * sem

            # Update statistics table
            self.replicate_stats_table.setRowCount(1)
            self.replicate_stats_table.setItem(0, 0, QTableWidgetItem(metric_name))
            self.replicate_stats_table.setItem(0, 1, QTableWidgetItem(str(n)))
            self.replicate_stats_table.setItem(0, 2, QTableWidgetItem(f"{mean:.4f}"))
            self.replicate_stats_table.setItem(0, 3, QTableWidgetItem(f"{std:.4f}"))
            self.replicate_stats_table.setItem(0, 4, QTableWidgetItem(f"{sem:.4f}"))
            self.replicate_stats_table.setItem(0, 5, QTableWidgetItem(f"{ci_lower:.4f}"))
            self.replicate_stats_table.setItem(0, 6, QTableWidgetItem(f"{ci_upper:.4f}"))
            self.replicate_stats_table.setItem(0, 7, QTableWidgetItem(f"{median:.4f}"))

            # Create visualization
            if MATPLOTLIB_AVAILABLE:
                self.plot_replicate_statistics(metric_values, metric_name, mean, std, ci_lower, ci_upper)

            self.statusBar().showMessage(
                f"Replicate analysis complete: {metric_name} = {mean:.4f} ± {sem:.4f} (n={n})"
            )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to analyze replicates:\n{str(e)}")
            import traceback
            traceback.print_exc()

    def plot_replicate_statistics(self, metric_values, metric_name, mean, std, ci_lower, ci_upper):
        """Create statistical visualization for replicates."""
        self.stats_figure.clear()

        # Create two subplots: box plot and bar chart with error bars
        gs = self.stats_figure.add_gridspec(1, 2, wspace=0.3)

        # Box plot
        ax1 = self.stats_figure.add_subplot(gs[0, 0])
        box_data = ax1.boxplot([metric_values], labels=[metric_name], patch_artist=True)
        for patch in box_data['boxes']:
            patch.set_facecolor('#3498db')
            patch.set_alpha(0.7)

        # Add individual data points
        x_pos = np.random.normal(1, 0.04, size=len(metric_values))
        ax1.scatter(x_pos, metric_values, alpha=0.6, color='darkblue', s=50)

        ax1.set_ylabel('Value')
        ax1.set_title(f'Box Plot: {metric_name}')
        ax1.grid(True, alpha=0.3, axis='y')

        # Bar chart with error bars
        ax2 = self.stats_figure.add_subplot(gs[0, 1])
        ax2.bar([metric_name], [mean], yerr=[[mean - ci_lower], [ci_upper - mean]],
                capsize=10, color='#2ecc71', alpha=0.7, error_kw={'linewidth': 2})

        ax2.set_ylabel('Value')
        ax2.set_title(f'Mean with 95% CI: {metric_name}')
        ax2.grid(True, alpha=0.3, axis='y')

        # Add text annotation
        ax2.text(0, mean, f'{mean:.4f}\n±{std:.4f}',
                ha='center', va='bottom', fontsize=10, fontweight='bold')

        self.stats_canvas.draw()

    # =========================================================================
    # COMPARISON TAB
    # =========================================================================

    def add_comparison_experiment(self):
        """Add experiment(s) to comparison list - supports multi-selection."""
        # Use custom file dialog to allow multi-directory selection
        dialog = QFileDialog(self)
        dialog.setWindowTitle("Select Experiment Directory(ies)")
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)

        # Enable multi-selection
        file_view = dialog.findChild(QWidget, "listView")
        if file_view:
            file_view.setSelectionMode(3)  # MultiSelection
        tree_view = dialog.findChild(QWidget, "treeView")
        if tree_view:
            tree_view.setSelectionMode(3)  # MultiSelection

        if self.output_dir:
            dialog.setDirectory(str(self.output_dir))

        if dialog.exec_() == QFileDialog.Accepted:
            directories = dialog.selectedFiles()
            added_count = 0
            invalid_dirs = []

            for directory in directories:
                directory = Path(directory)
                if (directory / 'data.zarr').exists():
                    if directory not in self.experiments:
                        self.experiments.append(directory)
                        added_count += 1
                else:
                    invalid_dirs.append(directory.name)

            if added_count > 0:
                self.update_comparison_list()
                self.statusBar().showMessage(f"Added {added_count} experiment(s)")

            if invalid_dirs:
                QMessageBox.warning(
                    self,
                    "Invalid Experiments",
                    f"The following directories do not contain data.zarr:\n" +
                    "\n".join(invalid_dirs[:5]) +
                    (f"\n... and {len(invalid_dirs)-5} more" if len(invalid_dirs) > 5 else "")
                )

    def clear_comparison_experiments(self):
        """Clear all comparison experiments."""
        self.experiments = []
        self.update_comparison_list()
        if MATPLOTLIB_AVAILABLE:
            self.comparison_figure.clear()
            self.comparison_canvas.draw()

    def update_comparison_list(self):
        """Update comparison experiments list display."""
        text = ""
        for i, exp_path in enumerate(self.experiments, 1):
            text += f"{i}. {exp_path.name}\n"

        if not text:
            text = "No experiments selected for comparison."

        self.comparison_list.setPlainText(text)

    def generate_comparison(self):
        """Generate comparison plots."""
        if len(self.experiments) < 2:
            QMessageBox.warning(
                self,
                "Insufficient Data",
                "Please add at least 2 experiments to compare."
            )
            return

        if not MATPLOTLIB_AVAILABLE:
            return

        try:
            self.comparison_figure.clear()

            # Load all experiments
            exp_data_list = [ExperimentData(exp_path) for exp_path in self.experiments]

            # Analyze all
            time_series_list = [analyze_time_series(exp_data) for exp_data in exp_data_list]

            # Create comparison plots
            gs = self.comparison_figure.add_gridspec(2, 2, hspace=0.3, wspace=0.3)

            # Plot 1: Cell density comparison
            ax1 = self.comparison_figure.add_subplot(gs[0, 0])
            for i, (exp_data, ts) in enumerate(zip(exp_data_list, time_series_list)):
                if ts['network_metrics']:
                    densities = [m['cell_density'] for m in ts['network_metrics']]
                    ax1.plot(ts['timesteps'], densities, '-o', label=exp_data.exp_name, linewidth=2)
            ax1.set_xlabel('Timestep (MCS)')
            ax1.set_ylabel('Cell Density')
            ax1.set_title('Cell Density Comparison')
            ax1.legend()
            ax1.grid(True, alpha=0.3)

            # Plot 2: Cluster count comparison
            ax2 = self.comparison_figure.add_subplot(gs[0, 1])
            if SCIPY_AVAILABLE:
                for i, (exp_data, ts) in enumerate(zip(exp_data_list, time_series_list)):
                    if ts['network_metrics']:
                        clusters = [m.get('num_clusters', 0) for m in ts['network_metrics']]
                        ax2.plot(ts['timesteps'], clusters, '-o', label=exp_data.exp_name, linewidth=2)
                ax2.set_xlabel('Timestep (MCS)')
                ax2.set_ylabel('Number of Clusters')
                ax2.set_title('Network Fragmentation Comparison')
                ax2.legend()
                ax2.grid(True, alpha=0.3)

            # Plot 3: VEGF mean comparison
            ax3 = self.comparison_figure.add_subplot(gs[1, 0])
            for i, (exp_data, ts) in enumerate(zip(exp_data_list, time_series_list)):
                if ts['vegf_stats']:
                    vegf_mean = [v['mean'] for v in ts['vegf_stats']]
                    ax3.plot(ts['timesteps'], vegf_mean, '-o', label=exp_data.exp_name, linewidth=2)
            ax3.set_xlabel('Timestep (MCS)')
            ax3.set_ylabel('Mean VEGF Concentration')
            ax3.set_title('VEGF Evolution Comparison')
            ax3.legend()
            ax3.grid(True, alpha=0.3)

            # Plot 4: Side-by-side final frames
            ax4 = self.comparison_figure.add_subplot(gs[1, 1])
            # For now, show parameter comparison
            param_names = []
            param_values = []
            for exp_data in exp_data_list:
                # Extract a key parameter for comparison
                jem = exp_data.parameters.get('jem', 'N/A')
                param_names.append(exp_data.exp_name)
                param_values.append(jem if isinstance(jem, (int, float)) else 0)

            ax4.bar(range(len(param_names)), param_values)
            ax4.set_xticks(range(len(param_names)))
            ax4.set_xticklabels(param_names, rotation=45, ha='right')
            ax4.set_ylabel('jem Parameter Value')
            ax4.set_title('Parameter Comparison (jem)')
            ax4.grid(True, alpha=0.3, axis='y')

            self.comparison_figure.tight_layout()
            self.comparison_canvas.draw()

            self.statusBar().showMessage(f"Comparison generated for {len(self.experiments)} experiments")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate comparison:\n{str(e)}")