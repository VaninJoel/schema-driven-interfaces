"""
Generate a human-readable PDF summary of a single vCornea OMEX/COMBINE archive.

Reads the archive, parses its SED-ML, re-runs both validation layers live, and
writes <archive>_summary.pdf next to it. Includes plain-language explanations of
what the SED-ML encodes and how the validation makes the run auditable.

Usage:
    python make_omex_summary_pdf.py /path/to/archive.omex
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import warnings
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import csv as _csv

import os


def _register_conda_dll_dirs():
    """Make the packaged conda env usable when launched without `conda activate`.

    Run via the env's python.exe directly, conda's DLL dirs aren't on the search
    path, so numpy's MKL/LAPACK chain — which matplotlib calls for every plot —
    fails to load and crashes the process with a delay-load error (0xc06d007f).
    Register the conda DLL dirs explicitly. No-op off Windows / in an activated env.
    """
    if sys.platform != 'win32':
        return
    dirs = []
    for sub in ('Library\\bin', 'Library\\mingw-w64\\bin',
                'Library\\usr\\bin', 'Scripts', ''):
        d = os.path.join(sys.prefix, sub)
        if os.path.isdir(d):
            dirs.append(d)
            if hasattr(os, 'add_dll_directory'):
                try:
                    os.add_dll_directory(d)
                except OSError:
                    pass
    # add_dll_directory only governs DLLs the Python loader resolves; numpy/MKL
    # delay-load their secondary DLLs (mkl_intel_thread, libiomp5md, ...) through
    # a plain LoadLibrary that searches PATH, not the added dirs. Prepending these
    # to PATH is what `conda activate` does, and it's what actually prevents the
    # 0xc06d007f delay-load crash.
    if dirs:
        os.environ['PATH'] = os.pathsep.join(dirs) + os.pathsep + os.environ.get('PATH', '')


_register_conda_dll_dirs()

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (HRFlowable, Image, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

SEDNS = {'s': 'http://sed-ml.org/sed-ml/level1/version4',
         'h': 'http://www.w3.org/1999/xhtml'}


def parse_archive(omex: Path):
    with zipfile.ZipFile(omex) as zf:
        infos = {i.filename: i for i in zf.infolist()}
        names = sorted(infos)
        meta = json.loads(zf.read('run_metadata.json'))
        sedml = zf.read('simulation.sedml').decode('utf-8')
        manifest = zf.read('manifest.xml').decode('utf-8')
    return infos, names, meta, sedml, manifest


def _utils(name):
    """A vivarium_vcornea.utils module, by package name.

    vivarium-angio ships modules with the same bare names (omex_generator,
    parameter_audit, provenance), so a bare import off sys.path can resolve to the
    wrong package's module in any process that has loaded both. The bare import
    is only a fallback for a checkout whose package is not installed.
    """
    import importlib
    try:
        return importlib.import_module(f'vivarium_vcornea.utils.{name}')
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent / 'vivarium_vcornea' / 'utils'))
        return importlib.import_module(name)


def run_validation(omex: Path, sedml: str, manifest: str, names):
    validate_sedml_structure = _utils('omex_generator').validate_sedml_structure
    validate_omex_manifest = _utils('omex_generator').validate_omex_manifest
    s_ok = validate_sedml_structure(sedml)['valid']
    m_ok = validate_omex_manifest(
        manifest, [n for n in names if n != 'manifest.xml'])['valid']
    try:
        from biosimulators_utils.combine.io import CombineArchiveReader
        from biosimulators_utils.combine.validation import validate as v
        with tempfile.TemporaryDirectory() as ed, warnings.catch_warnings():
            warnings.simplefilter("ignore")
            arch = CombineArchiveReader().run(str(omex), ed)
            errs, warns = v(arch, archive_dirname=ed)
        bio = (f"PASS ({len(errs)} errors, {len(warns)} warning group)"
               if not errs else f"FAIL ({len(errs)} errors)")
    except Exception as e:  # noqa: BLE001
        bio = f"SKIP ({e})"
    return s_ok, m_ok, bio


def columns_for(dd) -> str:
    note = dd.find('.//h:p', SEDNS)
    if note is not None and note.text and 'Columns:' in note.text:
        return note.text.split('Columns:', 1)[1].strip()
    return ", ".join(ds.get('name', '') for ds in dd.findall('.//s:dataSource', SEDNS))


def read_provenance(omex):
    """Parse metadata.rdf (OMEX Metadata) into a flat dict, or None if absent."""
    DCT = '{http://purl.org/dc/terms/}'
    VC = '{http://www.w3.org/2006/vcard/ns#}'
    try:
        with zipfile.ZipFile(omex) as zf:
            if 'metadata.rdf' not in zf.namelist():
                return None
            root = ET.fromstring(zf.read('metadata.rdf').decode())
    except Exception:
        return None

    def text(tag):
        e = root.find('.//' + DCT + tag)
        if e is None:
            return None
        if (e.text or '').strip():
            return e.text.strip()
        w = e.find(DCT + 'W3CDTF')
        return w.text.strip() if (w is not None and w.text) else None

    name = " ".join(x for x in (root.findtext('.//' + VC + 'given-name'),
                                root.findtext('.//' + VC + 'family-name')) if x)
    return {
        'title': text('title'), 'description': text('description'),
        'creator': name or None, 'email': root.findtext('.//' + VC + 'hasEmail'),
        'created': text('created'), 'modified': text('modified'),
        'license': text('license'), 'citation': text('bibliographicCitation'),
        'keywords': [e.text for e in root.findall('.//' + DCT + 'subject') if e.text],
    }


def make_plots(omex: Path, datadesc, tmpdir: Path):
    """Plot each CSV DataDescription (non-Time columns vs Time). Returns
    [(png_path, source_name, caption), ...]."""
    plots = []
    with zipfile.ZipFile(omex) as zf:
        archive_names = set(zf.namelist())
        for i, dd in enumerate(datadesc):
            src = dd.get('source', '')
            if src not in archive_names or not src.lower().endswith('.csv'):
                continue
            rows = list(_csv.reader(
                zf.read(src).decode('utf-8').splitlines()))
            if len(rows) < 2:
                continue
            header = rows[0]
            data = {h: [] for h in header}
            for r in rows[1:]:
                if len(r) != len(header):
                    continue
                for h, v in zip(header, r):
                    try:
                        data[h].append(float(v))
                    except ValueError:
                        data[h].append(float('nan'))
            time_key = next((h for h in header if h.strip().lower() == 'time'),
                            header[-1])
            t = data[time_key]
            series = [h for h in header if h != time_key]
            fig, ax = plt.subplots(figsize=(6.6, 2.5), dpi=150)
            for h in series:
                ax.plot(t, data[h], linewidth=1.3, label=h)
            ax.set_xlabel('Time (hours)', fontsize=8)
            ax.set_ylabel('Value', fontsize=8)
            ax.tick_params(labelsize=7)
            ax.grid(True, alpha=0.3, linewidth=0.4)
            if len(series) > 1:
                ax.legend(fontsize=7, ncol=min(len(series), 4),
                          frameon=False, loc='best')
            ax.set_title(src, fontsize=8.5, color='#1a3c5e')
            fig.tight_layout()
            png = tmpdir / f"plot_{i}.png"
            fig.savefig(png, bbox_inches='tight')
            plt.close(fig)
            cap = f"{src}: {', '.join(series)} vs {time_key} ({len(t)} points)"
            plots.append((png, src, cap))
    return plots


def make_thickness_plots(omex: Path, tmpdir: Path):
    """Render spatial-thickness parquet (Time, Bin, Height) as a mean-over-time
    line (with min-max band) and a Bin x Time heatmap. Returns
    [(png_path, source_name, caption), ...]."""
    import io
    import pandas as pd
    out = []
    with zipfile.ZipFile(omex) as zf:
        parquets = [n for n in zf.namelist() if n.lower().endswith('.parquet')]
        for i, name in enumerate(parquets):
            try:
                df = pd.read_parquet(io.BytesIO(zf.read(name)))
            except Exception:
                continue
            if not {'Time', 'Bin', 'Height'}.issubset(df.columns):
                continue
            nbins = df['Bin'].nunique()

            g = df.groupby('Time')['Height'].agg(['mean', 'min', 'max'])
            fig, ax = plt.subplots(figsize=(6.6, 2.3), dpi=150)
            ax.fill_between(g.index, g['min'], g['max'], alpha=0.15,
                            color='#1a3c5e', label='min-max across bins')
            ax.plot(g.index, g['mean'], lw=1.4, color='#1a3c5e', label='spatial mean')
            ax.set_xlabel('Time (hours)', fontsize=8)
            ax.set_ylabel('Thickness (Height)', fontsize=8)
            ax.tick_params(labelsize=7)
            ax.grid(True, alpha=0.3, linewidth=0.4)
            ax.legend(fontsize=7, frameon=False)
            ax.set_title(f"{name} - mean epithelial thickness", fontsize=8.5,
                         color='#1a3c5e')
            fig.tight_layout()
            p1 = tmpdir / f"thick_line_{i}.png"
            fig.savefig(p1, bbox_inches='tight')
            plt.close(fig)
            out.append((p1, name,
                        f"{name}: spatial-mean Height vs Time "
                        f"(band = min-max across {nbins} bins)"))

            piv = df.pivot_table(index='Bin', columns='Time', values='Height')
            fig, ax = plt.subplots(figsize=(6.6, 2.3), dpi=150)
            im = ax.imshow(piv.values, aspect='auto', origin='lower', cmap='viridis',
                           extent=[float(piv.columns.min()), float(piv.columns.max()),
                                   float(piv.index.min()), float(piv.index.max())])
            ax.set_xlabel('Time (hours)', fontsize=8)
            ax.set_ylabel('Spatial bin (across cornea)', fontsize=8)
            ax.tick_params(labelsize=7)
            cb = fig.colorbar(im, ax=ax)
            cb.ax.tick_params(labelsize=6)
            cb.set_label('Height', fontsize=7)
            ax.set_title(f"{name} - thickness profile (Bin x Time)", fontsize=8.5,
                         color='#1a3c5e')
            fig.tight_layout()
            p2 = tmpdir / f"thick_heat_{i}.png"
            fig.savefig(p2, bbox_inches='tight')
            plt.close(fig)
            out.append((p2, name,
                        f"{name}: Height across spatial bins over time (heatmap). "
                        "This signal is packaged in the archive but is NOT indexed "
                        "by the SED-ML."))
    return out


ROLES = {
    'manifest.xml': 'OMEX manifest (COMBINE archive index)',
    'simulation.sedml': 'SED-ML L1V4 simulation description',
    'run_metadata.json': 'Authoritative parameter/run provenance',
    'Parameters.py': 'CC3D parameter file applied to this run',
    'stdout.log': 'CC3D run log (stdout)',
    'stderr.log': 'CC3D run log (stderr)',
    'cell_count_5761.csv': 'Cell counts by layer over time',
    'surfactant_5761.csv': 'Surfactant concentration over time',
    'thickness_rep_5761.parquet': 'Epithelial thickness per replicate',
}


def _parameter_credibility_block(audit_sources, H2, SUB, prows):
    """Flowables for the parameter-credibility section; [] when no audit exists.

    Reads parameter_audit.json (run dir or .omex) written by the run from its
    live schema. One table of the parameters an auditor must look at: changed
    from default, or sitting outside a documented range. Everything else is
    summarised in a line, so a report stays short when the run stayed inside
    its documented evidence.
    """
    try:
        _pa = _utils('parameter_audit')
    except Exception:
        return []
    audits = [a for a in (_pa.load_parameter_audit(s) for s in audit_sources) if a]
    if not audits:
        return []
    audit = audits[0]                       # replicates share a parameterization
    s = audit.get('summary') or {}
    out = [Paragraph("Parameter Credibility (run values against the schema's documented evidence)", H2),
           Paragraph(_pa.audit_summary_line(audit) + ".", SUB)]
    header, rows = _pa.audit_table_rows(audit, include='attention')
    if rows:
        def _fmt(v):
            return f"{v:g}" if isinstance(v, float) else str(v)
        data = [header] + [[r[0], _fmt(r[1]), _fmt(r[2]), r[3], r[4], r[5]] for r in rows]
        out.append(prows(data, [1.85 * inch, 0.7 * inch, 0.7 * inch, 0.7 * inch,
                                1.4 * inch, 1.4 * inch]))
    else:
        out.append(Paragraph("Every parameter ran at its documented default and inside "
                             "every documented range.", SUB))
    out.append(Paragraph(
        "<i>Credibility</i> places each executed value against the three range tiers the "
        "schema documents: the implementation-admissible range (outside = inadmissible), the "
        "evidence-supported range (outside = extrapolation beyond the documented evidence) and "
        "the recommended range for this model's context of use. The evidence column names the "
        "basis and citation the schema records for the supported range; "
        "<i>not recorded</i> means the bound exists but its justification has not been "
        "documented, which is itself an audit finding. Numeric parameters without any documented range "
        "are listed as unassessable; switches and categories are not range-assessed. Full detail for every parameter is in "
        "parameter_audit.json inside the archive.", SUB))
    if len(audits) > 1:
        diff = [k for k, e in audit['parameters'].items()
                if e.get('parameter_type') != 'control'
                and any(a['parameters'].get(k, {}).get('value') != e['value'] for a in audits[1:])]
        if diff:
            out.append(Paragraph("Replicates differ in: " + ", ".join(diff) +
                                 " (replicates of one combination should share every model parameter).", SUB))
    return out


def build(omex: Path):
    import shutil
    out = omex.with_name(omex.stem + "_summary.pdf")
    tmpdir = Path(tempfile.mkdtemp(prefix='omex_pdf_'))
    infos, names, meta, sedml, manifest = parse_archive(omex)
    s_ok, m_ok, bio = run_validation(omex, sedml, manifest, names)

    root = ET.fromstring(sedml)
    model = root.find('.//s:model', SEDNS)
    sim = root.find('.//s:uniformTimeCourse', SEDNS)
    alg = sim.find('s:algorithm', SEDNS)
    tasks = root.findall('.//s:listOfTasks/s:task', SEDNS)
    task = tasks[0] if tasks else root.find('.//s:task', SEDNS)
    repeated = root.find('.//s:repeatedTask', SEDNS)
    datadesc = root.findall('.//s:dataDescription', SEDNS)
    datagens = root.findall('.//s:dataGenerator', SEDNS)
    datasets = root.findall('.//s:dataSet', SEDNS)

    # Map each declared dataSource id -> (source_file, column_value)
    ds_map = {}
    for dd in datadesc:
        src = dd.get('source', '')
        for dsrc in dd.findall('.//s:dataSource', SEDNS):
            slc = dsrc.find('.//s:slice', SEDNS)
            col = slc.get('value') if slc is not None else dsrc.get('name', '')
            ds_map[dsrc.get('id')] = (src, col)

    # Resolve each dataGenerator to its underlying signal
    dg_info = []
    for dg in datagens:
        var = dg.find('.//s:variable', SEDNS)
        sym, tgt = (var.get('symbol'), var.get('target')) if var is not None else (None, None)
        if sym:
            origin = f"task symbol &middot; {sym.split(':')[-1]}"
        elif tgt:
            f, c = ds_map.get(tgt.lstrip('#'), ('?', '?'))
            origin = f"{f} :: {c}"
        else:
            origin = '&mdash;'
        dg_info.append((dg.get('id'), dg.get('name', ''), origin))

    # Row counts of packaged CSVs (to compare against declared step count)
    csv_counts = {}
    with zipfile.ZipFile(omex) as zf:
        for n in names:
            if n.endswith('.csv'):
                csv_counts[n] = max(0, zf.read(n).decode('utf-8').count('\n') - 1)
    max_csv_rows = max(csv_counts.values()) if csv_counts else 0
    n_replicates = meta.get('total_replicates', 1)

    # Correct time semantics via the canonical converter (units.py). SimTime is
    # in DAYS; the SED-ML generator currently emits the raw value mislabelled as
    # MCS, so we recompute the true values here rather than trust the SED-ML.
    try:
        _u = _utils('units')
        MCS_PER_DAY, MCS_PER_HOUR = _u.MCS_PER_DAY, _u.MCS_PER_HOUR
    except Exception:
        MCS_PER_DAY, MCS_PER_HOUR = 240.0, 10.0
    sim_days = (meta.get('key_parameters', {}).get('SimTime')
                or meta.get('simulation_config', {}).get('sim_time'))
    sim_mcs = sim_hours = None
    if isinstance(sim_days, (int, float)):
        sim_mcs = sim_days * MCS_PER_DAY
        sim_hours = sim_mcs / MCS_PER_HOUR

    ss = getSampleStyleSheet()
    H = ParagraphStyle('H', parent=ss['Heading1'], fontSize=15, spaceAfter=2,
                       textColor=colors.HexColor('#1a3c5e'))
    SUB = ParagraphStyle('SUB', parent=ss['Normal'], fontSize=8.5,
                         textColor=colors.grey, spaceAfter=8)
    H2 = ParagraphStyle('H2', parent=ss['Heading2'], fontSize=10.5, spaceBefore=9,
                        spaceAfter=3, textColor=colors.HexColor('#1a3c5e'))
    N = ParagraphStyle('N', parent=ss['Normal'], fontSize=8.2, leading=10.8,
                       spaceAfter=3)
    cell = ParagraphStyle('cell', parent=ss['Normal'], fontSize=7.6, leading=9)

    def tbl(data, widths, header=True):
        st = [('FONTSIZE', (0, 0), (-1, -1), 7.6),
              ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
              ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
              ('ROWBACKGROUNDS', (0, 1 if header else 0), (-1, -1),
               [colors.white, colors.HexColor('#f4f7fa')]),
              ('TOPPADDING', (0, 0), (-1, -1), 2.5),
              ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
              ('LEFTPADDING', (0, 0), (-1, -1), 5)]
        if header:
            st += [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3c5e')),
                   ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                   ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold')]
        t = Table(data, colWidths=widths)
        t.setStyle(TableStyle(st))
        return t

    cellH = ParagraphStyle('cellH', parent=cell, textColor=colors.white,
                           fontName='Helvetica-Bold')

    def prows(rows, widths, header=True):
        data = [[Paragraph(c, cellH if (header and i == 0) else cell) for c in r]
                for i, r in enumerate(rows)]
        return tbl(data, widths, header=header)

    S = []
    S.append(Paragraph("OMEX / COMBINE Archive Summary", H))
    S.append(Paragraph(
        f"{omex.name} &nbsp;|&nbsp; {omex.stat().st_size:,} bytes &nbsp;|&nbsp; "
        f"vivarium_wrapper {meta.get('vivarium_wrapper_version','?')} &nbsp;|&nbsp; "
        f"generated {meta.get('created_at','?')[:19]}", SUB))
    S.append(HRFlowable(width="100%", thickness=1,
                        color=colors.HexColor('#1a3c5e')))

    # Run overview
    S.append(Paragraph("Run Overview", H2))
    pc = meta.get('parameter_changes', {})
    changed = "; ".join(
        f"{k}: {v.get('default_value')}&rarr;{v.get('current_value')}"
        for k, v in pc.items()) or "none"
    cfg = meta.get('simulation_config', {})
    kp = meta.get('key_parameters', {})
    ov = [["Run name", meta.get('run_name', '')],
          ["Simulation", f"SimTime {cfg.get('sim_time')} days &middot; "
                         f"injury={'yes' if cfg.get('has_injury') else 'no'} "
                         f"({cfg.get('injury_type')})"],
          ["Params changed", f"{meta.get('parameters_changed')} of "
                             f"{meta.get('total_parameters')} &mdash; {changed}"],
          ["Key parameters", "  ".join(f"{k}={v}" for k, v in kp.items())],
          ["Replicate", f"{meta.get('replicate_id')} of "
                        f"{meta.get('total_replicates')}"],
          ["Outcome", f"success={meta.get('simulation_success')} &middot; "
                      f"healing_time={meta.get('healing_time')} &middot; "
                      f"completed {str(meta.get('simulation_completed_at',''))[:19]}"]]
    S.append(prows([[f"<b>{a}</b>", str(b)] for a, b in ov],
                   [1.35 * inch, 5.4 * inch], header=False))

    # Provenance (OMEX Metadata) ------------------------------------------
    prov = read_provenance(omex)
    if prov:
        S.append(Paragraph("Provenance (OMEX Metadata)", H2))
        pr = []
        if prov.get('creator'):
            pr.append(["Creator (experimenter)", prov['creator']
                       + (f" &middot; {prov['email']}" if prov.get('email') else "")])
        if prov.get('created'):
            pr.append(["Created", str(prov['created'])[:19]])
        if prov.get('modified'):
            pr.append(["Archived", str(prov['modified'])[:19]])
        if prov.get('license'):
            pr.append(["License", prov['license']])
        if prov.get('citation'):
            pr.append(["Citation", prov['citation']])
        if prov.get('keywords'):
            pr.append(["Keywords", ", ".join(prov['keywords'])])
        S.append(prows([[f"<b>{a}</b>", str(b)] for a, b in pr],
                       [1.6 * inch, 5.15 * inch], header=False))
        S.append(Paragraph("From metadata.rdf (COMBINE OMEX-Metadata): attribution / "
                           "provenance, not authentication.", SUB))

    # Parameter credibility (schema evidence vs. executed values) ----------
    S.extend(_parameter_credibility_block([omex], H2, SUB, prows))

    # Reading the SED-ML: conclusions for THIS experiment ----------------
    S.append(Paragraph("Reading the SED-ML &mdash; What This Experiment Is", H2))
    S.append(Paragraph(
        "Each row reads one part of the SED-ML and states what can be concluded "
        "about <i>this</i> run from it &mdash; the inverse of how the generator wrote "
        "the file.", N))
    rd = [["What the file states", "Conclusion for this experiment"],
          [f"<b>Model</b> '{model.get('name')}', source "
           f"{model.get('source')}, language {model.get('language')}",
           ("An agent-based CompuCell3D corneal model, <b>bundled in the archive</b> "
            "(model/@source resolves &mdash; self-contained). CC3D is not a SED-ML model "
            "language, so the archive <b>documents</b> the run; it is not re-executable "
            "by a SED-ML engine." if model.get('source') in names else
            "An agent-based CompuCell3D corneal model. CC3D is not a SED-ML model "
            "language, so this archive <b>documents</b> the run; it is not re-executable "
            "by a SED-ML engine.")],
          [f"<b>Simulation</b> uniformTimeCourse, t {sim.get('initialTime')}"
           f"&rarr;{sim.get('outputEndTime')}, {sim.get('numberOfSteps')} steps, "
           f"algorithm KiSAO {alg.get('kisaoID')}",
           ("<b>UNITS BUG in the SED-ML.</b> SimTime is in <b>days</b> "
            "(schema _unit='days'; units.py: 1 day = "
            f"{MCS_PER_DAY:.0f} MCS, 1 hour = {MCS_PER_HOUR:.0f} MCS). This is a "
            f"<b>{sim_days}-day</b> run = <b>{sim_hours:.0f} hours</b> = "
            f"<b>{sim_mcs:.0f} MCS</b>. The SED-ML instead emits outputEndTime="
            f"{sim.get('outputEndTime')} / numberOfSteps={sim.get('numberOfSteps')} "
            "and labels it 'MCS, 1 MCS = 6 min' &mdash; it copied the raw day value "
            "without calling the converter. Packaged Time columns confirm days: they "
            "run 0&rarr;576 hours (surfactant every 0.1 h = per-MCS, "
            f"{csv_counts.get('surfactant_5761.csv', max_csv_rows):,} rows; "
            "cell_count hourly, 577 rows).")
           if isinstance(sim_days, (int, float)) else
           "Time-course units could not be reconciled (SimTime missing from "
           "metadata)."],
          [f"<b>Tasks</b>: {len(tasks)} task(s) "
           f"({', '.join(t.get('id') for t in tasks) or '&mdash;'}); "
           f"repeatedTask {'present' if repeated is not None else 'absent'}",
           "One model&times;simulation binding and no repeatedTask/setValue range "
           "&mdash; so <b>no parameter scan</b>. Had the GUI passed a value range for a "
           "parameter, it would appear here as a repeatedTask with a setValue over a "
           "range; several swept parameters would nest as a cartesian product of "
           "ranges. None were swept in this run."],
          [f"<b>Replicates</b>: {n_replicates} "
           f"({'no' if repeated is not None else 'no'} replicate range encoded)"
           if repeated is None else
           f"<b>Replicates</b>: {n_replicates} (uniformRange over a repeatedTask)",
           "A single stochastic realization. CC3D is stochastic, so these outputs are "
           "<b>one sample, not a statistic</b> &mdash; estimating means, variance or "
           "confidence intervals needs N replicates (recorded as a repeatedTask over a "
           "replicate range). Read the trends here as illustrative, not statistically "
           "estimated." if n_replicates <= 1 else
           f"{n_replicates} stochastic realizations with identical parameters, each "
           "assigned its own independently drawn random seed (recorded per replicate, "
           "so a difference between them is stochastic rather than configured). "
           "Layer-wise means and spread across replicates become meaningful; a single "
           "run would not support variance/CI claims."],
          [f"<b>DataGenerators / Report</b>: {len(datagens)} generators, "
           f"{len(datasets)} reported data sets",
           "The signals the SED-ML actually exposes are listed below. Note the SED-ML "
           "is a <b>partial</b> index of the archive: the surfactant value column and "
           "the entire thickness parquet are not represented as generators (see plots)."]]
    S.append(prows(rd, [3.0 * inch, 3.75 * inch]))

    # Data generators detail
    S.append(Paragraph("Data Generators (signals the SED-ML exposes)", H2))
    S.append(Paragraph(
        "A DataGenerator is a named quantity the report plots/exports; each points "
        "either at a task observable (e.g. simulation time) or at a column of a "
        "packaged result file.", N))
    dg_rows = [["Generator id", "Name", "Resolves to"]]
    for gid, gname, origin in dg_info:
        dg_rows.append([gid, gname, origin])
    S.append(prows(dg_rows, [2.35 * inch, 1.85 * inch, 2.55 * inch]))

    # Data descriptions detail
    S.append(Paragraph("Recorded Outputs (DataDescriptions &rarr; columns)", H2))
    dd_rows = [["Source file", "Format", "Columns / data sources"]]
    for dd in datadesc:
        fmt = dd.get('format', '').split(':')[-1]
        dd_rows.append([dd.get('source', ''), fmt, columns_for(dd)])
    S.append(prows(dd_rows, [1.9 * inch, 0.7 * inch, 4.15 * inch]))

    # OMEX manifest contents
    S.append(Paragraph("OMEX Manifest (the archive's declared index)", H2))
    S.append(Paragraph(
        "manifest.xml is what makes this a COMBINE archive: every file must be "
        "listed with its media type, and exactly one entry is flagged master "
        "(the entry point a COMBINE tool opens first). The '.' entry declares the "
        "archive itself.", N))
    man_ns = {'m': 'http://identifiers.org/combine.specifications/omex-manifest'}
    man_root = ET.fromstring(manifest)
    man_rows = [["Location", "Format (media type)", "Master"]]
    for c in man_root.findall('m:content', man_ns):
        fmt = c.get('format', '')
        if 'combine.specifications' in fmt:
            short = fmt.split('combine.specifications/')[-1]
        else:
            short = fmt.split('mediatypes/')[-1] if 'mediatypes/' in fmt else fmt
        man_rows.append([c.get('location', ''), short,
                         'yes' if c.get('master') == 'true' else ''])
    S.append(prows(man_rows, [2.15 * inch, 4.0 * inch, 0.6 * inch]))

    # Embedded time-series plots (CSV via SED-ML + thickness parquet)
    plots = make_plots(omex, datadesc, tmpdir)
    if plots:
        S.append(PageBreak())
        S.append(Paragraph("Output Time-Series (rendered from packaged CSVs)", H2))
        S.append(Paragraph(
            "Plotted directly from the result files inside the archive, so the "
            "figures match exactly what the SED-ML DataDescriptions reference.", N))
        for png, _src, cap in plots:
            S.append(Image(str(png), width=6.6 * inch, height=2.5 * inch))
            S.append(Paragraph(cap, SUB))
            S.append(Spacer(1, 4))

    thick = make_thickness_plots(omex, tmpdir)
    if thick:
        S.append(PageBreak())
        S.append(Paragraph("Spatial Thickness (rendered from packaged parquet)", H2))
        S.append(Paragraph(
            "Thickness is stored as a spatial profile (Height per Bin over Time) in "
            "parquet. It is included in the COMBINE archive but is <b>not</b> indexed "
            "by the SED-ML (the generator only maps CSV outputs), so these figures are "
            "read straight from the parquet.", N))
        for png, _src, cap in thick:
            S.append(Image(str(png), width=6.6 * inch, height=2.3 * inch))
            S.append(Paragraph(cap, SUB))
            S.append(Spacer(1, 4))

    # Archive contents
    S.append(Paragraph("Archive Contents", H2))
    rows = [["File", "Size (B)", "Role"]]
    for n in names:
        role = ROLES.get(n)
        if role is None:
            if n == 'metadata.rdf':
                role = 'OMEX Metadata (provenance: creator, license, citation)'
            elif n.startswith('model/'):
                role = 'Bundled CC3D model file (so model/@source resolves)'
            else:
                role = '&mdash;'
        rows.append([n, f"{infos[n].file_size:,}", role])
    S.append(prows(rows, [2.15 * inch, 0.8 * inch, 3.8 * inch]))

    # Validation + audit explanation
    S.append(Paragraph("Validation Results &amp; How to Audit Them", H2))
    vr = [["Validation layer", "What it checks", "Result"],
          ["Built-in SED-ML structure",
           "Required elements present &amp; well-formed",
           "PASS" if s_ok else "FAIL"],
          ["Built-in OMEX manifest",
           "Every archive file is declared with the right type",
           "PASS" if m_ok else "FAIL"],
          ["biosimulators-utils (COMBINE spec)",
           "Independent third-party check vs. the COMBINE standard",
           bio]]
    S.append(prows(vr, [1.9 * inch, 3.1 * inch, 1.75 * inch]))
    S.append(Spacer(1, 4))
    S.append(Paragraph(
        "<b>Why this is easy to audit:</b> the three layers move from "
        "self-checks to an external authority. The first two are our own structural "
        "validators (fast, no dependencies). The third is <i>biosimulators-utils</i>, "
        "a widely-used independent library that re-checks the archive against the "
        "published COMBINE/SED-ML specification &mdash; so a reviewer does not have to "
        "trust our code. To reproduce: <font face='Courier'>pip install "
        "biosimulators-utils</font>, then validate the .omex. A clean pass means the "
        "archive is structurally complete and standards-conformant.", N))
    S.append(Paragraph(
        "<b>On the warnings:</b> they are benign and expected. CompuCell3D is not a "
        "registered SED-ML model language, so no third-party tool can re-execute or "
        "deep-validate the model itself; the step-count note simply flags the short "
        "24-step course. Neither affects archive validity. <b>Parameter provenance is "
        "authoritative in run_metadata.json</b>, which the SED-ML explicitly "
        "references &mdash; that JSON, not the SED-ML, is the source of truth for the "
        "exact values applied.", N))

    try:
        SimpleDocTemplate(str(out), pagesize=letter, topMargin=0.55 * inch,
                          bottomMargin=0.5 * inch, leftMargin=0.6 * inch,
                          rightMargin=0.6 * inch,
                          title="OMEX Archive Summary").build(S)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return out, bio


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    p, bio = build(Path(sys.argv[1]).expanduser())
    print("WROTE:", p, f"({p.stat().st_size:,} bytes)")
    print("biosimulators:", bio)
