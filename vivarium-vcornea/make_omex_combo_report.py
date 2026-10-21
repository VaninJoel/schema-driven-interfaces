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
from scipy import stats as _spstats

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

# The generator (to (re)build the experiment scan.omex before reporting on it) and
# its sibling utils are imported by package name: vivarium-angio ships modules
# with the same bare names (omex_generator, parameter_audit, provenance), so a bare
# import off sys.path can resolve to the wrong package's module in any process
# that has loaded both. Bare imports remain only as a fallback for a checkout
# whose package is not installed.
_UTILS_DIR = Path(__file__).resolve().parent / 'vivarium_vcornea' / 'utils'
try:
    from vivarium_vcornea.utils import omex_generator as _og
    from vivarium_vcornea.utils import parameter_audit as _parameter_audit
    from vivarium_vcornea.utils.units import MCS_PER_DAY, MCS_PER_HOUR
except ImportError:
    sys.path.insert(0, str(_UTILS_DIR))
    try:
        import omex_generator as _og
    except Exception:  # noqa: BLE001
        _og = None
    try:
        import parameter_audit as _parameter_audit
    except Exception:  # noqa: BLE001
        _parameter_audit = None
    try:
        from units import MCS_PER_DAY, MCS_PER_HOUR
    except Exception:  # noqa: BLE001
        MCS_PER_DAY, MCS_PER_HOUR = 240.0, 10.0

CELL_COLORS = {'Superficial': '#55ffff', 'Wing': '#0055ff',
               'Basal': '#ffbe99', 'Stem': '#ff007f'}


# --------------------------------------------------------------- discovery
def _is_per_run(omex: Path) -> bool:
    """A per-run archive of ANY outcome (the experiment-level *_scan.omex is not).

    Requiring simulation.sedml here used to drop every failed, cancelled and
    timed-out run from the reports without a trace, since those archives
    deliberately omit the executable SED-ML.
    """
    try:
        with zipfile.ZipFile(omex) as zf:
            n = set(zf.namelist())
        return 'run_metadata.json' in n and 'scan_metadata.json' not in n
    except Exception:
        return False


def archive_outcome(omex: Path) -> dict:
    """{'status', 'exit_code', 'error', 'replicate', 'archive'} for one per-run
    archive. status.json is authoritative; an archive that predates it is a
    success iff it carries an executable SED-ML."""
    out = {'status': None, 'exit_code': None, 'error': None,
           'replicate': omex.parent.name, 'archive': omex.name}
    try:
        with zipfile.ZipFile(omex) as zf:
            names = set(zf.namelist())
            doc = json.loads(zf.read('status.json')) if 'status.json' in names else {}
            meta = json.loads(zf.read('run_metadata.json')) if 'run_metadata.json' in names else {}
    except Exception as e:
        return {**out, 'status': 'unreadable', 'error': str(e)}
    out['status'] = doc.get('status') or ('success' if 'simulation.sedml' in names else 'failed')
    out['exit_code'] = doc.get('exit_code', meta.get('exit_code'))
    out['error'] = doc.get('error_message') or meta.get('error_message')
    if meta.get('replicate_id') is not None:
        out['replicate'] = f"replicate_{meta['replicate_id']}"
    return out


def split_by_outcome(omex_paths):
    """(successful archives, [archive_outcome() of every other archive])."""
    ok, other = [], []
    for o in omex_paths:
        outcome = archive_outcome(o)
        if outcome['status'] == 'success':
            ok.append(o)
        else:
            other.append(outcome)
    return ok, other


def _unsuccessful_table_rows(outcomes):
    rows = [["Replicate", "Status", "Exit code", "Error", "Archive"]]
    for oc in outcomes:
        err = (oc.get('error') or '&mdash;').replace('<', '&lt;')
        rows.append([oc['replicate'], f"<b>{oc['status']}</b>",
                     '&mdash;' if oc['exit_code'] is None else str(oc['exit_code']),
                     err[:220] + ('&hellip;' if len(err) > 220 else ''), oc['archive']])
    return rows


_UNSUCCESSFUL_NOTE = (
    "These attempts are part of the experiment record but are excluded from every "
    "plot and metric in this report: their archives carry status.json and no "
    "executable SED-ML, and any partial outputs they hold are not results. Open "
    "the listed archive (logs, parameters, partial outputs) to diagnose them.")


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
        # across-replicate mean ± SD per column (aligned on Time)
        for c, col in zip(cols, palette):
            series = [df[[tk, c]].rename(columns={c: 'v'}).groupby(tk)['v'].mean()
                      for _, df in dfs]
            merged = pd.concat(series, axis=1)         # always a DataFrame
            mean = merged.mean(axis=1)                  # = the single trace if 1 replicate
            line, = ax.plot(mean.index, mean.values, color=col, lw=1.8, label=f"{c} (mean)")
            if len(dfs) > 1:
                sd = merged.std(axis=1)
                ax.fill_between(mean.index, mean - sd, mean + sd, color=line.get_color(),
                                alpha=0.18, lw=0)
        ax.set_xlabel('Time (hours)', fontsize=8)
        ax.set_ylabel('Value', fontsize=8)
        ax.tick_params(labelsize=7)
        ax.grid(True, alpha=0.3, lw=0.4)
        ax.legend(fontsize=7, ncol=min(len(cols), 4), frameon=False, loc='best')
        ax.set_title(f"{prefix} — mean ± SD (n={len(dfs)}) and each replicate (thin)",
                     fontsize=8.5, color='#1a3c5e')
        fig.tight_layout()
        png = tmpdir / f"csv_{idx}.png"
        fig.savefig(png, bbox_inches='tight')
        plt.close(fig)
        out.append((png, f"{prefix}: {', '.join(cols)} vs Time — "
                    f"n = {len(dfs)} replicate(s); bold = across-replicate mean, shaded = "
                    "±1 SD across replicates, thin = individual replicates"))
    return out


# --------------------------------------------------------------- statistics
def _finite(values):
    return [float(x) for x in values if x is not None and np.isfinite(x)]


def _summary(values):
    """(n, mean, SD, 95% CI half-width) of the finite values; NaN where undefined."""
    v = np.asarray(_finite(values))
    n = len(v)
    if n == 0:
        return 0, np.nan, np.nan, np.nan
    sd = v.std(ddof=1) if n > 1 else np.nan
    half = _spstats.t.ppf(0.975, n - 1) * sd / np.sqrt(n) if n > 1 else np.nan
    return n, v.mean(), sd, half


def _kruskal_p(groups):
    """Kruskal–Wallis p across groups of replicate values; None if not testable."""
    g = [v for v in (_finite(grp) for grp in groups) if len(v) >= 2]
    if len(g) < 2:
        return None
    try:
        p = float(_spstats.kruskal(*g).pvalue)
    except ValueError:      # older scipy, every value identical
        return None
    return p if np.isfinite(p) else None    # NaN: every value identical


def _fmt_stat(values, nd=1):
    """'mean ± SD [CI low, CI high]', noting n when some replicates have no value."""
    n, m, sd, half = _summary(values)
    if n == 0:
        return "&mdash;"
    s = f"{m:.{nd}f}"
    if n > 1:
        s += f" &plusmn; {sd:.{nd}f}<br/>[{m - half:.{nd}f}, {m + half:.{nd}f}]"
    return s + (f"<br/>(n={n} of {len(values)})" if n < len(values) else "")


def _fmt_p(p):
    return "&mdash;" if p is None else ("&lt;0.001" if p < 0.001 else f"{p:.3f}")


def _short_labels(labels):
    """Tick labels and axis name: 'SLS_Concentration=1500.0' -> ('1500', 'SLS_Concentration')."""
    parts = [str(l).split('=', 1) for l in labels]
    if all(len(p) == 2 for p in parts) and len({p[0] for p in parts}) == 1:
        def num(v):
            try:
                return f"{float(v):g}"
            except ValueError:
                return v
        return [num(p[1]) for p in parts], parts[0][0]
    return [str(l) for l in labels], ''


def endpoint_plot(panels, labels, colors_by_label, png, ncols=2):
    """panels: [(title, {label: [value per replicate]})]. One panel per endpoint:
    each replicate a dot, the mean with its 95% CI as a black bar, and the
    Kruskal–Wallis p across the combinations in the panel title."""
    rows = -(-len(panels) // ncols)
    fig, axes = plt.subplots(rows, ncols, figsize=(6.7, 2.25 * rows), dpi=150, squeeze=False)
    ticks, xname = _short_labels(labels)
    rng = np.random.default_rng(0)
    for ax, (title, groups) in zip(axes.flat, panels):
        for i, lab in enumerate(labels):
            v = _finite(groups.get(lab, []))
            ax.scatter(i + rng.uniform(-0.1, 0.1, len(v)), v, s=16, alpha=0.75, lw=0,
                       color=colors_by_label[lab], zorder=2)
            n, m, _, half = _summary(v)
            if n:
                ax.errorbar(i + 0.27, m, yerr=None if np.isnan(half) else half, fmt='o',
                            color='black', ms=3.5, capsize=3, lw=1, zorder=3)
        p = _kruskal_p([groups.get(lab, []) for lab in labels])
        ax.set_title(title + (f"\nKruskal–Wallis p = {_fmt_p(p).replace('&lt;', '<')}"
                              if p is not None else ""), fontsize=7.5, color='#1a3c5e')
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(ticks, fontsize=7)
        ax.set_xlim(-0.5, len(labels) - 0.4)
        if xname:
            ax.set_xlabel(xname, fontsize=7)
        ax.tick_params(labelsize=7)
        ax.grid(True, axis='y', alpha=0.3, lw=0.4)
    for ax in list(axes.flat)[len(panels):]:
        ax.axis('off')
    fig.tight_layout()
    fig.savefig(png, bbox_inches='tight')
    plt.close(fig)
    return png


def _gui_analysis():
    """The V-Cornea GUI's own analysis modules (analysis_data, analysis_plots).

    The thickness figures are drawn by the same functions as the GUI's Analyze
    Results > Thickness tab, so the report shows the same quantity, in the same
    units, as the model's analysis: per-X-bin tissue top position, and thickness
    = (top position - membrane baseline) in µm. The GUI ships next to this tool
    (repository checkout and installed payload alike). None if unavailable.
    """
    gui = Path(__file__).resolve().parent.parent / 'vcornea-gui' / 'gui'
    if not (gui / 'analysis_plots.py').exists():
        return None
    # analysis_plots imports analysis_data by bare name; angio-gui has a module
    # of the same name, so make sure the one loaded is V-Cornea's.
    for name in ('analysis_data', 'analysis_plots'):
        mod = sys.modules.get(name)
        if mod is not None and Path(getattr(mod, '__file__', '') or '').parent != gui:
            del sys.modules[name]
    if str(gui) not in sys.path:
        sys.path.insert(0, str(gui))
    try:
        import analysis_data
        import analysis_plots
        return analysis_data, analysis_plots
    except Exception as e:  # noqa: BLE001
        print(f"[combo_report] V-Cornea analysis modules unavailable ({e}); "
              "thickness figures omitted")
        return None


def _thickness_dataset(combos, tmpdir):
    """An analysis_data.AnalysisDataset over the thickness data INSIDE the archives.

    combos: {combo_key: [omex, ...]}. Each archive's thickness parquet and
    run_metadata.json are unpacked to <tmpdir>/<combo>/replicate_<i>/, the layout
    the GUI analyses, so nothing is read from the loose run folders.
    """
    ga = _gui_analysis()
    if ga is None:
        return None, None
    root = Path(tmpdir) / 'thickness_dataset'
    for ck, omex_paths in combos.items():
        for i, omex in enumerate(omex_paths, 1):
            with zipfile.ZipFile(omex) as zf:
                names = zf.namelist()
                tn = _find_name(names, 'thickness', '.parquet')
                if not tn or 'run_metadata.json' not in names:
                    continue
                d = root / ck / f'replicate_{i}'
                d.mkdir(parents=True, exist_ok=True)
                (d / Path(tn).name).write_bytes(zf.read(tn))
                (d / 'run_metadata.json').write_bytes(zf.read('run_metadata.json'))
    if not root.exists():
        return None, None
    ds = ga[0].AnalysisDataset(root)
    return (ds, ga[1]) if ds.thickness_data else (None, None)


def _render(draw, png, size):
    from matplotlib.figure import Figure
    fig = Figure(figsize=size, dpi=150)
    draw(fig)
    fig.tight_layout()
    fig.savefig(png, bbox_inches='tight')
    return png


def make_thickness_plots(reps, tmpdir, combo='combination'):
    """The GUI's thickness views for one combination: the paper figure (Vanin et
    al. 2025, Fig 8) and the limbal vs central thickness over time."""
    ds, ap = _thickness_dataset({combo: [omex for _, omex, _ in reps]}, tmpdir)
    if ds is None:
        return []
    n = len(ds.thickness_data.get(combo, []))
    stable_day = ap._default_stable_day(ds)
    out = []
    p = _render(lambda fig: ap.paper_thickness(fig, ds, combo=combo, unit='days'),
                Path(tmpdir) / 'thick_paper.png', (6.7, 6.4))
    out.append((p, 6.4, (
        "Tissue thickness, drawn by the V-Cornea GUI's own analysis (Analyze Results "
        "&rarr; Thickness, paper view; Vanin et al. 2025, Fig 8). Top: tissue top "
        "position (vertical centre of mass of the top cells) in each of the 10 X-bins "
        f"over time, as the model records it; faint lines are the {n} replicate(s), "
        "solid lines their mean. Bottom: from the stability time (day "
        f"{stable_day:g}) on, top position (blue) and thickness (red) across X; "
        "thickness = (top position &minus; membrane baseline) &times; 2 &micro;m/voxel.")))
    p = _render(lambda fig: ap.enhanced_thickness(fig, ds, unit='days'),
                Path(tmpdir) / 'thick_regions.png', (6.7, 4.6))
    out.append((p, 4.6, (
        "Epithelial thickness in &micro;m over time in the limbus (bin 0) and the "
        f"central/peripheral cornea (bins 4&ndash;9): mean of the {n} replicate(s), "
        "shaded &plusmn;1 SD across replicates (Analyze Results &rarr; Thickness, "
        "comparison view).")))
    return out


# --------------------------------------------------------------- report
def _parameter_credibility_block(audit_sources, H2, SUB, prows):
    """Flowables for the parameter-credibility section; [] when no audit exists.

    Reads parameter_audit.json (run dir or .omex) written by the run from its
    live schema. One table of the parameters an auditor must look at: changed
    from default, or sitting outside a documented range. Everything else is
    summarised in a line, so a report stays short when the run stayed inside
    its documented evidence.
    """
    _pa = _parameter_audit
    if _pa is None:
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


def build_unsuccessful_combo_report(combo_key, outcomes, out_pdf):
    """Report for a combination none of whose attempts succeeded: there is
    nothing to plot, but the attempts must still appear in the record."""
    ss = getSampleStyleSheet()
    H = ParagraphStyle('H', parent=ss['Heading1'], fontSize=15, spaceAfter=2,
                       textColor=colors.HexColor('#1a3c5e'))
    SUB = ParagraphStyle('SUB', parent=ss['Normal'], fontSize=8.5,
                         textColor=colors.grey, spaceAfter=8)
    H2 = ParagraphStyle('H2', parent=ss['Heading2'], fontSize=10.5, spaceBefore=9,
                        spaceAfter=3, textColor=colors.HexColor('#1a3c5e'))
    S = [Paragraph(f"OMEX Combination Report — {combo_key}", H),
         Paragraph(f"No successful replicate: {len(outcomes)} unsuccessful attempt(s).", SUB),
         HRFlowable(width="100%", thickness=1, color=colors.HexColor('#1a3c5e')),
         Paragraph("Unsuccessful Attempts", H2),
         _prows_plain(_unsuccessful_table_rows(outcomes),
                      [0.95 * inch, 0.8 * inch, 0.65 * inch, 2.6 * inch, 1.75 * inch]),
         Paragraph(_UNSUCCESSFUL_NOTE, SUB)]
    SimpleDocTemplate(str(out_pdf), pagesize=letter, topMargin=0.55 * inch,
                      bottomMargin=0.5 * inch, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                      title=f"OMEX Combination Report {combo_key}").build(S)
    return Path(out_pdf)


def _prows_plain(rows, widths):
    """Header-styled table of Paragraph cells (shared by the unsuccessful-run
    sections, which sit outside the builders' local table helpers)."""
    ss = getSampleStyleSheet()
    cell = ParagraphStyle('cell', parent=ss['Normal'], fontSize=7.6, leading=9)
    cellH = ParagraphStyle('cellH', parent=cell, textColor=colors.white, fontName='Helvetica-Bold')
    t = Table([[Paragraph(c, cellH if i == 0 else cell) for c in r] for i, r in enumerate(rows)],
              colWidths=widths)
    t.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 7.6), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fdf3f2')]),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8a2a1f')),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5)]))
    return t


def build_combo_report(combo_key, omex_paths, out_pdf, unsuccessful=()):
    """omex_paths: the combination's SUCCESSFUL per-run archives (plotted and
    summarised). unsuccessful: archive_outcome() records of its other attempts,
    listed in their own section and excluded from every result."""
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
          ["Replicates", f"{n_replicates} (this report aggregates {len(reps)} successful "
                         "archive(s); plots show each replicate plus the across-replicate mean)"
                         + (f" &middot; <b>{len(unsuccessful)} unsuccessful attempt(s) excluded, "
                            "listed below</b>" if unsuccessful else "")]]
    S.append(prows([[f"<b>{a}</b>", b] for a, b in ov], [1.4 * inch, 5.35 * inch], header=False))

    if unsuccessful:
        S.append(Paragraph("Unsuccessful Attempts (excluded from results)", H2))
        S.append(_prows_plain(_unsuccessful_table_rows(unsuccessful),
                              [0.95 * inch, 0.8 * inch, 0.65 * inch, 2.6 * inch, 1.75 * inch]))
        S.append(Paragraph(_UNSUCCESSFUL_NOTE, SUB))

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

    # Run identity — the seed is what separates two replicates of one combination,
    # so a reader comparing curves needs it to tell stochastic variation from a
    # configured difference. Read from each replicate archive's run_metadata.json.
    ident = []
    for o in omex_paths:
        try:
            with zipfile.ZipFile(o) as zf:
                if 'run_metadata.json' not in zf.namelist():
                    continue
                m = json.loads(zf.read('run_metadata.json'))
        except Exception:
            continue
        code = (m.get('provenance') or {}).get('code') or {}
        ident.append([
            Path(o).parent.name,
            str(m.get('random_seed')) if m.get('random_seed') is not None else "not recorded",
            m.get('random_seed_origin') or "&mdash;",
            (m.get('schema_fingerprint')
             or (m.get('provenance') or {}).get('schema_fingerprint') or "not recorded"),
            ((code.get('describe') or code.get('commit_short') or '?')
             + (" (modified)" if code.get('dirty') else ""))
            if code.get('source') == 'git' else (code.get('source') or "not recorded"),
        ])
    if any(r[1] != "not recorded" for r in ident):
        S.append(Paragraph("Run Identity (stochastic realization &amp; code)", H2))
        S.append(prows([["Replicate", "RNG seed", "Origin", "Schema fingerprint", "Code"]] + ident,
                       [1.15 * inch, 1.15 * inch, 0.8 * inch, 2.0 * inch, 1.65 * inch]))
        S.append(Paragraph(
            "Replicates of a combination share a parameterization and differ only in the "
            "random number generator seed, so a difference between them is stochastic rather "
            "than configured. Seeds marked <i>drawn</i> were generated independently at launch "
            "and recorded afterwards; seeds marked <i>explicit</i> were set by the operator "
            "(a pinned seed applies to the first replicate only). The schema "
            "fingerprint identifies the parameter definitions in force when the run was "
            "configured, and the code entry the source revision that executed it.", SUB))

    S.extend(_parameter_credibility_block(list(omex_paths), H2, SUB, prows))

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
    thick_plots = make_thickness_plots(rep_plot_in, tmpdir, combo_key)
    if csv_plots or thick_plots:
        S.append(PageBreak())
        S.append(Paragraph("Results (replicate-aware, from the packaged data)", H2))
        S.append(Paragraph(
            f"Plotted from the CSV/parquet inside the {len(reps)} replicate archive(s). "
            "Thin lines are individual replicates; the bold line is the across-replicate "
            "mean and the shaded band &plusmn;1 SD across replicates. Time is shown in "
            "hours (as stored in the data).", N))
        for png, cap in csv_plots:
            S.append(Image(str(png), width=6.7 * inch, height=2.6 * inch))
            S.append(Paragraph(cap, SUB))
            S.append(Spacer(1, 4))
        for png, height, cap in thick_plots:
            S.append(Image(str(png), width=6.7 * inch, height=height * inch))
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
    Returns {'cell_count': df(Time index + cols), 'surfactant': df} (whichever
    are present) plus each replicate's own frames under 'cell_count_reps' /
    'surfactant_reps', and (label, reps, sim_days, inj_days, has_injury) from the
    run metadata. Thickness is analysed separately (_thickness_dataset)."""
    cc, surf = [], []
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
            if cn:
                d = pd.read_csv(io.BytesIO(zf.read(cn)))
                d = d.rename(columns={_time_key(d): 'Time'})
                cc.append(d.groupby('Time').mean(numeric_only=True))
            if sn:
                d = pd.read_csv(io.BytesIO(zf.read(sn)))
                d = d.rename(columns={_time_key(d): 'Time'})
                surf.append(d.groupby('Time').mean(numeric_only=True))
    frames = {}
    if cc:
        frames['cell_count'] = pd.concat(cc).groupby(level=0).mean(numeric_only=True)
        frames['cell_count_reps'] = cc
    if surf:
        frames['surfactant'] = pd.concat(surf).groupby(level=0).mean(numeric_only=True)
        frames['surfactant_reps'] = surf
    return frames, label, reps, sim_days, inj_days, has_injury


def build_experiment_report(root, combos, out_pdf, unsuccessful=None):
    """Cross-combination comparison PDF (OMEX-internal): per-replicate endpoints
    summarised across replicates (mean ± SD, 95% CI, Kruskal–Wallis across
    combinations) as a table and a dot plot; one line per combo (mean ± SD band)
    for each cell type and surfactant; the GUI's limbal vs central thickness view;
    and the GUI's paper thickness figure for each combination.

    combos: {combo: SUCCESSFUL per-run archives}. unsuccessful: {combo:
    [archive_outcome()]} for every other attempt, listed and excluded."""
    unsuccessful = {k: v for k, v in (unsuccessful or {}).items() if v}
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
        present = [(ck, [r[col] for r in data[ck]['frames'].get(metric + '_reps', [])
                         if col in r]) for ck in order]
        present = [(ck, reps) for ck, reps in present if reps]
        if not present:
            return None
        fig, ax = plt.subplots(figsize=(6.7, 2.7), dpi=150)
        for ck, reps in present:
            per_t = pd.concat(reps, axis=1)
            mean = per_t.mean(axis=1)
            ax.plot(mean.index, mean.values, lw=1.7, color=colors_by[ck],
                    label=f"{data[ck]['label']} (n={len(reps)})")
            if len(reps) > 1:
                sd = per_t.std(axis=1)
                ax.fill_between(mean.index, mean - sd, mean + sd, color=colors_by[ck],
                                alpha=0.15, lw=0)
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
            plots.append((p, f"{ct}: replicate mean per combination vs Time, shaded "
                          "&plusmn;1 SD across replicates"))
    p = line_plot('surfactant', 'Total Amount', 'Total amount',
                  "Surfactant across combinations", "surf.png")
    if p:
        plots.append((p, "Surfactant Total Amount: replicate mean per combination vs Time, "
                      "shaded &plusmn;1 SD across replicates"))
    plots = [(png, 2.7, cap) for png, cap in plots]
    ds, ap = _thickness_dataset(combos, tmpdir)
    thick_paper = []
    if ds is not None:
        p = _render(lambda fig: ap.enhanced_thickness(fig, ds, unit='days'),
                    tmpdir / 'thick.png', (6.7, 4.6))
        plots.append((p, 4.6, (
            "Epithelial thickness in &micro;m over time in the limbus (bin 0) and the "
            "central/peripheral cornea (bins 4&ndash;9), one line per combination "
            "(replicate mean, shaded &plusmn;1 SD across replicates), drawn by the "
            "V-Cornea GUI's own analysis (Analyze Results &rarr; Thickness, comparison "
            "view). Thickness = (top position &minus; membrane baseline) &times; 2 "
            "&micro;m/voxel. Time in days.")))
        stable_day = ap._default_stable_day(ds)
        for i, ck in enumerate(order):
            if ck not in ds.thickness_data:
                continue
            p = _render(lambda fig, ck=ck: ap.paper_thickness(fig, ds, combo=ck, unit='days'),
                        tmpdir / f'thick_paper_{i}.png', (6.7, 6.4))
            thick_paper.append((ck, p, len(ds.thickness_data[ck])))

    # ---- endpoints, computed per replicate (the statistics are across replicates)
    inj = inj_hours if (has_injury and inj_hours) else None

    def _split(s):
        """(pre-injury, post-injury) parts of a time series (whole series if no injury)."""
        if inj is None:
            return s.iloc[:1], s
        return s[s.index < inj], s[s.index >= inj]

    def central_series(ck):
        """Each replicate's central thickness (mean over bins 4–9) per time, µm."""
        if ds is None or ck not in ds.thickness_um:
            return []
        out = []
        for d in ds.thickness_um[ck]:
            d = d[d['Bin'].isin(ap.CENTRAL_BINS)]
            if not d.empty:
                out.append(d.groupby('Time')['Thickness'].mean())
        return out

    def recovery_days(s, frac=0.9):
        """Days from injury until thickness is back to frac × its pre-injury mean,
        counted from the post-injury minimum; 0 if it never fell below; NaN if it
        never recovered within the run."""
        pre, post = _split(s)
        if inj is None or pre.empty or post.empty:
            return np.nan
        base = pre.mean()
        if post.min() >= frac * base:
            return 0.0
        after = post[post.index >= post.idxmin()]
        hit = after[after >= frac * base]
        return (hit.index[0] - inj) / 24.0 if len(hit) else np.nan

    ENDPOINTS = [   # (key, row label, decimals)
        ('wing0', "Wing cells, pre-injury mean", 1),
        ('wing_min', "Wing cells, minimum after injury", 1),
        ('wing_rec', "Wing cells, final / pre-injury (%)", 1),
        ('th0', "Central thickness, pre-injury mean (&micro;m)", 1),
        ('th_min', "Central thickness, minimum after injury (&micro;m)", 1),
        ('th_end', "Central thickness, final (&micro;m)", 1),
        ('th_rec', "Central thickness, days to recover 90% of pre-injury", 1),
        ('surf_half', "Surfactant clearance half-life (h)", 1),
    ]

    def endpoints(ck):
        """{endpoint key: [value per replicate]} for one combination."""
        f = data[ck]['frames']
        e = {k: [] for k, _, _ in ENDPOINTS}

        def at_end(series_list):
            """Each series' value at the combination's last time point; NaN (counted
            as missing) for a series that does not reach it, never an earlier value."""
            if not series_list:
                return []
            t_end = max(s.index.max() for s in series_list)
            return [float(s.loc[t_end]) if t_end in s.index else np.nan for s in series_list]

        wings = [r['Wing'] for r in f.get('cell_count_reps', []) if 'Wing' in r]
        for w, w_end in zip(wings, at_end(wings)):
            pre, post = _split(w)
            w0 = pre.mean() if len(pre) else np.nan
            e['wing0'].append(w0)
            e['wing_min'].append(post.min() if len(post) else np.nan)
            e['wing_rec'].append(w_end / w0 * 100 if w0 else np.nan)
        central = central_series(ck)
        for s, s_end in zip(central, at_end(central)):
            pre, post = _split(s)
            e['th0'].append(pre.mean() if len(pre) else np.nan)
            e['th_min'].append(post.min() if len(post) else np.nan)
            e['th_end'].append(s_end)
            e['th_rec'].append(recovery_days(s))
        for r in f.get('surfactant_reps', []):
            if 'Total Amount' in r:   # Time is in hours; the peak is the applied dose
                a = r['Total Amount']
                below = a[(a.index > a.idxmax()) & (a <= a.max() / 2.0)] if a.max() > 0 else a[:0]
                e['surf_half'].append(below.index[0] - a.idxmax() if len(below) else np.nan)
        return e

    ends = {ck: endpoints(ck) for ck in order}

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
    S.append(prows([["Combination", "Label", "Replicates", "Unsuccessful"]] +
                   [[ck, data[ck]['label'], str(data[ck]['reps']),
                     str(len(unsuccessful.get(ck, [])))] for ck in order],
                   [2.0 * inch, 3.0 * inch, 0.85 * inch, 0.9 * inch]))
    if unsuccessful:
        S.append(Paragraph("Unsuccessful Attempts (excluded from every comparison)", H2))
        rows = [["Combination"] + _unsuccessful_table_rows([])[0]]
        for ck in sorted(unsuccessful):
            for r in _unsuccessful_table_rows(unsuccessful[ck])[1:]:
                rows.append([ck] + r)
        S.append(_prows_plain(rows, [1.2 * inch, 0.8 * inch, 0.7 * inch, 0.55 * inch,
                                     2.0 * inch, 1.5 * inch]))
        no_success = sorted(set(unsuccessful) - set(order))
        S.append(Paragraph(_UNSUCCESSFUL_NOTE + (
            " Combinations with no successful replicate (absent from the comparisons): "
            + ", ".join(no_success) + "." if no_success else ""), SUB))

    S.append(Paragraph("Summary Statistics (per-replicate endpoints)", H2))
    S.append(Paragraph(
        "Each endpoint is computed for every replicate separately, then summarised "
        "across the replicates of a combination as mean &plusmn; SD with the 95% "
        "confidence interval of the mean (t distribution) below it. The last column "
        "is a Kruskal&ndash;Wallis test of whether the endpoint differs across the "
        "combinations.", N))
    lw, pw = 2.05, 0.75
    cw = (6.75 - lw - pw) / max(len(order), 1)
    ticks, xname = _short_labels([data[ck]['label'] for ck in order])
    corner = "Endpoint" + (" &nbsp;/&nbsp; " + xname if xname else "")
    mrows = [[corner]
             + [f"{t}<br/>(n={data[ck]['reps']})" for t, ck in zip(ticks, order)]
             + ["Kruskal&ndash;<br/>Wallis p"]]
    for key, name, nd in ENDPOINTS:
        groups = [ends[ck][key] for ck in order]
        if not any(_finite(g) for g in groups):
            continue
        mrows.append([name] + [_fmt_stat(g, nd) for g in groups] + [_fmt_p(_kruskal_p(groups))])
    S.append(prows(mrows, [lw * inch] + [cw * inch] * len(order) + [pw * inch]))
    S.append(Paragraph(
        "Pre-injury = before the injury time; minimum after injury = damage depth. "
        "Central thickness = mean over bins 4&ndash;9 (&micro;m, the GUI's analysis; a "
        "bin with no epithelium left counts as 0). "
        "Surfactant half-life: hours from the applied peak until the total amount is "
        "down to half of it. "
        "Days to recover: from injury until central thickness, after its minimum, is "
        "back to 90% of its pre-injury mean (0 = never fell below 90%; replicates that "
        "did not recover within the run are left out and the remaining n is shown). "
        "With few replicates per combination the tests have little power and are not "
        "corrected for the number of endpoints; read them as descriptive.", SUB))

    stat_panels = [(name.replace("&micro;m", "µm"), {data[ck]['label']: ends[ck][key] for ck in order})
                   for key, name, _ in ENDPOINTS
                   if key in ('wing_min', 'wing_rec', 'th_min', 'th_rec')
                   and any(_finite(ends[ck][key]) for ck in order)]
    if stat_panels:
        labels_o = [data[ck]['label'] for ck in order]
        png = endpoint_plot(stat_panels, labels_o,
                            {data[ck]['label']: colors_by[ck] for ck in order},
                            tmpdir / 'endpoints.png')
        S.append(Image(str(png), width=6.7 * inch,
                       height=2.25 * -(-len(stat_panels) // 2) * inch))
        S.append(Paragraph(
            "Key endpoints by combination: each dot is one replicate; the black point and "
            "bar are the mean and its 95% confidence interval.", SUB))

    if plots:
        S.append(PageBreak())
        S.append(Paragraph("Metric Comparisons (one line per combination)", H2))
        S.append(Paragraph(
            "Each line is a combination's across-replicate mean and the shaded band "
            "&plusmn;1 SD across its replicates, read from the per-run OMEX archives. "
            "The legend gives the number of replicates n. Time in hours (thickness: "
            "days); the dashed red line marks injury.", N))
        for png, height, cap in plots:
            S.append(Image(str(png), width=6.7 * inch, height=height * inch))
            S.append(Paragraph(cap, SUB)); S.append(Spacer(1, 4))

    if thick_paper:
        S.append(PageBreak())
        S.append(Paragraph("Tissue Thickness by Combination (paper view)", H2))
        S.append(Paragraph(
            "For each combination, the V-Cornea GUI's paper thickness figure (Analyze "
            "Results &rarr; Thickness, paper view; Vanin et al. 2025, Fig 8). Top: tissue "
            "top position in each of the 10 X-bins over time; faint lines are the "
            "replicates, solid lines their mean. Bottom: from the stability time (day "
            f"{stable_day:g}) on, top position (blue) and thickness (red) across X, as "
            "box plots over replicates and time; thickness = (top position &minus; "
            "membrane baseline) &times; 2 &micro;m/voxel.", N))
        for i, (ck, png, n) in enumerate(thick_paper):
            if i:
                S.append(PageBreak())
            S.append(Paragraph(f"{data[ck]['label']} (n={n})", H2))
            S.append(Image(str(png), width=6.7 * inch, height=6.4 * inch))

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
    successful, unsuccessful = {}, {}
    for combo_key, omex_paths in combos.items():
        ok, other = split_by_outcome(omex_paths)
        if ok:
            successful[combo_key] = ok
        if other:
            unsuccessful[combo_key] = other
        # write the report into the combo folder (next to its replicates)
        out_dir = (path / combo_key) if (path / combo_key).is_dir() else omex_paths[0].parent.parent
        out_pdf = out_dir / f"{combo_key}_omex_report.pdf"
        if ok:
            written.append(build_combo_report(combo_key, ok, out_pdf, unsuccessful=other))
        else:
            written.append(build_unsuccessful_combo_report(combo_key, other, out_pdf))
        print(f"[combo_report] wrote {out_pdf}  ({len(ok)} successful, "
              f"{len(other)} unsuccessful replicate archive(s))")
    # whole-experiment comparison PDF when there is more than one combination
    if len(combos) > 1 and successful:
        _ensure_scan_archive(path, successful)   # refresh the comparison scan.omex first
        out_pdf = path / f"{path.name}_experiment_report.pdf"
        written.append(build_experiment_report(path, successful, out_pdf, unsuccessful))
        print(f"[combo_report] wrote {out_pdf}  (comparison across {len(successful)} combos)")
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
