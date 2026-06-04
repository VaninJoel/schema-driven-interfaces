"""
Main Window for Angiogenesis GUI

This is an example/template showing how to connect the enhanced schema
to the GUI interface.

Key Features:
- Schema-driven UI generation
- Parameter validation with visual feedback
- Preset management
- Reference documentation display
- Experiment metadata tracking
- Integration with Vivarium Engine

Author: GUI Implementation
Date: 2025
"""

import sys
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QGroupBox, QPushButton, QLabel, QMessageBox, QComboBox,
    QTextBrowser, QSplitter, QFileDialog, QProgressBar, QDoubleSpinBox,
    QCheckBox, QLineEdit, QSpinBox, QDialog, QDialogButtonBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

# Import angiogenesis process with comprehensive schema
from vivarium_angio.processes.angiogenesis_process import AngiogenesisProcess

# Import simulation worker
from simulation_worker import SimulationWorker

# Import schema utilities
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'utils'))
from schema_utils import (
    get_parameter_structure,
    get_display_name_mapping,
    get_model_defaults,
    get_parameters_by_expertise_level,
    get_full_parameter_info,
    validate_parameter_set,
    validate_parameter_value,  
    get_parameter_presets,
)

# Import custom widgets (these would be adapted from vCornea-GUI)
# from widgets.parameter_item import ParameterItem
# from widgets.collapsible_group import CollapsibleGroup
# from widgets.validation_indicator import ValidationIndicator
# from widgets.reference_display import ReferenceDisplay


class ClickableLabel(QLabel):
    """QLabel that emits a signal when clicked."""
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class ValidationInfoDialog(QDialog):
    """
    Pop-up dialog explaining parameter validation rules.

    Shows:
    - Why parameter is valid/invalid
    - Validation ranges and their meanings
    - How ranges were determined (references)
    """

    def __init__(self, param_name, param_info, current_value, issues, parent=None):
        super().__init__(parent)

        self.setWindowTitle(f"Validation: {param_info.get('_display_name', param_name)}")
        self.setMinimumSize(500, 400)

        layout = QVBoxLayout(self)

        # Create text browser
        text_browser = QTextBrowser()
        text_browser.setOpenExternalLinks(True)

        # Generate HTML
        html = self._generate_html(param_name, param_info, current_value, issues)
        text_browser.setHtml(html)

        layout.addWidget(text_browser)

        # Add OK button
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

    def _generate_html(self, param_name, param_info, current_value, issues):
        """Generate HTML for validation information."""

        html = f"""
        <style>
            body {{ font-family: Arial, sans-serif; margin: 10px; }}
            h2 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 5px; }}
            h3 {{ color: #34495e; margin-top: 15px; }}
            .current-value {{ background-color: #e8f4f8; padding: 10px; border-left: 4px solid #3498db; margin: 10px 0; }}
            .valid {{ background-color: #d4edda; padding: 10px; border-left: 4px solid #28a745; margin: 10px 0; }}
            .warning {{ background-color: #fff3cd; padding: 10px; border-left: 4px solid #ffc107; margin: 10px 0; }}
            .error {{ background-color: #f8d7da; padding: 10px; border-left: 4px solid #dc3545; margin: 10px 0; }}
            .range-item {{ margin: 8px 0; padding: 5px; background-color: #f8f9fa; border-radius: 3px; }}
            .label {{ font-weight: bold; color: #2c3e50; }}
            .sweep-value {{ margin: 5px 0; padding: 5px; background-color: #e8f4f8; border-radius: 3px; }}
        </style>

        <h2>{param_info.get('_display_name', param_name)}</h2>

        <div class="current-value">
            <strong>Current Value:</strong> {current_value} {param_info.get('_unit', '')}
        </div>
        """

        # Validation status
        if not issues:
            html += """
            <div class="valid">
                <strong>✓ Parameter is VALID</strong><br>
                The current value is within all recommended ranges.
            </div>
            """
        else:
            # Show issues
            for issue in issues:
                severity = issue['severity']
                message = issue['message']

                if severity in ['ERROR', 'CRITICAL']:
                    css_class = 'error'
                    icon = '❌'
                else:
                    css_class = 'warning'
                    icon = '⚠️'

                html += f"""
                <div class="{css_class}">
                    <strong>{icon} {severity}:</strong> {message}
                </div>
                """

        # Explain validation ranges
        html += "<h3>Validation Ranges Explained</h3>"

        # Check if we have a sweep (comma-separated values)
        is_sweep = isinstance(current_value, str) and ',' in str(current_value)

        if is_sweep:
            # Parse sweep values
            sweep_values = [v.strip() for v in str(current_value).split(',')]
            expected_type = type(param_info['_default'])

            # Convert each value to proper type for range checking
            numeric_values = []
            for val_str in sweep_values:
                try:
                    if expected_type == int:
                        numeric_values.append(int(val_str))
                    elif expected_type == float:
                        numeric_values.append(float(val_str))
                    else:
                        numeric_values.append(val_str)
                except:
                    numeric_values.append(None)

            # Show ranges with each sweep value checked
            if '_physiological_range' in param_info:
                r = param_info['_physiological_range']
                ref = param_info.get('_reference_paper', {}).get('source', 'Literature')

                html += f"""
                <div class="range-item">
                    <span class="label">Physiological Range:</span> [{r[0]}, {r[1]}] {param_info.get('_unit', '')}<br>
                    <small>Values observed in biological systems (Source: {ref})</small><br>
                    <strong>Your values:</strong>
                """

                for val in numeric_values:
                    if val is not None:
                        in_range = r[0] <= val <= r[1]
                        status = "✓" if in_range else "✗"
                        html += f'<div class="sweep-value">{status} {val}</div>'

                html += "</div>"

            if '_recommended_range' in param_info:
                r = param_info['_recommended_range']

                html += f"""
                <div class="range-item">
                    <span class="label">Recommended Range:</span> [{r[0]}, {r[1]}] {param_info.get('_unit', '')}<br>
                    <small>Suggested values for typical simulations</small><br>
                    <strong>Your values:</strong>
                """

                for val in numeric_values:
                    if val is not None:
                        in_range = r[0] <= val <= r[1]
                        status = "✓" if in_range else "✗"
                        html += f'<div class="sweep-value">{status} {val}</div>'

                html += "</div>"

            if '_mathematical_range' in param_info:
                r = param_info['_mathematical_range']

                html += f"""
                <div class="range-item">
                    <span class="label">Mathematical Range:</span> [{r[0]}, {r[1]}] {param_info.get('_unit', '')}<br>
                    <small>Model stability limits - simulation may crash outside this range</small><br>
                    <strong>Your values:</strong>
                """

                for val in numeric_values:
                    if val is not None:
                        in_range = r[0] <= val <= r[1]
                        status = "✓" if in_range else "✗"
                        html += f'<div class="sweep-value">{status} {val}</div>'

                html += "</div>"

        else:
            # Single value - check if numeric for range comparisons
            is_numeric = isinstance(current_value, (int, float))

            if '_physiological_range' in param_info and is_numeric:
                r = param_info['_physiological_range']
                ref = param_info.get('_reference_paper', {}).get('source', 'Literature')
                in_range = r[0] <= current_value <= r[1]
                status = "✓" if in_range else "✗"

                html += f"""
                <div class="range-item">
                    <span class="label">{status} Physiological Range:</span> [{r[0]}, {r[1]}] {param_info.get('_unit', '')}<br>
                    <small>Values observed in biological systems (Source: {ref})</small>
                </div>
                """

            if '_recommended_range' in param_info and is_numeric:
                r = param_info['_recommended_range']
                in_range = r[0] <= current_value <= r[1]
                status = "✓" if in_range else "✗"

                html += f"""
                <div class="range-item">
                    <span class="label">{status} Recommended Range:</span> [{r[0]}, {r[1]}] {param_info.get('_unit', '')}<br>
                    <small>Suggested values for typical simulations</small>
                </div>
                """

            if '_mathematical_range' in param_info and is_numeric:
                r = param_info['_mathematical_range']
                in_range = r[0] <= current_value <= r[1]
                status = "✓" if in_range else "✗"

                html += f"""
                <div class="range-item">
                    <span class="label">{status} Mathematical Range:</span> [{r[0]}, {r[1]}] {param_info.get('_unit', '')}<br>
                    <small>Model stability limits - simulation may crash outside this range</small>
                </div>
                """

        # For categorical parameters, show allowed values
        if '_value_mapping' in param_info and not is_sweep:
            is_numeric = isinstance(current_value, (int, float))
            if not is_numeric:
                html += "<h3>Allowed Values</h3>"
                value_mapping = param_info['_value_mapping']
                current_is_custom = str(current_value) not in value_mapping.values()

                html += "<ul>"
                for val, label in value_mapping.items():
                    is_current = str(current_value) == str(label)
                    marker = "✓" if is_current else "○"
                    html += f"<li>{marker} <strong>{label}</strong> → {val}</li>"

                if current_is_custom:
                    html += f"<li>✓ <strong>Custom value:</strong> {current_value}</li>"

                html += "</ul>"
                html += "<p><small>In Advanced mode, you can enter custom numerical values.</small></p>"

        # Add reference information
        if '_reference_paper' in param_info:
            ref = param_info['_reference_paper']
            html += "<h3>Parameter Source</h3>"
            html += f"<p><strong>{ref.get('source', 'N/A')}</strong></p>"
            if ref.get('title'):
                html += f"<p><i>{ref['title']}</i></p>"
            if ref.get('value') is not None:
                html += f"<p>Reference value: {ref['value']}</p>"

        # Warning about consequences
        if issues and any(i['severity'] in ['ERROR', 'CRITICAL'] for i in issues):
            html += """
            <h3>⚠️ Important</h3>
            <p style="color: #dc3545;">
            Values outside the mathematical range may cause the simulation to crash or produce
            nonsensical results. It is strongly recommended to use values within the physiological
            or recommended ranges for scientifically valid results.
            </p>
            """

        return html


class ParameterInfoDialog(QDialog):
    """
    Pop-up dialog showing detailed parameter information.

    Displays:
    - Full description with biological context
    - Reference papers with clickable DOI links
    - Validation ranges
    - Related parameters
    - Model equations
    """

    def __init__(self, param_name, param_info, display_names, parent=None):
        super().__init__(parent)

        self.setWindowTitle(f"Parameter Information: {param_info.get('_display_name', param_name)}")
        self.setMinimumSize(600, 500)

        layout = QVBoxLayout(self)

        # Create text browser for HTML content
        text_browser = QTextBrowser()
        text_browser.setOpenExternalLinks(True)

        # Generate HTML content
        html = self._generate_html(param_name, param_info, display_names)
        text_browser.setHtml(html)

        layout.addWidget(text_browser)

        # Add OK button
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

    def _generate_html(self, param_name, param_info, display_names):
        """Generate HTML content for parameter information."""

        html = f"""
        <style>
            body {{ font-family: Arial, sans-serif; margin: 10px; }}
            h2 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 5px; }}
            h3 {{ color: #34495e; margin-top: 20px; }}
            .description {{ background-color: #ecf0f1; padding: 10px; border-radius: 5px; margin: 10px 0; }}
            .info-item {{ margin: 5px 0; }}
            .label {{ font-weight: bold; color: #2c3e50; }}
            ul {{ margin-left: 20px; }}
            a {{ color: #3498db; }}
        </style>

        <h2>{param_info.get('_display_name', param_name)}</h2>

        <div class="description">
            <p>{param_info.get('_long_description', param_info.get('_description', 'No description available'))}</p>
        </div>
        """

        # Basic details
        html += "<h3>Details</h3><ul>"
        html += f"<li><span class='label'>Parameter Name:</span> <code>{param_name}</code></li>"
        html += f"<li><span class='label'>Category:</span> {param_info.get('_category', 'N/A')}</li>"
        html += f"<li><span class='label'>Subcategory:</span> {param_info.get('_subcategory', 'N/A')}</li>"
        html += f"<li><span class='label'>Unit:</span> {param_info.get('_unit', 'dimensionless')}</li>"
        html += f"<li><span class='label'>Default Value:</span> {param_info.get('_default', 'N/A')}</li>"
        html += f"<li><span class='label'>Expertise Level:</span> {param_info.get('_expert_level', 'N/A').title()}</li>"
        html += "</ul>"

        # Validation ranges
        if '_physiological_range' in param_info or '_recommended_range' in param_info:
            html += "<h3>Valid Ranges</h3><ul>"
            if '_physiological_range' in param_info:
                r = param_info['_physiological_range']
                html += f"<li><span class='label'>Physiological Range:</span> [{r[0]}, {r[1]}]</li>"
            if '_recommended_range' in param_info:
                r = param_info['_recommended_range']
                html += f"<li><span class='label'>Recommended Range:</span> [{r[0]}, {r[1]}]</li>"
            if '_mathematical_range' in param_info:
                r = param_info['_mathematical_range']
                html += f"<li><span class='label'>Mathematical Range:</span> [{r[0]}, {r[1]}] (model stability)</li>"
            html += "</ul>"

        # Reference information
        if '_reference_paper' in param_info:
            ref = param_info['_reference_paper']
            html += "<h3>Reference</h3>"
            html += f"<div class='info-item'><span class='label'>Source:</span> {ref.get('source', 'N/A')}</div>"
            if ref.get('title'):
                html += f"<div class='info-item'><i>{ref['title']}</i></div>"
            if ref.get('doi'):
                html += f"<div class='info-item'><span class='label'>DOI:</span> <a href='https://doi.org/{ref['doi']}'>{ref['doi']}</a></div>"
            if ref.get('journal'):
                html += f"<div class='info-item'><span class='label'>Journal:</span> {ref['journal']}</div>"
            if ref.get('year'):
                html += f"<div class='info-item'><span class='label'>Year:</span> {ref['year']}</div>"
            if ref.get('equation'):
                html += f"<div class='info-item'><span class='label'>Equation:</span> {ref['equation']}</div>"
            if ref.get('page'):
                html += f"<div class='info-item'><span class='label'>Page:</span> {ref['page']}</div>"
            if ref.get('notes'):
                html += f"<div class='info-item'><span class='label'>Notes:</span> {ref['notes']}</div>"

        # Biological meaning
        if '_biological_meaning' in param_info:
            html += "<h3>Biological Meaning</h3>"
            html += f"<div class='description'>{param_info['_biological_meaning']}</div>"

        # Model context
        if '_model_context' in param_info:
            html += "<h3>Model Context</h3>"
            html += f"<div class='description'>{param_info['_model_context']}</div>"

        # Related parameters
        if '_related_parameters' in param_info and param_info['_related_parameters']:
            html += "<h3>Related Parameters</h3><ul>"
            for related in param_info['_related_parameters']:
                display_name = display_names.get(related, related)
                html += f"<li>{display_name} (<code>{related}</code>)</li>"
            html += "</ul>"

        # Dependencies
        if '_dependencies' in param_info and param_info['_dependencies']:
            html += "<h3>Parameter Dependencies</h3><ul>"
            for dep_param, desc in param_info['_dependencies'].items():
                display_name = display_names.get(dep_param, dep_param)
                html += f"<li><span class='label'>{display_name}:</span> {desc}</li>"
            html += "</ul>"

        # Visual effects
        if '_visual_effects' in param_info:
            html += "<h3>Visual Effects</h3><ul>"
            effects = param_info['_visual_effects']
            if 'low_value' in effects:
                html += f"<li><span class='label'>Low values:</span> {effects['low_value']}</li>"
            if 'high_value' in effects:
                html += f"<li><span class='label'>High values:</span> {effects['high_value']}</li>"
            html += "</ul>"

        # Presets
        if '_presets' in param_info:
            html += "<h3>Available Presets</h3><ul>"
            for preset_name, preset_value in param_info['_presets'].items():
                html += f"<li><span class='label'>{preset_name}:</span> {preset_value}</li>"
            html += "</ul>"

        return html


class AngiogenesisMainWindow(QMainWindow):
    """
    Main window for Angiogenesis simulation GUI.

    Schema-driven interface that automatically generates UI from
    the AngiogenesisProcess ports_schema().
    """

    def __init__(self):
        super().__init__()

        # =====================================================================
        # INITIALIZE PROCESS AND SCHEMA
        # =====================================================================

        # Create process instance to get schema
        self.process = AngiogenesisProcess()
        self.schema = self.process.ports_schema()

        # Extract schema information using utilities
        self.parameter_structure = get_parameter_structure(self.schema)
        self.display_names = get_display_name_mapping(self.schema)
        self.model_defaults = get_model_defaults(self.schema)

        # Current parameter values (start with defaults)
        self.current_params = self.model_defaults.copy()

        # Expertise level
        self.expertise_level = 'basic'  # 'basic', 'intermediate', 'advanced'

        # =====================================================================
        # SIMULATION SETUP
        # =====================================================================

        # Initialize simulation worker components
        self.worker = None
        self.worker_thread = None

        # GUI settings file
        self.settings_file = Path(__file__).parent.parent / '.gui_settings.json'

        # Load saved GUI state (output dir, window size, etc.)
        self._load_gui_state()

        # If no saved state, use default output directory
        if not hasattr(self, 'output_dir') or self.output_dir is None:
            self.output_dir = Path(__file__).parent.parent / 'experiments'
            self.output_dir = self.output_dir.resolve()  # Convert to absolute path

        # =====================================================================
        # BATCH EXECUTION STATE
        # =====================================================================

        # For parameter sweeps
        self.sweep_parameters = {}
        self.base_parameters = {}
        self.parameter_combinations = []

        # For batch tracking
        self.simulation_threads = []  # List of (thread, worker) tuples
        self.completed_combinations = 0
        self.total_combinations = 0
        self.batch_output_folder = None
        self.is_cancelled = False

        # =====================================================================
        # UI SETUP
        # =====================================================================

        self.setWindowTitle("Angiogenesis Simulation")
        self.setGeometry(100, 100, 1400, 900)

        self.init_ui()
        self.create_parameter_tabs()
        self.connect_signals()

        # Show initial validation
        self.validate_all_parameters()

        # Apply saved experiment name if available
        if hasattr(self, '_saved_exp_name'):
            self.current_params['exp_name'] = self._saved_exp_name
            # Update the widget if it exists
            if 'exp_name' in self.param_widgets:
                widget = self.param_widgets['exp_name']['input']
                if hasattr(widget, 'setText'):
                    widget.setText(self._saved_exp_name)

    def init_ui(self):
        """Initialize the main UI layout."""

        # Central widget with main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # =====================================================================
        # MAIN PANEL: Parameter Controls
        # =====================================================================

        main_panel = QWidget()
        panel_layout = QVBoxLayout(main_panel)

        # --- TOOLBAR ---
        toolbar = self.create_toolbar()
        panel_layout.addWidget(toolbar)

        # --- PARAMETER TABS ---
        self.tab_widget = QTabWidget()
        panel_layout.addWidget(self.tab_widget)

        # --- RUN CONTROLS ---
        run_controls = self.create_run_controls()
        panel_layout.addWidget(run_controls)

        # Add panel directly to main layout (no splitter needed)
        main_layout.addWidget(main_panel)

    def create_toolbar(self):
        """Create toolbar with preset, expertise, and file controls."""

        toolbar = QGroupBox("Controls")
        layout = QHBoxLayout()

        # --- Expertise Level Selector ---
        level_label = QLabel("Expertise:")
        layout.addWidget(level_label)

        self.expertise_combo = QComboBox()
        self.expertise_combo.addItems(['Basic', 'Intermediate', 'Advanced'])
        self.expertise_combo.currentTextChanged.connect(self.on_expertise_changed)
        layout.addWidget(self.expertise_combo)

        layout.addSpacing(20)

        # --- Preset Selector ---
        preset_label = QLabel("Preset:")
        layout.addWidget(preset_label)

        self.preset_combo = QComboBox()
        preset_names = self.process.get_preset_names()
        self.preset_combo.addItems(['Custom'] + preset_names)
        self.preset_combo.currentTextChanged.connect(self.on_preset_selected)
        layout.addWidget(self.preset_combo)

        layout.addSpacing(20)

        # --- File Operations ---
        load_btn = QPushButton("Load Parameters")
        load_btn.clicked.connect(self.load_parameters_from_file)
        load_btn.setMinimumWidth(120)  # Ensure button is wide enough for text
        layout.addWidget(load_btn)

        save_btn = QPushButton("Save Parameters")
        save_btn.clicked.connect(self.save_parameters_to_file)
        save_btn.setMinimumWidth(120)
        layout.addWidget(save_btn)

        layout.addSpacing(20)

        # --- Reset Button ---
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self.reset_to_defaults)
        reset_btn.setMinimumWidth(130)  # Slightly wider for longer text
        layout.addWidget(reset_btn)

        layout.addStretch()

        # --- About Button ---
        about_btn = QPushButton("ℹ About")
        about_btn.clicked.connect(self.show_about_dialog)
        about_btn.setMinimumWidth(80)
        about_btn.setStyleSheet("font-weight: bold;")
        layout.addWidget(about_btn)

        toolbar.setLayout(layout)
        return toolbar

    def create_parameter_tabs(self):
        """
        Generate parameter tabs dynamically from schema structure.

        This is the core of schema-driven UI generation!
        """

        # Get parameters for current expertise level
        visible_params = get_parameters_by_expertise_level(
            self.schema,
            self.expertise_level
        )

        # Create tabs based on parameter structure
        for tab_name, groups in self.parameter_structure.items():
            tab_widget = QWidget()
            tab_layout = QVBoxLayout()
            tab_layout.setAlignment(Qt.AlignTop)

            # Create collapsible groups for each subcategory
            for group_name, params in groups.items():
                # Filter params by expertise level
                group_params = {
                    p: desc for p, desc in params.items()
                    if p in visible_params
                }

                if not group_params:
                    continue  # Skip empty groups

                # Create collapsible group
                # In real implementation, use CollapsibleGroup widget
                group_box = QGroupBox(group_name)
                group_layout = QVBoxLayout()

                for param_name, description in group_params.items():
                    # Create parameter item
                    # In real implementation, use ParameterItem widget
                    param_widget = self.create_parameter_widget(param_name)
                    group_layout.addWidget(param_widget)

                group_box.setLayout(group_layout)
                tab_layout.addWidget(group_box)

            tab_layout.addStretch()
            tab_widget.setLayout(tab_layout)
            self.tab_widget.addTab(tab_widget, tab_name)

    def create_parameter_widget(self, param_name: str):
        """
        Create a widget for a single parameter.

        Properly handles:
        - int vs float (QSpinBox vs QDoubleSpinBox)
        - Individual parameter ranges from schema
        - Appropriate step sizes
        - Value mappings for categorical params
        """
        param_info = self.schema['inputs'][param_name]

        # Container widget
        container = QWidget()
        layout = QHBoxLayout()

        # Label
        display_name = self.display_names.get(param_name, param_name)
        label = QLabel(display_name)
        label.setMinimumWidth(200)
        label.setToolTip(param_info.get('_description', ''))
        layout.addWidget(label)

        # Input widget based on type and metadata
        default_value = param_info['_default']
        # Use current parameter value if available (important for preset persistence)
        current_value = self.current_params.get(param_name, default_value)
        gui_hints = param_info.get('_gui_hints', {})
        value_mapping = param_info.get('_value_mapping', None)

        # Handle categorical parameters with value mapping
        # But if it's a numeric parameter with a range, prefer spinbox for exploration
        if value_mapping and isinstance(default_value, (int, float)) and '_mathematical_range' in param_info:
            # This is a categorical parameter with numeric exploration capability
            # Show a spinbox with hints about categorical values
            if isinstance(default_value, float):
                widget = QDoubleSpinBox()
                widget.setValue(current_value)

                # Set range
                min_val, max_val = param_info['_mathematical_range']
                widget.setRange(min_val, max_val)

                # Set step based on typical values in mapping
                step = gui_hints.get('slider_step', 0.01)
                widget.setSingleStep(step)

                # Auto-adjust decimal precision
                if step >= 1.0:
                    widget.setDecimals(0)
                elif step >= 0.1:
                    widget.setDecimals(1)
                elif step >= 0.01:
                    widget.setDecimals(2)
                else:
                    widget.setDecimals(4)

                widget.valueChanged.connect(
                    lambda val, pname=param_name: self.on_parameter_changed(pname, val)
                )
            else:  # int
                widget = QSpinBox()
                widget.setValue(current_value)

                min_val, max_val = param_info['_mathematical_range']
                widget.setRange(int(min_val), int(max_val))

                step = gui_hints.get('slider_step', 1)
                widget.setSingleStep(int(step))

                widget.valueChanged.connect(
                    lambda val, pname=param_name: self.on_parameter_changed(pname, val)
                )

            # Add tooltip showing categorical meanings
            categorical_info = ", ".join([f"{v}={k}" for k, v in value_mapping.items()])
            widget.setToolTip(f"{param_info.get('_description', '')}\n\nKey values: {categorical_info}")

        elif value_mapping:
            # Pure categorical parameter (no numeric exploration)
            widget = QComboBox()

            # Make combo box editable for advanced users to input custom values
            if self.expertise_level == 'advanced':
                widget.setEditable(True)
                widget.setToolTip(f"{param_info.get('_description', '')} \n\n(Advanced: You can type custom values)")

            # Add "Custom" option first for advanced users
            if self.expertise_level == 'advanced':
                widget.addItem("Custom...", None)

            # Add predefined items in the order they appear in value_mapping
            for value, label_text in value_mapping.items():
                widget.addItem(label_text, value)  # Store actual value as data

            # Set current value
            index = widget.findData(current_value)
            if index >= 0:
                widget.setCurrentIndex(index)
            elif self.expertise_level == 'advanced':
                # If current value not in mapping, show it in custom option
                widget.setCurrentIndex(0)  # Select "Custom..."
                widget.setEditText(str(current_value))

            # Handle value changes
            if widget.isEditable():
                # For editable combo (advanced), get text from editor
                widget.currentTextChanged.connect(
                    lambda text, pname=param_name: self.on_parameter_changed(pname, float(text) if self._is_number(text) else text)
                )
            else:
                # For non-editable combo (basic/intermediate), use item data
                widget.currentIndexChanged.connect(
                    lambda idx, pname=param_name, w=widget:
                        self.on_parameter_changed(pname, w.itemData(idx))
                )

        # Handle boolean parameters
        elif isinstance(default_value, bool):
            widget = QCheckBox()
            widget.setChecked(current_value)
            widget.stateChanged.connect(
                lambda state, pname=param_name: self.on_parameter_changed(pname, bool(state))
            )

        # Handle integer parameters - Use QLineEdit to support comma-separated sweeps
        elif isinstance(default_value, int):
            widget = QLineEdit()
            widget.setText(str(current_value))
            widget.setPlaceholderText("e.g., 100 or 50,100,150 for sweep")

            # Add tooltip with display name and sweep functionality
            display_name = self.display_names.get(param_name, param_name)
            tooltip = f"<b>{display_name}</b><br/><br/>"
            tooltip += param_info.get('_description', '')
            # tooltip += "<br/><br/>💡 <i>Tip: Enter comma-separated values for parameter sweep (e.g., 2,4,6,8)</i>"
            widget.setToolTip(tooltip)

            widget.textChanged.connect(
                lambda text, pname=param_name: self.on_parameter_changed(pname, text)
            )

        # Handle float parameters - Use QLineEdit to support comma-separated sweeps
        elif isinstance(default_value, float):
            widget = QLineEdit()
            widget.setText(str(current_value))
            widget.setPlaceholderText("e.g., 1.0 or 0.5,1.0,1.5 for sweep")

            # Add tooltip with display name and sweep functionality
            display_name = self.display_names.get(param_name, param_name)
            tooltip = f"<b>{display_name}</b><br/><br/>"
            tooltip += param_info.get('_description', '')
            # tooltip += "<br/><br/>💡 <i>Tip: Enter comma-separated values for parameter sweep (e.g., 0.1,0.2,0.3)</i>"
            widget.setToolTip(tooltip)

            widget.textChanged.connect(
                lambda text, pname=param_name: self.on_parameter_changed(pname, text)
            )

        # Handle string parameters
        elif isinstance(default_value, str):
            widget = QLineEdit()
            widget.setText(current_value)
            widget.textChanged.connect(
                lambda text, pname=param_name: self.on_parameter_changed(pname, text)
            )

        # Fallback for unsupported types
        else:
            widget = QLabel(str(default_value))

        layout.addWidget(widget)

        # Info button (show full parameter info in right panel)
        info_btn = QPushButton("ℹ")
        info_btn.setMaximumWidth(30)
        info_btn.clicked.connect(
            lambda checked, pname=param_name: self.show_parameter_info(pname)
        )
        layout.addWidget(info_btn)

        # Validation indicator (clickable to show validation details)
        validation_label = ClickableLabel("✓")
        validation_label.setMinimumWidth(30)
        validation_label.setStyleSheet("color: green; font-size: 16px;")
        validation_label.setCursor(Qt.PointingHandCursor)  # Set cursor using Qt API
        validation_label.setToolTip("Click for validation details")
        validation_label.clicked.connect(
            lambda pname=param_name: self.show_validation_info(pname)
        )
        layout.addWidget(validation_label)

        # Store references for later updates
        if not hasattr(self, 'param_widgets'):
            self.param_widgets = {}
        self.param_widgets[param_name] = {
            'input': widget,
            'validation': validation_label
        }

        container.setLayout(layout)
        return container

    def create_run_controls(self):
        """Create simulation run controls."""

        controls = QGroupBox("Simulation Control")
        layout = QVBoxLayout()

        # Storage location selector
        storage_layout = QHBoxLayout()
        storage_layout.addWidget(QLabel("Output Directory:"))

        self.storage_path_display = QLineEdit()
        self.storage_path_display.setText(str(self.output_dir))
        self.storage_path_display.setReadOnly(True)
        self.storage_path_display.setPlaceholderText("Select output directory...")
        storage_layout.addWidget(self.storage_path_display)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_output_directory)
        browse_btn.setMaximumWidth(100)
        storage_layout.addWidget(browse_btn)

        layout.addLayout(storage_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        # Batch execution controls
        batch_group = QGroupBox("Batch Execution (Parameter Sweep)")
        batch_layout = QVBoxLayout()

        # Info label
        info_label = QLabel("💡 <i>Tip: Use comma-separated values for parameter sweeps (e.g., <b>EC-EC Adhesion Energy:</b> 2,4,6,8)</i>")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #7f8c8d; padding: 5px;")
        batch_layout.addWidget(info_label)

        # Replicate control
        replicate_layout = QHBoxLayout()
        replicate_label = QLabel("Number of Replicates per Combination:")
        replicate_label.setToolTip("Run N identical simulations for each parameter combination (for statistical analysis)")
        self.replicate_spinbox = QSpinBox()
        self.replicate_spinbox.setRange(1, 100)
        self.replicate_spinbox.setValue(1)
        self.replicate_spinbox.setToolTip("Number of times to repeat each parameter combination")
        replicate_layout.addWidget(replicate_label)
        replicate_layout.addWidget(self.replicate_spinbox)
        replicate_layout.addStretch()
        batch_layout.addLayout(replicate_layout)

        batch_group.setLayout(batch_layout)
        layout.addWidget(batch_group)

        # Run button
        self.run_button = QPushButton("Run Simulation")
        self.run_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.run_button.clicked.connect(self.run_simulation)
        layout.addWidget(self.run_button)

        # Cancel button (initially hidden)
        self.cancel_button = QPushButton("Cancel Batch")
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                padding: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
        """)
        self.cancel_button.clicked.connect(self.cancel_batch)
        self.cancel_button.setVisible(False)
        layout.addWidget(self.cancel_button)

        # Analyze Results button
        self.analyze_button = QPushButton("📊 Analyze Results")
        self.analyze_button.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                font-weight: bold;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        self.analyze_button.setToolTip("Open analysis window to visualize and analyze simulation results")
        self.analyze_button.clicked.connect(self.open_analysis_window)
        layout.addWidget(self.analyze_button)

        controls.setLayout(layout)
        return controls

    # =========================================================================
    # EVENT HANDLERS
    # =========================================================================

    def on_parameter_changed(self, param_name: str, value):
        """Handle parameter value change."""
        # Convert value to appropriate type based on schema
        converted_value = self._convert_parameter_value(param_name, value)
        self.current_params[param_name] = converted_value

        # Mark as custom preset (unless we're loading a preset)
        if not getattr(self, '_loading_preset', False):
            self.preset_combo.setCurrentText('Custom')

        # Validate this parameter
        self.validate_parameter(param_name)

        # Update dependent parameter visibility if needed
        self.update_parameter_visibility()

    def _convert_parameter_value(self, param_name: str, value):
        """
        Convert parameter value to the appropriate type based on schema.
        Handles both single values and comma-separated sweep values.

        Args:
            param_name: Name of the parameter
            value: Value to convert (can be string with commas for sweeps)

        Returns:
            Converted value (single value or string with comma-separated values for sweeps)
        """
        if param_name not in self.schema['inputs']:
            return value

        param_info = self.schema['inputs'][param_name]
        expected_type = type(param_info['_default'])

        # If value is already the correct type, return as-is
        if isinstance(value, expected_type):
            return value

        # Convert string values
        if isinstance(value, str):
            value_str = value.strip()

            # Check for comma-separated values (sweep)
            if ',' in value_str:
                # For sweeps, keep as string but validate each value
                # The detect_sweep_parameters method will parse these later
                return value_str

            # Single value - convert to appropriate type
            try:
                if expected_type == int:
                    return int(value_str)
                elif expected_type == float:
                    return float(value_str)
                elif expected_type == bool:
                    return value_str.lower() in ('true', '1', 'yes')
                elif expected_type == str:
                    return value_str
            except ValueError:
                # If conversion fails, return original value
                # Validation will catch the error
                return value

        return value

    def on_expertise_changed(self, level_text: str):
        """Handle expertise level change."""
        self.expertise_level = level_text.lower()

        # Rebuild parameter tabs with new level
        self.rebuild_tabs()

    def on_preset_selected(self, preset_name: str):
        """Handle preset selection."""
        if preset_name == 'Custom':
            return

        try:
            # Set flag to prevent preset combo from resetting to 'Custom'
            self._loading_preset = True

            # Get preset from process
            preset = self.process.get_preset(preset_name)
            preset_params = preset['parameters']

            # Update parameter values
            self.current_params.update(preset_params)

            # Update UI widgets
            self.update_parameter_widgets(preset_params)

            # Validate all
            self.validate_all_parameters()

            # Clear flag
            self._loading_preset = False

            # Show preset info in message box
            QMessageBox.information(
                self,
                "Preset Loaded",
                f"Loaded preset: {preset['name']}\n\n{preset['description']}"
            )

        except Exception as e:
            self._loading_preset = False  # Clear flag on error
            QMessageBox.critical(self, "Error", f"Failed to load preset: {str(e)}")

    def show_parameter_info(self, param_name: str):
        """Display detailed parameter information in a pop-up dialog."""
        param_info = get_full_parameter_info(self.schema, param_name)

        # Create and show the dialog
        dialog = ParameterInfoDialog(param_name, param_info, self.display_names, self)
        dialog.exec_()

    def show_validation_info(self, param_name: str):
        """Display validation details for a parameter in a pop-up dialog."""
        param_info = self.schema['inputs'][param_name]
        current_value = self.current_params.get(param_name)

        # Get validation issues - handle sweep parameters
        if isinstance(current_value, str) and ',' in current_value:
            issues = self._validate_sweep_parameter(param_name, current_value)
        else:
            issues = validate_parameter_value(self.schema, param_name, current_value)

        # Create and show the dialog
        dialog = ValidationInfoDialog(param_name, param_info, current_value, issues, self)
        dialog.exec_()

    def show_about_dialog(self):
        """Display comprehensive About dialog with model and GUI information."""
        about_dialog = QDialog(self)
        about_dialog.setWindowTitle("About Angiogenesis Simulation")
        about_dialog.setMinimumSize(700, 600)

        layout = QVBoxLayout(about_dialog)

        # Create text browser
        text_browser = QTextBrowser()
        text_browser.setOpenExternalLinks(True)

        # Generate HTML content
        html = """
        <style>
            body { font-family: Arial, sans-serif; margin: 15px; }
            h1 { color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }
            h2 { color: #34495e; margin-top: 20px; }
            h3 { color: #7f8c8d; margin-top: 15px; }
            .section { background-color: #ecf0f1; padding: 15px; border-radius: 5px; margin: 10px 0; }
            ul { margin-left: 20px; }
            .feature { padding: 8px; background-color: #e8f4f8; margin: 5px 0; border-left: 4px solid #3498db; }
            a { color: #3498db; }
            .check { color: #2ecc71; font-size: 16px; font-weight: bold; } /* Green check mark */
            .warning { color: #f1c40f; font-size: 16px; font-weight: bold; } /* Yellow warning sign */
            .error { color: #e74c3c; font-size: 16px; font-weight: bold; } /* Red X mark */
        </style>

        <h1>Angiogenesis Simulation Model</h1>

        <div class="section">
            <h2>Model Overview</h2>
            <p>This application simulates endothelial cell migration and VEGF-driven angiogenesis
            using the <strong>Cellular Potts Model</strong> (CPM) framework implemented in CompuCell3D.</p>

            <h3>Key Components:</h3>
            <ul>
                <li><strong>Endothelial Cells (EC):</strong> Mobile cells that form blood vessel networks</li>
                <li><strong>Cell-Cell Adhesion:</strong> Controls how strongly cells stick together (JEE)</li>
                <li><strong>Cell-Medium Adhesion:</strong> Controls aggregation vs spreading (JEM)</li>
                <li><strong>VEGF Field:</strong> Diffusible growth factor guiding cell migration</li>
                <li><strong>Chemotaxis:</strong> Directed cell movement up VEGF gradients</li>
            </ul>
        </div>

        <div class="section">
            <h2>Quick Start Guide</h2>
            <ol>
                <li><strong>Select Expertise Level:</strong> Basic (7 params), Intermediate (9 params), or Advanced (all params)</li>
                <li><strong>Choose a Preset:</strong> Start with literature-tested parameter combinations</li>
                <li><strong>Explore Parameters:</strong>
                    <ul>
                        <li>Click <strong>ℹ</strong> next to any parameter for detailed information</li>
                        <li>Click validation icons (<span class="check">✓</span> <span class="warning">⚠️</span> <span class="error">❌</span>) to understand parameter ranges</li>
                        <li>Hover over parameters for quick tooltips</li>
                    </ul>
                </li>
                <li><strong>Adjust Values:</strong> Modify parameters within recommended ranges</li>
                <li><strong>Run Simulation:</strong> Enter experiment name and click "Run Simulation"</li>
            </ol>
        </div>

        <div class="section">
            <h2>GUI Features</h2>
            <div class="feature"><strong>Schema-Driven Interface:</strong> All parameter info comes from scientific metadata</div>
            <div class="feature"><strong>Three Expertise Levels:</strong> Progressive disclosure hides complexity for beginners</div>
            <div class="feature"><strong>Literature Integration:</strong> Direct links to source papers via DOI</div>
            <div class="feature"><strong>Smart Validation:</strong> Real-time checking against physiological ranges</div>
            <div class="feature"><strong>Preset Library:</strong> Pre-configured parameter sets from publications</div>
            <div class="feature"><strong>Parameter History:</strong> Load/save parameter configurations</div>
            <div class="feature"><strong>Reproducibility:</strong> Complete metadata saved with every run</div>
            <div class="feature"><strong>Parameter Sweeps:</strong> Comma-separated values for automatic batch execution</div>
            <div class="feature"><strong>Statistical Replicates:</strong> Run N identical simulations for each combination</div>
            <div class="feature"><strong>Configurable Save Frequency:</strong> Control how often data is written (MCS intervals)</div>
            <div class="feature"><strong>Batch Progress Tracking:</strong> Real-time monitoring of multiple simultaneous runs</div>
        </div>

        <div class="section">
            <h2>Batch Execution & Parameter Sweeps</h2>
            <h3>Running Parameter Sweeps:</h3>
            <p>Automatically explore parameter space by specifying comma-separated values:</p>
            <ol>
                <li>Enter comma-separated values in any parameter field<br>
                    <i>Example: <code>EC-EC Adhesion Energy: 2,4,6,8</code> creates 4 variations</i></li>
                <li>Combine multiple parameters for full factorial sweep<br>
                    <i>Example: <code>EC-EC Adhesion Energy: 2,4</code> + <code>EC-Medium Adhesion Energy: 2,4</code> = 4 combinations</i></li>
                <li>Set number of replicates (1-100) for statistical analysis</li>
                <li>Click "Run Simulation" - all combinations launch automatically</li>
            </ol>

            <h3>Output Organization:</h3>
            <p>Batch runs create organized output folders:</p>
            <pre style='background-color: #2c3e50; color: #ecf0f1; padding: 10px; border-radius: 5px; font-size: 10px;'>
batch_sweep_20251106_143052/
├── baseline_combo001_rep01/
│   ├── data.zarr/
│   ├── logs/
│   └── run_metadata.json
├── baseline_combo001_rep02/
├── baseline_combo002_rep01/
└── ...</pre>

            <h3>Naming Convention:</h3>
            <ul>
                <li><strong>Single run:</strong> <code>experiment_name/</code></li>
                <li><strong>Multiple replicates:</strong> <code>experiment_name_rep01/</code>, <code>experiment_name_rep02/</code>, ...</li>
                <li><strong>Parameter sweep:</strong> <code>experiment_name_combo001/</code>, <code>experiment_name_combo002/</code>, ...</li>
                <li><strong>Sweep + Replicates:</strong> <code>experiment_name_combo001_rep01/</code>, etc.</li>
            </ul>

            <h3>Data Save Options:</h3>
            <ul>
                <li><strong>Write Frequency:</strong> Control how often simulation data is saved to Zarr
                    <ul>
                        <li><i>Default: Every 10 MCS (high resolution)</i></li>
                        <li><i>Performance: Every 20-50 MCS (faster, smaller files)</i></li>
                        <li><i>Minimal: Set to sim_time for final state only</i></li>
                    </ul>
                </li>
                <li><strong>Output Directory:</strong> Choose where experiments are saved (local or network drives)</li>
                <li><strong>Zarr Format:</strong> Efficient hierarchical storage with incremental writes</li>
            </ul>
        </div>

        <div class="section">
            <h2>Scientific Validation</h2>
            <p>Parameter ranges are based on:</p>
            <ul>
                <li><strong>Merks et al., 2006:</strong> Cell elongation in vasculogenesis
                    <br><a href="https://doi.org/10.1016/j.ydbio.2005.10.003">DOI: 10.1016/j.ydbio.2005.10.003</a>
                </li>
                <li><strong>Merks & Glazier, 2008:</strong> Cell-centered developmental biology
                    <br><a href="https://doi.org/10.1016/j.physa.2007.11.053">DOI: 10.1016/j.physa.2007.11.053</a>
                </li>
            </ul>
        </div>

        <div class="section">
            <h2>Understanding Parameters</h2>
            <h3>Adhesion Parameters (J values):</h3>
            <ul>
                <li><strong>Lower J:</strong> Stronger adhesion (cells stick together)</li>
                <li><strong>Higher J:</strong> Weaker adhesion (cells separate)</li>
                <li><strong>JEE &lt; JEM:</strong> Cells form connected networks</li>
                <li><strong>JEM &gt; JEE:</strong> Cells aggregate into clusters</li>
            </ul>

            <h3>Chemotaxis (λ_chem):</h3>
            <ul>
                <li><strong>0:</strong> Random migration</li>
                <li><strong>500:</strong> Moderate directed migration (default)</li>
                <li><strong>1000+:</strong> Strong directed migration</li>
            </ul>

            <h3>VEGF Dynamics:</h3>
            <ul>
                <li><strong>Diffusion (vedir):</strong> How fast VEGF spreads</li>
                <li><strong>Decay (veder):</strong> How fast VEGF breaks down</li>
                <li><strong>Secretion (vesec):</strong> How much VEGF cells produce</li>
            </ul>
        </div>

        <div class="section">
            <h2>Tips for Successful Simulations</h2>
            <ul>
                <li><span class="check">✓</span><strong>Stay within physiological ranges</strong> for biologically realistic results</li>
                <li><span class="check">✓</span><strong>Start with presets</strong> to understand typical parameter combinations</li>
                <li><span class="check">✓</span><strong>Change one parameter at a time</strong> to understand its effect</li>
                <li><span class="check">✓</span><strong>Check validation warnings</strong> before running</li>
                <li><span class="check">✓</span><strong>Save interesting configurations</strong> using "Save Parameters"</li>
                <li><span class="warning"></span> Values outside mathematical ranges may crash the simulation</li>
                <li><span class="warning"></span> Extreme parameter combinations may produce nonsensical results</li>
            </ul>
        </div>

        <div class="section">
            <h2>📊 Analysis & Visualization Tools</h2>
            <p><strong>After running a simulation</strong>, click the <strong>"📊 Analyze Results"</strong> button to open a comprehensive 5-tab analysis interface.</p>

            <h3>Tab 1: 📊 Metrics</h3>
            <ul>
                <li><strong>Network Connectivity Metrics:</strong>
                    <ul>
                        <li><i>Cell Density:</i> Fraction of domain occupied by cells</li>
                        <li><i>Number of Clusters:</i> Connected components in the network</li>
                        <li><i>Fragmentation Index:</i> Measures network disconnection</li>
                        <li><i>Connectivity Index:</i> Largest cluster relative to total cells</li>
                        <li><i>Compactness:</i> Network shape (1.0 = perfect circle)</li>
                        <li><i>Network Perimeter:</i> Total boundary length</li>
                    </ul>
                </li>
                <li><strong>Cell-Based Metrics:</strong>
                    <ul>
                        <li><i>Number of Cells:</i> Unique cell count from cell ID field</li>
                        <li><i>Mean/Std Cell Size:</i> Average and variation in cell sizes</li>
                    </ul>
                </li>
                <li><strong>VEGF Statistics:</strong> Min, Max, Mean, Std, Median, 95th Percentile</li>
                <li><strong>Time Series Plots:</strong> Interactive matplotlib visualizations showing metric evolution</li>
                <li><strong>CSV Export:</strong> Export all metrics for external analysis</li>
            </ul>

            <h3>Tab 2: 🔬 Visualization</h3>
            <ul>
                <li><strong>Cell Field Display:</strong> White (medium) → Dark Red (endothelial cells)</li>
                <li><strong>VEGF Field Display:</strong> Viridis colormap (purple → yellow)</li>
                <li><strong>🔒 Locked VEGF Colorbar:</strong> Scale fixed across ALL timesteps for accurate temporal comparison
                    <ul>
                        <li><i>Uses global min/max computed at load time</i></li>
                        <li><i>Range shown in status bar</i></li>
                        <li><i>Prevents misleading color shifts between frames</i></li>
                    </ul>
                </li>
                <li><strong>Cell Boundary Overlay:</strong> Toggle 1-pixel accurate cell borders (black lines)
                    <ul>
                        <li><i>Derived from cell ID field discontinuities</i></li>
                        <li><i>Shows exact cell-cell interfaces</i></li>
                    </ul>
                </li>
                <li><strong>Navigation Controls:</strong>
                    <ul>
                        <li><i>Timestep dropdown or ▶ Play button for animation</i></li>
                        <li><i>Layer toggles: Show Cells, Show VEGF, Show Cell Borders</i></li>
                        <li><i>Side-by-side or individual view modes</i></li>
                    </ul>
                </li>
            </ul>

            <h3>Tab 3: 💾 Export (Priority Feature!)</h3>
            <ul>
                <li><strong>Video Export:</strong>
                    <ul>
                        <li><i>MP4 Format:</i> H.264 codec, configurable FPS (1-30), requires <code>imageio-ffmpeg</code></li>
                        <li><i>GIF Format:</i> Animated GIF for presentations, requires <code>imageio</code></li>
                        <li><i>Layer Selection:</i> Choose which layers to include (Cells, VEGF, Boundaries)</li>
                        <li><i>Progress Monitoring:</i> See frame generation and encoding status</li>
                    </ul>
                </li>
                <li><strong>Still Images:</strong>
                    <ul>
                        <li><i>Current Frame:</i> High-DPI PNG of current visualization</li>
                        <li><i>Metric Plots:</i> Publication-quality time series figures</li>
                    </ul>
                </li>
            </ul>
            <p><strong>📹 To install video export:</strong> <code>pip install imageio imageio-ffmpeg</code></p>

            <h3>Tab 4: 📊 Statistics (Advanced Analysis)</h3>
            <ul>
                <li><strong>Replicate Analysis:</strong> Compare multiple runs with identical parameters
                    <ul>
                        <li><i>Click "Add Replicate" (Ctrl+multi-select supported)</i></li>
                        <li><i>Select metric: cell_density, num_clusters, connectivity_index, etc.</i></li>
                        <li><i>Get statistics: n, mean, std, SEM, 95% CI, median</i></li>
                        <li><i>Visualizations: Box plot with data points + Bar chart with error bars</i></li>
                    </ul>
                </li>
                <li><strong>Statistical Methods:</strong>
                    <ul>
                        <li><i>Standard Error of Mean (SEM)</i></li>
                        <li><i>95% Confidence Interval using t-distribution</i></li>
                        <li><i>Visual assessment of variation</i></li>
                    </ul>
                </li>
            </ul>

            <h3>Tab 5: 📈 Comparison</h3>
            <ul>
                <li><strong>Multi-Experiment Overlay:</strong> Compare different parameter sets
                    <ul>
                        <li><i>Add 2+ experiments (Ctrl+multi-select supported)</i></li>
                        <li><i>Overlaid time series for all metrics</i></li>
                        <li><i>Parameter value bar chart</i></li>
                        <li><i>Color-coded legend by experiment name</i></li>
                    </ul>
                </li>
            </ul>

            <h3>How to Navigate:</h3>
            <ol>
                <li><strong>Run simulation</strong> from main window</li>
                <li><strong>Click "📊 Analyze Results"</strong> button when complete</li>
                <li><strong>Select experiment</strong> from dropdown or browse to folder</li>
                <li><strong>Explore tabs:</strong> Switch between Metrics, Visualization, Export, Statistics, Comparison</li>
                <li><strong>Export results:</strong> Use Export tab for videos, images, or CSV data</li>
                <li><strong>Compare runs:</strong> Use Statistics tab for replicates or Comparison tab for different parameters</li>
            </ol>
        </div>

        <div class="section">
            <h2>Additional Resources</h2>
            <ul>
                <li><strong>Click ℹ buttons</strong> for detailed parameter information</li>
                <li><strong>Click validation icons</strong> to see why a value is flagged</li>
                <li><strong>Export metadata</strong> for publication-ready methods sections</li>
                <li><strong>Save/load parameters</strong> for reproducible experiments</li>
            </ul>
        </div>

        <div class="section">
            <h2>Technical Details</h2>
            <p><strong>Model Type:</strong> Cellular Potts Model (CPM) / Glazier-Graner-Hogeweg (GGH) Model</p>
            <p><strong>Time Unit:</strong> Monte Carlo Step (MCS)</p>
            <p><strong>Space Unit:</strong> Voxels (or Pixels for 2D simulations)</p>
            <p><strong>Framework:</strong> CompuCell3D with Vivarium wrapper</p>
            <p><strong>GUI Version:</strong> 1.0.0 (Schema-driven architecture)</p>
        </div>

        <div class="section" style="text-align: center; margin-top: 20px;">
            <p><strong>For questions, issues, or contributions:</strong></p>
            <p>Contact your lab administrator or check the project <a href="https://github.com/VaninJoel/vivarium-angio/tree/main">repository</a> </p>
        </div>
        """

        text_browser.setHtml(html)
        layout.addWidget(text_browser)

        # Add OK button
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(about_dialog.accept)
        layout.addWidget(button_box)

        about_dialog.exec_()

    def validate_parameter(self, param_name: str):
        """Validate single parameter and update indicator."""
        if param_name not in self.param_widgets:
            return

        value = self.current_params.get(param_name)

        # Handle sweep parameters (comma-separated values)
        if isinstance(value, str) and ',' in value:
            issues = self._validate_sweep_parameter(param_name, value)
        else:
            issues = validate_parameter_value(self.schema, param_name, value)

        indicator = self.param_widgets[param_name]['validation']

        if not issues:
            indicator.setText("✓")
            indicator.setStyleSheet("color: green; font-size: 16px;")
            indicator.setToolTip("Parameter is valid")
        else:
            # Show worst severity
            severities = [issue['severity'] for issue in issues]
            if 'ERROR' in severities or 'CRITICAL' in severities:
                indicator.setText("❌")
                indicator.setStyleSheet("color: red; font-size: 16px;")
            else:
                indicator.setText("⚠️")
                indicator.setStyleSheet("color: orange; font-size: 16px;")

            tooltip = "\n".join([f"{i['severity']}: {i['message']}" for i in issues])
            indicator.setToolTip(tooltip)

    def _validate_sweep_parameter(self, param_name: str, value_str: str):
        """
        Validate comma-separated sweep parameter values.

        Args:
            param_name: Name of the parameter
            value_str: Comma-separated string of values

        Returns:
            list: Issues found across all values in the sweep
        """
        all_issues = []

        if param_name not in self.schema['inputs']:
            return [{'severity': 'ERROR', 'message': 'Parameter not found in schema'}]

        param_info = self.schema['inputs'][param_name]
        expected_type = type(param_info['_default'])

        # Parse comma-separated values
        values = [v.strip() for v in value_str.split(',')]

        for i, val_str in enumerate(values):
            # Try to convert to expected type
            try:
                if expected_type == int:
                    converted_val = int(val_str)
                elif expected_type == float:
                    converted_val = float(val_str)
                elif expected_type == bool:
                    converted_val = val_str.lower() in ('true', '1', 'yes')
                elif expected_type == str:
                    converted_val = val_str
                else:
                    converted_val = val_str

                # Validate the converted value
                issues = validate_parameter_value(self.schema, param_name, converted_val)

                # Add index info to issues
                for issue in issues:
                    issue['message'] = f"Value #{i+1} ({val_str}): {issue['message']}"
                    all_issues.append(issue)

            except ValueError:
                all_issues.append({
                    'severity': 'ERROR',
                    'message': f"Value #{i+1} ({val_str}): Cannot convert to {expected_type.__name__}"
                })

        return all_issues

    def validate_all_parameters(self):
        """Validate all parameters and update summary display, handling sweep parameters."""
        # Build a validation-friendly version of parameters
        # For sweep parameters (comma-separated), validate each value individually
        all_issues = {}

        for param_name, value in self.current_params.items():
            # Handle sweep parameters with custom validation
            if isinstance(value, str) and ',' in value:
                issues = self._validate_sweep_parameter(param_name, value)
                if issues:
                    all_issues[param_name] = issues
            else:
                # Regular validation for single values
                issues = validate_parameter_value(self.schema, param_name, value)
                if issues:
                    all_issues[param_name] = issues

        # Update individual indicators
        for param_name in self.current_params.keys():
            if param_name in self.param_widgets:
                self.validate_parameter(param_name)

        # Update validation summary
        if not all_issues:
            html = "<p style='color: green; font-weight: bold;'>✓ All parameters valid</p>"
        else:
            html = "<h3>Validation Issues:</h3><ul>"
            for param_name, issues in all_issues.items():
                display_name = self.display_names.get(param_name, param_name)
                html += f"<li><b>{display_name}</b>:<ul>"
                for issue in issues:
                    color = 'red' if issue['severity'] == 'ERROR' else 'orange'
                    html += f"<li style='color: {color};'>{issue['message']}</li>"
                html += "</ul></li>"
            html += "</ul>"

        # Note: Validation now shown via clickable indicators - no permanent display panel

    # =========================================================================
    # BATCH EXECUTION METHODS
    # =========================================================================

    def detect_sweep_parameters(self):
        """
        Detect which parameters have comma-separated values for sweeping.

        Returns
        -------
        bool
            True if sweep parameters detected, False otherwise
        """
        self.sweep_parameters = {}
        self.base_parameters = {}

        for param_name, value in self.current_params.items():
            # Convert value to string for checking
            value_str = str(value)

            # Check for comma-separated values
            if isinstance(value_str, str) and ',' in value_str:
                try:
                    # Parse comma-separated list
                    value_list = [self._convert_to_number(v.strip()) for v in value_str.split(',')]
                    self.sweep_parameters[param_name] = value_list
                    self.base_parameters[param_name] = value_list[0]  # Use first as base
                    print(f"  Detected sweep for '{param_name}': {value_list}")
                except Exception as e:
                    print(f"  Warning: Could not parse sweep list for {param_name}: {e}")
                    self.base_parameters[param_name] = value  # Treat as single value
            else:
                self.base_parameters[param_name] = value  # Single value

        print(f"Sweep Parameters: {self.sweep_parameters}")
        print(f"Base Parameters: {self.base_parameters}")
        return bool(self.sweep_parameters)

    def _convert_to_number(self, value_str):
        """Convert string to int or float."""
        try:
            # Try int first
            if '.' not in value_str:
                return int(value_str)
            else:
                return float(value_str)
        except ValueError:
            # Return as-is if not a number
            return value_str

    def generate_parameter_combinations(self):
        """
        Generate all parameter combinations from sweep parameters.

        Returns
        -------
        list of dict
            List of parameter dictionaries for each combination
        """
        if not self.sweep_parameters:
            # No sweep, return single combination
            return [self.base_parameters.copy()]

        from itertools import product

        param_names = list(self.sweep_parameters.keys())
        param_values = [self.sweep_parameters[name] for name in param_names]

        combinations = []
        for i, value_combination in enumerate(product(*param_values)):
            combination = self.base_parameters.copy()
            for name, value in zip(param_names, value_combination):
                combination[name] = value
            combinations.append(combination)
            print(f"  Combination {i+1}: {', '.join([f'{k}={v}' for k, v in combination.items() if k in param_names])}")

        print(f"Generated {len(combinations)} parameter combinations")
        return combinations

    def cancel_batch(self):
        """Cancel all running simulations in batch."""
        self.is_cancelled = True

        reply = QMessageBox.question(
            self,
            "Cancel Batch",
            f"Cancel all running simulations?\n\n"
            f"Completed: {self.completed_combinations}/{self.total_combinations}\n"
            f"Running: {len([t for t, w in self.simulation_threads if t.isRunning()])}",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # Try to terminate all running threads
            for thread, worker in self.simulation_threads:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(1000)  # Wait up to 1 second

            self.statusBar().showMessage("Batch cancelled")
            self.finalize_batch(was_cancelled=True)

    def finalize_batch(self, was_cancelled=False):
        """Clean up after batch completion or cancellation."""
        self.run_button.setEnabled(True)
        self.cancel_button.setVisible(False)
        self.progress_bar.setVisible(False)

        if was_cancelled:
            QMessageBox.information(
                self,
                "Batch Cancelled",
                f"Batch execution cancelled.\n\n"
                f"Completed: {self.completed_combinations}/{self.total_combinations} simulations"
            )
        else:
            QMessageBox.information(
                self,
                "Batch Complete",
                f"All simulations completed successfully!\n\n"
                f"Total runs: {self.completed_combinations}\n"
                f"Output folder: {self.batch_output_folder}"
            )

    # =========================================================================
    # SIMULATION EXECUTION
    # =========================================================================

    def run_simulation(self):
        """Launch simulation(s) with current parameters - handles both single runs and batch sweeps."""
        # Final validation with sweep support
        all_issues = {}

        for param_name, value in self.current_params.items():
            # Handle sweep parameters with custom validation
            if isinstance(value, str) and ',' in value:
                issues = self._validate_sweep_parameter(param_name, value)
                if issues:
                    all_issues[param_name] = issues
            else:
                # Regular validation for single values
                issues = validate_parameter_value(self.schema, param_name, value)
                if issues:
                    all_issues[param_name] = issues

        # Check for errors and warnings
        errors = {p: issues for p, issues in all_issues.items()
                  if any(i['severity'] == 'ERROR' for i in issues)}
        warnings = {p: issues for p, issues in all_issues.items()
                    if any(i['severity'] == 'WARNING' for i in issues)}

        # Show warning dialog but allow user to proceed (pedagogical approach)
        if errors or warnings:
            msg = ""
            if errors:
                msg += f"⚠️ Found {len(errors)} parameter error(s):\n\n"
                for param_name, issues in errors.items():
                    display_name = self.display_names.get(param_name, param_name)
                    msg += f"• {display_name}:\n"
                    for issue in issues:
                        msg += f"  - {issue['message']}\n"
                msg += "\n"

            if warnings:
                msg += f"⚠️ Found {len(warnings)} parameter warning(s):\n\n"
                for param_name, issues in warnings.items():
                    display_name = self.display_names.get(param_name, param_name)
                    msg += f"• {display_name}:\n"
                    for issue in issues:
                        msg += f"  - {issue['message']}\n"

            msg += "\n⚠️ Running with invalid parameters may cause:\n"
            msg += "  • Simulation crashes\n"
            msg += "  • Nonsensical results\n"
            msg += "  • Numerical instabilities\n\n"
            msg += "Do you want to proceed anyway?"

            reply = QMessageBox.question(
                self,
                "Validation Issues Detected",
                msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply == QMessageBox.No:
                return

        # Detect sweep parameters and generate combinations
        is_sweep = self.detect_sweep_parameters()
        self.parameter_combinations = self.generate_parameter_combinations()
        replicates = self.replicate_spinbox.value()

        self.total_combinations = len(self.parameter_combinations) * replicates
        self.completed_combinations = 0
        self.is_cancelled = False

        if self.total_combinations == 0:
            QMessageBox.warning(self, "Error", "No parameter combinations generated.")
            return

        # Get base experiment name from schema parameter
        base_exp_name = self.current_params.get('exp_name', 'unnamed_run')

        # Setup output directory for batch
        from datetime import datetime
        if is_sweep or replicates > 1:
            # Create batch folder with timestamp
            folder_name = f"{base_exp_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.batch_output_folder = self.output_dir / folder_name
            self.batch_output_folder.mkdir(parents=True, exist_ok=True)
        else:
            self.batch_output_folder = self.output_dir

        # Show confirmation with batch info
        sweep_info = ""
        if is_sweep:
            sweep_params = ', '.join([f"{k} ({len(v)} values)" for k, v in self.sweep_parameters.items()])
            sweep_info = f"Parameter Sweep: {sweep_params}\n"

        replicate_info = f"Replicates: {replicates}\n" if replicates > 1 else ""

        reply = QMessageBox.question(
            self,
            "Run Simulation",
            f"{'Batch' if (is_sweep or replicates > 1) else 'Single'} Simulation: '{base_exp_name}'\n\n"
            f"{sweep_info}"
            f"{replicate_info}"
            f"Total runs: {self.total_combinations}\n"
            f"Duration per run: {self.current_params.get('sim_time', 100)} MCS\n"
            f"Warnings: {len(all_issues)}",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.launch_batch_simulation(base_exp_name)

    def launch_batch_simulation(self, base_exp_name):
        """Launch all simulations in batch (handles sweeps and replicates)."""
        # Setup UI for batch
        self.run_button.setEnabled(False)
        self.cancel_button.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(self.total_combinations)
        self.progress_bar.setValue(0)

        replicates = self.replicate_spinbox.value()
        self.simulation_threads = []

        # Status message
        if len(self.parameter_combinations) > 1 or replicates > 1:
            self.statusBar().showMessage(
                f"Starting batch: {self.total_combinations} simulations "
                f"({len(self.parameter_combinations)} combinations × {replicates} replicates)"
            )
        else:
            self.statusBar().showMessage("Starting simulation...")

        # Launch all combinations
        run_counter = 0
        for combo_idx, params in enumerate(self.parameter_combinations):
            for rep_idx in range(replicates):
                run_counter += 1

                # Generate unique experiment name
                if len(self.parameter_combinations) > 1 and replicates > 1:
                    exp_name = f"{base_exp_name}_combo{combo_idx+1:03d}_rep{rep_idx+1:02d}"
                elif len(self.parameter_combinations) > 1:
                    exp_name = f"{base_exp_name}_combo{combo_idx+1:03d}"
                elif replicates > 1:
                    exp_name = f"{base_exp_name}_rep{rep_idx+1:02d}"
                else:
                    exp_name = base_exp_name

                # Set experiment name in parameters
                params_copy = params.copy()
                params_copy['exp_name'] = exp_name

                print(f"Launching simulation {run_counter}/{self.total_combinations}: {exp_name}")

                # Create worker and thread
                worker = SimulationWorker(params_copy, str(self.batch_output_folder))
                thread = QThread()
                worker.moveToThread(thread)

                # Connect signals
                thread.started.connect(worker.run)
                worker.finished.connect(self.on_batch_simulation_finished)
                worker.error.connect(self.on_batch_simulation_error)
                worker.finished.connect(thread.quit)
                worker.finished.connect(worker.deleteLater)
                thread.finished.connect(thread.deleteLater)

                # Start thread
                thread.start()
                self.simulation_threads.append((thread, worker))

                # Small delay between launches to avoid race conditions
                QApplication.processEvents()

    def launch_simulation(self, metadata):
        """Actually launch the simulation in a worker thread."""
        # Disable run button during simulation
        self.run_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        # Create worker and thread (convert Path to string for compatibility)
        self.worker = SimulationWorker(self.current_params.copy(), str(self.output_dir))
        self.worker_thread = QThread()

        # Move worker to thread
        self.worker.moveToThread(self.worker_thread)

        # Connect signals
        self.worker.progress.connect(self.on_simulation_progress)
        self.worker.finished.connect(self.on_simulation_finished)
        self.worker.error.connect(self.on_simulation_error)
        self.worker_thread.started.connect(self.worker.run)

        # Start the thread
        self.worker_thread.start()

    def on_simulation_progress(self, percentage, message):
        """Handle progress updates from simulation worker."""
        self.progress_bar.setValue(percentage)
        self.statusBar().showMessage(message)

    def on_simulation_finished(self, results):
        """Handle simulation completion."""
        # Stop and cleanup thread
        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait()
            self.worker_thread = None
            self.worker = None

        # Re-enable run button
        self.run_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.statusBar().showMessage("Simulation completed successfully", 5000)

        # Show completion dialog
        exp_name = results.get('exp_name', 'unknown')
        final_step = results.get('final_step', 0)
        exp_dir = results.get('exp_dir', 'unknown')
        zarr_path = results.get('zarr_path', 'unknown')
        sim_time = results.get('parameters', {}).get('sim_time', 100)

        # Check if simulation completed fully
        completion_status = "completed successfully" if final_step >= sim_time else f"stopped at step {final_step}"

        msg = (
            f"<h3>Simulation '{exp_name}' {completion_status}!</h3>"
            f"<p><b>Final step:</b> {final_step}/{int(sim_time)} MCS</p>"
            f"<p><b>Experiment directory:</b> <code>{exp_dir}/</code></p>"
        )

        # Show directory structure
        msg += "<hr><p><b>Output structure:</b></p>"
        msg += "<pre style='font-size: 10px;'>"
        msg += f"{exp_name}/\n"
        msg += f"├── data.zarr/         (Zarr arrays)\n"
        msg += f"│   ├── 10/\n"
        msg += f"│   ├── 20/\n"
        msg += f"│   ├── 30/\n"
        msg += f"│   └── ...\n"
        msg += f"├── logs/\n"
        msg += f"│   ├── stdout.log\n"
        msg += f"│   └── stderr.log\n"
        msg += f"└── run_metadata.json\n"
        msg += "</pre>"

        QMessageBox.information(
            self,
            "Simulation Complete",
            msg
        )

    def on_simulation_error(self, error_message):
        """Handle simulation errors."""
        # Stop and cleanup thread
        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait()
            self.worker_thread = None
            self.worker = None

        # Re-enable run button
        self.run_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.statusBar().showMessage("Simulation failed", 5000)

        # Create scrollable error dialog with better formatting
        error_dialog = QMessageBox(self)
        error_dialog.setIcon(QMessageBox.Critical)
        error_dialog.setWindowTitle("Simulation Error")
        error_dialog.setText("<h3>Simulation failed!</h3>")

        # Format error message with HTML for better readability
        formatted_msg = error_message.replace('\n', '<br>')
        error_dialog.setInformativeText(
            f"<p><b>Check the log files for complete output.</b></p>"
            f"<pre style='font-size: 9px;'>{error_message}</pre>"
        )

        error_dialog.setStandardButtons(QMessageBox.Ok)
        error_dialog.setDetailedText(error_message)  # Full text in expandable section
        error_dialog.exec_()

    def on_batch_simulation_finished(self, results):
        """Handle completion of one simulation in a batch."""
        if self.is_cancelled:
            return

        self.completed_combinations += 1
        exp_name = results.get('exp_name', 'unknown')

        # Update progress
        self.progress_bar.setValue(self.completed_combinations)
        self.statusBar().showMessage(
            f"Completed {self.completed_combinations}/{self.total_combinations}: {exp_name}"
        )

        print(f"✓ Completed: {exp_name}")

        # Check if all simulations are done
        if self.completed_combinations >= self.total_combinations:
            self.finalize_batch(was_cancelled=False)

    def on_batch_simulation_error(self, error_message):
        """Handle error in one simulation of a batch."""
        if self.is_cancelled:
            return

        self.completed_combinations += 1

        # Update progress (count as completed even though it failed)
        self.progress_bar.setValue(self.completed_combinations)

        print(f"✗ Error in simulation {self.completed_combinations}/{self.total_combinations}")
        print(f"Error: {error_message[:200]}...")  # Print first 200 chars

        # For batch mode, log errors but continue with other simulations
        # Don't show popup for each error in batch mode
        if self.total_combinations == 1:
            # Single simulation - show full error dialog
            QMessageBox.critical(
                self,
                "Simulation Error",
                f"Simulation failed!\n\n{error_message[:500]}..."
            )

        # Check if all simulations are done
        if self.completed_combinations >= self.total_combinations:
            self.finalize_batch(was_cancelled=False)

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def rebuild_tabs(self):
        """Rebuild parameter tabs (e.g., after expertise change)."""
        # Clear existing tabs
        self.tab_widget.clear()

        # Recreate tabs
        self.create_parameter_tabs()

        # Revalidate
        self.validate_all_parameters()

    def update_parameter_widgets(self, params: dict):
        """Update widget values to match provided parameters."""
        for param_name, value in params.items():
            if param_name in self.param_widgets:
                widget = self.param_widgets[param_name]['input']
                # Update widget value based on type
                if hasattr(widget, 'setValue'):
                    widget.setValue(value)
                elif hasattr(widget, 'setChecked'):
                    widget.setChecked(value)
                elif hasattr(widget, 'setText'):
                    widget.setText(str(value))

    def update_parameter_visibility(self):
        """Update visibility of conditional parameters."""
        # Check each parameter's conditional display
        # (Implementation would check _conditional_display functions)
        pass

    def _load_gui_state(self):
        """Load saved GUI state from settings file."""
        if not self.settings_file.exists():
            return

        try:
            import json
            with open(self.settings_file, 'r') as f:
                settings = json.load(f)

            # Load output directory
            if 'output_dir' in settings:
                self.output_dir = Path(settings['output_dir']).resolve()

            # Load window geometry
            if 'window_geometry' in settings:
                geom = settings['window_geometry']
                self.setGeometry(geom['x'], geom['y'], geom['width'], geom['height'])

            # Load last experiment name (will be applied to current_params after init_ui)
            if 'last_exp_name' in settings:
                self._saved_exp_name = settings['last_exp_name']

        except Exception as e:
            print(f"Warning: Could not load GUI settings: {e}")

    def _save_gui_state(self):
        """Save current GUI state to settings file."""
        try:
            import json

            # Collect current settings
            settings = {
                'output_dir': str(self.output_dir),
                'window_geometry': {
                    'x': self.geometry().x(),
                    'y': self.geometry().y(),
                    'width': self.geometry().width(),
                    'height': self.geometry().height()
                },
                'last_exp_name': self.current_params.get('exp_name', 'vivarium_run')
            }

            # Save to file
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=2)

        except Exception as e:
            print(f"Warning: Could not save GUI settings: {e}")

    def closeEvent(self, event):
        """Handle window close event - save GUI state."""
        self._save_gui_state()
        event.accept()

    def reset_to_defaults(self):
        """Reset all parameters to default values."""
        reply = QMessageBox.question(
            self,
            "Reset Parameters",
            "Reset all parameters to default values?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.current_params = self.model_defaults.copy()
            self.update_parameter_widgets(self.current_params)
            self.preset_combo.setCurrentText('Custom')
            self.validate_all_parameters()

    def show_general_info(self):
        """Show general model information (deprecated - now using About dialog)."""
        pass  # Replaced by About dialog

    def show_preset_info(self, preset: dict):
        """Show information about a preset (deprecated - now shown in message box)."""
        pass  # Info now shown in message box when preset loaded

    def save_parameters_to_file(self):
        """Save current parameters to JSON file."""
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Parameters",
            "",
            "JSON Files (*.json);;All Files (*)"
        )

        if filename:
            import json
            with open(filename, 'w') as f:
                json.dump(self.current_params, f, indent=2)

            QMessageBox.information(self, "Saved", f"Parameters saved to {filename}")

    def load_parameters_from_file(self):
        """Load parameters from JSON file."""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load Parameters",
            "",
            "JSON Files (*.json);;All Files (*)"
        )

        if filename:
            import json
            try:
                with open(filename, 'r') as f:
                    loaded_params = json.load(f)

                self.current_params.update(loaded_params)
                self.update_parameter_widgets(loaded_params)
                self.preset_combo.setCurrentText('Custom')
                self.validate_all_parameters()

                QMessageBox.information(self, "Loaded", f"Parameters loaded from {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load parameters: {str(e)}")

    def browse_output_directory(self):
        """
        Browse for output directory where experiments will be stored.

        This method allows users to select any local directory. For cloud storage,
        users can manually enter paths like:
        - s3://my-bucket/experiments
        - gs://my-bucket/data
        - az://container/simulations

        Cloud storage requires fsspec to be installed with appropriate backends.
        """
        # Open directory selection dialog
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            str(self.output_dir),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )

        if selected_dir:
            # Update output directory
            self.output_dir = Path(selected_dir).resolve()
            self.storage_path_display.setText(str(self.output_dir))

            # Save GUI state to persist the output directory choice
            self._save_gui_state()

            # Inform user
            QMessageBox.information(
                self,
                "Output Directory Updated",
                f"Experiments will be saved to:\n{self.output_dir}\n\n"
                f"For cloud storage, you can manually edit the path to use:\n"
                f"• s3://bucket/path (AWS S3)\n"
                f"• gs://bucket/path (Google Cloud Storage)\n"
                f"• az://container/path (Azure Blob Storage)"
            )

    def _is_number(self, text):
        """Helper to check if text is a valid number."""
        try:
            float(text)
            return True
        except (ValueError, TypeError):
            return False

    def open_analysis_window(self):
        """Open the analysis and visualization window."""
        try:
            # Import here to avoid circular imports
            from analysis_window import AnalysisWindow

            # Create and show analysis window
            self.analysis_window = AnalysisWindow(output_dir=self.output_dir, parent=self)
            self.analysis_window.show()

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to open analysis window:\n{str(e)}\n\n"
                f"Make sure zarr and matplotlib are installed:\n"
                f"pip install zarr matplotlib scipy"
            )

    def connect_signals(self):
        """Connect additional signals."""
        # Add any additional signal connections here
        pass


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Launch the Angiogenesis GUI."""
    # Enable high-DPI scaling BEFORE creating QApplication
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)  # Enable scaling for high-DPI displays
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)     # Use high-resolution icons/images

    app = QApplication(sys.argv)

    # Set application-wide style
    app.setStyle('Fusion')  # Modern cross-platform style

    window = AngiogenesisMainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()