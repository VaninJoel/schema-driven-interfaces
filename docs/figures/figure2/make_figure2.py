"""Build manuscript Figure 2, "One parameter definition, several consumers".

    python docs/figures/figure2/make_figure2.py            # writes into this folder

Every panel is produced from the live code at one commit, so the figure cannot
show anything the software does not do:

  A  abridged Angio-GUI schema entry for VEGF diffusion (`vedir`), printed
     from AngiogenesisProcess.ports_schema() (real field names and values);
  B  the GUI row generated from that entry, rendered at three values: inside
     every range, outside the evidence-supported range (warning), and outside
     the admissible range (blocking error);
  C  the Angio-GUI information panel rendered from the same entry (cropped to
     the sections the caption discusses);
  D  the parameter-audit record of a run with vedir = 3.0, as written into the
     run's archive (parameter_audit.json, abridged);
  E  the same schema format in V-Cornea (`EGF_SUPERDiffCoef`): unit conversion,
     the literal Parameters.py assignment and the governing equation.

Outputs: panel_A.png ... panel_E.png, figure2.png / figure2.pdf (assembled
draft), and caption.md, which carries both schema fingerprints.

Rendering uses the Qt widgets themselves (never shown on screen). On a headless
machine set QT_QPA_PLATFORM=offscreen.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Windows are laid out but never put on screen (Qt.WA_DontShowOnScreen, below).
# Only a machine with no display at all falls back to the offscreen platform,
# which on Windows has no system fonts and would render text-less panels.
if sys.platform.startswith('linux') and not os.environ.get('DISPLAY') \
        and not os.environ.get('WAYLAND_DISPLAY'):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / 'tests' / 'gui'))   # harness: loads one GUI's modules cleanly

PANEL_WIDTH = 560          # px, before the device-pixel-ratio scale
SCALE = 3                  # render at 3x for print resolution

ANGIO_PARAM = 'vedir'
ANGIO_STATES = [(1.0, 'within every range'),
                (3.0, 'outside the supported range: warning'),
                (12.0, 'outside the admissible range: error')]
AUDIT_VALUE = 3.0
VCORNEA_PARAM = 'EGF_SUPERDiffCoef'

# Fields printed in panel A, in this order. Everything else is counted as omitted.
PANEL_A_FIELDS = ['_default', '_display_name', '_category', '_subcategory', '_expert_level',
                  '_unit', '_dimension', '_mathematical_range', '_physiological_range',
                  '_recommended_range', '_range_evidence', '_ontology_term', '_dependencies',
                  '_expected_behavior', '_reference_paper', '_measurable', '_experimental_assay']
PANEL_C_SECTIONS = ['Valid Ranges', 'Evidence Basis', 'Expected Behavior', 'Parameter Dependencies']
PANEL_E_SECTIONS = ['Units &amp; Conversion', 'GUI / Implementation', 'Governing Equations']

MONO = "font-family: Consolas, 'DejaVu Sans Mono', monospace; font-size: 10.5px;"


# ---------------------------------------------------------------- helpers
def _qapp():
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _grab(widget, path):
    """Render a widget at SCALE x into a PNG (no window is shown).

    A child widget keeps the geometry its layout gave it (so every control in a
    row is captured); only a free-standing widget is sized to its content.
    """
    from PyQt5.QtGui import QPixmap, QPainter, QColor
    from PyQt5.QtWidgets import QApplication
    QApplication.processEvents()
    widget.ensurePolished()
    if widget.parent() is None:
        widget.adjustSize()
    size = widget.size()
    if widget.parent() is not None:
        # A layout may stretch a row taller than it needs; capture its natural height.
        size.setHeight(min(size.height(), max(widget.sizeHint().height(), 1)))
    pm = QPixmap(size * SCALE)
    pm.setDevicePixelRatio(SCALE)
    pm.fill(QColor('white'))
    painter = QPainter(pm)
    from PyQt5.QtCore import QRect, QPoint
    from PyQt5.QtGui import QRegion
    widget.render(painter, QPoint(), QRegion(QRect(0, 0, size.width(), size.height())))
    painter.end()
    pm.save(str(path))
    return path


def _html_panel(html, path, search_paths=(), wrap=True):
    """Draw an HTML fragment's whole document into a PNG.

    The document is laid out by a QTextBrowser (which resolves images such as the
    rendered equations through its search paths) and drawn in full, so nothing is
    clipped to a viewport. wrap=False keeps preformatted text on its own lines.
    """
    from PyQt5.QtGui import QPixmap, QPainter, QColor
    from PyQt5.QtWidgets import QTextBrowser
    tb = QTextBrowser()
    tb.setSearchPaths([str(p) for p in search_paths])
    tb.setHtml(html)
    doc = tb.document()
    doc.setTextWidth(PANEL_WIDTH)
    if not wrap:
        doc.setTextWidth(doc.idealWidth())
    w, h = int(doc.size().width()) + 1, int(doc.size().height()) + 1
    pm = QPixmap(w * SCALE, h * SCALE)
    pm.setDevicePixelRatio(SCALE)
    pm.fill(QColor('white'))
    painter = QPainter(pm)
    doc.drawContents(painter)
    painter.end()
    pm.save(str(path))
    return path


def _sections(html, wanted):
    """Keep the info panel's <style> plus the <h3> sections named in `wanted`."""
    head, *chunks = html.split('<h3>')
    style = head[head.find('<style>'):head.find('</style>') + 8] if '<style>' in head else ''
    kept = []
    for name in wanted:
        for c in chunks:
            if c.startswith(name):
                kept.append('<h3>' + c)
    return style + ''.join(kept)


def _short(v, limit=110):
    s = ' '.join(str(v).split())
    return s if len(s) <= limit else s[:limit - 4] + ' […]'


def _pyrepr(v, indent, limit=110):
    """Python-literal rendering of a schema value, long strings shortened."""
    pad = ' ' * indent
    if isinstance(v, dict):
        if not v:
            return '{}'
        items = [f"{pad}    {k!r}: {_pyrepr(x, indent + 4, limit)}," for k, x in v.items()]
        return '{\n' + '\n'.join(items) + f'\n{pad}}}'
    if isinstance(v, str):
        return repr(_short(v, limit))
    return repr(v)


# ---------------------------------------------------------------- panels
def panel_a(schema, path):
    info = schema['inputs'][ANGIO_PARAM]
    lines = [f"'{ANGIO_PARAM}': {{"]
    for k in PANEL_A_FIELDS:
        if k not in info:
            continue
        v = info[k]
        if k == '_range_evidence':                 # keep basis/refs/note per tier
            v = {t: {f: e.get(f) for f in ('basis', 'refs', 'note') if f in e}
                 for t, e in v.items() if isinstance(e, dict)}
        if k == '_reference_paper':                # the provenance of the default
            v = {f: v.get(f) for f in ('source', 'value', 'notes') if f in v}
        lines.append(f"    {k!r}: {_pyrepr(v, 4, 92)},")
    omitted = [k for k in info if k not in PANEL_A_FIELDS]
    lines.append(f"    # … {len(omitted)} further fields omitted "
                 f"({', '.join(omitted[:4])}, …)")
    lines.append('}')
    text = '\n'.join(lines)
    (path.with_suffix('.txt')).write_text(text + '\n', encoding='utf-8')
    from html import escape
    return _html_panel(f"<pre style=\"{MONO}\">{escape(text)}</pre>", path, wrap=False)


def panel_b(win, path):
    """The generated row at three values, stacked, each with its verdict."""
    from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
    row = win.param_widgets[ANGIO_PARAM]
    tooltips = []
    host = QWidget()
    lay = QVBoxLayout(host)
    for value, caption in ANGIO_STATES:
        row['input'].setText(str(value))           # same path as typing a value
        tip = row['validation'].toolTip()
        tooltips.append({'value': value, 'indicator': row['validation'].text(), 'messages': tip})
        img = _grab(row['container'], path.with_name(f"panel_B_{value:g}.png"))
        from PyQt5.QtGui import QPixmap
        pic = QLabel()
        pm = QPixmap(str(img))
        pm.setDevicePixelRatio(SCALE)
        pic.setPixmap(pm)
        lay.addWidget(pic)
        # The most severe message is the one that decides the indicator.
        lines = [l for l in tip.splitlines() if l and tip != 'Parameter is valid']
        worst = next((l for l in lines if l.startswith(('ERROR', 'CRITICAL'))),
                     lines[0] if lines else '')
        cap = QLabel(f"<i>{ANGIO_PARAM} = {value:g}: {caption}</i>"
                     + (f"<br><span style='color:#555'>{worst}</span>" if worst else ''))
        cap.setWordWrap(True)
        cap.setFixedWidth(PANEL_WIDTH)
        lay.addWidget(cap)
    path.with_suffix('.json').write_text(json.dumps(tooltips, indent=2, ensure_ascii=False),
                                         encoding='utf-8')
    return _grab(host, path)


def panel_c(gui, win, path):
    from schema_utils import get_full_parameter_info
    info = get_full_parameter_info(win.schema, ANGIO_PARAM)
    dlg = gui.main_window.ParameterInfoDialog(ANGIO_PARAM, info, win.display_names, win)
    html = dlg._generate_html(ANGIO_PARAM, info, win.display_names)
    head = f"<h2 style='margin:0'>{info.get('_display_name')}</h2>"
    ont = info.get('_ontology_term')
    if ont:
        head += f"<div><b>Ontology term:</b> {ont}</div>"
    return _html_panel(head + _sections(html, PANEL_C_SECTIONS), path)


def panel_d(schema, path):
    from vivarium_angio.utils.parameter_audit import build_parameter_audit
    params = {k: v['_default'] for k, v in schema['inputs'].items()
              if isinstance(v, dict) and '_default' in v}
    params[ANGIO_PARAM] = AUDIT_VALUE
    e = build_parameter_audit(schema, params)['parameters'][ANGIO_PARAM]
    phys = (e.get('range_evidence') or {}).get('physiological') or {}
    record = {ANGIO_PARAM: {
        'value': e['value'], 'default': e['default'], 'unit': e['unit'],
        'changed_from_default': e['changed_from_default'],
        'ranges': e['ranges'], 'position': e['position'],
        'credibility': e['credibility'],
        'range_evidence': {'physiological': {
            'basis': phys.get('basis'),
            'refs': [r.get('key') for r in phys.get('refs') or []],
        }},
    }}
    text = json.dumps(record, indent=2, ensure_ascii=False)
    # Keep each range / position on one line, as a reader would scan them.
    import re
    text = re.sub(r'\[\s+([^\[\]]+?)\s+\]', lambda m: '[' + ' '.join(m.group(1).split()) + ']', text)
    path.with_suffix('.json').write_text(text + '\n', encoding='utf-8')
    from html import escape
    return _html_panel(f"<div style='color:#555'>parameter_audit.json (abridged) — "
                       f"run with {ANGIO_PARAM} = {AUDIT_VALUE:g}</div>"
                       f"<pre style=\"{MONO}\">{escape(text)}</pre>", path, wrap=False)


def panel_e(gui, win, path):
    from schema_utils import get_full_parameter_info
    info = get_full_parameter_info(win.schema, VCORNEA_PARAM)
    dlg = gui.main_window.ParameterInfoDialog(VCORNEA_PARAM, info, win.display_names, win)
    html = dlg._generate_html(VCORNEA_PARAM, info, win.display_names)
    try:
        from equation_render import CACHE_DIR
        paths = [CACHE_DIR]
    except Exception:
        paths = []
    head = (f"<h2 style='margin:0'>{info.get('_display_name')} "
            f"<span style='font-size:small;color:#555'>(V-Cornea)</span></h2>")
    return _html_panel(head + _sections(html, PANEL_E_SECTIONS), path, paths)


# ---------------------------------------------------------------- assembly
def _window(gui, tmp):
    """A main window as the operator would have it, laid out but never shown."""
    from harness import quiet_dialogs
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    import pytest
    mp = pytest.MonkeyPatch()
    quiet_dialogs(mp, gui, tmp)          # no modal dialog, no subprocess, no browser
    win = gui.window_class()
    win.settings_file = tmp / '.gui_settings.json'
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()                           # activates layouts; nothing appears on screen
    QApplication.processEvents()
    return win, mp


def assemble(panels, out_png, out_pdf):
    """Compose the panels at their native pixel size, so every panel keeps the
    same text scale (no panel is shrunk to fit a grid cell).

    Layout:  A | B      (A spans two rows on the left)
             A | C
             D | E
    """
    from PIL import Image, ImageDraw, ImageFont
    im = {k: Image.open(p).convert('RGB') for k, p in panels.items()}
    gap, label_h = 30 * SCALE // 3, 40 * SCALE // 3
    left_w = max(im['A'].width, im['D'].width)
    right_w = max(im['B'].width, im['C'].width, im['E'].width)
    top_h = max(im['A'].height, im['B'].height + label_h + gap + im['C'].height)
    bottom_h = max(im['D'].height, im['E'].height)
    W = left_w + gap + right_w + 2 * gap
    H = gap + label_h + top_h + gap + label_h + bottom_h + gap
    fig = Image.new('RGB', (W, H), 'white')
    draw = ImageDraw.Draw(fig)
    try:
        font = ImageFont.truetype('arialbd.ttf', 34 * SCALE // 3)
    except OSError:
        font = ImageFont.load_default()
    x_l, x_r = gap, gap + left_w + gap
    y_top = gap + label_h
    y_c = y_top + im['B'].height + gap + label_h
    y_bottom = gap + label_h + top_h + gap + label_h
    slots = {'A': (x_l, y_top), 'B': (x_r, y_top), 'C': (x_r, y_c),
             'D': (x_l, y_bottom), 'E': (x_r, y_bottom)}
    for k, (x, y) in slots.items():
        fig.paste(im[k], (x, y))
        draw.text((x, y - label_h), k, fill='black', font=font)
    fig.save(out_png, dpi=(100 * SCALE, 100 * SCALE))
    fig.save(out_pdf, resolution=100 * SCALE)


CAPTION = """**Figure 2. One parameter definition, several consumers.**
(A) Abridged process-schema entry for VEGF diffusion in Angio-GUI
(`AngiogenesisProcess.ports_schema()`); each range tier carries its own evidentiary
basis. (B) The control generated from it, at three values: inside every declared
range; outside the evidence-supported range (an extrapolation warning); and outside
the implementation-admissible range (an error; launching a run with it requires the
operator's explicit confirmation). (C) The in-context
information panel rendered from the same entry. (D) The corresponding entry in the
run's parameter-audit record for a run with `vedir = {audit_value:g}`, classifying the
value against each tier. (E) The same format in V-Cornea (`EGF_SUPERDiffCoef`): the
declared dimension drives conversion between the stored simulator value and the
operator-facing value, and the panel shows the literal `Parameters.py` assignment and
the governing equation. All panels were generated from schema fingerprints
`{angio_fp}` (Angio-GUI) and `{vcornea_fp}` (V-Cornea).
"""


def main():
    import tempfile
    import traceback
    from harness import load_gui
    # PyQt5 aborts the process on an exception raised inside a Qt slot unless an
    # excepthook is installed; print it instead so a failure is diagnosable.
    sys.excepthook = lambda *exc: traceback.print_exception(*exc)
    app = _qapp()   # keep a reference: a collected QApplication aborts the first widget  # noqa: F841
    tmp = Path(tempfile.mkdtemp(prefix='figure2_'))
    panels = {k: HERE / f"panel_{k}.png" for k in 'ABCDE'}

    angio = load_gui('angio')
    win, mp = _window(angio, tmp)
    from vivarium_angio.utils.provenance import schema_fingerprint
    angio_fp = schema_fingerprint(win.schema)
    win.expertise_combo.setCurrentText('Intermediate')   # vedir is an intermediate parameter
    panel_a(win.schema, panels['A'])
    panel_b(win, panels['B'])
    panel_c(angio, win, panels['C'])
    panel_d(win.schema, panels['D'])
    win.close(); mp.undo()

    vc = load_gui('vcornea')
    vwin, mp = _window(vc, tmp)
    from vivarium_vcornea.utils.provenance import schema_fingerprint as vfp
    vcornea_fp = vfp(vwin.schema)
    panel_e(vc, vwin, panels['E'])
    vwin.close(); mp.undo()

    assemble(panels, HERE / 'figure2.png', HERE / 'figure2.pdf')
    (HERE / 'caption.md').write_text(
        CAPTION.format(audit_value=AUDIT_VALUE, angio_fp=angio_fp, vcornea_fp=vcornea_fp),
        encoding='utf-8')
    for p in sorted(HERE.glob('*')):
        if p.suffix in ('.png', '.pdf', '.md', '.json', '.txt'):
            print(f"wrote {p.name}")


if __name__ == '__main__':
    main()
