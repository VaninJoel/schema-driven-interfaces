"""Per-combination PDF report built ONLY from the OMEX archives.

Same OMEX-internal style as make_omex_summary_pdf.py (archive contents, SED-ML
readout, validation), but aggregated over a combination's per-replicate archives:
when a combo has multiple replicate_*/*.omex, the time-series plots overlay each
replicate plus the across-replicate mean. Nothing is read from loose run folders —
only from inside the .omex files.

Usage:
    python make_omex_combo_report.py <experiment_dir>     # one report per combo
    python make_omex_combo_report.py <combo_dir>          # a single combo
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import warnings
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import os


def _register_conda_dll_dirs():
    """Make the packaged conda env usable when launched without `conda activate`.

    Run via the env's python.exe directly (as the GUI launches this reporter),
    conda's DLL dirs aren't on the search path, so numpy's MKL/LAPACK chain —
    which matplotlib calls for every plot — fails to load and crashes the process
    with a delay-load error (0xc06d007f). Register the conda DLL dirs explicitly.
    No-op off Windows or in an already-activated env.
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

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (HRFlowable, Image, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

# Reuse the liked single-archive tool's helpers so the look is identical.
from make_omex_summary_pdf import (parse_archive, run_validation, columns_for,
                                    ROLES, SEDNS, read_provenance as _read_provenance)

# Import the generator (by filename, so the package __init__/vivarium chain is not
# triggered) to (re)build the experiment scan.omex before reporting on it.
sys.path.insert(0, str((Path(__file__).resolve().parent / 'vivarium_vcornea' / 'utils')))
try:
    import omex_generator as _og
except Exception:  # noqa: BLE001
    _og = None

CELL_COLORS = {'Superficial': '#55ffff', 'Wing': '#0055ff',
               'Basal': '#ffbe99', 'Stem': '#ff007f'}


# --------------------------------------------------------------- discovery
def _is_per_run(omex: Path) -> bool:
    try:
        with zipfile.ZipFile(omex) as zf:
            n = set(zf.namelist())
        return 'run_metadata.json' in n and 'simulation.sedml' in n
    except Exception:
        return False


def _combo_key(omex: Path) -> str:
    """Combo = dir above replicate_*/, else the archive's parent dir."""
    p = omex.parent
    return p.parent.name if p.name.startswith('replicate_') else p.name


def discover_combos(root: Path) -> dict:
    """Return {combo_key: [per-run omex paths]} found under root (recursively)."""
    combos: dict = {}
    for omex in sorted(root.rglob('*.omex')):
        if not _is_per_run(omex):     # skip the experiment-level *_scan.omex
            continue
        combos.setdefault(_combo_key(omex), []).append(omex)
    return combos


# --------------------------------------------------------------- data access
def _read_table(omex: Path, name: str):
    with zipfile.ZipFile(omex) as zf:
        b = zf.read(name)
    return (pd.read_parquet(io.BytesIO(b)) if name.endswith('.parquet')
            else pd.read_csv(io.BytesIO(b)))


def _find_name(names, prefix, ext):
    return next((n for n in names if Path(n).name.startswith(prefix)
                 and n.endswith(ext)), None)


# _read_provenance is imported from make_omex_summary_pdf (single source of truth).


# --------------------------------------------------------------- plots (replicate-aware)
def _time_key(df):
    return next((c for c in df.columns if str(c).strip().lower() == 'time'),
                df.columns[-1])


def make_csv_plots(reps, tmpdir):
    """reps: list of (label, omex, names). One figure per CSV signal, overlaying
    every replicate (thin) plus the across-replicate mean (bold)."""
    out = []
    # signals present in the first replicate that carries them
    signals = []
    for prefix in ('cell_count', 'surfactant'):
        for _, omex, names in reps:
            if _find_name(names, prefix, '.csv'):
                signals.append(prefix)
                break
    for idx, prefix in enumerate(signals):
        # collect each replicate's df
        dfs = []
        for label, omex, names in reps:
            nm = _find_name(names, prefix, '.csv')
            if not nm:
                continue
            try:
                dfs.append((label, _read_table(omex, nm)))
            except Exception:
                continue
        if not dfs:
            continue
        tk = _time_key(dfs[0][1])
        cols = [c for c in dfs[0][1].columns if c != tk]
        palette = [CELL_COLORS.get(c) for c in cols]
        fig, ax = plt.subplots(figsize=(6.7, 2.7), dpi=150)
        # per-replicate thin traces
        for label, df in dfs:
            for c, col in zip(cols, palette):
                ax.plot(df[tk], df[c], color=col, alpha=0.28, lw=0.7)
        # across-replicate mean per column (aligned on Time)
        for c, col in zip(cols, palette):
            series = [df[[tk, c]].rename(columns={c: 'v'}).set_index(tk)['v']
                      for _, df in dfs]
            merged = pd.concat(series, axis=1)         # always a DataFrame
            mean = merged.mean(axis=1)                  # = the single trace if 1 replicate
            ax.plot(mean.index, mean.values, color=col, lw=1.8, label=f"{c} (mean)")
        ax.set_xlabel('Time (hours)', fontsize=8)
        ax.set_ylabel('Value', fontsize=8)
        ax.tick_params(labelsize=7)
        ax.grid(True, alpha=0.3, lw=0.4)
        ax.legend(fontsize=7, ncol=min(len(cols), 4), frameon=False, loc='best')
        ax.set_title(f"{prefix} — mean (bold) and {len(dfs)} replicate(s) (thin)",
                     fontsize=8.5, color='#1a3c5e')
        fig.tight_layout()
        png = tmpdir / f"csv_{idx}.png"
        fig.savefig(png, bbox_inches='tight')
        plt.close(fig)
        out.append((png, f"{prefix}: {', '.join(cols)} vs Time — "
                    f"{len(dfs)} replicate(s), bold = across-replicate mean"))
    return out


def make_thickness_plots(reps, tmpdir):
    """Spatial-mean thickness over time (per replicate + mean) and a Bin×Time
    heatmap of the replicate-averaged Height."""
    dfs = []
    for label, omex, names in reps:
        nm = _find_name(names, 'thickness', '.parquet')
        if not nm:
            continue
        try:
            df = _read_table(omex, nm)
        except Exception:
            continue
        if {'Time', 'Bin', 'Height'}.issubset(df.columns):
            dfs.append((label, df))
    if not dfs:
        return []
    out = []
    # spatial-mean Height vs Time, per replicate + across-replicate mean
    fig, ax = plt.subplots(figsize=(6.7, 2.5), dpi=150)
    per_rep_means = []
    for label, df in dfs:
        g = df.groupby('Time')['Height'].mean()
        ax.plot(g.index, g.values, alpha=0.3, lw=0.8, color='#1a3c5e')
        per_rep_means.append(g)
    allm = pd.concat(per_rep_means, axis=1)
    ax.plot(allm.index, allm.mean(axis=1).values, color='#1a3c5e', lw=1.8,
            label=f"mean across {len(dfs)} replicate(s)")
    ax.set_xlabel('Time (hours)', fontsize=8)
    ax.set_ylabel('Spatial-mean Height', fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(True, alpha=0.3, lw=0.4)
    ax.legend(fontsize=7, frameon=False)
    ax.set_title("thickness — spatial-mean Height vs Time", fontsize=8.5, color='#1a3c5e')
    fig.tight_layout()
    p1 = tmpdir / "thick_line.png"
    fig.savefig(p1, bbox_inches='tight'); plt.close(fig)
    out.append((p1, f"thickness: spatial-mean Height vs Time — {len(dfs)} replicate(s), "
                "bold = across-replicate mean"))

    # heatmap of replicate-averaged Height (Bin × Time)
    cat = pd.concat([df for _, df in dfs], ignore_index=True)
    piv = cat.groupby(['Bin', 'Time'])['Height'].mean().unstack('Time')
    fig, ax = plt.subplots(figsize=(6.7, 2.5), dpi=150)
    im = ax.imshow(piv.values, aspect='auto', origin='lower', cmap='viridis',
                   extent=[float(piv.columns.min()), float(piv.columns.max()),
                           float(piv.index.min()), float(piv.index.max())])
    ax.set_xlabel('Time (hours)', fontsize=8)
    ax.set_ylabel('Spatial bin', fontsize=8)
    ax.tick_params(labelsize=7)
    cb = fig.colorbar(im, ax=ax); cb.ax.tick_params(labelsize=6); cb.set_label('Height', fontsize=7)
    ax.set_title("thickness — replicate-averaged Height (Bin × Time)",
                 fontsize=8.5, color='#1a3c5e')
    fig.tight_layout()
    p2 = tmpdir / "thick_heat.png"
    fig.savefig(p2, bbox_inches='tight'); plt.close(fig)
    out.append((p2, "thickness: replicate-averaged Height across spatial bins over "
                "time (heatmap). Packaged in the archive but NOT indexed by the SED-ML."))
    return out


# --------------------------------------------------------------- report
def build_combo_report(combo_key, omex_paths, out_pdf):
    import shutil
    tmpdir = Path(tempfile.mkdtemp(prefix='omex_combo_'))

    # Parse every replicate archive; order by replicate_id when present.
    reps = []   # (label, omex, names, meta, sedml, manifest)
    for omex in omex_paths:
        infos, names, meta, sedml, manifest = parse_archive(omex)
        rid = meta.get('replicate_id')
        reps.append((rid, omex, names, meta, sedml, manifest))
    reps.sort(key=lambda r: (r[0] is None, r[0]))
    labels = [f"replicate_{r[0]}" if r[0] is not None else r[1].parent.name for r in reps]
    rep_plot_in = [(labels[i], reps[i][1], reps[i][2]) for i in range(len(reps))]

    rep0 = reps[0]
    _, omex0, names0, meta0, sedml0, manifest0 = rep0

    # Validate every replicate (built-in + biosimulators).
    val = []
    for (rid, omex, names, meta, sedml, manifest) in reps:
        s_ok, m_ok, bio = run_validation(omex, sedml, manifest, names)
        val.append((rid, s_ok, m_ok, bio))

    # SED-ML facts from the representative archive.
    root = ET.fromstring(sedml0)
    model = root.find('.//s:model', SEDNS)
    sim = root.find('.//s:uniformTimeCourse', SEDNS)
    alg = sim.find('s:algorithm', SEDNS)
    repeated = root.find('.//s:repeatedTask', SEDNS)
    datadesc = root.findall('.//s:dataDescription', SEDNS)
    datagens = root.findall('.//s:dataGenerator', SEDNS)

    n_replicates = meta0.get('total_replicates', len(reps))
    scan_point = meta0.get('scan_point') or {}
    combo_idx = meta0.get('combination_index')
    total_combos = meta0.get('total_combinations')
    cfg = meta0.get('simulation_config', {})

    try:
        sys.path.insert(0, str((Path(__file__).resolve().parent /
                                'vivarium_vcornea' / 'utils')))
        from units import MCS_PER_DAY, MCS_PER_HOUR
    except Exception:
        MCS_PER_DAY, MCS_PER_HOUR = 240.0, 10.0
    sim_days = (meta0.get('key_parameters', {}).get('SimTime') or cfg.get('sim_time'))
    sim_mcs = sim_hours = None
    if isinstance(sim_days, (int, float)):
        sim_mcs = sim_days * MCS_PER_DAY
        sim_hours = sim_mcs / MCS_PER_HOUR

    combo_label = (", ".join(f"{k}={v}" for k, v in scan_point.items())
                   or combo_key)

    # ---- styles (identical to make_omex_summary_pdf) ----
    ss = getSampleStyleSheet()
    H = ParagraphStyle('H', parent=ss['Heading1'], fontSize=15, spaceAfter=2,
                       textColor=colors.HexColor('#1a3c5e'))
    SUB = ParagraphStyle('SUB', parent=ss['Normal'], fontSize=8.5,
                         textColor=colors.grey, spaceAfter=8)
    H2 = ParagraphStyle('H2', parent=ss['Heading2'], fontSize=10.5, spaceBefore=9,
                        spaceAfter=3, textColor=colors.HexColor('#1a3c5e'))
    N = ParagraphStyle('N', parent=ss['Normal'], fontSize=8.2, leading=10.8, spaceAfter=3)
    cell = ParagraphStyle('cell', parent=ss['Normal'], fontSize=7.6, leading=9)

    def tbl(data, widths, header=True):
        st = [('FONTSIZE', (0, 0), (-1, -1), 7.6), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
              ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
              ('ROWBACKGROUNDS', (0, 1 if header else 0), (-1, -1),
               [colors.white, colors.HexColor('#f4f7fa')]),
              ('TOPPADDING', (0, 0), (-1, -1), 2.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
              ('LEFTPADDING', (0, 0), (-1, -1), 5)]
        if header:
            st += [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3c5e')),
                   ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                   ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold')]
        t = Table(data, colWidths=widths); t.setStyle(TableStyle(st)); return t

    cellH = ParagraphStyle('cellH', parent=cell, textColor=colors.white,
                           fontName='Helvetica-Bold')

    def prows(rows, widths, header=True):
        data = [[Paragraph(c, cellH if (header and i == 0) else cell) for c in r]
                for i, r in enumerate(rows)]
        return tbl(data, widths, header=header)

    S = []
    S.append(Paragraph(f"OMEX Combination Report — {combo_label}", H))
    pos = f" (point {combo_idx} of {total_combos})" if combo_idx and total_combos else ""
    S.append(Paragraph(
        f"{combo_key}{pos} &nbsp;|&nbsp; {len(reps)} replicate archive(s) &nbsp;|&nbsp; "
        f"vivarium_wrapper {meta0.get('vivarium_wrapper_version','?')}", SUB))
    S.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#1a3c5e')))

    # Combination overview
    S.append(Paragraph("Combination Overview", H2))
    ov = [["Scan point", combo_label + (pos if pos else "")],
          ["Simulation",
           (f"SimTime {sim_days} days (= {sim_mcs:g} MCS = {sim_hours:g} hours) &middot; "
            if sim_mcs else "") +
           f"injury={'yes' if cfg.get('has_injury') else 'no'} ({cfg.get('injury_type')})"],
          ["Replicates", f"{n_replicates} (this report aggregates {len(reps)} archive(s); "
                         "plots show each replicate plus the across-replicate mean)"]]
    S.append(prows([[f"<b>{a}</b>", b] for a, b in ov], [1.4 * inch, 5.35 * inch], header=False))

    # How replicates are represented in the OMEX (the reference the run gives us)
    S.append(Paragraph("How Replicates Appear in the OMEX", H2))
    S.append(Paragraph(
        "Each replicate is packaged as its OWN per-run .omex (under "
        "<i>replicate_N/</i>), carrying only that replicate's data and a "
        "<i>replicate_id</i> / <i>total_replicates</i> in run_metadata.json. The "
        "per-replicate SED-ML declares a replicate <i>repeatedTask</i> over a "
        f"uniformRange (1..{n_replicates}) "
        + ("[present]" if repeated is not None else "[absent]") +
        " — i.e. it documents the N-replicate design even though each archive holds "
        "one replicate. This report reads all replicate archives of the combination "
        "and aggregates them.", N))
    rv = [["Replicate", "run_metadata", "built-in SED-ML", "manifest", "biosimulators"]]
    for (rid, s_ok, m_ok, bio) in val:
        rv.append([f"replicate_{rid}" if rid is not None else "?",
                   f"id {rid} of {n_replicates}",
                   "PASS" if s_ok else "FAIL", "PASS" if m_ok else "FAIL", bio])
    S.append(prows(rv, [1.1 * inch, 1.4 * inch, 1.25 * inch, 1.0 * inch, 2.0 * inch]))

    # Provenance (OMEX Metadata) — who ran it, license, citation
    prov = _read_provenance(omex0)
    if prov:
        S.append(Paragraph("Provenance (OMEX Metadata)", H2))
        pr = [["Field", "Value"]]
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
        S.append(prows(pr, [1.6 * inch, 5.15 * inch]))
        S.append(Paragraph("From metadata.rdf (COMBINE OMEX-Metadata). The creator is "
                           "attribution/provenance, not authentication.", SUB))

    model_bundled = model.get('source') in names0
    # SED-ML readout (representative)
    S.append(Paragraph("Reading the SED-ML (representative replicate)", H2))
    rd = [["What the file states", "Conclusion"],
          [f"<b>Model</b> {model.get('source')} &middot; {model.get('language')}",
           ("Agent-based CC3D model, <b>bundled in the archive</b> so model/@source "
            "resolves (self-contained); still descriptive, not re-executable by a "
            "SED-ML engine." if model_bundled else
            "Agent-based CompuCell3D model; descriptive (not re-executable by a SED-ML engine).")],
          [f"<b>Simulation</b> uniformTimeCourse 0&rarr;{sim.get('outputEndTime')}, "
           f"{sim.get('numberOfSteps')} steps, KiSAO {alg.get('kisaoID')}",
           (f"{sim_days}-day run = {sim_hours:g} h = {sim_mcs:g} MCS "
            "(time course is in MCS)." if sim_mcs else "Time course in MCS.")],
          [f"<b>Replicates</b> repeatedTask {'present' if repeated is not None else 'absent'}, "
           f"total_replicates={n_replicates}",
           "Stochastic replicates; means/spread across replicates are meaningful "
           f"(this report uses {len(reps)})."],
          [f"<b>DataGenerators</b>: {len(datagens)}; dataDescriptions: {len(datadesc)}",
           "Signals the SED-ML indexes; thickness parquet is packaged but not indexed."]]
    S.append(prows(rd, [3.2 * inch, 3.55 * inch]))

    # Recorded outputs (representative)
    S.append(Paragraph("Recorded Outputs (DataDescriptions &rarr; columns)", H2))
    dd_rows = [["Source file", "Format", "Columns"]]
    for dd in datadesc:
        dd_rows.append([dd.get('source', ''), dd.get('format', '').split(':')[-1],
                        columns_for(dd)])
    S.append(prows(dd_rows, [1.9 * inch, 0.7 * inch, 4.15 * inch]))

    # Replicate-aware plots
    csv_plots = make_csv_plots(rep_plot_in, tmpdir)
    thick_plots = make_thickness_plots(rep_plot_in, tmpdir)
    if csv_plots or thick_plots:
        S.append(PageBreak())
        S.append(Paragraph("Results (replicate-aware, from the packaged data)", H2))
        S.append(Paragraph(
            f"Plotted from the CSV/parquet inside the {len(reps)} replicate archive(s). "
            "Thin lines are individual replicates; the bold line is the across-replicate "
            "mean. Time is shown in hours (as stored in the data).", N))
        for png, cap in csv_plots + thick_plots:
            S.append(Image(str(png), width=6.7 * inch, height=2.6 * inch))
            S.append(Paragraph(cap, SUB))
            S.append(Spacer(1, 4))

    # Archive contents (representative)
    S.append(Paragraph("Archive Contents (per replicate)", H2))
    rows = [["File", "Size (B)", "Role"]]
    with zipfile.ZipFile(omex0) as zf:
        infos0 = {i.filename: i for i in zf.infolist()}
    for n in sorted(names0):
        role = ROLES.get(n, ROLES.get(Path(n).name))
        if role is None:
            if n == 'metadata.rdf':
                role = 'OMEX Metadata (provenance: creator, license, citation)'
            elif n.startswith('model/'):
                role = 'Bundled CC3D model file (so model/@source resolves)'
            else:
                role = '&mdash;'
        rows.append([n, f"{infos0[n].file_size:,}", role])
    S.append(prows(rows, [2.15 * inch, 0.8 * inch, 3.8 * inch]))
    S.append(Paragraph(f"Each of the {len(reps)} replicate archives has this same layout.", SUB))

    try:
        SimpleDocTemplate(str(out_pdf), pagesize=letter, topMargin=0.55 * inch,
                          bottomMargin=0.5 * inch, leftMargin=0.6 * inch,
                          rightMargin=0.6 * inch,
                          title=f"OMEX Combination Report {combo_key}").build(S)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return Path(out_pdf)


def _combo_metric_frames(omex_paths):
    """Replicate-MEAN frames for a combo's metrics, read from its per-run OMEX.
    Returns {'cell_count': df(Time index + cols), 'surfactant': df, 'thickness':
    df('Height')} (whichever are present), plus (label, reps, sim_days, inj_days,
    has_injury) from the run metadata."""
    cc, surf, thick = [], [], []
    label = reps = sim_days = inj_days = None
    has_injury = False
    for omex in omex_paths:
        with zipfile.ZipFile(omex) as zf:
            names = zf.namelist()
            if 'run_metadata.json' not in names:
                continue
            if label is None:
                m = json.loads(zf.read('run_metadata.json'))
                sp = m.get('scan_point') or {}
                label = ", ".join(f"{k}={v}" for k, v in sp.items()) or omex.parent.parent.name
                reps = m.get('total_replicates', len(omex_paths))
                cfg = m.get('simulation_config', {})
                has_injury = bool(cfg.get('has_injury'))
                sim_days = m.get('key_parameters', {}).get('SimTime') or cfg.get('sim_time')
                inj_days = m.get('key_parameters', {}).get('InjuryTime')
            cn = _find_name(names, 'cell_count', '.csv')
            sn = _find_name(names, 'surfactant', '.csv')
            tn = _find_name(names, 'thickness', '.parquet')
            if cn:
                d = pd.read_csv(io.BytesIO(zf.read(cn)))
                cc.append(d.rename(columns={_time_key(d): 'Time'}).set_index('Time'))
            if sn:
                d = pd.read_csv(io.BytesIO(zf.read(sn)))
                surf.append(d.rename(columns={_time_key(d): 'Time'}).set_index('Time'))
            if tn:
                d = pd.read_parquet(io.BytesIO(zf.read(tn)))
                if {'Time', 'Height'}.issubset(d.columns):
                    thick.append(d.groupby('Time')['Height'].mean().to_frame('Height'))
    frames = {}
    if cc:
        frames['cell_count'] = pd.concat(cc).groupby(level=0).mean(numeric_only=True)
    if surf:
        frames['surfactant'] = pd.concat(surf).groupby(level=0).mean(numeric_only=True)
    if thick:
        frames['thickness'] = pd.concat(thick).groupby(level=0).mean(numeric_only=True)
    return frames, label, reps, sim_days, inj_days, has_injury


def build_experiment_report(root, combos, out_pdf):
    """Cross-combination comparison PDF (OMEX-internal): one line per combo for
    each cell type, surfactant, and mean thickness, plus a summary metrics table."""
    import shutil
    tmpdir = Path(tempfile.mkdtemp(prefix='omex_exp_'))

    data = {}            # combo_key -> dict(frames,label,reps)
    inj_hours = sim_days = None
    has_injury = False
    for ck, paths in combos.items():
        frames, label, reps, sd, idays, hinj = _combo_metric_frames(paths)
        data[ck] = {'frames': frames, 'label': label or ck, 'reps': reps or len(paths)}
        sim_days = sim_days or sd
        if hinj and idays is not None:
            inj_hours = idays * 24.0
            has_injury = True

    cmap = plt.get_cmap('tab10')
    order = list(data.keys())
    colors_by = {ck: cmap(i % 10) for i, ck in enumerate(order)}

    def line_plot(metric, col, ylabel, title, fname):
        present = [(ck, data[ck]['frames'][metric]) for ck in order
                   if metric in data[ck]['frames'] and col in data[ck]['frames'][metric].columns]
        if not present:
            return None
        fig, ax = plt.subplots(figsize=(6.7, 2.7), dpi=150)
        for ck, fr in present:
            ax.plot(fr.index, fr[col], lw=1.7, color=colors_by[ck], label=data[ck]['label'])
        if has_injury and inj_hours:
            ax.axvline(inj_hours, color='red', ls='--', lw=1, alpha=0.7, label='injury')
        ax.set_xlabel('Time (hours)', fontsize=8); ax.set_ylabel(ylabel, fontsize=8)
        ax.tick_params(labelsize=7); ax.grid(True, alpha=0.3, lw=0.4)
        ax.legend(fontsize=7, frameon=False)
        ax.set_title(title, fontsize=8.5, color='#1a3c5e')
        fig.tight_layout(); p = tmpdir / fname; fig.savefig(p, bbox_inches='tight'); plt.close(fig)
        return p

    plots = []
    for ct in ['Superficial', 'Wing', 'Basal', 'Stem']:
        p = line_plot('cell_count', ct, 'Cell count', f"{ct} cells across combinations",
                      f"cc_{ct}.png")
        if p:
            plots.append((p, f"{ct}: replicate-mean count per combination vs Time"))
    p = line_plot('surfactant', 'Total Amount', 'Total amount',
                  "Surfactant across combinations", "surf.png")
    if p:
        plots.append((p, "Surfactant Total Amount: replicate-mean per combination vs Time"))
    p = line_plot('thickness', 'Height', 'Spatial-mean Height',
                  "Mean thickness across combinations", "thick.png")
    if p:
        plots.append((p, "Thickness (spatial-mean Height): replicate-mean per combination vs Time"))

    # summary metrics table (computed from the replicate-mean series)
    def metrics(ck):
        f = data[ck]['frames']
        cc = f.get('cell_count'); su = f.get('surfactant'); th = f.get('thickness')
        wing0 = wing_min = wing_end = None
        if cc is not None and 'Wing' in cc:
            w = cc['Wing']
            if has_injury and inj_hours:
                pre = w[w.index < inj_hours]; post = w[w.index >= inj_hours]
                wing0 = pre.mean() if len(pre) else w.iloc[0]
                wing_min = post.min() if len(post) else w.min()
            else:
                wing0 = w.iloc[0]; wing_min = w.min()
            wing_end = w.iloc[-1]
        peak_surf = su['Total Amount'].max() if (su is not None and 'Total Amount' in su) else None
        min_h = th['Height'].min() if (th is not None and 'Height' in th) else None
        rec = (wing_end / wing0 * 100) if (wing0 and wing_end is not None and wing0) else None
        return wing0, wing_min, wing_end, rec, peak_surf, min_h

    ss = getSampleStyleSheet()
    H = ParagraphStyle('H', parent=ss['Heading1'], fontSize=15, spaceAfter=2,
                       textColor=colors.HexColor('#1a3c5e'))
    SUB = ParagraphStyle('SUB', parent=ss['Normal'], fontSize=8.5, textColor=colors.grey, spaceAfter=8)
    H2 = ParagraphStyle('H2', parent=ss['Heading2'], fontSize=10.5, spaceBefore=9, spaceAfter=3,
                        textColor=colors.HexColor('#1a3c5e'))
    N = ParagraphStyle('N', parent=ss['Normal'], fontSize=8.2, leading=10.8, spaceAfter=3)
    cell = ParagraphStyle('cell', parent=ss['Normal'], fontSize=7.6, leading=9)

    def prows(rows, widths, header=True):
        st = [('FONTSIZE', (0, 0), (-1, -1), 7.6), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
              ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
              ('ROWBACKGROUNDS', (0, 1 if header else 0), (-1, -1), [colors.white, colors.HexColor('#f4f7fa')]),
              ('TOPPADDING', (0, 0), (-1, -1), 2.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
              ('LEFTPADDING', (0, 0), (-1, -1), 5)]
        if header:
            st += [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3c5e')),
                   ('TEXTCOLOR', (0, 0), (-1, 0), colors.white), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold')]
        cellH = ParagraphStyle('cellH', parent=cell, textColor=colors.white,
                               fontName='Helvetica-Bold')
        t = Table([[Paragraph(c, cellH if (header and i == 0) else cell) for c in r]
                   for i, r in enumerate(rows)], colWidths=widths)
        t.setStyle(TableStyle(st)); return t

    def fmt(x):
        return f"{x:.1f}" if isinstance(x, (int, float)) else "—"

    S = []
    S.append(Paragraph(f"OMEX Experiment Report — {root.name}", H))
    S.append(Paragraph(
        f"{len(order)} combinations &nbsp;|&nbsp; "
        f"{', '.join(str(data[ck]['reps']) for ck in order)} replicate(s) each &nbsp;|&nbsp; "
        f"SimTime {sim_days} days &nbsp;|&nbsp; "
        + ("injury at day %s" % (inj_hours / 24.0) if has_injury and inj_hours else "no injury"), SUB))
    S.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#1a3c5e')))

    # --- OMEX-internal sections: this PDF is a report OF the experiment scan.omex,
    #     mirroring how the per-combo PDFs report each combination's archives. ---
    def _has_meta(p):
        try:
            with zipfile.ZipFile(p) as zf:
                return 'metadata.rdf' in zf.namelist()
        except Exception:
            return False
    scans = list(root.glob('*_scan.omex'))
    # Prefer a metadata-bearing archive, then the most recent.
    scans.sort(key=lambda p: (_has_meta(p), p.stat().st_mtime))
    scan_omex = scans[-1] if scans else None
    if scan_omex is not None:
        with zipfile.ZipFile(scan_omex) as zf:
            snames = zf.namelist()
            sm = json.loads(zf.read('scan_metadata.json')) if 'scan_metadata.json' in snames else {}
            sed = zf.read('scan.sedml').decode() if 'scan.sedml' in snames else ''
            man = zf.read('manifest.xml').decode() if 'manifest.xml' in snames else ''
            sinfo = {n: zf.getinfo(n).file_size for n in snames}
        s_ok, m_ok, bio = run_validation(scan_omex, sed, man, snames)
        rootel = ET.fromstring(sed) if sed else None

        S.append(Paragraph("Experiment Archive", H2))
        S.append(Paragraph(
            f"This report describes the experiment-level archive <b>{scan_omex.name}</b> "
            f"({scan_omex.stat().st_size:,} bytes) — the SED-ML/COMBINE description of "
            "the whole scan. The per-combination reports describe each combination's "
            "per-replicate archives; this one sits above them and compares the combos.", N))
        ov = [["Parameter scan", "; ".join(f"{k} &isin; {v}" for k, v in
                                            (sm.get('parameter_scan') or {}).items()) or "&mdash;"],
              ["Scan points", str(sm.get('total_scan_points'))],
              ["Replicates / point", str(sm.get('replicates_per_point'))],
              ["Total simulations", str(sm.get('total_simulations'))]]
        S.append(prows([[f"<b>{a}</b>", b] for a, b in ov], [1.7 * inch, 5.05 * inch], header=False))

        S.append(Paragraph("Experiment OMEX Contents", H2))
        crows = [["File", "Size (B)"]] + [[n, f"{sinfo[n]:,}"] for n in sorted(snames)]
        S.append(prows(crows, [4.8 * inch, 1.95 * inch]))

        if rootel is not None:
            ns = {'s': SEDNS['s']}
            plots2d = rootel.findall('.//s:plot2D', ns)
            dds = rootel.findall('.//s:dataDescription', ns)
            dsets = rootel.findall('.//s:report//s:dataSet', ns)
            S.append(Paragraph("Reading the SED-ML (comparison)", H2))
            S.append(Paragraph(
                f"scan.sedml encodes the scan as a repeatedTask AND compares the "
                f"combinations: {len(dds)} dataDescriptions (one per combo &times; metric, "
                f"bundled under combo_data/) feed {len(plots2d)} plot2D outputs — each "
                f"overlays the combinations for one signal — and a {len(dsets)}-series report.", N))
            prow = [["plot2D (signal across combinations)", "curves (= combinations)"]]
            for pl in plots2d:
                prow.append([pl.get('name', ''), str(len(pl.findall('.//s:curve', ns)))])
            S.append(prows(prow, [5.0 * inch, 1.75 * inch]))

        prov = _read_provenance(scan_omex)
        if prov:
            S.append(Paragraph("Provenance (OMEX Metadata)", H2))
            pr = [["Field", "Value"]]
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
            S.append(prows(pr, [1.6 * inch, 5.05 * inch]))
            S.append(Paragraph("From metadata.rdf in the scan archive: attribution / "
                               "provenance, not authentication.", SUB))

        S.append(Paragraph("Validation of the Experiment Archive", H2))
        vr = [["Layer", "Result"],
              ["Built-in SED-ML structure", "PASS" if s_ok else "FAIL"],
              ["Built-in OMEX manifest", "PASS" if m_ok else "FAIL"],
              ["biosimulators-utils (COMBINE)", bio]]
        S.append(prows(vr, [3.3 * inch, 3.45 * inch]))
        S.append(PageBreak())

    S.append(Paragraph("Combinations", H2))
    S.append(prows([["Combination", "Label", "Replicates"]] +
                   [[ck, data[ck]['label'], str(data[ck]['reps'])] for ck in order],
                   [2.2 * inch, 3.35 * inch, 1.2 * inch]))

    S.append(Paragraph("Summary Metrics (from replicate-mean series)", H2))
    mrows = [["Combination", "Wing baseline", "Wing min", "Wing final", "Recovery %",
              "Peak surfactant", "Min mean-Height"]]
    for ck in order:
        w0, wmin, wend, rec, ps, mh = metrics(ck)
        mrows.append([data[ck]['label'], fmt(w0), fmt(wmin), fmt(wend), fmt(rec), fmt(ps), fmt(mh)])
    S.append(prows(mrows, [1.9 * inch] + [0.81 * inch] * 6))
    S.append(Paragraph(
        "Wing baseline = pre-injury mean; Wing min = minimum after injury (damage depth); "
        "Recovery % = final / baseline. Metrics are on the across-replicate mean.", SUB))

    if plots:
        S.append(PageBreak())
        S.append(Paragraph("Metric Comparisons (one line per combination)", H2))
        S.append(Paragraph(
            "Each line is a combination's across-replicate mean, read from the per-run "
            "OMEX archives. Time in hours; the dashed red line marks injury.", N))
        for png, cap in plots:
            S.append(Image(str(png), width=6.7 * inch, height=2.7 * inch))
            S.append(Paragraph(cap, SUB)); S.append(Spacer(1, 4))

    try:
        SimpleDocTemplate(str(out_pdf), pagesize=letter, topMargin=0.55 * inch,
                          bottomMargin=0.5 * inch, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                          title=f"OMEX Experiment Comparison {root.name}").build(S)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return Path(out_pdf)


def _ensure_scan_archive(path, combos):
    """Build the experiment scan.omex (comparison SED-ML) from the per-run OMEX
    metadata IF one doesn't already exist. The GUI normally writes scan.omex itself
    (with the creator) in finalize_batch, so we must NOT overwrite it here. Best-effort."""
    if _og is None:
        return
    if any(path.glob('*_scan.omex')):   # keep the GUI-written archive (has creator)
        return
    import re
    scan_spec = None
    combinations = []
    sim_days = None
    reps = 1
    base_name = None
    for combo_key, omex_paths in combos.items():
        for omex in omex_paths:
            with zipfile.ZipFile(omex) as zf:
                if 'run_metadata.json' not in zf.namelist():
                    continue
                m = json.loads(zf.read('run_metadata.json'))
            scan_spec = scan_spec or m.get('parameter_scan')
            sim_days = sim_days or (m.get('key_parameters', {}).get('SimTime')
                                    or m.get('simulation_config', {}).get('sim_time'))
            reps = max(reps, m.get('total_replicates', 1) or 1)
            # Derive the base run name (drop the _comboNNN suffix) so the standalone
            # archive matches the GUI's naming (<base>_scan.omex), not <folder>_scan.omex.
            base_name = base_name or re.sub(r'_combo\d+$', '', m.get('run_name', '') or '')
            combinations.append({**(m.get('scan_point') or {}),
                                 '_index': m.get('combination_index'), '_folder': combo_key})
            break
    if not scan_spec:
        return
    run_name = base_name or path.name
    try:
        _og.create_experiment_scan_archive(path, scan_spec, combinations,
                                           {'SimTime': sim_days}, run_name=run_name,
                                           num_replicates=reps)
    except Exception as e:  # noqa: BLE001
        print(f"[combo_report] could not (re)generate scan archive: {e}")


def generate(path):
    path = Path(path)
    combos = discover_combos(path)
    if not combos:
        print(f"[combo_report] no per-run .omex archives under {path}")
        return []
    written = []
    for combo_key, omex_paths in combos.items():
        # write the report into the combo folder (next to its replicates)
        out_dir = (path / combo_key) if (path / combo_key).is_dir() else omex_paths[0].parent.parent
        out_pdf = out_dir / f"{combo_key}_omex_report.pdf"
        written.append(build_combo_report(combo_key, omex_paths, out_pdf))
        print(f"[combo_report] wrote {out_pdf}  ({len(omex_paths)} replicate archive(s))")
    # whole-experiment comparison PDF when there is more than one combination
    if len(combos) > 1:
        _ensure_scan_archive(path, combos)   # refresh the comparison scan.omex first
        out_pdf = path / f"{path.name}_experiment_report.pdf"
        written.append(build_experiment_report(path, combos, out_pdf))
        print(f"[combo_report] wrote {out_pdf}  (comparison across {len(combos)} combos)")
    return written


def main(argv=None):
    argv = argv or sys.argv[1:]
    if len(argv) != 1:
        print(__doc__); return 1
    n = len(generate(argv[0]))
    print(f"\nDone — {n} combination report(s) written.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
