"""
OMEX Archive Generator for vivarium-angio simulations.

Generates standards-compliant SED-ML and COMBINE/OMEX archives for the
angiogenesis CompuCell3D model whose outputs are stored in a Zarr store.

Architectural note
------------------
Unlike vivarium-vcornea (which produces per-run directories of CSV/Parquet
files), the angio process writes the entire simulation trajectory into a
single Zarr store on disk. This generator walks that store as a filesystem
tree and packages it inside the OMEX archive under `zarr/<exp_name>/`,
alongside a `simulation.sedml` and `manifest.xml` at the archive root.

This module is dependency-light: stdlib + xml.etree.ElementTree + zipfile.
No zarr/numpy/pandas imports here so the archive can be produced even if
the consumer of the archive does not have Zarr installed.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


# =============================================================================
# Standards URIs (kept in sync with vivarium-vcornea/omex_generator.py)
# =============================================================================

SEDML_NAMESPACE = "http://sed-ml.org/sed-ml/level1/version4"
SEDML_VERSION_ATTR = "4"
MATHML_NAMESPACE = "http://www.w3.org/1998/Math/MathML"
XHTML_NAMESPACE = "http://www.w3.org/1999/xhtml"
RDF_NAMESPACE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DC_NAMESPACE = "http://purl.org/dc/terms/"

OMEX_MANIFEST_NAMESPACE = "http://identifiers.org/combine.specifications/omex-manifest"
OMEX_METADATA_FORMAT = "http://identifiers.org/combine.specifications/omex-metadata"
NUML_NAMESPACE = "http://www.numl.org/numl/level1/version1"

# KiSAO:0000241 = Metropolis Monte Carlo (CPM/GGH family — used by the
# angiogenesis Cellular Potts model just as it is by the vCornea model).
KISAO_ALGORITHM_ID = "KISAO:0000241"
# Algorithm parameter carrying the RNG seed, so the archived experiment
# description states which stochastic realization the bundled data represents.
# KISAO:0000488 is "seed" (synonym "random seed"), defined as the parameter that
# "allows one to reproduce their results while running the same algorithm on the
# same computer" — verified against the KiSAO ontology via EBI OLS.
KISAO_RANDOM_SEED_ID = "KISAO:0000488"
SEDML_SYMBOL_TIME = "urn:sedml:symbol:time"
MODEL_LANGUAGE_URI = "urn:sedml:language:compucell3d"

# The angiogenesis model's reference paper.
ANGIO_CITATION = (
    "Merks, R.M.H., Brodsky, S.V., Goligorksy, M.S., Newman, S.A., Glazier, J.A. "
    "(2006). Cell elongation is key to in silico replication of in vitro "
    "vasculogenesis and subsequent remodeling. Developmental Biology 289(1), 44-54. "
    "https://doi.org/10.1016/j.ydbio.2005.10.003")

# Standard scalar signals extracted from the Zarr store (Time in MCS + these).
ANGIO_METRIC_COLUMNS = ['num_clusters', 'cell_density', 'largest_cluster_size', 'vegf_mean']
EC_CELL_TYPE = 1   # channel-0 value for endothelial cells (0 = Medium)

FORMAT_URIS = {
    '.sedml': 'http://identifiers.org/combine.specifications/sed-ml.level-1.version-4',
    '.omex': 'http://identifiers.org/combine.specifications/omex',
    '.csv': 'http://purl.org/NET/mediatypes/text/csv',
    '.json': 'http://purl.org/NET/mediatypes/application/json',
    '.txt': 'http://purl.org/NET/mediatypes/text/plain',
    '.log': 'http://purl.org/NET/mediatypes/text/plain',
    '.xml': 'http://purl.org/NET/mediatypes/application/xml',
    '.cc3d': 'http://purl.org/NET/mediatypes/application/xml',
    '.py': 'http://purl.org/NET/mediatypes/text/x-python',
    '.parquet': 'http://purl.org/NET/mediatypes/application/x-parquet',
    # Zarr metadata files (per Zarr v2/v3 spec: hidden JSON files at each node)
    '.zattrs': 'http://purl.org/NET/mediatypes/application/json',
    '.zarray': 'http://purl.org/NET/mediatypes/application/json',
    '.zgroup': 'http://purl.org/NET/mediatypes/application/json',
    '.zmetadata': 'http://purl.org/NET/mediatypes/application/json',
}

DEFAULT_FORMAT_URI = 'http://purl.org/NET/mediatypes/application/octet-stream'

# Files inside a Zarr store that are JSON metadata regardless of suffix
ZARR_METADATA_FILENAMES = {'.zattrs', '.zarray', '.zgroup', '.zmetadata', 'zarr.json'}


# =============================================================================
# Helpers
# =============================================================================

def _safe_sid(raw: str) -> str:
    """Coerce a string into a valid SED-ML SId (NCName-like)."""
    cleaned = []
    for ch in raw:
        if ch.isalnum() or ch == '_':
            cleaned.append(ch)
        else:
            cleaned.append('_')
    out = ''.join(cleaned)
    if not out or not (out[0].isalpha() or out[0] == '_'):
        out = '_' + out
    return out


def _archive_format_for(path_in_archive: str) -> str:
    """Pick a COMBINE format URI for a file inside the archive.

    Zarr stores contain a mixture of JSON metadata files (e.g. `.zattrs`,
    `.zarray`) and binary chunk files with numeric names (e.g. `0.0.0`).
    The metadata files get JSON URIs; chunks fall back to octet-stream.
    """
    name = Path(path_in_archive).name
    if name in ZARR_METADATA_FILENAMES:
        return FORMAT_URIS['.zattrs']
    suffix = Path(path_in_archive).suffix.lower()
    return FORMAT_URIS.get(suffix, DEFAULT_FORMAT_URI)


def _read_v3_array(array_dir):
    """Manual reader for a Zarr v3 array directory (zarr.json + c/<chunk> files).
    Supports the bytes+zstd codec pipeline the angio process writes. Used as a
    fallback when the `zarr` package is the wrong version (v3 store, Python<3.11)."""
    import itertools
    import numpy as np
    from numcodecs import Zstd
    meta = json.loads((array_dir / 'zarr.json').read_text())
    shape = list(meta['shape'])
    chunk = list(meta['chunk_grid']['configuration']['chunk_shape'])
    sep = meta.get('chunk_key_encoding', {}).get('configuration', {}).get('separator', '/')
    little = True
    for c in meta.get('codecs', []):
        if c.get('name') == 'bytes':
            little = c.get('configuration', {}).get('endian', 'little') == 'little'
    dtype = np.dtype('<f8' if little else '>f8')   # angio writes float64
    out = np.full(shape, float(meta.get('fill_value', 0.0)), dtype=dtype)
    z = Zstd()
    nchunks = [-(-shape[d] // chunk[d]) for d in range(len(shape))]
    for coord in itertools.product(*[range(n) for n in nchunks]):
        cf = array_dir.joinpath('c', *[str(c) for c in coord])
        if not cf.exists():
            continue
        arr = np.frombuffer(z.decode(cf.read_bytes()), dtype=dtype).reshape(chunk)
        tgt = tuple(slice(coord[d] * chunk[d], min((coord[d] + 1) * chunk[d], shape[d]))
                    for d in range(len(shape)))
        src = tuple(slice(0, t.stop - t.start) for t in tgt)
        out[tgt] = arr[src]
    return out


def _load_zarr_steps(store):
    """Yield (step:int, data:ndarray) for each timestep group. Tries the `zarr`
    package first; falls back to the manual v3 reader."""
    store = Path(store)
    try:
        import numpy as np
        import zarr
        root = zarr.open(str(store), mode='r')
        steps = sorted(int(k) for k in root.keys() if str(k).isdigit())
        if steps:
            for s in steps:
                try:
                    yield s, np.asarray(root[str(s)]['data'])
                except Exception:
                    continue
            return
    except Exception:
        pass
    # Manual v3 fallback: digit-named group dirs each holding data/zarr.json
    step_dirs = sorted((p for p in store.iterdir() if p.is_dir() and p.name.isdigit()),
                       key=lambda p: int(p.name))
    for p in step_dirs:
        adir = p / 'data'
        if (adir / 'zarr.json').exists():
            try:
                yield int(p.name), _read_v3_array(adir)
            except Exception:
                continue


def extract_zarr_metrics(zarr_store_path):
    """Best-effort scalar time-series from the Zarr store (each timestep `data`
    array is [X,Y,Z,3]: cell-type / cell-id / VEGF). Returns CSV text
    (`Time,<metrics>`) or None if numpy/scipy unavailable or no timestep data."""
    try:
        import numpy as np
        from scipy.ndimage import label
    except Exception:
        return None
    rows = ["Time," + ",".join(ANGIO_METRIC_COLUMNS)]
    for step, data in _load_zarr_steps(zarr_store_path):
        if data is None or data.ndim < 4 or data.shape[-1] < 3:
            continue
        cell_types = data[..., 0]
        vegf = data[..., 2]
        mask = (cell_types == EC_CELL_TYPE)
        total = cell_types.size
        density = (int(mask.sum()) / total) if total else 0.0
        flat = mask
        while flat.ndim > 2:
            flat = flat.squeeze(-1) if flat.shape[-1] == 1 else flat.any(axis=-1)
        try:
            lab, num = label(flat)
            largest = int(np.bincount(lab.ravel())[1:].max()) if num else 0
        except Exception:
            num, largest = 0, 0
        rows.append(f"{step},{num},{density:.6f},{largest},{float(np.mean(vegf)):.6f}")
    return ("\n".join(rows) + "\n") if len(rows) > 1 else None


def _collect_model_source_files():
    """Return ([(src_path, archive_path), ...], primary_archive_path) for the
    first-party Python source that DEFINES the integrated angiogenesis model.

    Unlike the decoupled case there is no .cc3d/CC3DML/PIFF on disk: the model is
    built in Python — AngiogenesisProcess constructs the CC3D specs from the
    parameters and carries the WriterSteppable, and the composer is the run entry
    point — so the actual source IS the model artifact. The primary file (what the
    SED-ML model/@source should resolve to) is the process module."""
    pkg_root = Path(__file__).resolve().parents[1]   # .../vivarium_angio
    candidates = [
        (pkg_root / 'processes' / 'angiogenesis_process.py',
         'model/src/angiogenesis_process.py'),
        (pkg_root / 'composites' / 'angiogenesis_composer.py',
         'model/src/angiogenesis_composer.py'),
    ]
    files = [(p, a) for (p, a) in candidates if p.exists()]
    primary = ('model/src/angiogenesis_process.py' if files
               else 'model/model_summary.json')
    return files, primary


def _collect_model_export(model_export_dir):
    """Discover a `model_export/` staging directory written by the LIVE process at
    run time (AngiogenesisProcess.export_model_export_dir). Returns
    (native_files, live_source_files, native_primary):

      * native_files       — [(abs_path, archive_loc)] for a runnable stock-CC3D
                             project (model/angiogenesis.cc3d + model/Simulation/*),
                             serialized from the live `self.specs` of the run.
      * live_source_files  — [(abs_path, archive_loc)] for the first-party Python
                             source, resolved from the LIVE imported module of the
                             executed process (inspect.getsourcefile), so the embed
                             is pinned to the exact code that ran — never a build/lib
                             shadow copy.
      * native_primary     — 'model/<name>.cc3d' if a native project was exported,
                             else None.

    Empty/(),None when the staging dir is absent (e.g. post-hoc regeneration with
    no live instance) — the caller then falls back to static source resolution."""
    model_export_dir = Path(model_export_dir)
    native_files, live_source_files, native_primary = [], [], None
    if not model_export_dir.exists():
        return native_files, live_source_files, native_primary

    native_root = model_export_dir / 'native'
    if native_root.exists():
        for p in sorted(native_root.rglob('*')):
            if not p.is_file():
                continue
            loc = f"model/{p.relative_to(native_root).as_posix()}"
            native_files.append((p, loc))
            if p.suffix == '.cc3d':
                native_primary = loc

    ls = model_export_dir / 'live_source.json'
    if ls.exists():
        try:
            info = json.loads(ls.read_text())
            for abs_path, loc in info.get('files', []):
                ap = Path(abs_path)
                if ap.exists():
                    live_source_files.append((ap, loc))
        except Exception:
            pass
    return native_files, live_source_files, native_primary


# The outcomes an archive can record. Cancellation is deliberately NOT folded into
# 'failed': a reviewer reading a batch needs to distinguish a model that misbehaved
# from a run an operator chose to stop, and only the first is evidence about the
# model. Each carries its own reader-facing explanation.
_ARCHIVE_STATUSES = {
    'success': ('Run completed successfully; simulation.sedml is the executable '
                'master describing the reproducible experiment.'),
    'failed': ('This run did NOT complete successfully. The archive preserves '
               'parameters, provenance, logs and any partial outputs for audit, '
               'but intentionally contains no executable SED-ML and asserts no '
               'reproducible experiment.'),
    'cancelled': ('This run was interrupted by the operator before completion. It '
                  'is not a failure of the model: no conclusion about model '
                  'behaviour should be drawn from it. The archive preserves the '
                  'intended parameters, provenance, logs and any partial outputs '
                  'produced before the interruption, and contains no executable '
                  'SED-ML.'),
    'timed_out': ('This run exceeded its wall-clock limit and was terminated before '
                  'completion. The archive preserves the intended parameters, '
                  'provenance, logs, the limit that applied and any partial outputs '
                  'produced before termination, and contains no executable SED-ML.'),
}


def _provenance_block(provenance):
    """Compact, self-describing code/schema identity for embedding in JSON artifacts.

    Returns None when nothing was captured, so a consumer can distinguish "not
    recorded" from "recorded as unknown".
    """
    prov = provenance or {}
    code = prov.get('code') or {}
    if not (code or prov.get('schema_fingerprint')):
        return None
    return {
        'code_revision': code.get('describe') or code.get('commit_short'),
        'commit': code.get('commit'),
        'commit_url': code.get('commit_url'),
        'working_tree_modified': code.get('dirty'),
        'revision_retrievable': code.get('commit_on_remote'),
        'identity_source': code.get('source'),
        'schema_fingerprint': prov.get('schema_fingerprint'),
        'note': ('code_revision identifies the source revision that produced this '
                 'archive; schema_fingerprint identifies the parameter definitions '
                 'the run was configured under. A modified working tree or an '
                 'unretrievable revision is reported rather than hidden.'),
    }


def generate_environment_manifest(provenance=None):
    """Best-effort pinned environment descriptor: the package versions needed to
    re-execute the embedded model source. The integrated model depends on
    CompuCell3D + vivarium packages that cannot be embedded as bytes, so they are
    *named* here for the reviewer to reconstruct the runtime."""
    import platform
    pkgs = ['cc3d', 'vivarium-core', 'vivarium-angio', 'zarr', 'numcodecs',
            'numpy', 'scipy', 'pandas']
    versions = {}
    try:
        from importlib.metadata import version
    except Exception:
        version = None
    for name in pkgs:
        v = None
        if version is not None:
            try:
                v = version(name)
            except Exception:
                v = None
        if v is None:
            # conda-installed packages (notably CompuCell3D) may carry no
            # importlib.metadata distribution record; fall back to the module's
            # own __version__ so the most important dependency is not reported
            # as 'unknown'.
            try:
                mod = __import__(name.replace('-', '_'))
                v = getattr(mod, '__version__', None)
            except Exception:
                v = None
        versions[name] = v or 'unknown'
    return json.dumps({
        'python_version': platform.python_version(),
        'platform': platform.platform(),
        'packages': versions,
        # Which revision of the first-party code this environment was executing.
        # Belongs here as much as the third-party versions do: "what you need to
        # reproduce this" is the packages AND the model source revision.
        'code': _provenance_block(provenance),
        'note': ('These packages must be installed to re-execute the embedded model '
                 'source. They are named, not embedded; see model/run_model.py.'),
    }, indent=2, default=str)


# A self-contained driver that re-executes the model from the bundled parameters,
# mirroring the path the GUI worker uses (Engine + AngiogenesisComposer).
_RUN_MODEL_SCRIPT = '''"""Re-run the integrated angiogenesis model from this OMEX archive.

Prerequisites: install the packages named in environment.json (CompuCell3D,
vivarium-core, vivarium-angio). Then, with model/src on PYTHONPATH, run:

    python run_model.py

This reconstructs the run from run_params.json using the same Vivarium
Engine + AngiogenesisComposer path the GUI uses.
"""
import json
from pathlib import Path

from vivarium.core.engine import Engine
from vivarium_angio.composites.angiogenesis_composer import AngiogenesisComposer

params = json.loads((Path(__file__).parent / "run_params.json").read_text())
composer = AngiogenesisComposer({"angiogenesis_process": params})
engine = Engine(composite=composer.generate())
engine.update(params.get("sim_time", 100.0))
print("Re-run complete.")
'''


def generate_run_model_script():
    """The model/run_model.py re-run driver (see _RUN_MODEL_SCRIPT)."""
    return _RUN_MODEL_SCRIPT


# Exact wording of the output-cadence caveat for the exported native CC3D project.
# Stated verbatim in model_summary.json whenever a native .cc3d is bundled.
NATIVE_CADENCE_CAVEAT = (
    "The exported native CC3D project (model/angiogenesis.cc3d) reproduces the archived "
    "run's model, random seed, and number of Monte Carlo steps, so re-executing it "
    "reproduces the same trajectory. It supplies output through a CC3D-native "
    "frequency-based dumper steppable substituted for the Vivarium-directed "
    "WriterSteppable used in the archived run, writing .npy snapshots under "
    "native_output/ rather than the Zarr hierarchy. The on-disk output format therefore "
    "differs from the archived trajectory even though the dynamics it records do not.")


def generate_model_summary(run_metadata, sim_params, *, artifact_files=None,
                           native_primary=None, status='success',
                           source_provenance='static'):
    """Human-readable index for the embedded model artifact.

    The integrated angio model is built in Python. The re-runnable artifact is the
    bundled Python source under model/src/ (+ run_params.json, environment.json,
    run_model.py) and, when it could be serialized from the live run, a runnable
    native CC3D project (model/angiogenesis.cc3d). This summary indexes them and
    states the re-run contract, the native-output cadence caveat, and how the
    embedded source was resolved."""
    has_native = bool(native_primary)
    summary = {
        'model_name': run_metadata.get('model_name', 'Angiogenesis'),
        # A declared, hand-maintained version: a statement about the model's
        # scientific content, deliberately NOT advanced by every code change.
        # `provenance` below is the machine-checkable identity.
        'model_version': run_metadata.get('model_version', '1.0.0'),
        'provenance': _provenance_block(run_metadata.get('provenance')),
        'model_type': 'Cellular Potts model (CompuCell3D / vivarium process)',
        'process': 'vivarium_angio.processes.angiogenesis_process.AngiogenesisProcess',
        'simulation_status': status,
        'artifact_type': ('native_cc3d_project+python_source' if has_native
                          else 'python_source'),
        # How the embedded model/src/*.py was resolved: 'live' = pinned to the exact
        # imported module of the executed process (inspect.getsourcefile); 'static' =
        # best-effort resolution from the generator's own location (no live instance).
        'source_provenance': source_provenance,
        'model_source_files': [a for (_p, a) in (artifact_files or [])],
        'entry_point': 'model/run_model.py',
        'resolved_parameters': 'model/run_params.json',
        'environment': 'model/environment.json',
        'rerun': {
            'reproducible_from_archive': 'native+partial' if has_native else 'partial',
            'how': ('Install the packages listed in environment.json, put model/src '
                    'on PYTHONPATH, then run model/run_model.py (it reads '
                    'run_params.json).'),
            'limitation': ('This model is defined in Python and depends on the '
                           'CompuCell3D + vivarium_angio packages, which are named in '
                           'environment.json rather than embedded as bytes. The archive '
                           'carries the complete model definition and the exact '
                           'parameters, not the full Python runtime.'),
        },
        'note': ('The model is encoded in the Python angiogenesis process. The bundled '
                 'source + parameters identify and reconstruct the exact model; full '
                 'trajectory data is under zarr/.'),
        'schema_version': run_metadata.get('schema_version', '1.0'),
        'reference': ANGIO_CITATION,
        'parameters': sim_params,
    }
    if has_native:
        summary['native_project'] = {
            'entry_point': native_primary,
            'runnable_with': 'stock cc3d.run_script (no vivarium import required)',
            'output_mechanism': ('native frequency-based dumper steppable '
                                 '(NativeDumperSteppable) substituted for the '
                                 'Vivarium-directed WriterSteppable'),
            'cadence_caveat': NATIVE_CADENCE_CAVEAT,
        }
        summary['rerun']['native'] = (
            'Open model/angiogenesis.cc3d with stock CompuCell3D '
            '(e.g. `python -m cc3d.run_script -i model/angiogenesis.cc3d -o out`). '
            'No vivarium/zarr required; output via the native dumper. ' + NATIVE_CADENCE_CAVEAT)
    return json.dumps(summary, indent=2, default=str)


def generate_omex_metadata_rdf(*, title, description=None, created=None, modified=None,
                               creators=None, license_uri=None, citation=None,
                               keywords=None, about='.', provenance=None):
    """OMEX-Metadata RDF/XML (Dublin Core + vCard). Provenance/attribution.

    Code and schema identity are emitted here as well as in run_metadata.json,
    because this is the standards-native location: a COMBINE-aware reader inspects
    metadata.rdf, and should not have to parse an application-specific JSON file to
    learn which revision produced the archive. Mapping:

        dcterms:hasVersion  -> the code revision (release-anchored where tagged)
        dcterms:source      -> a retrievable link to that revision
        dcterms:conformsTo  -> the schema fingerprint the run was configured under
    """
    RDF = RDF_NAMESPACE
    DCT = DC_NAMESPACE
    VC = "http://www.w3.org/2006/vcard/ns#"
    ET.register_namespace('rdf', RDF)
    ET.register_namespace('dcterms', DCT)
    ET.register_namespace('vCard', VC)
    root = ET.Element('{%s}RDF' % RDF)
    desc = ET.SubElement(root, '{%s}Description' % RDF)
    desc.set('{%s}about' % RDF, about)

    def add(tag, text):
        ET.SubElement(desc, '{%s}%s' % (DCT, tag)).text = str(text)

    add('title', title)
    if description:
        add('description', description)
    for c in (creators or []):
        cr = ET.SubElement(desc, '{%s}creator' % DCT)
        li = ET.SubElement(cr, '{%s}Description' % RDF)
        nm = ET.SubElement(li, '{%s}hasName' % VC)
        nmd = ET.SubElement(nm, '{%s}Description' % RDF)
        if c.get('family'):
            ET.SubElement(nmd, '{%s}family-name' % VC).text = c['family']
        if c.get('given'):
            ET.SubElement(nmd, '{%s}given-name' % VC).text = c['given']
        if c.get('email'):
            ET.SubElement(li, '{%s}hasEmail' % VC).text = c['email']
        if c.get('orcid'):
            ET.SubElement(li, '{%s}identifier' % DCT).text = c['orcid']
    for tag, val in (('created', created), ('modified', modified or created)):
        if val:
            e = ET.SubElement(desc, '{%s}%s' % (DCT, tag))
            ET.SubElement(e, '{%s}W3CDTF' % DCT).text = str(val)
    if license_uri:
        add('license', license_uri)
    if citation:
        add('bibliographicCitation', citation)
    for kw in (keywords or []):
        add('subject', kw)

    prov = provenance or {}
    code = prov.get('code') or {}
    version = code.get('describe') or code.get('commit_short') or code.get('commit')
    if version:
        # Flagged when the tree did not match the revision, so the version string
        # is never read as a complete description of what ran.
        add('hasVersion', f"{version} (modified working tree)" if code.get('dirty') else version)
    if code.get('commit_url'):
        # Emitted only when the guard confirmed the revision is retrievable; see
        # provenance.code_provenance.
        add('source', code['commit_url'])
    if prov.get('schema_fingerprint'):
        add('conformsTo', prov['schema_fingerprint'])
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')


# =============================================================================
# SED-ML generation (angio-specific)
# =============================================================================

def generate_sedml_document(
    run_metadata: Dict[str, Any],
    sim_params: Dict[str, Any],
    zarr_archive_root: str,
    model_source: str = "model/model_summary.json",
    metric_columns: Optional[List[str]] = None,
    metrics_source: str = "metrics.csv",
) -> str:
    """Build a SED-ML L1V4 document describing one angio run.

    model/@source points at the bundled model_summary.json. When metric_columns is
    given, the scalar time-series extracted from the Zarr store (metrics.csv) are
    indexed as dataDescriptions/dataGenerators and exposed in the report, so the
    SED-ML actually references the run's signals (not just time).
    """
    ET.register_namespace('', SEDML_NAMESPACE)
    ET.register_namespace('html', XHTML_NAMESPACE)
    ET.register_namespace('rdf', RDF_NAMESPACE)
    ET.register_namespace('dc', DC_NAMESPACE)
    ET.register_namespace('math', MATHML_NAMESPACE)
    ET.register_namespace('numl', NUML_NAMESPACE)

    root = ET.Element('sedML')
    root.set('xmlns', SEDML_NAMESPACE)
    root.set('level', '1')
    root.set('version', SEDML_VERSION_ATTR)

    exp_name = run_metadata.get('parameters', {}).get('exp_name') \
        or run_metadata.get('exp_name', 'angio_run')
    created_at = (run_metadata.get('created_at') or run_metadata.get('timestamp')
                  or datetime.now().isoformat())
    sim_time = float(sim_params.get('sim_time', 100.0))
    write_freq = float(sim_params.get('write_frequency', 10.0))
    n_steps = max(int(round(sim_time / write_freq)), 1) if write_freq > 0 else int(sim_time)
    metric_columns = metric_columns or []

    n_replicates = run_metadata.get('total_replicates', 1)
    scan_spec = run_metadata.get('parameter_scan')
    scan_point = run_metadata.get('scan_point')
    combo_index = run_metadata.get('combination_index')
    total_combos = run_metadata.get('total_combinations')
    # Resolved before the notes are written because both the human-readable notes
    # and the executable algorithmParameter below report it.
    seed = sim_params.get('random_seed', run_metadata.get('random_seed'))

    # Document notes
    notes = ET.SubElement(root, 'notes')
    body = ET.SubElement(notes, '{%s}body' % XHTML_NAMESPACE)
    info = [
        f"Angiogenesis Cellular Potts Simulation: {exp_name}",
        f"Created: {created_at}",
        f"Simulation time: {sim_time} MCS (time is in MCS; angio has no physical-time "
        f"calibration). Output every {write_freq} MCS -> {n_steps} steps.",
        f"Zarr trajectory under: {zarr_archive_root} (spatial ndarrays per timestep).",
        ("Scalar signals indexed from metrics.csv: " + ", ".join(metric_columns) + "."
         if metric_columns else
         "No scalar metrics indexed (extractor unavailable); see zarr/ for full data."),
    ]
    if scan_spec:
        dims = "; ".join(f"{p} in {list(v)}" for p, v in scan_spec.items())
        pt = ", ".join(f"{k}={v}" for k, v in (scan_point or {}).items()) or "see parameters"
        pos = f" (point {combo_index} of {total_combos})" if combo_index and total_combos else ""
        info += ["",
                 f"PARAMETER SCAN: this archive holds ONE point of a scan{pos}. This "
                 f"run's swept values: {pt}. Full scan space: {dims}. The executable "
                 "scan description lives in the experiment-level scan archive."]
    # State the seed as recorded fact. Previously this asserted "different seed"
    # for every replicate without the seed being set or captured anywhere — a
    # provenance claim the archive could not support.
    if seed is not None and str(seed) != '-1':
        info += [f"Random number generator seed: {seed} (recorded as SED-ML "
                 f"algorithmParameter {KISAO_RANDOM_SEED_ID}). The Cellular Potts "
                 "algorithm is stochastic; this seed identifies the realization "
                 "the bundled data represents."]
    else:
        info += ["Random number generator seed: not recorded for this run, so the "
                 "trajectory cannot be replayed exactly; compare replicate "
                 "distributions rather than individual trajectories."]
    if n_replicates and n_replicates > 1:
        info += [f"Replicate {run_metadata.get('replicate_id', '?')} of {n_replicates}: "
                 "identical parameters, distinct seed per replicate."]

    prov = run_metadata.get('provenance') or {}
    if prov.get('schema_fingerprint') or prov.get('code'):
        code = prov.get('code') or {}
        bits = [f"schema fingerprint {prov.get('schema_fingerprint', 'unrecorded')}"]
        if code.get('source') == 'git':
            bits.append(f"code commit {code.get('commit', '?')}"
                        + (" (working tree modified — commit does not fully describe "
                           "the code that ran)" if code.get('dirty') else ''))
            if code.get('commit_url'):
                bits.append(f"source: {code['commit_url']}")
        elif code.get('source') == 'build_stamp':
            bits.append(f"built from commit {code.get('commit', '?')}")
        info += ["", "RUN IDENTITY: " + "; ".join(bits) + "."]
    for line in info:
        p = ET.SubElement(body, '{%s}p' % XHTML_NAMESPACE)
        p.text = line

    # Model
    list_of_models = ET.SubElement(root, 'listOfModels')
    model = ET.SubElement(list_of_models, 'model')
    model.set('id', 'model_angio')
    model.set('name', 'Angiogenesis Cellular Potts Model')
    model.set('source', model_source)
    model.set('language', MODEL_LANGUAGE_URI)

    annotation = ET.SubElement(model, 'annotation')
    rdf = ET.SubElement(annotation, '{%s}RDF' % RDF_NAMESPACE)
    desc = ET.SubElement(rdf, '{%s}Description' % RDF_NAMESPACE)
    desc.set('{%s}about' % RDF_NAMESPACE, '#model_angio')
    relation = ET.SubElement(desc, '{%s}relation' % DC_NAMESPACE)
    relation.set('{%s}resource' % RDF_NAMESPACE, zarr_archive_root)

    # Simulation
    list_of_sims = ET.SubElement(root, 'listOfSimulations')
    sim = ET.SubElement(list_of_sims, 'uniformTimeCourse')
    sim.set('id', 'sim_mcs')
    sim.set('initialTime', '0')
    sim.set('outputStartTime', '0')
    sim.set('outputEndTime', str(sim_time))
    sim.set('numberOfSteps', str(n_steps))

    algorithm = ET.SubElement(sim, 'algorithm')
    algorithm.set('kisaoID', KISAO_ALGORITHM_ID)

    # The RNG seed is part of the executable description, not just a note: it
    # identifies which realization of the stochastic process this archive holds.
    # Omitted (rather than guessed) when the run predates seed capture.
    if seed is not None and str(seed) != '-1':
        algo_params = ET.SubElement(algorithm, 'listOfAlgorithmParameters')
        seed_param = ET.SubElement(algo_params, 'algorithmParameter')
        seed_param.set('kisaoID', KISAO_RANDOM_SEED_ID)
        seed_param.set('value', str(seed))

    # Task
    list_of_tasks = ET.SubElement(root, 'listOfTasks')
    task = ET.SubElement(list_of_tasks, 'task')
    task.set('id', 'task_main')
    task.set('modelReference', 'model_angio')
    task.set('simulationReference', 'sim_mcs')

    # listOfDataDescriptions: index metrics.csv (Time + the scalar signals) so the
    # SED-ML references the run's real signals, not just simulation time.
    metric_dg = {}        # column -> dataGenerator id
    if metric_columns:
        list_of_dd = ET.SubElement(root, 'listOfDataDescriptions')
        dd = ET.SubElement(list_of_dd, 'dataDescription')
        dd.set('id', 'data_metrics')
        dd.set('name', 'Scalar network/VEGF metrics over time')
        dd.set('source', metrics_source)
        dd.set('format', 'urn:sedml:format:csv')
        note = ET.SubElement(ET.SubElement(dd, 'notes'), '{%s}body' % XHTML_NAMESPACE)
        ET.SubElement(note, '{%s}p' % XHTML_NAMESPACE).text = (
            "Columns: Time, " + ", ".join(metric_columns))
        dim = ET.SubElement(dd, 'dimensionDescription')
        outer = ET.SubElement(dim, '{%s}compositeDescription' % NUML_NAMESPACE)
        outer.set('indexType', 'integer'); outer.set('id', 'rowIdx'); outer.set('name', 'Row')
        inner = ET.SubElement(outer, '{%s}compositeDescription' % NUML_NAMESPACE)
        inner.set('indexType', 'string'); inner.set('id', 'columnIds'); inner.set('name', 'Column')
        at = ET.SubElement(inner, '{%s}atomicDescription' % NUML_NAMESPACE)
        at.set('valueType', 'double'); at.set('id', 'value'); at.set('name', 'Value')
        los = ET.SubElement(dd, 'listOfDataSources')
        for col in ['Time'] + list(metric_columns):
            dsid = _safe_sid(f"ds_metrics_{col}")
            dsrc = ET.SubElement(los, 'dataSource'); dsrc.set('id', dsid); dsrc.set('name', col)
            sl = ET.SubElement(ET.SubElement(dsrc, 'listOfSlices'), 'slice')
            sl.set('reference', 'columnIds'); sl.set('value', col)

    # Data generators: time + one per indexed metric column.
    list_of_dgs = ET.SubElement(root, 'listOfDataGenerators')
    dg_time = ET.SubElement(list_of_dgs, 'dataGenerator')
    dg_time.set('id', 'dg_time'); dg_time.set('name', 'Simulation Time (MCS)')
    var = ET.SubElement(ET.SubElement(dg_time, 'listOfVariables'), 'variable')
    var.set('id', 'var_time'); var.set('taskReference', 'task_main')
    var.set('symbol', SEDML_SYMBOL_TIME)
    ET.SubElement(ET.SubElement(dg_time, '{%s}math' % MATHML_NAMESPACE),
                  '{%s}ci' % MATHML_NAMESPACE).text = 'var_time'
    for col in metric_columns:
        dgid = _safe_sid(f"dg_metrics_{col}")
        dg = ET.SubElement(list_of_dgs, 'dataGenerator')
        dg.set('id', dgid); dg.set('name', col)
        v = ET.SubElement(ET.SubElement(dg, 'listOfVariables'), 'variable')
        vid = _safe_sid(f"var_metrics_{col}")
        v.set('id', vid); v.set('target', f"#{_safe_sid(f'ds_metrics_{col}')}")
        ET.SubElement(ET.SubElement(dg, '{%s}math' % MATHML_NAMESPACE),
                      '{%s}ci' % MATHML_NAMESPACE).text = vid
        metric_dg[col] = dgid

    # Report: time + each metric series.
    list_of_outputs = ET.SubElement(root, 'listOfOutputs')
    report = ET.SubElement(list_of_outputs, 'report')
    report.set('id', 'report_main'); report.set('name', f"Angio outputs: {exp_name}")
    lod = ET.SubElement(report, 'listOfDataSets')
    ds = ET.SubElement(lod, 'dataSet')
    ds.set('id', 'ds_time'); ds.set('label', 'Time (MCS)'); ds.set('dataReference', 'dg_time')
    for col, dgid in metric_dg.items():
        d = ET.SubElement(lod, 'dataSet')
        d.set('id', _safe_sid(f"ds_out_{col}")); d.set('label', col); d.set('dataReference', dgid)

    xml_str = ET.tostring(root, encoding='unicode', method='xml')
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str


# =============================================================================
# Manifest generation (same shape as vivarium-vcornea)
# =============================================================================

def generate_omex_manifest(
    files: List[Dict[str, str]],
    sedml_location: str = "simulation.sedml",
) -> str:
    """Build a manifest.xml listing the archive root and every content file."""
    ET.register_namespace('', OMEX_MANIFEST_NAMESPACE)

    root = ET.Element('omexManifest')
    root.set('xmlns', OMEX_MANIFEST_NAMESPACE)

    root_content = ET.SubElement(root, 'content')
    root_content.set('location', '.')
    root_content.set('format', FORMAT_URIS['.omex'])

    for file_info in files:
        location = file_info['location']
        format_uri = file_info.get('format') or _archive_format_for(location)
        content = ET.SubElement(root, 'content')
        content.set('location', location)
        content.set('format', format_uri)
        if location == sedml_location:
            content.set('master', 'true')

    xml_str = ET.tostring(root, encoding='unicode', method='xml')
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str


# =============================================================================
# Archive packaging
# =============================================================================

def create_omex_archive_from_zarr(
    zarr_store_path: Union[str, Path],
    run_metadata: Dict[str, Any],
    sim_params: Dict[str, Any],
    archive_path: Optional[Union[str, Path]] = None,
    exp_name: Optional[str] = None,
    creator: Optional[Dict[str, str]] = None,
    license_uri: str = "https://spdx.org/licenses/CC-BY-4.0.html",
    citation: str = ANGIO_CITATION,
    keywords: Optional[List[str]] = None,
    logs_dir: Optional[Union[str, Path]] = None,
    failed: bool = False,
    model_export_dir: Optional[Union[str, Path]] = None,
    status: Optional[str] = None,
    parameter_audit: Optional[Dict[str, Any]] = None,
) -> Path:
    """Package a run into an OMEX archive (successful OR failed).

    Self-contained + indexed. A SUCCESSFUL archive co-locates the five-item audit
    record: (i) parameterization + provenance metadata (run_metadata.json,
    sim_params.json, metadata.rdf), (ii) execution logs, (iii) raw outputs (the Zarr
    trajectory + metrics.csv), (iv) the model artifact, and (v) a manifest typing
    every entry. An executable SED-ML (uniformTimeCourse + algorithm) is the master.

    The model artifact is re-runnable, not just descriptive: the first-party Python
    source under model/src/ (+ a re-run driver, resolved parameters and a pinned
    environment descriptor) and — when the live process captured it at run time
    (`model_export/`, see AngiogenesisProcess.export_model_export_dir) — a runnable
    native stock-CC3D project (model/angiogenesis.cc3d + model/Simulation/*),
    serialized from the live `self.specs` of the run. When a native project is
    present model/@source resolves to it; otherwise to the bundled Python source.
    The embedded source is pinned to the LIVE imported module of the executed
    process when `model_export/` is present, falling back to best-effort static
    resolution otherwise (recorded as source_provenance in model_summary.json).

    FAILED archive (`failed=True`): same container and typed manifest, carrying
    params/provenance, logs, and any partial outputs that exist, but marked failed
    and WITHOUT asserting a reproducible experiment — the executable SED-ML is
    omitted entirely (so a consumer cannot mistake it for a completed run), a
    machine-readable status.json is added, run_metadata.simulation_status='failed',
    and the provenance RDF states the failure. A failed run tolerates a missing or
    partial Zarr store.

    Logs are best-effort: `logs_dir` defaults to `<zarr parent>/logs`; absent → omitted.

    Returns the created .omex Path.
    """
    # Three outcomes, not two. `status` is authoritative when given; `failed` is
    # retained for callers that predate cancellation being first class. An
    # interrupted run is NOT a failure — the model did not misbehave, the operator
    # stopped it — and requirement 2.5.4 names interrupted attempts alongside
    # failed and timed-out ones as needing the same run identity.
    status = status or ('failed' if failed else 'success')
    if status not in _ARCHIVE_STATUSES:
        raise ValueError(f"unknown archive status {status!r}; "
                         f"expected one of {sorted(_ARCHIVE_STATUSES)}")
    complete = status == 'success'
    failed = not complete  # keep downstream conditionals honest

    zarr_store_path = Path(zarr_store_path).resolve()
    zarr_exists = zarr_store_path.exists()
    if not zarr_exists and complete:
        raise FileNotFoundError(f"Zarr store not found: {zarr_store_path}")

    # Execution logs live alongside the Zarr store under <exp_dir>/logs by default
    # (see angio-gui SimulationWorker). Collect any *.log files best-effort.
    if logs_dir is None:
        logs_dir = zarr_store_path.parent / 'logs'
    logs_dir = Path(logs_dir)
    log_files = (sorted(p for p in logs_dir.glob('*.log') if p.is_file())
                 if logs_dir.exists() else [])

    # Native model export staging dir, written by the LIVE process at run time.
    # Auto-discover alongside the Zarr store unless an explicit path is given.
    if model_export_dir is None:
        model_export_dir = zarr_store_path.parent / 'model_export'
    native_files, live_source_files, native_primary = _collect_model_export(model_export_dir)

    # Source-of-truth for the embedded Python source: the LIVE module path when the
    # process captured it, else best-effort static resolution from this generator's
    # own location (no live instance available — e.g. post-hoc regeneration).
    if live_source_files:
        model_source_files = live_source_files
        source_provenance = 'live'
    else:
        model_source_files, _ = _collect_model_source_files()
        source_provenance = 'static'

    # model/@source priority: native .cc3d > primary Python source > summary.
    if native_primary:
        model_primary_source = native_primary
    elif model_source_files:
        model_primary_source = model_source_files[0][1]
    else:
        model_primary_source = 'model/model_summary.json'

    exp_name = (
        exp_name or sim_params.get('exp_name')
        or run_metadata.get('parameters', {}).get('exp_name')
        or zarr_store_path.stem or 'angio_run')

    if archive_path is None:
        archive_path = zarr_store_path.parent / f"{exp_name}.omex"
    archive_path = Path(archive_path).resolve()
    zarr_prefix_in_archive = f"zarr/{exp_name}"

    # Scalar metrics (best-effort) + the columns the SED-ML should index. A failed
    # run is not indexed as an executable experiment, so metrics are skipped there.
    metrics_csv = extract_zarr_metrics(zarr_store_path) if (zarr_exists and not failed) else None
    metric_columns = ANGIO_METRIC_COLUMNS if metrics_csv else []

    # Stamp the machine-readable failure status onto the provenance record.
    run_metadata = {**run_metadata, 'simulation_status': status}

    # OMEX Metadata (provenance) — the description states the run status explicitly.
    cr = creator or run_metadata.get('creator')
    creators = ([cr] if isinstance(cr, dict) else [{'given': str(cr)}] if cr else [])
    status_phrase = {
        'success': "completed run",
        'failed': "FAILED run (incomplete; not a reproducible experiment)",
        'cancelled': ("CANCELLED run (interrupted by the operator; incomplete and not "
                      "evidence about model behaviour)"),
        'timed_out': ("TIMED-OUT run (terminated at its wall-clock limit; incomplete, "
                      "not a reproducible experiment)"),
    }[status]
    status_tag = {'success': "", 'failed': " [FAILED]", 'cancelled': " [CANCELLED]",
                  'timed_out': " [TIMED OUT]"}[status]
    metadata_rdf = generate_omex_metadata_rdf(
        title=f"Angiogenesis simulation: {exp_name}{status_tag}",
        description=(f"Cellular Potts angiogenesis {status_phrase}: '{exp_name}'. "
                     f"sim_time={sim_params.get('sim_time')} MCS. Scalar signals: "
                     + (", ".join(metric_columns) if metric_columns else "none indexed")),
        created=run_metadata.get('created_at') or run_metadata.get('timestamp'),
        modified=datetime.now().isoformat(),
        creators=creators, license_uri=license_uri, citation=citation,
        keywords=keywords or ['angiogenesis', 'vasculogenesis', 'cellular Potts model',
                              'VEGF', 'agent-based model'],
        provenance=run_metadata.get('provenance'))

    manifest_entries: List[Dict[str, str]] = []

    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 1. simulation.sedml (master) — ONLY for successful runs. A failed run omits
        #    the executable SED-ML so a consumer cannot mistake it for a completed,
        #    reproducible experiment (no uniformTimeCourse claiming the run finished).
        if not failed:
            sedml_content = generate_sedml_document(
                run_metadata=run_metadata, sim_params=sim_params,
                zarr_archive_root=zarr_prefix_in_archive,
                model_source=model_primary_source,
                metric_columns=metric_columns)
            zf.writestr('simulation.sedml', sedml_content)
            manifest_entries.append({'location': 'simulation.sedml', 'format': FORMAT_URIS['.sedml']})

        # 2. metadata.rdf — provenance
        zf.writestr('metadata.rdf', metadata_rdf)
        manifest_entries.append({'location': 'metadata.rdf', 'format': OMEX_METADATA_FORMAT})

        # 2b. status.json — unambiguous machine-readable run status. This is the
        #     primary signal a consumer uses to tell a failed archive from a success.
        status_doc = {
            'status': status,
            'simulation_success': complete,
            # Recorded separately from `status` so a consumer can act on the
            # distinction without knowing the vocabulary: an interrupted run is
            # incomplete but says nothing about the model.
            'interrupted_by_operator': status == 'cancelled',
            'executable_sedml_present': complete,
            'final_mcs': run_metadata.get('final_mcs') or run_metadata.get('final_step'),
            'exp_name': exp_name,
            'run_id': run_metadata.get('run_id'),
            'exit_code': run_metadata.get('exit_code'),
            'timed_out': status == 'timed_out',
            'timeout_seconds': run_metadata.get('run_timeout_seconds'),
            'started_at': run_metadata.get('started_at'),
            'duration_seconds': run_metadata.get('duration_seconds'),
            'cancelled_at': run_metadata.get('cancelled_at'),
            'note': _ARCHIVE_STATUSES[status],
        }
        zf.writestr('status.json', json.dumps(status_doc, indent=2, default=str))
        manifest_entries.append({'location': 'status.json', 'format': FORMAT_URIS['.json']})

        # 3. The model artifact (re-runnable, not just descriptive):
        #    3a. native stock-CC3D project serialized from the live run (if captured)
        for src_path, archive_loc in native_files:
            zf.write(src_path, archive_loc)
            manifest_entries.append({'location': archive_loc})  # format auto-typed
        #    3b. the actual model source under model/src/ (pinned to live module
        #        when source_provenance == 'live')
        for src_path, archive_loc in model_source_files:
            zf.write(src_path, archive_loc)
            manifest_entries.append({'location': archive_loc, 'format': FORMAT_URIS['.py']})
        #    3c. resolved parameters the re-run driver consumes
        zf.writestr('model/run_params.json', json.dumps(sim_params, indent=2, default=str))
        manifest_entries.append({'location': 'model/run_params.json', 'format': FORMAT_URIS['.json']})
        #    3d. pinned environment descriptor (what to install to re-run)
        zf.writestr('model/environment.json',
                    generate_environment_manifest(run_metadata.get('provenance')))
        manifest_entries.append({'location': 'model/environment.json', 'format': FORMAT_URIS['.json']})

        #    3d'. parameter_audit.json — what the schema documents about every
        #    executed value (default vs. run value, position against the
        #    admissible / evidence-supported / recommended ranges, and the
        #    evidence behind each bound). Built where the live schema exists
        #    (GUI main window or Process.finish) — see utils/parameter_audit.py.
        if parameter_audit:
            zf.writestr('model/parameter_audit.json',
                        json.dumps(parameter_audit, indent=2, default=str))
            manifest_entries.append({'location': 'model/parameter_audit.json', 'format': FORMAT_URIS['.json']})
        #    3e. self-contained re-run driver
        zf.writestr('model/run_model.py', generate_run_model_script())
        manifest_entries.append({'location': 'model/run_model.py', 'format': FORMAT_URIS['.py']})
        #    3f. model_summary.json — human-readable index over the above
        zf.writestr('model/model_summary.json',
                    generate_model_summary(run_metadata, sim_params,
                                           artifact_files=model_source_files,
                                           native_primary=native_primary,
                                           status=status,
                                           source_provenance=source_provenance))
        manifest_entries.append({'location': 'model/model_summary.json', 'format': FORMAT_URIS['.json']})

        # 4. metrics.csv — scalar signals indexed by the SED-ML (success only)
        if metrics_csv:
            zf.writestr('metrics.csv', metrics_csv)
            manifest_entries.append({'location': 'metrics.csv', 'format': FORMAT_URIS['.csv']})

        # 5. run_metadata.json — authoritative provenance (carries simulation_status)
        zf.writestr('run_metadata.json', json.dumps(run_metadata, indent=2, default=str))
        manifest_entries.append({'location': 'run_metadata.json'})

        # 6. sim_params.json — exact parameters used
        zf.writestr('sim_params.json', json.dumps(sim_params, indent=2, default=str))
        manifest_entries.append({'location': 'sim_params.json'})

        # 7. Execution logs (stdout/stderr/errors) — typed like every other entry
        for log_path in log_files:
            archive_loc = f"logs/{log_path.name}"
            zf.write(log_path, archive_loc)
            manifest_entries.append({'location': archive_loc, 'format': FORMAT_URIS['.log']})

        # 8. The Zarr store (any partial outputs that exist), packed under zarr/<exp_name>/
        if zarr_exists:
            for file_path in sorted(zarr_store_path.rglob('*')):
                if not file_path.is_file():
                    continue
                rel = file_path.relative_to(zarr_store_path)
                archive_loc = f"{zarr_prefix_in_archive}/{rel.as_posix()}"
                zf.write(file_path, archive_loc)
                manifest_entries.append({
                    'location': archive_loc,
                    'format': _archive_format_for(archive_loc),
                })

        # 9. manifest.xml — must reference every entry above
        manifest_content = generate_omex_manifest(
            files=manifest_entries,
            sedml_location='simulation.sedml',
        )
        zf.writestr('manifest.xml', manifest_content)

    return archive_path


# =============================================================================
# Experiment-level parameter-scan archive (comparison across combinations)
# =============================================================================

def build_parameter_scan_repeated_task(scan_spec, base_task_id='task_main',
                                       model_id='model_angio'):
    """A SED-ML repeatedTask encoding the (flattened cartesian) parameter scan:
    one aligned vectorRange (length N) + setValue per swept parameter."""
    if not scan_spec:
        return None
    from itertools import product
    names = list(scan_spec.keys())
    combos = list(product(*[list(scan_spec[p]) for p in names]))
    rt = ET.Element('repeatedTask')
    rt.set('id', 'parameter_scan_task'); rt.set('resetModel', 'true')
    lor = ET.SubElement(rt, 'listOfRanges')
    loc = ET.SubElement(rt, 'listOfChanges')
    range_ids = []
    for i, p in enumerate(names):
        rid = _safe_sid(f"range_{p}")
        range_ids.append(rid)
        vr = ET.SubElement(lor, 'vectorRange'); vr.set('id', rid)
        for combo in combos:
            ET.SubElement(vr, 'value').text = str(combo[i])
        sv = ET.SubElement(loc, 'setValue')
        sv.set('modelReference', model_id); sv.set('range', rid); sv.set('target', p)
        ET.SubElement(ET.SubElement(sv, '{%s}math' % MATHML_NAMESPACE),
                      '{%s}ci' % MATHML_NAMESPACE).text = rid
    rt.set('range', range_ids[0])
    st = ET.SubElement(ET.SubElement(rt, 'listOfSubTasks'), 'subTask')
    st.set('task', base_task_id); st.set('order', '1')
    return rt


def generate_comparison_sedml_document(scan_spec, combo_info, run_name, sim_params,
                                       num_replicates=1):
    """Experiment-level SED-ML comparing combinations: scan repeatedTask + one
    dataDescription per combo (its replicate-mean metrics.csv) + per-(combo,metric)
    dataGenerators + one plot2D per metric (a curve per combo) + a report.
    combo_info entries: {safe, label, source, columns}."""
    for ns_prefix, ns in (('', SEDML_NAMESPACE), ('html', XHTML_NAMESPACE),
                          ('math', MATHML_NAMESPACE), ('numl', NUML_NAMESPACE)):
        ET.register_namespace(ns_prefix, ns)
    root = ET.Element('sedML')
    root.set('xmlns', SEDML_NAMESPACE); root.set('level', '1'); root.set('version', SEDML_VERSION_ATTR)
    sim_time = float(sim_params.get('sim_time', 100.0))
    scan_dims = "; ".join(f"{p} in {list(v)}" for p, v in scan_spec.items())
    n_points = len({c['safe'] for c in combo_info})

    body = ET.SubElement(ET.SubElement(root, 'notes'), '{%s}body' % XHTML_NAMESPACE)
    ET.SubElement(body, '{%s}h2' % XHTML_NAMESPACE).text = f"Angio parameter scan (comparison): {run_name}"
    for line in [
        f"Experiment-level COMPARISON of an angiogenesis parameter scan: {scan_dims}.",
        f"Combinations: {n_points}; replicates per point: {num_replicates}. Each combo's "
        "bundled combo_data/ CSV holds its replicate-MEAN metric series (time in MCS).",
        "plot2D outputs below place the combinations side by side, one curve per combo "
        f"per metric ({', '.join(ANGIO_METRIC_COLUMNS)}).",
    ]:
        ET.SubElement(body, '{%s}p' % XHTML_NAMESPACE).text = line

    model = ET.SubElement(ET.SubElement(root, 'listOfModels'), 'model')
    model.set('id', 'model_angio'); model.set('name', 'Angiogenesis Cellular Potts Model')
    model.set('source', 'model/model_summary.json'); model.set('language', MODEL_LANGUAGE_URI)
    sim = ET.SubElement(ET.SubElement(root, 'listOfSimulations'), 'uniformTimeCourse')
    sim.set('id', 'sim_mcs'); sim.set('initialTime', '0'); sim.set('outputStartTime', '0')
    sim.set('outputEndTime', str(sim_time)); sim.set('numberOfSteps', str(int(sim_time)))
    ET.SubElement(sim, 'algorithm').set('kisaoID', KISAO_ALGORITHM_ID)

    lot = ET.SubElement(root, 'listOfTasks')
    bt = ET.SubElement(lot, 'task'); bt.set('id', 'task_main')
    bt.set('modelReference', 'model_angio'); bt.set('simulationReference', 'sim_mcs')
    scan_task = build_parameter_scan_repeated_task(scan_spec)
    if scan_task is not None:
        lot.append(scan_task)

    lodd = ET.SubElement(root, 'listOfDataDescriptions')
    lodg = ET.SubElement(root, 'listOfDataGenerators')
    signal_curves = {}; signal_order = []; report_sets = []
    for c in combo_info:
        safe, src, cols = c['safe'], c['source'], c['columns']
        dd = ET.SubElement(lodd, 'dataDescription')
        dd.set('id', _safe_sid(f"data_{safe}")); dd.set('name', f"{c['label']} (replicate-mean)")
        dd.set('source', src); dd.set('format', 'urn:sedml:format:csv')
        dim = ET.SubElement(dd, 'dimensionDescription')
        outer = ET.SubElement(dim, '{%s}compositeDescription' % NUML_NAMESPACE)
        outer.set('indexType', 'integer'); outer.set('id', 'rowIdx'); outer.set('name', 'Row')
        inner = ET.SubElement(outer, '{%s}compositeDescription' % NUML_NAMESPACE)
        inner.set('indexType', 'string'); inner.set('id', 'columnIds'); inner.set('name', 'Column')
        at = ET.SubElement(inner, '{%s}atomicDescription' % NUML_NAMESPACE)
        at.set('valueType', 'double'); at.set('id', 'value'); at.set('name', 'Value')
        los = ET.SubElement(dd, 'listOfDataSources')
        time_dg = None
        for col in ['Time'] + cols:
            dsid = _safe_sid(f"ds_{safe}_{col}")
            dsrc = ET.SubElement(los, 'dataSource'); dsrc.set('id', dsid); dsrc.set('name', col)
            sl = ET.SubElement(ET.SubElement(dsrc, 'listOfSlices'), 'slice')
            sl.set('reference', 'columnIds'); sl.set('value', col)
            dgid = _safe_sid(f"dg_{safe}_{col}")
            dg = ET.SubElement(lodg, 'dataGenerator'); dg.set('id', dgid)
            dg.set('name', f"{c['label']} :: {col}")
            v = ET.SubElement(ET.SubElement(dg, 'listOfVariables'), 'variable')
            vid = _safe_sid(f"var_{safe}_{col}"); v.set('id', vid); v.set('target', f"#{dsid}")
            ET.SubElement(ET.SubElement(dg, '{%s}math' % MATHML_NAMESPACE),
                          '{%s}ci' % MATHML_NAMESPACE).text = vid
            if col == 'Time':
                time_dg = dgid
            else:
                if col not in signal_curves:
                    signal_curves[col] = []
                    signal_order.append(col)
                signal_curves[col].append((c['label'], time_dg, dgid))
                report_sets.append((c['label'], col, dgid))

    loo = ET.SubElement(root, 'listOfOutputs')
    for col in signal_order:
        plot = ET.SubElement(loo, 'plot2D'); plot.set('id', _safe_sid(f"plot_{col}"))
        plot.set('name', f"{col} across combinations")
        lc = ET.SubElement(plot, 'listOfCurves')
        for i, (label, tdg, vdg) in enumerate(signal_curves[col]):
            cur = ET.SubElement(lc, 'curve'); cur.set('id', _safe_sid(f"curve_{col}_{i}"))
            cur.set('logX', 'false'); cur.set('logY', 'false')
            cur.set('xDataReference', tdg); cur.set('yDataReference', vdg)
    report = ET.SubElement(loo, 'report'); report.set('id', 'report_comparison')
    report.set('name', f"Comparison across combinations: {run_name}")
    lod = ET.SubElement(report, 'listOfDataSets')
    for i, (label, col, dgid) in enumerate(report_sets):
        d = ET.SubElement(lod, 'dataSet'); d.set('id', _safe_sid(f"out_{i}_{col}"))
        d.set('label', f"{label} :: {col}"); d.set('dataReference', dgid)

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')


def run_outcome(run_dir) -> str:
    """'success' / 'failed' / 'timed_out' / 'cancelled' / 'unknown' for one run dir.

    The single test of whether a run's outputs may enter a result. A run that
    failed, timed out or was cancelled can still leave a partial data.zarr; its
    trajectory is evidence for diagnosis, never a replicate to average.
    Precedence: cancellation marker, the run's own run_metadata.json, then the
    status.json of its archive. A run with no record at all is 'unknown' and is
    treated as not successful.
    """
    run_dir = Path(run_dir)
    if (run_dir / 'cancelled.json').exists():
        return 'cancelled'
    try:
        meta = json.loads((run_dir / 'run_metadata.json').read_text())
    except Exception:
        meta = None
    if meta:
        if meta.get('simulation_status') in _ARCHIVE_STATUSES:
            return meta['simulation_status']
        success = (meta.get('execution') or {}).get('success')
        if success is not None:
            return 'success' if success else 'failed'
    archive = run_dir / f"{run_dir.name}.omex"
    try:
        with zipfile.ZipFile(archive) as zf:
            status = json.loads(zf.read('status.json')).get('status')
        if status in _ARCHIVE_STATUSES:
            return status
    except Exception:
        pass
    return 'unknown'


def _replicate_identity(run_dir, root=None):
    """Where a replicate lives and which realization it is, for scan_metadata."""
    run_dir = Path(run_dir)
    try:
        meta = json.loads((run_dir / 'run_metadata.json').read_text())
    except Exception:
        meta = {}
    params = meta.get('parameters') or {}
    location = str(run_dir)
    if root is not None:
        try:
            location = run_dir.relative_to(root).as_posix()
        except ValueError:
            pass
    archive = run_dir / f"{run_dir.name}.omex"
    return {
        'run_dir': location,
        'run_id': meta.get('run_id'),
        'random_seed': meta.get('random_seed', params.get('random_seed')),
        'archive': (f"{location}/{archive.name}" if archive.exists() else None),
    }


def split_replicates(replicate_dirs):
    """(successful dirs, [(dir, outcome)] for the rest), in input order."""
    ok, other = [], []
    for d in replicate_dirs or []:
        outcome = run_outcome(d)
        if outcome == 'success':
            ok.append(Path(d))
        else:
            other.append((Path(d), outcome))
    return ok, other


def _read_combo_metric_means(combinations):
    """For each combo, average the per-replicate metric series (extracted from each
    SUCCESSFUL replicate's data.zarr) on Time. combinations entries: {label, safe,
    replicate_dirs}. Returns [{safe,label,df(Time+metrics),included,excluded}];
    combos without a successful replicate are omitted. Needs pandas; empty if
    unavailable.

    Replicates that failed, timed out or were cancelled are excluded even when they
    left a data.zarr: averaging a truncated trajectory into a replicate mean would
    silently bias the series it is compared on.
    """
    try:
        import io
        import pandas as pd
    except Exception:
        return []
    out = []
    for combo in combinations or []:
        ok, excluded = split_replicates(combo.get('replicate_dirs', []))
        frames, included = [], []
        for rep_dir in ok:
            store = rep_dir / 'data.zarr'
            if not store.exists():
                excluded.append((rep_dir, 'no data.zarr'))
                continue
            csv = extract_zarr_metrics(store)
            if not csv:
                excluded.append((rep_dir, 'no metrics'))
                continue
            frames.append(pd.read_csv(io.StringIO(csv)).set_index('Time'))
            included.append(rep_dir)
        if not frames:
            continue
        mean = pd.concat(frames).groupby(level=0).mean(numeric_only=True).reset_index()
        out.append({'safe': _safe_sid(combo['label']), 'label': combo['label'], 'df': mean,
                    'included': included, 'excluded': excluded})
    return out


def create_experiment_scan_archive(batch_output_dir, scan_spec, combinations, sim_params,
                                   run_name=None, num_replicates=1, creator=None,
                                   license_uri="https://spdx.org/licenses/CC-BY-4.0.html",
                                   citation=ANGIO_CITATION, keywords=None):
    """Experiment-level OMEX at the batch root comparing the combinations. Bundles the
    comparison SED-ML (master), each combo's replicate-mean combo_data/<safe>.csv,
    a metadata.rdf, and scan_metadata.json. combinations entries:
    {label, replicate_dirs:[...], _index?}."""
    if not scan_spec:
        return None
    batch_output_dir = Path(batch_output_dir)
    run_name = run_name or batch_output_dir.name or 'angio_scan'
    omex_path = batch_output_dir / f"{run_name}_scan.omex"

    summaries = _read_combo_metric_means(combinations)
    data_files = {}
    if summaries:
        combo_info = []
        for s in summaries:
            src = f"combo_data/{s['safe']}.csv"
            data_files[src] = s['df'].to_csv(index=False)
            combo_info.append({'safe': s['safe'], 'label': s['label'], 'source': src,
                               'columns': [c for c in s['df'].columns if c != 'Time']})
        sedml = generate_comparison_sedml_document(scan_spec, combo_info, run_name,
                                                   sim_params, num_replicates)
    else:
        sedml = generate_comparison_sedml_document(scan_spec, [], run_name, sim_params, num_replicates)

    # Code identity of the tooling that assembled this experiment-level archive.
    # Only the code half is captured here: the schema fingerprint is a property of
    # a configured run, and lives in the per-point archives rather than being
    # re-derived (which would mean constructing a process, and so a simulation).
    # Imported defensively because this module is also loaded by file path, where
    # relative imports have no package context.
    try:
        try:
            from .provenance import code_provenance
        except ImportError:
            from provenance import code_provenance
        scan_provenance = {'code': code_provenance()}
    except Exception:
        scan_provenance = None

    # Per combination: which replicates the bundled mean series was computed from
    # (location, run_id, seed, archive) and which were left out, with why. The
    # scan archive previously recorded only a replicate count, so neither the
    # source runs of a mean nor the exclusion of a failed run was visible.
    by_label = {s['label']: s for s in summaries}
    combo_records = []
    for c in (combinations or []):
        s = by_label.get(c['label'])
        if s is not None:
            included, excluded = s['included'], s['excluded']
        else:
            included, excluded = [], split_replicates(c.get('replicate_dirs', []))[1]
        combo_records.append({
            'label': c['label'],
            'index': c.get('_index'),
            'replicates': len(c.get('replicate_dirs', [])),
            'replicates_in_mean': len(included),
            'mean_series': f"combo_data/{_safe_sid(c['label'])}.csv" if s is not None else None,
            'included': [_replicate_identity(d, batch_output_dir) for d in included],
            'excluded': [{**_replicate_identity(d, batch_output_dir), 'reason': why}
                         for d, why in excluded],
        })
    scan_metadata = {
        'run_name': run_name, 'created_at': datetime.now().isoformat(),
        'archive_type': 'experiment_scan', 'comparison': bool(summaries),
        'provenance': _provenance_block(scan_provenance),
        'parameter_scan': scan_spec, 'total_scan_points': len(combinations or []),
        'replicates_per_point': num_replicates,
        'metrics': ANGIO_METRIC_COLUMNS,
        'replicate_mean_policy': ('Mean series average only replicates whose run '
                                  'completed successfully; failed, timed-out and '
                                  'cancelled replicates are listed under "excluded".'),
        'combinations': combo_records,
    }
    cr = creator
    creators = ([cr] if isinstance(cr, dict) else [{'given': str(cr)}] if cr else [])
    metadata_rdf = generate_omex_metadata_rdf(
        title=f"Angiogenesis parameter scan: {run_name}",
        description=(f"Experiment-level COMBINE archive comparing {len(combinations or [])} "
                     f"combinations of an angio scan ({'; '.join(f'{k} in {list(v)}' for k, v in scan_spec.items())})."),
        created=scan_metadata['created_at'], modified=scan_metadata['created_at'],
        creators=creators, license_uri=license_uri, citation=citation,
        keywords=keywords or ['angiogenesis', 'parameter scan', 'cellular Potts model', 'VEGF'],
        provenance=scan_provenance)

    # The comparison SED-ML sets model/@source = 'model/model_summary.json'
    # (see generate_comparison_sedml_document). Bundle that file so the @source
    # resolves to a real archive entry instead of dangling — mirroring the per-run
    # archive, whose @source resolves to bundled model content. We bundle the
    # descriptive summary here (the experiment-level archive compares combinations
    # and intentionally does not embed per-run model source); the per-run archives
    # at each scan point carry the re-runnable model artifact.
    model_summary = generate_model_summary(
        {'model_name': 'Angiogenesis', 'schema_version': '1.0',
         'provenance': scan_provenance}, sim_params)

    with zipfile.ZipFile(omex_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('scan.sedml', sedml)
        zf.writestr('metadata.rdf', metadata_rdf)
        zf.writestr('scan_metadata.json', json.dumps(scan_metadata, indent=2, default=str))
        zf.writestr('model/model_summary.json', model_summary)
        entries = [{'location': 'scan.sedml', 'format': FORMAT_URIS['.sedml']},
                   {'location': 'metadata.rdf', 'format': OMEX_METADATA_FORMAT},
                   {'location': 'scan_metadata.json', 'format': FORMAT_URIS['.json']},
                   {'location': 'model/model_summary.json', 'format': FORMAT_URIS['.json']}]
        for src, text in data_files.items():
            zf.writestr(src, text); entries.append({'location': src, 'format': FORMAT_URIS['.csv']})
        zf.writestr('manifest.xml', generate_omex_manifest(entries, sedml_location='scan.sedml'))
    return omex_path


# =============================================================================
# Validators (structural only — parallel to vivarium-vcornea)
# =============================================================================

def validate_sedml_structure(sedml_content: str) -> Dict[str, Any]:
    """Lightweight structural check of a SED-ML document."""
    errors = []
    try:
        root = ET.fromstring(sedml_content)
    except ET.ParseError as e:
        return {'valid': False, 'errors': [f'XML parse error: {e}']}

    if not root.tag.endswith('sedML'):
        errors.append(f"Root element should be 'sedML', got '{root.tag}'")
    if root.get('level') != '1':
        errors.append("Missing or incorrect 'level' attribute (should be '1')")
    if root.get('version') != SEDML_VERSION_ATTR:
        errors.append(
            f"Missing or incorrect 'version' attribute (should be '{SEDML_VERSION_ATTR}')"
        )

    expected_sections = [
        'listOfModels', 'listOfSimulations', 'listOfTasks',
        'listOfDataGenerators', 'listOfOutputs',
    ]
    present = {child.tag.split('}', 1)[-1] for child in root}
    for section in expected_sections:
        if section not in present:
            errors.append(f"Missing expected section: {section}")

    return {'valid': len(errors) == 0, 'errors': errors}


def validate_omex_manifest(manifest_content: str, archive_files: List[str]) -> Dict[str, Any]:
    """Lightweight structural check of an OMEX manifest.

    Verifies the manifest parses, has a master entry, and that every
    manifest <content> location actually exists in `archive_files`.
    """
    errors = []
    try:
        root = ET.fromstring(manifest_content)
    except ET.ParseError as e:
        return {'valid': False, 'errors': [f'XML parse error: {e}']}

    manifest_locations = set()
    has_master = False
    has_sedml = False
    for content in root.findall('.//{%s}content' % OMEX_MANIFEST_NAMESPACE):
        location = content.get('location')
        if location and location != '.':
            manifest_locations.add(location)
        if location and location.endswith('.sedml'):
            has_sedml = True
        if content.get('master') == 'true':
            has_master = True

    # A master entry is required only when the archive carries an executable
    # SED-ML document. A failed-run archive deliberately omits the SED-ML (so a
    # consumer cannot mistake it for a reproducible success) and therefore has no
    # master — that is valid, not an error.
    if has_sedml and not has_master:
        errors.append("Manifest has no master entry")

    archive_set = set(archive_files)
    missing = manifest_locations - archive_set
    if missing:
        errors.append(f"Manifest references files not in archive: {sorted(missing)[:5]}")

    return {'valid': len(errors) == 0, 'errors': errors}
