"""Build manuscript Figure 2, "One parameter definition, several consumers".

    python docs/figures/figure2/make_figure2.py            # writes into this folder

Every panel is produced from the live code at one commit, so the figure cannot
show anything the software does not do:

  A  abridged Angio-GUI schema entry for VEGF diffusion (`vedir`), printed
     from AngiogenesisProcess.ports_schema() (real field names and values);
  B  the GUI row generated from that entry, rendered at three values: inside
     every range, outside the working range (the run proceeds, recorded), and
     outside the implementation limit (needs the operator's confirmation);
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

# Sizes are in logical pixels. The figure is FIG_W wide and is meant to be printed
# PRINT_WIDTH_CM wide, so one logical pixel is PRINT_WIDTH_CM / FIG_W on paper and
# a font of MIN_FONT_PX comes out at about 7 pt. Nothing is drawn smaller.
FIG_W = 760
PRINT_WIDTH_CM = 17.0
PAD, GAP, LABEL_H = 8, 14, 20
FULL = FIG_W - 2 * PAD              # a panel across the page
HALF = (FULL - GAP) // 2            # a panel in one of two columns
PANEL_WIDTH = HALF
SCALE = 4                           # 3040 px across: about 450 dpi at 17 cm
MIN_FONT_PX = 11                    # 11 px * 17 cm / 760 px = 6.97 pt
BODY_FONT_PX = 12
PT_PER_PX = PRINT_WIDTH_CM / 2.54 * 72 / FIG_W

ANGIO_PARAM = 'vedir'
ANGIO_STATES = [(1.0, 'within the working range and the implementation limit'),
                (3.0, 'outside the working range: the run proceeds and this is recorded'),
                (12.0, 'outside the implementation limit: needs confirmation')]
AUDIT_VALUE = 3.0
VCORNEA_PARAM = 'EGF_SUPERDiffCoef'

# Fields printed in panel A, in this order. Everything else is counted as omitted.
PANEL_A_FIELDS = ['_default', '_display_name', '_expert_level',
                  '_unit', '_dimension', '_mathematical_range', '_physiological_range',
                  '_recommended_range', '_range_evidence', '_ontology_term', '_dependencies',
                  '_expected_behavior', '_reference_paper']
PANEL_A_CHARS = 118        # characters per line that fit the full width at MIN_FONT_PX
PANEL_C_SECTIONS = ['Ranges']
PANEL_E_SECTIONS = ['Units &amp; Conversion', 'Governing Equations']
NOTE_LIMIT = 150           # characters of each range's evidence statement kept in panel C

MONO = f"font-family: Consolas, 'DejaVu Sans Mono', monospace; font-size: {MIN_FONT_PX}px;"
# The dialogs' own HTML, with font sizes pinned so the print size is known.
FIG_CSS = (f"<style>body, p, li, div {{ font-family: Arial, sans-serif; font-size: {BODY_FONT_PX}px; }}"
           f" h2 {{ font-size: 15px; margin: 0; }}"
           f" h3 {{ font-size: 13px; margin-top: 6px; margin-bottom: 2px; }}"
           f" ul {{ margin-top: 0; margin-bottom: 0; margin-left: 0; }}</style>")


def _pin_fonts(html):
    """<small> would come out below the minimum size; give it the minimum. Section
    headings and list indents are sized for a half-width panel."""
    return (html.replace('<small>', f"<span style='font-size:{MIN_FONT_PX}px'>")
                .replace('</small>', '</span>')
                .replace('<h3>', "<h3 style='font-size:13px; margin-top:6px; margin-bottom:2px'>")
                .replace('<ul>', "<ul style='margin-left:-22px; margin-top:0; margin-bottom:0'>"))


H2 = "<h2 style='font-size:15px; margin-top:0; margin-bottom:2px; color:#2c3e50'>"


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


def _html_panel(html, path, search_paths=(), width=FULL):
    """Draw an HTML fragment's whole document into a PNG exactly `width` wide.

    The document is laid out by a QTextBrowser (which resolves images such as the
    rendered equations through its search paths) and drawn in full, so nothing is
    clipped to a viewport. A line that does not fit the width is an error, not a
    silently wider panel.
    """
    from PyQt5.QtGui import QPixmap, QPainter, QColor, QFont
    from PyQt5.QtWidgets import QTextBrowser
    tb = QTextBrowser()
    tb.setSearchPaths([str(p) for p in search_paths])
    font = QFont('Arial')
    font.setPixelSize(BODY_FONT_PX)
    tb.document().setDefaultFont(font)
    tb.document().setDocumentMargin(2)
    tb.setHtml(html)
    doc = tb.document()
    doc.setTextWidth(width)
    assert doc.idealWidth() <= width + 1, (path.name, doc.idealWidth(), width)
    w, h = width, int(doc.size().height()) + 1
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


def _oneline(v, limit):
    """Python-literal rendering on one line, strings longer than `limit` shortened."""
    if isinstance(v, dict):
        return '{' + ', '.join(f"{k!r}: {_oneline(x, limit)}" for k, x in v.items()) + '}'
    if isinstance(v, str):
        return repr(_short(v, limit))
    return repr(v)


def _fit(prefix, v, width_chars):
    """`prefix` + the one-line rendering of v, strings shortened until it fits."""
    for limit in (200, 120, 90, 70, 56, 46, 38, 30, 24, 18):
        line = f"{prefix}{_oneline(v, limit)},"
        if len(line) <= width_chars:
            return line
    return line


# ---------------------------------------------------------------- panels
def panel_a(schema, path):
    """The schema entry, one field per line; long strings are cut with […]."""
    info = schema['inputs'][ANGIO_PARAM]
    chars = PANEL_A_CHARS
    lines = [f"'{ANGIO_PARAM}': {{"]
    for k in PANEL_A_FIELDS:
        if k not in info:
            continue
        v = info[k]
        if k == '_range_evidence':                 # basis / refs / note per tier, a line each
            lines.append(f"    {k!r}: {{")
            for tier, e in v.items():
                if isinstance(e, dict):
                    e = {f: e.get(f) for f in ('basis', 'refs', 'note') if f in e}
                lines.append(_fit(f"        {tier!r}: ", e, chars))
            lines.append("    },")
            continue
        if k == '_reference_paper':                # the provenance of the default
            v = {f: v.get(f) for f in ('source', 'value', 'notes') if f in v}
        lines.append(_fit(f"    {k!r}: ", v, chars))
    omitted = [k for k in info if k not in PANEL_A_FIELDS]
    lines.append(f"    # … {len(omitted)} further fields omitted "
                 f"({', '.join(omitted[:4])}, …)")
    lines.append('}')
    text = '\n'.join(lines)
    (path.with_suffix('.txt')).write_text(text + '\n', encoding='utf-8')
    from html import escape
    return _html_panel(f"<pre style=\"{MONO}\">{escape(text)}</pre>", path)


def panel_b(win, path):
    """The generated row at three values, stacked, each with its verdict."""
    from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
    row = win.param_widgets[ANGIO_PARAM]
    tooltips = []
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    row['container'].setFixedWidth(HALF)           # the real row, laid out one column wide
    from PyQt5.QtWidgets import QApplication
    QApplication.processEvents()
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
        cap = QLabel(f"<span style='font-size:{BODY_FONT_PX}px'><i>{ANGIO_PARAM} = {value:g}: "
                     f"{caption}</i></span>"
                     + (f"<br><span style='color:#444; font-size:{MIN_FONT_PX}px'>{worst}</span>"
                        if worst else ''))
        cap.setWordWrap(True)
        cap.setFixedWidth(PANEL_WIDTH)
        # A word-wrapped label reports a one-line size hint; give it the height
        # its text needs at this width, or the last line is cut off.
        cap.setMinimumHeight(cap.heightForWidth(PANEL_WIDTH) + 6)
        lay.addWidget(cap)
    path.with_suffix('.json').write_text(json.dumps(tooltips, indent=2, ensure_ascii=False),
                                         encoding='utf-8')
    return _grab(host, path)


def _abridge_notes(html):
    """Cut each range's evidence statement (the text under a range) to NOTE_LIMIT
    characters, marked with […]. The statement is the GUI's own; only its length changes."""
    import re

    def shorten(m):
        text = ' '.join(re.sub(r'<[^>]+>', '', m.group(1)).split())
        if len(text) > NOTE_LIMIT:
            text = text[:NOTE_LIMIT].rsplit(' ', 1)[0] + ' […]'
        return f"<small>{text}</small>"
    return re.sub(r'<small>(.*?)</small>', shorten, html, flags=re.S)


def panel_c(gui, win, path):
    from schema_utils import get_full_parameter_info
    info = get_full_parameter_info(win.schema, ANGIO_PARAM)
    dlg = gui.main_window.ParameterInfoDialog(ANGIO_PARAM, info, win.display_names, win)
    html = dlg._generate_html(ANGIO_PARAM, info, win.display_names)
    head = f"{H2}{info.get('_display_name')}</h2>"
    ont = info.get('_ontology_term')
    if ont:
        head += f"<div><b>Ontology term:</b> {ont}</div>"
    body = _pin_fonts(_abridge_notes(_sections(html, PANEL_C_SECTIONS)))
    return _html_panel(body.replace('</style>', '</style>' + FIG_CSS + head, 1), path, width=HALF)


def panel_d(schema, path):
    from vivarium_angio.utils.parameter_audit import build_parameter_audit, credibility_label
    params = {k: v['_default'] for k, v in schema['inputs'].items()
              if isinstance(v, dict) and '_default' in v}
    params[ANGIO_PARAM] = AUDIT_VALUE
    e = build_parameter_audit(schema, params)['parameters'][ANGIO_PARAM]
    phys = (e.get('range_evidence') or {}).get('physiological') or {}
    record = {ANGIO_PARAM: {
        'value': e['value'], 'default': e['default'],
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
    return _html_panel(f"<div style='color:#444; font-size:{MIN_FONT_PX}px'>parameter_audit.json "
                       f"(abridged), {ANGIO_PARAM} = {AUDIT_VALUE:g}. In reports: "
                       f"{escape(credibility_label(e))}</div>"
                       f"<pre style=\"{MONO}\">{escape(text)}</pre>", path, width=HALF)


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
    head = (f"{H2}{info.get('_display_name')} "
            f"<span style='font-size:{BODY_FONT_PX}px;color:#444'>(V-Cornea)</span></h2>")
    body = _sections(html, PANEL_E_SECTIONS)
    # The parameter's assignment in the generated file, from the dialog's own
    # "GUI / Implementation" section.
    import re
    written = re.search(r'<li>Written to.*?</li>', html, flags=re.S)
    if written:
        body = body.replace('<h3>Governing Equations', '<ul>' + written.group(0)
                            + '</ul><h3>Governing Equations', 1)
    body = re.sub(r"<div class='info-item' style='color:#566573'>\s*Other parameters in this "
                  r"equation:.*?</div>", '', body, flags=re.S)
    # An equation image is drawn no wider than the panel.
    body = re.sub(r"(<img [^>]*width=')(\d+)'",
                  lambda m: f"{m.group(1)}{min(int(m.group(2)), HALF - 30)}'", body)
    body = _pin_fonts(body)
    return _html_panel(body.replace('</style>', '</style>' + FIG_CSS + head, 1), path, paths,
                       width=HALF)


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
    """Compose the panels at their native pixel size (no panel is rescaled, so the
    text keeps its print size).

    Layout:  A A      (A across the page)
             B C
             D E
    """
    from PIL import Image, ImageDraw, ImageFont
    im = {k: Image.open(p).convert('RGB') for k, p in panels.items()}
    px = lambda v: int(v * SCALE)
    assert im['A'].width == px(FULL) and all(im[k].width == px(HALF) for k in 'BCDE'), \
        {k: v.size for k, v in im.items()}
    row2 = max(im['B'].height, im['C'].height)
    row3 = max(im['D'].height, im['E'].height)
    W = px(FIG_W)
    H = (px(PAD) + px(LABEL_H) + im['A'].height + px(GAP) + px(LABEL_H) + row2
         + px(GAP) + px(LABEL_H) + row3 + px(PAD))
    fig = Image.new('RGB', (W, H), 'white')
    draw = ImageDraw.Draw(fig)
    try:
        font = ImageFont.truetype('arialbd.ttf', px(14))
    except OSError:
        font = ImageFont.load_default()
    x_l, x_r = px(PAD), px(PAD + HALF + GAP)
    y1 = px(PAD + LABEL_H)
    y2 = y1 + im['A'].height + px(GAP + LABEL_H)
    y3 = y2 + row2 + px(GAP + LABEL_H)
    slots = {'A': (x_l, y1), 'B': (x_l, y2), 'C': (x_r, y2), 'D': (x_l, y3), 'E': (x_r, y3)}
    for k, (x, y) in slots.items():
        fig.paste(im[k], (x, y))
        draw.text((x, y - px(LABEL_H) + px(2)), k, fill='black', font=font)
    dpi = W / (PRINT_WIDTH_CM / 2.54)
    fig.save(out_png, dpi=(dpi, dpi))
    fig.save(out_pdf, resolution=dpi)
    print(f"figure: {W}x{H} px = {PRINT_WIDTH_CM:g} x {H / dpi * 2.54:.1f} cm at {dpi:.0f} dpi; "
          f"smallest text {MIN_FONT_PX} px = {MIN_FONT_PX * PT_PER_PX:.1f} pt, "
          f"body {BODY_FONT_PX} px = {BODY_FONT_PX * PT_PER_PX:.1f} pt; panel heights "
          + ", ".join(f"{k} {v.height // SCALE}" for k, v in im.items()))


CAPTION = """**Figure 2. One parameter definition, several consumers.**
(A) Process-schema entry for VEGF diffusion in Angio-GUI
(`AngiogenesisProcess.ports_schema()`), abridged: long strings are cut at […] and
further fields are omitted as stated in the panel. Each range carries its own basis.
The key names `_physiological_range` and `_mathematical_range` are historical: the
interface shows them as the working range (the values the model is meant to be used
with) and the implementation limit (what the model code can run with). (B) The control
generated from the entry, at three values: within the working range and the
implementation limit; outside the working range (the run proceeds and the finding is
recorded with the basis of the range, here published literature); and outside the
implementation limit (the run starts only after the operator's explicit confirmation,
which is recorded). (C) The ranges section of the in-context information panel rendered
from the same entry, with each range's evidence statement cut at […]; the working range
is labelled physiological because its basis is published literature. (D) The entry for
this parameter in the parameter-audit record of a run with `vedir = {audit_value:g}`
(abridged), giving the position of the value against each range. The machine label
`extrapolation` is the stored form of "outside the documented working range", which is
how reports word it. (E) The same format in V-Cornea (`EGF_SUPERDiffCoef`), from its
information panel: the declared dimension drives conversion between the stored
simulator value and the operator-facing value, and the panel shows the literal
`Parameters.py` assignment and the governing equation. Panels B, C and E are renderings
of the running interfaces and A and D are printed from the running code, at schema
fingerprints `{angio_fp}` (Angio-GUI) and `{vcornea_fp}` (V-Cornea). Text is at least
7 pt when the figure is printed 17 cm wide.
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
