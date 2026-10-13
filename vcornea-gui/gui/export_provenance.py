"""Provenance for exported figures, tables and animations (requirement 2.5.2).

Every artifact the analysis view exports keeps a reference to the run(s) it was
derived from: run directory, run_id, seed, schema fingerprint, code revision and
archive. The record is written as a `<file>.provenance.json` sidecar next to the
export and, for PNG / PDF / SVG figures, also embedded in the image metadata, so
a figure that travels without its sidecar still names its source runs.

attach_to_figure() wraps a figure's savefig, so the export buttons and the
matplotlib toolbar's save button are covered by the same path.

(The Angio GUI carries an identical copy of this module.)
"""
import json
from datetime import datetime
from pathlib import Path

SIDECAR_SUFFIX = '.provenance.json'

# Image formats whose matplotlib writer accepts a free-text metadata field.
_METADATA_KEY = {'png': 'Description', 'pdf': 'Subject', 'svg': 'Description'}


def run_record(run_dir):
    """Identity of one source run, read from its run_metadata.json."""
    run_dir = Path(run_dir)
    record = {'run_dir': str(run_dir)}
    try:
        meta = json.loads((run_dir / 'run_metadata.json').read_text())
    except Exception:
        record['note'] = 'run_metadata.json not found or unreadable'
        return record
    prov = meta.get('provenance') or {}
    code = prov.get('code') or {}
    params = meta.get('parameters') or {}
    archive = meta.get('omex_archive') or next((p.name for p in run_dir.glob('*.omex')), None)
    record.update({
        'run_id': meta.get('run_id'),
        'run_name': meta.get('run_name') or meta.get('experiment_name'),
        'status': meta.get('simulation_status'),
        'random_seed': meta.get('random_seed', params.get('random_seed')),
        'random_seed_origin': meta.get('random_seed_origin') or params.get('random_seed_origin'),
        'schema_fingerprint': (meta.get('schema_fingerprint') or prov.get('schema_fingerprint')
                               or params.get('_schema_fingerprint')),
        'code': ({k: code.get(k) for k in ('source', 'commit', 'describe', 'dirty')}
                 if code else None),
        'archive': archive,
    })
    return record


def build_record(run_dirs, application, view=None):
    """Provenance record for one export derived from `run_dirs`."""
    unique = sorted({str(Path(d)) for d in run_dirs})
    return {
        'exported_at': datetime.now().isoformat(timespec='seconds'),
        'application': application,
        'view': view or {},
        'source_runs': [run_record(d) for d in unique],
    }


def write_sidecar(export_path, record):
    path = Path(str(export_path) + SIDECAR_SUFFIX)
    path.write_text(json.dumps(record, indent=2, default=str))
    return path


def attach_to_figure(figure, provider):
    """Make every figure.savefig() embed and sidecar the provenance `provider()`
    returns (None = nothing to record, e.g. no run loaded)."""
    original = figure.savefig

    def savefig(fname, *args, **kwargs):
        record = None
        if isinstance(fname, (str, Path)):
            try:
                record = provider()
            except Exception as e:  # provenance must never block an export
                print(f"Warning: could not build export provenance: {e}")
        if record is not None:
            fmt = (kwargs.get('format') or Path(fname).suffix.lstrip('.') or 'png').lower()
            key = _METADATA_KEY.get(fmt)
            if key:
                kwargs['metadata'] = {**(kwargs.get('metadata') or {}),
                                      key: json.dumps(record, default=str)}
        result = original(fname, *args, **kwargs)
        if record is not None:
            write_sidecar(fname, record)
        return result

    figure.savefig = savefig
    return figure
