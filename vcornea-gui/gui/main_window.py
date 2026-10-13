"""
Main Window for V-Cornea GUI

Schema-driven interface that connects the V-Cornea schema
to the GUI interface.

Key Features:
- Schema-driven UI generation
- Parameter validation with visual feedback
- Preset management
- Reference documentation display
- Experiment metadata tracking
- Integration with Vivarium Engine

Author: GUI Implementation
Date: 2026
"""

import sys
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QGroupBox, QPushButton, QLabel, QMessageBox, QComboBox,
    QTextBrowser, QFileDialog, QProgressBar, QDoubleSpinBox,
    QCheckBox, QLineEdit, QSpinBox, QDialog, QDialogButtonBox, QSizePolicy,
    QScrollArea
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

# Import vCornea process with comprehensive schema
from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
try:
    # Unit conversion service: editable fields show PHYSICAL units; current_params
    # stays sim-canonical. Only _dimension-tagged params are converted; if the
    # import is unavailable the GUI falls back to showing raw sim values.
    from vivarium_vcornea.utils import units as _units
except Exception:
    _units = None

# Import simulation worker
from simulation_worker import SimulationWorker

# Import schema utilities
sys.path.insert(0, str(Path(__file__).parent.parent / 'utils'))
from schema_utils import (
    format_range_evidence,
    RANGE_TIERS,
    format_ontology_term,
    default_provenance_lines,
    evidence_basis_lines,
    expected_behavior_lines,
    get_parameter_structure,
    get_display_name_mapping,
    get_model_defaults,
    get_full_parameter_info,
    validate_parameter_value,
    should_show_parameter,
)

# Import custom widgets (these would be adapted from vCornea-GUI)
# from widgets.parameter_item import ParameterItem
# from widgets.collapsible_group import CollapsibleGroup
# from widgets.validation_indicator import ValidationIndicator
# from widgets.reference_display import ReferenceDisplay



def _int_from_text(text):
    """Parse an operator-typed integer, accepting an integral float spelling.

    Presets and saved files legitimately carry 10.0 for an int parameter; the
    round trip through a QLineEdit must not turn that into a type error (or,
    worse, store the raw string). A genuinely fractional value still raises.
    """
    text = str(text).strip()
    try:
        return int(text)
    except ValueError:
        f = float(text)
        if f.is_integer():
            return int(f)
        raise ValueError(f"{text!r} is not an integer")


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

                html += f"""
                <div class="range-item">
                    <span class="label">Physiological Range:</span> [{r[0]}, {r[1]}] {param_info.get('_unit', '')}<br>
                    <small>{format_range_evidence(param_info, 'physiological')}</small><br>
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
                    <small>{format_range_evidence(param_info, 'recommended')}</small><br>
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
                    <small>{format_range_evidence(param_info, 'mathematical')}</small><br>
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
                in_range = r[0] <= current_value <= r[1]
                status = "✓" if in_range else "✗"

                html += f"""
                <div class="range-item">
                    <span class="label">{status} Physiological Range:</span> [{r[0]}, {r[1]}] {param_info.get('_unit', '')}<br>
                    <small>{format_range_evidence(param_info, 'physiological')}</small>
                </div>
                """

            if '_recommended_range' in param_info and is_numeric:
                r = param_info['_recommended_range']
                in_range = r[0] <= current_value <= r[1]
                status = "✓" if in_range else "✗"

                html += f"""
                <div class="range-item">
                    <span class="label">{status} Recommended Range:</span> [{r[0]}, {r[1]}] {param_info.get('_unit', '')}<br>
                    <small>{format_range_evidence(param_info, 'recommended')}</small>
                </div>
                """

            if '_mathematical_range' in param_info and is_numeric:
                r = param_info['_mathematical_range']
                in_range = r[0] <= current_value <= r[1]
                status = "✓" if in_range else "✗"

                html += f"""
                <div class="range-item">
                    <span class="label">{status} Mathematical Range:</span> [{r[0]}, {r[1]}] {param_info.get('_unit', '')}<br>
                    <small>{format_range_evidence(param_info, 'mathematical')}</small>
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

        # Schema reference (from the main window) enables in-panel navigation
        # between related parameters/equation terms.
        self._schema = getattr(parent, 'schema', None)
        self._display_names = display_names

        # Create text browser for HTML content
        self._text_browser = QTextBrowser()
        self._history = []  # visited parameter names, for in-place Back navigation
        # We intercept ALL link clicks: `param:<name>` navigates IN-PLACE to another
        # parameter's info (no new window); http(s) links open in the system browser.
        self._text_browser.setOpenLinks(False)
        self._text_browser.anchorClicked.connect(self._on_anchor)

        # Let <img src="<name>.png"> resolve to the equation render cache so
        # rendered LaTeX equations display inline.
        try:
            from equation_render import CACHE_DIR as _EQ_CACHE
            self._text_browser.setSearchPaths([str(_EQ_CACHE)])
        except Exception:
            pass

        layout.addWidget(self._text_browser)

        # Add OK button
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

        # Render the initial parameter (also seeds history).
        self._navigate(param_name)

    def _navigate(self, param_name, record=True):
        """Render a parameter's info in-place (no new window). Used for both the
        initial open and click-through to related parameters/equation terms."""
        info = param_name and self._schema and self._schema.get('inputs', {}).get(param_name)
        if not info:
            return
        info = get_full_parameter_info(self._schema, param_name)
        if record:
            self._history.append(param_name)
        self.setWindowTitle(f"Parameter Information: {info.get('_display_name', param_name)}")
        self._text_browser.setHtml(self._generate_html(param_name, info, self._display_names))

    def _on_anchor(self, qurl):
        """Handle link clicks. `param:<name>` navigates in-place to that parameter;
        `back:` goes to the previous parameter; other schemes open in the browser."""
        try:
            s = qurl.toString()
            if s.startswith('param:'):
                name = s[len('param:'):].lstrip('/')  # case-preserving (avoids QUrl host lowercasing)
                if name:
                    self._navigate(name)
                return
            if s.startswith('back:'):
                if len(self._history) >= 2:
                    self._history.pop()              # drop current
                    self._navigate(self._history[-1], record=False)
                return
            if s:
                import webbrowser
                webbrowser.open(s)
        except Exception:
            pass

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
        """

        # Back link for in-place navigation history.
        if len(getattr(self, '_history', [])) >= 2:
            html += "<div class='info-item'><a href='back:'>← Back</a></div>"

        html += f"""
        <div class="description">
            <p>{param_info.get('_long_description', param_info.get('_description', 'No description available'))}</p>
        </div>
        """

        # Basic details
        html += "<h3>Details</h3><ul>"
        html += f"<li><span class='label'>Parameter Name:</span> <code>{param_name}</code></li>"
        html += f"<li><span class='label'>Category:</span> {param_info.get('_category', 'N/A')}</li>"
        html += f"<li><span class='label'>Subcategory:</span> {param_info.get('_subcategory', 'N/A')}</li>"
        html += f"<li><span class='label'>Unit (as documented):</span> {param_info.get('_unit', 'dimensionless')}</li>"
        html += f"<li><span class='label'>Expertise Level:</span> {param_info.get('_expert_level', 'N/A').title()}</li>"
        if param_info.get('_unit_long'):
            html += f"<li><span class='label'>Unit, spelled out:</span> {param_info['_unit_long']}</li>"
        if param_info.get('_ontology_term'):
            html += f"<li><span class='label'>Ontology term:</span> {format_ontology_term(param_info['_ontology_term'])}</li>"
        html += "</ul>"

        # --- Units & Conversion (learner panel) ---
        # Storage is sim-canonical: _default and ranges are in SIMULATION units.
        # We surface the physical equivalent + the conversion rule so the operator
        # sees physical units while the value the model runs stays explicit.
        dim = param_info.get('_dimension')
        disp_override = param_info.get('_display_unit')
        sim_default = param_info.get('_default', None)
        try:
            from vivarium_vcornea.utils import units as _units
        except Exception:
            _units = None

        is_number = isinstance(sim_default, (int, float)) and not isinstance(sim_default, bool)

        def _fmt_range(r):
            if _units is not None and dim and abs(_units.factor(dim, disp_override) - 1.0) > 1e-12:
                dr = _units.convert_range(r, dim, disp_override)
                dl = _units.display_unit_label(dim, disp_override)
                sl = _units.sim_unit_label(dim)
                return f"[{dr[0]:g}, {dr[1]:g}] {dl} &nbsp;<i>(sim: [{r[0]:g}, {r[1]:g}] {sl})</i>"
            return f"[{r[0]}, {r[1]}] {param_info.get('_unit', '')}"

        if _units is not None and dim and is_number:
            f = _units.factor(dim, disp_override)
            disp_label = _units.display_unit_label(dim, disp_override)
            sim_label = _units.sim_unit_label(dim)
            html += "<h3>Units &amp; Conversion</h3><ul>"
            if abs(f - 1.0) < 1e-12:
                html += f"<li><span class='label'>Value:</span> {sim_default:g} {disp_label or param_info.get('_unit', '')}</li>"
                html += f"<li><i>Arbitrary {dim} unit — no physical conversion; the simulation uses this number directly.</i></li>"
            else:
                disp_val = _units.to_display(sim_default, dim, disp_override)
                html += f"<li><span class='label'>Value (physical):</span> {disp_val:g} {disp_label}</li>"
                html += f"<li><span class='label'>Simulation value:</span> {sim_default:g} {sim_label}</li>"
                html += f"<li><span class='label'>Conversion rule:</span> display = simulation × {f:g} &nbsp;(1 {sim_label} = {f:g} {disp_label})</li>"
            html += "</ul>"
        else:
            # Booleans / categoricals / time-as-days (pre-flip) / untagged: show as stored.
            html += "<h3>Value</h3><ul>"
            html += f"<li><span class='label'>Unit:</span> {param_info.get('_unit', 'dimensionless')}</li>"
            html += f"<li><span class='label'>Default Value:</span> {param_info.get('_default', 'N/A')}</li>"
            html += "</ul>"

        # Validation ranges (shown in physical + simulation units)
        if any(k in param_info for k in ('_physiological_range', '_recommended_range', '_mathematical_range')):
            html += "<h3>Valid Ranges</h3><ul>"
            for key, tier, label in RANGE_TIERS:
                if key in param_info:
                    html += (f"<li><span class='label'>{label}:</span> {_fmt_range(param_info[key])}"
                             f"<br><small>{format_range_evidence(param_info, tier)}</small></li>")
            html += "</ul>"

        # Where the default value came from, with its locator (table / equation / page)
        if param_info.get('_reference_paper'):
            html += "<h3>Default Value Provenance</h3>"
            for label, text in default_provenance_lines(param_info['_reference_paper']):
                html += f"<div class='info-item'><span class='label'>{label}:</span> {text}</div>"
        basis = evidence_basis_lines(param_info)
        if basis:
            html += "<h3>Evidence Basis</h3><ul>"
            for label, text in basis:
                html += f"<li><span class='label'>{label}:</span> {text}</li>"
            html += "</ul>"

        # Literature (external cited works behind the parameter's value). Entries are
        # paper reference numbers resolved against the bibliography (references.py) so
        # citations + DOIs live in a single source.
        if param_info.get('_literature'):
            try:
                from vivarium_vcornea.utils import references as _refs
            except Exception:
                _refs = None
            html += "<h3>Literature</h3><ul>"
            for lit in param_info['_literature']:
                if isinstance(lit, int) and _refs is not None:
                    r = _refs.REFERENCES.get(lit, {})
                    line = r.get('cite', f'[ref {lit}]')
                    if r.get('doi'):
                        line += f" &middot; <a href='https://doi.org/{r['doi']}'>doi:{r['doi']}</a>"
                    elif r.get('pmid'):
                        line += f" &middot; PMID:{r['pmid']}"
                    html += f"<li>{line}</li>"
                elif isinstance(lit, dict):
                    line = lit.get('cite', '')
                    if lit.get('doi'):
                        line += f" &middot; <a href='https://doi.org/{lit['doi']}'>doi:{lit['doi']}</a>"
                    html += f"<li>{line}</li>"
                else:
                    html += f"<li>{lit}</li>"
            html += "</ul>"

        # Biological meaning
        if '_biological_meaning' in param_info:
            html += "<h3>Biological Meaning</h3>"
            html += f"<div class='description'>{param_info['_biological_meaning']}</div>"

        # Model context
        if '_model_context' in param_info:
            html += "<h3>Model Context</h3>"
            html += f"<div class='description'>{param_info['_model_context']}</div>"

        # GUI / Implementation — how this knob is realized in the simulation.
        impl = []
        if _units is not None and dim and is_number and abs(_units.factor(dim, disp_override) - 1.0) > 1e-12:
            impl.append(f"Displayed in the GUI as <b>{_units.to_display(sim_default, dim, disp_override):g} "
                        f"{_units.display_unit_label(dim, disp_override)}</b>, converted from the stored simulation value.")
        # The literal assignment the run will write: the CURRENT value (not the
        # schema default), through the same conversion the Parameters.py writer
        # uses (e.g. SimTime in days -> MCS).
        current_params = getattr(self.parent(), 'current_params', None) or {}
        current_value = current_params.get(param_name, sim_default)
        if current_value is not None:
            try:
                from vivarium_vcornea.processes.vcornea_process import to_cc3d_value
                written = to_cc3d_value(param_info, current_value)
            except Exception:
                written = current_value
            impl.append(f"Written to <code>Parameters.py</code> as <code>{param_name}={written!r}</code> "
                        f"(CC3D-native units — the value the model actually runs).")
        if '_conditional_display' in param_info:
            impl.append("Shown conditionally in the GUI (depends on injury/mode flags).")
        if param_info.get('_implementation_pattern'):
            impl.append(param_info['_implementation_pattern'])
        if impl:
            html += "<h3>GUI / Implementation</h3><ul>"
            for _it in impl:
                html += f"<li>{_it}</li>"
            html += "</ul>"

        # Governing equations (from the equations registry; mathtext-rendered images
        # with a LaTeX-source fallback for constructs mathtext can't typeset).
        try:
            from vivarium_vcornea.utils import equations as _eqs
            from equation_render import render_latex_png as _render_eq
        except Exception:
            _eqs = None
        try:
            from vivarium_vcornea.utils import references as _refs_eq
        except Exception:
            _refs_eq = None
        if _eqs is not None:
            eqmap = _eqs.equations_for_param(param_name)
            if eqmap:
                html += "<h3>Governing Equations</h3>"
                for _eid, _e in eqmap.items():
                    html += (f"<div class='info-item'><span class='label'>{_e['name']}</span>"
                             f" <span style='color:#7f8c8d'>· {_e.get('paper_ref', '')}</span></div>")
                    try:
                        _png, _w = _render_eq(_e['latex'])
                    except Exception:
                        _png, _w = None, 0
                    if _png:
                        # Cap display width so wide equations fit the panel; keep
                        # narrow ones at natural size (never enlarge).
                        _disp_w = min(_w, 500) if _w else 500
                        html += f"<div class='info-item'><img src='{_png}' width='{_disp_w}'></div>"
                    else:
                        html += (f"<div class='info-item'><pre style='background:#f4f6f7;"
                                 f"padding:6px;white-space:pre-wrap'>{_e['latex']}</pre></div>")
                    if _e.get('description'):
                        html += f"<div class='info-item' style='color:#566573'>{_e['description']}</div>"
                    # Sibling parameters this equation also governs -> clickable cross-navigation
                    sibs = [g for g in _e.get('governs', [])
                            if g != param_name and self._schema and g in self._schema.get('inputs', {})]
                    if sibs:
                        links = " · ".join(
                            f"<a href='param:{g}'>{display_names.get(g, g)}</a>" for g in sibs)
                        html += (f"<div class='info-item' style='color:#566573'>"
                                 f"Other parameters in this equation: {links}</div>")
                    # Supporting literature for this equation (resolved via references.py).
                    erefs = _eqs.refs_for(_eid) if hasattr(_eqs, 'refs_for') else []
                    if erefs and _refs_eq is not None:
                        parts = []
                        for _n in erefs:
                            _r = _refs_eq.REFERENCES.get(_n, {})
                            lbl = _refs_eq.short(_n)
                            parts.append(f"<a href='https://doi.org/{_r['doi']}'>{lbl}</a>"
                                         if _r.get('doi') else lbl)
                        html += (f"<div class='info-item' style='color:#7f8c8d'>"
                                 f"Refs: {', '.join(parts)}</div>")

        # Conceptualization hint (single source: schema; also projected to the vault note)
        if param_info.get('_conceptual_hint'):
            html += "<h3>Conceptualization Hints</h3>"
            html += f"<div class='description'>{param_info['_conceptual_hint']}</div>"

        # Related parameters — clickable cross-navigation when they're real knobs.
        if '_related_parameters' in param_info and param_info['_related_parameters']:
            html += "<h3>Related Parameters</h3><ul>"
            for related in param_info['_related_parameters']:
                display_name = display_names.get(related, related)
                if self._schema and related in self._schema.get('inputs', {}):
                    html += f"<li><a href='param:{related}'>{display_name}</a> (<code>{related}</code>)</li>"
                else:
                    html += f"<li>{display_name} (<code>{related}</code>)</li>"
            html += "</ul>"

        # Dependencies
        if '_dependencies' in param_info and param_info['_dependencies']:
            html += "<h3>Parameter Dependencies</h3><ul>"
            for dep_param, desc in param_info['_dependencies'].items():
                display_name = display_names.get(dep_param, dep_param)
                html += f"<li><span class='label'>{display_name}:</span> {desc}</li>"
            html += "</ul>"

        # Expected behaviour as the value changes (low / high regimes, transition)
        behavior = expected_behavior_lines(param_info)
        if behavior:
            html += "<h3>Expected Behavior</h3><ul>"
            for label, text in behavior:
                html += f"<li><span class='label'>{label}:</span> {text}</li>"
            html += "</ul>"

        # Presets
        if param_info.get('_presets'):
            html += "<h3>Available Presets</h3><ul>"
            for preset_name, preset_value in param_info['_presets'].items():
                html += f"<li><span class='label'>{preset_name}:</span> {preset_value}</li>"
            html += "</ul>"

        return html


class VCorneaMainWindow(QMainWindow):
    """
    Main window for vCornea cell fate simulation GUI.

    Schema-driven interface that automatically generates UI from
    the VCorneaProcess ports_schema().
    """

    def __init__(self):
        super().__init__()

        # =====================================================================
        # INITIALIZE PROCESS AND SCHEMA
        # =====================================================================

        # Create process instance to get schema.
        # Prefer the clean paper-version model from github.com/VaninJoel/vCornea
        # (no MaBoSS coupling); the cellfate-augmented copy was crashing CC3D
        # on startup via `from maboss_helpers import ...` and is now kept only
        # as a fallback in case the clean source isn't present.
        project_root = Path(__file__).resolve().parents[2]
        candidates = [
            project_root / 'vcornea_paper' / 'Local' / 'Project' / 'paper_version',
            project_root / 'vcornea_cellfate_updated',
        ]
        vcornea_project_path = next((p for p in candidates if p.exists()), None)
        if vcornea_project_path is not None:
            self.process = VCorneaProcess({'vcornea_project_path': str(vcornea_project_path)})
        else:
            self.process = VCorneaProcess()
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

        # If no saved state, use default output directory.
        # absolute() instead of resolve() so a mapped drive letter (e.g. X:)
        # survives instead of being normalized to its UNC target.
        if not hasattr(self, 'output_dir') or self.output_dir is None:
            self.output_dir = (Path(__file__).parent.parent / 'experiments').absolute()

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

        self.setWindowTitle("V-Cornea Simulation")
        self.setGeometry(100, 100, 1400, 900)
        # Keep the floor small enough to fit a high-DPI 1080p panel (where the
        # logical screen can be ~960x500); tabs scroll, so the window can shrink.
        self.setMinimumSize(800, 560)
        self.setStyleSheet(
            "QMainWindow { background: #f7f7f7; }"
            "QGroupBox { font-weight: bold; border: 1px solid #d9d9d9;"
            " border-radius: 6px; margin-top: 12px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
            "QLabel { color: #2c3e50; }"
            "QTabWidget::pane { border: 1px solid #d0d0d0; border-radius: 6px; }"
            "QTabBar::tab { padding: 6px 14px; }"
        )

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
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("V-Cornea")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        subtitle = QLabel(
            "Configure injury scenarios, tissue parameters, and output reporting. "
            "Hover or click info icons for biological context."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #5f6b77;")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        panel_layout.addWidget(header)

        toolbar = self.create_toolbar()
        panel_layout.addWidget(toolbar)

        # --- PARAMETER TABS ---
        self.tab_widget = QTabWidget()
        self.tab_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        panel_layout.addWidget(self.tab_widget, stretch=1)

        # --- RUN CONTROLS ---
        run_controls = self.create_run_controls()
        panel_layout.addWidget(run_controls)

        # Add panel directly to main layout (no splitter needed)
        main_layout.addWidget(main_panel)

    def create_toolbar(self):
        """Create toolbar with preset, expertise, and file controls."""

        toolbar = QGroupBox("Session Controls")
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
        preset_names = []
        if hasattr(self.process, 'get_preset_names'):
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

        # Create tabs based on parameter structure
        for tab_name, groups in self.parameter_structure.items():
            tab_container = QWidget()
            tab_layout = QVBoxLayout(tab_container)
            tab_layout.setAlignment(Qt.AlignTop)
            tab_layout.setContentsMargins(12, 12, 12, 12)
            tab_layout.setSpacing(12)

            # Create collapsible groups for each subcategory
            for group_name, params in groups.items():
                # Filter params by expertise level
                group_params = {
                    p: desc for p, desc in params.items()
                }

                if not group_params:
                    continue  # Skip empty groups

                # Create collapsible group
                # In real implementation, use CollapsibleGroup widget
                group_box = QGroupBox(group_name)
                group_layout = QVBoxLayout()
                group_layout.setSpacing(8)

                for param_name, description in group_params.items():
                    # Create parameter item
                    # In real implementation, use ParameterItem widget
                    param_widget = self.create_parameter_widget(param_name)
                    group_layout.addWidget(param_widget)
                    if param_name in self.param_widgets:
                        self.param_widgets[param_name]['group_box'] = group_box

                group_box.setLayout(group_layout)
                tab_layout.addWidget(group_box)

            tab_layout.addStretch()

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(tab_container)
            scroll.setFrameShape(QScrollArea.NoFrame)
            self.tab_widget.addTab(scroll, tab_name)

        # Apply conditional display rules so initial paint reflects current_params
        self.update_parameter_visibility()

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
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
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
            # Pure categorical parameter — always a fixed-options combo box.
            # The previous "Custom..." + editable-combo affordance was removed
            # because every categorical parameter in the schema is boolean
            # (two options); a free-text field would only invite invalid input.
            widget = QComboBox()

            for value, label_text in value_mapping.items():
                widget.addItem(label_text, value)  # Store actual value as data

            index = widget.findData(current_value)
            if index >= 0:
                widget.setCurrentIndex(index)

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
            widget.setText(self.sim_to_display_str(param_name, current_value))
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
            widget.setText(self.sim_to_display_str(param_name, current_value))
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
        widget.setMinimumWidth(160)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Physical-unit suffix so the operator always sees the unit they edit in.
        unit_text = ''
        if _units is not None:
            _dim, _du = self._param_dim(param_name)
            if _dim:
                unit_text = _units.display_unit_label(_dim, _du)
        if not unit_text:
            unit_text = param_info.get('_unit', '')
        if unit_text and unit_text not in ('boolean', 'categorical', 'dimensionless', '-'):
            unit_lbl = QLabel(unit_text)
            unit_lbl.setStyleSheet("color: #7f8c8d;")
            unit_lbl.setMinimumWidth(70)
            layout.addWidget(unit_lbl)

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
        layout.setStretch(1, 1)

        # Disable if above current expertise level
        level_order = {'basic': 0, 'intermediate': 1, 'advanced': 2}
        param_level = param_info.get('_expert_level', 'advanced')
        if level_order.get(param_level, 2) > level_order.get(self.expertise_level, 0):
            widget.setEnabled(False)
            label.setStyleSheet("color: #9aa4ad;")
            widget.setToolTip("Increase expertise level to edit this parameter.")
            info_btn.setToolTip("Increase expertise level to edit this parameter.")
            validation_label.setToolTip("Increase expertise level to edit this parameter.")

        # Store references for later updates
        if not hasattr(self, 'param_widgets'):
            self.param_widgets = {}
        self.param_widgets[param_name] = {
            'input': widget,
            'validation': validation_label,
            'container': container,
            'group_box': None,
        }

        container.setLayout(layout)
        return container

    def create_run_controls(self):
        """Create simulation run controls."""

        controls = QGroupBox("Simulation Control")
        layout = QVBoxLayout()

        # Experiment name input — drives the output sub-folder name and
        # propagates as exp_name to VCorneaProcess (which now uses it for
        # the inner run_name as well so the batch and replicate dirs match).
        exp_name_layout = QHBoxLayout()
        exp_name_layout.addWidget(QLabel("Experiment Name:"))
        self.exp_name_input = QLineEdit()
        initial_exp_name = (
            getattr(self, '_saved_exp_name', None)
            or self.current_params.get('exp_name')
            or 'vcornea_run'
        )
        self.exp_name_input.setText(initial_exp_name)
        self.current_params['exp_name'] = initial_exp_name
        self.exp_name_input.setPlaceholderText("e.g. control_run, chem_injury_high_SLS")
        self.exp_name_input.setToolTip(
            "Name used for the output folder (and .omex archive) of this run.\n"
            "Avoid spaces and slashes; the same name is reused on subsequent runs."
        )
        self.exp_name_input.textChanged.connect(self._on_exp_name_changed)
        exp_name_layout.addWidget(self.exp_name_input)
        layout.addLayout(exp_name_layout)

        # Operator identity — recorded as the OMEX metadata.rdf creator (attribution,
        # not authentication). Optional; the person responsible for this run.
        operator_layout = QHBoxLayout()
        operator_layout.addWidget(QLabel("Operator:"))
        self.operator_name_input = QLineEdit()
        self.operator_name_input.setPlaceholderText("Your name (recorded as OMEX creator)")
        self.operator_name_input.setToolTip(
            "Optional. The person responsible for this run's parameters; written to the\n"
            "OMEX metadata.rdf creator. Attribution/provenance, not authentication.")
        operator_layout.addWidget(self.operator_name_input)
        operator_layout.addWidget(QLabel("Email:"))
        self.operator_email_input = QLineEdit()
        self.operator_email_input.setPlaceholderText("optional")
        self.operator_email_input.setMaximumWidth(180)
        operator_layout.addWidget(self.operator_email_input)
        self.operator_name_input.textChanged.connect(self._update_creator)
        self.operator_email_input.textChanged.connect(self._update_creator)
        layout.addLayout(operator_layout)

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
        info_label = QLabel(
            "Tip: Use comma-separated values for parameter sweeps "
            "(e.g., <b>Injury Radius:</b> 20,30 or <b>EGF_BASAL_HalfMaxValue:</b> 5,7,9)."
        )
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

        # Concurrency cap. Each run is a CC3D process; starting a whole sweep at
        # once starves the workstation (readiness audit 3.3). Runs beyond the cap
        # wait in a queue and start as slots free up; the batch result is the same.
        concurrency_layout = QHBoxLayout()
        concurrency_label = QLabel("Max simultaneous runs:")
        concurrency_label.setToolTip("How many simulations may execute at the same time; the rest queue.")
        self.concurrency_spinbox = QSpinBox()
        self.concurrency_spinbox.setRange(1, 64)
        self.concurrency_spinbox.setValue(
            getattr(self, '_saved_max_concurrent', None) or self.default_max_concurrent_runs())
        self.concurrency_spinbox.setToolTip(
            "Default is one less than the number of CPU cores. Each run is a separate "
            "CompuCell3D process; queued runs start automatically as others finish.")
        concurrency_layout.addWidget(concurrency_label)
        concurrency_layout.addWidget(self.concurrency_spinbox)
        concurrency_layout.addStretch()
        batch_layout.addLayout(concurrency_layout)

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

    def _param_dim(self, param_name):
        """Return (dimension, display_unit) for a parameter, or (None, None)."""
        info = self.schema['inputs'].get(param_name, {})
        return info.get('_dimension'), info.get('_display_unit')

    def _is_int_param(self, param_name):
        d = self.schema['inputs'].get(param_name, {}).get('_default')
        return isinstance(d, int) and not isinstance(d, bool)

    def _fmt_num(self, param_name, num):
        """Format a number for the field, honoring the parameter's int/float type."""
        if self._is_int_param(param_name):
            return str(int(round(num)))
        return f"{num:g}"

    def sim_to_display_str(self, param_name, sim_value):
        """Sim-canonical stored value -> physical string shown in the editable field.

        Handles single values and comma-separated sweep strings. Non-dimensioned
        params (booleans, time, untagged) are returned unchanged (identity).
        """
        dim, du = self._param_dim(param_name)
        if _units is None or not dim:
            return str(sim_value)

        def one(x):
            return self._fmt_num(param_name, _units.to_display(float(x), dim, du))

        if isinstance(sim_value, str):
            if ',' in sim_value:
                parts = []
                for p in sim_value.split(','):
                    p = p.strip()
                    try:
                        parts.append(one(p))
                    except ValueError:
                        parts.append(p)
                return ','.join(parts)
            try:
                return one(sim_value)
            except ValueError:
                return sim_value
        if isinstance(sim_value, (int, float)) and not isinstance(sim_value, bool):
            return one(sim_value)
        return str(sim_value)

    def _display_to_sim(self, param_name, display_value):
        """Physical (display-unit) value -> sim-canonical value for current_params.

        Single values return a number; sweep strings return a comma-separated
        string. Non-dimensioned params are returned unchanged (identity).
        """
        dim, du = self._param_dim(param_name)
        if _units is None or not dim:
            return display_value
        is_int = self._is_int_param(param_name)

        def one(x):
            s = _units.to_model_units(float(x), dim, du)
            return int(round(s)) if is_int else s

        if isinstance(display_value, str):
            if ',' in display_value:
                out = []
                for p in display_value.split(','):
                    p = p.strip()
                    try:
                        out.append(str(one(p)))
                    except ValueError:
                        out.append(p)
                return ','.join(out)
            try:
                return one(display_value)
            except ValueError:
                return display_value
        if isinstance(display_value, (int, float)) and not isinstance(display_value, bool):
            return one(display_value)
        return display_value

    def _convert_parameter_value(self, param_name: str, value):
        """Convert a widget value into the sim-canonical value stored in current_params.

        Stage 1: parse to the correct Python type (or keep a comma-separated sweep
        string), in DISPLAY units. Stage 2: convert display -> sim for
        _dimension-tagged params via the units service (no-op otherwise).
        """
        if param_name not in self.schema['inputs']:
            return value

        param_info = self.schema['inputs'][param_name]
        expected_type = type(param_info['_default'])

        # Stage 1: normalize to a display-unit value (type-correct, or sweep string).
        if isinstance(value, str):
            value_str = value.strip()
            if ',' in value_str:
                display_val = value_str  # sweep; per-value conversion happens in stage 2
            else:
                try:
                    if expected_type == int:
                        display_val = int(float(value_str))  # tolerate "30.0"
                    elif expected_type == float:
                        display_val = float(value_str)
                    elif expected_type == bool:
                        display_val = value_str.lower() in ('true', '1', 'yes')
                    elif expected_type == str:
                        display_val = value_str
                    else:
                        display_val = value_str
                except ValueError:
                    return value  # invalid input; validation will flag it
        else:
            display_val = value

        # Stage 2: display -> sim (identity for non-dimensioned params).
        return self._display_to_sim(param_name, display_val)

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
        """Display the About dialog with model citation and GUI information."""
        about_dialog = QDialog(self)
        about_dialog.setWindowTitle("About V-Cornea")
        about_dialog.setMinimumSize(700, 600)

        layout = QVBoxLayout(about_dialog)

        text_browser = QTextBrowser()
        text_browser.setOpenExternalLinks(True)

        html = """
        <style>
            body { font-family: Arial, sans-serif; margin: 15px; }
            h1 { color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }
            h2 { color: #34495e; margin-top: 20px; }
            h3 { color: #7f8c8d; margin-top: 15px; }
            .section { background-color: #ecf0f1; padding: 15px; border-radius: 5px; margin: 10px 0; }
            ul { margin-left: 20px; }
            a { color: #3498db; }
            .citation { font-size: 11px; color: #555; }
        </style>

        <h1>V-Cornea</h1>
        <p><i>A computational model of corneal epithelium homeostasis, injury, and recovery.</i></p>

        <div class="section">
            <h2>About the model</h2>
            <p>V-Cornea is an agent-based model of the human corneal epithelium implemented
            in <strong>CompuCell3D</strong>. Individual cells follow biologically-motivated
            rules for growth, movement, differentiation, and death, and an EGF signaling
            field couples cell-level behavior to tissue-level outcomes
            (in&nbsp;vitro to in&nbsp;vivo extrapolation, IVIVE).</p>

            <h3>What the model reproduces</h3>
            <ul>
                <li>Layered epithelial architecture (stem, basal, wing, superficial cells)</li>
                <li>Homeostatic tissue maintenance over a 7&ndash;14 day renewal cycle</li>
                <li>Healing of slight and mild injuries in 3&ndash;5 days</li>
                <li>Persistent disorganization following moderate injuries that disrupt the basement membrane,
                    resembling recurrent corneal erosions</li>
            </ul>

            <h3>Injury scenarios</h3>
            <ul>
                <li><strong>Chemical exposure</strong> &mdash; SLS application with configurable concentration and pattern</li>
                <li><strong>Mechanical ablation</strong> &mdash; localized tissue removal with configurable depth and radius</li>
            </ul>
        </div>

        <div class="section">
            <h2>Citation</h2>
            <p class="citation">Vanin J, Getz M, Mahony C, Knudsen TB, Glazier JA (2025).
            <i>V-Cornea: A computational model of corneal epithelium homeostasis, injury,
            and recovery.</i> PLoS Computational Biology 21(12): e1013410.
            DOI: <a href="https://doi.org/10.1371/journal.pcbi.1013410">10.1371/journal.pcbi.1013410</a></p>
            <p><strong>Source code:</strong>
            <a href="https://github.com/VaninJoel/vCornea">github.com/VaninJoel/vCornea</a></p>
            <p><strong>Versioned archive:</strong>
            <a href="https://doi.org/10.5281/zenodo.16764318">Zenodo 10.5281/zenodo.16764318</a></p>
        </div>

        <div class="section">
            <h2>About this GUI</h2>
            <p>The GUI is a schema-driven front-end that loads parameter metadata directly
            from the V-Cornea Vivarium wrapper. Three expertise levels (Basic, Intermediate,
            Advanced) progressively expose parameters; conditional-display logic hides
            scenario-irrelevant parameters as you toggle injury type.</p>

            <h3>Workflow</h3>
            <ol>
                <li><strong>Pick an expertise level</strong> in the toolbar.</li>
                <li><strong>Configure parameters</strong> across the tabs. Hover for tooltips or
                    click the <strong>&#8505;</strong> button next to a parameter for full metadata.</li>
                <li><strong>Optional &mdash; explore parameter space</strong>: enter comma-separated values
                    in any field (e.g. <code>5,7,9</code>) to sweep, and set the replicates count.</li>
                <li><strong>Run Simulation</strong>. Every run produces a self-contained
                    COMBINE/OMEX archive alongside the CSV/Parquet outputs.</li>
                <li><strong>Click "Analyze Results"</strong> when complete for plots and comparisons.</li>
            </ol>
        </div>

        <div class="section">
            <h2>Outputs</h2>
            <p>Each run produces under the experiment directory:</p>
            <ul>
                <li>Per-step CSV/Parquet files (cell counts, thickness, injury tracking, field statistics)</li>
                <li><code>run_metadata.json</code> &mdash; parameter values, execution record, file index</li>
                <li><code>&lt;exp_name&gt;.omex</code> &mdash; COMBINE archive with SED-ML L1V4 description for reproducibility</li>
                <li><code>logs/</code> &mdash; stdout and stderr from the CC3D subprocess</li>
            </ul>
        </div>

        <div class="section">
            <h2>Technical details</h2>
            <p><strong>Model framework:</strong> Cellular Potts (Glazier-Graner-Hogeweg) Model</p>
            <p><strong>Simulator:</strong> CompuCell3D, driven via the Vivarium wrapper as a headless subprocess</p>
            <p><strong>Time unit:</strong> Monte Carlo Step (MCS). 1 MCS &asymp; 6 minutes; 240 MCS &asymp; 1 day.</p>
            <p><strong>Spatial unit:</strong> 1 voxel &asymp; 2&nbsp;&micro;m (2D lattice)</p>
            <p><strong>Standards compliance:</strong> SED-ML L1V4, COMBINE Archive (.omex)</p>
        </div>

        <div class="section">
            <h2>Funding &amp; affiliations</h2>
            <p>Developed by the Glazier Lab, Indiana University Bloomington
            (Department of Intelligent Systems Engineering, Biocomplexity Institute),
            in collaboration with the Procter &amp; Gamble Technical Centre (Reading, UK).</p>
            <p class="citation">Supported by Procter &amp; Gamble, NSF awards 2303695 and 2120200,
            and NIH grant U24 EB028887.</p>
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
                    converted_val = _int_from_text(val_str)
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
        """Cancel all running simulations in batch.

        This is non-trivial: the worker thread is blocked inside Python
        code (subprocess.wait) so `thread.quit()` alone does nothing. We
        also have to kill the spawned subprocess tree (Python interpreter
        + conda wrapper + CC3D) — otherwise CC3D keeps consuming CPU long
        after Cancel was clicked. Each SimulationWorker.cancel() kills its
        own process tree; THEN we tell the Qt threads to wind down.
        """
        reply = QMessageBox.question(
            self,
            "Cancel Batch",
            f"Cancel all running simulations?\n\n"
            f"Completed: {self.completed_combinations}/{self.total_combinations}\n"
            f"Running: {len([t for t, w in self.simulation_threads if t.isRunning()])}\n"
            f"Queued (not started): {len(getattr(self, '_pending_runs', []))}\n\n"
            f"This will terminate the CC3D subprocesses immediately.",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        self.is_cancelled = True
        queued = len(getattr(self, '_pending_runs', []))
        self._pending_runs = []       # never start what has not started
        if queued:
            print(f"  > {queued} queued run(s) will not be started")
        self.statusBar().showMessage("Cancelling — terminating CC3D subprocesses...")
        QApplication.processEvents()

        killed = 0
        cancelled_names = []
        for thread, worker in self.simulation_threads:
            if not thread.isRunning():
                continue
            try:
                worker.cancel()  # Kills subprocess TREE + drops cancelled.json
                killed += 1
                cancelled_names.append(worker.exp_name)
            except Exception as e:
                print(f"  > Warning: failed to cancel worker {getattr(worker, 'exp_name', '?')}: {e}")
            # Now that the blocking subprocess.wait() has returned (its child
            # was killed), the QThread's event loop can be exited cleanly.
            thread.quit()
            thread.wait(2000)
            if thread.isRunning():
                thread.terminate()
                thread.wait(1000)

        # Persist a batch-level cancellation record in experiment_log.csv so
        # the cancelled runs show up alongside completed/failed ones when
        # someone audits the batch later.
        self._append_cancellation_audit(cancelled_names)

        self._batch_cancelled = killed
        self.statusBar().showMessage(
            f"Batch cancelled ({killed} subprocess tree(s) terminated)", 5000
        )
        self.finalize_batch(was_cancelled=True)

    def _append_cancellation_audit(self, cancelled_names):
        """Append one row per cancelled run to experiment_log.csv.

        VCorneaProcess writes to experiment_log.csv only when a run
        completes; cancelled runs would otherwise be invisible in the
        per-batch audit trail. This makes them first-class entries.
        """
        if not cancelled_names or self.batch_output_folder is None:
            return
        from datetime import datetime
        try:
            # Same append-only, locked, fixed-column log VCorneaProcess writes,
            # so cancellation rows can never corrupt or be clobbered by it.
            from vivarium_vcornea.utils.experiment_log import append_rows
            now = datetime.now().isoformat()
            injury_type = 'ablation' if self.current_params.get('InjuryType', False) else 'chemical'
            append_rows(self.batch_output_folder, [{
                'run_name': name,
                'status': 'cancelled',
                'simulation_success': False,
                'created_at': now,
                'completed_at': now,
                'sim_time': self.current_params.get('SimTime'),
                'has_injury': self.current_params.get('IsInjury'),
                'injury_type': injury_type,
                'output_directory': name,
                'error_message': 'Run interrupted by the operator before completion.',
            } for name in cancelled_names])
        except Exception as e:
            print(f"  > Warning: could not append cancellation to experiment_log.csv: {e}")

    def finalize_batch(self, was_cancelled=False):
        """Clean up after batch completion or cancellation.

        Reports honest success/failure counts. Earlier this always claimed
        "All simulations completed successfully!" even when every replicate
        had failed, because it only counted invocations, not outcomes.
        """
        self.run_button.setEnabled(True)
        self.cancel_button.setVisible(False)
        self.progress_bar.setVisible(False)

        succeeded = getattr(self, '_batch_succeeded', 0)
        failed = getattr(self, '_batch_failed', 0)
        cancelled = getattr(self, '_batch_cancelled', 0)
        total = self.total_combinations
        not_started = max(0, total - succeeded - failed - cancelled)

        # For a completed sweep, emit the experiment-level scan OMEX at the batch
        # root (documents the full scan as a SED-ML repeatedTask over the ranges).
        scan_archive_path = None
        if not was_cancelled and getattr(self, 'sweep_parameters', None) and succeeded > 0:
            scan_archive_path = self._generate_experiment_scan_archive()

        # Then generate the OMEX PDF report(s) — per-combination plus the experiment
        # comparison — now that every .omex (and the scan.omex) has been written.
        # A batch whose runs all failed still gets a report: it lists the failed
        # attempts, which are part of the record.
        if not was_cancelled and (succeeded > 0 or failed > 0):
            self._generate_run_pdfs()

        if was_cancelled:
            lines = [
                f"Batch execution cancelled by user.",
                "",
                f"Total runs in batch: {total}",
                f"  Succeeded before cancel: {succeeded}",
                f"  Failed before cancel:    {failed}",
                f"  Cancelled (killed):      {cancelled}",
            ]
            if not_started:
                lines.append(f"  Never started:           {not_started}")
            lines.append("")
            lines.append(f"Output folder: {self.batch_output_folder}")
            lines.append("")
            lines.append(
                "Cancelled runs are recorded as CANCELLED in experiment_log.csv "
                "and each cancelled run dir contains a cancelled.json audit marker."
            )
            QMessageBox.warning(
                self,
                "Batch Cancelled",
                "\n".join(lines)
            )
        elif failed == 0 and succeeded == total:
            scan_note = (f"\n\nExperiment scan archive: {scan_archive_path.name}"
                         if scan_archive_path else "")
            QMessageBox.information(
                self,
                "Batch Complete",
                f"All {total} simulation(s) completed successfully.\n\n"
                f"Output folder: {self.batch_output_folder}"
                f"{scan_note}"
            )
        elif succeeded == 0:
            QMessageBox.critical(
                self,
                "Batch Failed",
                f"All {total} simulation(s) failed.\n\n"
                f"Check the per-replicate stderr.log files under:\n"
                f"{self.batch_output_folder}"
            )
        else:
            QMessageBox.warning(
                self,
                "Batch Complete (partial)",
                f"{succeeded}/{total} simulation(s) succeeded; {failed} failed.\n\n"
                f"Output folder: {self.batch_output_folder}\n"
                f"Check stderr.log in the failed replicates' directories."
            )

        # Reset trackers for the next batch
        self._batch_succeeded = 0
        self._batch_failed = 0
        self._batch_cancelled = 0

    def _generate_experiment_scan_archive(self):
        """Emit the experiment-level scan OMEX at the batch root after a sweep.

        Documents the whole scan as a SED-ML repeatedTask over the parameter ranges
        and catalogues each point's output folder. Best-effort: any failure here is
        logged but never blocks batch finalization. Returns the .omex Path or None.
        """
        scan_spec = getattr(self, 'sweep_parameters', None)
        if not scan_spec:
            return None
        try:
            from vivarium_vcornea.utils.omex_generator import create_experiment_scan_archive
            sim_params = {'SimTime': self.current_params.get('SimTime', 24)}
            return create_experiment_scan_archive(
                batch_output_dir=self.batch_output_folder,
                scan_spec=dict(scan_spec),
                combinations=getattr(self, '_scan_combination_records', []),
                sim_params=sim_params,
                run_name=getattr(self, '_scan_base_exp_name', None),
                num_replicates=getattr(self, '_scan_replicates', 1),
                creator=self.current_params.get('creator'),
            )
        except Exception as e:  # never let archive generation break the batch
            print(f"  > WARNING: experiment scan archive not generated: {e}")
            return None

    def _generate_run_pdfs(self):
        """Generate the OMEX PDF report(s) for the just-finished run.

        Runs make_omex_combo_report.py in a DETACHED subprocess so it cannot disturb
        the GUI's matplotlib backend and a missing dependency (reportlab, etc.) only
        logs a warning instead of breaking the batch. Produces one
        <combo>_omex_report.pdf per combination plus, for sweeps, the
        <experiment>_experiment_report.pdf at the experiment root.
        """
        import subprocess
        import sys as _sys
        from pathlib import Path as _P
        try:
            # Experiment folder: the batch folder for sweeps/replicates; for a plain
            # single run it is output_dir/<exp_name> (the batch folder is output_dir).
            folder = _P(self.batch_output_folder)
            if folder == _P(self.output_dir):
                exp = f"{getattr(self, '_scan_base_exp_name', 'run')}_{getattr(self, '_run_timestamp', '')}"
                folder = _P(self.output_dir) / exp
            # Locate the report tool via the installed vivarium_vcornea package
            # (avoid importing it here so its matplotlib 'Agg' switch stays out of
            # this process).
            import vivarium_vcornea
            tool = _P(vivarium_vcornea.__file__).resolve().parent.parent / "make_omex_combo_report.py"
            if not tool.exists():
                print(f"  > OMEX PDF report tool not found at {tool}; skipping.")
                return
            subprocess.Popen([_sys.executable, str(tool), str(folder)])
            print(f"  > Launched OMEX PDF report generation for {folder}")
        except Exception as e:  # never block the batch on reporting
            print(f"  > WARNING: OMEX PDF report not generated: {e}")

    # =========================================================================
    # SIMULATION EXECUTION
    # =========================================================================

    def run_simulation(self):
        """Launch simulation(s) with current parameters - handles both single runs and batch sweeps."""
        # Final validation with sweep support.
        # Skip GUI-only metadata fields (exp_name, run_id, etc.) that
        # legitimately don't appear in the VCorneaProcess schema — otherwise
        # they fire spurious "Parameter not found in schema" errors.
        gui_only_fields = {'exp_name', 'run_name', 'run_id', 'output_base_dir'}
        all_issues = {}

        for param_name, value in self.current_params.items():
            if param_name in gui_only_fields:
                continue
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

        # Total combinations = number of parameter sets (VCorneaProcess handles replicates internally)
        self.total_combinations = len(self.parameter_combinations)
        self.completed_combinations = 0
        self.is_cancelled = False

        if self.total_combinations == 0:
            QMessageBox.warning(self, "Error", "No parameter combinations generated.")
            return

        # Get base experiment name from schema parameter
        base_exp_name = self.current_params.get('exp_name', 'unnamed_run')

        # Setup output directory for batch. Always add a timestamp so reruns
        # don't overwrite earlier results. For sweeps the timestamp goes on
        # the batch wrapper folder; for single runs the timestamp is folded
        # into the run exp_name (no extra wrapper folder).
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._run_timestamp = timestamp
        if is_sweep or replicates > 1:
            folder_name = f"{base_exp_name}_{timestamp}"
            self.batch_output_folder = self.output_dir / folder_name
            self.batch_output_folder.mkdir(parents=True, exist_ok=True)
        else:
            self.batch_output_folder = self.output_dir

        # Confirmation dialog — read SimTime from the actual schema key
        # (CamelCase, in DAYS) and show both days and the CC3D-equivalent MCS.
        sim_time_days = self.current_params.get('SimTime', 24)
        try:
            sim_time_mcs = int(round(float(sim_time_days) * 240))
        except (TypeError, ValueError):
            sim_time_mcs = '?'

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
            f"Duration per run: {sim_time_days} days ({sim_time_mcs} MCS)\n"
            f"Output folder: {base_exp_name}_{timestamp}/\n"
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

        # Reset per-batch success/failure/cancelled trackers so the
        # finalize_batch summary reflects only this batch (not leftover
        # counts from a previous interrupted run).
        self._batch_succeeded = 0
        self._batch_failed = 0
        self._batch_cancelled = 0

        replicates = self.replicate_spinbox.value()
        self.simulation_threads = []
        self._pending_runs = []      # (exp_name, params) not yet started
        self._active_runs = 0
        self._launched_runs = 0

        # Status message
        if len(self.parameter_combinations) > 1 or replicates > 1:
            self.statusBar().showMessage(
                f"Starting batch: {self.total_combinations} simulations "
                f"({len(self.parameter_combinations)} combinations × {replicates} replicates)"
            )
        else:
            self.statusBar().showMessage("Starting simulation...")

        # Launch all combinations
        # NOTE: VCorneaProcess handles replicates internally, so we DON'T loop over replicates here
        # Records (swept values + output folder) for the experiment-level scan OMEX,
        # built once all combos finish (see _generate_experiment_scan_archive).
        self._scan_base_exp_name = base_exp_name
        self._scan_replicates = replicates
        self._scan_combination_records = []
        run_counter = 0
        for combo_idx, params in enumerate(self.parameter_combinations):
            run_counter += 1

            # Generate unique experiment name (no _rep suffix - VCorneaProcess creates replicate_N folders).
            # For SINGLE runs (no sweep wrapper folder), fold the timestamp into
            # the exp_name itself so the resulting output dir is unique. For
            # sweeps, the parent batch folder already carries the timestamp, so
            # the inner combo names stay short.
            timestamp = getattr(self, '_run_timestamp', '')
            if len(self.parameter_combinations) > 1:
                exp_name = f"{base_exp_name}_combo{combo_idx+1:03d}"
            elif timestamp:
                exp_name = f"{base_exp_name}_{timestamp}"
            else:
                exp_name = base_exp_name

            # Set experiment name and replicates in parameters
            params_copy = params.copy()
            params_copy['exp_name'] = exp_name
            params_copy['replicates'] = replicates  # Let VCorneaProcess handle all replicates
            params_copy['creator'] = self.current_params.get('creator')  # OMEX provenance

            # Parameter-scan provenance (control-only keys; never written to
            # Parameters.py). Lets each per-run OMEX annotate its scan point and
            # feeds the experiment-level scan archive built in finalize_batch.
            if self.sweep_parameters:
                scan_point = {name: params[name]
                              for name in self.sweep_parameters if name in params}
                params_copy['parameter_scan'] = dict(self.sweep_parameters)
                params_copy['scan_point'] = scan_point
                params_copy['combination_index'] = combo_idx + 1
                params_copy['total_combinations'] = len(self.parameter_combinations)
                self._scan_combination_records.append(
                    {**scan_point, '_index': combo_idx + 1, '_folder': exp_name})

            print(f"Launching simulation {run_counter}/{len(self.parameter_combinations)}: {exp_name} ({replicates} replicate{'s' if replicates > 1 else ''})")

            self._pending_runs.append((exp_name, params_copy))

        self._start_queued_runs()

    # ------------------------------------------------------------------
    # Batch queue: at most `concurrency_spinbox` runs execute at once
    # ------------------------------------------------------------------
    @staticmethod
    def default_max_concurrent_runs():
        import os
        return max(1, (os.cpu_count() or 2) - 1)

    def max_concurrent_runs(self):
        try:
            return max(1, int(self.concurrency_spinbox.value()))
        except Exception:
            return self.default_max_concurrent_runs()

    def _start_queued_runs(self):
        """Start pending runs until the concurrency cap is reached."""
        cap = self.max_concurrent_runs()
        while self._pending_runs and self._active_runs < cap and not self.is_cancelled:
            exp_name, params_copy = self._pending_runs.pop(0)
            self._start_run(exp_name, params_copy)
        self._update_batch_status()

    def _update_batch_status(self, note=None):
        if not hasattr(self, 'total_combinations'):
            return
        msg = (f"Completed {self.completed_combinations}/{self.total_combinations}"
               f" \u00b7 running {self._active_runs}"
               f" \u00b7 queued {len(self._pending_runs)}"
               f" (max {self.max_concurrent_runs()} at once)")
        if note:
            msg += f" \u00b7 {note}"
        self.statusBar().showMessage(msg)

    def _release_run_slot(self):
        """A run finished or failed: free its slot and start the next queued run."""
        self._active_runs = max(0, self._active_runs - 1)
        self._start_queued_runs()

    def _start_run(self, exp_name, params_copy):
        """Create the worker + thread for one run and start it (the old loop body)."""
        self._launched_runs += 1
        print(f"Launching simulation {self._launched_runs}/{self.total_combinations}: {exp_name}"
              f"  [running {self._active_runs + 1}, queued {len(self._pending_runs)}]")
        worker = self._make_worker(params_copy)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self.on_batch_simulation_finished)
        worker.error.connect(self.on_batch_simulation_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._active_runs += 1
        thread.start()
        self.simulation_threads.append((thread, worker))
        QApplication.processEvents()

    def _make_worker(self, params_copy):
        return SimulationWorker(params_copy, str(self.batch_output_folder))


    def on_simulation_progress(self, percentage, message):
        """Handle progress updates from simulation worker."""
        self.progress_bar.setValue(percentage)
        self.statusBar().showMessage(message)


    def on_batch_simulation_finished(self, results):
        """Handle completion of one simulation in a batch."""
        if self.is_cancelled:
            return

        self.completed_combinations += 1
        self._release_run_slot()
        self._batch_succeeded = getattr(self, '_batch_succeeded', 0) + 1
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
        self._release_run_slot()
        self._batch_failed = getattr(self, '_batch_failed', 0) + 1

        # Update progress (count as completed even though it failed)
        self.progress_bar.setValue(self.completed_combinations)

        print(f"✗ Error in simulation {self.completed_combinations}/{self.total_combinations}")
        print(f"Error: {error_message[:200]}...")  # Print first 200 chars

        # In single-run (1 combination × 1+ replicates) mode the per-replicate
        # error and the final finalize_batch popup would say the same thing
        # twice — and worse, the batch popup would still claim success
        # because it didn't track failures. With the new finalize_batch
        # tracking, the batch popup is now accurate, so we skip the early
        # per-replicate popup entirely. All run details are still in
        # stderr.log under the replicate directory.

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
        """Update widget values to match provided parameters.

        Handles QSpinBox/QDoubleSpinBox (setValue), QCheckBox (setChecked),
        QComboBox (findData -> setCurrentIndex), and QLineEdit (setText).
        After widget updates, refreshes conditional-display so changes that
        flip trigger params (e.g. IsInjury, InjuryType from a preset) collapse
        or expand the right groups.
        """
        for param_name, value in params.items():
            if param_name not in self.param_widgets:
                continue
            widget = self.param_widgets[param_name]['input']
            try:
                # QComboBox first — `findData` lets us match by underlying value
                # (e.g. True/False) rather than the display label.
                if hasattr(widget, 'findData') and hasattr(widget, 'setCurrentIndex'):
                    idx = widget.findData(value)
                    if idx >= 0:
                        widget.setCurrentIndex(idx)
                        continue
                if isinstance(value, bool) and hasattr(widget, 'setChecked'):
                    widget.setChecked(value)
                elif hasattr(widget, 'setValue') and isinstance(value, (int, float)) and not isinstance(value, bool):
                    dim, du = self._param_dim(param_name)
                    widget.setValue(_units.to_display(value, dim, du) if (_units and dim) else value)
                elif hasattr(widget, 'setText'):
                    # current_params/presets are sim-canonical; show physical in the field.
                    widget.setText(self.sim_to_display_str(param_name, value))
            except (RuntimeError, TypeError):
                continue

        # Conditional display lambdas read current_params; the caller must have
        # already updated current_params before invoking us. Refresh so groups
        # collapse/expand for any preset/load that toggled IsInjury/InjuryType.
        self.update_parameter_visibility()

    def update_parameter_visibility(self):
        """Toggle parameter row visibility based on _conditional_display lambdas.

        Drives the schema's `_conditional_display` metadata: each parameter row
        is shown only when its lambda evaluates True against current_params.
        Group boxes with no remaining visible rows are hidden too so the UI
        does not show empty section headers. Layouts are explicitly
        invalidated so the QScrollArea/QGroupBox nesting reflows immediately
        instead of waiting for the next paint event.
        """
        if not hasattr(self, 'param_widgets') or 'inputs' not in self.schema:
            return

        group_has_visible = {}
        group_objs = {}
        layouts_to_invalidate = set()
        hidden_count = 0
        shown_count = 0

        for param_name in self.schema['inputs']:
            widgets = self.param_widgets.get(param_name)
            if not widgets:
                continue
            container = widgets.get('container')
            if container is None:
                continue
            try:
                visible = should_show_parameter(self.schema, param_name, self.current_params)
                # Grey out inapplicable parameters (e.g. injury params when injury is
                # off) instead of hiding them, so the operator always sees the full
                # parameter set (consistent with expertise-level greying).
                container.setVisible(True)
                container.setEnabled(visible)
                # Track parent layouts so we can invalidate them once at the end
                parent_layout = container.parentWidget().layout() if container.parentWidget() else None
                if parent_layout is not None:
                    layouts_to_invalidate.add(parent_layout)
                if visible:
                    shown_count += 1
                else:
                    hidden_count += 1
            except RuntimeError:
                # Widget was deleted (e.g., after rebuild_tabs cleared the tabs)
                continue
            group_box = widgets.get('group_box')
            if group_box is not None:
                gid = id(group_box)
                group_objs[gid] = group_box
                group_has_visible[gid] = group_has_visible.get(gid, False) or visible

        for gid, gb in group_objs.items():
            try:
                gb.setVisible(True)  # keep groups visible; rows inside are greyed, not hidden
                if gb.parentWidget() and gb.parentWidget().layout():
                    layouts_to_invalidate.add(gb.parentWidget().layout())
            except RuntimeError:
                continue

        # Force Qt to recompute layout geometry now instead of on next paint
        for lay in layouts_to_invalidate:
            try:
                lay.invalidate()
                lay.activate()
            except RuntimeError:
                continue
        if hasattr(self, 'tab_widget') and self.tab_widget is not None:
            try:
                self.tab_widget.updateGeometry()
                cur = self.tab_widget.currentWidget()
                if cur is not None:
                    cur.updateGeometry()
            except RuntimeError:
                pass

        # One-shot diagnostic on first call so the user can verify wiring.
        # Set CORNEA_GUI_DEBUG=1 in the environment to keep printing every call.
        import os as _os
        if not getattr(self, '_visibility_logged', False) or _os.environ.get('CORNEA_GUI_DEBUG'):
            inj = self.current_params.get('IsInjury')
            inj_type = self.current_params.get('InjuryType')
            print(f"[conditional-display] IsInjury={inj} InjuryType={inj_type}  "
                  f"-> shown={shown_count} hidden={hidden_count}  "
                  f"groups_visible={sum(1 for v in group_has_visible.values() if v)}/"
                  f"{len(group_has_visible)}")
            self._visibility_logged = True

    def _load_gui_state(self):
        """Load saved GUI state from settings file."""
        if not self.settings_file.exists():
            return

        try:
            import json
            with open(self.settings_file, 'r') as f:
                settings = json.load(f)

            # Load output directory.
            # absolute() not resolve(): keep a mapped drive letter (e.g. X:)
            # the user saved instead of normalizing to its UNC target.
            if 'output_dir' in settings:
                self.output_dir = Path(settings['output_dir']).absolute()

            # Load window geometry
            if 'window_geometry' in settings:
                geom = settings['window_geometry']
                self.setGeometry(geom['x'], geom['y'], geom['width'], geom['height'])

            # Load last experiment name (will be applied to current_params after init_ui)
            if 'max_concurrent_runs' in settings:
                try:   # applied when the control is built (settings load before the UI)
                    self._saved_max_concurrent = int(settings['max_concurrent_runs'])
                except (TypeError, ValueError):
                    pass
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
                'max_concurrent_runs': self.max_concurrent_runs(),
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
            # Use absolute() rather than resolve(): on Windows, resolve()
            # follows symlinks/junction points so a mapped network drive
            # (e.g. X: -> \\wsl.localhost\Ubuntu\...) gets normalized to
            # the UNC target, which the user did not pick. absolute() keeps
            # the drive letter the user actually selected.
            self.output_dir = Path(selected_dir).absolute()
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

    def _on_exp_name_changed(self, text: str):
        """Propagate the experiment-name field into current_params.

        VCorneaProcess reads `exp_name` as the canonical run identifier; the
        GUI also uses it to construct the batch output folder name. Keeping
        them in lockstep avoids the bug where the inner replicate dirs got
        an auto-generated `default_run_<ts>` while the batch dir carried the
        user-supplied name.
        """
        # The name becomes a folder name and the archive stem: keep it to the
        # same character set the angio schema enforces (_validation_pattern
        # ^[a-zA-Z0-9_-]+$), replacing anything else so '1,2,3' or 'a b' cannot
        # produce odd directories.
        import re as _re
        cleaned = _re.sub(r'[^a-zA-Z0-9_-]+', '_', text.strip()).strip('_')[:50] or 'vcornea_run'
        self.current_params['exp_name'] = cleaned
        if cleaned != text:
            self.exp_name_input.setToolTip(
                f"Only letters, digits, '_' and '-' are kept (max 50): the run will be named '{cleaned}'.")

    def _update_creator(self):
        """Build the OMEX creator dict from the operator name/email fields and store
        it in current_params['creator'] (None when both are blank)."""
        name = self.operator_name_input.text().strip()
        email = self.operator_email_input.text().strip()
        creator = None
        if name or email:
            creator = {}
            if name:
                parts = name.rsplit(' ', 1)
                if len(parts) == 2:
                    creator['given'], creator['family'] = parts[0], parts[1]
                else:
                    creator['given'] = name
            if email:
                creator['email'] = email
        self.current_params['creator'] = creator

    def _is_number(self, text):
        """Helper to check if text is a valid number."""
        try:
            float(text)
            return True
        except (ValueError, TypeError):
            return False

    def _latest_experiment_dir(self):
        """Most recently modified experiment folder (immediate child of the output
        root that contains run outputs). Returns None if none found.

        Experiment folders carry a unique timestamp suffix, so we select by
        modification time rather than by name. We never return the output root
        itself (it mixes all experiments).
        """
        try:
            root = Path(getattr(self, 'output_dir', '') or '')
            if not root.exists():
                return None
        except Exception:
            return None
        candidates = []
        for d in sorted(root.iterdir(), reverse=True):
            try:
                if d.is_dir() and next(d.rglob('cell_count_*.csv'), None) is not None:
                    candidates.append(d)
            except Exception:
                continue  # skip unreadable subdir, don't abort the whole scan
        if not candidates:
            return None
        try:
            return max(candidates, key=lambda p: p.stat().st_mtime)
        except Exception:
            return candidates[0]

    def open_analysis_window(self):
        """Open the analysis and visualization window."""
        try:
            # Import here to avoid circular imports
            from analysis_window import AnalysisWindow

            # Auto-load the most recent EXPERIMENT folder (one level below the
            # output root), never the output root itself — loading the root would
            # mix every experiment's combos into one dataset. Also pass the output
            # root so the Browse dialog opens there (not in the GUI source folder).
            out_root = str(getattr(self, 'output_dir', '') or '')
            self.analysis_window = AnalysisWindow(
                exp_dir=self._latest_experiment_dir(), default_dir=out_root)
            self.analysis_window.show()

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to open analysis window:\n{str(e)}\n\n"
                f"Make sure pandas and matplotlib are installed:\n"
                f"pip install pandas matplotlib"
            )

    def connect_signals(self):
        """Connect additional signals."""
        # Add any additional signal connections here
        pass


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Launch the V-Cornea GUI."""
    # Enable high-DPI scaling BEFORE creating QApplication
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)  # Enable scaling for high-DPI displays
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)     # Use high-resolution icons/images

    app = QApplication(sys.argv)

    # Set application-wide style
    app.setStyle('Fusion')  # Modern cross-platform style

    window = VCorneaMainWindow()
    # Fit the window within the available screen. High-DPI display scaling
    # (e.g. 200% on a 1080p panel) leaves little logical screen space, so clamp
    # the default 1400x900 geometry to what actually fits and center it instead
    # of overflowing the monitor.
    avail = app.primaryScreen().availableGeometry()
    w = min(window.width(), avail.width())
    h = min(window.height(), avail.height())
    window.resize(w, h)
    window.move(avail.left() + (avail.width() - w) // 2,
                avail.top() + (avail.height() - h) // 2)
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
