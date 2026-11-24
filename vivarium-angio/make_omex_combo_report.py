"""Per-combination + experiment PDF reports for angio OMEX runs (parity with the
vivarium-vcornea report tool, adapted for the angio Zarr/metrics model).

Two separate steps:

  1. Export (only where a working directory exists): a run directory that has no
     archive yet gets one, built by the current generator. A run directory is
     never read after this step.
  2. Report: every figure, table and number is read from the .omex archives --
     run_metadata.json, the parameter audit, metadata.rdf, metrics.csv and the
     Zarr trajectory packed under zarr/. The metric series are recomputed from
     that archived trajectory and compared with the archive's own metrics.csv;
     the outcome is printed in the report. A directory holding nothing but
     .omex files therefore produces the same report as the original experiment
     directory.

Output:
  * one <combo>_omex_report.pdf per combination (replicate-aware metric plots +
    a final-step network snapshot + provenance + validation), and
  * one <experiment>_experiment_report.pdf comparing the combinations.

Usage:
    python make_omex_combo_report.py <experiment_dir | directory of .omex files>
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

# By package name: vivarium-vcornea ships a module also called omex_generator,
# so a bare import off sys.path can resolve to the wrong package's generator in
# any process that has loaded both. (vivarium_angio/__init__ imports nothing, so
# this does not pull in the simulation stack.) Bare import only as a fallback for
# a checkout whose package is not installed.
try:
    from vivarium_angio.utils import omex_generator as og  # noqa: E402
except ImportError:
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
    'status.json': 'Machine-readable run outcome',
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
def _combo_key(run_name):
    """`<base>_comboNNN_repRR` -> `<base>_comboNNN`; a plain single run is its own
    one-replicate combination."""
    return re.sub(r'_rep\d+$', '', run_name)


def discover_combos(root):
    """Group RUN DIRECTORIES by combination, for the export step only.

    A run directory is one that holds a `data.zarr`, a `run_metadata.json` or its
    own `<name>.omex`. A run that failed before it wrote any Zarr store is
    therefore still found, archived and listed, instead of vanishing from the
    batch.
    """
    root = Path(root)
    combos = {}
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        if not ((d / 'data.zarr').exists() or (d / 'run_metadata.json').exists()
                or (d / f"{d.name}.omex").exists()):
            continue
        combos.setdefault(_combo_key(d.name), []).append(d)
    return combos


class ArchivedRun:
    """One run, as its .omex archive describes it. Everything the report shows
    about a run comes through this class, and this class opens only the archive.

    `omex` is None for a run that has no archive (it could not be exported); such
    a run is listed as excluded and nothing else is known about it.
    """

    def __init__(self, omex=None, name=None):
        self.omex = Path(omex) if omex else None
        self.name = name or self.omex.stem
        self._meta = None
        self._loaded = False
        self._frame = None
        self._fields = {}
        self.metrics_check = 'not checked'

    def _read_json(self, member):
        if self.omex is None:
            return None
        try:
            with zipfile.ZipFile(self.omex) as zf:
                return json.loads(zf.read(member)) if member in zf.namelist() else None
        except Exception:
            return None

    @property
    def meta(self):
        if self._meta is None:
            self._meta = self._read_json('run_metadata.json') or {}
        return self._meta

    @property
    def params(self):
        return self.meta.get('parameters') or self._read_json('sim_params.json') or {}

    @property
    def status(self):
        """The outcome the archive records; 'no archive' / 'unknown' otherwise."""
        if self.omex is None:
            return 'no archive'
        status = self.meta.get('simulation_status')
        if status not in og._ARCHIVE_STATUSES:
            status = (self._read_json('status.json') or {}).get('status')
        return status if status in og._ARCHIVE_STATUSES else 'unknown'

    def _load(self):
        """Read the archived trajectory once: metric series + final-step fields."""
        if self._loaded:
            return
        self._loaded = True
        embedded = recomputed = None
        try:
            with zipfile.ZipFile(self.omex) as zf:
                if 'metrics.csv' in zf.namelist():
                    embedded = pd.read_csv(io.BytesIO(zf.read('metrics.csv')))
        except Exception as e:  # noqa: BLE001
            print(f"[angio_report] {self.name}: metrics.csv unreadable: {e}")
        with tempfile.TemporaryDirectory(prefix='angio_omex_',
                                         ignore_cleanup_errors=True) as tmp:
            try:
                store = og.extract_archive_zarr(self.omex, tmp)
            except Exception as e:  # noqa: BLE001
                print(f"[angio_report] {self.name}: archived trajectory unreadable: {e}")
                store = None
            if store is not None:
                csv = og.extract_zarr_metrics(store)
                if csv:
                    recomputed = pd.read_csv(io.StringIO(csv))
                last = None
                for _, data in og._load_zarr_steps(store):
                    last = data
                if last is not None:
                    for channel in (0, 2):
                        f = last[..., channel]
                        while f.ndim > 2:
                            f = f[..., 0] if f.shape[-1] == 1 else f.mean(axis=-1)
                        self._fields[channel] = np.array(f)
        # The archived trajectory is the raw state; the series are derived from it.
        # metrics.csv is the archive's own copy of that derivation, so the two are
        # compared, and it is the fallback when the trajectory cannot be read.
        self._frame = recomputed if recomputed is not None else embedded
        if recomputed is None:
            self.metrics_check = ('trajectory unreadable; metrics.csv used'
                                  if embedded is not None else 'no metric data')
        elif embedded is None:
            self.metrics_check = 'no metrics.csv in archive'
        else:
            same = (list(embedded.columns) == list(recomputed.columns)
                    and embedded.shape == recomputed.shape
                    and np.allclose(embedded.to_numpy(dtype=float),
                                    recomputed.to_numpy(dtype=float),
                                    rtol=0, atol=1e-6, equal_nan=True))
            self.metrics_check = 'MATCH' if same else 'DIFFERS'

    @property
    def frame(self):
        """Time + metric columns, derived from the archived trajectory (or None)."""
        self._load()
        return self._frame

    def final_field(self, channel):
        """Final-step 2D view of a channel (0 = cell type, 2 = VEGF), or None."""
        self._load()
        return self._fields.get(channel)


def _is_scan_archive(omex):
    try:
        with zipfile.ZipFile(omex) as zf:
            names = zf.namelist()
        return 'scan.sedml' in names or 'scan_metadata.json' in names
    except Exception:
        return True          # unreadable: not a run archive either


def discover_archived_runs(root):
    """{combo: [ArchivedRun]} for every per-run archive under root: a run
    directory's own `<name>/<name>.omex`, or an .omex lying directly in root (an
    experiment distributed as archives only). Experiment-level scan archives are
    skipped. A run directory's archive wins over a loose copy of the same name."""
    root = Path(root)
    found = {}
    for omex in sorted(root.glob('*.omex')):
        if not _is_scan_archive(omex):
            found[omex.stem] = omex
    for omex in sorted(root.glob('*/*.omex')):
        if omex.stem == omex.parent.name and not _is_scan_archive(omex):
            found[omex.stem] = omex
    combos = {}
    for name in sorted(found):
        combos.setdefault(_combo_key(name), []).append(ArchivedRun(found[name], name))
    return combos


def find_scan_archive(root):
    """An experiment-level scan archive already present in root, or None."""
    for omex in sorted(Path(root).glob('*.omex')):
        try:
            with zipfile.ZipFile(omex) as zf:
                if 'scan.sedml' in zf.namelist():
                    return omex
        except Exception:
            continue
    return None


def _params(run):
    """Parameters of a run: from its archive (ArchivedRun), or — in the export
    step, before an archive exists — from the run directory's run_metadata.json."""
    if isinstance(run, ArchivedRun):
        return run.params
    try:
        return json.loads((Path(run) / 'run_metadata.json').read_text()).get('parameters', {})
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
def replicate_metric_frames(runs):
    """One metrics frame per ArchivedRun, each derived from its archive."""
    return [r.frame for r in runs if r.frame is not None]


def _leaf_messages(nodes, trail=()):
    """Flatten the validator's nested [message, [children]] lists into one line
    per leaf: 'file -> element -> what is wrong'."""
    lines = []
    for node in nodes or []:
        if isinstance(node, str):
            lines.append(' → '.join(trail + (node.strip(),)))
        elif isinstance(node, (list, tuple)) and node and isinstance(node[0], str):
            message = ' '.join(node[0].split())
            children = node[1] if len(node) > 1 else None

            def _is_leaf(child):
                return isinstance(child, str) or (
                    isinstance(child, (list, tuple)) and len(child) == 1
                    and isinstance(child[0], str)) or (
                    isinstance(child, (list, tuple)) and len(child) == 2
                    and isinstance(child[0], str) and not child[1])
            if children and len(children) > 1 and all(_is_leaf(c) for c in children):
                # details of ONE finding (e.g. the four numbers of a time course):
                # keep them on its line instead of repeating the finding per detail
                details = '; '.join(' '.join((c if isinstance(c, str) else c[0]).split())
                                    for c in children)
                lines.append(' → '.join(trail + (f"{message} ({details})",)))
            elif children:
                lines.extend(_leaf_messages(children, trail + (message,)))
            else:
                lines.append(' → '.join(trail + (message,)))
        elif isinstance(node, (list, tuple)):
            lines.extend(_leaf_messages(node, trail))
    return lines


_VALIDATION_CACHE = {}


def validation_detail(omex):
    """What the external validator (biosimulators-utils) said about an archive:
    {'errors': [...], 'warnings': [...], 'notices': [...], 'skipped': reason|None}.
    `warnings` are the validator's own findings, one line each; `notices` are what
    it reported it did NOT check (raised as Python warnings)."""
    key = (str(omex), Path(omex).stat().st_mtime_ns)
    if key in _VALIDATION_CACHE:
        return _VALIDATION_CACHE[key]
    detail = {'errors': [], 'warnings': [], 'notices': [], 'skipped': None}
    try:
        from biosimulators_utils.combine.io import CombineArchiveReader
        from biosimulators_utils.combine.validation import validate as bv
        with tempfile.TemporaryDirectory() as ed, warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            arch = CombineArchiveReader().run(str(omex), ed)
            errs, warns = bv(arch, archive_dirname=ed)
        detail['errors'] = _leaf_messages(errs)
        detail['warnings'] = _leaf_messages(warns)
        notices = set()
        for w in caught:
            text = ' '.join(re.sub(r'\x1b\[[0-9;]*m', '', str(w.message)).split())
            if 'not yet supported' not in text and 'biosimulators' not in str(
                    getattr(w, 'filename', '')).lower():
                continue
            if text.startswith('The SED document is potentially incorrect'):
                continue                  # a restatement of the warnings above
            # the validator names its own temporary copy; keep the file name only
            notices.add(re.sub(r'`[^`]*[\\/]([^`\\/]+)`', r'`\1`', text))
        detail['notices'] = sorted(notices)
    except Exception as e:  # noqa: BLE001
        detail['skipped'] = str(e)
    _VALIDATION_CACHE[key] = detail
    return detail


def run_validation(omex):
    with zipfile.ZipFile(omex) as zf:
        names = zf.namelist()
        sed = zf.read('simulation.sedml').decode() if 'simulation.sedml' in names else \
            (zf.read('scan.sedml').decode() if 'scan.sedml' in names else '')
        man = zf.read('manifest.xml').decode()
    s_ok = og.validate_sedml_structure(sed)['valid'] if sed else False
    m_ok = og.validate_omex_manifest(man, [n for n in names if n != 'manifest.xml'])['valid']
    d = validation_detail(omex)
    if d['skipped'] is not None:
        bio = f"SKIP ({d['skipped']})"
    elif d['errors']:
        bio = f"FAIL ({len(d['errors'])} errors)"
    else:
        n = len(d['warnings'])
        bio = f"PASS (0 errors, {n} warning{'' if n == 1 else 's'})"
    return s_ok, m_ok, bio


_VALIDATOR_SCOPE = (
    "The external validator (biosimulators-utils) checks the COMBINE manifest and the "
    "structure of the SED-ML document. It cannot validate a CompuCell3D model file and "
    "says so in a warning; the model is therefore not validated by this step. Its "
    "\"unusual number of steps\" warning is a rule of thumb raised whenever numberOfSteps "
    "is not a multiple of 5; here that number is the count of recorded snapshots minus "
    "one, with the first output at the first recorded step (the initial condition is not "
    "stored).")


def _validator_messages_block(omex_paths, SUB):
    """Flowables quoting the validator's own messages for a set of archives (each
    distinct message once), with what the validator does and does not check."""
    errors, warns, notices, skipped = [], [], [], []
    for o in omex_paths:
        d = validation_detail(o)
        for found, bucket in ((d['errors'], errors), (d['warnings'], warns),
                              (d['notices'], notices)):
            for line in found:
                if line not in bucket:
                    bucket.append(line)
        if d['skipped'] and d['skipped'] not in skipped:
            skipped.append(d['skipped'])

    def _esc(text):
        return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    out = [Paragraph(_VALIDATOR_SCOPE, SUB)]
    for title, lines in (("Validator errors", errors), ("Validator warnings", warns),
                         ("Not checked by the validator", notices),
                         ("Validator not run", skipped)):
        if lines:
            out.append(Paragraph(f"<b>{title}:</b><br/>"
                                 + "<br/>".join("&bull; " + _esc(l) for l in lines), SUB))
    return out


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


def read_run_identity(runs):
    """Per-replicate stochastic and code identity, from each archive's run_metadata.json.

    The seed matters to a reader of the report, not only to a re-executor: within a
    combination the replicates share a parameterization and differ ONLY in their
    seed, so it is the seed that says whether a difference between two curves is
    stochastic or configured. Reported alongside the schema fingerprint (which
    parameter definitions were in force) and the code revision that produced the run.
    """
    rows = []
    for run in runs:
        meta = run.meta
        if not meta:
            continue
        prov = meta.get('provenance') or {}
        code = prov.get('code') or {}
        params = meta.get('parameters') or {}
        rows.append({
            'replicate': run.name,
            'seed': meta.get('random_seed', params.get('random_seed')),
            'origin': params.get('random_seed_origin'),
            'fingerprint': prov.get('schema_fingerprint') or meta.get('schema_fingerprint'),
            'commit': code.get('commit_short'),
            'dirty': bool(code.get('dirty')),
            'source': code.get('source'),
        })
    return rows


def _parameter_credibility_block(audit_sources, H2, SUB, prows):
    """Flowables for the parameter-credibility section; [] when no audit exists.

    Reads parameter_audit.json (run dir or .omex) written by the run from its
    live schema. One table of the parameters an auditor must look at: changed
    from default, or sitting outside a documented range. Everything else is
    summarised in a line, so a report stays short when the run stayed inside
    its documented ranges. Every verdict names what the range is based on.
    """
    # By package name, like omex_generator above: the bare name is only on
    # sys.path when the package is NOT installed, so a bare import alone failed
    # in every installed copy and silently dropped this whole section.
    try:
        from vivarium_angio.utils import parameter_audit as _pa
    except ImportError:
        try:
            import parameter_audit as _pa  # checkout without the package installed
        except Exception:
            return []
    audits = [a for a in (_pa.load_parameter_audit(s) for s in audit_sources) if a]
    if not audits:
        return []
    audit = audits[0]                       # replicates share a parameterization
    s = audit.get('summary') or {}
    out = [Paragraph("Parameter Audit (run values against the ranges the schema documents)", H2),
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
        "Each executed value is placed against the range tiers the schema declares: the "
        "<i>implementation limit</i>, the <i>documented working range</i> and the "
        "<i>recommended range</i> for this model's context of use. A range is only as strong "
        "as what it rests on, so every verdict states its basis: published literature, model "
        "calibration, the modeler's judgement, a numerical or implementation limit, or "
        "exploratory presets. \"Outside the documented working range\" therefore reports "
        "where a value sits relative to the schema's documentation; it is evidence of "
        "physiological implausibility only where the basis is published literature. The last "
        "column gives the basis and, where recorded, the citation of the range that decided "
        "the verdict; <i>basis not recorded</i> means the bound exists but its justification "
        "has not been documented, which is itself an audit finding. Numeric parameters "
        "without any documented range are listed as such; switches and categories are not "
        "range-assessed. Full detail for every parameter is in parameter_audit.json inside "
        "the archive.", SUB))
    if len(audits) > 1:
        diff = [k for k, e in audit['parameters'].items()
                if e.get('parameter_type') != 'control'
                and any(a['parameters'].get(k, {}).get('value') != e['value'] for a in audits[1:])]
        if diff:
            out.append(Paragraph("Replicates differ in: " + ", ".join(diff) +
                                 " (replicates of one combination should share every model parameter).", SUB))
    return out


def _run_identity_block(runs, H2, SUB, prows):
    """Flowables for the run-identity table; empty list when nothing was recorded."""
    ident = read_run_identity(runs)
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
_METRIC_AXIS = {
    'num_clusters': 'clusters (count)',
    'largest_cluster_size': 'largest cluster (lattice sites)',
    'cell_density': 'cell density (fraction of lattice sites)',
    'vegf_mean': 'mean VEGF (model units)',
}

_METRIC_NOTE = (
    "Clusters are connected groups of endothelial lattice sites (4-neighbour "
    "connectivity) on the model's lattice, which is periodic in x and y: a cluster "
    "that crosses a lattice edge is counted once. Cluster size is in lattice sites; "
    "cell density is the fraction of lattice sites occupied by endothelial cells; "
    "VEGF is in the model's concentration units, which are not calibrated to a "
    "physical unit.")


def _ylabel(metric):
    return _METRIC_AXIS.get(metric, metric)


def _per_time(frames, metric):
    """Replicates of one metric side by side on the Time index (one column each)."""
    cols = [df.groupby('Time')[metric].mean() for df in frames if metric in df]
    return pd.concat(cols, axis=1) if cols else None


def _metric_replicate_plot(metric, frames, tmpdir, fname):
    """One combo: per-replicate thin + across-replicate mean bold ± SD band, for one metric."""
    fig, ax = plt.subplots(figsize=(6.7, 2.3), dpi=150)
    for df in frames:
        if metric in df:
            ax.plot(df['Time'], df[metric], color=NAVY, alpha=0.3, lw=0.8)
    per_t = _per_time(frames, metric)
    if per_t is not None:
        m = per_t.mean(axis=1)
        ax.plot(m.index, m.values, color=NAVY, lw=1.8,
                label=(f"mean of {per_t.shape[1]} replicates" if per_t.shape[1] > 1
                       else "single run (no replicate mean)"))
        if per_t.shape[1] > 1:
            sd = per_t.std(axis=1)
            ax.fill_between(m.index, m - sd, m + sd, color=NAVY, alpha=0.15, lw=0,
                            label="±1 SD")
        ax.legend(fontsize=7, frameon=False)
    ax.set_xlabel('Time (MCS)', fontsize=8); ax.set_ylabel(_ylabel(metric), fontsize=7)
    ax.tick_params(labelsize=7); ax.grid(True, alpha=0.3, lw=0.4)
    ax.set_title(f"{metric} — replicate-aware", fontsize=8.5, color=NAVY)
    fig.tight_layout(); p = tmpdir / fname; fig.savefig(p, bbox_inches='tight'); plt.close(fig)
    return p


def _metric_compare_plot(metric, combo_frames, tmpdir, fname):
    """Experiment: one line per combination (replicate mean) with a ±1 SD band
    across its replicates, for one metric. combo_frames: [(label, [frames])]."""
    fig, ax = plt.subplots(figsize=(6.7, 2.5), dpi=150)
    cmap = plt.get_cmap('tab10')
    for i, (label, frames) in enumerate(combo_frames):
        per_t = _per_time(frames, metric)
        if per_t is None:
            continue
        m = per_t.mean(axis=1)
        ax.plot(m.index, m.values, lw=1.7, color=cmap(i % 10),
                label=f"{label} (n={per_t.shape[1]})")
        if per_t.shape[1] > 1:
            sd = per_t.std(axis=1)
            ax.fill_between(m.index, m - sd, m + sd, color=cmap(i % 10), alpha=0.15, lw=0)
    ax.set_xlabel('Time (MCS)', fontsize=8); ax.set_ylabel(_ylabel(metric), fontsize=7)
    ax.tick_params(labelsize=7); ax.grid(True, alpha=0.3, lw=0.4)
    ax.legend(fontsize=7, frameon=False)
    ax.set_title(f"{metric} across combinations (mean ± SD)", fontsize=8.5, color=NAVY)
    fig.tight_layout(); p = tmpdir / fname; fig.savefig(p, bbox_inches='tight'); plt.close(fig)
    return p


# ----------------------------------------------------------------- statistics
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


def _fmt_stat(values):
    """'mean ± SD [CI low, CI high]', plain numbers at the mean's 3 significant figures."""
    n, m, sd, half = _summary(values)
    if n == 0:
        return "&mdash;"
    d = max(0, 2 - int(np.floor(np.log10(abs(m))))) if m else 2
    s = f"{m:,.{d}f}"
    if n > 1:
        s += f" &plusmn; {sd:,.{d}f}<br/>[{m - half:,.{d}f}, {m + half:,.{d}f}]"
    return s + (f"<br/>(n={n} of {len(values)})" if n < len(values) else "")


def _fmt_p(p):
    return "&mdash;" if p is None else ("&lt;0.001" if p < 0.001 else f"{p:.3f}")


def _p_phrase(p):
    """Plain-text p for a plot title: 'p = 0.012' or 'p < 0.001'."""
    s = _fmt_p(p).replace("&lt;", "< ")
    return "p " + s if s.startswith("<") else "p = " + s


def _short_labels(labels):
    """Tick labels and axis name: 'lchem=100' -> ('100', 'lchem')."""
    parts = [str(l).split('=', 1) for l in labels]
    if all(len(p) == 2 for p in parts) and len({p[0] for p in parts}) == 1:
        return [p[1] for p in parts], parts[0][0]
    return [str(l) for l in labels], ''


def _endpoint_plot(panels, labels, tmpdir, fname, ncols=2):
    """panels: [(title, {label: [value per replicate]})]. One panel per endpoint:
    each replicate a dot, the mean with its 95% CI as a black bar, and the
    Kruskal–Wallis p across the combinations in the panel title."""
    rows = -(-len(panels) // ncols)
    fig, axes = plt.subplots(rows, ncols, figsize=(6.7, 2.25 * rows), dpi=150, squeeze=False)
    cmap = plt.get_cmap('tab10')
    ticks, xname = _short_labels(labels)
    rng = np.random.default_rng(0)
    for ax, (title, groups) in zip(axes.flat, panels):
        for i, lab in enumerate(labels):
            v = _finite(groups.get(lab, []))
            ax.scatter(i + rng.uniform(-0.1, 0.1, len(v)), v, s=16, alpha=0.75, lw=0,
                       color=cmap(i % 10), zorder=2)
            n, m, _, half = _summary(v)
            if n:
                ax.errorbar(i + 0.27, m, yerr=None if np.isnan(half) else half, fmt='o',
                            color='black', ms=3.5, capsize=3, lw=1, zorder=3)
        p = _kruskal_p([groups.get(lab, []) for lab in labels])
        ax.set_title(title + (f"\nKruskal–Wallis {_p_phrase(p)}"
                              if p is not None else ""), fontsize=7.5, color=NAVY)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(ticks, fontsize=7)
        ax.set_xlim(-0.5, len(labels) - 0.4)
        if xname:
            ax.set_xlabel(xname, fontsize=7)
        ax.tick_params(labelsize=7)
        ax.grid(True, axis='y', alpha=0.3, lw=0.4)
    for ax in list(axes.flat)[len(panels):]:
        ax.axis('off')
    fig.tight_layout(); p = tmpdir / fname; fig.savefig(p, bbox_inches='tight'); plt.close(fig)
    return p


def _network_snapshot(run, tmpdir, fname, title):
    """Render the final-step EC network (cell-type channel) from the run's archive."""
    ct = run.final_field(0)
    if ct is None:
        return None
    fig, ax = plt.subplots(figsize=(3.1, 3.1), dpi=150)
    ax.imshow(ct.T, origin='lower', cmap='gray_r', interpolation='nearest')
    ax.set_title(title, fontsize=8, color=NAVY)
    ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout(); p = tmpdir / fname; fig.savefig(p, bbox_inches='tight'); plt.close(fig)
    return p


def _vegf_snapshot(run, tmpdir, fname, title):
    """Render the final-step VEGF field (channel 2) from the run's archive."""
    vegf = run.final_field(2)
    if vegf is None:
        return None
    fig, ax = plt.subplots(figsize=(3.4, 3.1), dpi=150)
    im = ax.imshow(vegf.T, origin='lower', cmap='viridis', interpolation='nearest')
    ax.set_title(title, fontsize=8, color=NAVY)
    ax.set_xticks([]); ax.set_yticks([])
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04); cb.ax.tick_params(labelsize=6)
    cb.set_label('VEGF (model units)', fontsize=6)
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
_EXCLUDED_NOTE = (
    "Excluded from every plot, mean and summary metric in this report. A failed, "
    "timed-out or cancelled run can leave a partial Zarr trajectory, or none at all; "
    "averaging it into a replicate mean would bias the result. Its archive keeps the "
    "logs, parameters and partial outputs for diagnosis. <i>no archive</i> marks a run "
    "directory for which no archive could be built, so nothing about it is reported.")


def _excluded_rows(excluded):
    rows = [["Replicate", "Status", "Exit code", "Error", "Archive"]]
    for run, status in excluded:
        meta = run.meta
        exit_code = (meta.get('execution') or {}).get('exit_code')
        err = str(meta.get('error_message') or '&mdash;').replace('<', '&lt;')
        rows.append([run.name, f"<b>{status}</b>",
                     '&mdash;' if exit_code is None else str(exit_code),
                     err[:200] + ('&hellip;' if len(err) > 200 else ''),
                     run.omex.name if run.omex is not None else '&mdash;'])
    return rows


def _excluded_block(excluded, H2, SUB, prows, title="Excluded Replicates (unsuccessful runs)"):
    if not excluded:
        return []
    return [Paragraph(title, H2),
            prows(_excluded_rows(excluded),
                  [1.6 * inch, 0.75 * inch, 0.65 * inch, 2.35 * inch, 1.4 * inch]),
            Paragraph(_EXCLUDED_NOTE, SUB)]


def build_excluded_only_report(combo, label, excluded, out_pdf):
    """A combination none of whose replicates succeeded: nothing to plot or
    average, but its attempts are part of the record."""
    H, SUB, H2, N, prows = _styles()
    S = [Paragraph(f"Angio OMEX Combination Report — {label}", H),
         Paragraph(f"{combo} &nbsp;|&nbsp; no successful replicate "
                   f"({len(excluded)} unsuccessful)", SUB),
         HRFlowable(width="100%", thickness=1, color=colors.HexColor(NAVY))]
    S.extend(_excluded_block(excluded, H2, SUB, prows))
    SimpleDocTemplate(str(out_pdf), pagesize=letter, topMargin=0.55 * inch, bottomMargin=0.5 * inch,
                      leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                      title=f"Angio Combination Report {combo}").build(S)
    return Path(out_pdf)


def build_combo_report(combo, label, runs, omex_paths, sim_time, out_pdf, excluded=()):
    """runs: the combination's SUCCESSFUL replicates, as ArchivedRun (plotted and
    averaged); omex_paths: their archives. excluded: [(ArchivedRun, status)] of
    the others, listed only. Nothing here reads a run directory."""
    import shutil
    tmpdir = Path(tempfile.mkdtemp(prefix='angio_combo_'))
    H, SUB, H2, N, prows = _styles()
    frames = replicate_metric_frames(runs)
    omex0 = omex_paths[0] if omex_paths else None
    val = [(r.name, *run_validation(r.omex), r.metrics_check) for r in runs]
    prov = read_provenance(omex0) if omex0 else None

    S = [Paragraph(f"Angio OMEX Combination Report — {label}", H),
         Paragraph(f"{combo} &nbsp;|&nbsp; {len(runs)} replicate(s) &nbsp;|&nbsp; "
                   f"sim_time {sim_time} MCS", SUB),
         HRFlowable(width="100%", thickness=1, color=colors.HexColor(NAVY))]

    S.append(Paragraph("Combination Overview", H2))
    S.append(prows([["Property", "Value"],
                    ["Scan point", label],
                    ["Replicates", f"{len(runs)} successful (plotted and averaged)"
                     + (f"; {len(excluded)} unsuccessful, excluded" if excluded else "")],
                    ["Signals", ", ".join(METRICS)],
                    ["Time", "MCS (angio has no physical-time calibration)"]],
                   [1.4 * inch, 5.35 * inch]))
    S.extend(_excluded_block(excluded, H2, SUB, prows))

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

    S.extend(_run_identity_block(runs, H2, SUB, prows))
    S.extend(_parameter_credibility_block(list(omex_paths or []), H2, SUB, prows))

    if omex_paths:
        S.append(Paragraph("Per-replicate Archive Validation", H2))
        rv = [["Replicate", "built-in SED-ML", "manifest", "biosimulators",
               "metrics.csv vs archived trajectory"]]
        for repname, s_ok, m_ok, bio, check in val:
            rv.append([repname, "PASS" if s_ok else "FAIL", "PASS" if m_ok else "FAIL", bio, check])
        S.append(prows(rv, [1.75 * inch, 0.95 * inch, 0.75 * inch, 1.75 * inch, 1.55 * inch]))
        S.append(Paragraph(
            "Every figure and number in this report is read from the archives listed "
            "here, not from the directory the runs were produced in. The metric series "
            "are recomputed from the Zarr trajectory inside each archive (zarr/) and "
            "compared with the archive's own metrics.csv, the table its SED-ML indexes: "
            "<i>MATCH</i> means the two agree at every step. <i>DIFFERS</i> means the "
            "archive's table was written under a different metric definition or does "
            "not belong to this trajectory; the plots then show the recomputed series.",
            SUB))
        S.extend(_validator_messages_block(omex_paths, SUB))

    if omex0:
        S.append(Paragraph("Archive Contents (per replicate)", H2))
        S.append(prows(_contents_rows(omex0), [2.6 * inch, 0.9 * inch, 3.25 * inch]))
        S.append(Paragraph(f"Each of the {len(runs)} replicate archives has this layout.", SUB))

    # metric plots + spatial snapshots
    S.append(PageBreak())
    S.append(Paragraph("Metrics (replicate-aware, from the archived Zarr trajectory)", H2))
    S.append(Paragraph(("Thin = each replicate; bold = across-replicate mean; shaded = "
                        "&plusmn;1 SD across replicates. " if len(runs) > 1 else
                        "A single run: the line is that run's trajectory, not a mean. ")
                       + "Time in MCS.", N))
    S.append(Paragraph(_METRIC_NOTE, SUB))
    for i, metric in enumerate(METRICS):
        p = _metric_replicate_plot(metric, frames, tmpdir, f"m_{i}.png")
        S.append(Image(str(p), width=6.7 * inch, height=2.3 * inch)); S.append(Spacer(1, 3))
    ec = _network_snapshot(runs[0], tmpdir, "ec.png", "Final EC network")
    vegf = _vegf_snapshot(runs[0], tmpdir, "vegf.png", "Final VEGF field")
    if ec or vegf:
        S.append(Paragraph(f"Final-step spatial fields ({runs[0].name}, from "
                           f"zarr/ in {runs[0].omex.name})", H2))
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


def build_experiment_report(root, scan_omex, combos, labels, sim_time, out_pdf, excluded=None):
    """combos: {combo: SUCCESSFUL replicates as ArchivedRun}. excluded: {combo:
    [(ArchivedRun, status)]} of the others, listed and left out of every comparison."""
    import shutil
    tmpdir = Path(tempfile.mkdtemp(prefix='angio_exp_'))
    H, SUB, H2, N, prows = _styles()
    excluded = {c: v for c, v in (excluded or {}).items() if v}
    order = sorted(combos)
    combo_frames = []       # [(label, [one metrics frame per replicate])]
    for c in order:
        frames = replicate_metric_frames(combos[c])
        if frames:
            combo_frames.append((labels[c], frames))

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
        S.extend(_validator_messages_block([scan_omex], SUB))
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

    if excluded:
        rows = [["Combination"] + _excluded_rows([])[0]]
        for c in sorted(excluded):
            rows += [[labels.get(c, c)] + r for r in _excluded_rows(excluded[c])[1:]]
        S.append(Paragraph("Excluded Replicates (unsuccessful runs)", H2))
        S.append(prows(rows, [1.1 * inch, 1.25 * inch, 0.7 * inch, 0.55 * inch,
                              1.95 * inch, 1.2 * inch]))
        missing = [labels.get(c, c) for c in sorted(set(excluded) - set(order))]
        S.append(Paragraph(_EXCLUDED_NOTE + (
            " Combinations with no successful replicate (absent from the comparisons): "
            + ", ".join(missing) + "." if missing else ""), SUB))

    # summary statistics: each metric's final-step value per replicate, summarised
    # across the replicates of each combination. "Final" is the combination's last
    # step; a replicate without that step counts as missing (the cell shows n),
    # never as its own earlier value.
    def _finals(frames, m):
        t_end = max(df['Time'].max() for df in frames)
        return [(lambda v: float(v.iloc[0]) if len(v) else np.nan)(df.loc[df['Time'] == t_end, m])
                for df in frames if m in df]
    finals = {label: {m: _finals(frames, m) for m in METRICS} for label, frames in combo_frames}
    clabels = [label for label, _ in combo_frames]
    S.append(PageBreak())
    S.append(Paragraph("Summary Statistics (final step, per replicate)", H2))
    S.append(Paragraph(
        "Each metric is read at the final step of every replicate, then summarised "
        "across the replicates of a combination as mean &plusmn; SD with the 95% "
        "confidence interval of the mean (t distribution) below it. The last column is "
        "a Kruskal&ndash;Wallis test of whether the metric differs across the "
        "combinations.", N))
    ticks, xname = _short_labels(clabels)
    lw, pw = 1.6, 0.8
    cw = (6.75 - lw - pw) / max(len(clabels), 1)
    corner = "Metric" + (" &nbsp;/&nbsp; " + xname if xname else "")
    mrows = [[corner] + [f"{t}<br/>(n={len(frames)})" for t, (_, frames) in zip(ticks, combo_frames)]
             + ["Kruskal&ndash;<br/>Wallis p"]]
    for m in METRICS:
        groups = [finals[label][m] for label in clabels]
        mrows.append([m] + [_fmt_stat(g) for g in groups] + [_fmt_p(_kruskal_p(groups))])
    S.append(prows(mrows, [lw * inch] + [cw * inch] * len(clabels) + [pw * inch]))
    S.append(Paragraph(
        "With few replicates per combination the tests have little power and are not "
        "corrected for the number of metrics; read them as descriptive.", SUB))
    if clabels:
        p = _endpoint_plot([(m, {label: finals[label][m] for label in clabels}) for m in METRICS],
                           clabels, tmpdir, "endpoints.png")
        S.append(Image(str(p), width=6.7 * inch, height=2.25 * -(-len(METRICS) // 2) * inch))
        S.append(Paragraph(
            "Final-step value of each metric by combination: each dot is one replicate; "
            "the black point and bar are the mean and its 95% confidence interval.", SUB))

    S.append(PageBreak())
    S.append(Paragraph("Metric Comparisons (one line per combination)", H2))
    S.append(Paragraph(
        "Each line is a combination's across-replicate mean and the shaded band "
        "&plusmn;1 SD across its replicates; the legend gives the number of replicates "
        "n. Time in MCS.", N))
    S.append(Paragraph(_METRIC_NOTE, SUB))
    for i, metric in enumerate(METRICS):
        p = _metric_compare_plot(metric, combo_frames, tmpdir, f"c_{i}.png")
        S.append(Image(str(p), width=6.7 * inch, height=2.5 * inch)); S.append(Spacer(1, 3))

    # final-step spatial fields side by side (one per combo, replicate 1)
    S.append(Paragraph("Final-step EC networks (one per combination)", H2))
    ec_imgs = []
    for c in order:
        snap = _network_snapshot(combos[c][0], tmpdir, f"ec_{c}.png", labels[c])
        if snap:
            ec_imgs.append(Image(str(snap), width=2.0 * inch, height=2.0 * inch))
    if ec_imgs:
        S.append(Table([ec_imgs], colWidths=[2.2 * inch] * len(ec_imgs)))

    S.append(Paragraph("Final-step VEGF fields (one per combination)", H2))
    vegf_imgs = []
    for c in order:
        snap = _vegf_snapshot(combos[c][0], tmpdir, f"vg_{c}.png", labels[c])
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
    def _is_current_archive(omex):
        # An archive carrying status.json was written by the current worker and
        # records the run's outcome; it is never rebuilt. (Testing for
        # metrics.csv instead treated every failed/cancelled archive, which has
        # no metrics, as old-format and regenerated it as a SUCCESS archive with
        # executable SED-ML.)
        try:
            with zipfile.ZipFile(omex) as zf:
                names = zf.namelist()
                return 'status.json' in names or (
                    'metrics.csv' in names and 'metadata.rdf' in names)
        except Exception:
            return False

    omex_by_combo = {}
    for c, dirs in combos.items():
        paths = []
        for d in dirs:
            existing = d / f"{d.name}.omex"
            if existing.exists() and _is_current_archive(existing):
                paths.append(existing)        # reuse the worker-generated archive
                continue
            try:
                meta = json.loads((d / 'run_metadata.json').read_text())
            except Exception:
                meta = {'parameters': _params(d)}
            # Rebuilding a legacy archive: keep the outcome the run recorded.
            status = meta.get('simulation_status')
            if (d / 'cancelled.json').exists():
                status = 'cancelled'
            if status not in ('success', 'failed', 'cancelled', 'timed_out'):
                status = 'success' if (meta.get('execution') or {}).get('success') else 'failed'
            try:
                paths.append(og.create_omex_archive_from_zarr(
                    d / 'data.zarr', meta, meta.get('parameters', {}),
                    archive_path=existing, creator=creator, status=status))
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


def _export_missing_archives(root, creator=None):
    """Step 1 — export. Give every run DIRECTORY under root an archive (existing
    worker-written archives are kept as they are) and build the experiment-level
    scan archive. This is the only place a working directory is read. Returns the
    scan archive path (or None), and the names of run directories for which no
    archive could be built."""
    dir_combos = discover_combos(root)
    if not dir_combos:
        return None, []
    scan_spec, labels = derive_scan(dir_combos)
    num_replicates = max(len(v) for v in dir_combos.values())
    sim_params = _params(next(iter(dir_combos.values()))[0])
    if creator is None:      # inherit the operator from an existing per-run archive
        for dirs in dir_combos.values():
            for d in dirs:
                o = d / f"{d.name}.omex"
                if o.exists():
                    creator = _creator_from_omex(o)
                    break
            if creator:
                break
    # Every run, whatever its outcome, gets a correctly typed archive (the scan
    # archive filters to successful replicates itself, via og.run_outcome).
    _, scan = _regenerate_archives(dir_combos, labels, scan_spec, sim_params, root,
                                   num_replicates, creator)
    unarchived = [d.name for dirs in dir_combos.values() for d in dirs
                  if not (d / f"{d.name}.omex").exists()]
    return scan, unarchived


def generate(root, creator=None):
    root = Path(root)
    scan, unarchived = _export_missing_archives(root, creator)

    # Step 2 — report, from the archives alone.
    combos = discover_archived_runs(root)
    for name in unarchived:
        combos.setdefault(_combo_key(name), []).append(ArchivedRun(None, name))
    if not combos:
        print(f"[angio_report] no run archives (.omex) or run directories under {root}")
        return []
    archived = {c: [r for r in runs if r.omex is not None] for c, runs in combos.items()}
    archived = {c: runs for c, runs in archived.items() if runs}
    scan_spec, labels = derive_scan(archived) if archived else ({}, {})
    labels = {c: labels.get(c, c) for c in combos}
    first = next(iter(archived.values()))[0] if archived else None
    sim_time = (first.params if first else {}).get('sim_time', 100.0)
    scan = scan or find_scan_archive(root)

    # Results use successful replicates only; the rest are listed, never averaged.
    successful, excluded = {}, {}
    for c, runs in combos.items():
        ok = [r for r in runs if r.status == 'success']
        other = [(r, r.status) for r in runs if r.status != 'success']
        if ok:
            successful[c] = ok
        if other:
            excluded[c] = other

    written = []
    for c in sorted(combos):
        out_pdf = root / f"{c}_omex_report.pdf"
        if c in successful:
            written.append(build_combo_report(c, labels[c], successful[c],
                                              [r.omex for r in successful[c]], sim_time,
                                              out_pdf, excluded=excluded.get(c, [])))
        else:
            written.append(build_excluded_only_report(c, labels[c], excluded.get(c, []), out_pdf))
        print(f"[angio_report] wrote {out_pdf}  ({len(successful.get(c, []))} successful, "
              f"{len(excluded.get(c, []))} excluded replicate(s))")
    if len(combos) > 1 and successful:
        out_pdf = root / f"{root.name}_experiment_report.pdf"
        written.append(build_experiment_report(root, scan, successful, labels, sim_time,
                                               out_pdf, excluded=excluded))
        print(f"[angio_report] wrote {out_pdf}  (comparison across {len(successful)} combos)")
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
