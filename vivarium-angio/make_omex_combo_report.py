"""Per-combination + experiment PDF reports for angio OMEX runs (parity with the
vivarium-vcornea report tool, adapted for the angio Zarr/metrics model).

Reads ONLY the OMEX archives' worth of information: it (re)generates each run's
.omex with the current generator (so each carries metrics.csv + metadata.rdf +
model summary), then builds, OMEX-internal style:
  * one <combo>_omex_report.pdf per combination (replicate-aware metric plots +
    a final-step network snapshot + provenance + validation), and
  * one <experiment>_experiment_report.pdf comparing the combinations.

Usage:
    python make_omex_combo_report.py <experiment_dir>
"""
from __future__ import annotations

import io
import json
import re
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

sys.path.insert(0, str((Path(__file__).resolve().parent / 'vivarium_angio' / 'utils')))
import omex_generator as og  # noqa: E402

SEDNS = {'s': 'http://sed-ml.org/sed-ml/level1/version4',
         'h': 'http://www.w3.org/1999/xhtml'}
METRICS = og.ANGIO_METRIC_COLUMNS
NAVY = '#1a3c5e'

ROLES = {
    'simulation.sedml': 'SED-ML L1V4 simulation description',
    'scan.sedml': 'SED-ML comparison (scan repeatedTask + plot2D per metric)',
    'metadata.rdf': 'OMEX Metadata (provenance: creator, license, citation)',
    'manifest.xml': 'OMEX manifest (COMBINE archive index)',
    'run_metadata.json': 'Run provenance / parameters',
    'sim_params.json': 'Exact simulation parameters',
    'scan_metadata.json': 'Scan catalogue (points, combinations, metrics)',
    'metrics.csv': 'Scalar signals over time (indexed by the SED-ML)',
    'model/model_summary.json': 'Bundled model artifact (model/@source resolves here)',
}


def _role(name):
    if name in ROLES:
        return ROLES[name]
    if name.startswith('combo_data/'):
        return 'Per-combination replicate-mean metrics (CSV)'
    if name.startswith('model/'):
        return 'Bundled model file'
    if name.startswith('zarr/'):
        return 'Zarr trajectory (spatial ndarrays)'
    return '&mdash;'


def _contents_rows(omex):
    """File/Size/Role rows for an archive; the Zarr tree is collapsed to one row."""
    with zipfile.ZipFile(omex) as zf:
        infos = zf.infolist()
    rows = [["File", "Size (B)", "Role"]]
    zarr_files = [i for i in infos if i.filename.startswith('zarr/')]
    other = sorted((i for i in infos if not i.filename.startswith('zarr/')),
                   key=lambda x: x.filename)
    for i in other:
        rows.append([i.filename, f"{i.file_size:,}", _role(i.filename)])
    if zarr_files:
        total = sum(i.file_size for i in zarr_files)
        rows.append([f"zarr/&hellip; ({len(zarr_files)} files)", f"{total:,}",
                     "Full Zarr spatial trajectory (per-timestep ndarrays)"])
    return rows


# ----------------------------------------------------------------- discovery
def discover_combos(root):
    """Group run directories (each holding a `data.zarr`) by combination.

    Sweep/replicate runs use flat `<base>_comboNNN_repRR/` dirs, grouped here by
    stripping the `_repRR` suffix. A plain single run has no `_repNN` suffix, so
    its directory is treated as its own one-replicate combination — otherwise the
    GUI's single runs would never produce a report.
    """
    root = Path(root)
    combos = {}
    for d in sorted(root.iterdir()):
        if not (d.is_dir() and (d / 'data.zarr').exists()):
            continue
        key = re.sub(r'_rep\d+$', '', d.name) if re.search(r'_rep\d+$', d.name) else d.name
        combos.setdefault(key, []).append(d)
    return combos


def _params(rep_dir):
    try:
        return json.loads((rep_dir / 'run_metadata.json').read_text()).get('parameters', {})
    except Exception:
        return {}


# Execution-control / provenance keys the worker stamps onto every run's
# parameters. They differ between runs by design (seeds, indices) or are not
# model parameters at all, so they must never be inferred as swept.
_NON_MODEL_PARAM_KEYS = frozenset((
    'exp_name', 'store_path', 'creator', 'random_seed', 'random_seed_origin',
    '_schema_fingerprint', 'parameter_scan', 'scan_point', 'combination_index',
    'total_combinations', 'replicate_id', 'total_replicates',
    'parent_experiment_id',
))


def derive_scan(combos):
    """Return (scan_spec, combo_label_map).

    The recorded `parameter_scan` (stamped by the GUI on every sweep run) is
    authoritative when present. The cross-combo diff is only a fallback for
    pre-provenance runs, and skips execution-control keys — otherwise per-run
    values like random_seed (or the dict-valued scan_point) read as swept.
    """
    cparams = {c: _params(dirs[0]) for c, dirs in combos.items()}
    first = next(iter(cparams.values()))
    recorded = first.get('parameter_scan')
    if recorded and all(p.get('parameter_scan') == recorded for p in cparams.values()):
        swept = sorted(recorded)
        scan_spec = {k: sorted(recorded[k]) for k in swept}
    else:
        swept = sorted(k for k in first if k not in _NON_MODEL_PARAM_KEYS
                       and len({str(cparams[c].get(k)) for c in combos}) > 1)
        scan_spec = {k: sorted({cparams[c][k] for c in combos}) for k in swept}
    labels = {c: (", ".join(f"{k}={cparams[c].get(k)}" for k in swept) or c)
              for c in combos}
    return scan_spec, labels


# ----------------------------------------------------------------- data + validation
def replicate_metric_frames(rep_dirs):
    frames = []
    for d in rep_dirs:
        csv = og.extract_zarr_metrics(Path(d) / 'data.zarr')
        if csv:
            frames.append(pd.read_csv(io.StringIO(csv)))
    return frames


def run_validation(omex):
    with zipfile.ZipFile(omex) as zf:
        names = zf.namelist()
        sed = zf.read('simulation.sedml').decode() if 'simulation.sedml' in names else \
            (zf.read('scan.sedml').decode() if 'scan.sedml' in names else '')
        man = zf.read('manifest.xml').decode()
    s_ok = og.validate_sedml_structure(sed)['valid'] if sed else False
    m_ok = og.validate_omex_manifest(man, [n for n in names if n != 'manifest.xml'])['valid']
    try:
        from biosimulators_utils.combine.io import CombineArchiveReader
        from biosimulators_utils.combine.validation import validate as bv
        with tempfile.TemporaryDirectory() as ed, warnings.catch_warnings():
            warnings.simplefilter("ignore")
            arch = CombineArchiveReader().run(str(omex), ed)
            errs, warns = bv(arch, archive_dirname=ed)
        bio = f"PASS ({len(errs)} errors, {len(warns)} warning group)" if not errs else f"FAIL ({len(errs)} errors)"
    except Exception as e:  # noqa: BLE001
        bio = f"SKIP ({e})"
    return s_ok, m_ok, bio


def read_provenance(omex):
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
    return {'creator': name or None, 'email': root.findtext('.//' + VC + 'hasEmail'),
            'created': text('created'), 'modified': text('modified'),
            'license': text('license'), 'citation': text('bibliographicCitation'),
            'keywords': [e.text for e in root.findall('.//' + DCT + 'subject') if e.text]}


def read_run_identity(rep_dirs):
    """Per-replicate stochastic and code identity, from each run's metadata.

    The seed matters to a reader of the report, not only to a re-executor: within a
    combination the replicates share a parameterization and differ ONLY in their
    seed, so it is the seed that says whether a difference between two curves is
    stochastic or configured. Reported alongside the schema fingerprint (which
    parameter definitions were in force) and the code revision that produced the run.
    """
    rows = []
    for d in rep_dirs:
        try:
            meta = json.loads((Path(d) / 'run_metadata.json').read_text())
        except Exception:
            continue
        prov = meta.get('provenance') or {}
        code = prov.get('code') or {}
        params = meta.get('parameters') or {}
        rows.append({
            'replicate': Path(d).name,
            'seed': meta.get('random_seed', params.get('random_seed')),
            'origin': params.get('random_seed_origin'),
            'fingerprint': prov.get('schema_fingerprint') or meta.get('schema_fingerprint'),
            'commit': code.get('commit_short'),
            'dirty': bool(code.get('dirty')),
            'source': code.get('source'),
        })
    return rows


def _run_identity_block(rep_dirs, H2, SUB, prows):
    """Flowables for the run-identity table; empty list when nothing was recorded."""
    ident = read_run_identity(rep_dirs)
    if not any(r.get('seed') is not None for r in ident):
        return []
    rows = [["Replicate", "RNG seed", "Origin", "Schema fingerprint", "Code"]]
    for r in ident:
        if r.get('source') == 'git':
            code_txt = (r.get('commit') or '?') + (" (modified)" if r['dirty'] else "")
        elif r.get('source') == 'build_stamp':
            code_txt = f"built {r.get('commit') or '?'}"
        else:
            code_txt = "not recorded"
        rows.append([r['replicate'],
                     str(r['seed']) if r['seed'] is not None else "not recorded",
                     r.get('origin') or "—",
                     r.get('fingerprint') or "not recorded",
                     code_txt])
    out = [Paragraph("Run Identity (stochastic realization &amp; code)", H2),
           prows(rows, [1.25 * inch, 1.15 * inch, 0.85 * inch, 2.05 * inch, 1.45 * inch]),
           Paragraph(
               "Replicates within a combination share a parameterization and differ only in "
               "the random number generator seed, so a difference between them is stochastic "
               "rather than configured. Seeds marked <i>drawn</i> were generated independently "
               "at launch and recorded afterwards; the software does not prescribe a seed. "
               "The schema fingerprint identifies the parameter definitions in force when the "
               "run was configured, and the code entry the source revision that executed it.",
               SUB)]
    return out


# ----------------------------------------------------------------- plots
def _metric_replicate_plot(metric, frames, tmpdir, fname):
    """One combo: per-replicate thin + across-replicate mean bold, for one metric."""
    fig, ax = plt.subplots(figsize=(6.7, 2.3), dpi=150)
    merged = None
    for df in frames:
        if metric not in df:
            continue
        ax.plot(df['Time'], df[metric], color=NAVY, alpha=0.3, lw=0.8)
        s = df.set_index('Time')[metric]
        merged = s if merged is None else pd.concat([merged, s], axis=1)
    if merged is not None:
        m = merged.mean(axis=1) if isinstance(merged, pd.DataFrame) else merged
        ax.plot(m.index, m.values, color=NAVY, lw=1.8, label=f"mean of {len(frames)} replicate(s)")
        ax.legend(fontsize=7, frameon=False)
    ax.set_xlabel('Time (MCS)', fontsize=8); ax.set_ylabel(metric, fontsize=8)
    ax.tick_params(labelsize=7); ax.grid(True, alpha=0.3, lw=0.4)
    ax.set_title(f"{metric} — replicate-aware", fontsize=8.5, color=NAVY)
    fig.tight_layout(); p = tmpdir / fname; fig.savefig(p, bbox_inches='tight'); plt.close(fig)
    return p


def _metric_compare_plot(metric, combo_means, tmpdir, fname):
    """Experiment: one line per combination (replicate-mean) for one metric."""
    fig, ax = plt.subplots(figsize=(6.7, 2.5), dpi=150)
    cmap = plt.get_cmap('tab10')
    for i, (label, df) in enumerate(combo_means):
        if metric in df:
            ax.plot(df['Time'], df[metric], lw=1.7, color=cmap(i % 10), label=label)
    ax.set_xlabel('Time (MCS)', fontsize=8); ax.set_ylabel(metric, fontsize=8)
    ax.tick_params(labelsize=7); ax.grid(True, alpha=0.3, lw=0.4)
    ax.legend(fontsize=7, frameon=False)
    ax.set_title(f"{metric} across combinations", fontsize=8.5, color=NAVY)
    fig.tight_layout(); p = tmpdir / fname; fig.savefig(p, bbox_inches='tight'); plt.close(fig)
    return p


def _final_field(data_zarr, channel):
    """Final-step 2D view of a channel (0=cell type, 2=VEGF) from the Zarr store."""
    last = None
    for _, data in og._load_zarr_steps(data_zarr):
        last = data
    if last is None:
        return None
    f = last[..., channel]
    while f.ndim > 2:
        f = f[..., 0] if f.shape[-1] == 1 else f.mean(axis=-1)
    return f


def _network_snapshot(data_zarr, tmpdir, fname, title):
    """Render the final-step EC network (cell-type channel) from the Zarr store."""
    ct = _final_field(data_zarr, 0)
    if ct is None:
        return None
    fig, ax = plt.subplots(figsize=(3.1, 3.1), dpi=150)
    ax.imshow(ct.T, origin='lower', cmap='gray_r', interpolation='nearest')
    ax.set_title(title, fontsize=8, color=NAVY)
    ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout(); p = tmpdir / fname; fig.savefig(p, bbox_inches='tight'); plt.close(fig)
    return p


def _vegf_snapshot(data_zarr, tmpdir, fname, title):
    """Render the final-step VEGF field-of-view (channel 2) as a heatmap."""
    vegf = _final_field(data_zarr, 2)
    if vegf is None:
        return None
    fig, ax = plt.subplots(figsize=(3.4, 3.1), dpi=150)
    im = ax.imshow(vegf.T, origin='lower', cmap='viridis', interpolation='nearest')
    ax.set_title(title, fontsize=8, color=NAVY)
    ax.set_xticks([]); ax.set_yticks([])
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04); cb.ax.tick_params(labelsize=6)
    fig.tight_layout(); p = tmpdir / fname; fig.savefig(p, bbox_inches='tight'); plt.close(fig)
    return p


# ----------------------------------------------------------------- styles
def _styles():
    ss = getSampleStyleSheet()
    H = ParagraphStyle('H', parent=ss['Heading1'], fontSize=15, spaceAfter=2, textColor=colors.HexColor(NAVY))
    SUB = ParagraphStyle('SUB', parent=ss['Normal'], fontSize=8.5, textColor=colors.grey, spaceAfter=8)
    H2 = ParagraphStyle('H2', parent=ss['Heading2'], fontSize=10.5, spaceBefore=9, spaceAfter=3, textColor=colors.HexColor(NAVY))
    N = ParagraphStyle('N', parent=ss['Normal'], fontSize=8.2, leading=10.8, spaceAfter=3)
    cell = ParagraphStyle('cell', parent=ss['Normal'], fontSize=7.6, leading=9)
    cellH = ParagraphStyle('cellH', parent=cell, textColor=colors.white, fontName='Helvetica-Bold')

    def prows(rows, widths, header=True):
        st = [('FONTSIZE', (0, 0), (-1, -1), 7.6), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
              ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
              ('ROWBACKGROUNDS', (0, 1 if header else 0), (-1, -1), [colors.white, colors.HexColor('#f4f7fa')]),
              ('TOPPADDING', (0, 0), (-1, -1), 2.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
              ('LEFTPADDING', (0, 0), (-1, -1), 5)]
        if header:
            st += [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(NAVY)),
                   ('TEXTCOLOR', (0, 0), (-1, 0), colors.white), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold')]
        data = [[Paragraph(c, cellH if (header and i == 0) else cell) for c in r] for i, r in enumerate(rows)]
        t = Table(data, colWidths=widths); t.setStyle(TableStyle(st)); return t
    return H, SUB, H2, N, prows


# ----------------------------------------------------------------- reports
def build_combo_report(combo, label, rep_dirs, omex_paths, sim_time, out_pdf):
    import shutil
    tmpdir = Path(tempfile.mkdtemp(prefix='angio_combo_'))
    H, SUB, H2, N, prows = _styles()
    frames = replicate_metric_frames(rep_dirs)
    omex0 = omex_paths[0] if omex_paths else None
    val = [(Path(o).parent.name, *run_validation(o)) for o in omex_paths]
    prov = read_provenance(omex0) if omex0 else None

    S = [Paragraph(f"Angio OMEX Combination Report — {label}", H),
         Paragraph(f"{combo} &nbsp;|&nbsp; {len(rep_dirs)} replicate(s) &nbsp;|&nbsp; "
                   f"sim_time {sim_time} MCS", SUB),
         HRFlowable(width="100%", thickness=1, color=colors.HexColor(NAVY))]

    S.append(Paragraph("Combination Overview", H2))
    S.append(prows([["Property", "Value"],
                    ["Scan point", label], ["Replicates", str(len(rep_dirs))],
                    ["Signals", ", ".join(METRICS)],
                    ["Time", "MCS (angio has no physical-time calibration)"]],
                   [1.4 * inch, 5.35 * inch]))

    if prov:
        S.append(Paragraph("Provenance (OMEX Metadata)", H2))
        pr = [["Field", "Value"]]
        if prov.get('creator'):
            pr.append(["Creator (experimenter)",
                       prov['creator'] + (f" &middot; {prov['email']}" if prov.get('email') else "")])
        for k in ('created', 'modified', 'license', 'citation'):
            if prov.get(k):
                pr.append([k.capitalize(), str(prov[k])])
        if prov.get('keywords'):
            pr.append(["Keywords", ", ".join(prov['keywords'])])
        S.append(prows(pr, [1.6 * inch, 5.15 * inch]))

    S.extend(_run_identity_block(rep_dirs, H2, SUB, prows))

    if omex_paths:
        S.append(Paragraph("Per-replicate Archive Validation", H2))
        rv = [["Replicate", "built-in SED-ML", "manifest", "biosimulators"]]
        for repname, s_ok, m_ok, bio in val:
            rv.append([repname, "PASS" if s_ok else "FAIL", "PASS" if m_ok else "FAIL", bio])
        S.append(prows(rv, [2.2 * inch, 1.4 * inch, 1.1 * inch, 2.05 * inch]))

    if omex0:
        S.append(Paragraph("Archive Contents (per replicate)", H2))
        S.append(prows(_contents_rows(omex0), [2.6 * inch, 0.9 * inch, 3.25 * inch]))
        S.append(Paragraph(f"Each of the {len(rep_dirs)} replicate archives has this layout.", SUB))

    # metric plots + spatial snapshots
    S.append(PageBreak())
    S.append(Paragraph("Metrics (replicate-aware, from the Zarr trajectory)", H2))
    S.append(Paragraph("Thin = each replicate; bold = across-replicate mean. Time in MCS.", N))
    for i, metric in enumerate(METRICS):
        p = _metric_replicate_plot(metric, frames, tmpdir, f"m_{i}.png")
        S.append(Image(str(p), width=6.7 * inch, height=2.3 * inch)); S.append(Spacer(1, 3))
    ec = _network_snapshot(Path(rep_dirs[0]) / 'data.zarr', tmpdir, "ec.png",
                           "Final EC network")
    vegf = _vegf_snapshot(Path(rep_dirs[0]) / 'data.zarr', tmpdir, "vegf.png",
                          "Final VEGF field")
    if ec or vegf:
        S.append(Paragraph("Final-step spatial fields (replicate 1)", H2))
        cells = [c for c in (Image(str(ec), width=2.7 * inch, height=2.7 * inch) if ec else None,
                             Image(str(vegf), width=3.0 * inch, height=2.7 * inch) if vegf else None) if c]
        S.append(Table([cells], colWidths=[3.0 * inch, 3.3 * inch][:len(cells)]))

    try:
        SimpleDocTemplate(str(out_pdf), pagesize=letter, topMargin=0.55 * inch, bottomMargin=0.5 * inch,
                          leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                          title=f"Angio Combination Report {combo}").build(S)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return Path(out_pdf)


def build_experiment_report(root, scan_omex, combos, labels, sim_time, out_pdf):
    import shutil
    tmpdir = Path(tempfile.mkdtemp(prefix='angio_exp_'))
    H, SUB, H2, N, prows = _styles()
    order = sorted(combos)
    combo_means = []
    for c in order:
        frames = replicate_metric_frames(combos[c])
        if frames:
            mean = pd.concat([f.set_index('Time') for f in frames]).groupby(level=0).mean(numeric_only=True).reset_index()
            combo_means.append((labels[c], mean))

    S = [Paragraph(f"Angio OMEX Experiment Report — {root.name}", H),
         Paragraph(f"{len(order)} combinations &nbsp;|&nbsp; "
                   f"{', '.join(str(len(combos[c])) for c in order)} replicate(s) each &nbsp;|&nbsp; "
                   f"sim_time {sim_time} MCS", SUB),
         HRFlowable(width="100%", thickness=1, color=colors.HexColor(NAVY))]

    if scan_omex and Path(scan_omex).exists():
        with zipfile.ZipFile(scan_omex) as zf:
            snames = zf.namelist()
            sm = json.loads(zf.read('scan_metadata.json')) if 'scan_metadata.json' in snames else {}
            sed = zf.read('scan.sedml').decode() if 'scan.sedml' in snames else ''
            sinfo = {n: zf.getinfo(n).file_size for n in snames}
        s_ok, m_ok, bio = run_validation(scan_omex)
        S.append(Paragraph("Experiment Archive", H2))
        S.append(Paragraph(f"Report OF the experiment archive <b>{Path(scan_omex).name}</b> "
                           f"({Path(scan_omex).stat().st_size:,} bytes) — the SED-ML/COMBINE "
                           "description of the whole scan.", N))
        S.append(prows([["Property", "Value"],
                        ["Parameter scan", "; ".join(f"{k} &isin; {v}" for k, v in (sm.get('parameter_scan') or {}).items())],
                        ["Scan points", str(sm.get('total_scan_points'))],
                        ["Replicates / point", str(sm.get('replicates_per_point'))],
                        ["Metrics compared", ", ".join(sm.get('metrics', METRICS))]],
                       [1.7 * inch, 5.05 * inch]))

        S.append(Paragraph("Experiment OMEX Contents", H2))
        S.append(prows(_contents_rows(scan_omex), [2.6 * inch, 0.9 * inch, 3.25 * inch]))

        if sed:
            r = ET.fromstring(sed)
            plots = r.findall('.//s:plot2D', SEDNS)
            S.append(Paragraph("Reading the SED-ML (comparison)", H2))
            S.append(prows([["plot2D (signal across combinations)", "curves (= combinations)"]] +
                           [[pl.get('name', ''), str(len(pl.findall('.//s:curve', SEDNS)))] for pl in plots],
                           [5.0 * inch, 1.75 * inch]))
        S.append(Paragraph("Validation of the Experiment Archive", H2))
        S.append(prows([["Layer", "Result"], ["Built-in SED-ML", "PASS" if s_ok else "FAIL"],
                        ["Built-in manifest", "PASS" if m_ok else "FAIL"],
                        ["biosimulators-utils", bio]], [3.3 * inch, 3.45 * inch]))
        prov = read_provenance(scan_omex)
        if prov:
            S.append(Paragraph("Provenance (OMEX Metadata)", H2))
            pr = [["Field", "Value"]]
            if prov.get('creator'):
                pr.append(["Creator (experimenter)",
                           prov['creator'] + (f" &middot; {prov['email']}" if prov.get('email') else "")])
            for k in ('created', 'modified', 'license', 'citation'):
                if prov.get(k):
                    pr.append([k.capitalize(), str(prov[k])])
            if prov.get('keywords'):
                pr.append(["Keywords", ", ".join(prov['keywords'])])
            S.append(prows(pr, [1.6 * inch, 5.15 * inch]))

    # summary metrics table (final value per combo per metric)
    S.append(Paragraph("Summary Metrics (replicate-mean, final step)", H2))
    mrows = [["Combination"] + METRICS]
    for label, df in combo_means:
        last = df.iloc[-1]
        mrows.append([label] + [f"{last[m]:.3g}" if m in df else "—" for m in METRICS])
    S.append(prows(mrows, [1.9 * inch] + [1.21 * inch] * len(METRICS)))

    S.append(PageBreak())
    S.append(Paragraph("Metric Comparisons (one line per combination)", H2))
    for i, metric in enumerate(METRICS):
        p = _metric_compare_plot(metric, combo_means, tmpdir, f"c_{i}.png")
        S.append(Image(str(p), width=6.7 * inch, height=2.5 * inch)); S.append(Spacer(1, 3))

    # final-step spatial fields side by side (one per combo, replicate 1)
    S.append(Paragraph("Final-step EC networks (one per combination)", H2))
    ec_imgs = []
    for c in order:
        snap = _network_snapshot(Path(combos[c][0]) / 'data.zarr', tmpdir, f"ec_{c}.png", labels[c])
        if snap:
            ec_imgs.append(Image(str(snap), width=2.0 * inch, height=2.0 * inch))
    if ec_imgs:
        S.append(Table([ec_imgs], colWidths=[2.2 * inch] * len(ec_imgs)))

    S.append(Paragraph("Final-step VEGF fields (one per combination)", H2))
    vegf_imgs = []
    for c in order:
        snap = _vegf_snapshot(Path(combos[c][0]) / 'data.zarr', tmpdir, f"vg_{c}.png", labels[c])
        if snap:
            vegf_imgs.append(Image(str(snap), width=2.15 * inch, height=2.0 * inch))
    if vegf_imgs:
        S.append(Table([vegf_imgs], colWidths=[2.35 * inch] * len(vegf_imgs)))

    try:
        SimpleDocTemplate(str(out_pdf), pagesize=letter, topMargin=0.55 * inch, bottomMargin=0.5 * inch,
                          leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                          title=f"Angio Experiment Report {root.name}").build(S)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return Path(out_pdf)


def _regenerate_archives(combos, labels, scan_spec, sim_params, root, num_replicates, creator):
    """(Re)generate per-run .omex (new format) + the experiment scan.omex."""
    def _is_new_format(omex):
        try:
            with zipfile.ZipFile(omex) as zf:
                return 'metrics.csv' in zf.namelist() and 'metadata.rdf' in zf.namelist()
        except Exception:
            return False

    omex_by_combo = {}
    for c, dirs in combos.items():
        paths = []
        for d in dirs:
            existing = d / f"{d.name}.omex"
            if existing.exists() and _is_new_format(existing):
                paths.append(existing)        # reuse worker-generated new-format archive
                continue
            try:
                meta = json.loads((d / 'run_metadata.json').read_text())
            except Exception:
                meta = {'parameters': _params(d)}
            try:
                paths.append(og.create_omex_archive_from_zarr(
                    d / 'data.zarr', meta, meta.get('parameters', {}),
                    archive_path=existing, creator=creator))
            except Exception as e:  # noqa: BLE001
                print(f"[angio_report] per-run archive failed for {d.name}: {e}")
        omex_by_combo[c] = paths
    combinations = [{'label': labels[c], 'replicate_dirs': [str(x) for x in combos[c]], '_index': i + 1}
                    for i, c in enumerate(sorted(combos))]
    scan = None
    if scan_spec:
        try:
            scan = og.create_experiment_scan_archive(root, scan_spec, combinations, sim_params,
                                                     run_name=re.sub(r'_\d{8}_\d{6}$', '', root.name),
                                                     num_replicates=num_replicates, creator=creator)
        except Exception as e:  # noqa: BLE001
            print(f"[angio_report] scan archive failed: {e}")
    return omex_by_combo, scan


def _creator_from_omex(omex):
    """Reconstruct a creator dict from an archive's metadata.rdf (so the scan archive
    inherits the operator the worker stamped on the per-run archives)."""
    prov = read_provenance(omex)
    if not prov or not (prov.get('creator') or prov.get('email')):
        return None
    c = {}
    name = prov.get('creator')
    if name:
        parts = name.rsplit(' ', 1)
        if len(parts) == 2:
            c['given'], c['family'] = parts[0], parts[1]
        else:
            c['given'] = name
    if prov.get('email'):
        c['email'] = prov['email']
    return c


def generate(root, creator=None):
    root = Path(root)
    combos = discover_combos(root)
    if not combos:
        print(f"[angio_report] no runs with data.zarr under {root}")
        return []
    scan_spec, labels = derive_scan(combos)
    num_replicates = max(len(v) for v in combos.values())
    sim_params = _params(next(iter(combos.values()))[0])
    sim_time = sim_params.get('sim_time', 100.0)

    # Inherit the operator/creator from an existing per-run archive if not given.
    if creator is None:
        for c, dirs in combos.items():
            for d in dirs:
                o = d / f"{d.name}.omex"
                if o.exists():
                    creator = _creator_from_omex(o)
                    break
            if creator:
                break

    omex_by_combo, scan = _regenerate_archives(combos, labels, scan_spec, sim_params, root, num_replicates, creator)

    written = []
    for c in sorted(combos):
        out_pdf = root / f"{c}_omex_report.pdf"
        written.append(build_combo_report(c, labels[c], combos[c], omex_by_combo.get(c, []), sim_time, out_pdf))
        print(f"[angio_report] wrote {out_pdf}  ({len(combos[c])} replicate(s))")
    if len(combos) > 1:
        out_pdf = root / f"{root.name}_experiment_report.pdf"
        written.append(build_experiment_report(root, scan, combos, labels, sim_time, out_pdf))
        print(f"[angio_report] wrote {out_pdf}  (comparison across {len(combos)} combos)")
    return written


def main(argv=None):
    argv = argv or sys.argv[1:]
    if len(argv) < 1:
        print(__doc__); return 1
    n = len(generate(argv[0]))
    print(f"\nDone — {n} report(s) written.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
